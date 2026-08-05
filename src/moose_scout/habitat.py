"""Stage 3 — Moose Habitat Suitability Model (HSM).

Weighted overlay on the canonical grid. North of the écoforestière limit the
vegetation signal comes from Sentinel-2 NDVI (browse/cover proxy) rather than
stand polygons. Robust to missing layers — uses what acquisition produced.

Outputs (cache/<aoi>/):
  hsm.tif             0..1 suitability
  hsm_thermal.tif     thermal-refuge score ("climatiseur à orignaux")
  hsm_rut.tif         rut/calling-site score (edge × funnel × wetland)
  dist_water.tif      metres to nearest water (for extraction + reporting)
"""
from __future__ import annotations

import numpy as np

from .config import Context, cache_dir
from . import rasterio_utils as ru


def _opt(path):
    try:
        return ru.read(path)[0]
    except Exception:
        return None


def _dist(mask_bool, res):
    from scipy.ndimage import distance_transform_edt

    if mask_bool.any():
        return distance_transform_edt(~mask_bool) * res
    return np.full(mask_bool.shape, 1e6, dtype="float32")


def _prox(dist, optimal_m, falloff_m):
    """1.0 within optimal, decaying to 0 by optimal+falloff."""
    out = np.ones_like(dist, dtype="float32")
    far = dist > optimal_m
    out[far] = np.clip(1 - (dist[far] - optimal_m) / max(falloff_m, 1), 0, 1)
    return out


