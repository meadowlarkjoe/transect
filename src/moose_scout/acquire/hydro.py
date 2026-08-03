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
from ..rasterio_utils import target_grid


def fetch(ctx: Context) -> None:
    import os

    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject, transform_bounds
    from rasterio.windows import from_bounds

    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    cache = cache_dir(ctx.aoi.name)
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    dst_crs, dst_transform, W, H = target_grid(ctx)

    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                      modifier=pc.sign_inplace)
    items = list(cat.search(collections=["esa-worldcover"],
                            bbox=[minlon, minlat, maxlon, maxlat], limit=5).items())
    if not items:
        raise RuntimeError("no WorldCover item for AOI")
    # Prefer the most recent map.
    item = sorted(items, key=lambda i: i.properties.get("start_datetime", ""))[-1]

    href = item.assets["map"].href
    with rasterio.open(href) as src:
        l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
        win = from_bounds(l, b, r, t, src.transform)
        lc_src = src.read(1, window=win, out_shape=(H, W), resampling=Resampling.nearest)
        win_tr = src.window_transform(win)
        sx = (win.width / W) if win.width else 1
        sy = (win.height / H) if win.height else 1
        src_tr = win_tr * Affine.scale(sx, sy)
        scrs = src.crs

    lc = np.zeros((H, W), dtype="uint8")
    reproject(lc_src, lc, src_transform=src_tr, src_crs=scrs,
              dst_transform=dst_transform, dst_crs=dst_crs, resampling=Resampling.nearest)

    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": 0,
            "compress": "deflate", "tiled": True}

    def _save(name, arr):
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(arr.astype("uint8"), 1)

    _save("landcover.tif", lc)
    _save("water.tif", (lc == 80).astype("uint8"))
    _save("wetland.tif", (lc == 90).astype("uint8"))
