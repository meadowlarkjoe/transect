"""Water, wetland & land cover from ESA WorldCover (10 m, via Planetary Computer).

Replaces a slow/heavy OSM-Overpass water pull with one decimated COG read that
yields, on the canonical grid:
  water.tif      1 = permanent water body (class 80)
  wetland.tif    1 = herbaceous wetland (class 90)
  landcover.tif  raw WorldCover class (10 tree, 20 shrub, 30 grass, 60 bare,
                 80 water, 90 wetland, 100 moss/lichen, ...)

The classes feed the HSM directly (shrubland/grassland = browse, tree = cover,
water/wetland = aquatic forage) and are reliable north of the écoforestière limit.
"""
from __future__ import annotations

from ..config import Context, cache_dir
from .. import rasterio_utils as ru
from ..rasterio_utils import target_grid


def fetch(ctx: Context) -> None:
    import os

    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client

    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    cache = cache_dir(ctx.aoi.name)
    # All three outputs present → nothing to do. Without this, hydro re-queried the
    # STAC catalogue and re-warped WorldCover on every run, and it was the last source
    # still spending real time on a fully cached box.
    if all((cache / n).exists() and (cache / n).stat().st_size > 0
           for n in ("landcover.tif", "water.tif", "wetland.tif")):
        print("[hydro] cached — skipping WorldCover")
        return

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    aoi_wgs = (minlon, minlat, maxlon, maxlat)
    dst_crs, dst_transform, W, H = target_grid(ctx)

    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                      modifier=pc.sign_inplace)
    items = list(cat.search(collections=["esa-worldcover"],
                            bbox=[minlon, minlat, maxlon, maxlat], limit=12).items())
    if not items:
        raise RuntimeError("no WorldCover item for AOI")
    # A 45 km box straddles WorldCover's 3° tiles, so one item covers only part of it —
    # reading a single item with an out-of-bounds window is what striped the map. Take
    # ALL tiles of the most-recent map year and mosaic them onto the canonical grid, each
    # via a window CLAMPED to its real extent (see ru.reproject_window).
    newest = max(i.properties.get("start_datetime", "") for i in items)
    tiles = [i for i in items if i.properties.get("start_datetime", "") == newest] or items

    lc = np.zeros((H, W), dtype="uint8")
    for it in tiles:
        with rasterio.open(it.assets["map"].href) as src:
            arr, mask = ru.reproject_window(src, dst_crs, dst_transform, W, H, aoi_wgs,
                                            resampling="nearest")
        if arr is None:
            continue
        fill = mask & (lc == 0)                       # first tile to cover a cell wins
        lc[fill] = np.rint(arr[fill]).astype("uint8")

    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": 0,
            "compress": "deflate", "tiled": True}

    def _save(name, arr):
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(arr.astype("uint8"), 1)

    _save("landcover.tif", lc)
    _save("water.tif", (lc == 80).astype("uint8"))
    _save("wetland.tif", (lc == 90).astype("uint8"))
