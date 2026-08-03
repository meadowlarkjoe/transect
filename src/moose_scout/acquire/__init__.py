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
    import os

    # Network guards: a slow/stalled data source must TIME OUT and raise (then the
    # per-source try/except below skips it) rather than hang the whole job forever.
    for k, v in (("GDAL_HTTP_TIMEOUT", "40"), ("GDAL_HTTP_CONNECTTIMEOUT", "15"),
                 ("GDAL_HTTP_MAX_RETRY", "2"), ("GDAL_HTTP_RETRY_DELAY", "3")):
        os.environ.setdefault(k, v)
    try:
        import osmnx as ox
        ox.settings.timeout = 90
        try:
            ox.settings.requests_timeout = 90
        except Exception:
            pass
        # Don't subdivide the AOI into ~20+ sequential Overpass sub-queries (the
        # "N times your configured max query area" warning) — that's the main reason
        # acquire crawled for ~10 min. Fire-Lake-sized boxes are sparse; fetch them in
        # one query. Raise the cap well above any AOI we build (radius ≤120 km).
        try:
            ox.settings.max_query_area_size = 5_000_000_000  # m² (5,000 km²)
        except Exception:
            pass
        # overpass-api.de (osmnx's default) and its kumi mirror BLOCK this droplet's
        # DigitalOcean IP outright (fast connection-refused) → every OSM fetch came
        # back empty (roads/water = infra:0). This mirror answers from cloud IPs and
        # has global coverage. Overridable via env if it ever goes down.
        try:
            ox.settings.overpass_url = os.environ.get(
                "OVERPASS_URL", "https://maps.mail.ru/osm/tools/overpass/api")
        except Exception:
            pass
    except Exception:
        pass

    from . import dem, ecoforestiere, fire, hydro, roads, sentinel, tenure, zones

    steps = [
        ("zones", zones.fetch),
        ("tenure", tenure.fetch),
        ("dem", dem.fetch),
        ("ecoforestiere", ecoforestiere.fetch),
        ("fire", fire.fetch),          # burn history → disturbance-age browse curve
        ("hydro", hydro.fetch),
        ("roads", roads.fetch),
        ("sentinel", sentinel.fetch),
    ]
    # Hard wall-clock timeout per source: a stalled download (e.g. a slow Overpass
    # mirror that accepts the connection then hangs, defeating the request timeout)
    # must NOT freeze the whole job. Each source runs in its own worker; if it blows
    # the budget we abandon it and press on with a degraded-but-complete result.
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as _FTimeout
    src_timeout = int(os.environ.get("ACQUIRE_SOURCE_TIMEOUT", "200"))
    status: dict[str, str] = {}
    for name, fn in steps:
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            pool.submit(fn, ctx).result(timeout=src_timeout)
            status[name] = "ok"
        except _FTimeout:
            status[name] = "timeout"       # stalled source can no longer hang the job
        except NotImplementedError:
            status[name] = "todo"
        except Exception as exc:  # noqa: BLE001 — surface, don't abort the batch
            status[name] = f"error: {exc}"
        finally:
            pool.shutdown(wait=False)       # abandon a stuck worker thread; move on
    return status


def cached(ctx: Context, filename: str):
    """Path helper: cache/<aoi>/<filename>."""
    return cache_dir(ctx.aoi.name) / filename
