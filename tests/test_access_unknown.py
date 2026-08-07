"""Not knowing is not the same as knowing it is impossible (T0.5).

Surfaced by T0.4 the moment the test contamination stopped masking it: on the fire_lake
cache, synth logged `capability gate: 37 of 37 focus areas excluded; 0 viable areas
promoted to ranks 1..0`. No areas, no routes, nothing to hunt.

THE CAUSE. `roads.tif` is missing from that cache — acquire never landed a road network —
so `access.py` fills `dist_road` with its 1e6 placeholder and raises `access_unknown.flag`.
The gate then read `dr >= 5e5` and told the hunter, of every single area:

    "No boat — this ground is cut off from every road by water. A canoe or boat
     would open it."

That is a confident, specific, checkable claim, and it was built on having no data at
all. Two very different conditions had been collapsed into one sentinel range:

  * WATER-LOCKED — roads exist and the cost-distance found no walkable path to any of
    them. A real finding about the ground.
  * NO ROAD DATA — acquire never ran or timed out, so the distance is a placeholder.

access.py had already learned this lesson and says so at length: it refuses to zero the
extraction surface when the network is missing, falls back to a neutral 0.85, and raises
the flag precisely so the rest of the engine can tell the difference. The fix was applied
in one place and not the other, and the gate went on making the mistake it was warned
about — for long enough that the test which should have caught it was itself broken.

Measured after the fix, same cache: 37 areas, 0 excluded, 111 routes.
"""
import pytest

from moose_scout import synth


class _Hunter:
    walk_access_km = 6.0
    walk_hunt_km = 3.0
    hunt_style = "spike"
    watercraft = "none"
    hunt_radius_km = None


FOOT = {"boat": False, "motor": False, "atv": False}
BOAT = {"boat": True, "motor": False, "atv": False}


# ------------------------------------------------------------------ the reported bug


def test_missing_road_data_does_not_become_cut_off_by_water():
    """THE ONE THIS EXISTS FOR. 1e6 is access.py's placeholder for 'we never found out',
    and it must not be reported as a finding about the ground."""
    ok, why = synth._capability_gate(1e6, _Hunter(), FOOT, access_unknown=True)
    assert ok is True, f"excluded on missing data, saying: {why}"
    assert why is None


def test_the_same_distance_IS_a_finding_when_the_roads_were_mapped():
    """Water-locked is a real answer and must survive. The difference between the two is
    the flag, not the number."""
    ok, why = synth._capability_gate(1e6, _Hunter(), FOOT, access_unknown=False)
    assert ok is False
    assert "cut off from every road by water" in why


def test_a_boat_opens_water_locked_ground():
    ok, why = synth._capability_gate(1e6, _Hunter(), BOAT, access_unknown=False)
    assert ok is True and why is None


def test_ordinary_out_of_range_ground_is_still_excluded_when_access_is_known():
    """The gate's real job must not be weakened by any of this."""
    ok, why = synth._capability_gate(40_000, _Hunter(), FOOT, access_unknown=False)
    assert ok is False and "Beyond your range" in why


def test_out_of_range_ground_is_NOT_excluded_when_access_was_never_modelled():
    """With no road network there is no honest distance to be beyond — the number is a
    placeholder, and gating on it is gating on nothing."""
    ok, _why = synth._capability_gate(40_000, _Hunter(), FOOT, access_unknown=True)
    assert ok is True


def test_in_range_ground_passes_either_way():
    for unknown in (True, False):
        ok, why = synth._capability_gate(2_000, _Hunter(), FOOT, access_unknown=unknown)
        assert ok is True and why is None, unknown


# ------------------------------------------------------------- the flag is read at all


def test_synth_reads_the_flag_access_py_writes():
    """The two halves have to agree. access.py raises `access_unknown.flag` for exactly
    this purpose; a gate that never reads it cannot tell the two cases apart."""
    import inspect
    src = inspect.getsource(synth.run)
    assert "access_unknown.flag" in src, "synth no longer reads the flag"
    assert "access_unknown=_access_unknown" in src, "the flag never reaches the gate"


def test_a_missing_flag_is_treated_as_access_known():
    """Absent flag means an older cache, or one where access ran normally. Defaulting to
    'unknown' would disable the gate everywhere, which is the opposite failure."""
    import inspect
    src = inspect.getsource(synth.run)
    assert "_access_unknown = False" in src


def test_a_fixed_camp_still_gates_on_distance_from_camp():
    """The camp branch returns before any of this — road distance is not a capability
    limit for a camp hunt, it is trivia (the reason that branch exists at all)."""
    h = _Hunter(); h.hunt_radius_km = 5.0
    ok, why = synth._capability_gate(1e6, h, FOOT, camp_km=12.0, access_unknown=True)
    assert ok is False and "from camp" in why
