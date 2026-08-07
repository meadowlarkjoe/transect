"""Sentinel-2 L2A NDVI (Microsoft Planetary Computer STAC).

North of the écoforestière limit this is the primary vegetation signal: NDVI separates
productive regenerating browse / riparian shrub (high) from open water, rock, and recent
burns (low), and closed mature conifer (moderate). Bands are read DECIMATED to the
canonical grid (10 m → 40 m via COG overviews) so a 70 km box stays within a 2 GB VM.
Writes cache/<aoi>/ndvi.tif plus ndvi.json recording which scenes it actually used.

TWO THINGS THIS FIXES, and the second is the serious one (T10.16).

1. THE WINDOW WAS FROZEN. It read `datetime="2023-07-01/2024-09-15"` — a literal, so
   the greenness behind every browse score was built from 2023–24 imagery no matter
   when the analysis ran, and drifted further out of date every day that stood. Cuts
   and burns newer than Sept 2024 were invisible to it, on ground whose whole browse
   story is disturbance age. The window now follows the run date.

2. IT WAS COMPOSITING SNOW. That window spanned a boreal winter, and scenes were ranked
   by LOWEST CLOUD — but snow is not cloud, and a snowfield reads as a beautifully
   clear scene. Measured on the two test boxes: 3 of the 10 scenes composited over Fire
   Lake were 2023-12-08 at 87–93% snow, and 2 of 10 over Rouyn were 2023-11-25 at 54%.
   Snow reflects high in BOTH red and NIR, so its NDVI collapses toward zero and drags
   the per-pixel median down with it. Removing those scenes moved mean NDVI 0.272 →
   0.320 at Rouyn (p10 0.149 → 0.225) and shifted 38% of the box by more than 0.05;
   at Fire Lake, 12% of cells. The browse surface has been reading systematically LOW,
   silently, on more than a third of some boxes.

   So the search is now confined to the GROWING SEASON and snow-flagged scenes are
   rejected outright. NDVI for browse means leaf-on greenness; there is no version of
   this question a December scene helps answer.
"""
from __future__ import annotations

import json
from datetime import date

from ..config import Context, cache_dir
from .. import rasterio_utils as ru
from ..rasterio_utils import target_grid

OUT = "ndvi.tif"
SIDECAR = "ndvi.json"

# Leaf-on window for the boreal / mixedwood range this engine covers. Starts after
# spring green-up completes and ends before senescence, so every scene in the pool is
# measuring the same thing. (Regional enough to belong in a region profile eventually —
# see the note in docs/BACKLOG.md — but wrong everywhere as a hardcoded 14-month span.)
SEASON_START = (6, 15)
SEASON_END = (9, 20)
# How far back to look for a usable season before giving up. Three years is enough to
# ride out a smoke-covered or persistently cloudy summer without reaching imagery so old
# that a cutblock has closed in since.
YEARS_BACK = 3
MAX_CLOUD = 25.0
# A scene with more than a trace of snow is not measuring vegetation. The winter scenes
# that prompted this carried 54–93%; the threshold is low because late-September snow at
# altitude is real and equally useless.
MAX_SNOW = 5.0
MAX_SCENES = 10


def season_windows(today: date, years_back: int = YEARS_BACK):
    """Growing-season windows to search, NEWEST FIRST.

    Newest-first matters: the caller stops as soon as it has enough scenes, so a box
    with good current imagery never reaches back a year, and one clouded out all summer
    degrades to last season rather than to nothing.
    """
    out = []
    for y in range(today.year, today.year - years_back - 1, -1):
        start = date(y, *SEASON_START)
        end = date(y, *SEASON_END)
        if start > today:
            continue                       # this season has not begun yet
        out.append((start, min(end, today)))
    return out


def _usable(item) -> bool:
    """Reject scenes that are not measuring leaf-on vegetation."""
    p = item.properties or {}
    cloud = float(p.get("eo:cloud_cover") or 0.0)
    snow = float(p.get("s2:snow_ice_percentage") or 0.0)
    return cloud < MAX_CLOUD and snow <= MAX_SNOW


def imagery_epoch(today: date) -> int:
    """The newest season-year whose imagery we would try to use.

    This is the geography cache's freshness key: an ndvi.tif whose sidecar predates the
    current epoch is last year's answer, and the cache would otherwise serve it forever
    because its key is only geometry. One re-fetch per season, not per run.
    """
    wins = season_windows(today)
    return wins[0][0].year if wins else today.year - 1


