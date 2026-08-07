"""A route says what each stretch is TRAVELLED BY, and the machine stays where you left
it (T10.20).

Reported: "I indicated on setup i had an ATV/SXS. On the analysis, i can't see any
difference between routes to be travelled on ATV vs things to be walked... and it should
be able to chain sections of those together - and understand if you go from boat/atv to
walk, the boat/atv is going to stay where it is and not be available for future legs."

WHAT WAS BROKEN was worse than invisible. Routes were computed on the WALKING cost
surface and then, if the hunter had an ATV, every cell that happened to sit on ridable
ground was labelled "atv" afterwards. Measured on a real ATV run, every hunt route came
back as

    foot -> atv -> foot

which says: walk away from camp, board a machine parked in the middle of the bush, ride,
step off, walk on. You can only ride from where the machine IS.

THE RULE, which is also what makes the search cheap: the vehicle starts wherever you do,
and the moment you step off it, it stays there. So a leg has AT MOST ONE vehicle segment
and nothing may be ridden after it. That is enforced structurally by the router rather
than checked afterwards, and the tests below are the guard.

Joe's rules about where each machine starts, recorded because they are product decisions
that no data can settle:
  * an ATV/SxS is co-located with staging, and a vehicle or quad reaches ANY hunt camp;
  * a motorboat rides on the vehicle's trailer, so it launches only where a DRIVABLE
    ROAD meets water — not a quad track;
  * a canoe is portaged, so it can reach water over trails, roads and a short bushwhack.
"""
import numpy as np
import pytest

pytest.importorskip("skimage")
pytest.importorskip("scipy")

from moose_scout import synth


N = 60
RES = 40.0


def _grid():
    """Open bush with one trail running along row 10."""
    walk = np.full((N, N), 1.14)          # bush, as _walk_cost prices it
    net = np.zeros((N, N), bool)
    net[10, :] = True
    walk[net] = 0.05                      # the routing attractor value for a road
    return walk, net


# ------------------------------------------------------ the physically impossible one


def _modes(legs):
    return [m for m, _rc in legs]


def test_a_vehicle_leg_is_never_anything_but_the_first():
    """THE REPORTED BUG. foot -> atv -> foot means boarding a machine that is not there."""
    walk, net = _grid()
    # start ON the trail, destination off it, so a naive labeller would ride-walk-ride
    path, legs = synth._route_with_modes(walk, {"atv": net}, (10, 2), (10, 55), res=RES)
    veh = [i for i, m in enumerate(_modes(legs)) if not m.startswith("foot")]
    assert veh, "the quad was on the trail and was not used at all"
    assert veh == [0], f"vehicle segment is not first / is remounted: {_modes(legs)}"


def test_you_cannot_remount_after_stepping_off():
    """Two trail segments with a gap: walking the gap leaves the quad on the first one,
    so the second must be walked however ridable it looks."""
    walk = np.full((N, N), 1.14)
    net = np.zeros((N, N), bool)
    net[10, 0:20] = True
    net[10, 40:] = True                   # a second, disconnected stretch
    walk[net] = 0.05
    _p, legs = synth._route_with_modes(walk, {"atv": net}, (10, 2), (10, 55), res=RES)
    assert _modes(legs).count("atv") <= 1, f"remounted: {_modes(legs)}"
    veh = [i for i, m in enumerate(_modes(legs)) if not m.startswith("foot")]
    assert veh in ([], [0])


def test_riding_is_preferred_over_walking_the_same_ground():
    """The second version of this bug: ride costs priced from honest EFFORT (0.15/cell)
    were dearer than `_walk_cost`'s road attractor (0.05/cell), so the router dismounted
    the instant it reached the trail — it rode 0.6 km then walked 4.2 km of ridable
    trail. Ride costs are relative to that surface, not to effort."""
    assert synth.RIDE_COST["atv"] < 0.05, \
        "riding a road costs more than walking it — the router will dismount immediately"
    walk, net = _grid()
    _p, legs = synth._route_with_modes(walk, {"atv": net}, (10, 2), (10, 55), res=RES)
    km = {}
    for m, rc in legs:
        km[m] = km.get(m, 0) + (len(rc) - 1)
    assert km.get("atv", 0) > km.get("foot_trail", 0) + km.get("foot", 0), \
        f"walked more ridable ground than it rode: {km}"


