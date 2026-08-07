"""Stage 5/6 — focus areas + annotated features (Les-Cartes-Xperts vocabulary).

From the huntability surface, extract ranked FOCUS AREAS, then place typed
features that speak Charles Dorris's legend (config/output_legend.yaml):
  rut_calling · thermal_refuge · saline_blind · validate_ground · funnel ·
  glassing · base_camp · parking, plus least-cost approach ROUTES.

Writes cache/<aoi>/focus_areas.geojson, cache/<aoi>/features.geojson,
outputs/<aoi>/brief.md.
"""
from __future__ import annotations

import os

import json

import numpy as np

from .config import Context, cache_dir, outputs_dir
from . import rasterio_utils as ru
from . import scent as _scent


def _to_lonlat(prof):
    """Return a function mapping (row, col) -> (lon, lat)."""
    from pyproj import Transformer

    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    T = prof["transform"]

    def f(rc):
        r, c = rc
        x, y = T * (c + 0.5, r + 0.5)
        lon, lat = tr.transform(x, y)
        return float(lon), float(lat)

    return f


def _peaks(arr, n, min_dist_px):
    from skimage.feature import peak_local_max

    a = np.where(np.isfinite(arr), arr, 0)
    # exclude_border=False: the default excludes a border of width=min_distance, which
    # on smaller AOIs drops every peak (synth already crops its own 2 km border).
    pk = peak_local_max(a, num_peaks=n, min_distance=min_dist_px, threshold_rel=0.4,
                        exclude_border=False)
    return [tuple(p) for p in pk]


def extract_focus_areas(ctx, hunt, prof):
    from rasterio.features import shapes as rio_shapes
    from scipy.ndimage import (binary_closing, binary_fill_holes,
                               gaussian_filter, label as ndlabel)
    from skimage.feature import peak_local_max
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform, unary_union
    from pyproj import Transformer

    res = ctx.model.raster_resolution_m
    fcfg = ctx.model.focus_areas or {}
    # NO COUNT CAP. Ground either clears the quality bar or it doesn't; how many
    # pieces of it happen to clear is a finding, not a setting. A fixed count meant
    # a 36 km box and a 240 km box both returned five areas, which reads as "there
    # are only five spots here" when it actually meant "we stopped looking at five".
    # The gate is: top quartile of the smoothed surface, >=30% of the AOI maximum,
    # >=8 km from the next candidate, and >= min_area_km2 of contiguous ground.
    NO_CAP = 100000
    px_area = (res * res) / 1e6  # km2/pixel
    min_km2 = fcfg.get("min_area_km2", 3)
    max_km2 = fcfg.get("max_area_km2", 60)
    # PARTY SIZE SHAPES THE GROUND, not just the label. Two callers working the same
    # 8 km2 lobe are hunting each other's bull: a moose call carries roughly a
    # kilometre, so each setup needs its own envelope. Grow the focus area with the
    # crew so there is somewhere to actually put them, and grow the floor too so we
    # don't hand a six-man party a 3 km2 pocket.
    party = int(getattr(ctx.aoi.hunter, "party_size", 2) or 2)
    crew_scale = min(3.0, max(1.0, party / 2.0))
    # Party size adds MORE focus areas (the count is uncapped, gated on quality), it does
    # NOT inflate one polygon into a 180 km² blob a party could never work (audit #50).
    # The floor grows modestly so a big crew isn't handed a 3 km² pocket.
    min_km2 = min_km2 * min(2.0, crew_scale)
    # ...BUT NEVER MORE THAN A SENSIBLE SHARE OF THE GROUND THE HUNTER CAN ACTUALLY REACH.
    #
    # This floor is stated in absolute km², which is right for a box you drew but wrong
    # for a hunt bounded by how far you will walk from a camp. A hunter with a 2 km hunt
    # radius has 12.6 km² in total; a party of four then needs 6 km² — 48% of everything
    # they can reach — as ONE contiguous lobe above the quality bar. That cannot happen on
    # any real ground, so the plan came back completely empty: no areas, and therefore no
    # sites and no routes, because everything downstream is placed per area. The engine
    # reported success and the map showed nothing.
    #
    # A focus area still has to be a chunk worth walking to; it just cannot be asked to be
    # bigger than the hunt itself. 15% of reachable ground is the cap, and only ever
    # LOWERS the floor — a big box keeps the full 3 km² (×crew) bar.
    avail_km2 = float(np.isfinite(hunt).sum()) * px_area
    if avail_km2 > 0:
        capped = max(0.5, 0.15 * avail_km2)
        if capped < min_km2:
            print(f"[synth] focus-area floor {min_km2:.1f} -> {capped:.1f} km2 "
                  f"({avail_km2:.1f} km2 reachable)")
            min_km2 = capped
    FLOOR = float(fcfg.get("min_huntability", 0.30))   # ABSOLUTE admission bar
    # How far an admitted area may EXTEND (see the note at `grow` below). Not a quality
    # bar — nothing is admitted by these; they only decide where an already-qualified
    # area stops. Capped so an area can still never exceed max_area_km2.
    GROW_FRAC_OF_FLOOR = float(fcfg.get("grow_frac_of_floor", 0.72))
    GROW_REL = float(fcfg.get("grow_rel", 0.80))
    # QUALITY IS TESTED ON THE RAW SURFACE, EXTENT ON THE SMOOTHED ONE (T6.3).
    #
    # Everything below thresholds `hs`, the surface after a ~350 m Gaussian. That is
    # right for deciding SHAPE — the raw 40 m surface is speckly and a bare threshold
    # gives swiss-cheese — but it is wrong for deciding QUALITY, because a blur pulls
    # genuinely poor ground up over the bar whenever it sits next to good ground.
    #
    # Measured: the extent bar is FLOOR x GROW_FRAC_OF_FLOOR = 0.216, while random ground
    # on these boxes averages 0.235-0.248. An admitted area could therefore grow out into
    # ground BELOW the landscape mean, and did — one 19 km2 patch scoring 0.248 against
    # 0.244 for a random draw, on a box where a contiguous area of that size could reach
    # 0.322.
    #
    # So a cell must now clear a bar on its OWN value as well. Coherence is not lost:
    # binary_closing + binary_fill_holes below absorb isolated rejects, so speckle is
    # still smoothed over — only genuinely poor REGIONS are kept out.
    EXTENT_RAW_FRAC = float(fcfg.get("extent_raw_frac", 0.0))
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    to_wgs = lambda geom: shp_transform(lambda xs, ys: tr.transform(xs, ys), geom)

    hfill = np.where(np.isfinite(hunt), hunt, 0)
    # Smooth before region-growing: the raw 40 m surface is speckly, so a bare
    # threshold gives swiss-cheese. Smoothing yields cohesive focus-area blobs.
    hs = gaussian_filter(hfill, sigma=max(4, int(round(float(fcfg.get("smoothing_m", 350)) / res))))
    radius_px = int(round(np.sqrt(max_km2 / np.pi) * 1000 / res))
    # SEPARATION IS DERIVED, NOT A MAGIC 8 km. Candidates were forced >=8000 m
    # apart regardless of AOI size or area size, and that — not the quality bar —
    # was what limited the count: measured on the 36 km Fire Lake surface, 8 km
    # spacing allows only 4 peaks to exist at all (2 survive), while 5 km allows 11
    # (9 survive) passing the IDENTICAL quality gate. On a 100 km box that reads as
    # "there is one good spot in 5000 km2", which is a statement about the constant,
    # not about the ground.
    #
    # One area-radius is the principled floor: closer than that and two candidates'
    # footprints are the same piece of ground. Further apart is thinning for its own
    # sake. It scales with max_area_km2, so bigger areas do get more spacing.
    sep_m = max(float(fcfg.get("min_separation_m", 0)) or 0.0,
                np.sqrt(max_km2 / np.pi) * 1000.0)
    min_dist_px = max(3, int(round(sep_m / res)))
    Y, X = np.ogrid[:hunt.shape[0], :hunt.shape[1]]

    def _find(floor, gate_f, min_a):
        # ABSOLUTE admission (audit #50): a peak must clear `floor` on the real 0..1 scale,
        # not a within-AOI percentile — so a mediocre box no longer invents areas from its
        # local top quartile. exclude_border=False (the default excludes a ~min_distance
        # border that on a small AOI falls over the best ground); synth crops its own 2 km.
        peaks = peak_local_max(hs, num_peaks=NO_CAP, min_distance=min_dist_px,
                               threshold_abs=floor, exclude_border=False)
        out = []
        dbg = []
        for (pr, pc) in peaks:
            near = (Y - pr) ** 2 + (X - pc) ** 2 <= radius_px ** 2
            # ADMISSION AND EXTENT ARE DIFFERENT QUESTIONS, and one constant was answering
            # both. `floor` proves a spot is good enough to ANCHOR an area — that must stay
            # absolute and strict, it is the whole of audit #50. But using the same value
            # to bound how far the area EXTENDS says a focus area may only cover ground as
            # good as its own best cell, which is not how anyone hunts: you sit the good
            # spot and work the decent ground around it.
            #
            # It only started to bite when the browse rebuild gave the surface real
            # CONTRAST. Before, a satellite floor smeared every peak into a broad shoulder,
            # so "above the admission bar" and "workable ground around the peak" happened to
            # be the same region. With the smear gone the peaks stayed just as high
            # (smoothed max 0.352 vs 0.359 on the same ground) and the shoulders fell away,
            # so lobes collapsed from ~8 km² to ~1.5 km², dropped under min_area_km2, and
            # every candidate died — a plan with no areas, and therefore no stands and no
            # routes, on ground that had three good areas under the previous revision.
            #
            # So extent gets its own, looser bar: ground at least GROW_FRAC_OF_FLOOR as good
            # as the admission bar, and still related to this peak. Quality is unchanged —
            # nothing is admitted that was not admitted before.
            grow = max(FLOOR * GROW_FRAC_OF_FLOOR, float(hs[pr, pc]) * gate_f * GROW_REL)
            raw = near & np.isfinite(hunt) & (hs >= grow)
            if EXTENT_RAW_FRAC > 0:
                # Relative to the ADMISSION FLOOR, not to `grow`. Tying it to `grow` was
                # the first attempt and it did nothing: grow is already as low as 0.216,
                # so a fraction of it lands near 0.17 — far under the ~0.248 these
                # landscapes average, which is the very ground being excluded.
                raw = raw & (np.nan_to_num(hunt) >= FLOOR * EXTENT_RAW_FRAC)
            # Keep ONLY the connected component containing the peak, then close gaps &
            # fill holes so the ring, its centroid, and its placed sites all agree.
            lbl, _ = ndlabel(raw)
            comp = lbl[pr, pc]
            if comp == 0:
                continue
            sel = binary_fill_holes(binary_closing(lbl == comp, iterations=2))
            area = int(sel.sum()) * px_area
            if area < min_a:
                if os.environ.get("FOCUS_DEBUG"):
                    dbg.append((float(hs[pr, pc]), (int(pr), int(pc)), area,
                                float(np.nanmean(hunt[sel])), f"dropped: < {min_a:.1f} km2"))
                continue
            if os.environ.get("FOCUS_DEBUG"):
                dbg.append((float(hs[pr, pc]), (int(pr), int(pc)), area,
                            float(np.nanmean(hunt[sel])), "KEPT"))
            out.append((float(hs[pr, pc]), area, float(np.nanmean(hunt[sel])), sel))
        if os.environ.get("FOCUS_DEBUG"):
            # EVERY PEAK AND ITS FATE, from inside the real loop. Reconstructing this
            # from outside gave three different wrong answers before it was clear the
            # reconstruction was the problem — so the question gets asked here or not
            # at all.
            fin = np.isfinite(hunt)
            gy, gx = np.unravel_index(int(np.argmax(np.where(fin, hs, -1))), hs.shape)
            print(f"[synth] _find(floor={floor:.3f}, gate_f={gate_f}, min_area={min_a:.1f}) "
                  f"-> {len(peaks)} peaks, {len(out)} kept")
            print(f"[synth]    surface: finite {int(fin.sum())} cells, rows "
                  f"{int(np.where(fin.any(axis=1))[0].min())}-"
                  f"{int(np.where(fin.any(axis=1))[0].max())}, cols "
                  f"{int(np.where(fin.any(axis=0))[0].min())}-"
                  f"{int(np.where(fin.any(axis=0))[0].max())}")
            print(f"[synth]    smoothed max {hs[fin].max():.3f} at ({gy},{gx}); "
                  f"raw max {np.nanmax(hunt):.3f}")
            for pk, rc, ar, mn, why in sorted(dbg, reverse=True):
                print(f"[synth]    peak {rc} smoothed {pk:.3f} lobe {ar:6.1f} km2 "
                      f"mean {mn:.3f}  {why}")
        return out

    # Primary pass at the absolute floor, then ONE mild fallback (still absolute, not a
    # percentile). If nothing clears even that, return ZERO areas honestly — a poor or
    # water-locked box should say "thin ground here" (the access flags + recommendations
    # explain the trade-off), not dress up its least-bad ground as a recommendation.
    cands = _find(FLOOR, 0.82, min_km2)
    if not cands:
        cands = _find(FLOOR * 0.8, 0.70, max(1.0, min_km2 * 0.5))
    # The trigger is ONE FULL-SIZE FOCUS AREA (max_area_km2), not a multiple of the
    # minimum: you cannot subdivide something smaller than one unit of the thing you are
    # subdividing into. A 2 km hunt radius holds 11.5 km² against an 18 km² area — there
    # is no meaningful choice to offer between areas, so offering none was the failure.
    # A 5 km radius (78 km²) is comfortably larger and still has to earn its areas.
    if not cands and 0 < avail_km2 <= float(max_km2):
        # WHEN THE HUNT IS SMALLER THAN A FOCUS AREA, THE HUNT *IS* THE FOCUS AREA.
        #
        # A focus area is defined as "a chunk a party can work in a day" — roughly 3 km²
        # of a drainage. A hunter who tells us they will walk 2 km from the cabin has
        # 12.6 km² in total, and asking that to subdivide into a smaller, self-contained
        # chunk of exceptional ground is asking the wrong question: they have already
        # done the subdividing by choosing where to sleep. Returning nothing left them
        # with an empty map — no areas, and so no stands and no routes either, because
        # everything downstream is placed per area — on ground they hunt every season.
        #
        # This is NOT a lowered quality bar. Nothing here is claimed to be exceptional;
        # the area simply becomes "the ground you can reach", and the stands, routes and
        # scores inside it are computed and reported exactly as they always are, so a
        # thin cabin still reads as thin.
        sel = np.isfinite(hunt)
        if sel.any():
            sel = binary_fill_holes(binary_closing(sel, iterations=2))
            area = int(sel.sum()) * px_area
            score = float(np.nanmean(hunt[sel]))
            peak = float(np.nanmax(np.nan_to_num(hs)))
            print(f"[synth] hunt radius holds only {avail_km2:.1f} km2 — the reachable "
                  f"ground IS the focus area (mean huntability {score:.3f})")
            cands = [(peak, area, score, sel)]
    # Rank by EXPECTED ENCOUNTER ≈ area × mean huntability (coverage matters for a species
    # at ~20 km²/moose), not by mean alone, which favoured tiny tight pockets over large
    # good ground.
    cands.sort(key=lambda t: t[1] * t[2], reverse=True)
    # WHY THESE AREAS AND NOT OTHERS. Reconstructing this loop from outside the pipeline
    # to answer that produced three wrong answers in a row (a different gate_f, a
    # different smoothing, a different surface) before it was obvious the reconstruction
    # was the problem and not the model. FOCUS_DEBUG=1 asks the real code instead.
    if os.environ.get("FOCUS_DEBUG"):
        print(f"[synth] focus candidates: {len(cands)} kept | floor {FLOOR} "
              f"grow_frac {GROW_FRAC_OF_FLOOR} extent_raw {EXTENT_RAW_FRAC} "
              f"min_area {min_km2:.1f} max_area {max_km2} smoothing "
              f"{fcfg.get('smoothing_m')} sep {sep_m:.0f} m")
        for i, (pk, ar, sc, _s) in enumerate(cands, 1):
            print(f"[synth]   cand {i}: peak(smoothed) {pk:.3f} area {ar:.1f} km2 "
                  f"mean {sc:.3f} rank-score {ar * sc:.2f}")

    feats = []
    masks = []
    n_found = len(cands)
    for rank, (_peak, area, score, sel) in enumerate(cands, 1):
        selu = sel.astype("uint8")
        geoms = [shp_shape(g) for g, v in rio_shapes(selu, mask=sel, transform=prof["transform"]) if v == 1]
        if not geoms:
            continue
        poly = unary_union(geoms)
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda p: p.area)  # dominant lobe
        poly_wgs = to_wgs(poly)
        rp = poly_wgs.representative_point()               # guaranteed INSIDE
        cen = [round(rp.x, 5), round(rp.y, 5)]
        masks.append((rank, sel))
        feats.append({
            "type": "Feature", "geometry": poly_wgs.__geo_interface__,
            "properties": {"legend": "focus_area", "rank": rank,
                           "area_km2": round(area, 1), "mean_huntability": round(score, 3),
                           "centroid": cen,
                           # every candidate that cleared the bar is shown; this is a
                           # count of what qualified, not of what we chose to display
                           "candidates_found": n_found},
        })
    return feats, masks


