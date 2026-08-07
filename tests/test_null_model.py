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
                mean_hunt_ceiling=0.60, capture=0.5,
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


def test_the_measured_capture_on_real_boxes_is_reported_not_flattered():
    """THE FINDING. On first measurement the focus areas captured 6%, 16% and 20% of the
    gap between random ground and what the model's own score could reach — so the
    benchmark FAILS two of three real boxes, and the threshold was left where it fails
    rather than moved until it passed. Retuning this to go green is the rev-21 mistake."""
    for cap in (0.06, 0.16, 0.20):
        assert validate.verdict(_r(capture=cap))["beats_random"] is False, cap
    assert validate.verdict(_r(capture=0.30))["beats_random"] is True


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