def test_foot_only_when_there_is_no_machine():
    walk, _net = _grid()
    _p, legs = synth._route_with_modes(walk, {}, (30, 2), (30, 55), res=RES)
    assert _modes(legs) == ["foot"]


def test_a_machine_that_does_not_help_is_not_used():
    """A trail running the wrong way is not a reason to ride."""
    walk = np.full((N, N), 1.14)
    net = np.zeros((N, N), bool)
    net[55, :] = True                     # far from both endpoints
    walk[net] = 0.05
    _p, legs = synth._route_with_modes(walk, {"atv": net}, (2, 2), (2, 50), res=RES)
    assert _modes(legs) == ["foot"], f"detoured to a useless trail: {_modes(legs)}"


# ------------------------------------------------------------- where the machine is


def test_a_quad_reaches_a_camp_the_trail_network_does_not_touch():
    """Joe's rule: a vehicle or quad reaches any hunt camp. Measured on a real run, camp
    sat 715 m off the nearest mapped trail and the router refused to ride at all."""
    walk, net = _grid()
    off_trail_camp = (14, 2)              # 4 cells = 160 m off the network
    _p, legs = synth._route_with_modes(walk, {"atv": net}, off_trail_camp, (10, 55), res=RES)
    assert "atv" in _modes(legs), f"the quad could not reach its own camp: {_modes(legs)}"
    assert _modes(legs)[0] == "atv"


def test_the_spur_is_bounded_so_quads_do_not_go_everywhere():
    """The allowance that lets a quad reach its camp must not become open-country
    travel. Far enough off the network and it is a walk."""
    walk, net = _grid()
    far = int(synth.ATV_SPUR_M / RES) + 6
    _p, legs = synth._route_with_modes(walk, {"atv": net}, (10 + far, 2), (10 + far, 55),
                                       res=RES)
    assert "atv" not in _modes(legs), "rode across open bush well beyond the spur limit"


def test_both_ends_drivable_makes_the_whole_leg_a_ride():
    """Staging -> camp: both ends are places a vehicle got to, so it is one ride. Without
    this the access leg came back as 620 m of bushwhacking on a run where the hunter had
    a quad and both ends were places you drive to."""
    walk, net = _grid()
    _p, legs = synth._route_with_modes(walk, {"atv": net}, (13, 4), (13, 12),
                                       res=RES, dest_vehicle_ok=True)
    assert _modes(legs) == ["atv"], f"expected one ride, got {_modes(legs)}"


# -------------------------------------------------------------- naming what you cross


def test_foot_legs_separate_trail_from_bushwhack():
    """Walking a cut line and bushwhacking are different hunts — different speed, noise
    and odds of being seen first — and the bushwhack is the number that matters on a
    pack-out."""
    _walk, net = _grid()
    leg = [(10, c) for c in range(2, 20)] + [(r, 20) for r in range(11, 25)]
    out = synth._split_foot(leg, net)
    modes = [m for m, _ in out]
    assert "foot_trail" in modes and "foot_bush" in modes, modes
    assert modes[0] == "foot_trail"


def test_split_foot_is_a_no_op_without_a_trail_layer():
    leg = [(5, c) for c in range(2, 12)]
    assert synth._split_foot(leg, None) == [("foot", leg)]


# --------------------------------------------------------------------- the boat rules


def test_a_motorboat_needs_a_road_at_the_water():
    """It is on the vehicle's trailer. A quad track is not a boat launch."""
    import types

    shape = (N, N)
    water = np.zeros(shape, bool); water[30:40, :] = True
    cache = types.SimpleNamespace()
    # no roads.tif in this cache → nowhere to launch
    assert synth._launch_mask("motor", water, _NoCache(), shape, RES) is None


class _NoCache:
    """A cache path that contains nothing — every _opt() read misses."""
    def __truediv__(self, other):
        return _NoCache()
    def exists(self):
        return False
    def __fspath__(self):
        return "/nonexistent"


def test_a_canoe_may_be_carried_to_the_water():
    """Portaged, so it does not need a ramp — it needs water within a carry."""
    shape = (N, N)
    water = np.zeros(shape, bool); water[30:40, :] = True
    # with nothing mapped to carry along, the whole waterbody is fair game
    m = synth._launch_mask("canoe", water, _NoCache(), shape, RES)
    assert m is not None and m.any()
