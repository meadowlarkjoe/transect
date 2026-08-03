"""Stage 1 — data acquisition.

Each module fetches one source into the per-AOI cache as GeoTIFF/GeoParquet/
GeoJSON, keyed by AOI bbox so re-runs are cheap. Clients are thin wrappers over
the access types declared in ``config/sources.yaml`` (wfs / wms / stac / download
/ overpass / rest). Network code is intentionally isolated here so the rest of
the pipeline operates purely on cached files.
"""
from __future__ import annotations

from ..config import Context, cache_dir


def run(ctx: Context) -> dict[str, str]:
    """Acquire all sources needed for the AOI. Idempotent: skips cached layers.
    Tolerant: a source still stubbed (NotImplementedError) is skipped so the
    implemented ones (e.g. tenure) still land. Returns per-source status."""
    from . import dem, ecoforestiere, hydro, roads, sentinel, tenure, zones

    steps = [
        ("zones", zones.fetch),
        ("tenure", tenure.fetch),
        ("dem", dem.fetch),
        ("ecoforestiere", ecoforestiere.fetch),
        ("hydro", hydro.fetch),
        ("roads", roads.fetch),
        ("sentinel", sentinel.fetch),
    ]
    status: dict[str, str] = {}
    for name, fn in steps:
        try:
            fn(ctx)
            status[name] = "ok"
        except NotImplementedError:
            status[name] = "todo"
        except Exception as exc:  # noqa: BLE001 — surface, don't abort the batch
            status[name] = f"error: {exc}"
    return status


def cached(ctx: Context, filename: str):
    """Path helper: cache/<aoi>/<filename>."""
    return cache_dir(ctx.aoi.name) / filename
