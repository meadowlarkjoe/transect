"""Access network from OpenStreetMap: Route 389 + logging/resource roads and
tracks. Lighter than the water query. Writes:
  cache/<aoi>/roads.gpkg   — road lines (WGS84)
  cache/<aoi>/roads.tif    — 1=road on the canonical grid (drivable proxy)

TODO(P2+): union with the official MRNF forest-road layer and downgrade segments
contradicted by Sentinel-2 (per-segment confidence).
"""
from __future__ import annotations

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

DRIVE_TAGS = {"highway": ["motorway", "trunk", "primary", "secondary", "tertiary",
                          "unclassified", "residential", "track", "service"]}
RAIL_TAGS = {"railway": ["rail", "narrow_gauge", "light_rail"]}
# Vector hydrography — captures narrow rivers/streams the 10 m WorldCover raster
# misses, and gives exact geometry for map display + route river-crossing checks.
WATER_LINE_TAGS = {"waterway": ["river", "stream", "canal", "tidal_channel", "rapids"]}
WATER_POLY_TAGS = {"natural": ["water"], "water": True, "landuse": ["reservoir"]}


def _osm(ctx, tags):
    import osmnx as ox

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    try:
        return ox.features.features_from_bbox((minlon, minlat, maxlon, maxlat), tags)
    except TypeError:
        return ox.features_from_bbox(maxlat, minlat, maxlon, minlon, tags)


def fetch(ctx: Context) -> None:
    import numpy as np
    import rasterio
    from rasterio.features import rasterize

    cache = cache_dir(ctx.aoi.name)

    # rail (best-effort — QNS&L / Fire Lake mine line etc.)
    try:
        r = _osm(ctx, RAIL_TAGS)
        r = r[r.geometry.type.isin(["LineString", "MultiLineString"])] if len(r) else r
        if r is not None and len(r):
            r[["geometry"]].reset_index(drop=True).to_file(cache / "rail.gpkg", driver="GPKG")
    except Exception:
        pass

    # vector waterways (rivers/streams) + waterbodies (lakes) — exact geometry
    try:
        wl = _osm(ctx, WATER_LINE_TAGS)
        wl = wl[wl.geometry.type.isin(["LineString", "MultiLineString"])] if len(wl) else wl
        if wl is not None and len(wl):
            cols = [c for c in ("waterway",) if c in wl.columns] + ["geometry"]
            wl[cols].reset_index(drop=True).to_file(cache / "waterways.gpkg", driver="GPKG")
    except Exception:
        pass
    try:
        wp = _osm(ctx, WATER_POLY_TAGS)
        wp = wp[wp.geometry.type.isin(["Polygon", "MultiPolygon"])] if len(wp) else wp
        if wp is not None and len(wp):
            wp[["geometry"]].reset_index(drop=True).to_file(cache / "waterbodies.gpkg", driver="GPKG")
    except Exception:
        pass

    # Roads themselves — guard like the other layers so a slow/failed Overpass query
    # doesn't abort the whole fetch (was unguarded → a timeout here left NO roads.gpkg
    # and NO roads.tif, so the contract's infra came back empty).
    try:
        g = _osm(ctx, DRIVE_TAGS)
        g = g[g.geometry.type.isin(["LineString", "MultiLineString"])] if len(g) else g
    except Exception:
        g = None
    dst_crs, transform, w, h = target_grid(ctx)
    if g is not None and len(g):
        g[["geometry"]].reset_index(drop=True).to_file(cache / "roads.gpkg", driver="GPKG")
        shapes = [(geom, 1) for geom in g.to_crs(dst_crs).geometry if geom and not geom.is_empty]
        arr = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0,
                        default_value=1, dtype="uint8", all_touched=True)
    else:
        arr = np.zeros((h, w), dtype="uint8")

    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": h, "width": w,
            "crs": dst_crs, "transform": transform, "nodata": 0, "compress": "deflate", "tiled": True}
    with rasterio.open(cache / "roads.tif", "w", **prof) as dst:
        dst.write(arr, 1)
