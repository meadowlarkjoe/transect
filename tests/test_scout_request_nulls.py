"""An unset walk distance must not refuse the whole run.

THE BUG THIS EXISTS FOR. The Setup page holds walk_access_km / walk_hunt_km as null
until the hunter types in those two number fields — which nothing forces them to do,
and which the run button does not check for. The client sent the nulls through
faithfully. On the engine side both were declared plain `float` with a default, and a
pydantic default only fills a MISSING key: an explicit null is a validation error.

So POST /scout answered 422. The app's fetch handler had branches for 503 and 401 and
fell through on everything else into `r.json()`, which parsed the 422 body perfectly
happily, found no job_id, threw, and landed in the generic catch — which told the
hunter "the engine isn't answering" while the button went on counting elapsed minutes
for a run that had never started. Two false statements from one unset field.

Two invariants, both cheap:
  * an unset distance takes the default rather than rejecting the request, and
  * a STATED ZERO survives — `v or default` would silently turn "I won't walk that
    leg" into six kilometres, which re-ranks the whole map. Unset and zero are
    different facts.
"""
import pytest

from moose_scout.config import _walk


def test_none_takes_the_default():
    assert _walk(None, 6.0, 0.5, 30.0) == 6.0


def test_a_stated_zero_is_not_an_unset_value():
    """The distinction the `or` idiom erases. Zero clamps to the floor because a walk
    of 0.0 km is out of the model's range — but it must clamp, not fall back to 6."""
    assert _walk(0, 6.0, 0.5, 30.0) == 0.5
    assert _walk(0.0, 3.0, 0.3, 20.0) == 0.3


def test_a_real_value_passes_through():
    assert _walk(4.2, 6.0, 0.5, 30.0) == 4.2


@pytest.mark.parametrize("v,expect", [(999, 30.0), (-5, 0.5)])
def test_out_of_range_clamps_rather_than_raises(v, expect):
    assert _walk(v, 6.0, 0.5, 30.0) == expect


def test_garbage_takes_the_default_instead_of_raising():
    """Never let a malformed field turn into a 500 — the run is refused loudly enough
    by the clamp."""
    assert _walk("", 6.0, 0.5, 30.0) == 6.0
    assert _walk("abc", 6.0, 0.5, 30.0) == 6.0


def test_the_request_model_accepts_explicit_nulls():
    """THE ACTUAL 422. This is the payload the live app sent."""
    api = pytest.importorskip("moose_scout.api")
    r = api.ScoutReq(species="moose", lat=47.8556, lon=-77.7908, radius_km=9,
                     walk_access_km=None, walk_hunt_km=None, hunt_radius_km=5)
    assert r.walk_access_km is None and r.walk_hunt_km is None


def test_the_worker_survives_the_same_payload():
    """The worker reads the SAME request dict the API validated, with .get(k, default)
    — which also only covers a missing key. It needs the same coalescing, and a
    near-miss here means the API accepts a run the worker then dies on."""
    from moose_scout import worker
    src = (worker.__file__ or "")
    assert src, "worker module has no file"
    text = open(src).read()
    assert 'float(req.get("walk_access_km"' not in text, \
        "worker is back to float()-ing a value that can be null"
    assert "_walk(req.get(\"walk_access_km\")" in text
    assert "_walk(req.get(\"walk_hunt_km\")" in text
