"""A camp the hunter placed is THE camp — not a suggestion to compete with.

THE BUG THIS EXISTS FOR, reported off a screenshot: "it is still hallucinating a
'Spike Camp' location right beside the cabin location". Two camp icons, ~630 m apart,
on a hunt where the hunter had pointed at their cabin.

`_group_camps` is an INDEPENDENT camp-finder living in the contract layer. It clusters
the focus-area centroids and sites a camp at the road nearest that centroid, and it
knew nothing about `fixed_camp`. So on a cabin hunt it dutifully invented "Camp A"
beside the real one — after synth had already stopped emitting a base_camp pin for
precisely this reason. The duplicate icon was the visible half. The invisible half was
worse: `packin_km_by_area` was measured FROM the invented site, so every pack-out
distance in the brief belonged to a camp that does not exist.

That made three separate places deriving "where is camp" — synth, routing, and here —
and the bug each time was a derivation that ignored the answer we had been given.
"""
import pytest


def _area(rank, lon, lat):
    return {"properties": {"rank": rank, "centroid": [lon, lat]}}


AREAS = [_area(1, -77.770, 47.860), _area(2, -77.810, 47.845), _area(3, -77.795, 47.870)]
CAMP = (47.85561, -77.79078)          # (lat, lon), as the hunter placed it


def _group(**kw):
    contract = pytest.importorskip("moose_scout.contract")
    return contract._group_camps(AREAS, cache=None, **kw)


def test_a_fixed_camp_produces_exactly_one_camp_at_that_point():
    camps = _group(fixed=CAMP)
    assert len(camps) == 1, "a hunter with one cabin has one camp"
    site = camps[0]["site"]
    assert (round(site["lat"], 5), round(site["lon"], 5)) == (round(CAMP[0], 5), round(CAMP[1], 5)), \
        f"camp was moved to {site} — the hunter told us where it is"


def test_every_area_belongs_to_the_fixed_camp():
    """You hunt all of it from the one cabin; no area may be orphaned to a camp that
    was never created."""
    camps = _group(fixed=CAMP)
    assert camps[0]["member_areas"] == [1, 2, 3]


def test_packin_distances_are_measured_from_the_real_camp():
    """The quiet half of the bug. A wrong camp site silently produces wrong pack-out
    numbers, which is a load a hunter plans around."""
    from moose_scout.contract import _haversine_km
    camps = _group(fixed=CAMP)
    packin = camps[0]["packin_km_by_area"]
    for a in AREAS:
        rank = a["properties"]["rank"]
        lon, lat = a["properties"]["centroid"]
        assert packin[rank] == round(_haversine_km(CAMP, (lat, lon)), 1)


def test_it_is_flagged_as_the_hunters_own():
    """The client needs to tell "your camp" from "a camp we picked" — to label it
    honestly and to avoid drawing a recommendation on top of the hunter's own marker."""
    c = _group(fixed=CAMP)[0]
    assert c.get("fixed") is True
    assert c["access_type"] == "yours"


def test_without_a_fixed_camp_the_finder_still_runs():
    """The auto path must not regress — most hunts have no fixed camp and DO want a
    camp proposed. cache=None makes _road_coords come back empty, so the camp falls
    back to the cluster centroid; that is fine, the point is that it still produces one."""
    camps = _group()
    assert len(camps) >= 1
    assert camps[0].get("fixed") is not True
    assert sorted(sum((c["member_areas"] for c in camps), [])) == [1, 2, 3]
