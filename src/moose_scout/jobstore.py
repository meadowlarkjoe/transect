"""Job state on disk (#17).

Until now a run's state lived only in an in-memory dict inside the API process, which
meant the state and the work died together. Restart the container — deploy, crash, OOM
— and every in-flight analysis vanished with no record that it had ever existed. The
hunter saw a spinner stop, and there was nothing to reconnect to.

Putting the state on disk decouples the two: the API can restart, crash, or be replaced
mid-deploy and still answer "what happened to my run?", because the answer is a file the
worker keeps writing. It is also what lets a job outlive the request that started it
without being invisible to whatever comes next.

Layout, one directory per job under the cache root:

    _jobs/<jid>/req.json     the request, so a worker can rebuild the Context alone
    _jobs/<jid>/state.json   status · stage · progress · pid · timestamps
    _jobs/<jid>/cancel       a file whose EXISTENCE means stop

Cancellation is a file rather than a flag in state.json on purpose: the worker owns
state.json and rewrites it whole after every stage, so a cancel written into it would be
clobbered by the next stage's update. A separate file has exactly one writer (the API)
and one reader (the worker), and cannot be lost in a race.

Writes are atomic (temp + os.replace) so a reader never sees half a JSON document — the
same discipline as the rasters, for the same reason: a torn file that parses is worse
than one that does not.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

TERMINAL = ("done", "error", "cancelled", "interrupted")


def root() -> Path:
    d = Path(os.environ.get("MOOSE_SCOUT_CACHE", "cache")) / "_jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def dir_for(jid: str) -> Path:
    d = root() / jid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_atomic(path: Path, obj) -> None:
    tmp = path.with_name(path.name + f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)


def create(jid: str, req: dict, uid) -> dict:
    d = dir_for(jid)
    _write_atomic(d / "req.json", req)
    st = {"status": "running", "stage": "queued", "progress": 0.0, "uid": uid,
          "started": time.time(), "seen": time.time(), "pid": None}
    _write_atomic(d / "state.json", st)
    return st


def read_req(jid: str) -> dict | None:
    p = root() / jid / "req.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def read(jid: str) -> dict | None:
    p = root() / jid / "state.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def update(jid: str, **kw) -> dict | None:
    """Merge into the stored state. Read-modify-write: the worker is the only writer of
    the fields it owns, and the API only ever touches `seen`, so the interleaving that
    a lock would protect against does not arise."""
    st = read(jid)
    if st is None:
        return None
    st.update(kw)
    try:
        _write_atomic(root() / jid / "state.json", st)
    except Exception:
        return st
    return st


def set_cancel(jid: str) -> None:
    try:
        (dir_for(jid) / "cancel").write_text("1")
    except OSError:
        pass


def cancelled(jid: str) -> bool:
    return (root() / jid / "cancel").exists()


def alive(pid) -> bool:
    """Is that worker still running? signal 0 asks the kernel without touching it."""
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def effective_status(st: dict) -> str:
    """What the status ACTUALLY is, not just what was last written.

    A worker killed outright — OOM, SIGKILL, the container going away — never gets to
    write a terminal status, so the file still says "running" forever. Checking the pid
    turns that into `interrupted`, which is a thing the client can act on ("your run was
    cut short, resume it?") rather than a spinner that never stops.
    """
    s = st.get("status")
    if s in TERMINAL:
        return s
    if st.get("pid") and not alive(st.get("pid")):
        return "interrupted"
    return s


def all_states():
    for d in sorted(root().glob("*")):
        if not d.is_dir():
            continue
        st = read(d.name)
        if st is not None:
            yield d.name, st


def active_ids():
    """Jobs a deploy would destroy: still running, with a live worker behind them."""
    return [jid for jid, st in all_states() if effective_status(st) == "running"]


def prune(keep_hours: float = 48.0) -> int:
    """Drop terminal job state older than `keep_hours`. The cache dirs those jobs used
    are pruned separately by their own budget; this is just the small state."""
    import shutil
    cutoff = time.time() - keep_hours * 3600
    n = 0
    for jid, st in list(all_states()):
        if effective_status(st) in TERMINAL and (st.get("started") or 0) < cutoff:
            shutil.rmtree(root() / jid, ignore_errors=True)
            n += 1
    return n
