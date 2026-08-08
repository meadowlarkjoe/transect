"""Geography-keyed acquire cache (#79).

Every run used to start from an empty `cache/job_<uuid>/` and re-download the lot:
DEM, Sentinel-2, écoforestière stands, AQréseau+ roads, GRHQ hydrography, NBAC burns.
That is the slow half of a run — minutes of network for bytes we already had on disk
from the last job over the same ground. It also meant the two things a hunter most
wants to change cheaply, **resolution** and **hunt dates**, both cost a full re-fetch,
and it made re-running an area to check a model change an expensive act rather than a
routine one.

Acquired layers depend on the GEOGRAPHY and the GRID, and nothing else. Not the
species, not the dates, not the hunter's kit, not the party size — those shape what we
COMPUTE from the layers, never the layers themselves. So the key is exactly:

    centre (4 dp) · radius · working CRS · raster resolution

and any two jobs that agree on those five numbers can share every byte of stage 1.

Sharing is by HARDLINK, so a reused layer costs one inode and no copy, and the store
is kept read-only so nothing can scribble through a link into another job's cache.
`rasterio_utils.write` replaces atomically, which is what makes that safe: a stage
that legitimately rewrites a layer gets a fresh inode instead of editing the shared
one. Only files stage 1 owns are shared — the ARTIFACTS list below is deliberately
explicit, because sharing a DERIVED layer would silently serve one job's model output
to another.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

# Files stage 1 (acquire) owns. Anything not named here is derived, per-job, and is
# never shared — an allowlist rather than a denylist, because the cost of wrongly
# sharing a computed surface is a plan that silently belongs to somebody else's setup.
# Every entry was checked against the module that actually writes it — the sole writer
# of each must live under acquire/. `access_unknown.flag` looked like it belonged here
# and does NOT: access.py writes it, and it encodes one hunter's reachability verdict.
# Sharing it would have handed that verdict to the next person over the same ground.
ARTIFACTS = (
    "dem.tif", "dem_fine.tif", "dem_source.json",               # dem.py (T9.10: dem.tif
    #   without its sidecar is a pre-LiDAR file — dem.fetch re-fetches rather than
    #   serving a 30 m surface from an old slot with nothing saying so)
    "landcover.tif", "water.tif", "wetland.tif",                # hydro.py
    # native 10 m class fractions (#77/#78) — same grid, measured not sampled
    "lcfrac_tree.tif", "lcfrac_shrub.tif", "lcfrac_grass.tif", "lcfrac_crop.tif",
    "lcfrac_bare.tif", "lcfrac_water.tif", "lcfrac_wetland.tif", "lcfrac_moss.tif",
    "ndvi.tif", "ndvi.json",                                    # sentinel.py (T10.16:
    #   the sidecar carries the imagery EPOCH. Without it the cache — keyed on geometry
    #   alone — would serve one season's greenness forever, which is how the window came
    #   to be two years stale in the first place.)
    "burn_year.tif",                                            # fire.py
    "cut_year.tif", "stand_closure.tif", "stand_type.tif",      # ecoforestiere.py
    "stand_height.tif", "stand_age.tif", "stand_slope.tif",     #   ↳ E11.2: the survey
    "stand_ess_browse.tif", "stands.geojson", "stands.json",                      #     attributes + polygons
    "ecoforestiere_absent.flag",                                #   ↳ its coverage flag
    "roads.tif", "roads.gpkg", "trails.gpkg", "rail.gpkg",      # roads.py
    "waterbodies.gpkg", "waterways.gpkg",                       #   ↳ OSM hydrography
    "aqreseau.gpkg", "aq_bridges.gpkg",                         # aqreseau.py
    "aq_trails.gpkg", "aq_rail.gpkg",
    "beaver_pond.tif", "wetland_grhq.tif",                      # grhq.py
    "tenure.geojson",                                           # tenure.py
    "baux.geojson", "baux.json",                                # baux.py
    "zones_chasse.geojson",                                     # zones.py
)


def enabled() -> bool:
    """Off switch, for when you deliberately want a cold fetch (a source changed
    upstream, or you are debugging an acquire module)."""
    return os.environ.get("GEOCACHE", "1") not in ("0", "off", "false")


def store_root() -> Path:
    root = Path(os.environ.get("MOOSE_SCOUT_CACHE", "cache")) / "_geo"
    root.mkdir(parents=True, exist_ok=True)
    return root


def key(ctx) -> str:
    """What stage 1 produces is decided by the ANALYSIS BOX, so that is what this keys on.

    It used to be centre + `bbox_halfwidth_km`, which describes the box only in radius
    mode. A drawn AOI (T10.8) takes its extent from its padded ring and can carry any
    stored radius at all, so two different parcels could key the same and the same parcel
    could key differently after a slider nudge. `bbox_wgs84()` is the single source of
    truth for the extent in both modes, and this reads it.

    Rounded so a box nudged by centimetres still hits — but NOT loosely, however tempting
    "a redrawn parcel should still hit a warm cache" sounds. `restore` hardlinks the
    cached rasters in with no shape check, so a key that matched a box we did not analyse
    would silently hand the run a misaligned grid. 4 dp is ~11 m, well under any
    resolution we analyse at; a parcel redrawn by hand further out than that pays for a
    re-fetch, and that is the correct trade.
    """
    box = tuple(round(float(v), 4) for v in ctx.aoi.bbox_wgs84())
    res = round(float(ctx.model.raster_resolution_m), 2)
    crs = str(ctx.model.working_crs)
    raw = "|".join(str(v) for v in box) + f"|{crs}|{res}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def slot(ctx) -> Path:
    return store_root() / key(ctx)


def _link(src: Path, dst: Path) -> bool:
    """Hardlink src->dst, falling back to a copy across filesystems. Never raises:
    a cache is an optimisation and must not be able to fail a run."""
    import shutil

    try:
        if dst.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.link(src, dst)
        return True
    except OSError:
        try:
            shutil.copy2(src, dst)
            return True
        except Exception:
            return False
    except Exception:
        return False


def restore(ctx, cache: Path) -> list[str]:
    """Link previously acquired layers for this geography into the job's cache dir.
    Stage 1 skips any layer already present, so this alone is what turns a re-fetch
    into a no-op. Returns the names restored."""
    if not enabled():
        return []
    src = slot(ctx)
    if not src.is_dir():
        return []
    got = []
    for name in ARTIFACTS:
        p = src / name
        if p.is_file() and _link(p, cache / name):
            got.append(name)
    return got


def publish(ctx, cache: Path) -> list[str]:
    """Contribute this job's freshly acquired layers to the shared store, read-only.

    Only ever ADDS: a layer already in the store is left alone, so the store is
    append-only per key and two concurrent jobs cannot fight over it."""
    if not enabled():
        return []
    dst = slot(ctx)
    try:
        dst.mkdir(parents=True, exist_ok=True)
    except Exception:
        return []
    put = []
    for name in ARTIFACTS:
        p = cache / name
        if not p.is_file():
            continue
        t = dst / name
        if t.exists():
            continue
        if _link(p, t):
            try:
                os.chmod(t, 0o444)   # read-only: nothing writes THROUGH a shared link
            except OSError:
                pass
            put.append(name)
    return put


def prune(keep: int = 12) -> int:
    """Bound disk: keep the `keep` most recently used geography slots, drop the rest.
    Disk on the box is finite and a slot is tens to hundreds of MB."""
    import shutil

    root = store_root()
    try:
        slots = sorted((p for p in root.iterdir() if p.is_dir()),
                       key=lambda p: p.stat().st_mtime, reverse=True)
    except Exception:
        return 0
    dropped = 0
    for p in slots[keep:]:
        try:
            # chmod back so rmtree can remove the read-only files it finds
            for f in p.rglob("*"):
                try:
                    os.chmod(f, 0o644)
                except OSError:
                    pass
            shutil.rmtree(p, ignore_errors=True)
            dropped += 1
        except Exception:
            pass
    return dropped


def touch(ctx) -> None:
    """Mark this slot as recently used, so prune() keeps the ones people actually
    re-run rather than merely the ones most recently created."""
    try:
        os.utime(slot(ctx), None)
    except OSError:
        pass