def methodology(ctx) -> dict:
    """Plain-language statement of what terrain we're hunting for and the factors
    weighted — derived from the species config so it stays in sync with the model."""
    sp = ctx.species
    w = sp.hsm_weights
    order = sorted(w.items(), key=lambda kv: kv[1], reverse=True)
    factor_names = {"browse": "browse — burn regeneration age (NBAC fire history, peaking 15–22 yr "
                              "post-fire) plus shrub/wetland satellite land cover",
                    "water": "water & wetland proximity (riparian browse, travel corridors; aquatic "
                             "feeding is weighted only for summer dates — it ends by mid-September)",
                    "cover": "security/thermal cover (satellite tree cover next to browse)",
                    "terrain": "terrain (valley bottoms, wet flats, gentle slopes)",
                    "edge_density": "cover↔opening edge density (the feeding seam)"}
    weighted = [f"{factor_names.get(k,k)} ({int(v*100)}%)" for k, v in order]
    return {
        "summary": (
            "Moose are edge animals of the water-rich boreal, and in black-spruce country "
            "they are concentrated, not spread out — the unburned matrix is close to a food "
            "desert. So I hunt for regenerating burns of the right age beside security cover "
            "and water, then weight each candidate by how retrievable a 400–600 lb animal is "
            "and how little hunter pressure it likely sees."),
        "factors_weighted": weighted,
        "then": ("The habitat score is re-weighted by where your hunt dates fall in the rut "
                 "(at the breeding peak it leans toward cow habitat, because bulls stop feeding "
                 "and go where the cows are; in the seeking phase it leans toward bull travel "
                 "corridors), then multiplied by extraction ease and reduced by road-based "
                 "hunter pressure."),
        "caveats": [
            "Every site is a hypothesis to ground-truth on foot (à valider sur le terrain).",
            "Vegetation comes from 10 m satellite land cover plus mapped burn perimeters — "
            "NOT stand-level forestry inventory. Cutblock age is not modelled (only fire), "
            "so logged regeneration is under-counted.",
            "Scores are relative WITHIN this area of interest — a 0.85 here is not directly "
            "comparable to a 0.85 in a different search box.",
        ],
    }


def _lc_frac(lc, sel, classes):
    import numpy as np
    if lc is None or not sel.any():
        return 0.0
    return float(np.isin(lc[sel], classes).mean())


def _explain_area(sel, L, res, med, hunter=None):
    """Data-driven pros/cons + a 'why' sentence for one focus area."""
    import numpy as np

    wc = getattr(hunter, "watercraft", "none")
    walk_km = float(getattr(hunter, "walk_access_km", 6.0) or 6.0)
    style = getattr(hunter, "hunt_style", "spike")

    def mean(a):
        return float(np.nanmean(a[sel])) if (a is not None and sel.any()) else None

    dw, dr = mean(L["dist_water"]), mean(L["dist_road"])
    extr, pres, slp = mean(L["extraction"]), mean(L["pressure"]), mean(L["slope"])
    rutv, thm = mean(L["rut"]), mean(L["thermal"])
    elev = mean(L["dem"])
    f_water = _lc_frac(L["lc"], sel, [80]) + _lc_frac(L["lc"], sel, [90])
    f_browse = _lc_frac(L["lc"], sel, [20, 30]) + _lc_frac(L["lc"], sel, [90])
    f_cover = _lc_frac(L["lc"], sel, [10])

    kit = _hunter_kit(hunter)
    pros, cons = [], []
    if dw is not None and dw < 300:
        # Never sell water as an extraction route to a hunter who has no boat — that
        # was the model crediting a retrieval path the hunter can't use (user-caught).
        pros.append(f"water within ~{int(dw)} m ("
                    + ("aquatic feed + boat extraction" if kit["boat"] else "riparian browse & travel")
                    + ")")
    if f_browse > 0.25:
        pros.append(f"{int(f_browse*100)}% open browse/wetland (regen & riparian forage)")
    if 0.25 < f_cover < 0.85:
        pros.append("strong cover↔opening edge (mature conifer beside forage)")
    if dr is not None and dr < 1500:
        pros.append(f"truck-accessible (~{int(dr)} m to a road)")
    elif wc != "none" and dw is not None and dw < 300:
        pros.append(f"{'motor-boat' if wc=='motor' else 'canoe'}/water extraction (retrieve down to the nearest water)")
    if pres is not None and pres < 0.15:
        pros.append("low hunter pressure (off the main road)")
    if rutv is not None and rutv > 0.4:
        pros.append("rut/calling terrain (edges & funnels near wetland)")
    if slp is not None and slp < 6:
        pros.append(f"gentle ground (~{slp:.0f}° mean slope)")

    if dr is not None and dr > 4000:
        # Advise the kit they HAVE, not the kit the sentence was written around.
        _have = ([] + (["canoe/boat"] if kit["boat"] else []) + (["ATV"] if kit["atv"] else []))
        cons.append(f"far from a mapped road (~{dr/1000:.0f} km — "
                    + (f"plan {' or '.join(_have)}" if _have else "a long pack on foot")
                    + ")")
    if slp is not None and slp > 12:
        cons.append(f"steeper access (~{slp:.0f}° mean slope)")
    if pres is not None and pres > 0.4:
        cons.append("closer to road access → likely more hunting pressure")
    if f_water > 0.35:
        cons.append("very wet — scout dry approach lines and firm footing")
    if thm is not None and thm < 0.1:
        cons.append("few thermal refuges — tougher midday hunting if it's warm")
    if f_cover < 0.2:
        cons.append("open — limited security cover, bulls may hold elsewhere midday")
    # --- Setup-aware access gating: does THIS hunter's kit actually reach here? ---
    access_flag, boat_required = None, False
    if dr is not None:
        if wc == "none" and dr >= 5e5:
            access_flag = "⚠ No boat: this ground is cut off from the road by a river — not reachable on foot. A canoe/boat would open it."
            boat_required = True
            cons.insert(0, "cut off from the road by a river (needs a boat)")
        elif wc == "none" and dr > walk_km * 1000:
            access_flag = (f"⚠ ~{dr/1000:.1f} km on foot from the nearest road — beyond your "
                           f"~{walk_km:.0f} km walk-in. Expect a hard pack-out.")
            cons.insert(0, f"~{dr/1000:.1f} km walk-in on foot (past your {walk_km:.0f} km limit)")
        elif style == "vehicle" and dr > walk_km * 1000:
            access_flag = (f"~{dr/1000:.1f} km from a road — tough to return to the truck nightly; "
                           "consider a spike camp.")
    if not cons:
        cons.append("verify access and sign on the ground before committing")

    why = (f"Centers on a browse-and-water complex around {int(elev) if elev else '?'} m, "
           f"with forage within ~{int(dw) if dw is not None else '?'} m of water and a "
           f"{'strong' if 0.25<f_cover<0.85 else 'moderate'} cover-to-opening edge. "
           f"{'Retrievable and low-pressure' if (extr and extr>0.6 and pres and pres<0.2) else 'Weigh the access/extraction trade-off'} "
           f"for the rut window.")
    # Report habitat quality and retrievability as SEPARATE axes as well as the
    # combined score, so "A+ habitat, brutal pack-out" stays legible instead of being
    # averaged into one number.
    hab = mean(L.get("habitat_phase"))
    ret = mean(L.get("retrieval"))
    return {"why": why, "pros": pros, "cons": cons,
            "access_flag": access_flag, "boat_required": boat_required,
            "habitat_score": None if hab is None else round(hab, 3),
            "retrieval_score": None if ret is None else round(ret, 3),
            "stats": {"dist_water_m": None if dw is None else int(dw),
                      "dist_road_m": None if dr is None else int(dr),
                      "mean_slope_deg": None if slp is None else round(slp, 1)}}


# How the weapon re-weights the site mix. Multiplies the rut-phase weighting rather
# than replacing it — a bow hunt in the seeking phase is still a calling hunt.
METHOD_SITE_W = {
    "rifle": {"glassing": 1.0, "rut_calling": 1.0, "funnel": 1.0, "saline_blind": 1.0},
    # Glassing is a rifle tactic — spotting a bull you cannot reach is not a plan.
    # Everything that brings him inside 35 m matters more.
    "bow": {"glassing": 0.4, "rut_calling": 1.25, "funnel": 1.3, "saline_blind": 1.15},
    "muzzleloader": {"glassing": 0.8, "rut_calling": 1.1, "funnel": 1.1, "saline_blind": 1.05},
}


def _hunter_kit(hunter):
    """What the hunter actually brought. `transport` is the multi-select from Setup;
    `watercraft` is the older single field, kept in sync — either may carry the boat."""
    tr = dict(getattr(hunter, "transport", {}) or {})
    wc = getattr(hunter, "watercraft", "none")
    return {"boat": bool(tr.get("canoe") or tr.get("motor") or wc in ("canoe", "motor")),
            "motor": bool(tr.get("motor") or wc == "motor"),
            "atv": bool(tr.get("atv"))}


def _reach_km(hunter, kit):
    """How far from a road this hunter can realistically work, on their own terms.
    Spike/camp hunts add the road→camp leg to the camp→hunt leg; a vehicle hunt has
    only the one. An ATV multiplies it along tracks (the ride/walk split is #69)."""
    style = getattr(hunter, "hunt_style", "spike")
    # `x or default` treats a stated ZERO as "not set" — a hunter who says they will walk
    # 0 km in from the road silently got 6 km, which is the opposite of what they said.
    # Fall back only when the value is genuinely absent.
    _a = getattr(hunter, "walk_access_km", None)
    _h = getattr(hunter, "walk_hunt_km", None)
    access = float(6.0 if _a is None else _a)
    hunt_km = float(3.0 if _h is None else _h)
    reach = hunt_km if style == "vehicle" else (access + hunt_km)
    if kit["atv"]:
        reach = reach * 2.5 + 5.0
    return reach


def _capability_gate(dr, hunter, kit, camp_km=None, access_unknown=False):
    """Can this hunter actually GET here and get an animal OUT, given what they told
    us they have? Returns (ok, reason). A "no" is not a judgement about the ground —
    the area still ships, flagged, so the hunter can decide whether the kit is worth
    bringing (user: 'interesting to know they're there ... but not helpful to formally
    suggest sites the hunter cannot access').

    FIXED CAMP CHANGES THE QUESTION. If the hunter told us where camp is, they are not
    walking in from a road — they are already there, and what they said they'd cover is
    the distance from CAMP. Gating those areas on distance-to-road excluded ground 2.3 km
    from the tent because it was 4.2 km from a logging road nobody was going to use, and
    the card said so while its own header read "PACK-IN ≤ 2.3 KM". Road distance is not
    a capability limit for a camp hunt; it is trivia.
    """
    if camp_km is not None:
        reach = float(getattr(hunter, "hunt_radius_km", None)
                      or getattr(hunter, "walk_hunt_km", 3.0) or 3.0)
        if kit["atv"]:
            reach = reach * 2.5 + 5.0
        if camp_km > reach:
            return False, (f"Beyond your range — ~{camp_km:.1f} km from camp, past the "
                           f"~{reach:.0f} km you said you'd walk from it"
                           + (" (even by ATV)." if kit["atv"] else "."))
        return True, None
    if dr is None:
        return True, None
    # ACCESS UNKNOWN IS NOT ACCESS IMPOSSIBLE (T0.5). access.py already learned this and
    # says so at length — when no road network was acquired it refuses to zero the
    # extraction surface and falls back to a neutral 0.85 with a flag. This gate was
    # never taught the same lesson, and it collapsed two very different conditions into
    # one sentinel range:
    #
    #   * WATER-LOCKED — roads exist, and the cost-distance found no walkable path to
    #     any of them. That is a real finding about the ground.
    #   * NO ROAD DATA — acquire never landed a road network (a big box can blow the
    #     Overpass budget), so access.py fills dist_road with 1e6 as a placeholder.
    #
    # Both land above 5e5, so the second was being reported as the first. Measured on
    # the fire_lake cache, whose roads.tif is missing: dist_road is 1e6 across 100% of
    # cells, every one of 37 focus areas was excluded, and each carried the sentence
    # "No boat — this ground is cut off from every road by water." That is a confident,
    # specific claim built on having no data at all, which is the worst shape a wrong
    # answer can take.
    if access_unknown:
        return True, None
    reach = _reach_km(hunter, kit)
    # 5e5 is the barrier sentinel: no walkable path to a road at all (water-locked).
    if dr >= 5e5:
        if not kit["boat"]:
            return False, ("No boat — this ground is cut off from every road by water. "
                           "A canoe or boat would open it.")
        return True, None
    if dr > reach * 1000:
        return False, (f"Beyond your range — ~{dr/1000:.1f} km from the nearest road, past the "
                       f"~{reach:.0f} km you said you'd cover"
                       + (" (even by ATV)." if kit["atv"] else
                          ". An ATV or a boat would bring it in range."))
    return True, None


