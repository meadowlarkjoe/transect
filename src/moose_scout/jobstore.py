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
    # `jid` is stored so a reader holding only the state can verify the pid really is
    # THAT worker (see alive()). Without it the cmdline check has nothing to match on.
    st = {"jid": jid, "status": "running", "stage": "queued", "progress": 0.0, "uid": uid,
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
        st = json.loads(p.read_text())
    except Exception:
        return None
    st.setdefault("jid", jid)      # states written before jid was stored
    return st


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


def _cmdline(pid):
    """The process's command line, or None if we cannot see one.

    Split out so a test can say "pretend this pid IS the worker" without the production
    check being loosened to make itself testable.
    """
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "replace")
    except OSError:
        return None


def alive(pid, jid=None) -> bool:
    """Is THAT worker still running — not merely: is something using that pid?

    signal 0 asks the kernel whether the number is in use, which is a different question.
    Pids restart from low numbers in a fresh container, so after a replacement an
    unrelated process — uvicorn itself, a shell — inherits the number a dead worker had,
    this returns True, and the job stays "running" for ever. Twice that held a deploy
    DRAIN open indefinitely and left the engine answering 503 until it was cleared by
    hand, which is a bad way to find out.

    So when we know which job we are asking about, confirm the process really IS that
    worker by reading its command line. `python -m moose_scout.worker <jid>` is
    unmistakable, and a recycled pid cannot fake it.
    """
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    if jid:
        cmd = _cmdline(pid)
        if cmd is None:
            # No procfs (a Mac dev box). Fall back to the bare pid test rather than
            # declaring a live run dead — a false "interrupted" is worse than a slow one.
            return True
        if "moose_scout.worker" not in cmd or str(jid) not in cmd:
            return False               # the pid was recycled by something else
    return True


def effective_status(st: dict) -> str:
    """What the status ACTUALLY is, not just what was last written.

    A worker killed outright — OOM, SIGKILL, the container going away — never gets to
    write a terminal status, so the file still says "running" forever. Resolving it
    against the process turns that into `interrupted`, which is a thing the client can
    act on ("your run was cut short, resume it?") rather than a spinner that never stops.

    Note what is NOT used here: how recently the state file was touched. `seen` is
    stamped by the API every time a CLIENT POLLS, so it measures how recently somebody
    looked, not whether anything is still happening. Keying liveness on it would declare
    the run dead for any hunter who closed the tab — which is the exact case #17 exists
    to survive.
    """
    s = st.get("status")
    if s in TERMINAL:
        return s
    if st.get("pid") and not alive(st.get("pid"), st.get("jid")):
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
