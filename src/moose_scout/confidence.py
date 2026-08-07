"""Confidence scoring for the analysis.

Every prediction here is only as good as the data under it, and that data quality
varies in space. The dominant driver at Fire Lake is the écoforestière limit:
south of ~52°N we'd have stand-level forestry (species/age/height/cut history);
north of it we fall back to satellite land-cover + Sentinel NDVI, which is coarser
and can't see understory browse — so confidence drops. Other drivers: whether we
actually got NDVI/land-cover/road layers, how homogeneous a focus area is (a big
single-class satellite blob is more ambiguous than a varied mosaic), and whether
density came from an aerial survey or a bioclimatic guess.

Pure functions, no I/O beyond what callers pass in:
  • area_confidence(sel, layers)  -> per focus-area score + drivers (called in synth)
  • overall(ctx, cache)           -> AOI-level score/band/drivers (export + brief)
"""
from __future__ import annotations


def _band(score: float) -> str:
    return "high" if score >= 0.72 else ("moderate" if score >= 0.5 else "low")


def area_confidence(sel, layers) -> dict:
    """Confidence [0,1] for one focus area from data coverage under its mask.
    `layers` mirrors synth's Lyr dict (lc, ndvi optional). Returns {score, band,
    drivers:[...]}. Robust to missing layers."""
    import numpy as np

    lat_north = layers.get("lat", 52.5) >= 52.0
    base = 0.60 if lat_north else 0.82
    drivers = []
    drivers.append("north of ~52°N — satellite land-cover, no stand-level forestry"
                   if lat_north else "stand-level forestry coverage (south of ~52°N)")

    lc = layers.get("lc")
    if lc is not None and sel is not None and sel.any():
        vals = lc[sel]
        vals = vals[np.isfinite(vals)]
        if vals.size:
            # class diversity: a varied mosaic is more trustworthy than one big blob
            _, counts = np.unique(vals.astype(int), return_counts=True)
            frac_top = counts.max() / counts.sum()
            if frac_top > 0.85:
                base -= 0.10
                drivers.append(f"homogeneous cover ({int(frac_top*100)}% one class) — coarser read")
            elif frac_top < 0.55:
                base += 0.06
                drivers.append("varied cover mosaic (clearer edges/forage read)")
            # very wet/water-heavy areas: harder to model on-ground huntability
            water_frac = float(np.isin(vals.astype(int), [80]).mean())
            if water_frac > 0.30:
                base -= 0.06
                drivers.append(f"{int(water_frac*100)}% open water — access/footing uncertain")
    else:
        base -= 0.05
        drivers.append("no land-cover layer for this area")

    if layers.get("ndvi") is not None:
        base += 0.04
        drivers.append("Sentinel-2 NDVI available (greenness/browse proxy)")

    score = float(max(0.30, min(0.95, base)))
    return {"score": round(score, 2), "band": _band(score), "drivers": drivers[:4]}


def overall(ctx, cache) -> dict:
    """AOI-level confidence from data availability + density source. `cache` is the
    Path to cache/<aoi>. Returns {score, band, drivers, caveats}."""
    lat = ctx.aoi.center.lat
    north = lat >= 52.0
    # NOTE: stand-level écoforestière data is NOT wired in (the fetcher is a stub), so
    # vegetation comes from satellite everywhere — we must not claim otherwise, and the
    # southern AOI gets no confidence credit for data we don't actually have.
    score = 0.60 if north else 0.66
    drivers = []
    drivers.append("Vegetation from satellite (ESA WorldCover + Sentinel-2) plus mapped "
                   "burn perimeters — stand-level forestry inventory is NOT used"
                   + (" (and this AOI is north of the écoforestière limit anyway)." if north
                      else "; cutblock age is therefore not modelled."))

    def has(name):
        return (cache / name).exists()

    if has("burn_year.tif"):
        score += 0.06
        drivers.append("Burn history (NBAC) acquired — disturbance-age browse modelled.")
    else:
        score -= 0.05
        drivers.append("No burn history — browse rests on land cover alone (weaker).")

    if has("ndvi.tif"):
        score += 0.04; drivers.append("Sentinel-2 NDVI acquired.")
    else:
        score -= 0.06; drivers.append("No Sentinel-2 NDVI (imagery gap) — browse read weaker.")
    if has("stand_type.tif"):
        score += 0.08
        drivers.append("Écoforestière stand data acquired — real species, canopy closure "
                       "and dated cuts (not just satellite land cover).")
    elif has("ecoforestiere_absent.flag"):
        drivers.append("North of the écoforestière limit (~52°N) — cover/browse rest on "
                       "WorldCover + Sentinel-2 (coarser, lower confidence).")
    if has("landcover.tif"):
        score += 0.03; drivers.append("ESA WorldCover land-cover acquired.")
    # HOW OLD THE SATELLITE HALF IS (T10.16). Until the frozen window was fixed this was
    # unanswerable — the imagery was 2023-24 on every run, and nothing said so. A cut or
    # burn newer than the freshest scene is invisible to the greenness term, on ground
    # whose whole browse story is disturbance age, so age here is a real confidence cost.
    try:
        import json as _json
        _s2 = _json.loads((cache / "ndvi.json").read_text())
        _run_year = int((_s2.get("run_date") or "0000")[:4])
        _newest = int((_s2.get("newest") or "0000")[:4])
        _age = _run_year - _newest
        if _age >= 2:
            score -= 0.06
            drivers.append(f"Satellite greenness is {_age} growing seasons old (newest "
                           f"usable scene {_newest}) — recent cuts and burns are not in it.")
        elif _age == 1:
            drivers.append(f"Satellite greenness is last summer's ({_newest}) — this "
                           f"season had too little clear, snow-free cover.")
        else:
            drivers.append(f"Satellite greenness from this summer "
                           f"({_s2.get('n')} leaf-on scenes, newest {_s2.get('newest')}).")
    except Exception:
        pass
    if has("roads.tif"):
        drivers.append("OSM road network present (access/pressure modelled).")
    else:
        score -= 0.04; drivers.append("No mapped roads in window — access modelled on water only.")

    # density source (strategy): aerial survey vs bioclimatic prior
    try:
        from .strategy import density_estimate
        d = density_estimate(ctx)
        if d.get("is_estimate"):
            score -= 0.05
            drivers.append("Moose density is a bioclimatic estimate (no aerial survey for this zone).")
        else:
            score += 0.05
            drivers.append(f"Density from {d.get('source', 'aerial inventory')}.")
    except Exception:
        pass

    score = float(max(0.30, min(0.95, score)))
    return {
        "score": round(score, 2),
        "band": _band(score),
        "drivers": drivers,
        "caveats": [
            "Model output is a prioritized hypothesis to ground-truth on foot.",
            "Confidence is about DATA quality, not a guarantee animals are present.",
        ],
    }