def _manual_focus_areas(manual_areas, hunt, prof, res):
    """Build (features, area_masks) from hand-drawn polygons, in the SAME shape
    extract_focus_areas returns — so the rest of synth (explain, site placement,
    camps, routes) runs unchanged. This is how a hunter says "we're hunting HERE"
    and the model plans inside their polygon instead of its own."""
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform
    from pyproj import Transformer

    to_grid = Transformer.from_crs("EPSG:4326", prof["crs"], always_xy=True)
    px_area = (res * res) / 1e6
    feats, masks = [], []
    for i, poly_lonlat in enumerate(manual_areas, 1):
        ring = poly_lonlat[0] if (poly_lonlat and isinstance(poly_lonlat[0][0], (list, tuple))) else poly_lonlat
        if len(ring) < 3:
            continue
        geom_wgs = {"type": "Polygon", "coordinates": [ring]}
        geom_grid = shp_transform(lambda xs, ys: to_grid.transform(xs, ys), shp_shape(geom_wgs))
        sel = rasterize([(geom_grid, 1)], out_shape=hunt.shape, transform=prof["transform"],
                        fill=0, dtype="uint8").astype(bool)
        sel &= np.isfinite(hunt)
        if not sel.any():
            continue
        area = int(sel.sum()) * px_area
        score = float(np.nanmean(hunt[sel]))
        rp = shp_shape(geom_wgs).representative_point()
        feats.append({"type": "Feature", "geometry": geom_wgs,
                      "properties": {"legend": "focus_area", "rank": i,
                                     "area_km2": round(area, 1),
                                     "mean_huntability": round(score, 3),
                                     "centroid": [round(rp.x, 5), round(rp.y, 5)],
                                     "manual": True,
                                     "candidates_found": len(manual_areas),
                                     "candidates_shown": len(manual_areas)}})
        masks.append((i, sel))
    return feats, masks


