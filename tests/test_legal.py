"""The legal gate is the load-bearing filter — lock its behaviour.

Uses an isolated temp cache so results don't depend on whatever has been acquired
locally.

THAT ISOLATION USED TO LEAK, AND IT BROKE OTHER TESTS (T0.4). The env var was set with a
plain assignment at MODULE IMPORT — so from the moment pytest merely COLLECTED this file,
every later test in the session resolved its cache to this temp directory. `test_synth_
smoke` then looked for fire_lake's rasters somewhere they had never been written and died
with `RasterioIOError: .../fire_lake/huntability.tif` in about five seconds, instead of
running the real ~95 s pipeline it is there to exercise. Alone it passed; in the suite it
failed whatever the engine code did — so it could not report a genuine synth regression,
which is worse than not having the test.

An autouse fixture undoes itself. Import time does not.
"""
import json
import os
import tempfile

import pytest

os.environ.setdefault("MOOSE_SCOUT_CONFIG", "config")
_TMP = tempfile.mkdtemp(prefix="moose-scout-test-")


@pytest.fixture(autouse=True)
def _hermetic_cache(monkeypatch):
    """Point the cache at an empty directory FOR THESE TESTS ONLY."""
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", _TMP)


from moose_scout.config import Context, cache_dir
from moose_scout.legal import ACCESS_RULES, PARALLEL_52, Tenure, assess


def test_fire_lake_is_north_of_52():
    ctx = Context.for_aoi("fire_lake")
    assert ctx.aoi.center.lat >= PARALLEL_52
    assert assess(ctx).north_of_52 is True


def test_unverified_when_no_tenure_cached():
    # No tenure file -> UNVERIFIED, never a confident "no access".
    ctx = Context.for_aoi("fire_lake")
    a = assess(ctx)
    assert a.unverified is True
    assert a.diy_possible is False


def test_empty_tenure_clip_means_crown_and_huntable():
    # An acquired-but-empty clip = all crown land = huntable for a resident.
    ctx = Context.for_aoi("fire_lake")
    (cache_dir("fire_lake") / "tenure.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": []})
    )
    a = assess(ctx)
    assert a.unverified is False
    assert a.diy_possible is True
    assert Tenure.CROWN in a.huntable_tenures


def test_resident_may_hunt_crown_but_nonresident_needs_outfitter():
    assert ACCESS_RULES["quebec_resident"][Tenure.CROWN] == "yes"
    assert ACCESS_RULES["non_resident_canada"][Tenure.CROWN] == "outfitter"
    assert ACCESS_RULES["quebec_resident"][Tenure.POURVOIRIE_EXCLUSIVE] == "no"


def test_target_dates_land_in_rut_window():
    ctx = Context.for_aoi("fire_lake")
    peak = ctx.species.rut["peak_rut"]
    assert peak[0] <= "09-25" <= peak[1]
