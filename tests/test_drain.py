"""Deploy drain gate.

An analysis is a daemon thread inside uvicorn with state only in memory (#17), so
restarting the container throws away every in-flight run. Until that is fixed
structurally, the deploy must be able to (a) see that runs are in flight and (b) stop
new ones starting so the wait converges. Both are tested here because both are load-
bearing for not destroying someone's evening.
"""
import pytest

pytest.importorskip("fastapi")

from moose_scout import api


@pytest.fixture(autouse=True)
def _clean():
    api.JOBS.clear()
    api.DRAINING = False
    yield
    api.JOBS.clear()
    api.DRAINING = False


def test_active_jobs_counts_only_runs_that_would_die():
    api.JOBS.update({
        "a": {"status": "running"},
        "b": {"status": "done"},
        "c": {"status": "error"},
        "d": {"status": "cancelled"},
        "e": {"status": "running"},
    })
    assert api._active_jobs() == 2, "finished jobs are not at risk; running ones are"


def test_health_reports_what_the_deploy_needs():
    api.JOBS["x"] = {"status": "running"}
    h = api.health()
    assert h["active_jobs"] == 1
    assert h["draining"] is False
    assert "engine_revision" in h


def test_drain_blocks_new_runs(monkeypatch):
    """Without this the wait never converges: you drain while the app starts more."""
    # Auth is checked BEFORE drain, which is the right order — an anonymous caller
    # should be told to sign in, not told about our deploy state. So authenticate first.
    monkeypatch.setattr(api, "REQUIRE_ACCOUNT", False)
    api.DRAINING = True
    with pytest.raises(api.HTTPException) as e:
        api.scout(_req(), x_api_key=api.API_KEY, authorization=None)
    assert e.value.status_code == 503
    assert e.value.detail == "engine-updating"


def test_auth_is_checked_before_drain(monkeypatch):
    """A signed-out caller gets 'sign in', not our maintenance state."""
    monkeypatch.setattr(api, "REQUIRE_ACCOUNT", True)
    api.DRAINING = True
    with pytest.raises(api.HTTPException) as e:
        api.scout(_req(), x_api_key=api.API_KEY, authorization=None)
    assert e.value.status_code == 401


def test_drain_is_reversible_and_reports_state():
    assert api.drain(on=True, x_api_key=api.API_KEY)["draining"] is True
    assert api.drain(on=False, x_api_key=api.API_KEY)["draining"] is False


def test_a_fresh_process_accepts_work():
    """The flag is process-local ON PURPOSE — a new container must come up taking work,
    or a deploy would leave the engine permanently drained."""
    assert api.DRAINING is False


def _req():
    return api.ScoutReq(lat=48.0, lon=-78.0)
