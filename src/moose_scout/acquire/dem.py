"""Elevation: MRDEM-30 (NRCan Medium Resolution DEM, national 30 m, 2024) — the
reliable choice for the far north where HRDEM LiDAR is patchy. The DTM (bare
earth) COG is windowed-read over HTTP (COG range requests — no full download),
then reprojected to the working grid. Writes cache/<aoi>/dem.tif.

HRDEM (1 m) can be substituted where it genuinely covers an AOI; MRDEM-30 is the
dependable default at Fire Lake.
"""
from __future__ import annotations

import os

from ..config import Context, cache_dir

# MRDEM-30 DTM national COG (public S3, no auth).
MRDEM_DTM = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"

OUT = "dem.tif"


def fetch(ctx: Context) -> None:
    out = cache_dir(ctx.aoi.name) / OUT
    if out.exists() and out.stat().st_size > 0:
        return

    import numpy as np
    import rasterio
    from rasterio.warp import Resampling, reproject, transform_bounds
    from rasterio.windows import from_bounds

    from ..rasterio_utils import target_grid

    # COG-friendly GDAL settings: don't scan the bucket, cache range reads.
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    dst_crs, dst_transform, w, h = target_grid(ctx)  # tight canonical grid

    with rasterio.open(f"/vsicurl/{MRDEM_DTM}") as src:
        # Read a slightly padded source window covering the AOI, then reproject
        # into the tight canonical grid (cropping any projection over-hang).
        l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
        pad = 0.05 * max(r - l, t - b)
        win = from_bounds(l - pad, b - pad, r + pad, t + pad, src.transform)
        data = src.read(1, window=win)
        src_transform = src.window_transform(win)
        src_crs = src.crs
        nodata = src.nodata

    dst = np.full((h, w), nodata if nodata is not None else -9999.0, dtype="float32")
    reproject(
        source=data, destination=dst,
        src_transform=src_transform, src_crs=src_crs,
        dst_transform=dst_transform, dst_crs=dst_crs,
        src_nodata=nodata, dst_nodata=nodata if nodata is not None else -9999.0,
        resampling=Resampling.bilinear,
    )

    profile = {
        "driver": "GTiff", "dtype": "float32", "count": 1,
        "height": h, "width": w, "crs": dst_crs, "transform": dst_transform,
        "nodata": nodata if nodata is not None else -9999.0,
        "compress": "deflate", "tiled": True,
    }
    with rasterio.open(out, "w", **profile) as dstf:
        dstf.write(dst, 1)