def run(ctx: Context) -> None:
    from scipy.ndimage import generic_filter, uniform_filter

    aoi = ctx.aoi.name
    cache = cache_dir(aoi)
    tdir = cache / "terrain"
    res = ctx.model.raster_resolution_m
    sp = ctx.species
    W = sp.water or {}

    _, prof = ru.read(tdir / "slope.tif")
    slope = _opt(tdir / "slope.tif")
    tpi = _opt(tdir / "tpi.tif")
    wet = _opt(tdir / "wet.tif")
    funnel = _opt(tdir / "funnel.tif")
    cool = _opt(tdir / "coolaspect.tif")
    ndvi = _opt(cache / "ndvi.tif")
    water = _opt(cache / "water.tif")
    wetland = _opt(cache / "wetland.tif")
    shape = slope.shape

    # --- water: prefer OSM raster; fall back to very-low NDVI as water ---
    if water is not None:
        water_mask = water > 0
    elif ndvi is not None:
        water_mask = ndvi < 0.0
    else:
        water_mask = np.zeros(shape, bool)
    wetland_mask = (wetland > 0) if wetland is not None else np.zeros(shape, bool)

    dist_water = _dist(water_mask | wetland_mask, res)
    ru.write(cache / "dist_water.tif", dist_water.astype("float32"), prof)

    # --- browse / cover / edge from WorldCover classes, refined by NDVI ---
    #   browse: shrub/grass/wetland/regen high, conifer low
    #   cover:  mature tree high
    #   edge:   tree <-> opening interface (moose feed at the seam)
    lc = _opt(cache / "landcover.tif")
    BROWSE_LC = {20: 1.0, 30: 0.7, 90: 0.6, 100: 0.3, 40: 0.5, 10: 0.2, 60: 0.05, 80: 0.0}
    COVER_LC = {10: 0.9, 20: 0.35, 90: 0.15}
    edge = np.full(shape, 0.3, dtype="float32")
    # NATIVE-RESOLUTION CLASS FRACTIONS (#77/#78), when acquire measured them. Land
    # cover is 10 m and this grid is typically 40 m; the categorical map records the
    # winner of a 16-way vote, the fractions record the actual mixture. Interspersion is
    # the model's dominant term, so the mixture is the signal — not a nicety.
    FRAC_NAME = {10: "tree", 20: "shrub", 30: "grass", 40: "crop",
                 60: "bare", 80: "water", 90: "wetland", 100: "moss"}
    fr = {}
    for code, nm in FRAC_NAME.items():
        a = _opt(cache / f"lcfrac_{nm}.tif")
        if a is not None:
            fr[code] = np.nan_to_num(a, nan=0.0)
    have_frac = len(fr) >= 4

    if have_frac:
        # Fraction-weighted mixtures: a cell that is 60 % regen shrub and 40 % conifer
        # now scores as both, instead of as whichever class won the vote.
        browse_lc = np.zeros(shape, "float32")
        cover_lc = np.zeros(shape, "float32")
        for k, v in BROWSE_LC.items():
            if k in fr:
                browse_lc += v * fr[k]
        for k, v in COVER_LC.items():
            if k in fr:
                cover_lc += v * fr[k]
        browse_lc = np.clip(browse_lc, 0, 1)
        cover_lc = np.clip(cover_lc, 0, 1)
        p_tree = np.clip(fr.get(10, np.zeros(shape, "float32")), 0, 1)
        # TWO scales of interspersion, and they are different things:
        #   sub-cell — this 40 m cell is itself part tree, part opening: a seam we could
        #              not see at all before, and the tightest edge a moose actually uses;
        #   neighbourhood — the ~200 m mosaic the old code approximated from binary cells,
        #              now averaged from real fractions instead of 0/1 votes.
        sub = np.clip(4 * p_tree * (1 - p_tree), 0.0, 1.0)
        nbr_p = uniform_filter(p_tree, size=max(3, int(round(200 / res)) | 1))
        nbr = np.clip(4 * nbr_p * (1 - nbr_p), 0.0, 1.0)
        edge = np.clip(np.maximum(nbr, 0.85 * sub), 0.0, 1.0)
        print(f"[habitat] edge from NATIVE 10 m fractions "
              f"(sub-cell mean {float(np.nanmean(sub)):.3f}, neighbourhood {float(np.nanmean(nbr)):.3f})")
    elif lc is not None:
        browse_lc = np.zeros(shape, "float32")
        cover_lc = np.zeros(shape, "float32")
        for k, v in BROWSE_LC.items():
            browse_lc[lc == k] = v
        for k, v in COVER_LC.items():
            cover_lc[lc == k] = v
        tree = (lc == 10).astype("float32")
        p = uniform_filter(tree, size=max(3, int(round(200 / res)) | 1))
        edge = np.clip(4 * p * (1 - p), 0.0, 1.0)         # interspersion, ABSOLUTE (peaks 50/50)
    else:
        browse_lc = cover_lc = None

    if ndvi is not None:
        n = np.clip(ndvi, -0.2, 0.9)
        browse_n = np.clip((n - 0.15) / 0.5, 0, 1) * np.clip(1 - (n - 0.8) / 0.15, 0, 1)
        cover_n = np.clip((n - 0.5) / 0.4, 0, 1)
    else:
        browse_n = cover_n = None

    if browse_lc is not None and browse_n is not None:
        # NDVI REFINES land-cover, and now may be NaN where no Sentinel scene covered a
        # cell (a coverage gap — previously a fake 0 that read as barren and striped the
        # map). Where NDVI is present, blend; where it's absent, fall back to land-cover
        # alone rather than letting a NaN poison the blend and delete the cell.
        have_n = np.isfinite(browse_n)
        browse = np.where(have_n, 0.6 * browse_lc + 0.4 * np.nan_to_num(browse_n), browse_lc)
        have_c = np.isfinite(cover_n)
        cover = np.where(have_c, 0.6 * cover_lc + 0.4 * np.nan_to_num(cover_n), cover_lc)
    elif browse_lc is not None:
        browse, cover = browse_lc, cover_lc
    elif browse_n is not None:
        browse, cover = browse_n, cover_n
        edge = ru.normalize(uniform_filter((n - uniform_filter(n, 5)) ** 2, 5))
    else:
        browse = wet.copy()
        cover = np.full(shape, 0.4, dtype="float32")

    # --- DISTURBANCE AGE: the strongest boreal browse predictor we have ----------
    # Post-fire browse follows a well-established curve — use is low in very young
    # burns (browse below reachable height, no security cover) despite high biomass,
    # peaks ~15–22 yr, then falls away as the canopy closes. Locally validated: the
    # zone-19 aerial inventory found old burns correlate with moose numbers at
    # r = 0.62, p < 0.01. Where a burn is mapped, it OVERRIDES the coarse land-cover
    # browse guess, because a 15-yr burn is prime browse whatever WorldCover calls it.
    burn = _opt(cache / "burn_year.tif")
    burn_age = None
    if burn is not None and np.any(burn > 0):
        age = float(ctx.aoi.season.year) - burn
        pts = [(0, 0.05), (5, 0.05), (9, 0.35), (14, 0.85), (18, 1.00),
               (22, 1.00), (27, 0.80), (35, 0.45), (60, 0.15), (200, 0.10)]
        dist_val = np.interp(np.clip(np.nan_to_num(age), 0, 200),
                             [p[0] for p in pts], [p[1] for p in pts]).astype("float32")
        # burn_year nodata is 0 → ru.read turns it to NaN, so `burn > 0` is False AND
        # `burn <= 0` is False on never-burned cells. The old `dist_val[burn<=0]=0` missed
        # them, leaving dist_val NaN there, and np.maximum(browse, NaN) then propagated NaN
        # and ZEROED browse across all never-burned ground (i.e. most of any AOI that has
        # burns). Force the disturbance signal to 0 wherever there is no real burn year.
        dist_val = np.where(np.isfinite(burn) & (burn > 0), dist_val, 0.0).astype("float32")
        burn_age = np.where(np.isfinite(burn) & (burn > 0), age, np.nan).astype("float32")
        browse = np.maximum(np.nan_to_num(browse), np.nan_to_num(dist_val))
        ru.write(cache / "burn_browse.tif", dist_val, prof)

    # --- ÉCOFORESTIÈRE OVERRIDE (south of ~52°N) --------------------------------------
    # Real stand species + canopy closure + dated CUTS beat the 10 m WorldCover guess.
    # Where a stand is mapped it is authoritative for cover/browse; WorldCover+NDVI fills
    # the rest (north of the limit, or gaps). This is what finally lets the model see
    # CONIFER (not "any tree") and count logging cuts as browse by age (#34).
    stand = _opt(cache / "stand_type.tif")
    conifer_close = None
    if stand is not None:
        st = np.nan_to_num(stand).astype("int16")
        have = st > 0
        cl = np.clip(np.nan_to_num(_opt(cache / "stand_closure.tif")), 0.0, 1.0)
        # species → cover / browse (from config/species/moose.yaml cover_types), 0..1
        SP_COVER = {1: 0.85, 2: 0.55, 3: 0.25, 4: 0.05, 5: 0.20, 6: 0.10}   # rés·mél·feu·cut·regen·burn
        SP_BROWSE = {1: 0.05, 2: 0.35, 3: 0.30, 4: 0.55, 5: 0.85, 6: 0.30}
        eco_cover = np.zeros(shape, "float32")
        eco_browse = np.zeros(shape, "float32")
        for k, v in SP_COVER.items():
            eco_cover[st == k] = v
        for k, v in SP_BROWSE.items():
            eco_browse[st == k] = v
        eco_cover = np.clip(eco_cover * (0.5 + 0.5 * cl), 0.0, 1.0)          # scale cover by closure
        cover = np.where(have, eco_cover, np.nan_to_num(cover))
        browse = np.where(have, np.maximum(np.nan_to_num(browse), eco_browse), np.nan_to_num(browse))
        # conifer canopy closure (résineux/mélangé) — the real thermal-refuge signal
        conifer_close = np.where(np.isin(st, [1, 2]), cl, 0.0).astype("float32")
        # dated CUTS through the same disturbance-age browse curve as burns (#34)
        cut_yr = _opt(cache / "cut_year.tif")
        if cut_yr is not None and np.any(np.nan_to_num(cut_yr) > 0):
            cyr = np.nan_to_num(cut_yr)
            cage = float(ctx.aoi.season.year) - cyr
            cpts = [(0, 0.05), (4, 0.15), (8, 0.55), (12, 0.95), (18, 1.00),
                    (25, 0.85), (32, 0.50), (45, 0.30), (80, 0.15)]   # cuts sucker earlier than fire
            cdist = np.interp(np.clip(cage, 0, 200),
                              [p[0] for p in cpts], [p[1] for p in cpts]).astype("float32")
            cdist = np.where(cyr > 0, cdist, 0.0)
            browse = np.maximum(np.nan_to_num(browse), cdist)

    # --- water/forage proximity ---
    water_score = _prox(dist_water, W.get("wetland_optimal_m", 150), W.get("wetland_falloff_m", 800))

    # --- terrain: valley bottoms, wet flats, gentle ground (fixed bounds) ---
    terr = ru.normalize(-tpi, lo=-5.0, hi=15.0) * 0.5 + np.clip(np.nan_to_num(wet), 0, 1) * 0.3 \
        + ru.normalize(slope, lo=0.0, hi=15.0, invert=True) * 0.2
    steep = slope > sp.terrain.get("avoid_steep_slope_deg", 25)

    # ABSOLUTE SCALE. The weights sum to 1 and every component is already on a real
    # 0..1 scale, so the weighted sum is natively 0..1 — it needs a clip, NOT another
    # percentile stretch. Re-ranking here is what made "huntability 0.85" mean only
    # "top of whatever box you happened to draw"; now it means the same thing in
    # every AOI, which is also the precondition for validating the model at all.
    wts = sp.hsm_weights
    hsm = (wts.get("browse", .35) * np.nan_to_num(browse)
           + wts.get("cover", .2) * np.nan_to_num(cover)
           + wts.get("water", .25) * np.nan_to_num(water_score)
           + wts.get("terrain", .1) * np.nan_to_num(terr)
           + wts.get("edge_density", .1) * np.nan_to_num(edge))
    hsm = np.clip(hsm, 0, 1)
    hsm[steep] = hsm[steep] * 0.3     # discount steep ground (before masking)
    hsm[water_mask] = np.nan          # can't hunt open water
    ru.write(cache / "hsm.tif", hsm.astype("float32"), prof)

    # Persist the sub-scores so the behavioral stage (behavior.py) can build
    # time/temperature occupancy surfaces without recomputing the veg model.
    # These are already 0..1 — clip, don't re-stretch.
    for nm, arr in (("browse", browse), ("cover", cover), ("edge", edge)):
        a = np.clip(np.nan_to_num(arr), 0, 1)
        a[water_mask] = np.nan
        ru.write(cache / f"{nm}.tif", a.astype("float32"), prof)

    # --- SEX-SPECIFIC HABITAT (matters at the rut) --------------------------------
    # Outside the rut the sexes segregate: bulls maximize forage intake and select
    # open regen/cutblocks, while cows-with-calves minimize predation risk and stay
    # tight to security cover — trail-camera detection of cows-with-calves runs 0.24
    # in cuts <10 yr old vs 0.83 at 11–25 yr vs 0.94 in undisturbed stands (Thomas
    # 2025), a ~4x effect. DURING the rut the sexes aggregate and bulls adopt cow
    # habitat: mature bulls stop feeding entirely around 18–20 Sep (Miquelle 1990),
    # so they are no longer in feeding habitat at all — they are where the cows are.
    # access.py blends between these two surfaces by rut phase.
    # The discriminating variable is the OPENNESS OF THE SURROUNDING MATRIX, not
    # distance-to-cover: in this landscape 65% of pixels are closed canopy, so
    # distance-to-cover is ~0 almost everywhere and would make the two surfaces
    # monotone transforms of browse (i.e. identical after ranking). Neighbourhood
    # tree fraction varies continuously and separates "small opening inside timber"
    # (cow ground) from "big open cutblock/burn interior" (bull ground).
    cover_mask = (np.nan_to_num(cover) > 0.5).astype("float32")
    win = max(3, int(round(400 / res)) | 1)          # ~400 m matrix context
    treefrac = uniform_filter(cover_mask, size=win)  # 1 = closed matrix, 0 = wide open
    br0 = np.nan_to_num(browse)
    # cows-with-calves: forage, but only where the matrix still offers escape cover.
    # Trail-camera detection of cows-with-calves: 0.24 in cuts <10 yr vs 0.94 in
    # undisturbed stands (Thomas 2025) — they will not use big open ground.
    cow = br0 * (0.15 + 0.85 * treefrac)
    cow[water_mask] = np.nan
    # ABSOLUTE (clip, NOT normalize): browse × matrix-cover is already a real 0..1 score.
    # ru.normalize() here re-ranked it per-AOI, which leaked back into hsm_phase → the
    # "0.85 = top of whatever box you drew" bug (audit #49). Same for bull below.
    ru.write(cache / "hsm_cow.tif", np.clip(np.nan_to_num(cow), 0, 1).astype("float32"), prof)
    # bulls (outside the rut): forage-maximizing, select open regen/cutblocks
    bull = br0 * (0.30 + 0.70 * (1.0 - treefrac))
    bull[water_mask] = np.nan
    ru.write(cache / "hsm_bull.tif", np.clip(np.nan_to_num(bull), 0, 1).astype("float32"), prof)

    # --- thermal refuge: dense cover made usable by a cool microsite --------------
    # Dense canopy is NECESSARY (ramp 0.60→0.85 so open/regen ground contributes 0). It
    # becomes a midday retreat via EITHER of two cool-microsite pathways, whichever is
    # stronger (accuracy audit #54):
    #   (a) WET/LOWLAND — proximity to water/wetland OR a valley-bottom flat. Wet substrate
    #       and standing water are the strongest cooling mechanism, stronger than canopy
    #       (McCann 2013, van Beest 2012, Thompson 2021); this is what makes flat cedar /
    #       black-spruce swamp a refuge — exactly what an aspect-only rule deletes.
    #   (b) COOL ASPECT — a N/NE face, slope-gated (aspect is noise on flat ground).
    # Aspect is NO LONGER the sole gate (Mumma 2020: no north-slope selection; canopy
    # dominates), so flats are eligible through (a). Absolute scale, NO normalize, so the
    # downstream 0.5 threshold stays portable across AOIs.
    cover0 = np.nan_to_num(cover)
    # Where écoforestière maps it, `dense` is REAL conifer canopy closure (résineux/
    # mélangé × density class) — the true thermal-refuge cover. Elsewhere (north of the
    # limit, or gaps) fall back to the coarse WorldCover "any tree above 0.60" proxy,
    # which over-counts because it can't see species or closure.
    dense = np.clip((cover0 - 0.60) / 0.25, 0.0, 1.0)
    if conifer_close is not None:
        cc = np.nan_to_num(conifer_close)
        dense = np.where(cc > 0, np.clip((cc - 0.45) / 0.35, 0.0, 1.0), dense)
    lowland = np.clip(ru.normalize(-tpi, lo=0.0, hi=15.0), 0.0, 1.0)    # fixed bounds → absolute
    wet_cool = np.maximum(_prox(dist_water, 100, 350), 0.7 * lowland)
    slope_gate = np.clip(np.nan_to_num(slope) / 8.0, 0.0, 1.0)
    aspect_cool = np.clip((np.nan_to_num(cool) - 0.50) / 0.40, 0.0, 1.0) * slope_gate
    enhance = np.maximum(wet_cool, aspect_cool)
    thermal = (dense * (0.12 + 0.88 * enhance)).astype("float32")
    thermal[water_mask] = np.nan
    ru.write(cache / "hsm_thermal.tif", thermal, prof)

    # --- rut/calling sites (accuracy audit #55) -----------------------------------
    # A bull cruises and calls the SECURITY-COVER↔OPENING seam — not any 50/50 tree mix.
    # The global `edge` above is a single-class tree/not-tree interspersion, which can't
    # tell a cover-to-regen seam from a hardwood/conifer ecotone, so here we build a
    # structural seam from the cover and browse surfaces: a cell scores where dense cover
    # AND low open browse both occur within ~150 m (the callable lip). Three independent
    # contributors soft-combine on an ABSOLUTE scale (no final normalize):
    #   • the cover↔opening seam (primary — where bulls cruise/call),
    #   • funnels/travel corridors (a good neck is a stand even off a perfect edge),
    #   • WALLOWS (wet ground within/beside cover) — the strongest rut attractant, and
    #     entirely absent before this.
    from scipy.ndimage import uniform_filter as _uf
    cov = np.nan_to_num(cover); brw = np.nan_to_num(browse)
    win_e = max(3, int(round(150 / res)) | 1)
    cov_near = _uf((cov > 0.55).astype("float32"), size=win_e)
    open_near = _uf((brw > 0.45).astype("float32"), size=win_e)
    rut_edge = np.clip(4.0 * cov_near * open_near, 0.0, 1.0)          # both present = a seam
    win_w = max(3, int(round(120 / res)) | 1)
    cover_adj = _uf((cov > 0.55).astype("float32"), size=win_w)
    wallow = np.clip(np.nan_to_num(wet), 0.0, 1.0) * cover_adj        # wet depression beside cover
    funnel_abs = np.clip(np.nan_to_num(funnel), 0.0, 1.0)            # already absolute from terrain
    wet_prox = _prox(_dist(wetland_mask | water_mask, res), 200, 1000)
    # BEAVER PONDS (GRHQ Mare, #62): a fresh flowage is a rut HUB — bulls scent-mark its wet
    # edge and cows are drawn to it — strongest where it sits BESIDE security cover (the
    # classic flowage-edge stand). NOT fall aquatic forage (decayed out by the hunt); this is
    # a rut/wallow attractant, so it rides here with the wallow term, never in the food blend.
    pond = _opt(cache / "beaver_pond.tif")
    pond_hub = np.zeros(shape, "float32")
    if pond is not None and pond.shape == shape:
        pond_prox = _prox(_dist(np.nan_to_num(pond) > 0, res), 150, 600)
        pond_hub = np.clip(pond_prox * (0.4 + 0.6 * cover_adj), 0.0, 1.0)
    rut = np.clip(0.55 * rut_edge * (0.5 + 0.5 * wet_prox)
                  + 0.30 * funnel_abs
                  + 0.35 * wallow
                  + 0.30 * pond_hub, 0.0, 1.0)
    rut[water_mask] = np.nan
    ru.write(cache / "hsm_rut.tif", rut.astype("float32"), prof)
