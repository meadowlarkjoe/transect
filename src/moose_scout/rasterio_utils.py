"""Small shared raster helpers (read/write GeoTIFF on the working grid)."""
from __future__ import annotations

from pathlib import Path


def target_grid(ctx):
    """The canonical analysis grid for an AOI: the AOI bbox as a TIGHT axis-aligned
    raster in the working CRS at raster_resolution_m. Every layer is reprojected
    onto this exact grid so the HSM overlay aligns cell-for-cell. Returns
    (dst_crs, transform, width, height)."""
    import math

    from rasterio.transform import from_origin
    from rasterio.warp import transform_bounds

    dst_crs = ctx.model.working_crs
    res = ctx.model.raster_resolution_m
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    l, b, r, t = transform_bounds("EPSG:4326", dst_crs, minlon, minlat, maxlon, maxlat)
    w = int(math.ceil((r - l) / res))
    h = int(math.ceil((t - b) / res))
    return dst_crs, from_origin(l, t, res, res), w, h


def read(path) -> tuple:
    """Return (array float32 with nodata->nan, profile)."""
    import numpy as np
    import rasterio

    with rasterio.open(path) as src:
        a = src.read(1).astype("float32")
        prof = src.profile
        nd = src.nodata
    if nd is not None:
        a[a == nd] = np.nan
    return a, prof


def write(path, arr, profile, nodata=-9999.0) -> Path:
    import numpy as np
    import rasterio

    prof = dict(profile)
    prof.update(dtype="float32", count=1, nodata=nodata, compress="deflate", tiled=True)
    out = np.where(np.isnan(arr), nodata, arr).astype("float32")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(out, 1)
    return Path(path)


def normalize(arr, lo=None, hi=None, invert=False):
    """Scale to 0..1 using given or 2nd/98th percentile bounds; nan-safe."""
    import numpy as np

    a = arr.astype("float32")
    finite = np.isfinite(a)
    if lo is None:
        lo = np.nanpercentile(a[finite], 2) if finite.any() else 0.0
    if hi is None:
        hi = np.nanpercentile(a[finite], 98) if finite.any() else 1.0
    if hi <= lo:
        hi = lo + 1e-6
    out = np.clip((a - lo) / (hi - lo), 0, 1)
    if invert:
        out = 1 - out
    out[~finite] = np.nan
    return out
