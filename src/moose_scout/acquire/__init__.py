"""Stage 1 — data acquisition.

Each module fetches one source into the per-AOI cache as GeoTIFF/GeoParquet/
GeoJSON, keyed by AOI bbox so re-runs are cheap. Clients are thin wrappers over
the access types declared in ``config/sources.yaml`` (wfs / wms / stac / download
/ overpass / rest). Network code is intentionally isolated here so the rest of
the pipeline operates purely on cached files.
"""
from __future__ import annotations

from ..config import Context, cache_dir


_OVERPASS_MIRRORS = [
    "https://overpass.private.coffee/api",
    "https://overpass.osm.ch/api",
    "https://overpass.openstreetmap.ru/api",
    "https://maps.mail.ru/osm/tools/overpass/api",   # works, but slow — last resort
    "https://overpass-api.de/api",                   # blocks this host, kept for other deploys
]
_PICKED: list = []


def _pick_overpass() -> str:
    """Return the first Overpass mirror that answers a trivial query quickly.

    Cached for the process. `OVERPASS_URL` forces a specific one.
    """
    import os
    import time
    import urllib.parse
    import urllib.request

    forced = os.environ.get("OVERPASS_URL")
    if forced:
        return forced
    if _PICKED:
        return _PICKED[0]

    # The probe must test COVERAGE, not just responsiveness. Several mirrors are
    # regional extracts — overpass.osm.ch answers a query about Québec in 13 s and
    # returns nothing at all, because it only holds Switzerland. So probe a tiny box
    # over downtown Montréal (guaranteed dense in any planet-wide database) and
    # require actual features back before trusting the mirror with a real fetch.
    import json as _json
    probe = ("[out:json][timeout:15];"
             "way[highway](45.5010,-73.5720,45.5045,-73.5680);out ids 3;")
    for base in _OVERPASS_MIRRORS:
        url = base.rstrip("/") + "/interpreter"
        try:
            t0 = time.time()
            req = urllib.request.Request(
                url, data=urllib.parse.urlencode({"data": probe}).encode(),
                headers={"User-Agent": "moose-scout/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status != 200:
                    continue
                body = _json.loads(r.read().decode("utf-8", "replace"))
                if not body.get("elements"):
                    continue                     # regional extract → no planet coverage
                if (time.time() - t0) > 20:
                    continue
                _PICKED.append(base)
                return base
        except Exception:
            continue
    _PICKED.append(_OVERPASS_MIRRORS[0])
    return _OVERPASS_MIRRORS[0]


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
        # Overpass mirror selection, by measurement rather than hope.
        # overpass-api.de (osmnx's default) and kumi BLOCK this droplet's DigitalOcean
        # IP outright, which silently emptied every OSM layer. mail.ru answers but is
        # catastrophically slow on road-dense boxes — a single 70 km AOI took 2.2 HOURS.
        # So probe the candidates with a tiny query and take the first fast responder.
        try:
            ox.settings.overpass_url = _pick_overpass()
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
    # Scale the budget with the box: a 134 km-wide AOI asks Overpass for vastly more
    # than a 32 km one, and losing the road network is not a cosmetic failure — with no
    # watercraft it used to zero out extraction across the whole map.
    _hw = float(getattr(ctx.aoi, "bbox_halfwidth_km", 35) or 35)
    src_timeout = int(os.environ.get(
        "ACQUIRE_SOURCE_TIMEOUT", str(int(min(600, max(200, 120 + 5.5 * _hw))))))
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
