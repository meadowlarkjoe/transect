"""The capability gate, and the camp-hunt bug it had (#72, camp fix).

Reported from a real plan: a camp hunt with a stated 4 km walk FROM CAMP had two focus
areas excluded as "~4.2 km from the nearest road, past the ~4 km you said you'd cover" —
printed under a header reading "CAMP A · PACK-IN ≤ 2.3 KM". The engine knew the areas
were 2.3 km from the tent and excluded them on road distance anyway.

These are unit tests on the gate rather than a whole-AOI run, deliberately: the cached
AOI's areas sit 244 m and 305 m from a road, so no amount of running it reproduces the
geometry that matters. Testing the decision directly is the only honest way to pin it.
"""
import pytest

from moose_scout.synth import _capability_gate

FOOT = {"boat": False, "motor": False, "atv": False}
ATV = {"boat": False, "motor": False, "atv": True}


class _Hunter:
    def __init__(self, **kw):
        self.hunt_style = kw.get("hunt_style", "spike")
        self.walk_access_km = kw.get("walk_access_km", 6.0)
        self.walk_hunt_km = kw.get("walk_hunt_km", 3.0)
        self.hunt_radius_km = kw.get("hunt_radius_km")


def test_camp_hunt_keeps_ground_near_the_tent_and_far_from_a_road():
    """THE REPORTED BUG, with the numbers off the screenshot: 2.3 km from camp, 4.2 km
    from a road, 4 km stated walk. You already drove to camp; the road is trivia.

    walk_access_km=0 matters — that is what makes the OLD road reach exactly 4 km, so
    4.2 km tipped over it. A first version of this test used the default 6 km access leg,
    which made the old reach 10 km and the test passed against the BROKEN code: it proved
    nothing until the config matched the report."""
    h = _Hunter(walk_access_km=0.0, walk_hunt_km=4.0, hunt_radius_km=4.0)  # reach 4 km
    assert _capability_gate(4200, h, FOOT)[0] is False, "precondition: the road gate excluded it"
    ok, why = _capability_gate(4200, h, FOOT, camp_km=2.3)
    assert ok is True, f"excluded ground inside the stated walk: {why}"
    assert why is None


def test_camp_hunt_still_excludes_ground_beyond_the_stated_walk():
    """The gate must still gate — it just has to measure the right distance."""
    h = _Hunter(hunt_radius_km=4.0, walk_hunt_km=4.0)
    ok, why = _capability_gate(200, h, FOOT, camp_km=9.0)
    assert ok is False
    assert "from camp" in why, why
    assert "4 km" in why, why


def test_camp_exclusion_never_blames_the_road():
    h = _Hunter(hunt_radius_km=3.0)
    ok, why = _capability_gate(50_000, h, FOOT, camp_km=12.0)
    assert ok is False
    assert "road" not in why.lower(), f"a camp hunt must not be gated on roads: {why}"


def test_atv_extends_the_camp_reach_too():
    """An ATV multiplies reach from a road; it multiplies reach from camp as well."""
    h = _Hunter(hunt_radius_km=4.0)
    assert _capability_gate(200, h, FOOT, camp_km=9.0)[0] is False
    assert _capability_gate(200, h, ATV, camp_km=9.0)[0] is True   # 4*2.5+5 = 15 km


def test_road_gating_is_unchanged_without_a_camp():
    """Spike and vehicle hunts DO start at a road — that gate must not regress."""
    h = _Hunter(hunt_style="spike", walk_access_km=2.0, walk_hunt_km=2.0)   # reach 4 km
    ok, why = _capability_gate(4200, h, FOOT)
    assert ok is False
    assert "road" in why, why
    assert _capability_gate(3000, h, FOOT)[0] is True


def test_water_locked_ground_still_needs_a_boat():
    """5e5 is the barrier sentinel — no walkable path to a road at all."""
    h = _Hunter()
    ok, why = _capability_gate(5e5, h, FOOT)
    assert ok is False and "boat" in why.lower()
    assert _capability_gate(5e5, h, {"boat": True, "motor": False, "atv": False})[0] is True


def test_no_distance_information_is_not_an_exclusion():
    """Missing data must never masquerade as a capability verdict."""
    assert _capability_gate(None, _Hunter(), FOOT) == (True, None)


@pytest.mark.parametrize("camp_km,expect_ok", [(0.0, True), (3.9, True), (4.1, False)])
def test_the_boundary_is_where_the_hunter_put_it(camp_km, expect_ok):
    h = _Hunter(hunt_radius_km=4.0)
    assert _capability_gate(9999, h, FOOT, camp_km=camp_km)[0] is expect_ok
