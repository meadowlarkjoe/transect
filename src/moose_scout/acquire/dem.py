"""Elevation. Two national products, best-available per cell (T9.10):

  HRDEM  — NRCan High Resolution DEM, airborne LiDAR bare-earth at 1 m, published as
           a mosaic of 500 km COG tiles in EPSG:3979 with overviews to /64. Ragged
           coverage: it exists where somebody flew it. Measured over the two test
           boxes — Rouyn 99.99%, Fire Lake 41%.
  MRDEM-30 — NRCan Medium Resolution DEM, national 30 m, 2024. Complete, everywhere,
           and the only thing available over most of the far north.

WHY THIS MATTERS AND IS NOT COSMETIC. Every terrain product derives from this file, and
two of them are answers a hunter acts on: the funnel NECK WIDTH and the glassing
prominence. A 30 m grid cannot resolve a 100 m neck or a small knob — which is exactly
what the relief basemap shows plainly and the model could not see.

DO NOT WARP THE TILE. A 1 m DTM over a 9 km box is ~81 M cells; over a 70 km box it is
~4.9 G. The window is read DECIMATED, which makes GDAL serve it from the COG's own
overview pyramid — the aggregation happens in SOURCE space, over source pixels, before
anything crosses the network or enters memory. What lands is a few hundred MB at most,
already at roughly the analysis resolution.

NODATA IS THE TRAP IN THAT PLAN. A decimated read averages -32767 straight into the
result wherever the window clips a void, and a cell that is 99% valid comes back ~330 m
low — wrong, plausible-looking, and invisible on a hillshade. So the validity FRACTION
is read alongside (`read_masks`, same decimation) and the contaminated mean is inverted
exactly:  mean_valid = (mixed - (1-f)*nodata) / f.

THE SEAM. Splicing 1 m data into 30 m data would leave a step at every void edge, and a
step is a cliff to a slope operator — it would manufacture funnels and glassing knobs
along the boundary of the LiDAR flight lines. Measured first: the two products agree to
0.05 m of bias (sd 3.5-4.8 m, which is real detail MRDEM smooths away). So there is no
datum offset to correct, only local difference, and the fill is MRDEM plus a smoothed
LOCAL delta carried out from the covered ground — continuous across the join by
construction.

Writes cache/<aoi>/dem.tif on the canonical grid, plus dem_source.json recording which
source covered how much. That sidecar is also what makes the geography cache honest:
`dem.tif` without it is a pre-T9.10 file from an older run, and is re-fetched rather
than served as if it had been through this path.
"""
from __future__ import annotations

import json
import os

from ..config import Context, cache_dir

# MRDEM-30 DTM national COG (public S3, no auth).
MRDEM_DTM = "https://canelevation-dem.s3.ca-central-1.amazonaws.com/mrdem-30/mrdem-30-dtm.tif"

# HRDEM mosaic tiles. The index is a regular 500 km grid in EPSG:3979 — verified
# against the published bounds of 1_3, 6_2, 8_1, 10_5 and 11_4, which all match — so
# the covering tiles are computed rather than discovered, and each candidate's REAL
# bounds are re-checked on open before anything is read from it.
HRDEM_TMPL = ("https://canelevation-dem.s3.ca-central-1.amazonaws.com/"
              "hrdem-mosaic-{res}/{tile}-mosaic-{res}-dtm.tif")
HRDEM_CRS = "EPSG:3979"
TILE_M = 500_000
TILE_COL0, TILE_ROW0 = 6, 3          # tile (c,r) origin = ((c-6)*500km, (r-3)*500km)

# Read budget for the decimated source read, and for the terrain fine grid it becomes.
# 9 M cells is ~36 MB as float32; the fine grid is then carried through a distance
# transform (float64) and a couple of filters, so this is the number that keeps the
# 4 GB worker alive on the biggest box. It sets the effective resolution: ~23 m over a
# 70 km box, and the FINEST_FRAC_OF_RES cap (10 m) binds for anything under ~30 km.
READ_BUDGET_PX = 9_000_000
# No point reading finer than this relative to the analysis grid — reproject only needs
# enough detail to resample from, and past 4x it is memory spent on nothing.
FINEST_FRAC_OF_RES = 0.25
# Below this valid fraction a decimated cell is mostly void; drop it rather than trust
# the inverted mean over a handful of real pixels.
MIN_VALID_FRAC = 0.5