def run(ctx: Context, manual_areas=None) -> None:
    cache = cache_dir(ctx.aoi.name)
    res = ctx.model.raster_resolution_m
    hunt, prof = ru.read(cache / "huntability.tif")
    rut = ru.read(cache / "hsm_rut.tif")[0]
    thermal = ru.read(cache / "hsm_thermal.tif")[0]
    funnel = ru.read(cache / "terrain/funnel.tif")[0]
    dem = ru.read(cache / "dem.tif")[0]
    dist_water = ru.read(cache / "dist_water.tif")[0]
    # Prominence for glassing. T9.10 measures this on the LiDAR fine grid and reports
    # the PEAK inside each analysis cell — an 80 m knob is two cells at 40 m and the
    # smoothing flattens it, which is the "they need to be on high points and it feels
    # like they often aren't" complaint. terrain.py falls the layer back to the coarse
    # tpi wherever no LiDAR was flown, so this is never the reason a glassing point is
    # missing; the `or` below only covers a cache written before T9.10.
    tpi = _opt(cache / "terrain/prominence.tif")
    prom_is_peak = tpi is not None
    if tpi is None:
        tpi = _opt(cache / "terrain/tpi.tif")   # cache written before T9.10
    cover = _opt(cache / "cover.tif")
    browse = _opt(cache / "browse.tif")            # glassable openings / feeding edge

    dist_road = _opt(cache / "dist_road.tif")
    # Behavioral occupancy surfaces (behavior stage) — richer signals than the
    # raw HSM sub-scores for placing period-specific sits. Fall back if absent.
    b_feed = _opt(cache / "behavior/feed.tif")
    b_refuge = _opt(cache / "behavior/refuge.tif")
    b_cruise = _opt(cache / "behavior/cruise.tif")
    toll = _to_lonlat(prof)
    md = max(3, int(round(1500 / res)))  # keep features ~1.5 km apart

    # Crop a border margin: focal/Hessian filters produce artefacts at the raster
    # edge, which would otherwise pull every peak onto the AOI boundary.
    m = max(5, int(round(2000 / res)))
    for a in (hunt, rut, thermal, funnel, dem, b_feed, b_refuge, b_cruise):
        if a is None:
            continue
        a[:m, :] = np.nan
        a[-m:, :] = np.nan
        a[:, :m] = np.nan
        a[:, -m:] = np.nan

    # HUNT-FROM-A-FIXED-CAMP: narrow the analysis to what you can walk from camp.
    # The hunter has chosen where they're basing, so the only relevant ground is a
    # circle around it (radius = hunt_radius_km, or their camp→hunt walk). Masking the
    # huntability surface here means focus areas, sites and routes all fall within
    # reach of camp — a tight, usable plan instead of the whole box.
    fixed_camp = getattr(ctx.aoi.hunter, "fixed_camp", None)
    fixed_camp_rc = None
    if fixed_camp:
        from pyproj import Transformer as _TR
        _tr = _TR.from_crs("EPSG:4326", prof["crs"], always_xy=True)
        _inv = ~prof["transform"]
        _x, _y = _tr.transform(fixed_camp[1], fixed_camp[0])   # (lat,lon)->(x,y)
        _c, _r = _inv * (_x, _y)
        H, W = hunt.shape
        fixed_camp_rc = (max(0, min(H - 1, int(_r))), max(0, min(W - 1, int(_c))))
        radius_km = (getattr(ctx.aoi.hunter, "hunt_radius_km", None)
                     or getattr(ctx.aoi.hunter, "walk_hunt_km", 3.0) or 3.0)
        rad_px = max(3, int(round(radius_km * 1000.0 / res)))
        Yc, Xc = np.ogrid[:H, :W]
        outside = (Yc - fixed_camp_rc[0]) ** 2 + (Xc - fixed_camp_rc[1]) ** 2 > rad_px ** 2
        hunt[outside] = np.nan          # everything past the camp radius drops out

    # Manual focus areas (hunter drew "we're hunting here") take over from the
    # model's own extraction; everything downstream — sites, camps, routes, brief —
    # then plans inside the hunter's polygon.
    if manual_areas:
        features, area_masks = _manual_focus_areas(manual_areas, hunt, prof, res)
    # PERSIST THE POOL THE EXTRACTION ACTUALLY CHOSE FROM (T6.4).
    #
    # `hunt` reaches here already narrowed — a 2 km border crop for filter artefacts, and
    # the reachability/camp-radius mask above. On one real box that leaves rows 254-754 of
    # a 1008-row raster: a 10 km window inside a 20 km box.
    #
    # Nothing downstream could see that, and the null-model benchmark got it wrong FOUR
    # times in a row — each time drawing its "best possible area" from ground the model
    # was structurally forbidden to select, and each time producing a confident verdict
    # that the extraction was choosing badly. The last of those put the ideal area at
    # (241, 759), outside this window on both axes. Guessing the mask from outside does
    # not work; writing it down does.
    try:
        ru.write(cache / "focus_pool.tif",
                 np.isfinite(hunt).astype("float32"), prof)
    except Exception as _e:  # noqa: BLE001 — diagnostics must never fail a run
        print(f"[synth] focus_pool not written: {_e}")
    if not manual_areas or not area_masks:
        features, area_masks = extract_focus_areas(ctx, hunt, prof)

    # Data-driven "why this area" + pros/cons for each focus area.
    Lyr = {"dist_water": dist_water, "dist_road": dist_road, "dem": dem,
           "rut": rut, "thermal": thermal,
           "extraction": _opt(cache / "extraction.tif"),
           "pressure": _opt(cache / "pressure.tif"),
           "habitat_phase": _opt(cache / "habitat_phase.tif"),
           "retrieval": _opt(cache / "retrieval.tif"),
           "slope": _opt(cache / "terrain/slope.tif"),
           "lc": _opt(cache / "landcover.tif"),
           "ndvi": _opt(cache / "ndvi.tif"), "lat": ctx.aoi.center.lat}
    mask_by_rank = {rank: sel for rank, sel in area_masks}
    from . import confidence as _conf
    for f in features:
        if f["properties"]["legend"] == "focus_area":
            sel = mask_by_rank.get(f["properties"]["rank"])
            if sel is not None:
                f["properties"].update(_explain_area(sel, Lyr, res, None, ctx.aoi.hunter))
                f["properties"]["conf"] = _conf.area_confidence(sel, Lyr)

    # ---- CAPABILITY GATE ------------------------------------------------------
    # Did access get modelled at all? access.py raises this flag when no road network
    # was acquired, and without reading it the gate cannot tell "cut off by water" from
    # "we never found out" — see _capability_gate.
    _access_unknown = False
    try:
        _access_unknown = (cache / "access_unknown.flag").read_text().strip() == "1"
    except Exception:
        _access_unknown = False
    # Ground the hunter cannot reach with the kit they told us about is not a
    # recommendation — it's a note. Gate every area, then RE-RANK so the areas they
    # can actually hunt take ranks 1..n (this is the "search down the ranking for
    # viable alternates" step: extraction is uncapped, so the lower-scoring areas
    # that DO fit are already found and simply get promoted). Excluded areas keep
    # their order behind them and carry the reason instead of a recommendation.
    _kit = _hunter_kit(ctx.aoi.hunter)
    _areas = [f for f in features if f["properties"]["legend"] == "focus_area"]
    for f in _areas:
        st = (f["properties"].get("stats") or {})
        # With a fixed camp the reach is measured from the CAMP, not from a road: the
        # nearest cell of the area, so a big area counts as reachable when its near edge
        # is in range rather than being judged on its far corner.
        _camp_km = None
        if fixed_camp_rc is not None:
            _sel = mask_by_rank.get(f["properties"]["rank"])
            if _sel is not None and _sel.any():
                _rc = np.argwhere(_sel)
                _d = np.hypot(_rc[:, 0] - fixed_camp_rc[0], _rc[:, 1] - fixed_camp_rc[1])
                _camp_km = float(_d.min()) * res / 1000.0
        ok, why_not = _capability_gate(st.get("dist_road_m"), ctx.aoi.hunter, _kit,
                                       camp_km=_camp_km, access_unknown=_access_unknown)
        f["properties"]["status"] = "ok" if ok else "excluded"
        f["properties"]["excluded_reason"] = why_not
    _ok = [f for f in _areas if f["properties"]["status"] == "ok"]
    _ex = [f for f in _areas if f["properties"]["status"] != "ok"]
    _remap = {}
    for new_rank, f in enumerate(_ok + _ex, 1):
        _remap[f["properties"]["rank"]] = new_rank
    for f in _areas:
        f["properties"]["rank"] = _remap[f["properties"]["rank"]]
    # Sites/routes are placed ONLY inside areas the hunter can work — no compute
    # spent detailing ground the plan can't send them to.
    area_masks = [(_remap[rank], sel) for rank, sel in area_masks
                  if _remap.get(rank) is not None
                  and _remap[rank] <= len(_ok)]
    area_masks.sort(key=lambda t: t[0])
    mask_by_rank = {rank: sel for rank, sel in area_masks}
    if _ex:
        print(f"[synth] capability gate: {len(_ex)} of {len(_areas)} focus areas excluded; "
              f"{len(_ok)} viable areas promoted to ranks 1..{len(_ok)}")

    def _best_in(arr, mask, k):
        """Top-k peaks of arr restricted to a focus-area mask."""
        a = np.where(mask & np.isfinite(arr), arr, 0.0)
        return _peaks(a, k, md)

    def add_points_per_area(arr, legend, per_area, extra=None, min_score=0.0):
        """Place features INSIDE each focus area (like annotations inside the
        expert's loops) so they distribute across all ranked areas.

        `min_score` is a floor: a site is only placed where the surface actually
        carries signal. Without it, the per-area argmax drops a marker even on a
        near-zero surface — which put "funnels" 4–5 km from any water on a
        water-sparse AOI (no real neck exists, so none should be shown). Better to
        place fewer or none than to invent a low-confidence site."""
        for rank, mask in area_masks:
            for (r, c) in _best_in(arr, mask, per_area):
                if not np.isfinite(arr[r, c]) or float(arr[r, c]) < min_score:
                    continue
                lon, lat = toll((r, c))
                props = {"legend": legend, "focus_area": rank,
                         "score": round(float(arr[r, c]), 3),
                         "elev_m": round(float(dem[r, c]), 0) if np.isfinite(dem[r, c]) else None}
                # #71: WHY this marker is here, in plain language, plus a confidence that
                # never pretends a modelled site is a certainty. Reads the local values
                # that actually drove the placement.
                try:
                    def _at(a):
                        return (float(a[r, c]) if a is not None and np.isfinite(a[r, c]) else None)
                    props.update(_conf.site_explain(legend, {
                        "score": float(arr[r, c]),
                        "dist_water_m": _at(dist_water), "dist_road_m": _at(dist_road),
                        "slope_deg": _at(Lyr.get("slope")), "browse": _at(browse),
                    }))
                except Exception:
                    pass
                if extra:
                    props.update(extra)
                features.append({"type": "Feature",
                                 "geometry": {"type": "Point", "coordinates": [lon, lat]},
                                 "properties": props})

    near_water = np.where(np.isfinite(hunt), hunt * np.exp(-dist_water / 400), np.nan)
    # GLASSING (audit #56): a knob is worth glassing for what it OVERLOOKS, not its raw
    # height. Was glass = normalize(dem) — pure elevation rank, which invents "knobs" on
    # flat closed canopy. Rebuild as local PROMINENCE (height above the ~500 m
    # neighbourhood, fixed-metre bounds → absolute) × VISIBLE OPENNESS (how much
    # glassable feeding habitat lies within optical range). A prominent point in a sea of
    # timber scores ~0; a modest rise over a willow flat scores high. On flat/closed AOIs
    # this is ~0 everywhere, so the min_score floor below places NO glassing points —
    # honest (the tactic degrades to calling/still-hunting).
    from scipy.ndimage import maximum_filter as _mxg
    from scipy.ndimage import uniform_filter as _ufg
    _res = float(ctx.model.raster_resolution_m)
    # PROMINENCE, and two things it has to get right (user: "they need to be on high
    # points and it feels like they often aren't").
    #
    # 1. SCALE. This clamped at TPI/12 m, and 12 m above a 500 m neighbourhood is a low
    #    bar in rolling boreal country — a large share of cells hit 1.0 and TIED. Once
    #    prominence saturates, the product below is decided entirely by openness, so the
    #    model was really picking "most browse within 1.2 km" and height had stopped
    #    discriminating at all. Scaling over ~30 m lets a real knob outrank a bump.
    #
    # 2. BEING ACTUALLY HIGH. TPI is elevation minus the neighbourhood MEAN, which is
    #    positive anywhere above average — including the middle of a uniform slope, with
    #    a hillside at your back blocking half the view. Require the cell to sit near the
    #    neighbourhood MAXIMUM as well: full credit at the local summit, fading out ~15 m
    #    below it. Mid-slope ground stops qualifying as a knob.
    #
    # 3. THE SCALE HAS TO FOLLOW THE MEASUREMENT (T9.10). Since the layer became a PEAK
    #    within the cell measured on the LiDAR grid, the same knob reads ~1.5x higher in
    #    metres than the 40 m cell mean did. Dividing by 30 would have quietly undone
    #    fix (1) by pushing the same cells back into saturation — a resolution upgrade
    #    silently re-breaking the calibration it was supposed to help. The divisor moves
    #    with the statistic so "full prominence" keeps meaning the same landform.
    if tpi is not None:
        prom = np.clip(np.nan_to_num(tpi) / (45.0 if prom_is_peak else 30.0), 0.0, 1.0)
        if dem is not None:
            _win_p = max(3, int(round(600 / _res)) | 1)
            _demf = np.nan_to_num(dem, nan=np.nanmin(dem) if np.isfinite(dem).any() else 0.0)
            _below = _mxg(_demf, size=_win_p) - _demf          # metres below the local high
            prom = prom * np.clip(1.0 - _below / 15.0, 0.0, 1.0)
    else:
        prom = np.where(np.isfinite(hunt), ru.normalize(dem), 0.0)
    if browse is not None:
        win_g = max(3, int(round(1200 / _res)) | 1)          # ~1.2 km glassing radius
        openness = _ufg(np.clip(np.nan_to_num(browse), 0.0, 1.0), size=win_g)
        openness = np.clip(openness / 0.40, 0.0, 1.0)
    else:
        openness = np.ones_like(prom)
    glass = np.where(np.isfinite(hunt), prom * openness, np.nan)
    # Prefer the behavioral surfaces (time/temp-resolved) where the stage ran;
    # tag every sit with WHEN to hunt it so the map reads as a day plan.
    rut_surf = b_cruise if b_cruise is not None else rut
    refuge_surf = b_refuge if b_refuge is not None else thermal
    feed_surf = b_feed if b_feed is not None else near_water
    # A focus area has to hold the whole crew, so every setup type scales with it.
    # One calling stand and one knob is a solo plan; it tells a party of five
    # nothing about where the other four should stand.
    party = int(getattr(ctx.aoi.hunter, "party_size", 2) or 2)
    import math as _m
    from . import rut_timing as _rt
    # PHASE SHIFTS THE SITE MIX, not just the surface underneath it. A seeking hunt
    # wants more calling stands and travel funnels; a peak hunt wants fewer calling
    # stands and more cow/feeding sits; post-rut leans to food. Base counts scale with
    # the crew, then the phase re-weights each type (min 1 so a type never vanishes —
    # it's de-emphasised, not deleted; the hunter still sees the option).
    pw = _rt.PHASE_SITE_W[_rt.dominant_phase(ctx)]
    # ...AND BY WHAT YOU ARE CARRYING (T10.2). "shooting locations for a bow (max
    # 30/40yds) are going to be different for those with a rifle (longer range, need
    # visibility more than proximity)". A glassing knob is a rifle tactic: seeing a bull
    # at 600 m is worth something only if you can reach him. With a bow the value is in
    # being CLOSE to where he already walks — the neck, the calling setup — and in wind
    # discipline, because you are inside his nose's working range the whole time.
    mw = METHOD_SITE_W.get(_scent.method_of(ctx), METHOD_SITE_W["rifle"])
    def _n(base, key, cap):
        # Bias the rounding so the emphasis is visible even at party=2 (base 1): a
        # phase that FAVOURS a type rounds up, one that de-emphasises rounds down
        # (floor, min 1 — the option never disappears). Plain round() would collapse
        # every 0.7–1.4 multiplier on a base of 1 back to 1 and hide the whole point.
        w = pw.get(key, 1.0) * mw.get(key, 1.0)
        n = _m.ceil(base * w) if w > 1.0 else max(1, _m.floor(base * w))
        return max(1, min(cap, int(n)))
    n_call   = _n(max(2, min(8, party)), "rut_calling", 8)
    n_glass  = _n(max(1, _m.ceil(party / 2)), "glassing", 4)
    n_feed   = _n(max(1, _m.ceil(party / 3)), "saline_blind", 4)
    n_funnel = _n(max(1, _m.ceil(party / 2)), "funnel", 4)
    n_refuge = _n(1, "thermal_refuge", 3)
    add_points_per_area(rut_surf, "rut_calling", n_call,
                        {"min_stand_minutes": 30, "when": "dawn & dusk + all rut day (bulls cruise these edges)"})
    add_points_per_area(refuge_surf, "thermal_refuge", n_refuge,
                        {"when": "midday when it's warm (> ~14 °C) — hunt the cool cover, not the openings"})
    # FEEDING sites (audit #57): keep points on the browse EDGE, not bare shoreline, and
    # tell the truth about the season — aquatic-sodium feeding is a summer behaviour that
    # is over by the late-Sept/Oct rut, so only say "aquatic" when the hunt date is early.
    if browse is not None:
        feed_surf = np.where(np.nan_to_num(browse) > 0.20, feed_surf, np.nan)
    def _aquatic_relevant():
        try:
            d = ctx.aoi.season.target_dates[0]           # 'YYYY-MM-DD'
            mm, dd = int(d[5:7]), int(d[8:10])
            return (mm < 9) or (mm == 9 and dd <= 20)
        except Exception:
            return False
    feed_when = ("first & last light — aquatic feeding (shallow ponds & flowages) + browse edge"
                 if _aquatic_relevant() else
                 "first & last light — feeding along the browse edge / riparian willow")
    add_points_per_area(feed_surf, "saline_blind", n_feed, {"when": feed_when})
    # A feeding EDGE is a band, not a dot. The point marker says "sit here", which is
    # useful, but drawing only a point misrepresents what was found — the whole seam is
    # workable and the hunter should see its extent and shape. Persist the surface so the
    # contract can polygonize it into the band it actually is (the points stay).
    try:
        ru.write(cache / "feed_edge.tif", np.where(np.isfinite(feed_surf), feed_surf, np.nan), prof)
    except Exception as _ex:
        print(f"[synth] feed_edge surface not written: {_ex}")
    add_points_per_area(funnel, "funnel", n_funnel,
                        {"when": "travel corridor — any time, best when animals are moving"},
                        min_score=0.15)   # only where a real neck exists (tightened surface)
    # min_score floor: on flat/closed-canopy ground with nothing to overlook, place NO
    # glassing knob rather than inventing one on the tallest closed-canopy cell.
    add_points_per_area(glass, "glassing", n_glass,
                        {"when": "dawn & dusk — glass the openings from high ground",
                         "pair": "glass in pairs where the crew allows — two sets of eyes on one basin beats two basins half-watched"},
                        min_score=0.15)
    # NO "ground-truth point" PIN. It was one marker per area dropped on the highest
    # huntability cell — which is where the plan already puts a stand, so it added a
    # second icon saying "go and look at the place we just told you to hunt". The
    # advice is real and stays, as the ground-truth CHECKLIST in the brief, which
    # applies to every stand and every access line rather than to an arbitrary point.
    # ground_truth_checklist() already words itself correctly for a count of zero.

    # --- access anchors: base camp + parking (need roads) ---
    routes_msg = ""
    if dist_road is not None and np.isfinite(dist_road).any() and dist_road.min() < 5000:
        access = dist_road
        anchor_kind = "road"
    else:
        access = dist_water  # canoe put-in as the access anchor
        anchor_kind = "water"
        routes_msg = "No mapped roads in AOI window — access anchored on water (canoe)."
    # base camp: near access AND near water AND central-ish, on huntable ground.
    #
    # ONE CAMP PER FOCUS AREA. This used to take the 2 best camp cells AOI-WIDE,
    # which on a big box put every camp in one corner — and since hunt lines run
    # camp -> stand, the map drew 40 km "walking routes" from a camp in one
    # drainage to a stand in another. Staging was already per-area; the camp was
    # not, so the two disagreed. A focus area has to be a self-contained plan:
    # park here, sleep here, hunt these stands, all within a day's foot travel.
    #
    # AND: a VEHICLE hunter has no base camp at all — they sleep at the truck and
    # come back to it. Placing a separate "base camp" pin for them invents a
    # structure they told us they weren't using, and then draws hunt lines from
    # it. For hunt_style=vehicle the staging point IS the camp, and only one pin
    # is emitted.
    # Camp OFF the haul road (audit #60): exp(-access/600) pulled the camp onto the road
    # shoulder — the opposite of field practice, which sets camp back from the main road
    # for quiet and away from other hunters' headlights, but within an easy carry of it.
    # Use a set-back BAND that peaks ~400 m off the road. A water (canoe) anchor is
    # different — there you want to be AT the put-in, so keep the near-preference.
    if anchor_kind == "road":
        access_pref = np.clip(access / 400.0, 0, 1) * np.exp(-np.clip(access - 400.0, 0, None) / 900.0)
    else:
        access_pref = np.exp(-access / 500.0)
    camp_score = access_pref * np.exp(-dist_water / 500) * np.nan_to_num(hunt)
    vehicle_style = getattr(ctx.aoi.hunter, "hunt_style", "spike") == "vehicle"
    camp_cells = []
    camp_of_area = {}
    if fixed_camp_rc is not None:
        # The hunter fixed the camp — every area is hunted FROM it. No camp-finding.
        for rank, sel in area_masks:
            camp_of_area[rank] = fixed_camp_rc
        camp_cells = [fixed_camp_rc]
    else:
        for rank, sel in area_masks:
            # allow the camp to sit just OUTSIDE the area (on the access side) but not
            # far: dilate the mask by ~the hunter's stated camp->hunt walking distance
            try:
                from scipy.ndimage import binary_dilation
                reach_px = max(2, int(round((ctx.aoi.hunter.walk_hunt_km * 1000) / res)))
                near = binary_dilation(sel, iterations=min(reach_px, 60))
            except Exception:
                near = sel
            cand = np.where(near, camp_score, 0.0)
            if not np.isfinite(cand).any() or float(np.nanmax(cand)) <= 0:
                continue
            rc = np.unravel_index(int(np.nanargmax(cand)), cand.shape)
            camp_cells.append((int(rc[0]), int(rc[1])))
            camp_of_area[rank] = (int(rc[0]), int(rc[1]))

    # Vehicle staging is a SEPARATE thing from camp: where you leave the truck, on
    # the road spine (or the canoe put-in if it's water-access).
    #
    # ONE STAGING POINT PER FOCUS AREA, at that area's OWN nearest road pixel.
    # This used to be derived per-camp and, worse, every access route was drawn
    # from a single global argmin of dist_road — one arbitrary cell for the whole
    # AOI. The result was a single long path chaining every area together, tens of
    # kilometres of it, crossing every river on the way. You do not drive to one
    # spot and then bushwhack across the AOI; you drive to the road nearest the
    # area you intend to hunt. Minimising that walk is the entire point.
    stage_mask = None
    stage_kind = "none"
    roads_r = _opt(cache / "roads.tif")
    if roads_r is not None and (np.nan_to_num(roads_r) > 0).any():
        stage_mask = np.nan_to_num(roads_r) > 0
        stage_kind = "road"
    elif dist_road is not None and np.isfinite(dist_road).any() and np.nanmin(dist_road) < 5000:
        # roads.tif is written by acquire, but an older cache may predate it. Falling
        # straight through to water then declared every area "boat access only" — a
        # false alarm that made nine road-accessible areas look unreachable. If we
        # have distance-to-road we still know exactly where the roads are.
        stage_mask = np.nan_to_num(dist_road, nan=1e9) <= max(res, 60.0)
        stage_kind = "road"
    else:
        wr = _opt(cache / "water.tif")
        if wr is not None and (np.nan_to_num(wr) > 0).any():
            stage_mask = np.nan_to_num(wr) > 0
            stage_kind = "water"
    stage_rc = np.argwhere(stage_mask) if stage_mask is not None else None

    def _nearest_stage(r, c):
        """Nearest staging pixel to (r, c), or None if nothing is mapped."""
        if stage_rc is None or not len(stage_rc):
            return None
        d2 = (stage_rc[:, 0] - r) ** 2 + (stage_rc[:, 1] - c) ** 2
        sr, sc = stage_rc[int(np.argmin(d2))]
        return int(sr), int(sc)

    # STAGING FIRST, then camps. The vehicle branch derives its camp FROM staging,
    # so staging has to exist before either branch runs — reading area_stage above
    # its own definition was an UnboundLocalError on every vehicle hunt (the spike
    # path never touched it, so it slipped past a spike-only test).
    area_stage = {}
    for rank, sel in area_masks:
        rc = np.argwhere(sel)
        if not len(rc):
            continue
        ar, ac = rc.mean(axis=0)                      # area centre in pixel space
        # snap the centre to a cell actually inside the area, then find its road
        d2 = (rc[:, 0] - ar) ** 2 + (rc[:, 1] - ac) ** 2
        ar, ac = rc[int(np.argmin(d2))]
        st = _nearest_stage(int(ar), int(ac))
        if st is None:
            continue
        area_stage[rank] = (st, (int(ar), int(ac)))
        # HUNT STYLE DECIDES WHAT ANCHORS EXIST.
        #   hunting camp (fixed) : the camp IS the staging and the bed — ONE pin, no
        #                          separate parking (you drove to your camp).
        #   vehicle              : staging only — you sleep at the truck, so a separate
        #                          "base camp" pin would be a fiction.
        #   spike                : both — leave the truck here, pack in and sleep there.
        # area_stage is still computed for fixed camps because routing uses it; it just
        # doesn't become a map feature.
        if fixed_camp_rc is not None:
            continue
        slon, slat = toll(st)
        walk_px = float(np.hypot(st[0] - ar, st[1] - ac))
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [slon, slat]},
                         "properties": {"legend": "parking", "anchor": stage_kind,
                                        "focus_area": rank,
                                        # say it out loud when the truck is also the bed
                                        "is_camp": bool(vehicle_style),
                                        "walk_km": round(walk_px * res / 1000.0, 2)}})

    if fixed_camp_rc is not None:
        # The hunter fixed the camp: every area is hunted from it, and we emit NO pin.
        #
        # We used to drop a "Base camp" marker on the spot they had just told us about,
        # which handed their own input back as if the model had found it — and under a
        # legend row reading "Where you sleep. Spike hunts only." A hunting-camp hunt has
        # no base camp to recommend; it HAS a camp, and the hunter knows where, because
        # they put it there. Routing still starts from it (camp_of_area below); it simply
        # stops pretending to be a recommendation.
        camp_of_area = {rank: fixed_camp_rc for rank, _sel in area_masks}
        camp_cells = [fixed_camp_rc]
    elif vehicle_style:
        # No base_camp features at all: routes originate from the staging pin.
        camp_of_area = {rank: st for rank, (st, _c) in area_stage.items()}
        camp_cells = list(camp_of_area.values())
    else:
        for rank, (r, c) in camp_of_area.items():
            lon, lat = toll((r, c))
            features.append({"type": "Feature",
                             "geometry": {"type": "Point", "coordinates": [lon, lat]},
                             "properties": {"legend": "base_camp", "anchor": anchor_kind,
                                            "focus_area": rank}})

    # --- least-cost approach routes: access -> top rut sites (best), -> thermal (midday_hot) ---
    try:
        _add_routes(ctx, features, cache, prof, access, toll, camp_of_area=camp_of_area)
    except Exception as e:  # routing is best-effort
        routes_msg += f" (routes skipped: {e})"

    # --- REACHABILITY GATE ---------------------------------------------------
    # Focus areas are isolated by the hunter's SETUP, not by quietly scoring
    # unreachable ground down. An area that is prime habitat but needs a boat you
    # do not have, or sits further off a road than you said you would walk, stays
    # on the map — flagged, dimmed, with the reason stated. Hiding it would be the
    # trust violation: a recommendation you cannot see the existence of.
    reach_km = float(getattr(ctx.aoi.hunter, "walk_access_km", 6.0) or 6.0)
    has_boat = getattr(ctx.aoi.hunter, "watercraft", "none") != "none"
    for f in features:
        if f["properties"].get("legend") != "focus_area":
            continue
        rank = f["properties"].get("rank")
        st = area_stage.get(rank)
        reasons = []
        if st is None:
            reasons.append("no mapped road or put-in within the analysis window")
            walk_km = None
        else:
            (sr, sc), (ar, ac) = st
            walk_km = round(float(np.hypot(sr - ar, sc - ac)) * res / 1000.0, 2)
            if stage_kind == "water" and not has_boat:
                reasons.append("only reachable from the water and you have no boat")
            elif walk_km > reach_km:
                reasons.append(f"{walk_km} km from the nearest road — further than the "
                               f"{reach_km} km you said you would walk in")
        f["properties"]["walk_in_km"] = walk_km
        f["properties"]["reachable"] = not reasons
        f["properties"]["unreachable_why"] = reasons[0] if reasons else None

    # crew plan per focus area, from the sites that were actually placed in it
    for f in features:
        if f["properties"].get("legend") != "focus_area":
            continue
        rank = f["properties"].get("rank")
        inside = [g for g in features
                  if g["properties"].get("focus_area") == rank
                  and g["geometry"]["type"] == "Point"]
        f["properties"]["crew"] = _crew_plan(
            f["properties"], inside, party,
            shooter_m=_scent.geometry_for(_scent.method_of(ctx))["shooter_m"])

    fc = {"type": "FeatureCollection", "features": features}
    (cache / "features.geojson").write_text(json.dumps(fc))
    # split focus areas out too (for KML polygons)
    fas = [f for f in features if f["properties"]["legend"] == "focus_area"]
    (cache / "focus_areas.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": fas}))

    _write_brief(ctx, features, cache, outputs_dir(ctx.aoi.name), routes_msg)


