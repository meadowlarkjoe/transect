"""Where do I hunt in the box I chose? (reported from a live run)

    "'No focus areas met the bar' — This is the wrong way to analyze this. No focus areas
    shouldnt be an option. I want to know what are the best places to hunt in the area
    ive chosen. The bar should be relative to the search area. It should lower
    progressively so it always provides at least one option, ideally 3+"

    "This area is full of moose so that seems wrong anyway"

That second line is ground truth, and it turns this from a design argument into a
calibration finding. T6.4 measured these boxes earlier: the BEST ACHIEVABLE contiguous
area scores 0.233-0.244, against an admission bar of 0.26. The bar sits ABOVE what this
landscape produces, so "nothing cleared it" was close to the default answer — and it was
being presented as a finding about the ground.

TWO QUESTIONS, AND THEY ARE NOT THE SAME ONE:
    "is this ground good?"       -> the absolute bar; the answer may be "not especially"
    "where do I go on Saturday?" -> the best ground IN THIS BOX, always

WHAT THIS IS NOT: the rev-21 mistake of retuning a constant until a number looks
familiar. `min_huntability` is untouched. What changed is that failing it stops being the
end of the conversation, and every area records WHICH question it answered.
"""
import inspect
import pathlib
import re

import pytest

pytest.importorskip("rasterio")

from moose_scout import synth


def _extract():
    return inspect.getsource(synth.extract_focus_areas)


def test_the_absolute_bar_still_runs_first_and_is_unchanged():
    """Good ground must still be identifiable AS good. If the relative ladder ran first,
    every box would look equally promising and the model would say nothing at all."""
    import yaml
    cfg = yaml.safe_load(pathlib.Path("config/model.yaml").read_text())["focus_areas"]
    assert cfg["min_huntability"] == 0.26, "the absolute constant was retuned — see rev 21"
    src = _extract()
    assert src.index("_find(FLOOR, 0.82") < src.index("np.percentile(pool")


def test_the_floor_steps_down_through_the_boxs_own_distribution():
    src = _extract()
    assert "np.percentile(pool, q)" in src
    assert "TARGET_AREAS" in src


def test_the_ladder_only_ever_relaxes():
    """A percentile floor ABOVE the absolute one would admit less than the pass that
    already ran. CLAMPED rather than skipped: the primary pass can fail on CONTIGUITY
    instead of height — measured, p96 of the smoothed surface is 0.425 and 0.587 on the
    two cached boxes, both well above the 0.26 floor — so skipping those rungs would
    leave a box whose ground is high but fragmented with no areas and no rung willing to
    look at it."""
    src = _extract()
    assert "min(float(np.percentile(pool, q)), FLOOR)" in src


def test_clearing_the_absolute_bar_is_not_caveated_as_relative():
    """A rung that lands ON the absolute floor and succeeds only because the minimum AREA
    was relaxed still found ground that met the quality bar. Labelling that "relative"
    would apologise for a result that needs no apology."""
    src = _extract()
    assert 'bar_kind = "relative" if floor_q < FLOOR else "absolute"' in src


def test_it_aims_for_three_but_settles_for_one():
    """"it should lower progressively so it always provides at least one option, ideally
    3+". The ladder keeps the best result it has found rather than requiring three."""
    src = _extract()
    assert "len(got) > len(cands)" in src
    assert "len(cands) >= TARGET_AREAS" in src
    import yaml
    cfg = yaml.safe_load(pathlib.Path("config/model.yaml").read_text())["focus_areas"]
    assert cfg["target_areas"] >= 3


def test_the_ladder_draws_from_the_same_pool_the_extraction_uses():
    """`hs[np.isfinite(hunt)]` — reachable ground only. Percentiles over the whole raster
    would set the floor from cells that were never candidates, which is the mistake T6.4
    made four times in a row from the other direction."""
    src = _extract()
    assert "hs[np.isfinite(hunt)]" in src


def test_every_area_records_which_bar_it_cleared():
    """The non-negotiable half. A relative ranking presented without saying so reads as
    "this ground is strong", which is exactly the false confidence the absolute bar
    existed to prevent."""
    src = _extract()
    assert '"bar": bar_kind' in src
    assert '"absolute_floor"' in src


def test_the_app_says_when_the_ranking_is_only_relative():
    app = pathlib.Path("app/app.js").read_text()
    assert "Ranked against this box, not against the absolute bar" in app
    body = app[app.index("function relativeBar(){"):]
    body = body[:body.index("\n}")]
    assert "a.bar==='relative'" in body.replace(" ", "")


def test_an_older_plan_is_not_mistaken_for_a_relative_one():
    """Plans saved before this have no `bar` at all, and absence is not evidence of a
    fallback — they were absolute, and labelling them otherwise would be inventing a
    caveat about a run that never needed one."""
    app = pathlib.Path("app/app.js").read_text()
    body = app[app.index("function relativeBar(){"):]
    body = body[:body.index("\n}")]
    assert "every(" in body, "one area without a bar would flip the whole plan"


def test_the_extent_gates_relax_with_the_admission_bar():
    """THE BUG THE TESTS MISSED. Both extent gates are fractions OF THE ADMISSION BAR, and
    they were computed from the module-level FLOOR while the ladder lowered a local
    `floor`. The effect was total: with the absolute bar out of reach the ladder duly
    relaxed admission, and these two gates then rejected every cell the relaxed peaks
    tried to grow into — zero areas, exactly as before, with a green suite.

    Measured after the fix, on fire_lake with the bar forced to 0.95: 45 areas, all
    labelled relative. Before it: 0."""
    src = _extract()
    i = src.index("grow = max(")
    seg = src[i:i + 400]
    assert "max(floor * GROW_FRAC_OF_FLOOR" in seg, \
        "the grow gate reads the module FLOOR again and will not relax"
    assert "np.nan_to_num(hunt) >= floor * EXTENT_RAW_FRAC" in src, \
        "the raw extent gate reads the module FLOOR again"


def test_the_absolute_path_is_unchanged_by_that_fix():
    """`floor` IS `FLOOR` on the primary pass, so nothing about a box that already worked
    moves. Measured on fire_lake at the shipped bar: 58 areas, all absolute, top mean
    0.575 — before and after."""
    src = _extract()
    assert "cands = _find(FLOOR, 0.82, min_km2)" in src
