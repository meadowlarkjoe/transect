"""The legal gate is the load-bearing filter — lock its behaviour.

Uses an isolated temp cache so results don't depend on whatever has been
acquired locally.
"""
import json
import os
import tempfile

os.environ.setdefault("MOOSE_SCOUT_CONFIG", "config")
# Hermetic cache: never see a real acquired tenure file.
_TMP = tempfile.mkdtemp(prefix="moose-scout-test-")
os.environ["MOOSE_SCOUT_CACHE"] = _TMP

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