# --- #71: plain-language WHY + confidence, per placed feature -------------------
# A hunter should never have to wonder why the model dropped a marker somewhere. Two
# honest families here, and they deserve different language:
#   MODELLED  — we inferred it from terrain/cover/water. Confidence is about DATA
#               quality, and the reasons quote the local values that drove the call.
#   SOURCED   — it came from an official dataset. Confidence is high and the honest
#               "why" is naming the source, not inventing a rationale.
SOURCE_NOTES = {
    "burns":    ("NBAC (Canadian national burned-area composite) fire perimeters, dated", 0.95),
    "cuts":     ("MRNF carte écoforestière — mapped cutblocks with harvest year", 0.93),
    "beaver":   ("MRNF GRHQ hydrography — mapped flowages ('mare')", 0.92),
    "wetland":  ("MRNF GRHQ hydrography — mapped marsh/bog/fen", 0.92),
    "water":    ("OSM hydrography + ESA WorldCover 10 m water mask", 0.9),
    "roads":    ("AQréseau+ (official Québec road network, MRNF) unioned with OSM", 0.93),
    "trails":   ("AQréseau+ quad/snowmobile sentiers + OSM foot paths", 0.85),
    "crossings": ("GRHQ Strahler order + perenniality where available; OSM waterway class otherwise", 0.7),
    "tenure":   ("MRNF tenure polygons (pourvoirie / ZEC / réserve)", 0.95),
}


def site_explain(legend, vals) -> dict:
    """Why THIS site, in language a hunter uses. `vals` carries whatever local numbers
    synth had to hand (dist_water_m, dist_road_m, slope_deg, cover_frac, browse,
    score...). Returns {conf, band, why:[...]} — never raises, and says less rather
    than inventing a reason it can't support."""
    why = []
    v = {k: x for k, x in (vals or {}).items() if x is not None}
    s = v.get("score")
    dw, dr = v.get("dist_water_m"), v.get("dist_road_m")
    slope, cov, brw = v.get("slope_deg"), v.get("cover_frac"), v.get("browse")

    if legend == "thermal_refuge":
        why.append("dense mature conifer — the cool, shaded cover moose bed in when it warms up")
        if dw is not None and dw < 500:
            why.append(f"water within ~{int(dw)} m to cool off and drink")
        why.append("scored well above the surrounding ground on this AOI's own refuge surface")
    elif legend == "rut_calling":
        why.append("sits on a cover↔opening seam — bulls cruise these edges looking for cows")
        if brw is not None and brw > 0.2:
            why.append("forage on the open side, so cows use it too")
        why.append("enough security cover behind you to call from without skylining")
    elif legend == "saline_blind":
        why.append("browse edge / riparian willow — the food itself, worked at first and last light")
        if dw is not None and dw < 400:
            why.append(f"riparian band ~{int(dw)} m from water")
    elif legend == "glassing":
        why.append("high ground with a real view over open country — prominence plus visible openness")
    elif legend == "funnel":
        why.append("a narrow neck of land between water or wetland — travelling animals squeeze through here")
    elif legend == "validate_ground":
        why.append("a spot where the model is confident enough to be worth checking — go look for sign")
    if slope is not None and slope < 8:
        why.append(f"gentle ground (~{slope:.0f}° slope) — quiet to still-hunt and easier to pack out")
    if dr is not None and dr > 3000:
        why.append(f"~{dr/1000:.1f} km off the nearest road — less hunter pressure, longer haul")

    # Confidence: the surface's own strength, tempered because a placed site is always
    # a hypothesis to ground-truth. Never presented as certainty.
    base = 0.55 + 0.30 * float(min(1.0, max(0.0, s))) if s is not None else 0.6
    score = float(max(0.35, min(0.9, base)))
    return {"conf": round(score, 2), "band": _band(score), "why": why[:4]}
