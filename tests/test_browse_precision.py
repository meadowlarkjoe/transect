"""The satellite tier must never outrank a surveyed one (T10.19).

T10.16 fixed a frozen, snow-contaminated imagery window and moved mean NDVI on a real
box from 0.272 to 0.467. The browse and cover curves it feeds use ABSOLUTE breakpoints,
so rev 21's lesson applied directly: a constant left pointing at a distribution that has
shifted underneath it is how the model goes quietly wrong. T10.19 was opened to check
them against evidence rather than against the argument that they "look like textbook
leaf-on values" — which is what I had, and which is not evidence.

WHAT THE MEASUREMENT FOUND, using the écoforestière stand map as ground truth (surveyed,
and independent of NDVI), on two boxes:

    class        NDVI p50   browse_n     browse FINAL
    conifer        0.41       0.53          0.000
    recent cut     0.43       0.58          0.430

The NDVI term is a BAD browse discriminator and says so plainly: it scores closed
conifer at 0.53 — moderate browse, for ground surveyors recorded as having nothing to
eat — and it ranks mature DECIDUOUS (0.78) above a recent CUT (0.58), which is backwards
for anything eaten at browse height. Land cover is no better: +0.03 between cut and
conifer, against NDVI's +0.05.

The final answer is nonetheless right, and the reason is architectural rather than lucky.
Rev 21 put both in the LANDCOVER tier — the least precise — so a surveyed stand or a
dated cut overrides them outright: +0.43 separation where NDVI and land cover together
could not manage +0.09. Where no stand map exists (north of ~52°N) NDVI carries 40% of
that tier, and swapping the contaminated input for honest leaf-on moved browse on closed
tree cover only 0.269 -> 0.325, with the fraction above 0.5 unchanged at 6.1%.

So the breakpoints stay. What this file guards is the thing that makes that safe: the
ordering. A change that promotes the landcover tier, or drops a surveyed source, would
re-expose a term we now have measurements proving is unfit to lead.
"""
import inspect

import pytest

from moose_scout import habitat


def _order():
    src = inspect.getsource(habitat)
    line = [l for l in src.split("\n") if l.strip().startswith("ORDER = [")]
    assert line, "the precision ORDER is gone — browse is no longer combined by precision"
    return eval(line[0].split("=", 1)[1].strip())      # noqa: S307 — our own source


def test_the_satellite_tier_ranks_last():
    """THE ONE THAT MATTERS. NDVI and WorldCover are guesses about what is growing;
    a dated cut and a walked stand are records of it. Measured, the guesses separate
    browse from conifer by +0.05 and the records by +0.43."""
    order = dict(_order())
    assert order["landcover"] == min(order.values()), \
        f"the satellite tier is no longer least-precise: {order}"


def test_a_dated_disturbance_outranks_everything():
    """Browse in this landscape is a function of disturbance AGE, and a cut with a year
    on it is the only source that knows the year."""
    order = dict(_order())
    assert order["cut"] == max(order.values()), f"dated cuts no longer lead: {order}"
    assert order["cut"] > order["stand"] > order["landcover"]


def test_burn_and_stand_both_outrank_the_satellite():
    order = dict(_order())
    assert order["burn"] > order["landcover"]
    assert order["stand"] > order["landcover"]


def test_every_tier_has_a_distinct_precision():
    """Ties would make the combine order depend on dict iteration, which is not a
    modelling decision anybody made."""
    order = dict(_order())
    assert len(set(order.values())) == len(order), f"tiers tie: {order}"


# ----------------------------------------------------- the curve's known weaknesses


def _browse_n(n):
    import numpy as np
    n = np.clip(n, -0.2, 0.9)
    return float(np.clip((n - 0.15) / 0.5, 0, 1) * np.clip(1 - (n - 0.8) / 0.15, 0, 1))


def test_the_ndvi_curve_cannot_separate_cut_from_conifer():
    """Not a bug to fix here — a limit to keep recorded, because it is the reason the
    tier order above is load-bearing. Measured NDVI medians: conifer 0.41, cut 0.43."""
    gap = _browse_n(0.43) - _browse_n(0.41)
    assert 0.0 < gap < 0.10, (
        f"cut-vs-conifer separation from NDVI alone is {gap:.3f}; if this ever becomes "
        f"large, NDVI has become a real discriminator and the tiering can be revisited")


def test_the_ndvi_curve_still_ranks_deciduous_above_a_recent_cut():
    """Backwards for browse, and pinned so nobody 'fixes' the tiering while believing
    this term is sound. Measured medians: recent cut 0.43, deciduous 0.56."""
    assert _browse_n(0.56) > _browse_n(0.43)


def test_the_curve_rolls_off_for_very_green_ground():
    """The one thing it does get right: a closed, uniformly green canopy is not browse."""
    assert _browse_n(0.90) < _browse_n(0.70)


@pytest.mark.parametrize("n", [-0.2, 0.0, 0.1])
def test_water_and_bare_ground_score_no_browse(n):
    assert _browse_n(n) == 0.0