def _opt(p):
    """Read a raster if it exists, else None. Module-level because _walk_cost needs
    it too — it used to be nested inside synth(), so calling it from here raised
    NameError straight into the routing try/except and silently dropped every route."""
    try:
        return ru.read(p)[0]
    except Exception:
        return None


def _walk_cost(ctx, cache, roads_free=True):
    """Walking friction: base + slope + landcover, roads cheap, water impassable.

    Three defects this replaces, all visible on one Rouyn-Noranda run:

    1. WATER WAS ONLY BLOCKED VIA landcover==80. If landcover was missing the
       except swallowed it and every lake became walkable, so least-cost paths
       ran straight across open water with no crossing marker. Water now blocks
       from water.tif AND wetland/landcover, whichever exist — belt and braces,
       because being wrong here draws a line telling someone to walk onto a lake.

    2. ROADS WERE NOT IN THE SURFACE AT ALL, so a path had no reason to follow
       one. A hunter walks the road until it stops being useful; the model
       bushwhacked from the first metre.

    3. The water penalty (1e4) was finite, so on a long path the router would
       still happily cross a lake rather than take a 40 km detour. It is now
       large enough that crossing is never the cheap option.
    """
    slope = ru.read(cache / "terrain/slope.tif")[0]
    cost = 1.0 + np.nan_to_num(slope) / 10.0

    lc = _opt(cache / "landcover.tif")
    if lc is not None:
        cost = cost + np.where(lc == 90, 3.0, 0.0)   # wetland slow
    wg = _opt(cache / "wetland_grhq.tif")            # GRHQ wetland: slow going, not impassable (#62)
    if wg is not None:
        cost = cost + np.where(np.nan_to_num(wg) > 0, 3.0, 0.0)

    # TRAILS + RAIL are NOT roads and must never be costed as one — you cannot take a
    # truck down a quad trail or a rail grade. But both beat bushwhacking badly: a
    # cleared trail or an open rail grade is a fast walking line (and an ATV rides the
    # trail outright), which is also why moose use them as travel corridors. Their own
    # tier, between road (0.05) and open bush (~1+).
    _lin = _linear_cost_layer(cache, cost.shape)
    if _lin is not None:
        cost = np.where(_lin, 0.35, cost)

    # roads: near-free travel. This is what makes a route look like a route.
    # Applied AFTER trails so a genuine road always wins where the two overlap.
    if roads_free:
        rd = _opt(cache / "roads.tif")
        if rd is not None:
            cost = np.where(np.nan_to_num(rd) > 0, 0.05, cost)

    # water: impassable on foot, from every source that says "water"
    WATER = 1e7
    wet = _opt(cache / "water.tif")
    if wet is not None:
        cost = np.where(np.nan_to_num(wet) > 0, WATER, cost)
    if lc is not None:
        cost = np.where(lc == 80, WATER, cost)
    # ...AND the OSM lake polygons the MAP draws. WorldCover (water.tif) misses lakes in
    # remote areas, so a lake plainly visible on the map wasn't in the barrier and the
    # least-cost path ran straight across it instead of around the shore (user-reported).
    # Burning the same waterbodies the contract displays keeps route and map in agreement.
    lake = _lake_barrier(cache, cost.shape)
    if lake is not None:
        cost = np.where(lake, WATER, cost)
    return cost.astype("float64")


def _linear_cost_layer(cache, shape, motorised_only=False):
    """Linear features that beat bushwhacking, rasterized onto the analysis grid.

    TWO DIFFERENT QUESTIONS, and conflating them was the bug (T10.15). Reported twice
    with screenshots: "Access line follows road. Hunt line bushwacks for some reason" —
    the map drew a dashed trail running to the waypoint and the route ignored it and cut
    its own line through the bush beside it.

    The cause was that this read `aq_trails.gpkg` and `aq_rail.gpkg` only, while
    `export.py` DRAWS `trails.gpkg` too. Measured across the cached runs, the share of
    the drawn network the router could not see: 46% on the box he reported (30.3 km of
    trail), 92-97% on two boxes that have no AQréseau sentiers at all. The app was
    drawing a path to a place the router did not know how to walk to.

    But they are not interchangeable, which is why this takes a flag rather than simply
    adding the file. `aq_trails` is the official MOTORISED sentier network — quad and
    snowmobile. `trails.gpkg` is OSM, and on these boxes it is entirely `path` and
    `footway`: foot trails. Both beat bushwhacking on foot; only the first is something
    you ride. Feeding OSM footways to the ATV network would have swapped one wrong
    answer for another — a quad sent down a hiking trail.
    """
    import numpy as _np
    names = ["aq_trails.gpkg", "aq_rail.gpkg"]          # official motorised sentiers
    if not motorised_only:
        names += ["trails.gpkg", "rail.gpkg"]           # OSM foot paths + rail grades
    paths = [cache / n for n in names]
    paths = [p for p in paths if p.exists()]
    if not paths:
        return None
    try:
        import geopandas as gpd
        from rasterio.features import rasterize
        prof = ru.read(cache / "dem.tif")[1]
        geoms = []
        for p in paths:
            g = gpd.read_file(p)
            if not len(g):
                continue
            if g.crs and str(g.crs) != str(prof["crs"]):
                g = g.to_crs(prof["crs"])
            geoms += [gm for gm in g.geometry if gm is not None and not gm.is_empty]
        if not geoms:
            return None
        arr = rasterize([(gm, 1) for gm in geoms], out_shape=shape,
                        transform=prof["transform"], fill=0, dtype="uint8",
                        all_touched=True)      # a narrow trail must not vanish on a coarse grid
        return arr.astype(bool) if arr.any() else None
    except Exception as ex:
        print(f"[synth] trail/rail cost layer skipped: {ex}")
        return None


def _lake_barrier(cache, shape):
    """Rasterize the OSM lake polygons (waterbodies.gpkg) onto the analysis grid as a
    boolean foot barrier, so the walk-cost surface blocks every lake the map shows — not
    just the WorldCover raster. None if the layer is absent or unreadable."""
    p = cache / "waterbodies.gpkg"
    if not p.exists():
        return None
    try:
        import geopandas as gpd
        import rasterio
        from rasterio.features import rasterize

        with rasterio.open(cache / "terrain" / "slope.tif") as src:
            transform, crs = src.transform, src.crs
        g = gpd.read_file(p)
        if g.crs is None:
            return None
        g = g.to_crs(crs)
        shapes = [(geom, 1) for geom in g.geometry if geom is not None and not geom.is_empty]
        if not shapes:
            return None
        m = rasterize(shapes, out_shape=shape, transform=transform, fill=0,
                      default_value=1, dtype="uint8", all_touched=True)
        return m > 0
    except Exception:
        return None


def _water_cost(ctx, cache):
    """Cost surface that hugs water: cheap on water/wetland, expensive on land, so
    a least-cost path follows the waterway and only cuts across land for short
    portages — the canoe-in leg the user actually paddles."""
    shape_ref = ru.read(cache / "hsm.tif")[0]
    cost = np.full(shape_ref.shape, 60.0, dtype="float64")   # land = expensive
    for nm in ("water.tif", "wetland.tif"):
        w = None
        try:
            w = ru.read(cache / nm)[0]
        except Exception:
            pass
        if w is not None:
            cost[np.nan_to_num(w) > 0] = 1.0                  # on-water = cheap
    return cost


# ---------------------------------------------------------------------------------
# MODE-AWARE ROUTING (T10.20). What a leg is TRAVELLED BY, not just where it goes.
#
# THE BUG THIS REPLACES, and it was physically impossible rather than merely coarse.
# Routes were computed on the WALKING cost surface and then, if the hunter had an ATV,
# each cell that happened to sit on ridable ground was labelled "atv" after the fact.
# Measured on a real ATV run, every single hunt route came back
#     foot -> atv -> foot
# which says: walk away from camp, board an ATV parked in the middle of the bush, ride,
# get off, walk on. You can only ride from where the machine IS.
#
# THE RULE THAT MAKES IT CORRECT, and it is also what collapses the search: the vehicle
# starts wherever you do, and the moment you step off it, it stays there. So an outbound
# leg has AT MOST ONE ride segment and that segment must BEGIN AT THE ORIGIN. There is no
# remounting — walking from one trail to another leaves the quad behind on the first.
#
# That reduces a state-space search to one argmin over the transfer point P:
#     ride origin -> P  (restricted to that vehicle's network)
#     walk P -> destination
# and picking whichever P minimises the total. Foot-only is always a candidate, so a
# vehicle is used only when it actually helps.
#
# Cost is in walk-equivalent effort per cell, so ride and walk legs are directly
# comparable and the argmin needs no fudge factor. Riding is cheap but not free: fuel,
# noise and the fact that the machine has to be left somewhere are all real.
# THESE ARE RELATIVE TO `_walk_cost`, NOT TO REAL EFFORT, and that distinction is the
# whole reason the first version of this did the wrong thing. `_walk_cost` is a routing
# ATTRACTOR: it prices a road at 0.05 and open bush at ~1.14 so that paths FOLLOW roads,
# not because walking a road costs a twentieth of walking bush. Setting ride costs from
# honest effort (0.15/cell) therefore made riding three times DEARER than walking the
# same road, and the router dismounted the instant it reached the trail — measured, it
# rode 0.6 km and then walked 4.2 km along ridable trail.
#
# Priced against that surface instead: riding a trail is ~5x cheaper than walking it,
# which is about the speed ratio. A boat is a little slower to get moving than a quad.
RIDE_COST = {"atv": 0.010, "canoe": 0.030, "motor": 0.012}
IMPASSABLE = 1e7

# WHERE EACH MACHINE ACTUALLY IS AT THE START OF THE DAY. These are Joe's rules, and
# they are product decisions rather than anything the data can tell us — recorded here
# because every one of them changes what the router is allowed to do:
#
#   ATV/SxS   co-located with staging, and a vehicle or quad can reach ANY hunt camp.
#             So the machine is at the origin even where the mapped trail network stops
#             short of it — measured on a real run, camp sat 715 m off the nearest
#             mapped trail and the router refused to ride at all. A bounded rough spur
#             out to the network encodes "it got here somehow" without turning into
#             "quads go anywhere".
#   MOTORBOAT on the vehicle's trailer, so it launches only where a DRIVABLE ROAD meets
#             water. Not a trail: you cannot back a trailer down a quad track.
#   CANOE     portaged. It can reach water over trails, forest roads and a short
#             bushwhack, and between waterbodies — but a portage route is not
#             necessarily a route you want to drag a quartered bull along, which the
#             brief says out loud rather than pretending otherwise.
ATV_SPUR_M = 1500.0      # how far a quad will bulldoze off-network to reach its camp
ATV_SPUR_COST = 0.50     # bulldozing off-network: ~2x cheaper than walking the same bush
PORTAGE_M = 400.0        # a canoe carry — short, and over anything
LAUNCH_TOUCH_M = 60.0    # how close a road has to be to the water to be a put-in


