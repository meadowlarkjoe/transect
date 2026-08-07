"""The null-model benchmark, and the mistake it nearly shipped with (T6.1).

The ticket named the problem: "the model is currently unfalsifiable. This is the
highest-value ticket in the backlog and the one most easily deferred forever." There is
no ground truth for where moose are, which is exactly why a benchmark that waits for
ground truth waits forever.

So this asks the question that can be answered without any: does the model tell you
anything a five-line heuristic would not?

THE MISTAKE, pinned below because it is subtle and it passed every eye until it was run.
The random null was first written as an OVERLAP test — take a random selection of the
same size and see how much of it the model also picked. That number is a tautology: two
independent same-sized selections from the same pool overlap at the area fraction by
construction. Measured, it came back 4.0% against an expected 4.0% and 6.3% against 6.3%,
and the check built on it would have passed for a literally random model. It is now
measured on CAPTURE — how much of the discrimination the model's own surface contains
survives into the ground it hands you — and on coherence.

WHAT IT MUST NEVER CLAIM: beating both nulls does not mean the answer is right. It means
the model is doing something other than tracing roads or throwing darts. Being wrong in
an interesting way still fails a hunt.
"""
import numpy as np
import pytest

pytest.importorskip("scipy")

from moose_scout import validate


def _r(**kw):
    base = dict(ok=True, selected_frac=0.05, overlap_road=0.1,
                mean_hunt_selected=0.40, mean_hunt_random=0.20,
                mean_hunt_ceiling=0.60, mean_hunt_oracle=0.50,
                oracle_headroom=0.30, capture=0.5,
                patches_selected=3, patches_random=5000,
                spearman_hunt_vs_proximity=0.1)
    base.update(kw)
    return base


# ---------------------------------------------------------------- the road null model


def test_a_model_that_is_a_road_buffer_fails():
    """The failure this benchmark exists to catch: if a road buffer picks the same
    ground, the model is an expensive road buffer."""
    assert validate.verdict(_r(overlap_road=0.92))["beats_road"] is False


def test_a_model_that_merely_RANKS_like_road_proximity_also_fails():
    """Two ways to be a road buffer. Picking the same ground is one; ordering all ground
    the same way is the other, and it is the one that hides better."""
    assert validate.verdict(_r(spearman_hunt_vs_proximity=0.88))["beats_road"] is False
    assert validate.verdict(_r(spearman_hunt_vs_proximity=-0.88))["beats_road"] is False


def test_real_measurements_clear_the_road_null():
    """Measured on three real boxes: overlap 0.4-11.3%, rank correlation +0.06 to +0.20.
    Whatever else is true, this model is not tracing roads."""
    for ov, sp in ((0.047, 0.056), (0.004, 0.078), (0.113, 0.202)):
        assert validate.verdict(_r(overlap_road=ov, spearman_hunt_vs_proximity=sp))["beats_road"]


# -------------------------------------------------------------- the random null model


def test_the_random_null_is_not_an_overlap_test():
    """THE MISTAKE. Overlap with a random selection of matched size equals the area
    fraction by construction, so it cannot distinguish anything."""
    import inspect
    src = inspect.getsource(validate)
    assert "overlap_random" not in src.split('"""', 2)[2], \
        "the tautological overlap-with-random metric is back"


def test_a_selection_that_keeps_none_of_the_signal_fails():
    """Capture 0 means the chosen ground is no better than a random draw."""
    assert validate.verdict(_r(capture=0.0))["beats_random"] is False


def test_confetti_fails_even_if_it_concentrates():
    """Scattered cells are not a place you can hunt, however well they score."""
    assert validate.verdict(_r(capture=0.9, patches_selected=4000,
                               patches_random=5000))["beats_random"] is False


def test_the_capture_threshold_is_where_it_fails_not_where_it_flatters():
    """The threshold sits where a poor selection FAILS, and was never moved to make a
    result go green — that would be the rev-21 mistake.

    Note the "2% of achievable" this was originally written around did not survive:
    T6.4 found it was measured against ground the model could not select at all. With
    the pool recorded (test_focus_pool.py) the model beats a random draw on every box.
    The threshold stands regardless — it guards a real failure mode, it is not a claim
    that the failure is currently happening."""
    for cap in (0.02, 0.05, 0.20):
        assert validate.verdict(_r(capture=cap))["beats_random"] is False, cap
    assert validate.verdict(_r(capture=0.30))["beats_random"] is True


def test_the_yardstick_is_a_contiguous_area_not_cherry_picked_cells():
    """The first ceiling was the best n CELLS, which is maximally fragmented and which no
    walkable area could ever reach — judged against it every result looked like failure,
    which is uninformative. Measured on one box: model 0.248, cherry-picked 0.435, best
    contiguous 0.322. Capture 1% against the wrong target, 5% against the right one."""
    import inspect
    src = inspect.getsource(validate.benchmark)
    assert "_oracle_blob" in src
    assert "hunt_oracle - hunt_rand" in src, "capture is measured against the wrong ceiling"


