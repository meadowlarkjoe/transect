"""Stage 5/6 — focus areas + annotated features (Les-Cartes-Xperts vocabulary).

From the huntability surface, extract ranked FOCUS AREAS, then place typed
features that speak Charles Dorris's legend (config/output_legend.yaml):
  rut_calling · thermal_refuge · saline_blind · validate_ground · funnel ·
  glassing · base_camp · parking, plus least-cost approach ROUTES.

Writes cache/<aoi>/focus_areas.geojson, cache/<aoi>/features.geojson,
outputs/<aoi>/brief.md.
"""
from __future__ import annotations

import json

import numpy as np

from .config import Context, cache_dir, outputs_dir
from . import rasterio_utils as ru


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
    FLOOR = float(fcfg.get("min_huntability", 0.30))   # ABSOLUTE admission bar
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
        for (pr, pc) in peaks:
            near = (Y - pr) ** 2 + (X - pc) ** 2 <= radius_px ** 2
            # grow the lobe down to gate_f·peak, but NEVER below the absolute floor
            raw = near & np.isfinite(hunt) & (hs >= max(floor, float(hs[pr, pc]) * gate_f))
            # Keep ONLY the connected component containing the peak, then close gaps &
            # fill holes so the ring, its centroid, and its placed sites all agree.
            lbl, _ = ndlabel(raw)
            comp = lbl[pr, pc]
            if comp == 0:
                continue
            sel = binary_fill_holes(binary_closing(lbl == comp, iterations=2))
            area = int(sel.sum()) * px_area
            if area < min_a:
                continue
            out.append((float(hs[pr, pc]), area, float(np.nanmean(hunt[sel])), sel))
        return out

    # Primary pass at the absolute floor, then ONE mild fallback (still absolute, not a
    # percentile). If nothing clears even that, return ZERO areas honestly — a poor or
    # water-locked box should say "thin ground here" (the access flags + recommendations
    # explain the trade-off), not dress up its least-bad ground as a recommendation.
    cands = _find(FLOOR, 0.82, min_km2)
    if not cands:
        cands = _find(FLOOR * 0.8, 0.70, max(1.0, min_km2 * 0.5))
    # Rank by EXPECTED ENCOUNTER ≈ area × mean huntability (coverage matters for a species
    # at ~20 km²/moose), not by mean alone, which favoured tiny tight pockets over large
    # good ground.
    cands.sort(key=lambda t: t[1] * t[2], reverse=True)

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
    access = float(getattr(hunter, "walk_access_km", 6.0) or 6.0)
    hunt_km = float(getattr(hunter, "walk_hunt_km", 3.0) or 3.0)
    reach = hunt_km if style == "vehicle" else (access + hunt_km)
    if kit["atv"]:
        reach = reach * 2.5 + 5.0
    return reach


def _capability_gate(dr, hunter, kit):
    """Can this hunter actually GET here and get an animal OUT, given what they told
    us they have? Returns (ok, reason). A "no" is not a judgement about the ground —
    the area still ships, flagged, so the hunter can decide whether the kit is worth
    bringing (user: 'interesting to know they're there ... but not helpful to formally
    suggest sites the hunter cannot access')."""
    if dr is None:
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
    tpi = _opt(cache / "terrain/tpi.tif")          # prominence for glassing
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
        ok, why_not = _capability_gate(st.get("dist_road_m"), ctx.aoi.hunter, _kit)
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
    from scipy.ndimage import uniform_filter as _ufg
    _res = float(ctx.model.raster_resolution_m)
    prom = np.clip(np.nan_to_num(tpi) / 12.0, 0.0, 1.0) if tpi is not None else \
        np.where(np.isfinite(hunt), ru.normalize(dem), 0.0)
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
    def _n(base, key, cap):
        # Bias the rounding so the emphasis is visible even at party=2 (base 1): a
        # phase that FAVOURS a type rounds up, one that de-emphasises rounds down
        # (floor, min 1 — the option never disappears). Plain round() would collapse
        # every 0.7–1.4 multiplier on a base of 1 back to 1 and hide the whole point.
        w = pw.get(key, 1.0)
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
    add_points_per_area(funnel, "funnel", n_funnel,
                        {"when": "travel corridor — any time, best when animals are moving"},
                        min_score=0.15)   # only where a real neck exists (tightened surface)
    # min_score floor: on flat/closed-canopy ground with nothing to overlook, place NO
    # glassing knob rather than inventing one on the tallest closed-canopy cell.
    add_points_per_area(glass, "glassing", n_glass,
                        {"when": "dawn & dusk — glass the openings from high ground",
                         "pair": "glass in pairs where the crew allows — two sets of eyes on one basin beats two basins half-watched"},
                        min_score=0.15)
    add_points_per_area(hunt, "validate_ground", 1)

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
        # The hunter fixed the camp: emit ONE pin there, and every area is hunted from
        # it. (Overrides the vehicle/auto logic — they told us exactly where.)
        camp_of_area = {rank: fixed_camp_rc for rank, _sel in area_masks}
        lon, lat = toll(fixed_camp_rc)
        features.append({"type": "Feature",
                         "geometry": {"type": "Point", "coordinates": [lon, lat]},
                         "properties": {"legend": "base_camp", "anchor": "fixed",
                                        "fixed": True}})
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
        _add_routes(ctx, features, cache, prof, access, toll)
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
        f["properties"]["crew"] = _crew_plan(f["properties"], inside, party)

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


def _linear_cost_layer(cache, shape):
    """Rasterize motorised TRAILS (quad/snowmobile) and RAIL grades onto the analysis
    grid as a boolean 'easy walking line' mask. Deliberately separate from roads.tif:
    these are not drivable in a truck, so nothing may treat them as vehicle access —
    they only make walking (and, for #69, riding) cheaper than bushwhacking, and they
    are the linear corridors wildlife moves along. None if neither layer is present."""
    import numpy as _np
    paths = [cache / "aq_trails.gpkg", cache / "aq_rail.gpkg"]
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
def _crew_plan(area_props, sites, party):
    """sites = the features already placed inside THIS area."""
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
            "Caller and shooter split up: shooter ~70 m downwind of the caller, on "
            "the side the bull is most likely to circle to. The caller is bait, not "
            "the gun.")
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


def _add_routes(ctx, features, cache, prof, access, toll):
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

    def add_route(rank, dest_feat, legend):
        lon, lat = dest_feat["geometry"]["coordinates"]
        end = lonlat_to_rc(lon, lat)
        start = camp_by_area.get(rank)
        if start is None or start == end:
            return
        path, _ = route_through_array(cost, start, end, fully_connected=True, geometric=True)
        coords = [list(toll((r, c))) for r, c in path]
        features.append({"type": "Feature",
                         "geometry": {"type": "LineString", "coordinates": coords},
                         "properties": {"legend": legend, "focus_area": rank}})

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
            legs = [(None, road_start, s) for s in camp_rc]
        for rank, start, dest in legs:
            if start == dest:
                continue
            if no_road:
                path, _ = route_through_array(wcost, start, dest,
                                              fully_connected=True, geometric=True)
                legend = "route_paddle"
            else:
                path, _ = route_through_array(cost, start, dest,
                                              fully_connected=True, geometric=True)
                legend = "route_access"
            coords = [list(toll((r, c))) for r, c in path]
            if len(coords) >= 2:
                features.append({"type": "Feature",
                                 "geometry": {"type": "LineString", "coordinates": coords},
                                 "properties": {"legend": legend, "focus_area": rank}})
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
        "note": ("Log what you find at the ground-truth points so the next plan learns from the "
                 "boots, not just the pixels."),
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
