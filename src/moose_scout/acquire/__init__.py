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
        # Mirror selection happens LATER, and only if some OSM layer is actually
        # missing — see below. (Why it is measured at all: overpass-api.de and kumi
        # BLOCK this droplet's IP outright, silently emptying every OSM layer, and
        # mail.ru answers but took 2.2 HOURS on one 70 km box.)
    except Exception:
        pass

    from . import baux, dem, ecoforestiere, fire, grhq, hydro, roads, sentinel, tenure, zones

    # GEOGRAPHY CACHE (#79). Every source below skips a layer that is already on disk,
    # so linking in what a previous job over this same box + grid already downloaded is
    # all it takes to turn the slow half of a run into a no-op. Nothing here can fail
    # the run: a miss just means we fetch, exactly as before.
    from .. import geocache
    cache = cache_dir(ctx.aoi.name)
    reused = []
    try:
        reused = geocache.restore(ctx, cache)
        k = geocache.key(ctx)
        if reused:
            print(f"[acquire] geocache HIT {k} — reused {len(reused)} layers, skipping "
                  f"their downloads: {', '.join(sorted(reused)[:8])}"
                  f"{'…' if len(reused) > 8 else ''}")
        elif geocache.slot(ctx).is_dir():
            # restore() links nothing when the job already HAS every layer. Reporting
            # that as a MISS was a lie that sent me hunting a cache bug that was not
            # there — the store was fine, the job dir was simply already complete.
            print(f"[acquire] geocache {k} — job cache already complete, nothing to restore")
        else:
            print(f"[acquire] geocache MISS {k} — fetching this box cold")
    except Exception as e:  # noqa: BLE001
        print(f"[acquire] geocache restore skipped: {e}")

    # Only probe Overpass if we are actually going to ASK it something. The probe walks
    # up to five mirrors at 20 s apiece, and it was running unconditionally at startup —
    # ~50 s of the 72 s a fully-cached run was taking, spent choosing a server no query
    # would ever be sent to.
    try:
        _osm_outs = ("rail.gpkg", "trails.gpkg", "waterways.gpkg", "waterbodies.gpkg",
                     "roads.gpkg")
        if any(not (cache / n).exists() for n in _osm_outs):
            import osmnx as _ox
            _ox.settings.overpass_url = _pick_overpass()
        else:
            print("[acquire] every OSM layer cached — skipping the mirror probe")
    except Exception:
        pass

    steps = [
        ("zones", zones.fetch),
        ("tenure", tenure.fetch),
        ("baux", baux.fetch),          # leased shelters → hunter PRESSURE, never a gate
        ("dem", dem.fetch),
        ("ecoforestiere", ecoforestiere.fetch),
        ("fire", fire.fetch),          # burn history → disturbance-age browse curve
        ("hydro", hydro.fetch),
        ("roads", roads.fetch),
        ("grhq", grhq.fetch),          # GRHQ beaver ponds (rut hub) + wetlands (barriers)
        ("sentinel", sentinel.fetch),
    ]
    # Hard wall-clock timeout per source: a stalled download (e.g. a slow Overpass
    # mirror that accepts the connection then hangs, defeating the request timeout)
    # must NOT freeze the whole job. Each source runs in its own worker; if it blows
    # the budget we abandon it and press on with a degraded-but-complete result.
    import time
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
        # Écoforestière is a heavy full-stand vector pull (the richest habitat signal), so
        # it gets a longer leash than the other sources — the user chose full stands over
        # speed. Its own wall-clock budget (ECOFOR_BUDGET_S) still bounds it.
        this_timeout = max(src_timeout, 900) if name == "ecoforestiere" else src_timeout
        _t0 = time.time()
        try:
            pool.submit(fn, ctx).result(timeout=this_timeout)
            # Report the seconds. Without this, "everything says ok" hides which source
            # is still going to the network on a warm cache — which is exactly the
            # question the geography cache (#79) exists to answer.
            status[name] = f"ok ({time.time() - _t0:.0f}s)"
        except _FTimeout:
            status[name] = "timeout"       # stalled source can no longer hang the job
        except NotImplementedError:
            status[name] = "todo"
        except Exception as exc:  # noqa: BLE001 — surface, don't abort the batch
            status[name] = f"error: {exc}"
        finally:
            pool.shutdown(wait=False)       # abandon a stuck worker thread; move on

    # Contribute whatever this run fetched back to the shared store, so the NEXT job
    # over this box gets it free. Publish only layers that landed — a source that timed
    # out must not cache its absence as if it were a result.
    try:
        put = geocache.publish(ctx, cache)
        geocache.touch(ctx)
        geocache.prune()
        if put:
            print(f"[acquire] geocache published {len(put)} layers to {geocache.key(ctx)}")
    except Exception as e:  # noqa: BLE001
        print(f"[acquire] geocache publish skipped: {e}")
    status["_geocache"] = f"reused {len(reused)}"
    return status


def cached(ctx: Context, filename: str):
    """Path helper: cache/<aoi>/<filename>."""
    return cache_dir(ctx.aoi.name) / filename
