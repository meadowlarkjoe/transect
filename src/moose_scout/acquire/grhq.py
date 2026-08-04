"""GRHQ hydrography — beaver ponds + wetlands (phase 2 of #62).

The per-crossing Strahler/perenniality query already lives in ``contract._grhq_crossing_class``;
this module adds the two POLYGON layers that shape habitat and travel:

  * BEAVER PONDS / small flowages — MRNF GRHQ MapServer layer 23 ("Surface [125K-1]"),
    ``TYPECE`` 22 (Mare) + small isolated 21 (Lac). A beaver flowage is a RUT HUB (bulls
    scent-mark, cows are drawn) and a browse/travel edge — NOT fall aquatic forage, which
    is decayed out by the rifle hunt. So it feeds the rut/wallow term, never a water-food one.
  * WETLANDS — layer 5 ("Éléments surfaciques"), ``TYPECE`` 31 (Milieu humide): marsh /
    bog / fen. A travel BARRIER that forms land-bridge funnels, and slow going on foot.

Writes on the working grid (0 elsewhere):
  beaver_pond.tif   uint8  1 = beaver pond / small flowage
  wetland_grhq.tif  uint8  1 = mapped wetland (milieu humide)

Bulk GRHQ is fine-scale (tens of thousands of polygons per box), so each layer is PAGED and
per-page RASTERIZED (memory-bounded) under a wall-clock budget — the écoforestière pattern.
GRHQ covers all of Québec, so there is no coverage edge to skip (unlike écoforestière).
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

BASE = os.environ.get(
    "GRHQ_BASE",
    "https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/GRHQ_WMS/MapServer")
BUDGET = float(os.environ.get("GRHQ_BUDGET_S", "300"))   # wall-clock safety net per run
PAGE = 1000

# What we pull from each layer. where clauses key off the TYPECE codebook (verified against
# the layer renderers): 22=Mare, 21=Lac, 31=Milieu humide. Beaver ponds = MARE only — a
# specific small-pond/flowage class, the rut-hub signal. Small natural lakes (21) are just
# lakes and are already handled as water barriers/display, so counting them here would
# dilute the signal and double-count water.
POND_LAYER, POND_WHERE = 23, "TYPECE=22"
WET_LAYER, WET_WHERE = 5, "TYPECE=31"


def _fetch_page(layer, bbox, where, start, count, timeout=60):
    """One page of a GRHQ polygon layer as GeoJSON (the server supports f=geojson and
    resultOffset paging). Returns (features, error_code|None)."""
    q = {"geometry": bbox, "geometryType": "esriGeometryEnvelope",
         "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
         "where": where, "outFields": "TYPECE,SUP_HA", "returnGeometry": "true",
         "resultRecordCount": str(count), "resultOffset": str(start),
         "orderByFields": "OBJECTID", "f": "geojson"}
    url = f"{BASE}/{layer}/query?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "moose-scout/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        return d.get("features") or [], None
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception:
        return None, -1


def _rasterize_layer(layer, where, bbox, transform, w, h, proj, t0):
    """Page through one layer, rasterizing each page into a uint8 accumulator so peak
    memory is one page of geometry, never the whole AOI. Budget-bounded."""
    import numpy as np
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp_shape

    acc = np.zeros((h, w), "uint8")
    start, got = 0, 0
    while True:
        if time.time() - t0 > BUDGET:
            break
        feats, err = _fetch_page(layer, bbox, where, start, PAGE)
        if err is not None or not feats:
            break
        shapes = []
        for f in feats:
            g = f.get("geometry")
            if not g:
                continue
            try:
                shapes.append((proj(shp_shape(g)), 1))
            except Exception:
                continue
        if shapes:
            pr = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0,
                           default_value=1, dtype="uint8", all_touched=True)
            acc = np.where(pr > 0, 1, acc).astype("uint8")
        got += len(feats)
        if len(feats) < PAGE:
            break
        start += PAGE
    return acc, got


def fetch(ctx: Context) -> None:
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from shapely.ops import transform as shp_transform

    cache = cache_dir(ctx.aoi.name)
    if (cache / "beaver_pond.tif").exists() and (cache / "wetland_grhq.tif").exists():
        return

    dst_crs, transform, w, h = target_grid(ctx)
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    bbox = f"{minlon},{minlat},{maxlon},{maxlat}"

    to_dst = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)
    proj = lambda g: shp_transform(lambda xx, yy: to_dst.transform(xx, yy), g)  # noqa: E731

    t0 = time.time()
    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": h, "width": w,
            "crs": dst_crs, "transform": transform, "nodata": 0, "compress": "deflate", "tiled": True}
    for name, layer, where in (("beaver_pond.tif", POND_LAYER, POND_WHERE),
                               ("wetland_grhq.tif", WET_LAYER, WET_WHERE)):
        if (cache / name).exists():
            continue
        try:
            acc, n = _rasterize_layer(layer, where, bbox, transform, w, h, proj, t0)
        except Exception:
            acc, n = np.zeros((h, w), "uint8"), 0
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(acc, 1)
