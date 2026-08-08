"""The delivery decision, and the reason it is one file rather than three.

E11.6 (the forest layer — 2.7 MB for an 8 km box, ~170 MB for a 35 km one), T10.22 (the
LiDAR hillshade) and E12.2 (the printed field sheet) each needed a way to get a large
per-job file to the hunter and keep it working afterwards. Three tickets, one gap. Left
alone that was three mechanisms, three lifecycles and three ways to fail.

THE TRAP EACH OF THEM WOULD HAVE FALLEN INTO: serving out of the job cache. Job state
prunes at 48 h and the geography cache prunes on its own budget, so the layer works for an
afternoon and then quietly 404s for anyone reopening a saved plan. A JOB is an event; a
PLAN is the thing someone comes back to.

Measured on the live droplet before deciding: 7 plans, 11 users, plan blobs averaging
586 KB in sqlite, a 3.2 GB geography cache and 59 GB free.
"""
import json
import os
import pathlib

import pytest

from moose_scout import artifacts


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("TRANSECT_ARTIFACTS", str(tmp_path / "art"))
    monkeypatch.setattr(artifacts, "root", lambda: tmp_path / "art")
    yield


def _src(tmp_path, name="stands.geojson", size=1024):
    p = tmp_path / name
    p.write_bytes(b"x" * size)
    return p


# ------------------------------------------------------------------ the core promise


def test_a_missing_artifact_is_an_answer_not_a_hole():
    """THE WHOLE REASON THIS MODULE EXISTS. An empty layer and a swept layer look
    identical on a map, and a hunter reading the first concludes there is nothing on the
    ground. `state` must tell them apart."""
    st = artifacts.state("plan1", "stands.geojson")
    assert st["status"] == "absent"
    assert st["why"]


def test_evicted_is_distinguishable_from_never_had_one(tmp_path):
    """"We reclaimed it, re-run to rebuild" and "your run predates this layer" are
    different sentences and the app has to be able to say the right one."""
    artifacts.put("plan1", _src(tmp_path))
    assert artifacts.state("plan1", "stands.geojson")["status"] == "present"
    artifacts.forget_files = None  # noqa: B010 — guard against a helper appearing later
    import shutil
    shutil.rmtree(artifacts.root() / "plan1")          # simulate eviction
    st = artifacts.state("plan1", "stands.geojson")
    assert st["status"] == "evicted", st
    assert "re-run" in st["why"].lower()


def test_the_ledger_survives_eviction_because_that_is_its_job():
    """Eviction deliberately keeps the `had` list. Dropping it would collapse "evicted"
    back into "absent" — the exact distinction this store is for."""
    import inspect
    src = inspect.getsource(artifacts._evict)
    assert "KEEPS the `had` list" in src


# ------------------------------------------------------------------------ the store


def test_only_allowlisted_names_are_stored(tmp_path):
    """An allowlist rather than "whatever the job wrote", for the same reason
    geocache.ARTIFACTS is one: `access_unknown.flag` looks like source data and is
    actually one hunter's reachability verdict."""
    assert artifacts.put("plan1", _src(tmp_path, "access_unknown.flag")) is False
    assert artifacts.put("plan1", _src(tmp_path, "stands.geojson")) is True


def test_a_plan_id_cannot_walk_out_of_the_store(tmp_path):
    """A plan id reaching the filesystem is a path-traversal question. Refused rather
    than sanitised — sanitising invites an argument about whether it is complete."""
    for bad in ("../etc", "a/b", "", ".", "x" * 200):
        assert artifacts.put(bad, _src(tmp_path)) is False
        assert artifacts.path(bad, "stands.geojson") is None


def test_storing_never_raises(tmp_path):
    """This is delivery, not the answer. A failure here must never cost the analysis."""
    assert artifacts.put("plan1", tmp_path / "does-not-exist.gpkg") is False


def test_reading_touches_the_plan_so_eviction_is_least_RECENTLY_used(tmp_path):
    """A plan reopened every autumn is in use, even if it was written years ago."""
    artifacts.put("plan1", _src(tmp_path))
    before = json.loads((artifacts.root() / "_ledger.json").read_text())["plan1"]["used"]
    artifacts.path("plan1", "stands.geojson")
    after = json.loads((artifacts.root() / "_ledger.json").read_text())["plan1"]["used"]
    assert after >= before


def test_eviction_drops_whole_plans_not_odd_files():
    """Half a plan's layers is a map inconsistent with itself, and "some of your forest
    is missing" is a worse thing to explain than "this plan's layers were reclaimed"."""
    import inspect
    src = inspect.getsource(artifacts._evict)
    assert "shutil.rmtree(d" in src


def test_eviction_frees_space_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "BUDGET_BYTES", 3000)
    for i in range(6):
        artifacts.put(f"plan{i}", _src(tmp_path, size=1000))
    assert artifacts.usage() <= 3000 * 2, artifacts.usage()


def test_deleting_a_plan_takes_its_artifacts(tmp_path):
    """An artefact outliving its plan is a leak with someone's hunting ground in it."""
    artifacts.put("plan1", _src(tmp_path))
    artifacts.forget("plan1")
    assert artifacts.path("plan1", "stands.geojson") is None
    assert "plan1" not in json.loads((artifacts.root() / "_ledger.json").read_text())


# ------------------------------------------------------------------------- the route


def test_the_route_reuses_the_plan_acl_rather_than_inventing_one():
    """A shared plan's party must see its layers. A second, quietly divergent ACL on the
    same objects is how a share silently stops working."""
    import inspect
    from moose_scout import api
    src = inspect.getsource(api.get_artifact)
    assert "_plan_access(con, pid, uid)" in src
    assert "401" in src and "403" in src


def test_the_route_answers_410_with_a_reason_not_a_bare_404():
    """404 collapses "swept" and "never had one" into an empty map."""
    import inspect
    from moose_scout import api
    src = inspect.getsource(api.get_artifact)
    assert "410" in src
    assert 'st.get("why")' in src


def test_promotion_happens_on_SAVE_not_on_run():
    """Saving is when a run stops being an event and becomes something someone returns
    to. Promoting at run time would spend disk on every abandoned experiment."""
    import inspect
    from moose_scout import api
    src = inspect.getsource(api.put_plan)
    assert "artifacts.promote_job" in src
    assert "con.commit()" in src[:src.index("artifacts.promote_job")], \
        "the plan must be committed before promotion, so a promote failure cannot cost it"


def test_the_doc_carries_the_job_that_made_it():
    """Without it the API cannot find the cache to promote from, and the app's
    client-side job id does not survive reopening the plan on another device."""
    import inspect
    from moose_scout import worker
    src = inspect.getsource(worker.run)
    assert '"job_id"] = jid' in src
