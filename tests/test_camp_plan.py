"""A camp hunt is asked a different question (T9.3).

A find-sites hunt asks "which of these places should I go to", and ranking areas against
each other answers it. A hunt from a camp you already own asks something else: "how good
is hunting THIS cabin, and which of the ground I can reach should I hunt today". The
areas around a camp are COMPLEMENTS — you will hunt all of them across a week — so
ranking them against each other answers a question nobody asked.

Reported directly: "A camp style hunt is more concentrated by default... Im less
concerned about comparing those three sites - im more concerned about 'how good is
hunting this cabin at this time, given your access to these three sites' and potentially
a strategy of when to hunt each of the different focus areas based on weather."
"""
import pytest

from moose_scout.contract import _ang_diff, camp_plan


class _Hunter:
    def __init__(self, fixed_camp=None):
        self.fixed_camp = fixed_camp


class _AOI:
    def __init__(self, fixed_camp=None):
        self.hunter = _Hunter(fixed_camp)


class _Ctx:
    def __init__(self, fixed_camp=None):
        self.aoi = _AOI(fixed_camp)
        self.model = type("M", (), {"weather": {"midday_hot_threshold_c": 15.0}})()


def _area(rank, km2, hab):
    return {"rank": rank, "area_km2": km2, "habitat_score": hab}


def _stand(area, from_deg, legend="rut_calling"):
    return {"type": legend, "properties": {"legend": legend, "focus_area": area,
                                           "optimal_wind": {"from_deg": from_deg}}}


def _day(date, wind_deg, compass="N", t_max=8.0, precip=0.0):
    return {"date": date, "wind_from_deg": wind_deg, "wind_from_compass": compass,
            "wind_kmh": 12.0, "t_max_c": t_max, "precip_mm": precip}


# ------------------------------------------------------------------ scope


def test_it_is_only_for_a_camp_hunt():
    """Every other hunt style keeps the brief it has. Returning None rather than an empty
    block means no caller downstream has to special-case the difference."""
    assert camp_plan(_Ctx(fixed_camp=None), [_area(1, 5, 0.4)], [], {}, [], None) is None


def test_a_camp_with_no_qualifying_ground_says_so_without_blaming_the_cabin():
    """Zero areas is a statement about the stated WALK, not about the place. Telling a
    hunter their cabin is bad ground when we only looked 2 km around it would be a
    confident overreach."""
    out = camp_plan(_Ctx(fixed_camp=(47.8, -77.8)), [], [], {}, [], None)
    assert out["verdict"]["areas"] == 0
    assert "widen the walk" in out["verdict"]["line"]


# ------------------------------------------------------------------ the verdict


def test_the_verdict_is_about_the_camp_not_a_league_table():
    areas = [_area(1, 6.0, 0.40), _area(2, 2.0, 0.20)]
    stands = [_stand(1, 90), _stand(2, 270)]
    camps = [{"packin_km_by_area": {"1": 1.2, "2": 3.4}}]
    out = camp_plan(_Ctx(fixed_camp=(47.8, -77.8)), areas, stands, {}, camps, None)
    v = out["verdict"]
    assert v["areas"] == 2
    assert v["total_km2"] == 8.0
    # AREA-WEIGHTED, not a flat mean: 6 km2 of 0.40 and 2 km2 of 0.20 is 0.35, not 0.30.
    # A flat mean would let a tiny poor pocket drag down a big good one.
    assert v["habitat"] == pytest.approx(0.35, abs=1e-6)
    assert v["packin_min_km"] == 1.2 and v["packin_max_km"] == 3.4
    assert "8.0 km²" in v["line"] and "2 areas" in v["line"]


def test_a_long_carry_is_called_out_before_the_shot_not_after():
    areas = [_area(1, 8.0, 0.5)]
    camps = [{"packin_km_by_area": {"1": 4.5}}]
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), areas, [_stand(1, 0)], {}, camps, None)
    assert any("pack-out before you shoot" in c for c in out["verdict"]["caveats"])


def test_thin_ground_is_stated_plainly():
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), [_area(1, 2.0, 0.12)], [_stand(1, 0)],
                    {}, [], None)
    cav = " ".join(out["verdict"]["caveats"])
    assert "modest" in cav and "concentrated" in cav


# ------------------------------------------------------------------ the rotation


def test_the_rotation_picks_the_area_the_wind_suits():
    areas = [_area(1, 5, 0.4), _area(2, 5, 0.4)]
    stands = [_stand(1, 90), _stand(2, 270)]     # area 1 wants an E wind, area 2 a W wind
    weather = {"days": [_day("2026-10-10", 90, "E"), _day("2026-10-11", 270, "W")]}
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), areas, stands, weather, [], None)
    rot = {r["date"]: r for r in out["rotation"]}
    assert rot["2026-10-10"]["areas"] == [1], "an east wind must send you to the east-facing area"
    assert rot["2026-10-11"]["areas"] == [2]


def test_a_day_that_suits_nothing_says_so_and_still_gives_the_closest():
    """Silence on a bad-wind day is useless; a hunter is going out regardless."""
    areas = [_area(1, 5, 0.4)]
    stands = [_stand(1, 0)]                      # wants a N wind
    weather = {"days": [_day("2026-10-10", 180, "S")]}   # dead opposite
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), areas, stands, weather, [], None)
    d = out["rotation"][0]
    assert d["areas"] == []
    assert d["second"] == [1]
    assert "still-hunt it into the wind" in d["note"]


def test_a_warm_day_changes_the_advice():
    areas = [_area(1, 5, 0.4)]
    weather = {"days": [_day("2026-10-10", 0, "N", t_max=19.0)]}
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), areas, [_stand(1, 0)], weather, [], None)
    d = out["rotation"][0]
    assert d["hot"] is True
    assert "thermal refuge" in (d["hot_note"] or "")


# ------------------------------------------------- wind robustness (a built stand)


def test_wind_robustness_counts_the_directions_a_stand_can_be_hunted_on():
    """The question that matters for a cabin you return to every year: a blind that only
    works on a north wind is worth far less than one that works on four. Nothing scored
    this before."""
    areas = [_area(1, 5, 0.4), _area(2, 5, 0.4)]
    stands = [_stand(1, 0), _stand(1, 90), _stand(1, 180), _stand(1, 270),  # all round
              _stand(2, 0)]                                                  # one way only
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), areas, stands, {}, [], None)
    assert out["robust"][1]["octants"] == 8, "four opposed stands cover every octant"
    assert out["robust"][2]["octants"] == 3, "one bearing covers itself and its neighbours"
    assert out["robust"][1]["octants"] > out["robust"][2]["octants"]


def test_the_framing_says_the_areas_are_complements():
    out = camp_plan(_Ctx(fixed_camp=(1, 1)), [_area(1, 5, 0.4)], [_stand(1, 0)],
                    {}, [], None)
    assert "not competing" in out["how"]


# ------------------------------------------------------------------ the helper


@pytest.mark.parametrize("a,b,want", [(0, 0, 0), (0, 90, 90), (0, 350, 10),
                                      (350, 10, 20), (0, 180, 180), (270, 90, 180)])
def test_angle_difference_wraps(a, b, want):
    assert _ang_diff(a, b) == pytest.approx(want)
