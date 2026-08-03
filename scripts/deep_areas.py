"""Deep per-focus-area re-analysis.

For each focus area in a parent AOI's scout, re-run the pipeline on a TIGHT box
around the area centroid at a FINER resolution (default 20 m vs the 40 m AOI grid)
— a small box at 20 m is far fewer cells, so no OOM — pulling less-decimated
Sentinel-2 and the local hydro. Produces outputs/<parent>/area_detail.json:

  { "<rank>": { box, res_m, hunt_zones, browse_zones, hydro{rivers,lakes},
                sites[{t,ll,when}], stats } }

The MapLibre app loads this and swaps to the high-res layers when you open an
area in Field view.
"""
from __future__ import annotations

import json
import sys
import time

from moose_scout import contract as C
from moose_scout import pipeline
from moose_scout.config import (AOI, Context, LatLon, cache_dir, load_aoi,
                                load_model, load_species, outputs_dir)

# thermal_refuge + funnel are AREAS now (rendered as zones), so not point sites.
SITE_TYPES = {"rut_calling", "saline_blind", "glassing", "validate_ground"}


def _deep_sites(cache, ctx):
    """Place finer sites directly from the 20 m surfaces (the small deep box has no
    sub-focus-areas, so synth places nothing — do it from the peaks here)."""
    import numpy as np
    from pyproj import Transformer
    from skimage.feature import peak_local_max

    from moose_scout import rasterio_utils as ru

    def opt(p):
        try:
            return ru.read(cache / p)[0]
        except Exception:
            return None

    try:
        _, prof = ru.read(cache / "huntability.tif")
    except Exception:
        return []
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    T = prof["transform"]
    res = ctx.model.raster_resolution_m
    md = max(3, int(round(600 / res)))
    m = max(5, int(round(400 / res)))          # crop edge artefacts

    def toll(r, c):
        x, y = T * (c + 0.5, r + 0.5)
        lon, lat = tr.transform(x, y)
        return [round(lon, 5), round(lat, 5)]

    def peaks(arr, n):
        if arr is None:
            return []
        a = np.where(np.isfinite(arr), arr, 0).astype("float32")
        a[:m, :] = 0; a[-m:, :] = 0; a[:, :m] = 0; a[:, -m:] = 0
        return [tuple(p) for p in peak_local_max(a, num_peaks=n, min_distance=md, threshold_rel=0.4)]

    rut = opt("hsm_rut.tif"); dem = opt("dem.tif"); hunt = opt("huntability.tif"); dw = opt("dist_water.tif")
    near_water = None
    if hunt is not None and dw is not None:
        near_water = np.where(np.isfinite(hunt), hunt * np.exp(-dw / 300.0), np.nan)
    plan = [(rut, "rut_calling", 5, "dawn & dusk + all rut day (bulls cruise these edges)"),
            (near_water, "saline_blind", 3, "first & last light — feeding on browse edge / in water"),
            (dem, "glassing", 2, "dawn & dusk — glass the openings from high ground"),
            (hunt, "validate_ground", 3, "")]
    out = []
    for arr, t, n, when in plan:
        for (r, c) in peaks(arr, n):
            out.append({"t": t, "ll": toll(r, c), "when": when})
    return out


def _hydro(cache):
    import geopandas as gpd
    out = {"rivers": [], "lakes": []}
    try:
        p = cache / "waterways.gpkg"
        if p.exists():
            g = gpd.read_file(p)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            g["geometry"] = g.geometry.simplify(0.00012)
            wcol = "waterway" if "waterway" in g.columns else None
            for _, row in g.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue
                cls = "river" if (wcol and str(row[wcol]) in ("river", "canal")) else "stream"
                for part in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
                    ll = [[round(x, 5), round(y, 5)] for x, y in part.coords]
                    if len(ll) >= 2:
                        out["rivers"].append({"cls": cls, "ll": ll})
        p = cache / "waterbodies.gpkg"
        if p.exists():
            g = gpd.read_file(p)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            g["geometry"] = g.geometry.simplify(0.00012)
            for geom in g.geometry:
                if geom is None or geom.is_empty:
                    continue
                for part in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]):
                    ring = [[round(x, 5), round(y, 5)] for x, y in part.exterior.coords]
                    if len(ring) >= 4:
                        out["lakes"].append(ring)
    except Exception:
        pass
    return out


def deep(parent_name, radius_km=6.0, res_m=20.0, only=None):
    paoi = load_aoi(parent_name)
    doc = json.loads((outputs_dir(parent_name) / "transect.json").read_text())
    detail = {}
    for a in doc["areas"]:
        rank = a["rank"]
        if only and rank not in only:
            continue
        lon, lat = a["centroid"]
        name = f"{parent_name}_a{rank}"
        aoi = AOI(name=name, title=f"{paoi.title} — Area {rank}", species=paoi.species,
                  center=LatLon(lat=lat, lon=lon), bbox_halfwidth_km=radius_km,
                  zone_hint=paoi.zone_hint, season=paoi.season, hunter=paoi.hunter)
        model = load_model().model_copy(update={"raster_resolution_m": res_m})
        ctx = Context(aoi=aoi, species=load_species(paoi.species), model=model)
        t0 = time.time()
        print(f"[area {rank}] deep analysis @ {res_m}m, {radius_km}km box…", flush=True)
        for stage in ("acquire", "terrain", "habitat", "behavior", "access", "synth"):
            pipeline.run_stage(stage, ctx)
        cache = cache_dir(name)
        minlon, minlat, maxlon, maxlat = aoi.bbox_wgs84()
        # finer zones (smaller min area / lighter smoothing since the box is small)
        hz = C._polygonize(ctx, cache, "huntability.tif",
                           [("low", 0.42), ("medium", 0.6), ("high", 0.76)],
                           min_km2=0.12, smooth_m=90, per_class=14, simp=0.0004)
        bz = C._browse_zones(ctx, cache, min_km2=0.08, smooth_m=80)
        rfz = C._polygonize(ctx, cache, "hsm_thermal.tif", [("refuge", 0.5)],
                            min_km2=0.15, smooth_m=140, per_class=12, simp=0.0004)
        fnz = C._polygonize(ctx, cache, "terrain/funnel.tif", [("funnel", 0.55)],
                            min_km2=0.08, smooth_m=90, per_class=16, simp=0.0004)
        # finer sites from the 20 m surfaces
        sites = _deep_sites(cache, ctx)
        detail[str(rank)] = {
            "rank": rank, "res_m": res_m,
            "box": {"w": round(minlon, 6), "e": round(maxlon, 6), "n": round(maxlat, 6), "s": round(minlat, 6)},
            "hunt_zones": hz, "browse_zones": bz, "refuge_zones": rfz, "funnel_zones": fnz,
            "hydro": _hydro(cache), "sites": sites, "stats": a.get("stats", {}),
        }
        print(f"[area {rank}] done in {time.time()-t0:.0f}s — {len(hz)} zones, {len(bz)} browse, "
              f"{len(sites)} sites, {len(detail[str(rank)]['hydro']['rivers'])} rivers", flush=True)
    out = outputs_dir(parent_name) / "area_detail.json"
    # merge with any existing (so partial runs accumulate)
    if out.exists():
        try:
            prev = json.loads(out.read_text())
            prev.update(detail)
            detail = prev
        except Exception:
            pass
    out.write_text(json.dumps(detail))
    print(f"WROTE {out} ({out.stat().st_size} bytes, areas={sorted(detail.keys())})", flush=True)


if __name__ == "__main__":
    parent = sys.argv[1] if len(sys.argv) > 1 else "fire_lake"
    only = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
    deep(parent, only=only)
