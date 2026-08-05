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


def reproject_window(src, dst_crs, dst_transform, W, H, aoi_wgs84,
                     band=1, resampling="bilinear"):
    """Read the part of an open source raster `src` that overlaps the AOI and reproject
    it onto the canonical (dst_crs, dst_transform, W, H) grid. Returns (float32 array,
    valid-bool mask), NaN where the source does not cover — so several tiles / scenes
    can be mosaicked cell-by-cell.

    THE BUG THIS REPLACES: callers built one window with `from_bounds` and did a
    decimated `src.read(window=win, out_shape=(H, W))` even when the window ran off the
    edge of the source (the AOI straddling a WorldCover / Sentinel tile boundary — the
    common case for any box bigger than one tile). rasterio clamps the read but the
    reconstructed `win.width / W` transform still assumes the full out-of-bounds window,
    so every tile landed sub-pixel-misregistered and the per-pixel median left regular
    HORIZONTAL SEAMS across huntability / thermal refuge (invisible on a small AOI that
    fits one tile, glaring on a 45 km box). Here the window is CLAMPED to the source's
    real pixels before the decimated read, so the transform matches what was read."""
    import numpy as np
    import rasterio
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject, transform_bounds
    from rasterio.windows import Window, from_bounds

    rs = getattr(Resampling, resampling)
    minlon, minlat, maxlon, maxlat = aoi_wgs84
    l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
    win = from_bounds(l, b, r, t, src.transform)
    # Clamp to the source's real extent (robust across rasterio versions) — no
    # out-of-bounds pixels enter the decimated read.
    c0 = max(0, int(np.floor(win.col_off)))
    r0 = max(0, int(np.floor(win.row_off)))
    c1 = min(src.width, int(np.ceil(win.col_off + win.width)))
    r1 = min(src.height, int(np.ceil(win.row_off + win.height)))
    if c1 <= c0 or r1 <= r0:
        return None, None
    win = Window(c0, r0, c1 - c0, r1 - r0)
    # Decimate the read so a full 3° tile stays inside a 2 GB VM, but keep it a little
    # finer than the destination so reproject has detail to resample from.
    scale = max(1.0, win.width / (W * 1.3), win.height / (H * 1.3))
    ow = max(1, int(round(win.width / scale)))
    oh = max(1, int(round(win.height / scale)))
    arr = src.read(band, window=win, out_shape=(oh, ow), resampling=rs).astype("float32")
    src_tr = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
    dst = np.full((H, W), np.nan, dtype="float32")
    reproject(arr, dst, src_transform=src_tr, src_crs=src.crs,
              dst_transform=dst_transform, dst_crs=dst_crs,
              src_nodata=None, dst_nodata=np.nan, resampling=rs)
    return dst, np.isfinite(dst)


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

    import os

    prof = dict(profile)
    prof.update(dtype="float32", count=1, nodata=nodata, compress="deflate", tiled=True)
    out = np.where(np.isnan(arr), nodata, arr).astype("float32")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # ATOMIC. Two reasons, both of which have teeth:
    #   1. A run killed mid-write (container restart, OOM) used to leave a TRUNCATED
    #      .tif behind, and every stage's "skip if it already exists" check would then
    #      happily reuse the corpse.
    #   2. The geography cache (#79) hands out HARDLINKS to shared layers. Writing in
    #      place would edit the shared inode and poison that layer for every future
    #      job; replace() swaps a fresh inode in and leaves the shared one alone.
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    try:
        with rasterio.open(tmp, "w", **prof) as dst:
            dst.write(out, 1)
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
    return path


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
