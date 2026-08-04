"""Access network from OpenStreetMap: Route 389 + logging/resource roads and
tracks. Lighter than the water query. Writes:
  cache/<aoi>/roads.gpkg   — road lines (WGS84)
  cache/<aoi>/roads.tif    — 1=road on the canonical grid (drivable proxy)

TODO(P2+): union with the official MRNF forest-road layer and downgrade segments
contradicted by Sentinel-2 (per-segment confidence).
"""
from __future__ import annotations

import math

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

DRIVE_TAGS = {"highway": ["motorway", "trunk", "primary", "secondary", "tertiary",
                          "unclassified", "residential", "track", "service"]}
# Foot access — trails a hunter walks in on but can't drive. Kept SEPARATE from the
# drivable network so access/pack-out never treats a footpath as a truck road (#32).
TRAIL_TAGS = {"highway": ["path", "footway", "bridleway", "cycleway"]}
RAIL_TAGS = {"railway": ["rail", "narrow_gauge", "light_rail"]}
# Vector hydrography — captures narrow rivers/streams the 10 m WorldCover raster
# misses, and gives exact geometry for map display + route river-crossing checks.
WATER_LINE_TAGS = {"waterway": ["river", "stream", "canal", "tidal_channel", "rapids"]}
# NOTE: keep this NARROW. A broad `"water": True` catch-all matches every water=*
# feature and, over a lake-rich boreal AOI on a slow Overpass mirror, hangs for many
# minutes. natural=water captures the lakes/ponds we render; that's enough.
WATER_POLY_TAGS = {"natural": ["water"]}


def _osm_bbox(tags, minlon, minlat, maxlon, maxlat):
    import osmnx as ox
    try:
        return ox.features.features_from_bbox((minlon, minlat, maxlon, maxlat), tags)
    except TypeError:
        return ox.features_from_bbox(maxlat, minlat, maxlon, minlon, tags)


# One Overpass request for a 70–134 km box over road-dense country is enormous and
# simply times out on a public mirror — which cost us the ENTIRE road network (and,
# with no watercraft, zeroed the whole huntability surface). Split the AOI into tiles
# no wider than this and merge; a failed tile costs one tile, not the layer.
_TILE_DEG = 0.60            # ~67 km N-S. Wide, because with a fast mirror the
                            # per-request overhead dominates; tiling is insurance
                            # against one huge request timing out, not the main event.


def _osm(ctx, tags, local=None):
    """OSM features for the AOI.

    Prefers a LOCAL Geofabrik extract (fast, offline, no rate limits) and only falls
    back to live Overpass when the extract isn't present — see acquire/osm_local.py for
    why: public mirrors variously block this host, return the wrong continent, or take
    over two hours for a single road-dense box.
    """
    import geopandas as gpd
    import pandas as pd

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()

    if local is not None:
        try:
            from . import osm_local
            if osm_local.available():
                g = local((minlon, minlat, maxlon, maxlat))
                if g is not None:
                    return g
        except Exception:
            pass

    nx = max(1, int(math.ceil((maxlon - minlon) / _TILE_DEG)))
    ny = max(1, int(math.ceil((maxlat - minlat) / _TILE_DEG)))
    if nx * ny <= 1:
        return _osm_bbox(tags, minlon, minlat, maxlon, maxlat)

    dx = (maxlon - minlon) / nx
    dy = (maxlat - minlat) / ny
    parts, ok, fail = [], 0, 0
    for i in range(nx):
        for j in range(ny):
            a, b = minlon + i * dx, minlat + j * dy
            try:
                g = _osm_bbox(tags, a, b, a + dx, b + dy)
                if g is not None and len(g):
                    parts.append(g)
                ok += 1
            except Exception:
                fail += 1                      # keep going; a hole beats no layer
    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")
    out = pd.concat(parts, ignore_index=True)
    return gpd.GeoDataFrame(out, geometry="geometry", crs=parts[0].crs)


def fetch(ctx: Context) -> None:
    import numpy as np
    import rasterio
    from rasterio.features import rasterize

    cache = cache_dir(ctx.aoi.name)

    # rail (best-effort — QNS&L / Fire Lake mine line etc.)
    try:
        from . import osm_local as _L
        r = _osm(ctx, RAIL_TAGS, local=_L.rail)
        r = r[r.geometry.type.isin(["LineString", "MultiLineString"])] if len(r) else r
        if r is not None and len(r):
            r[["geometry"]].reset_index(drop=True).to_file(cache / "rail.gpkg", driver="GPKG")
    except Exception:
        pass

    # foot trails (path/footway/bridleway) — walk-in access, NOT drivable (#32). Kept in
    # its own layer so access never mistakes a footpath for a truck road.
    try:
        from . import osm_local as _L
        tr = _osm(ctx, TRAIL_TAGS, local=_L.trails)
        tr = tr[tr.geometry.type.isin(["LineString", "MultiLineString"])] if len(tr) else tr
        if tr is not None and len(tr):
            cols = [c for c in ("highway", "name") if c in tr.columns] + ["geometry"]
            tr[cols].reset_index(drop=True).to_file(cache / "trails.gpkg", driver="GPKG")
    except Exception:
        pass

    # vector waterways (rivers/streams) + waterbodies (lakes) — exact geometry
    try:
        from . import osm_local as _L
        wl = _osm(ctx, WATER_LINE_TAGS, local=_L.waterways)
        wl = wl[wl.geometry.type.isin(["LineString", "MultiLineString"])] if len(wl) else wl
        if wl is not None and len(wl):
            cols = [c for c in ("waterway",) if c in wl.columns] + ["geometry"]
            wl[cols].reset_index(drop=True).to_file(cache / "waterways.gpkg", driver="GPKG")
    except Exception:
        pass
    try:
        from . import osm_local as _L
        wp = _osm(ctx, WATER_POLY_TAGS, local=_L.waterbodies)
        wp = wp[wp.geometry.type.isin(["Polygon", "MultiPolygon"])] if len(wp) else wp
        if wp is not None and len(wp):
            wp[["geometry"]].reset_index(drop=True).to_file(cache / "waterbodies.gpkg", driver="GPKG")
    except Exception:
        pass

    # Roads themselves — guard like the other layers so a slow/failed Overpass query
    # doesn't abort the whole fetch (was unguarded → a timeout here left NO roads.gpkg
    # and NO roads.tif, so the contract's infra came back empty).
    try:
        from . import osm_local as _L
        g = _osm(ctx, DRIVE_TAGS, local=_L.roads)
        g = g[g.geometry.type.isin(["LineString", "MultiLineString"])] if len(g) else g
    except Exception:
        g = None
    dst_crs, transform, w, h = target_grid(ctx)
    if g is not None and len(g):
        # Keep the tag column: contract.py reads bridge=yes off it to tell a real
        # obstacle from a road bridge you simply drive over. Writing geometry only
        # threw that away and every bridged river came back as "needs a boat".
        keep = ["geometry"] + [c for c in ("other_tags", "highway", "name") if c in g.columns]
        g[keep].reset_index(drop=True).to_file(cache / "roads.gpkg", driver="GPKG")
        shapes = [(geom, 1) for geom in g.to_crs(dst_crs).geometry if geom and not geom.is_empty]
        arr = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0,
                        default_value=1, dtype="uint8", all_touched=True)
    else:
        arr = np.zeros((h, w), dtype="uint8")

    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": h, "width": w,
            "crs": dst_crs, "transform": transform, "nodata": 0, "compress": "deflate", "tiled": True}
    with rasterio.open(cache / "roads.tif", "w", **prof) as dst:
        dst.write(arr, 1)
