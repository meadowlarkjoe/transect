"""Shared acquisition helpers: cached HTTP downloads and CRS-aware AOI clipping.

Province-wide source files (e.g. TFS tenure) are cached once under
``cache/_shared`` and reused across every Quebec AOI; per-AOI clips are written
under ``cache/<aoi>``.
"""
from __future__ import annotations

import os
import ssl
import urllib.request
from pathlib import Path

from ..config import Context

_UA = {"User-Agent": "moose-scout/0.1 (+https://local)"}
_SSL = ssl.create_default_context()


def shared_dir() -> Path:
    d = Path(os.environ.get("MOOSE_SCOUT_CACHE", "cache")) / "_shared"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(url: str, dest: str | Path, force: bool = False, timeout: int = 300) -> Path:
    """Download ``url`` to ``dest`` unless already cached (non-empty)."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0 and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, context=_SSL, timeout=timeout) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)
    return dest


def read_clip(src: str | Path, ctx: Context):
    """Read ``src`` clipped to the AOI bbox, returned in WGS84.

    The AOI bbox is defined in WGS84 but the source may be in any CRS (TFS is
    EPSG:32198). We read the source CRS first, transform the bbox into it, filter
    server-side/at-read-time, then reproject the result to WGS84 for storage.
    """
    import geopandas as gpd
    import pyogrio
    from pyproj import Transformer
    from shapely.geometry import box

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()

    info = pyogrio.read_info(str(src))
    src_crs = info.get("crs") or "EPSG:4326"

    if str(src_crs).upper().endswith("4326") or "4326" in str(src_crs):
        bbox = (minlon, minlat, maxlon, maxlat)
    else:
        tr = Transformer.from_crs("EPSG:4326", src_crs, always_xy=True)
        xs, ys = tr.transform([minlon, maxlon], [minlat, maxlat])
        bbox = (min(xs), min(ys), max(xs), max(ys))

    gdf = gpd.read_file(str(src), bbox=bbox, engine="pyogrio")
    if len(gdf) and gdf.crs is not None:
        try:
            if gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(4326)
        except Exception:
            pass
    return gdf


def pick_field(columns, *candidates: str) -> str | None:
    """Case-insensitive fuzzy field picker (attribute names vary across MFFP
    layers). Returns the first column whose lowercased name contains any
    candidate substring."""
    low = {c.lower(): c for c in columns}
    for cand in candidates:
        cand = cand.lower()
        for lc, orig in low.items():
            if cand in lc:
                return orig
    return None
