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
    # MOSAIC, not a single scene. One Sentinel-2 tile is ~110 km, so limit=1 left most
    # of a large AOI OUTSIDE the scene footprint — and outside the footprint reflectance
    # is 0, which made NDVI = (0-0)/(0+1e-6) = 0. That coverage-gap-as-zero entered the
    # habitat model as "barren" and produced sharp horizontal SCENE-EDGE BANDS in
    # huntability and thermal refuge (and suppressed scores across the gap). We now take
    # several low-cloud scenes and per-pixel nan-median them, filling the box and
    # shrugging off residual cloud.
    search = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=[minlon, minlat, maxlon, maxlat],
        datetime="2023-07-01/2024-09-15",
        query={"eo:cloud_cover": {"lt": 25}},
        sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
        limit=20,
    )
    items = list(search.items())
    if not items:
        raise RuntimeError("no low-cloud Sentinel-2 scene for AOI window")

    dst_crs, dst_transform, W, H = target_grid(ctx)

    def read_band(item, asset_key):
        href = item.assets[asset_key].href
        with rasterio.open(href) as src:
            l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
            win = from_bounds(l, b, r, t, src.transform)
            band = src.read(1, window=win, out_shape=(H, W),
                            resampling=Resampling.bilinear).astype("float32")
            win_transform = src.window_transform(win)
            sx = (win.width / W) if win.width else 1
            sy = (win.height / H) if win.height else 1
            from rasterio.transform import Affine
            return band, win_transform * Affine.scale(sx, sy), src.crs

    # Composite: accumulate each scene's NDVI on the canonical grid, then nan-median.
    # Capped so a huge AOI × many scenes stays inside the 2 GB VM.
    MAX_SCENES = 10
    layers = []
    for item in items[:MAX_SCENES]:
        try:
            red, tr, scrs = read_band(item, "B04")
            nir, _, _ = read_band(item, "B08")
        except Exception:
            continue
        # Sentinel-2 L2A nodata is 0 reflectance — mask it so a coverage gap is NaN,
        # NOT a valid "zero greenness" reading. This is the actual bug fix.
        valid = (red > 0) & (nir > 0)
        ndvi_src = np.where(valid, (nir - red) / (nir + red + 1e-6), np.nan).astype("float32")
        dst = np.full((H, W), np.nan, dtype="float32")
        reproject(source=ndvi_src, destination=dst,
                  src_transform=tr, src_crs=scrs,
                  dst_transform=dst_transform, dst_crs=dst_crs,
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
        if np.isfinite(dst).any():
            layers.append(dst)
    if not layers:
        raise RuntimeError("Sentinel-2 scenes found but none yielded valid NDVI over the AOI")
    # nan-median across scenes: fills each pixel from whatever scene(s) covered it.
    with np.errstate(all="ignore"):
        ndvi = np.nanmedian(np.stack(layers, axis=0), axis=0).astype("float32")

    prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": -9999.0,
            "compress": "deflate", "tiled": True}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(ndvi), ndvi, -9999.0), 1)
