"""A portage you can carry a canoe over is not a route you can pack a bull out on (T10.21).

Joe, setting the canoe rule for T10.20: "canoe... can be portaged betwene locations (but
routes like that might not be reasonable for extraction)."

T10.20 let a canoe reach water over a carry, which is right for getting IN. Coming out is
a different problem and the model reported ONE `walk_km` for both directions. Worse, the
pack-out estimate ignored the route entirely and used straight-line distance to the
nearest road — a number that charges you for ground a boat or a quad carries the load
over for free, and that cannot see a portage at all.
"""
import inspect

import pytest

from moose_scout import synth


def test_a_foot_leg_beside_a_boat_leg_is_a_portage():
    src = inspect.getsource(synth._add_routes)
    assert '_boat_at' in src and '"portage"' in src, \
        "portage legs are no longer distinguished from ordinary walking"


def test_a_portage_costs_the_boat_as_well_as_the_loads():
    """In with a canoe, out with the canoe AND the meat. That is one more trip over the
    same yards than an ordinary carry, every time."""
    src = inspect.getsource(synth._add_routes)
    assert "(LOADS + 1)" in src, "a portage is being costed as an ordinary walk"


def test_the_carry_distance_counts_only_what_you_carry():
    """Water and ridden legs move the load in one trip; foot legs you walk repeatedly.
    Measured on a real ATV run: 1.62 km of bushwhack became 11.3 km under load, while
    7.18 km of quad cost nothing."""
    src = inspect.getsource(synth._add_routes)
    seg = src[src.index("carry = 0.0"):src.index('props["carry_km"]')]
    assert "startswith(\"foot\")" in seg
    for ridden in ("atv", "canoe", "motor"):
        assert f'"{ridden}"' not in seg, f"{ridden} legs are being charged as a carry"


def test_loads_is_a_quartered_bull_not_a_daypack():
    assert synth.LOADS >= 5, "a 400-600 lb animal does not come out in three trips"


def test_walk_km_includes_the_portage():
    """A portage is still walking — it must not vanish from the on-foot total just
    because it earned its own name."""
    src = inspect.getsource(synth._add_routes)
    seg = src[src.index('props["walk_km"]'):src.index("carry = 0.0")]
    assert 'k == "portage"' in seg


def test_the_app_prefers_the_route_over_distance_to_road():
    import pathlib
    src = pathlib.Path("app/app.js").read_text()
    body = src[src.index("function packout(a){"):]
    body = body[:body.index("\nfunction ")]
    assert "carry_km" in body, "the pack-out read still ignores what the route knows"
    assert "PORTAGE" in body, "a portage is not called out to the hunter"
    assert "dist_road_m" in body, "the fallback for older plans was removed"