OUT = "dem.tif"
FINE = "dem_fine.tif"        # terrain fine grid — LiDAR only, voids left as voids
SIDECAR = "dem_source.json"


def _tiles_for(bounds_3979) -> list[str]:
    """Tile ids whose 500 km cell touches the AOI bounds (already in EPSG:3979)."""
    import math

    l, b, r, t = bounds_3979
    c0 = math.floor(l / TILE_M) + TILE_COL0
    c1 = math.floor((r - 1e-6) / TILE_M) + TILE_COL0
    r0 = math.floor(b / TILE_M) + TILE_ROW0
    r1 = math.floor((t - 1e-6) / TILE_M) + TILE_ROW0
    return [f"{c}_{rr}" for c in range(c0, c1 + 1) for rr in range(r0, r1 + 1)]


def _read_aggregated(src, aoi_wgs84, read_res_m):
    """Window of `src` covering the AOI, aggregated in SOURCE space to ~read_res_m.

    Returns (values float32 with NaN voids, transform) or (None, None). The decimation
    is what makes GDAL serve this from the COG overviews instead of the 1 m band.
    """
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds

    minlon, minlat, maxlon, maxlat = aoi_wgs84
    l, b, r, t = transform_bounds("EPSG:4326", src.crs, minlon, minlat, maxlon, maxlat)
    win = from_bounds(l, b, r, t, src.transform)
    c0 = max(0, int(np.floor(win.col_off)))
    r0 = max(0, int(np.floor(win.row_off)))
    c1 = min(src.width, int(np.ceil(win.col_off + win.width)))
    r1 = min(src.height, int(np.ceil(win.row_off + win.height)))
    if c1 <= c0 or r1 <= r0:
        return None, None                       # AOI misses this tile's real extent
    win = Window(c0, r0, c1 - c0, r1 - r0)

    src_res = abs(src.transform.a)
    step = max(1.0, read_res_m / src_res)
    ow = max(1, int(round(win.width / step)))
    oh = max(1, int(round(win.height / step)))

    vals = src.read(1, window=win, out_shape=(oh, ow),
                    resampling=Resampling.average).astype("float64")
    # Validity fraction over the same aggregation, so the nodata contamination in
    # `vals` can be undone exactly rather than guessed at with a threshold.
    frac = (src.read_masks(1, window=win, out_shape=(oh, ow),
                           resampling=Resampling.average).astype("float64") / 255.0)
    nod = src.nodata
    if nod is not None:
        with np.errstate(invalid="ignore", divide="ignore"):
            vals = (vals - (1.0 - frac) * float(nod)) / frac
    vals = np.where(frac >= MIN_VALID_FRAC, vals, np.nan).astype("float32")
    tr = src.window_transform(win) * Affine.scale(win.width / ow, win.height / oh)
    return vals, tr


def _to_grid(vals, src_tr, src_crs, dst_crs, dst_transform, w, h):
    import numpy as np
    from rasterio.warp import Resampling, reproject

    dst = np.full((h, w), np.nan, dtype="float32")
    reproject(source=vals, destination=dst,
              src_transform=src_tr, src_crs=src_crs,
              dst_transform=dst_transform, dst_crs=dst_crs,
              src_nodata=np.nan, dst_nodata=np.nan,
              resampling=Resampling.bilinear)
    return dst