def _mode_networks(ctx, cache, shape, kit):
    """{mode: boolean mask of ground that mode can travel} for the kit in hand.

    Empty when the hunter brought nothing — which is the common case, and then routing
    is exactly the foot-only routing it always was.
    """
    nets = {}
    if kit.get("atv"):
        m = np.zeros(shape, bool)
        rd = _opt(cache / "roads.tif")
        if rd is not None:
            m |= np.nan_to_num(rd) > 0
        # MOTORISED ONLY. OSM `path`/`footway` is a foot trail; riding a quad down one
        # is not a route, it is a different wrong answer (T10.15).
        lin = _linear_cost_layer(cache, shape, motorised_only=True)
        if lin is not None:
            m |= lin
        if m.any():
            nets["atv"] = m
    if kit.get("boat"):
        w = np.zeros(shape, bool)
        a = _opt(cache / "water.tif")
        if a is not None:
            w |= np.nan_to_num(a) > 0
        lake = _lake_barrier(cache, shape)            # the lakes the map actually draws
        if lake is not None:
            w |= lake
        if w.any():
            nets["motor" if kit.get("motor") else "canoe"] = w
    return nets


def _launch_mask(mode, net, cache, shape, res):
    """Cells where this boat can be PUT IN — the constraint that decides whether a boat
    is usable at all, and it is different for the two of them.

    A motorboat rides on the vehicle's trailer, so it needs a drivable road at the
    water's edge. A canoe is carried, so any water within a portage of a trail, a road
    or the bank will do.
    """
    from scipy import ndimage as ndi

    if mode == "motor":
        rd = _opt(cache / "roads.tif")
        if rd is None:
            return None                    # no drivable road mapped → nowhere to launch
        near_road = ndi.binary_dilation(
            np.nan_to_num(rd) > 0, iterations=max(1, int(round(LAUNCH_TOUCH_M / res))))
        m = net & near_road
        return m if m.any() else None
    # canoe: water within a carry of anything you can walk a boat down
    carry = np.zeros(shape, bool)
    rd = _opt(cache / "roads.tif")
    if rd is not None:
        carry |= np.nan_to_num(rd) > 0
    lin = _linear_cost_layer(cache, shape)
    if lin is not None:
        carry |= lin
    if not carry.any():
        return net                          # nothing mapped to carry along — allow it
    reach = ndi.binary_dilation(carry, iterations=max(1, int(round(PORTAGE_M / res))))
    m = net & reach
    return m if m.any() else None


def _mcp_field(cost, seeds):
    """Cumulative least-cost from `seeds` over `cost`, plus the object to traceback with."""
    from skimage.graph import MCP_Geometric

    mcp = MCP_Geometric(cost)
    field, _ = mcp.find_costs([tuple(s) for s in seeds])
    return field, mcp


def _route_with_modes(walk_cost, nets, start, end, cache=None, res=40.0,
                      dest_vehicle_ok=False):
    """(path, legs) from `start` to `end`, riding only where riding is actually possible.

    `legs` is [(mode, [rc, ...]), ...] in travel order. At most ONE vehicle segment, and
    nothing may be ridden after it — because the machine does not follow you once you
    are off it. That is the rule the old post-hoc labelling broke (it produced
    foot -> atv -> foot on every route of a real run), and it is enforced structurally
    here rather than checked afterwards.
    """
    from skimage.graph import route_through_array

    def _walk(a, b):
        try:
            pth, _ = route_through_array(walk_cost, a, b, fully_connected=True,
                                         geometric=True)
            return [tuple(x) for x in pth]
        except Exception:
            return []

    walk_path = _walk(start, end)
    if len(walk_path) < 2:
        return [], []
    best = (float(np.sum([walk_cost[r, c] for r, c in walk_path[1:]])),
            walk_path, [("foot", walk_path)])

    for mode, net in (nets or {}).items():
        on_net = bool(net[start[0], start[1]])
        ride_cost = np.where(net, RIDE_COST.get(mode, 0.2), IMPASSABLE).astype("float64")
        seeds = [tuple(start)]

        if mode == "atv":
            # The machine is AT the origin — staging, or a camp a vehicle reached — so
            # it may work out to the mapped network over a BOUNDED rough spur. Bounded
            # is the point: without a limit this becomes "quads go anywhere".
            #
            # `dest_vehicle_ok` says the far end is ALSO vehicle-accessible, which is
            # true for the staging -> camp access leg by Joe's rule that a vehicle or
            # quad reaches any hunt camp. Without it that leg came back as 620 m of
            # bushwhacking on a run where the hunter had a quad and both ends were
            # places you drive to.
            anchors = [start] + ([end] if dest_vehicle_ok else [])
            off = [a for a in anchors if not net[a[0], a[1]]]
            if off:
                from scipy import ndimage as ndi
                seed = np.ones(net.shape, bool)
                for a in off:
                    seed[a[0], a[1]] = False
                near = (ndi.distance_transform_edt(seed) * res) <= ATV_SPUR_M
                ride_cost = np.where(net, RIDE_COST["atv"],
                                     np.where(near, ATV_SPUR_COST, IMPASSABLE))
            if dest_vehicle_ok and np.isfinite(ride_cost[end[0], end[1]]) \
                    and ride_cost[end[0], end[1]] < IMPASSABLE:
                # Both ends drivable: the whole leg is a ride, so score it as one rather
                # than hunting for a dismount point that does not exist.
                try:
                    full, _fm = _mcp_field(ride_cost, [start])
                    if np.isfinite(full[end[0], end[1]]):
                        leg = [tuple(x) for x in _fm.traceback(tuple(end))]
                        if len(leg) >= 2 and full[end[0], end[1]] < best[0]:
                            best = (float(full[end[0], end[1]]), leg, [("atv", leg)])
                            continue
                except Exception:
                    pass
        elif not on_net:
            # A boat has to be PUT IN somewhere legitimate, and getting to the put-in is
            # a walk (carrying, or towing to a ramp) rather than part of the ride.
            launch = _launch_mask(mode, net, cache, net.shape, res) if cache is not None else net
            if launch is None or not launch.any():
                continue
            seeds = [tuple(x) for x in np.argwhere(launch)[:4000]]

        try:
            ride_field, ride_mcp = _mcp_field(ride_cost, seeds)
            walk_field, walk_mcp = _mcp_field(walk_cost, end if isinstance(end, list) else [end])
        except Exception:
            continue
        total = np.where(np.isfinite(ride_field + walk_field) & net,
                         ride_field + walk_field, np.inf)
        if not np.isfinite(total).any():
            continue
        pt = tuple(int(v) for v in np.unravel_index(int(np.argmin(total)), total.shape))
        cost_here = float(total[pt])
        if not np.isfinite(cost_here) or cost_here >= best[0]:
            continue                      # the machine does not help; stay on foot
        try:
            ride_leg = [tuple(x) for x in ride_mcp.traceback(pt)]
            walk_leg = [tuple(x) for x in walk_mcp.traceback(pt)][::-1]
        except Exception:
            continue
        if len(ride_leg) < 2:
            continue                      # the transfer point IS the origin — just walk

        legs = []
        if ride_leg[0] != tuple(start):
            approach = _walk(start, ride_leg[0])       # walking to where the boat is
            if len(approach) >= 2:
                legs.append(("foot", approach))
        legs.append((mode, ride_leg))
        if len(walk_leg) >= 2:
            legs.append(("foot", walk_leg))
        best = (cost_here, [rc for _m, seg in legs for rc in seg], legs)
    return best[1], best[2]


def _split_foot(leg_rc, trail_mask):
    """Break a foot leg into TRAIL and BUSHWHACK runs.

    Walking a cut trail and bushwhacking are different hunts — different speed, different
    noise, different odds of being seen first — and the map should not draw them with one
    line. Purely descriptive: the path is already chosen, this only names what it crosses.
    """
    if trail_mask is None or len(leg_rc) < 2:
        return [("foot", leg_rc)]
    on = [bool(trail_mask[r, c]) for r, c in leg_rc]
    for i in range(1, len(on) - 1):       # smooth 1-cell flicker into real segments
        if on[i - 1] == on[i + 1] != on[i]:
            on[i] = on[i - 1]
    out, cur, cur_on = [], [], None
    for rc, o in zip(leg_rc, on):
        if cur_on is None or o != cur_on:
            if len(cur) >= 2:
                out.append(("foot_trail" if cur_on else "foot_bush", cur))
            cur, cur_on = ([cur[-1]] if cur else []), o
        cur.append(rc)
    if len(cur) >= 2:
        out.append(("foot_trail" if cur_on else "foot_bush", cur))
    return out or [("foot", leg_rc)]


def _area_dest(features, rank, lonlat_to_rc):
    """Where an access leg should END for a focus area: a point guaranteed inside
    it. representative_point() is already computed upstream and is inside even for
    a crescent-shaped lobe, so the leg never terminates outside its own area."""
    if rank is None:
        return None
    for f in features:
        p = f["properties"]
        if p.get("legend") == "focus_area" and p.get("rank") == rank:
            cen = p.get("centroid")
            if cen:
                return lonlat_to_rc(cen[0], cen[1])
    return None