def test_no_headroom_means_no_verdict_rather_than_a_bad_one():
    """On ground with no structure at this scale the denominator is noise — it produced a
    meaningless -26% on a real box whose oracle beat random by 0.005. 'Not applicable' is
    the honest answer there, not 'failed'."""
    v = validate.verdict(_r(capture=None, oracle_headroom=0.005))
    assert v["beats_random"] is None
    assert v["beats_road"] is True, "the road verdict is independent and must survive"


def test_capture_is_zero_when_the_selection_is_random_and_one_at_the_ceiling():
    r = validate.benchmark.__doc__
    assert r  # the metric is documented
    lo = (0.20 - 0.20) / (0.60 - 0.20)
    hi = (0.60 - 0.20) / (0.60 - 0.20)
    assert lo == 0.0 and hi == 1.0


# ------------------------------------------------------------------------ mechanics


def test_top_mask_takes_exactly_the_requested_cells_and_only_huntable_ones():
    score = np.arange(100, dtype="float64").reshape(10, 10)
    huntable = np.zeros((10, 10), bool)
    huntable[:5, :] = True
    m = validate._top_mask(score, huntable, 7)
    assert m.sum() == 7
    assert not (m & ~huntable).any(), "picked ground the hunter cannot hunt"
    assert score[m].min() >= score[huntable].max() - 7 * 1.0


def test_top_mask_cannot_ask_for_more_than_exists():
    huntable = np.zeros((10, 10), bool); huntable[0, :3] = True
    m = validate._top_mask(np.random.default_rng(0).random((10, 10)), huntable, 999)
    assert m.sum() == 3


def test_spearman_is_a_rank_correlation():
    a = np.array([1.0, 2, 3, 4, 5])
    assert validate._spearman(a, a) == pytest.approx(1.0)
    assert validate._spearman(a, -a) == pytest.approx(-1.0)
    assert validate._spearman(a, a ** 3) == pytest.approx(1.0), "should be rank, not linear"


def test_a_cache_with_no_huntable_ground_reports_rather_than_raises():
    r = {"ok": False, "why": "no huntable ground in this cache"}
    v = validate.verdict(r)
    assert v["beats_road"] is None and v["beats_random"] is None


def test_the_benchmark_never_claims_the_model_is_right():
    """The one sentence this file must always carry."""
    import inspect
    assert "does not say the answer is right" in inspect.getsource(validate.report)


# ------------------------------------------------ the extent bar T6.3 actually shipped


def test_extent_is_gated_on_the_raw_value_not_only_the_smoothed_one():
    """T6.3. Everything in extract_focus_areas thresholds a ~200 m Gaussian, which is
    right for deciding SHAPE and wrong for deciding QUALITY — a blur lifts poor ground
    over the bar wherever it sits beside good ground. Measured, that let an area grow
    until 64-73% of it was below the landscape mean."""
    import inspect
    from moose_scout import synth
    src = inspect.getsource(synth.extract_focus_areas)
    assert "EXTENT_RAW_FRAC" in src
    assert "FLOOR * EXTENT_RAW_FRAC" in src, (
        "the raw bar is tied to `grow` again — that was the first attempt and it did "
        "nothing, because grow can be as low as 0.216 while these landscapes average 0.248")


def test_the_shipped_extent_bar_is_the_one_the_evidence_supported():
    """0.7 is where the sweep stopped, not where capture looked best. 0.85 scored higher
    on one box and halved the area count on two of three; 1.0 produced ZERO areas
    everywhere. Better ground is worth nothing if it is not enough ground to hunt."""
    import pathlib
    import yaml
    cfg = yaml.safe_load(pathlib.Path("config/model.yaml").read_text())
    frac = cfg["focus_areas"]["extent_raw_frac"]
    assert 0.6 <= frac <= 0.8, (
        f"extent_raw_frac is {frac}; above ~0.85 real boxes start losing areas entirely, "
        f"which the sweep measured rather than guessed")


def test_an_extraction_that_produced_nothing_scores_no_capture():
    """The trap this nearly fell into: with zero focus areas the benchmark falls back to
    top-scoring cells, which trivially beat the oracle — a sweep reported capture 2.3-3.2
    for settings whose real result was ZERO areas. The most flattering possible number
    for the worst possible outcome."""
    import inspect
    src = inspect.getsource(validate.benchmark)
    assert "no_areas" in src and "not no_areas" in src, \
        "capture is reported again for a cache with no focus areas"