def fetch(ctx: Context, today: date | None = None) -> None:
    import os

    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client

    cache = cache_dir(ctx.aoi.name)
    out, side = cache / OUT, cache / SIDECAR
    today = today or date.today()
    epoch = imagery_epoch(today)

    # Cached only if it is also CURRENT. A bare ndvi.tif is a pre-T10.16 file built from
    # the frozen window (and quite possibly from snow); one whose sidecar names an older
    # season is simply last year's greenness.
    if out.exists() and out.stat().st_size > 0 and side.exists():
        try:
            if int(json.loads(side.read_text()).get("epoch") or 0) >= epoch:
                return
        except Exception:
            pass

    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                      modifier=pc.sign_inplace)

    # MOSAIC, not a single scene. One Sentinel-2 tile is ~110 km, so limit=1 left most
    # of a large AOI OUTSIDE the scene footprint — and outside the footprint reflectance
    # is 0, which made NDVI = (0-0)/(0+1e-6) = 0. That coverage-gap-as-zero entered the
    # habitat model as "barren" and produced sharp horizontal SCENE-EDGE BANDS in
    # huntability and thermal refuge. We take several low-cloud scenes and per-pixel
    # nan-median them, filling the box and shrugging off residual cloud.
    picked, seasons = [], []
    for start, end in season_windows(today):
        if len(picked) >= MAX_SCENES:
            break
        search = cat.search(
            collections=["sentinel-2-l2a"],
            bbox=[minlon, minlat, maxlon, maxlat],
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": MAX_CLOUD}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            limit=20,
        )
        got = [it for it in search.items() if _usable(it)]
        if got:
            seasons.append(start.year)
            picked.extend(got[: MAX_SCENES - len(picked)])
    if not picked:
        raise RuntimeError(
            f"no leaf-on, snow-free Sentinel-2 scene for this AOI in the last "
            f"{YEARS_BACK} growing seasons")

    dst_crs, dst_transform, W, H = target_grid(ctx)
    aoi_wgs = (minlon, minlat, maxlon, maxlat)

    def band_on_grid(item, asset_key):
        # Reproject B04/B08 onto the canonical grid with a window CLAMPED to the scene's
        # real extent. The previous read used an out-of-bounds window plus a win.width/W
        # transform, which sub-pixel-misregistered every partially-covering scene and
        # left horizontal seams once the scenes were median-composited.
        with rasterio.open(item.assets[asset_key].href) as src:
            arr, _ = ru.reproject_window(src, dst_crs, dst_transform, W, H, aoi_wgs,
                                         resampling="bilinear")
        return arr

    layers, used = [], []
    for item in picked:
        try:
            red = band_on_grid(item, "B04")
            nir = band_on_grid(item, "B08")
        except Exception:
            continue
        if red is None or nir is None:
            continue
        # Sentinel-2 L2A nodata is 0 reflectance — mask it so a coverage gap is NaN,
        # NOT a valid "zero greenness" reading.
        with np.errstate(all="ignore"):
            valid = np.isfinite(red) & np.isfinite(nir) & (red > 0) & (nir > 0)
            dst = np.where(valid, (nir - red) / (nir + red + 1e-6), np.nan).astype("float32")
        if np.isfinite(dst).any():
            layers.append(dst)
            used.append(item)
    if not layers:
        raise RuntimeError("Sentinel-2 scenes found but none yielded valid NDVI over the AOI")

    # An all-NaN column is a real, expected case — a cell no scene covered — and
    # nanmedian warns about it. errstate does not catch that warning, so it printed on
    # every run and read like a fault. The NaN is what we want: it becomes nodata, which
    # habitat.py already handles as "no satellite here" rather than "barren".
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ndvi = np.nanmedian(np.stack(layers, axis=0), axis=0).astype("float32")

    prof = {"driver": "GTiff", "dtype": "float32", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": -9999.0,
            "compress": "deflate", "tiled": True}
    with rasterio.open(out, "w", **prof) as dst:
        dst.write(np.where(np.isfinite(ndvi), ndvi, -9999.0), 1)

    dates = sorted(f"{it.datetime:%Y-%m-%d}" for it in used)
    side.write_text(json.dumps({
        "epoch": epoch,
        "run_date": today.isoformat(),
        "scenes": dates,
        "n": len(dates),
        "newest": dates[-1] if dates else None,
        "oldest": dates[0] if dates else None,
        "seasons": sorted(set(seasons), reverse=True),
        "max_cloud": MAX_CLOUD,
        "max_snow": MAX_SNOW,
    }))
    print(f"[sentinel] {len(dates)} leaf-on scenes from season(s) "
          f"{', '.join(str(s) for s in sorted(set(seasons), reverse=True))} "
          f"({dates[0]} → {dates[-1]})")
