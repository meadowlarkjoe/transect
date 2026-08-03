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
    if lc is not None:
        browse_lc = np.zeros(shape, "float32")
        cover_lc = np.zeros(shape, "float32")
        for k, v in BROWSE_LC.items():
            browse_lc[lc == k] = v
        for k, v in COVER_LC.items():
            cover_lc[lc == k] = v
        tree = (lc == 10).astype("float32")
        p = uniform_filter(tree, size=max(3, int(round(200 / res)) | 1))
        edge = ru.normalize(4 * p * (1 - p))              # peaks at 50/50 tree:open
    else:
        browse_lc = cover_lc = None

    if ndvi is not None:
        n = np.clip(ndvi, -0.2, 0.9)
        browse_n = np.clip((n - 0.15) / 0.5, 0, 1) * np.clip(1 - (n - 0.8) / 0.15, 0, 1)
        cover_n = np.clip((n - 0.5) / 0.4, 0, 1)
    else:
        browse_n = cover_n = None

    if browse_lc is not None and browse_n is not None:
        browse = 0.6 * browse_lc + 0.4 * browse_n
        cover = 0.6 * cover_lc + 0.4 * cover_n
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
        dist_val = np.interp(np.clip(age, 0, 200),
                             [p[0] for p in pts], [p[1] for p in pts]).astype("float32")
        dist_val[burn <= 0] = 0.0            # never-burned → no disturbance signal
        burn_age = np.where(burn > 0, age, np.nan).astype("float32")
        browse = np.maximum(np.nan_to_num(browse), dist_val)
        ru.write(cache / "burn_browse.tif", dist_val, prof)

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
    ru.write(cache / "hsm_cow.tif", ru.normalize(cow).astype("float32"), prof)
    # bulls (outside the rut): forage-maximizing, select open regen/cutblocks
    bull = br0 * (0.30 + 0.70 * (1.0 - treefrac))
    bull[water_mask] = np.nan
    ru.write(cache / "hsm_bull.tif", ru.normalize(bull).astype("float32"), prof)

    # --- thermal refuge: cool aspect + cover + near water ---
    thermal = np.nan_to_num(cool) * np.nan_to_num(cover) * _prox(dist_water, 100, 400)
    thermal[water_mask] = np.nan
    ru.write(cache / "hsm_thermal.tif", ru.normalize(thermal).astype("float32"), prof)

    # --- rut/calling sites: cover<->opening edge × funnel × near wetland ---
    wet_prox = _prox(_dist(wetland_mask | water_mask, res), 200, 1000)
    rut = np.nan_to_num(edge) * (0.5 + 0.5 * ru.normalize(funnel)) * wet_prox
    rut[water_mask] = np.nan
    ru.write(cache / "hsm_rut.tif", ru.normalize(rut).astype("float32"), prof)
