"""Large per-plan artefacts — the ones too big to live in the plan blob.

THE DECISION THIS FILE IS. Three tickets independently needed the same missing piece and
were each about to invent it: E11.6 (the forest layer, ~2.7 MB for an 8 km box and ~170 MB
for a 35 km one), T10.22 (the LiDAR hillshade) and E12.2 (the printed field sheet). Left
alone that would have been three delivery mechanisms with three lifecycles and three ways
to fail.

WHY NOT THE OBVIOUS OPTIONS.

*In the plan blob.* Plans are a TEXT column in sqlite — measured on the live droplet, 7
plans averaging 586 KB and peaking at 1.5 MB. Base64ing a 170 MB layer into a row that is
read in full on every plan open is not a store, it is a way to make opening a plan slow
for everyone.

*In the job cache.* This is what the three tickets would each have done, and it is the
trap. Job state prunes at 48 h and the geography cache prunes on its own budget, so the
layer works for an afternoon and then quietly 404s for anyone reopening a saved plan —
the exact silent-breakage pattern this codebase keeps getting bitten by. A JOB is an
event; a PLAN is the thing someone comes back to. Artefacts belong to the plan.

*Object storage.* Correct at scale and the wrong dependency at 7 plans and 11 users. The
droplet has 59 GB free against a 3.2 GB cache. When the budget below starts evicting
things people still want, that is the signal to move — and the interface here does not
change when it does.

WHAT MAKES THIS SAFE RATHER THAN JUST SMALL. A budget with LRU eviction, and — the part
that matters — **a missing artefact is an ANSWER, not a hole**. `state()` distinguishes
"never had one" from "had one and it was evicted", so the app can say "this layer was
swept, re-run to restore it" instead of drawing an empty map and letting the hunter
conclude there is nothing there. Every other decision here is reversible; that one is the
reason the file exists.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

# Total disk this store may occupy, and the ceiling for any single plan. Sized against
# the real droplet: 59 GB free, a 3.2 GB geography cache, and a worst-case forest layer
# of ~170 MB for a 35 km box. 20 GB is room for roughly a hundred big plans while leaving
# the cache and the OS the space they already use.
BUDGET_BYTES = int(os.environ.get("TRANSECT_ARTIFACT_BUDGET", str(20 * 1024 ** 3)))
PER_PLAN_BYTES = int(os.environ.get("TRANSECT_ARTIFACT_PER_PLAN", str(400 * 1024 ** 2)))

# Only these may be promoted. An allowlist rather than "whatever the job wrote", for the
# same reason geocache.ARTIFACTS is one: `access_unknown.flag` looks like source data and
# is actually one hunter's reachability verdict. A store that takes anything eventually
# serves something it should not.
PROMOTABLE = {
    "stands.geojson": "The forest survey's stand polygons with their attributes (E11.6).",
    "stands.json": "How many stands that layer holds, and whether it was capped.",
    "hillshade_lidar.png": "AOI hillshade rendered from HRDEM (T10.22).",
    "hillshade_lidar.json": "Its bounds and which DEM produced it.",
}

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def root() -> Path:
    return Path(os.environ.get("TRANSECT_ARTIFACTS", "/app/data/artifacts"))


def _plan_dir(pid: str) -> Path:
    # A plan id reaching the filesystem is a path-traversal question, not a formatting
    # one. Anything that is not a plain id is refused rather than sanitised — sanitising
    # invites an argument about whether the sanitiser is complete.
    if not _SAFE.match(str(pid or "")):
        raise ValueError("bad plan id")
    return root() / str(pid)


def put(pid: str, src: Path, name: str | None = None) -> bool:
    """Promote one file from a job cache into the plan's store. Never raises.

    Returns True if the artefact is now present. A failure here must never cost anyone
    the analysis that produced it — this is delivery, not the answer.
    """
    try:
        name = name or Path(src).name
        if name not in PROMOTABLE or not Path(src).is_file():
            return False
        d = _plan_dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        dst = d / name
        shutil.copy2(src, dst)
        _record(pid, name, dst.stat().st_size)
        _evict()
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[artifacts] {pid}/{name} not stored: {e}")
        return False


def path(pid: str, name: str) -> Path | None:
    """The file, or None. Touches the plan so eviction is genuinely least-RECENTLY-used
    rather than least-recently-written — a plan reopened every autumn is in use."""
    try:
        p = _plan_dir(pid) / name
        if not p.is_file():
            return None
        _touch(pid)
        return p
    except Exception:
        return None


def state(pid: str, name: str) -> dict:
    """Why this artefact is not here — the whole point of the module.

      present  — serve it
      evicted  — it existed and the budget reclaimed it. RE-RUNNABLE, and the app must
                 say so rather than drawing nothing.
      absent   — this plan never had one (an older run, or no coverage). Also not a hole:
                 "your run predates this layer" is a different sentence from "we lost it".
    """
    try:
        p = _plan_dir(pid) / name
        if p.is_file():
            return {"status": "present", "bytes": p.stat().st_size}
        led = _ledger()
        if name in (led.get(pid, {}).get("had") or []):
            return {"status": "evicted",
                    "why": "This layer was reclaimed to make room. Re-run the analysis "
                           "to rebuild it — nothing about your plan was lost."}
        return {"status": "absent",
                "why": "This plan has no such layer. It may predate the layer, or the "
                       "survey may not cover this ground."}
    except Exception:
        return {"status": "absent", "why": "unavailable"}


# ------------------------------------------------------------------ budget + ledger
# The ledger remembers what a plan ONCE had, which is what lets `state` tell "evicted"
# from "never existed". It is small, rewritten whole, and never load-bearing: losing it
# degrades an explanation, not the data.

def _ledger_path() -> Path:
    return root() / "_ledger.json"


def _ledger() -> dict:
    try:
        return json.loads(_ledger_path().read_text())
    except Exception:
        return {}


def _write_ledger(led: dict) -> None:
    try:
        root().mkdir(parents=True, exist_ok=True)
        tmp = _ledger_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(led))
        tmp.replace(_ledger_path())
    except Exception:
        pass


def _record(pid: str, name: str, size: int) -> None:
    led = _ledger()
    e = led.setdefault(str(pid), {"had": [], "used": 0.0})
    if name not in e["had"]:
        e["had"].append(name)
    e["used"] = time.time()
    _write_ledger(led)


def _touch(pid: str) -> None:
    led = _ledger()
    if str(pid) in led:
        led[str(pid)]["used"] = time.time()
        _write_ledger(led)


def usage() -> int:
    try:
        return sum(f.stat().st_size for f in root().rglob("*") if f.is_file())
    except Exception:
        return 0


def _plan_bytes(pid: str) -> int:
    try:
        return sum(f.stat().st_size for f in _plan_dir(pid).glob("*") if f.is_file())
    except Exception:
        return 0


def _evict() -> list:
    """Drop whole plans, least recently used first, until the store is inside budget.

    WHOLE plans rather than individual files on purpose: half a plan's layers is a map
    that is inconsistent with itself, and "some of your forest is missing" is a worse
    thing to explain than "this plan's layers were reclaimed, re-run to rebuild".
    """
    dropped = []
    try:
        if usage() <= BUDGET_BYTES:
            return dropped
        led = _ledger()
        plans = sorted(((led.get(d.name, {}).get("used", 0.0), d)
                        for d in root().iterdir() if d.is_dir()),
                       key=lambda t: t[0])
        for _used, d in plans:
            if usage() <= BUDGET_BYTES:
                break
            shutil.rmtree(d, ignore_errors=True)
            dropped.append(d.name)
        if dropped:
            # The ledger deliberately KEEPS the `had` list for an evicted plan — that is
            # exactly the record `state()` needs to say "evicted" rather than "absent".
            print(f"[artifacts] evicted {len(dropped)} plan(s) to stay inside budget")
    except Exception as e:  # noqa: BLE001
        print(f"[artifacts] eviction skipped: {e}")
    return dropped


def promote_job(pid: str, cache: Path) -> list:
    """Promote everything promotable from a finished job's cache into the plan."""
    got = []
    try:
        if _plan_bytes(pid) > PER_PLAN_BYTES:
            print(f"[artifacts] plan {pid} is over its own budget; not promoting more")
            return got
        for name in PROMOTABLE:
            if put(pid, Path(cache) / name):
                got.append(name)
    except Exception as e:  # noqa: BLE001
        print(f"[artifacts] promote failed for {pid}: {e}")
    return got


def forget(pid: str) -> None:
    """Called when a plan is deleted. An artefact outliving its plan is a leak with
    someone's hunting ground in it."""
    try:
        shutil.rmtree(_plan_dir(pid), ignore_errors=True)
        led = _ledger()
        if str(pid) in led:
            led.pop(str(pid), None)
            _write_ledger(led)
    except Exception:
        pass