def _fetch_hrdem(ctx, read_res_m):
    """LiDAR terrain over the AOI, still in SOURCE space, one entry per covering tile.

    Returns (parts, note). `parts` is a list of (values, transform, crs) ready to be
    laid onto any destination grid — the caller wants two (the 40 m analysis grid and
    the terrain fine grid) and re-reading the network for the second would be silly.
    An empty list means no LiDAR tile answered and MRDEM-30 carries the whole box.
    """
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds

    aoi = ctx.aoi.bbox_wgs84()
    tiles = _tiles_for(transform_bounds("EPSG:4326", HRDEM_CRS, *aoi))
    if not tiles:
        return [], "AOI outside the HRDEM tile grid"

    parts, used, tried = [], [], []
    native = None
    for tile in tiles:
        for res_name in ("1m", "2m"):            # 2 m is the fallback publication
            url = HRDEM_TMPL.format(res=res_name, tile=tile)
            tried.append(f"{tile}/{res_name}")
            try:
                with rasterio.open(f"/vsicurl/{url}") as src:
                    vals, tr = _read_aggregated(src, aoi, read_res_m)
                    if vals is None or not np.isfinite(vals).any():
                        break                    # tile exists but is void here
                    parts.append((vals, tr, src.crs))
                    native = abs(src.transform.a) if native is None else \
                        min(native, abs(src.transform.a))
                used.append(f"{tile}@{res_name}")
                break
            except Exception as e:  # noqa: BLE001 — a missing tile is normal, not fatal
                print(f"[dem] hrdem {tile} {res_name}: {type(e).__name__}: {str(e)[:90]}")
                continue

    if not parts:
        return [], f"no HRDEM tile covered the box (tried {', '.join(tried)})"
    return parts, {"tiles": used, "native_res_m": native}


def _mosaic(parts, dst_crs, dst_transform, w, h):
    """Lay the source-space tiles onto one destination grid, first valid wins."""
    import numpy as np

    out = np.full((h, w), np.nan, dtype="float32")
    for vals, tr, crs in parts:
        grid = _to_grid(vals, tr, crs, dst_crs, dst_transform, w, h)
        out = np.where(np.isfinite(out), out, grid)
    return out


