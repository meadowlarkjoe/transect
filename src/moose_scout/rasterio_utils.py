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


def class_fractions(src, classes, dst_crs, dst_transform, W, H, aoi_wgs84,
                    budget_px=24_000_000):
    """AREAL FRACTION of each class, measured at the source's NATIVE resolution and
    averaged into the analysis grid. Returns {class: float32 (H, W) in 0..1}, plus a
    coverage mask.

    WHY THIS EXISTS (#77/#78). Land cover is 10 m; the analysis grid is typically 40 m.
    `reproject_window` decimates and then takes the NEAREST native pixel, so one pixel
    in sixteen decided the class of the whole cell — a cell that is genuinely half
    conifer and half regen came out as "conifer" or "shrub" on a coin flip. That is not
    a rounding error: cover↔food INTERSPERSION is the dominant term in the habitat
    model, and the sub-cell mixture is exactly the signal it wants. Measuring the
    fraction keeps it.

    Aggregation is areal mean of a binary mask, which is the definition of "what
    fraction of this cell is class k" — not a resample of a category, which has no
    meaningful average.

    TILED (#76) over destination row-bands so the native-resolution read is bounded no
    matter how big the box: the whole point is to raise the resolution ceiling without
    raising peak memory with it.
    """
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject, transform_bounds
    from rasterio.windows import Window, from_bounds

    minlon, minlat, maxlon, maxlat = aoi_wgs84
    out = {k: np.zeros((H, W), dtype="float32") for k in classes}
    seen = np.zeros((H, W), dtype=bool)

    # How many destination rows can we do at once? Estimate the native pixels each dest
    # row pulls in, from the source/destination resolution ratio.
    try:
        src_res = abs(src.transform.a)
        dst_res = abs(dst_transform.a)
        ratio = max(1.0, dst_res / max(src_res, 1e-9))
    except Exception:
        src_res, dst_res, ratio = 10.0, 40.0, 4.0
    # Block factor: collapse native pixels to ~half a destination cell before warping.
    # Constant for the whole call, and the source window is snapped to a multiple of it,
    # so block boundaries sit on a GLOBAL grid and cannot shift with the tiling — that is
    # what makes the tiled result identical to the untiled one.
    bf = int(max(1, np.floor(dst_res / (2.0 * src_res))))
    per_row = max(1.0, W * ratio * ratio)
    band = int(max(1, min(H, budget_px // per_row)))

    for r0 in range(0, H, band):
        r1 = min(H, r0 + band)
        sub_tr = dst_transform * Affine.translation(0, r0)
        # bounds of this destination band, in the source CRS
        left, top = sub_tr * (0, 0)
        right, bottom = sub_tr * (W, r1 - r0)
        try:
            l, b, rr, t = transform_bounds(dst_crs, src.crs, left, bottom, right, top)
        except Exception:
            continue
        win = from_bounds(l, b, rr, t, src.transform)
        c0 = max(0, int(np.floor(win.col_off)) - 1)
        rw0 = max(0, int(np.floor(win.row_off)) - 1)
        c1 = min(src.width, int(np.ceil(win.col_off + win.width)) + 1)
        rw1 = min(src.height, int(np.ceil(win.row_off + win.height)) + 1)
        # snap DOWN to the global block grid so blocks never move between tilings
        c0 -= c0 % bf
        rw0 -= rw0 % bf
        if c1 <= c0 or rw1 <= rw0:
            continue
        win = Window(c0, rw0, c1 - c0, rw1 - rw0)
        # NATIVE resolution — no decimation. That is the entire point; decimating here
        # would throw away the sub-cell detail we came to measure.
        arr = src.read(1, window=win)
        src_tr = src.window_transform(win)
        bh = r1 - r0

        # AGGREGATE IN SOURCE SPACE FIRST.
        #
        # The obvious implementation — warp one full-resolution binary mask per class —
        # is correct and far too slow: eight ~50-megapixel warps per tile took over ten
        # minutes on a 70 km box and blew the per-source time budget, which would have
        # silently degraded the layer to nothing.
        #
        # But a class FRACTION block-averages exactly: the mean of a binary mask over a
        # block IS the fraction of that block in the class. So collapse the native array
        # to about half the destination cell size with a plain numpy block mean (cheap,
        # no reprojection), then warp the small float fraction maps. Same answer, a
        # fraction of the work — and it is still "measured at native resolution,
        # aggregated late", just aggregated in two cheap steps instead of one dear one.
        _bf = bf
        if bf > 1:
            hh = (arr.shape[0] // bf) * bf
            ww = (arr.shape[1] // bf) * bf
            if hh >= bf and ww >= bf:
                sub = arr[:hh, :ww]
                src_tr = src_tr * Affine.scale(bf, bf)
            else:
                _bf, sub = 1, arr
        else:
            sub = arr

        def _blockmean(m, _bf=None):
            """Exact areal fraction over bf×bf native blocks."""
            f = _bf if _bf else 1
            if f == 1:
                return m
            return m.reshape(m.shape[0] // f, f, m.shape[1] // f, f).mean(axis=(1, 3))

        cov = np.zeros((bh, W), dtype="float32")
        reproject(_blockmean(np.ones(sub.shape, dtype="float32"), _bf), cov,
                  src_transform=src_tr, src_crs=src.crs,
                  dst_transform=sub_tr, dst_crs=dst_crs,
                  src_nodata=None, dst_nodata=0.0, resampling=Resampling.average)
        band_seen = cov > 0.01
        seen[r0:r1] |= band_seen

        for k in classes:
            m = _blockmean((sub == k).astype("float32"), _bf)
            dst = np.zeros((bh, W), dtype="float32")
            reproject(m, dst, src_transform=src_tr, src_crs=src.crs,
                      dst_transform=sub_tr, dst_crs=dst_crs,
                      src_nodata=None, dst_nodata=0.0, resampling=Resampling.average)
            # Destination bands are disjoint, so this writes each cell once. Mosaicking
            # ACROSS sources is the caller's job (tiles of one product don't overlap).
            blk = out[k][r0:r1]
            blk[band_seen] = dst[band_seen]
            out[k][r0:r1] = blk
    return out, seen


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
