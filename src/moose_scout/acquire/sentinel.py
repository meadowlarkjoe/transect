"""Sentinel-2 L2A NDVI (Microsoft Planetary Computer STAC).

North of the écoforestière limit this is the primary vegetation signal: NDVI
separates productive regenerating browse / riparian shrub (high) from open water,
rock, and recent burns (low), and closed mature conifer (moderate). Bands are read
DECIMATED to the canonical grid (10 m → 40 m via COG overviews) so a 70 km box
stays within a 2 GB VM. Writes cache/<aoi>/ndvi.tif on the canonical grid.
"""
from __future__ import annotations

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

OUT = "ndvi.tif"


def fetch(ctx: Context) -> None:
    import os

    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client
    from rasterio.enums import Resampling
    from rasterio.warp import reproject, transform_bounds
    from rasterio.windows import from_bounds

    out = cache_dir(ctx.aoi.name) / OUT
    if out.exists() and out.stat().st_size > 0:
        return

    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                      modifier=pc.sign_inplace)
    # Leaf-on window, least-cloud scene. Widen years if a season is too cloudy.
    search = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=[minlon, minlat, maxlon, maxlat],
        datetime="2023-07-01/2024-09-15",
        query={"eo:cloud_cover": {"lt": 15}},
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        limit=1,
    )
    items = list(search.items())
    if not items:
        raise RuntimeError("no low-cloud Sentinel-2 scene for AOI window")
    item = items[0]

    dst_crs, dst_transform, W, H = target_grid(ctx)

    def read_band(asset_key):
        href = item.assets[asset_key].href
        with rasterio.open(href) as src:
            l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
            win = from_bounds(l, b, r, t, src.transform)
            # decimate to ~canonical size (memory-safe)
            band = src.read(1, window=win, out_shape=(H, W),
                            resampling=Resampling.bilinear).astype("float32")
            win_transform = src.window_transform(win)
            # account for decimation in the transform
            sx = (win.width / W) if win.width else 1
            sy = (win.height / H) if win.height else 1
            from rasterio.transform import Affine
            band_transform = win_transform * Affine.scale(sx, sy)
            return band, band_transform, src.crs

    red, tr, scrs = read_band("B04")
    nir, _, _ = read_band("B08")
    ndvi_src = (nir - red) / (nir + red + 1e-6)

    ndvi = np.full((H, W), np.nan, dtype="float32")
    reproject(source=ndvi_src, destination=ndvi,
              src_transform=tr, src_crs=scrs,
              dst_transform=dst_transform, dst_crs=dst_crs,
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)

    prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": -9999.0,
            "compress": "deflate", "tiled": True}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(ndvi), ndvi, -9999.0), 1)
