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


def test_a_live_worker_still_reads_as_running():
    jobstore.create("j3", {}, uid=None)
    jobstore.update("j3", pid=os.getpid())
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


def test_active_ids_counts_only_live_runs():
    jobstore.create("a", {}, uid=None); jobstore.update("a", pid=os.getpid())
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


def test_prune_keeps_running_jobs_and_drops_old_finished_ones():
    jobstore.create("old", {}, uid=None)
    jobstore.update("old", status="done", started=time.time() - 90 * 3600)
    jobstore.create("live", {}, uid=None)
    jobstore.update("live", pid=os.getpid(), started=time.time() - 90 * 3600)
    assert jobstore.prune(keep_hours=48) == 1
    assert jobstore.read("old") is None
    assert jobstore.read("live") is not None
