"""Burn history from the National Burned Area Composite (NBAC, NRCan CWFIS).

This is the single highest-value habitat input for boreal moose, and it is the only
predictor with LOCAL validation for our test area: the 1988 MLCP zone-19 aerial
inventory (the zone containing Fire Lake / Fermont) found that old burns — generally
mixed or deciduous regeneration — correlated with observed moose numbers at
**r = 0.62, p < 0.01**. Nothing else in this model has that combination of effect
size and geographic specificity.

Post-disturbance browse follows a well-established curve: moose density peaks around
15 years post-burn and then declines ~9 %/yr as the canopy closes; use is LOW in very
young burns (<8 yr) despite high biomass, because the browse is below reachable
height and there is no security cover.

Writes:
  cache/<aoi>/burn_year.tif   — year of most recent burn per pixel (0 = never burned)

Source: CWFIS GeoServer WFS, layer `public:nbac` (~50k polygons, 1972→present,
attribute `year`, native EPSG:3978).
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

WFS = os.environ.get(
    "NBAC_WFS", "https://cwfis.cfs.nrcan.gc.ca/geoserver/public/wfs")
LAYER = os.environ.get("NBAC_LAYER", "public:nbac")
NATIVE_CRS = "EPSG:3978"


def _fetch_json(url: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "moose-scout/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def fetch(ctx: Context) -> None:
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform

    cache = cache_dir(ctx.aoi.name)
    out = cache / "burn_year.tif"
    if out.exists():
        return

    dst_crs, transform, w, h = target_grid(ctx)
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()

    # WFS bbox in the layer's native CRS (avoids server-side reprojection quirks)
    to_native = Transformer.from_crs("EPSG:4326", NATIVE_CRS, always_xy=True)
    xs, ys = zip(*[to_native.transform(x, y) for x, y in
                   ((minlon, minlat), (minlon, maxlat), (maxlon, minlat), (maxlon, maxlat))])
    bbox = f"{min(xs):.1f},{min(ys):.1f},{max(xs):.1f},{max(ys):.1f},urn:ogc:def:crs:EPSG::3978"
    q = {"service": "WFS", "version": "2.0.0", "request": "GetFeature",
         "typeNames": LAYER, "outputFormat": "application/json",
         "srsName": NATIVE_CRS, "bbox": bbox, "count": "4000"}
    doc = _fetch_json(WFS + "?" + urllib.parse.urlencode(q))
    feats = doc.get("features") or []

    # rasterize most-recent burn year per pixel (paint oldest→newest so newest wins)
    arr = np.zeros((h, w), dtype="int32")
    if feats:
        to_dst = Transformer.from_crs(NATIVE_CRS, dst_crs, always_xy=True)
        proj = lambda g: shp_transform(lambda xx, yy: to_dst.transform(xx, yy), g)  # noqa: E731
        shapes = []
        for f in feats:
            try:
                yr = int(f["properties"].get("year") or 0)
                if yr <= 0:
                    continue
                g = proj(shp_shape(f["geometry"]))
                if g.is_empty:
                    continue
                shapes.append((yr, g))
            except Exception:
                continue
        shapes.sort(key=lambda t: t[0])          # oldest first → newest overwrites
        if shapes:
            arr = rasterize([(g, yr) for yr, g in shapes], out_shape=(h, w),
                            transform=transform, fill=0, dtype="int32",
                            all_touched=True)

    prof = {"driver": "GTiff", "dtype": "int32", "count": 1, "height": h, "width": w,
            "crs": dst_crs, "transform": transform, "nodata": 0,
            "compress": "deflate", "tiled": True}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(arr, 1)
