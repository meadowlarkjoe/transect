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
    score = 0.60 if north else 0.82
    drivers = []
    drivers.append(("Vegetation from satellite (ESA WorldCover + Sentinel-2), not "
                    "stand-level forestry — north of the écoforestière limit.") if north
                   else "Stand-level écoforestière vegetation coverage.")

    def has(name):
        return (cache / name).exists()

    if has("ndvi.tif"):
        score += 0.04; drivers.append("Sentinel-2 NDVI acquired.")
    else:
        score -= 0.06; drivers.append("No Sentinel-2 NDVI (imagery gap) — browse read weaker.")
    if has("landcover.tif"):
        score += 0.03; drivers.append("ESA WorldCover land-cover acquired.")
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