# --- crew plan -----------------------------------------------------------------
# "If I had N hunters, where would I put them?" answered from the geometry that was
# actually placed — never invented. Capacity comes from calling separation, which is
# a real constraint: a moose call carries roughly a kilometre, so two callers inside
# that envelope are competing for the same bull rather than covering more ground.
KM2_PER_SETUP = 1.8          # ~750 m working radius per calling setup
def _crew_plan(area_props, sites, party, shooter_m=70):
    """sites = the features already placed inside THIS area.

    `shooter_m` is passed in rather than read from a context this function does not
    have — the same NameError the routing code was bitten by, and the reason it is a
    parameter and not a lookup."""
    a = float(area_props.get("area_km2") or 0)
    by = {}
    for f in sites:
        by.setdefault(f["properties"]["legend"], []).append(f)
    n_call  = len(by.get("rut_calling", []))
    n_glass = len(by.get("glassing", []))
    n_feed  = len(by.get("saline_blind", [])) + len(by.get("funnel", []))
    # what the ground can hold, and what we actually found room to place
    by_area  = max(1, int(a // KM2_PER_SETUP))
    capacity = max(1, min(by_area, n_call + n_glass + n_feed))
    seats = []
    for i, f in enumerate(by.get("rut_calling", []), 1):
        seats.append({"role": "caller", "n": i,
                      "at": [round(v, 5) for v in f["geometry"]["coordinates"]]})
    for i, f in enumerate(by.get("glassing", []), 1):
        seats.append({"role": "glasser", "n": i,
                      "at": [round(v, 5) for v in f["geometry"]["coordinates"]]})
    for i, f in enumerate(by.get("saline_blind", []) + by.get("funnel", []), 1):
        seats.append({"role": "sitter", "n": i,
                      "at": [round(v, 5) for v in f["geometry"]["coordinates"]]})

    notes = []
    fits = capacity >= party
    if not fits:
        notes.append(
            f"This area realistically holds about {capacity} hunter"
            f"{'s' if capacity != 1 else ''} at once — {a:.1f} km² at roughly "
            f"{KM2_PER_SETUP} km² per calling setup. With {party} in the party, split "
            f"across the ranked areas rather than stacking; two callers inside a "
            f"kilometre of each other are working the same bull.")
    if party >= 3 and n_glass:
        notes.append(
            "Glass in pairs. One on glass and one on the call beats two hunters "
            "half-watching two basins, and it gives you a spotter for the shot.")
    if party >= 2:
        notes.append(
            f"Caller and shooter split up: shooter ~{shooter_m} m downwind of the "
            "caller, on the side the bull is most likely to circle to. The caller is "
            "bait, not the gun.")
    if party == 1:
        notes.append(
            "Solo: work one calling stand per sit and stay put — 30 minutes minimum. "
            "Solo callers get busted circling downwind, so pick a stand with the wind "
            "in your face and cover behind you.")
    if party > 4:
        notes.append(
            f"A party of {party} is a lot of scent and noise for one drainage. "
            "Consider hunting two areas simultaneously and meeting at camp.")
    return {"party": party, "capacity": capacity, "fits": fits,
            "seats": seats[:max(party, 1) * 2], "notes": notes,
            "counts": {"calling": n_call, "glassing": n_glass, "sits": n_feed}}


def _add_routes(ctx, features, cache, prof, access, toll, camp_of_area=None):
    """camp_of_area: {rank: (row, col)} — the authoritative hunt anchor per area.

    IT IS AN ARGUMENT AND NOT A FEATURE SCAN FOR A REASON. This used to reconstruct the
    anchors by looking for `base_camp` pins among the features. Then a hunt from a camp
    the hunter placed themselves stopped drawing that pin — correctly, because handing
    someone their own input back as a recommendation is noise — and routing lost the only
    thing it was anchored to. camp_by_area came back empty, sites_of() skipped every area
    for want of a camp, and EVERY route silently disappeared: no hunt lines, no access
    legs, on exactly the hunt style where the camp is the least ambiguous thing on the
    map. Nothing raised; the layer just read NO DATA.

    Where a hunter sleeps and whether we draw a pin for it are two different questions.
    Only the first one belongs to routing.
    """
    from skimage.graph import route_through_array

    cost = _walk_cost(ctx, cache)
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", prof["crs"], always_xy=True)
    T = prof["transform"]
    inv = ~T

    def lonlat_to_rc(lon, lat):
        x, y = tr.transform(lon, lat)
        c, r = inv * (x, y)
        h, w = cost.shape
        return max(0, min(h - 1, int(r))), max(0, min(w - 1, int(c)))

    # Camps are the base you hunt FROM. Approach (still-hunt) lines run CAMP → each
    # hunt position, never road → position. Road/water access is a separate leg.
    if camp_of_area:
        camp_rc = list(dict.fromkeys(camp_of_area.values()))
    else:
        camps = [f["geometry"]["coordinates"] for f in features
                 if f["properties"]["legend"] == "base_camp"]
        camp_rc = [lonlat_to_rc(lo, la) for lo, la in camps]
    # Per-area staging, emitted upstream. The old code used a single
    # np.argmin(access) for the whole AOI, so every access leg started from the
    # same arbitrary cell and the map showed one path threading all the areas.
    stages = [(f["properties"].get("focus_area"),
               lonlat_to_rc(*f["geometry"]["coordinates"]))
              for f in features if f["properties"]["legend"] == "parking"]
    # last-resort anchor only if no staging point was mapped at all
    road_start = (stages[0][1] if stages
                  else np.unravel_index(np.argmin(access + 1e-6), access.shape))

    # A hunt line belongs to ONE focus area: it runs from that area's own camp to a
    # stand in that same area. Picking the "nearest" camp across the whole AOI is
    # what drew cross-country lines between unrelated drainages.
    # For a spike hunt this is the base camp; for a vehicle hunt there is no camp and
    # the truck (the staging pin) is where every day starts and ends. Either way the
    # hunt lines must originate INSIDE the area they serve.
    camp_by_area = dict(camp_of_area) if camp_of_area else {}
    if not camp_by_area:
        camp_by_area = {f["properties"].get("focus_area"): lonlat_to_rc(*f["geometry"]["coordinates"])
                        for f in features if f["properties"]["legend"] == "base_camp"}
    if not camp_by_area:
        camp_by_area = {f["properties"].get("focus_area"): lonlat_to_rc(*f["geometry"]["coordinates"])
                        for f in features if f["properties"]["legend"] == "parking"}

    def sites_of(legend, per_area):
        out = []
        seen = {}
        for f in features:
            p = f["properties"]
            if p.get("legend") != legend:
                continue
            rank = p.get("focus_area")
            if rank not in camp_by_area:      # no camp for that area -> no line to draw
                continue
            if seen.get(rank, 0) >= per_area:
                continue
            seen[rank] = seen.get(rank, 0) + 1
            out.append((rank, f))
        return out

    # WHAT EACH LEG IS TRAVELLED BY (T10.20). This used to compute a WALKING path and
    # then label the cells that happened to lie on ridable ground as "atv", which
    # produced foot -> atv -> foot on every route of a real ATV run: board a machine
    # parked in the middle of the bush. Routing is now mode-aware, and the vehicle stays
    # where you step off it. See _route_with_modes.
    _kit_r = _hunter_kit(ctx.aoi.hunter)
    _nets = _mode_networks(ctx, cache, cost.shape, _kit_r)
    # Descriptive only: which foot ground is a cut line and which is bushwhacking.
    _trail_mask = None
    try:
        _trail_mask = np.zeros(cost.shape, bool)
        _rd = _opt(cache / "roads.tif")
        if _rd is not None:
            _trail_mask |= np.nan_to_num(_rd) > 0
        _lin = _linear_cost_layer(cache, cost.shape)
        if _lin is not None:
            _trail_mask |= _lin
        if not _trail_mask.any():
            _trail_mask = None
    except Exception:
        _trail_mask = None

    _RES_KM = float(ctx.model.raster_resolution_m) / 1000.0

    def _emit(rank, legend, start_rc, end_rc, dest_vehicle_ok=False):
        """Route start->end, mode-aware, and append it with its legs."""
        path, legs = _route_with_modes(cost, _nets, start_rc, end_rc,
                                      cache=cache, res=_RES_KM * 1000.0,
                                      dest_vehicle_ok=dest_vehicle_ok)
        if len(path) < 2:
            return None
        detailed = []
        for mode, rc in legs:
            detailed.extend(_split_foot(rc, _trail_mask) if mode == "foot" else [(mode, rc)])
        props = {"legend": legend, "focus_area": rank}
        by_mode = {}
        out_legs = []
        for mode, rc in detailed:
            if len(rc) < 2:
                continue
            km = round((len(rc) - 1) * _RES_KM, 2)
            by_mode[mode] = round(by_mode.get(mode, 0.0) + km, 2)
            out_legs.append({"mode": mode, "km": km,
                             "coords": [list(toll(x)) for x in rc]})
        if out_legs:
            props["legs"] = out_legs
            props["km_by_mode"] = by_mode
            # The pack-out reality is the WALK, not the total — and with a vehicle the
            # walk is also the part you repeat carrying meat.
            props["walk_km"] = round(sum(v for k, v in by_mode.items()
                                         if k.startswith("foot")), 2)
            ride = {k: v for k, v in by_mode.items() if not k.startswith("foot")}
            if ride:
                props["ride_km"] = round(sum(ride.values()), 2)
                props["ride_mode"] = max(ride, key=ride.get)
                # WHERE THE MACHINE SPENDS THE DAY. It is not at camp and it is not at
                # the stand; it is at the transfer point, and on the way out you come
                # back to it. That is a place on the map, so put it on the map.
                for i, lg in enumerate(out_legs):
                    if lg["mode"] == props["ride_mode"] and i + 1 < len(out_legs):
                        props["vehicle_left_at"] = lg["coords"][-1]
                        break
        features.append({"type": "Feature",
                         "geometry": {"type": "LineString",
                                      "coordinates": [list(toll(x)) for x in path]},
                         "properties": props})
        return props

    def add_route(rank, dest_feat, legend):
        lon, lat = dest_feat["geometry"]["coordinates"]
        end_rc = lonlat_to_rc(lon, lat)
        start_rc = camp_by_area.get(rank)
        if start_rc is None or start_rc == end_rc:
            return
        _emit(rank, legend, start_rc, end_rc)

    for rank, f in sites_of("rut_calling", 2):
        add_route(rank, f, "route_best")
    for rank, f in sites_of("thermal_refuge", 1):
        add_route(rank, f, "route_midday_hot")

    # Access leg: road staging → camp. If there's no drivable road near camp it's
    # a canoe-in, so route it along water (hugs the waterway, short land portages)
    # instead of a straight line that ignores the hydrography.
    try:
        wcost = _water_cost(ctx, cache)
        no_road = not (np.isfinite(access).any() and float(np.nanmin(access)) < 5000)
        # One SHORT leg per focus area: that area's own staging point -> the area.
        # Not staging -> camp, and never one shared origin: the walk from the truck
        # is the thing being minimised, so each leg has to be measured on its own.
        # staging -> that area's camp (falling back to the area centroid if a camp
        # could not be placed). The truck-to-bed leg, per area, and nothing longer.
        legs = [(rank, st, dest) for rank, st in stages
                for dest in [camp_by_area.get(rank) or _area_dest(features, rank, lonlat_to_rc)]
                if dest]
        if not legs and camp_rc:
            # NO STAGING PIN — which is the normal case for a camp the hunter placed:
            # you drove to your cabin, so there is no separate parking to walk from.
            # The access leg is then "how you get IN to camp", and it has to start at the
            # road NEAREST THE CAMP. The old fallback started at road_start — the single
            # globally most accessible cell in the whole box — which on a real 9 km AOI
            # put the origin in a far corner and drew a 21 km "access route" to a cabin
            # you drive to. That is the same one-shared-origin mistake the comment above
            # warns about, just reached by a different path.
            _res_m = float(getattr(ctx.model, "raster_resolution_m", 40.0) or 40.0)
            _near = np.isfinite(access) & (access <= max(60.0, _res_m))
            _rr, _cc = np.nonzero(_near)

            def _road_near(rc):
                if _rr.size == 0:
                    return road_start
                d = (_rr - rc[0]) ** 2 + (_cc - rc[1]) ** 2
                i = int(np.argmin(d))
                return (int(_rr[i]), int(_cc[i]))

            legs = [(None, _road_near(s), s) for s in camp_rc]
        for rank, start, dest in legs:
            if start == dest:
                continue
            if no_road:
                # No drivable road anywhere near: this is a paddle-in, so it follows the
                # hydrography rather than cutting overland. One mode the whole way.
                path, _ = route_through_array(wcost, start, dest,
                                              fully_connected=True, geometric=True)
                coords = [list(toll((r, c))) for r, c in path]
                if len(coords) >= 2:
                    _m = "motor" if _kit_r.get("motor") else "canoe"
                    features.append({"type": "Feature",
                                     "geometry": {"type": "LineString", "coordinates": coords},
                                     "properties": {
                                         "legend": "route_paddle", "focus_area": rank,
                                         "legs": [{"mode": _m, "km": round((len(coords)-1)*_RES_KM, 2),
                                                   "coords": coords}],
                                         "km_by_mode": {_m: round((len(coords)-1)*_RES_KM, 2)}}})
            else:
                # THE LEG YOU WOULD MOST OBVIOUSLY RIDE, and it used to be the one with
                # no modes at all — a single undifferentiated line from the truck in.
                # Staging -> camp: both ends are places a vehicle got to.
                _emit(rank, "route_access", start, dest, dest_vehicle_ok=True)
    except Exception:
        pass


def _rut_section(ctx) -> list:
    """Rut-timing brief section from rut_timing.summary()."""
    from . import rut_timing
    r = rut_timing.summary(ctx)
    w = r["windows"]
    # NOT "latitude-adjusted" — the peak is deliberately anchored at ~2 Oct for every
    # latitude (moose conception is latitude-invariant across the range; see
    # rut_timing.py and lat_note). The old label claimed a shift the model refuses to
    # make, which is exactly the kind of thing a hunter checks and loses trust over.
    # The phase calendar is shown ALWAYS — it's a property of the LOCATION/year, not
    # of the chosen dates. A hunter deciding when to go needs to see the windows and
    # the average conception date even before they've picked dates.
    out = ["", "## Rut timing", "",
           f"Average conception (peak breeding) ≈ **{r['peak_date']}** — anchored, "
           f"not shifted for latitude (moose conception is latitude-invariant; this is "
           f"a {ctx.aoi.center.lat:.1f}°N hunt).", "",
           "**Phase calendar (this location, this year):**",
           f"- **Seeking / pre-rut:** {w['pre_rut'][0]} → {w['pre_rut'][1]}  "
           f"*(best calling — bulls searching, cows not yet receptive)*",
           f"- **Peak rut:** {w['peak_rut'][0]} → {w['peak_rut'][1]}  "
           f"*(bulls tending cows — hunt the cows, call less)*",
           f"- **Post-rut:** {w['post_rut'][0]} → {w['post_rut'][1]}  "
           f"*(recovery feeding; watch for a late re-cycle flurry ~24 d after peak)*"]
    if r["targets"]:
        out += ["", "**Your target dates:**"]
        for t in r["targets"]:
            out.append(f"- {t['date']} — **{t['phase']}** (calling responsiveness "
                       f"{int(t['responsiveness']*100)}%). {t['guidance']}")
    out += ["", f"> {r['lat_note']}"]
    return out


def _behavior_section(ctx, cache) -> list:
    """The 'where he'll be by time & temperature' brief section, grounded in the
    behavior stage's periods.json + the hunt-window forecast highs."""
    pj = cache / "behavior" / "periods.json"
    if not pj.exists():
        return []
    meta = json.loads(pj.read_text())
    heat = meta.get("heat", {})

    # expected midday from forecast highs over the target dates
    tmax = wclass = None
    try:
        from datetime import date

        from . import weather as wx
        from .behavior import refuge_weight
        wthr = wx.for_dates(ctx.aoi.center.lat, ctx.aoi.center.lon,
                            ctx.aoi.season.target_dates, today=date.today().isoformat())
        temps = [d.get("t_max_c") for d in wthr.get("days", []) if d.get("t_max_c") is not None]
        if temps:
            tmax = round(sum(temps) / len(temps), 1)
            w = refuge_weight(tmax, {"heat_onset_c": heat.get("onset_c", 14),
                                     "heat_severe_c": heat.get("severe_c", 20)})
            wclass = ("hard midday retreat to cover" if w >= 0.66 else
                      "partial midday cover use" if w >= 0.33 else
                      "moose stay out feeding/loafing through midday")
    except Exception:
        pass

    out = ["", "## Where he'll be — by time & temperature", "",
           "Moose are crepuscular and heat-sensitive, so *when* and *how warm* it is "
           "moves the animal as much as *where* the habitat is:", ""]
    for p in meta.get("periods", []):
        out.append(f"- **{p['label']}** — {p['text']}")
        if p.get("thermal"):
            out.append(f"  · *Thermals/approach:* {p['thermal']}.")
    onset = heat.get("onset_c", 14)
    out += ["", f"**Heat thresholds** (°C): shade-seeking begins ~{onset}, bedded "
            f"heat-stress ~{heat.get('bedded_c', 17)}, strong cover selection "
            f"~{heat.get('severe_c', 20)}, panting/body-temp rise ~{heat.get('bodytemp_c', 25)}."]
    if tmax is not None:
        out.append(f"**This hunt window** averages a **{tmax} °C** high → *{wclass}*. "
                   "Plan the midday around the thermal refuges; hunt the feeding edges hard "
                   "at first and last light.")
    return out


# --- Field-plan sections (#67) -----------------------------------------------
# Each is a STRUCTURED producer ({title, intro, items[], note}) so there is ONE
# source of truth rendered two ways: _brief_section_md() joins it into the markdown
# brief.md export, and contract.build() emits it verbatim for the app's Brief tab to
# render. Content is established moose field-craft grounded in the hunt's rut phase and
# the computed areas — never a 'chance he responds' number (the model has none).

def calling_sequence(ctx) -> dict:
    """A concrete calling SCRIPT keyed to the hunt's rut phase (#67)."""
    from .rut_timing import dominant_phase

    phase = dominant_phase(ctx)
    stand_min = 40
    try:
        from .strategy import strategy as _strategy
        stand_min = int(_strategy(ctx).get("stand_minutes", 40) or 40)
    except Exception:
        pass
    intro = (
        "Reach the stand in the dark, **downwind** of the cover you expect him in, back to "
        "something solid. A committing bull works to your downwind before he shows, so keep "
        f"that flank open to view. Sit each stand **{stand_min} min minimum** — the response "
        "is slow and the silence does the work.")
    if phase == "seeking":
        head = "Pre-rut / seeking — the most callable window of the year; bulls are up and searching."
        items = [
            "Open with 2–3 long **cow-in-heat wails**, 30–45 s apart, then sit 10 min dead silent.",
            "Work in short **bull grunts** on the walk-in and between sequences to sound like a rival moving, and **rake** a shrub or sapling with a scapula/stick for 20–30 s.",
            "Re-call every 20–30 min; give a working bull 45–60 min before you move. A hung-up bull often circles **silently to your downwind** — watch that flank, not the calling lane."]
    elif phase == "peak":
        head = "Peak rut — bulls are tending cows and go quiet; call SPARINGLY."
        items = [
            "**Soft cow whines only**, well spaced. Drop the aggressive bull grunting now — it just pushes a paired bull away.",
            "This is an **ambush week** more than a calling week: hunt where the cows are (feeding edges, cover) and sit long.",
            "A bull that does answer may come in **silent** — stay put, stay ready, don't call him past you."]
    elif phase == "post":
        head = "Post-rut / re-cycle — soft cow calls to bulls still seeking a last estrous cow."
        items = [
            "Spare **cow whines**, patient and well spaced; the aggressive calling is done for the year.",
            "Spent bulls are back on **feed** — cover the food edges and travel between food and cover.",
            "Expect long silences; a late-season bull is worn down and slow to commit."]
    else:
        head = "Outside the rut — calling is unreliable; treat any call as a locator only."
        items = [
            "Hunt **feeding edges** at first and last light and the travel lines between food and cover; rely on sign and glassing, not calling."]
    return {
        "title": "Calling sequence", "intro": intro, "headline": head, "items": items,
        "note": ("Always: fewer, patient sequences beat constant noise; let a long silence "
                 "ride after each; and never call from the open — a bull expects to **see** the "
                 "moose that called, so set up where he has to step out to look."),
    }


def scent_section(ctx, sc) -> dict:
    """Scent/lure as a brief section (#73) — placement, refresh cadence, handling, and
    the legal position, which for cervid urine is the part that can end a hunt."""
    if not sc:
        return {}
    items = [sc["placement"]] + list(sc.get("handling", []))
    cad = sc.get("cadence") or []
    if cad:
        worst = max(c["refresh_hours"] for c in cad)
        best = min(c["refresh_hours"] for c in cad)
        rainy = [c["date"] for c in cad if c.get("rain_reset")]
        line = (f"**Refresh every {best} h** on your coldest, calmest day and "
                f"**every {worst} h** on the warmest or windiest."
                if best != worst else f"**Refresh every {best} h** across your hunt window.")
        if rainy:
            line += (" Rain is forecast on " + ", ".join(rainy[:3]) +
                     " — re-apply once it passes; a wet wick is a dead wick.")
        items.append(line)
    lg = sc.get("legality")
    note = None
    if lg:
        note = f"**Legal — {lg['status'].replace('_', ' ')}.** {lg['text']} {lg['verify']} ({lg['why']})"
    return {
        "title": "Scent & lure placement",
        "intro": ("Calling puts a cow in his ears; scent is what he checks before he "
                  "believes it. A bull that answers swings **downwind of the call** to "
                  "verify her — that arc is the most predictable move he makes, and it is "
                  "where the hunt is usually lost, because what he finds there is you."),
        "items": items,
        "note": note,
    }


def day_plan(ctx, n_area: int) -> dict:
    """An ORDERED plan across the target dates (#67): locate, rotate by wind, pack-out
    buffer. Grounded in the computed area count + phase + hunt style."""
    from datetime import date as _date

    from .rut_timing import dominant_phase

    if n_area <= 0:
        return {}
    ds = sorted(d for d in (ctx.aoi.season.target_dates or []) if d)
    ndays = 0
    try:
        if len(ds) >= 2:
            ndays = (_date.fromisoformat(ds[-1]) - _date.fromisoformat(ds[0])).days + 1
    except Exception:
        ndays = 0
    phase = dominant_phase(ctx)
    prime = ("the calling stands" if phase == "seeking" else
             "the feeding edges and cover where the cows are" if phase in ("peak", "post") else
             "the feeding edges at first and last light")
    vehicle = getattr(ctx.aoi.hunter, "hunt_style", "spike") == "vehicle"
    base = "the truck" if vehicle else "camp"
    span = f"over {ndays} days" if ndays else "across your hunt window"
    items = [
        f"**Day 1 — arrive & locate.** Set {base}{'' if vehicle else ' and staging'}, then "
        "**glass from the knobs and listen at last light** before you commit — a located bull "
        "beats a guessed one. Still-hunt the nearest area's edges into dark."]
    if n_area > 1 or not ndays or ndays > 2:
        items.append(
            f"**Middle days — prime rotation.** First and last light at {prime}; midday, glass, "
            "or on a warm day (>~15 °C) slip into the **thermal refuges** where he beds. Move to "
            "the next ranked area when the wind turns wrong or an area goes cold after a full "
            "sit. Work Area 1 first, then down the ranking.")
    items.append(
        f"**Final day — pack-out buffer.** Hunt close to {base} / the road so a down animal is "
        "**out before dark** — a bull is 400–600+ lb, the meat is the law, and a deep kill late "
        "in the day is a next-morning problem. Don't shoot what you can't retrieve in the time "
        "and light you have left.")
    return {
        "title": "Day-by-day plan",
        "intro": (f"{n_area} focus area{'s' if n_area != 1 else ''} {span}, **{phase}** phase. "
                  "**Rotate by wind** — each morning hunt the area whose approach sits downwind, "
                  "so your scent blows away from the ground you're working."),
        "items": items, "note": "",
    }


def ground_truth_checklist(ctx, n_gt: int) -> dict:
    """A field CHECKLIST (#67): what sign to confirm, framed as verifiable fact-finding."""
    where = (f"the {n_gt} ground-truth point{'s' if n_gt != 1 else ''} and every calling stand"
             if n_gt else "every stand and along your access lines")
    return {
        "title": "Ground-truth checklist",
        "intro": f"Desk scouting gets you ~90%; the last 10% is boots. At {where}, confirm:",
        "items": [
            "**Fresh sign** — tracks and droppings, and *age* them: glistening, soft scat is hours old, not weeks. A pile of pellets plus beds says resident; a lone track says passing through.",
            "**Browse** — twigs nipped clean at a ~45° angle at moose height (0.5–2.5 m); hedged willow, birch, aspen, red-osier, mountain-ash. Heavy hedging = a feeding area worth a stand.",
            "**Rubs & thrashing** — barked saplings and torn shrubs where a bull has worked; wet, bright rubs are current.",
            "**Wallows** — a pawed, urine-soaked pit, sharply pungent in the rut. The desk **cannot** predict these, so **mark any you find** — a fresh wallow is a rut hub worth building a sit around.",
            "**Trails through the funnels** — a worn path pinched between water or wetland is exactly where an ambush pays; confirm it's used before you sit it.",
            "**Access reality** — scout the last spur on foot before you trust it: is it actually driveable, and are the crossing markers on your route fordable at the water you're seeing today?",
        ],
        "note": ("Log what you find so the next plan learns from the boots, not just the "
                 "pixels."),
    }


def _brief_section_md(sec: dict, numbered: bool = False) -> list:
    """Render a structured field-plan section into markdown lines for brief.md."""
    if not sec:
        return []
    out = ["", f"## {sec['title']}", ""]
    if sec.get("intro"):
        out += [sec["intro"], ""]
    if sec.get("headline"):
        out += [f"**{sec['headline']}**"]
    for i, it in enumerate(sec.get("items", []), 1):
        out.append(f"{i}. {it}" if numbered else f"- {it}")
    if sec.get("note"):
        out += ["", f"*{sec['note']}*"]
    return out


def _write_brief(ctx, features, cache, outdir, routes_msg):
    from .legal import assess

    la = assess(ctx)
    fas = sorted([f for f in features if f["properties"]["legend"] == "focus_area"],
                 key=lambda f: f["properties"]["rank"])
    counts = {}
    for f in features:
        counts[f["properties"]["legend"]] = counts.get(f["properties"]["legend"], 0) + 1

    lines = [
        f"# Moose Scout — {ctx.aoi.title}", "",
        f"*DIY moose hunt scouting brief · target {', '.join(ctx.aoi.season.target_dates)} "
        f"· {ctx.aoi.hunter.residency}.*", "",
        "> Model output is a prioritized hypothesis to **ground-truth on foot**, "
        "not a guarantee. Every site is tagged *à valider sur le terrain*.", "",
        "## Legal / access gate", "",
        f"- **Zone {la.zone}** · {'north' if la.north_of_52 else 'south'} of the 52nd parallel · "
        f"{'**DIY possible**' if la.diy_possible else 'restricted'}.",
        f"- Huntable tenure: {', '.join(t.value for t in la.huntable_tenures) or 'n/a'}.",
    ]
    for fl in la.flags:
        lines.append(f"- {fl}")

    # What I'm looking for + factors weighted.
    meth = methodology(ctx)
    lines += ["", "## What I'm looking for", "", meth["summary"], "",
              "**Factors weighted (habitat score):**"]
    for fac in meth["factors_weighted"]:
        lines.append(f"- {fac}")
    lines += ["", meth["then"], ""]
    for cv in meth["caveats"]:
        lines.append(f"> {cv}")

    # Density-driven strategy (research-grounded).
    try:
        from .strategy import strategy as _strategy
        st = _strategy(ctx)
        est = " *(estimated — no aerial survey for this zone)*" if st.get("density_is_estimate") else ""
        # Strategy leads with the PHASE (the bigger lever for how you hunt this week),
        # then the density profile modulated by it. The calling/stand numbers below are
        # already phase-adjusted in strategy().
        lines += ["", "## Strategy", ""]
        if st.get("phase_headline"):
            lines += [f"**{st['phase_headline']}**", "", st.get("phase_guidance", ""), ""]
        lines += [f"Density read: **{st['headline']}** (~{st['density_per_10km2']} moose/10 km²{est})", "",
                  f"- **Approach:** {st['approach']}",
                  f"- **Calling:** {st['calling']}  *(calling weight {st['calling_weight']} · ambush {st['ambush_weight']}, phase-adjusted)*",
                  f"- **Stands:** ~{st['stand_minutes']} min · **Movement:** {st['movement']}",
                  f"- **Attractants:** {st['attractants']}",
                  f"- *Why:* {st['why']}"]
        # The regulatory warning MUST ride with any attractant advice — salines/scents/
        # urine are regulated and vary by zone (audit #51). Never print the tactic bare.
        if st.get("scent_warning"):
            lines += [f"- ⚠️ **{st['scent_warning']}**"]
    except Exception:
        pass

    # Concrete calling script for the hunt's rut phase (#67) — pairs with Strategy.
    try:
        lines += _brief_section_md(calling_sequence(ctx), numbered=True)
    except Exception:
        pass

    # Rut-timing for the AOI (latitude-adjusted phenology).
    try:
        lines += _rut_section(ctx)
    except Exception:
        pass

    # Behavioral day-plan: where he is by time of day + temperature.
    try:
        lines += _behavior_section(ctx, cache)
    except Exception:
        pass

    # Confidence in the analysis (data-quality driven).
    try:
        from . import confidence as _conf
        ov = _conf.overall(ctx, cache)
        lines += ["", "## Confidence", "",
                  f"**Overall: {ov['band'].upper()} ({int(ov['score']*100)}%)** — data quality, "
                  "not a guarantee animals are present.", ""]
        for d in ov["drivers"]:
            lines.append(f"- {d}")
    except Exception:
        pass

    lines += ["", "## Focus areas — why each one", ""]
    for f in fas:
        p = f["properties"]
        lon, lat = p["centroid"]
        lines.append(f"### {p['rank']}. {p['area_km2']} km² · huntability "
                     f"{p['mean_huntability']} · {lat:.4f}, {lon:.4f}")
        if p.get("why"):
            lines.append(f"{p['why']}")
        if p.get("pros"):
            lines.append("**Pros:** " + "; ".join(p["pros"]) + ".")
        if p.get("cons"):
            lines.append("**Watch-outs:** " + "; ".join(p["cons"]) + ".")
        # Per-area pack-out read (#67). Key it off the DISTANCE TO A MAPPED ROAD —
        # the real haul — not the retrieval score, which folds in pressure and a
        # neutral fallback and so reads "easy" for ground that is 30 km from a road.
        dr = p.get("dist_road_m")
        reachable = p.get("reachable", True)
        cross = ("Check the crossing markers on your access leg before you commit to "
                 "shooting deep in — a river between you and the truck decides whether a "
                 "bull comes out whole or not at all.")
        if not reachable:
            lines.append("**Pack-out:** this ground is flagged **not reachable** "
                         f"({p.get('unreachable_why') or 'see watch-outs'}) — a 400–600 lb "
                         "animal cannot come out the way you'd walk in. " + cross)
        elif dr is None or dr >= 100000:
            lines.append("**Pack-out:** not modelled — no road network is mapped near this "
                         "box, so plan the carry or a float conservatively and scout the "
                         "access in person. " + cross)
        elif dr < 800:
            lines.append("**Pack-out:** roadside-easy — a mapped road or spur runs to the "
                         "edge. " + cross)
        else:
            km = dr / 1000.0
            tag = "workable carry" if km <= 3 else "hard — plan the pack-out"
            lines.append(f"**Pack-out:** {tag} — ~{km:.0f} km to the nearest mapped road. "
                         + cross)
        if p.get("conf"):
            c = p["conf"]
            lines.append(f"**Confidence:** {c['band']} ({int(c['score']*100)}%) — "
                         + "; ".join(c.get("drivers", [])) + ".")
        lines.append("")

    # Ordered day plan + boots-on-ground checklist (#67) — the actionable close.
    try:
        lines += _brief_section_md(day_plan(ctx, len(fas)))
    except Exception:
        pass
    try:
        lines += _brief_section_md(ground_truth_checklist(ctx, counts.get("validate_ground", 0)))
    except Exception:
        pass

    lines += ["", "## Placed features (Les Cartes Xperts legend)", ""]
    legend_names = {
        "rut_calling": "Rut / calling stations (≥30 min)", "thermal_refuge": "Thermal refuges",
        "saline_blind": "Feeding edge (dawn/dusk)", "funnel": "Natural funnels / passes",
        "glassing": "Glassing knobs", "validate_ground": "Ground-truth points",
        "base_camp": "Base camps", "route_best": "Best approach routes",
        "route_midday_hot": "Midday / hot-weather routes",
    }
    for k, name in legend_names.items():
        if counts.get(k):
            lines.append(f"- {counts[k]} × {name}")
    if routes_msg:
        lines += ["", f"*{routes_msg.strip()}*"]
    # Driven by the analysis + the AOI's own zone, not hardcoded to one road/zone (audit
    # #51 — the old text asserted Route 389 / zone 19 for every box). Legal facts are the
    # stable DIY-critical ones; the season/MWA specifics still say "verify" because they
    # rotate by year.
    _zone = str((la.zone if la else None) or getattr(ctx.aoi, "zone_hint", None) or "?")
    _access_line = (routes_msg.strip() if routes_msg else
                    "Reachable by road / logging spurs where mapped — plan fuel and check "
                    "seasonal and washout closures on remote resource roads.")
    lines += ["", "## Logistics & legal", "",
              f"- **Access:** {_access_line}",
              "- **Comms & safety:** little to no cell coverage in remote boreal Québec — "
              "carry a satellite messenger (InReach/Zoleo), leave a trip plan and a check-in "
              "schedule, and check SOPFEU fire-access restrictions and road closures before "
              "you travel. Cold, fast water at crossings is a real fall hazard — see the "
              "crossing notes on the map.",
              "- **Legal (stable — but verify seasons):** register the animal within **48 h** "
              "of leaving the hunt site; transport it whole or in **identifiable quarters** "
              "with the head (or lower jaw + antlers) and the **transport coupon attached**; "
              "you must keep all **edible flesh**. Confirm zone " + _zone + " season dates, "
              "any sub-zone split, and the antlerless (MWA) rule on quebec.ca — these rotate "
              "by year.", ""]
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "brief.md").write_text("\n".join(lines))