def _blend(hr, mr):
    """MRDEM everywhere, replaced by LiDAR where it exists, joined without a step.

    The fill is `mr + smooth(hr - mr)`: the low-frequency difference measured on the
    covered ground and carried out across the void by a NaN-aware (normalized)
    convolution. At the join the fill already equals the LiDAR to within its
    high-frequency detail, so what is left for the slope operator to see is terrain
    roughness rather than a cliff along a flight line.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    ok = np.isfinite(hr)
    if not ok.any():
        return mr, 0.0
    if ok.all():
        return hr.astype("float32"), 1.0

    d = np.where(ok, hr - mr, 0.0).astype("float64")
    wgt = ok.astype("float64")
    sigma = 6.0                                   # ~240 m at 40 m — low-frequency only
    num = gaussian_filter(d, sigma=sigma, mode="nearest")
    den = gaussian_filter(wgt, sigma=sigma, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        delta = np.where(den > 1e-3, num / den, 0.0)
    filled = (mr + delta).astype("float32")
    return np.where(ok, hr, filled).astype("float32"), float(ok.mean())


def fetch(ctx: Context) -> None:
    out = cache_dir(ctx.aoi.name) / OUT
    side = cache_dir(ctx.aoi.name) / SIDECAR
    # The sidecar is part of the product. A dem.tif without one predates T9.10 and was
    # written by the MRDEM-only path — serving it from the geography cache would keep a
    # box on the 30 m surface forever with nothing saying so.
    if out.exists() and out.stat().st_size > 0 and side.exists():
        return

    import numpy as np
    import rasterio

    from ..rasterio_utils import target_grid

    # COG-friendly GDAL settings: don't scan the bucket, cache range reads.
    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

    aoi = ctx.aoi.bbox_wgs84()
    dst_crs, dst_transform, w, h = target_grid(ctx)   # tight canonical grid
    res = float(ctx.model.raster_resolution_m)

    # --- MRDEM-30: the complete base, and the only thing over most of the north ------
    with rasterio.open(f"/vsicurl/{MRDEM_DTM}") as src:
        vals, tr = _read_aggregated(src, aoi, min(res, 30.0))
        if vals is None:
            raise RuntimeError("MRDEM-30 does not cover this AOI")
        mr = _to_grid(vals, tr, src.crs, dst_crs, dst_transform, w, h)

    # --- HRDEM: LiDAR where somebody flew it ----------------------------------------
    # Read resolution from a pixel budget, floored at a quarter of the analysis grid.
    # This same number becomes the terrain FINE GRID, which is where the LiDAR actually
    # pays: measured on this box, swapping 30 m for 1 m under a fixed 40 m analysis grid
    # moved mean slope by 1.2% and mean |TPI| by 1.4% — nothing. Measuring the SAME
    # LiDAR at 10 m instead doubled the peak slope inside a 40 m cell and raised peak
    # |TPI| by half. The grid was the limit all along, and a fine grid over MRDEM-30
    # would be interpolation rather than information — which is why the two go together.
    area_m2 = (w * res) * (h * res)
    read_res = max(res * FINEST_FRAC_OF_RES, (area_m2 / READ_BUDGET_PX) ** 0.5)
    parts, note = [], "not attempted"
    if os.environ.get("HRDEM", "1") not in ("0", "off", "false"):
        try:
            parts, note = _fetch_hrdem(ctx, read_res)
        except Exception as e:  # noqa: BLE001 — LiDAR is the bonus, never the blocker
            parts, note = [], f"{type(e).__name__}: {str(e)[:120]}"
            print(f"[dem] HRDEM unavailable, using MRDEM-30: {note}")
    else:
        note = "disabled by HRDEM=0"

    if not parts:
        dem, frac, source, native = mr, 0.0, "mrdem-30", 30.0
        detail = {"fallback_reason": note if isinstance(note, str) else str(note)}
    else:
        dem, frac = _blend(_mosaic(parts, dst_crs, dst_transform, w, h), mr)
        native = float(note.get("native_res_m") or 1.0)
        source = "hrdem+mrdem-30" if frac < 0.995 else "hrdem"
        detail = {"tiles": note.get("tiles", [])}

    nodata = -9999.0

    def _write(path, arr, transform, width, height):
        profile = {
            "driver": "GTiff", "dtype": "float32", "count": 1,
            "height": height, "width": width, "crs": dst_crs, "transform": transform,
            "nodata": nodata, "compress": "deflate", "tiled": True,
        }
        with rasterio.open(path, "w", **profile) as dstf:
            dstf.write(np.where(np.isfinite(arr), arr, nodata).astype("float32"), 1)

    _write(out, dem, dst_transform, w, h)

    # --- the fine grid, written only when there is real detail to put on it ----------
    # An integer ratio to the analysis grid, so terrain.py can aggregate a fine cell
    # into its parent working cell by reshape rather than by resampling it back.
    fine = cache_dir(ctx.aoi.name) / FINE
    fine_res = None
    if parts and frac > 0.05:
        step = max(2, int(round(res / read_res)))
        fine_res = res / step
        fcrs, ftr, fw, fh = target_grid(ctx, fine_res)
        fine_dem = _mosaic(parts, fcrs, ftr, fw, fh)
        # No blend here: the fine grid exists to carry LiDAR detail, and MRDEM-30
        # resampled to 10 m is not detail — it is the same 30 m surface with more cells,
        # and averaging it in would let terrain.py mistake interpolation for terrain.
        # Voids stay voids; terrain.py falls back to the working grid there.
        _write(fine, fine_dem, ftr, fw, fh)
    elif fine.exists():
        fine.unlink()               # stale fine grid from a previous run must not linger

    side.write_text(json.dumps({
        "source": source,
        "native_res_m": native,
        "read_res_m": round(read_res, 2),
        "fine_res_m": fine_res,
        "fine_coverage_frac": round(frac, 4),
        "grid_res_m": res,
        **detail,
    }))
    print(f"[dem] {source} — LiDAR over {frac * 100:.1f}% of the box "
          f"(native {native} m, read at {read_res:.1f} m"
          f"{f', fine grid {fine_res:.1f} m' if fine_res else ''})")
