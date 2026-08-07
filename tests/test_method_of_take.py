"""What you are carrying changes where you sit (T10.2).

Reported alongside the multi-window brief: "it seems like we need to indicate what the
method of take is for each hunting date range, as shooting locations for a bow (max
30/40yds) are going to be different for those with a rifle (longer range, need visibility
more than proximity - can reach out further / less concern about local scent as you wont
be as close)."

Before this, method of take was not an input at all. T10.1 gave each window its own
brief; without this that was half a fix — correctly labelled bow advice that still placed
the shooter 70 m from the caller, which is twice a bow's effective range, and still
recommended glassing knobs a bow hunter cannot use.

A window is usually a SEASON and a season is usually a weapon, which is how it was
reported, so the method belongs to the WINDOW. It rides as an optional third element of
each window so every request that ever worked still works.
"""
import pytest

from moose_scout import scent, synth, worker


BOW = ["2026-09-12", "2026-09-20"]
RIFLE = ["2026-10-10", "2026-10-25"]


# ------------------------------------------------------------- it belongs to the window


def test_a_window_carries_its_own_method():
    req = {"windows": [BOW + ["bow"], RIFLE + ["rifle"]]}
    assert worker.methods_of(req) == ["bow", "rifle"]
    assert worker.windows_of(req) == [BOW, RIFLE], "the dates must survive the extra element"


def test_a_two_element_window_is_still_a_rifle_window():
    """Every request that ever worked must keep working."""
    assert worker.methods_of({"windows": [BOW, RIFLE]}) == ["rifle", "rifle"]
    assert worker.methods_of({}) == ["rifle"]


def test_the_top_level_method_is_the_default_for_windows_that_omit_it():
    req = {"windows": [BOW, RIFLE + ["rifle"]], "method": "bow"}
    assert worker.methods_of(req) == ["bow", "rifle"]


def test_a_nonsense_method_falls_back_rather_than_propagating():
    assert worker.methods_of({"windows": [BOW + ["crossbow-of-doom"]]}) == ["rifle"]
    assert worker.methods_of({"method": "slingshot"}) == ["rifle"]


def test_methods_line_up_with_windows_one_for_one():
    """They are zipped by index in `run`, so a length mismatch silently gives a window
    somebody else's weapon."""
    for req in ({"windows": [BOW, RIFLE]},
                {"windows": [BOW + ["bow"]]},
                {"target_dates": RIFLE},
                {}):
        assert len(worker.methods_of(req)) == len(worker.windows_of(req)), req


def test_the_worker_gives_each_plan_its_own_method():
    import inspect
    src = inspect.getsource(worker.run)
    assert "methods_of(req)" in src
    assert 'method=pl.get("method")' in src, "the plan's method never reaches build_ctx"


# --------------------------------------------------------- it changes the geometry


def test_a_bow_setup_is_tighter_than_a_rifle_one():
    """THE ONE THIS EXISTS FOR. 70 m downwind is a rifle number; a bow hunter cannot
    shoot half that far, so the whole layout comes in."""
    bow, rifle = scent.geometry_for("bow"), scent.geometry_for("rifle")
    assert bow["shooter_m"] < rifle["shooter_m"]
    assert bow["wick_m"] < rifle["wick_m"]
    assert bow["flank_m"] < rifle["flank_m"]


@pytest.mark.parametrize("method", ["rifle", "bow", "muzzleloader"])
def test_the_bull_is_stopped_inside_a_range_you_can_use(method):
    """The point of the wicks: he cuts cow scent, stops to work it out, and does that
    where the shooter can act. If the gap exceeds the effective range the layout is
    decoration."""
    g = scent.geometry_for(method)
    gap = g["shooter_m"] - g["wick_m"]
    assert 0 < gap <= g["effective_m"], (
        f"{method}: bull stops {gap} m from the shooter, effective range {g['effective_m']} m")


def test_the_wicks_are_short_of_the_shooter_for_every_method():
    """Past the shooter and the bull walks into the shooter's own scent cone first."""
    for m in ("rifle", "bow", "muzzleloader"):
        g = scent.geometry_for(m)
        assert g["wick_m"] < g["shooter_m"], m


def test_an_unknown_method_gets_the_rifle_layout():
    assert scent.geometry_for("trebuchet") == scent.geometry_for("rifle")


def test_the_map_takes_the_shooter_distance_from_the_engine():
    """It was a literal 0.07 km in the client — a rifle setup drawn for everybody."""
    import pathlib
    src = pathlib.Path("app/app.js").read_text()
    i = src.index("function buildShooters(")
    body = src[i:src.index("\nfunction ", i)]
    assert "shooter_m" in body, "the client is not reading the engine's geometry"
    assert ",0.07)" not in body, "the hardcoded 70 m shooter offset is back"


# ------------------------------------------------------------- it changes the sites


def test_glassing_is_worth_less_with_a_bow():
    """Spotting a bull at 600 m is a plan only if you can reach him."""
    assert synth.METHOD_SITE_W["bow"]["glassing"] < synth.METHOD_SITE_W["rifle"]["glassing"]


def test_close_quarters_setups_matter_more_with_a_bow():
    for key in ("rut_calling", "funnel"):
        assert synth.METHOD_SITE_W["bow"][key] > synth.METHOD_SITE_W["rifle"][key], key


def test_muzzleloader_sits_between_the_two():
    for key in ("glassing", "rut_calling", "funnel"):
        lo = min(synth.METHOD_SITE_W["bow"][key], synth.METHOD_SITE_W["rifle"][key])
        hi = max(synth.METHOD_SITE_W["bow"][key], synth.METHOD_SITE_W["rifle"][key])
        assert lo <= synth.METHOD_SITE_W["muzzleloader"][key] <= hi, key


def test_the_rifle_weighting_is_neutral():
    """Rifle is what every existing plan was computed as, so it must not move."""
    assert set(synth.METHOD_SITE_W["rifle"].values()) == {1.0}


def test_the_method_multiplies_the_rut_phase_rather_than_replacing_it():
    """A bow hunt in the seeking phase is still a calling hunt."""
    import inspect
    src = inspect.getsource(synth)
    assert "pw.get(key, 1.0) * mw.get(key, 1.0)" in src
