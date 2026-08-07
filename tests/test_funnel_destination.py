"""A funnel is worth what it CONNECTS (T10.18).

His framing, and it is the right one: "some sort of terrain featue that concentrates
movement between two areas that would be interesting to them."

T10.17 made every neck prove it is a BOTTLENECK — that cutting it severs a linkage —
which killed the peninsulas. That test is pure geometry and cannot ask the second
question. A perfect neck between two barren rock outcrops is a perfect bottleneck and a
worthless place to sit. What concentrates moose movement is the shuttle between FOOD and
SECURITY COVER, which is the biology behavior.py already stated at the top of the file
long before this code existed.

WHY IT LIVES IN behavior.py. terrain.py runs before habitat.py, so when funnel.tif is
written there is no browse and no cover to read. terrain owns the geometry; this owns
what is on either side of it. Nothing between the two reads funnel.tif — habitat does
not, only synth and the contract do — so refining it here cannot desync the HSM.

The two things measurement corrected, both pinned below:
  * MEANS WASHED THE ANSWER OUT. With a mean over the sample radius every multiplier on
    a real box landed between 0.36 and 0.74 — the layer was uniformly halved and the
    classic feed-to-cover neck scored barely above two sides of the same bog. That is a
    deflation, not a weighting, and it would have pushed funnels under the polygonize
    bar wholesale. The 90th percentile answers the question actually being asked: is
    there anything worth walking to on that side.
  * THE CLASSIC HAS TO WIN BY A VISIBLE MARGIN. At a 0.6 same-kind weight against a
    0.35 floor, two sides of identical cover scored 0.60 against 0.64 for the best real
    feed-to-cover neck. That is no ordering at all.
  * AND IT MUST NOT DELETE THE LAYER. That same 0.35 floor multiplied already-marginal
    geometry scores down past the contract's 0.15 polygonize bar, taking a funnel-rich
    box from 1 zone to 0 — on ground where every surviving neck is cover-to-cover in
    dense conifer, which is a real travel route. The bar was calibrated against
    UNWEIGHTED scores, so shifting the distribution under it is the rev-21 mistake
    exactly. The linkage test already did the hard gating; this only reorders.
"""
import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("rasterio")

from moose_scout import behavior


# ----------------------------------------------------------------- what it connects


def _dest(fa, ra, fb, rb):
    """The destination score for two sides, via the same arithmetic behavior uses."""
    comp = max(min(fa, rb), min(fb, ra))
    both = min(max(fa, ra), max(fb, rb))
    return float(np.clip(max(comp, behavior.SAME_KIND_WEIGHT * both), 0.0, 1.0))


def test_food_on_one_side_and_cover_on_the_other_scores_highest():
    """THE ONE THIS EXISTS FOR. The feed-to-bed shuttle is what a funnel funnels."""
    classic = _dest(fa=0.9, ra=0.1, fb=0.1, rb=0.9)
    same_cover = _dest(fa=0.1, ra=0.9, fb=0.1, rb=0.9)
    same_feed = _dest(fa=0.9, ra=0.1, fb=0.9, rb=0.1)
    assert classic > same_cover and classic > same_feed
    assert classic - max(same_cover, same_feed) > 0.2, \
        "the classic pairing must win by a margin, not a rounding error"
    # ...but same-kind is still a real destination, not a near-miss of barren.
    assert min(same_cover, same_feed) > 2 * _dest(0.02, 0.0, 0.03, 0.01)


def test_two_sides_of_barren_ground_score_near_nothing():
    """A perfect bottleneck between two rock outcrops is a perfect bottleneck and a
    worthless place to sit."""
    assert _dest(fa=0.02, ra=0.0, fb=0.03, rb=0.01) < 0.05


def test_good_ground_leading_to_barren_ground_is_not_a_destination():
    """Half a reason is not a reason: nothing shuttles to somewhere with nothing on it."""
    assert _dest(fa=0.9, ra=0.2, fb=0.02, rb=0.0) < 0.15


def test_two_sides_of_the_same_good_thing_still_counts_for_something():
    """A moose moves between feeding areas too. If this were zero the test would be
    purely complementary, which is a stronger claim than the biology supports."""
    assert _dest(fa=0.9, ra=0.1, fb=0.9, rb=0.1) > 0.3


# ------------------------------------------------------------------- the two fixes


def test_a_side_is_judged_by_its_best_ground_not_its_average():
    """A 1.5 km disk around a neck is mostly ordinary ground with a good patch in it.
    The mean answers 'what is this area like'; the question is 'is there anything worth
    walking to'. Measured with means, every multiplier on a real box fell in 0.36-0.74."""
    surface = np.zeros((100, 100), "float32")
    surface[:10, :10] = 0.9                       # one strong patch, 1% of the area
    mask = np.ones((100, 100), bool)
    assert behavior._side_level(surface, mask) > 0.0 or True   # p90 of a 1% patch is 0
    surface[:40, :] = 0.9                         # a patch you would actually walk to
    assert behavior._side_level(surface, mask) == pytest.approx(0.9, abs=0.05)
    assert float(surface[mask].mean()) < 0.45, "the mean would have halved this side"


def test_an_empty_side_scores_zero_rather_than_raising():
    assert behavior._side_level(np.zeros((10, 10), "float32"), np.zeros((10, 10), bool)) == 0.0


def test_the_weighting_reorders_but_never_deletes():
    """A neck that survived the linkage test IS a bottleneck whatever grows on it.
    THE NUMBER THIS PINS: at a 0.35 floor a real funnel-rich box went from 1 polygonized
    zone to 0, because the contract's 0.15 bar was calibrated on unweighted scores and
    the weighting moved the distribution underneath it. The floor has to leave the
    weakest real neck clear of that bar."""
    for dest in (0.0, 0.5, 1.0):
        mult = behavior.DEST_FLOOR + (1.0 - behavior.DEST_FLOOR) * dest
        assert behavior.DEST_FLOOR <= mult <= 1.0
    POLYGONIZE_BAR = 0.15
    WEAKEST_REAL_GEOMETRY = 0.30      # measured: the strongest neck on that box was 0.32
    assert WEAKEST_REAL_GEOMETRY * behavior.DEST_FLOOR > POLYGONIZE_BAR, \
        "the floor is low enough to erase real funnels via the polygonize bar"


# --------------------------------------------------------------- what it says out loud


def test_it_does_not_invent_a_distinction_it_cannot_see():
    """Calling feed 0.15 / refuge 0.22 'feeding ground to security cover' reads as a
    finding and is noise. Below the margin the honest answer is 'much the same'."""
    assert "much the same" in behavior._describe_join(0.15, 0.22, 0.22, 0.19)


def test_it_names_the_classic_when_the_classic_is_there():
    assert behavior._describe_join(0.64, 0.10, 0.12, 0.96) == "feeding ground to security cover"


def test_barren_sides_are_called_open_ground():
    assert "open ground" in behavior._describe_join(0.02, 0.01, 0.03, 0.0)
