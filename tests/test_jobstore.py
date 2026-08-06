"""Job state on disk, and what it buys (#17).

The property that matters: a run's state must survive the process that started it. Every
test here is a way that used to be false.
"""
import json
import os
import subprocess
import sys
import time

import pytest

from moose_scout import jobstore


@pytest.fixture(autouse=True)
def _cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    yield


def test_state_survives_the_process_that_wrote_it():
    """THE POINT. State used to live in a dict inside uvicorn, so a restart erased every
    running job. Read it back from a SEPARATE interpreter to prove it is really on disk
    and not just in this one's memory."""
    jobstore.create("j1", {"lat": 48.0, "lon": -78.0}, uid=7)
    jobstore.update("j1", stage="habitat", progress=0.4)

    out = subprocess.run(
        [sys.executable, "-c",
         "import os,sys;sys.path.insert(0,'src');from moose_scout import jobstore;"
         "import json;print(json.dumps(jobstore.read('j1')))"],
        capture_output=True, text=True, env={**os.environ},
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert out.returncode == 0, out.stderr
    st = json.loads(out.stdout)
    assert st["stage"] == "habitat" and st["progress"] == 0.4 and st["uid"] == 7


def test_a_killed_worker_reads_as_interrupted_not_running():
    """A worker killed outright never writes a terminal status, so the file still says
    'running'. Without the pid check that is a spinner that never stops."""
    jobstore.create("j2", {}, uid=None)
    jobstore.update("j2", pid=999_999_999)          # a pid that cannot be alive
    st = jobstore.read("j2")
    assert st["status"] == "running"
    assert jobstore.effective_status(st) == "interrupted"


def _as_worker(monkeypatch, jid):
    """Make the pid look like the REAL worker for `jid`.

    alive() no longer accepts "some process holds that number" as proof — a recycled pid
    used to keep a dead job running for ever. So a test that means "a live worker" has to
    say so, rather than borrowing its own pid and relying on a weaker check.
    """
    monkeypatch.setattr(jobstore, "_cmdline",
                        lambda pid: f"python\x00-m\x00moose_scout.worker\x00{jid}\x00")


def test_a_live_worker_still_reads_as_running(monkeypatch):
    jobstore.create("j3", {}, uid=None)
    jobstore.update("j3", pid=os.getpid())
    _as_worker(monkeypatch, "j3")
    assert jobstore.effective_status(jobstore.read("j3")) == "running"


def test_terminal_status_is_never_second_guessed():
    """A finished job stays finished even though its worker is long gone."""
    jobstore.create("j4", {}, uid=None)
    jobstore.update("j4", status="done", pid=999_999_999)
    assert jobstore.effective_status(jobstore.read("j4")) == "done"


def test_cancel_is_a_separate_file_so_a_stage_update_cannot_clobber_it():
    """The worker rewrites state.json whole after every stage. A cancel stored in there
    would be erased by the next stage; a file has one writer and one reader."""
    jobstore.create("j5", {}, uid=None)
    jobstore.set_cancel("j5")
    jobstore.update("j5", stage="access", progress=0.7)   # worker's next write
    assert jobstore.cancelled("j5") is True


def test_active_ids_counts_only_live_runs(monkeypatch):
    jobstore.create("a", {}, uid=None); jobstore.update("a", pid=os.getpid())
    _as_worker(monkeypatch, "a")
    jobstore.create("b", {}, uid=None); jobstore.update("b", status="done")
    jobstore.create("c", {}, uid=None); jobstore.update("c", pid=999_999_999)
    assert jobstore.active_ids() == ["a"]


def test_writes_are_atomic_enough_to_never_be_read_half_written():
    """A torn file that parses is worse than one that does not — the reader would act on
    a plausible lie. temp + replace means a reader sees old or new, never partial."""
    jobstore.create("j6", {}, uid=None)
    for i in range(60):
        jobstore.update("j6", progress=i / 60)
        st = jobstore.read("j6")
        assert st is not None and "status" in st


def test_prune_keeps_running_jobs_and_drops_old_finished_ones(monkeypatch):
    jobstore.create("old", {}, uid=None)
    jobstore.update("old", status="done", started=time.time() - 90 * 3600)
    jobstore.create("live", {}, uid=None)
    jobstore.update("live", pid=os.getpid(), started=time.time() - 90 * 3600)
    _as_worker(monkeypatch, "live")   # genuinely running, however old — must survive
    assert jobstore.prune(keep_hours=48) == 1
    assert jobstore.read("old") is None
    assert jobstore.read("live") is not None


def test_a_recycled_pid_cannot_keep_a_dead_job_alive(tmp_path, monkeypatch):
    """THE BUG THIS EXISTS FOR, and it bit twice.

    alive() asked the kernel whether a pid was in use, which is not the question. Pids
    restart from low numbers inside a fresh container, so after a replacement an
    unrelated process — uvicorn itself, a shell — inherits the number a dead worker had.
    The job then reported "running" for ever: it held a deploy DRAIN open indefinitely
    and left the engine answering 503 to every new analysis until somebody edited the
    state file by hand.

    The current process is emphatically not `python -m moose_scout.worker <jid>`, so it
    stands in for the recycled pid.
    """
    import os
    from moose_scout import jobstore
    st = {"status": "running", "pid": os.getpid(), "jid": "deadbeef"}
    # The pid IS live...
    assert jobstore.alive(st["pid"]) is True
    # ...but it is not that worker, and that is what has to decide it.
    if os.path.exists(f"/proc/{os.getpid()}/cmdline"):      # Linux only; the guard is the point
        assert jobstore.alive(st["pid"], "deadbeef") is False
        assert jobstore.effective_status(st) == "interrupted"


def test_a_terminal_status_is_never_second_guessed(tmp_path):
    """A finished run stays finished whatever the process table says — resolving it
    against a pid could only ever turn a good result into a scary one."""
    import os
    from moose_scout import jobstore
    for s in ("done", "error", "cancelled", "interrupted"):
        assert jobstore.effective_status({"status": s, "pid": os.getpid(), "jid": "x"}) == s


def test_liveness_does_not_depend_on_anyone_watching(tmp_path, monkeypatch):
    """`seen` is stamped by the API on every client POLL, so it measures how recently
    somebody LOOKED. Keying liveness on it would declare the run dead for any hunter who
    closed the tab — the exact case #17 exists to survive. This pins that it is not used.
    """
    import inspect
    from moose_scout import jobstore
    src = inspect.getsource(jobstore.effective_status)
    body = src.split('"""')[-1]        # ignore the docstring, which discusses `seen`
    assert "seen" not in body, "effective_status is keying liveness on poll recency"
