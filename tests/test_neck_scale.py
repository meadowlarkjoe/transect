"""The neck cut and ring are metres, not cells (T9.10b).

T9.10b was blocked on an unexplained population change: measuring necks on a finer grid
took the funnel count from 7 to 3, and "relaxing the polygonize admission bar until the
count came back is the rev-21 mistake exactly." So it sat behind `FINE_NECKS=1`.

IT WAS NEVER THE TERRAIN. `_constriction` documents at length why `size=3` and `db > res`
had to become metres — "which asked a different question at every resolution" — and then
`neck_sides` was left with two bare cell counts doing exactly that:

  * `rad = ceil(db.max()/res) + 2`   — the cut reaches 2 CELLS past the half-width
  * `ndi.binary_dilation(cut, iterations=2)` — the ring is 2 CELLS thick

80 m each on the 40 m analysis grid; 27 m on a 13 m fine one. And the error is not
symmetric: a thinner cut fails to SEVER (`sn < 2`, thrown out as "separates nothing") and
a thinner ring TOUCHES fewer components (`len(touching) < 2`, thrown out as a dead end).
Both push a finer grid toward rejecting necks a coarser one keeps.

MEASURED, on an 800x800 box carrying the water vectors, fine grid at 13.3 m:

    before   candidates 1937 -> 2284   kept 228 ->  77    coarse-only cells 2595
    after    candidates 1937 -> 2284   kept 228 -> 436    coarse-only cells  717

The finer medial axis was always finding MORE candidates; the collapse was entirely in
admission. Fixed, the fine detector retains 76% of the coarse necks instead of 15%, and
distinct measured widths go from 19 to 98 with the floor dropping from 113 m to 53 m.

WHAT THIS FILE DOES NOT CLAIM: that the necks the fine grid ADDS are real. It gains 3007
cells at a median width of 208 m, and only 16% of those are narrower than the coarse
grid's 113 m floor — so most are not simply "necks the grid could not express". That is
a ground-truth question and it is still open.
"""
import inspect

import pytest

pytest.importorskip("scipy")

from moose_scout import terrain as T


def test_the_constants_exist_as_named_metres_not_literals():
    src = inspect.getsource(T.neck_sides)
    assert "CUT_MARGIN_CELLS" in src and "RING_CELLS" in src
    assert "+ 2\n" not in src, "the cut margin is a bare cell count again"
    assert "iterations=2)" not in src, "the ring is a bare cell count again"


def test_on_the_analysis_grid_nothing_changes_at_all():
    """The fix must be a NO-OP for every run shipping today, or it is not a fix, it is a
    model change wearing one. At res == grid_res both constants come back to 2 cells.

    Confirmed numerically as well as arithmetically: the coarse arm of the A/B kept 228
    necks both before and after this change."""
    for res in (10.0, 20.0, 40.0, 100.0):
        g = res
        assert max(1, int(round(T.CUT_MARGIN_CELLS * g / res))) == 2
        assert max(1, int(round(T.RING_CELLS * g / res))) == 2


def test_a_finer_grid_asks_the_same_question_in_metres():
    """3x finer means 3x the cells for the same distance on the ground."""
    grid = 40.0
    for k in (2, 3, 4, 8):
        res = grid / k
        assert max(1, int(round(T.CUT_MARGIN_CELLS * grid / res))) == 2 * k
        assert max(1, int(round(T.RING_CELLS * grid / res))) == 2 * k


def test_grid_res_reaches_neck_sides_from_the_detector():
    """The thread that carries it: _constriction -> _linkage -> neck_sides. A break
    anywhere silently restores the cell-denominated behaviour."""
    assert "grid_res" in inspect.signature(T.neck_sides).parameters
    assert "grid_res" in inspect.signature(T._linkage).parameters
    assert "_linkage(constriction, passable, res, db, grid_res)" in \
        inspect.getsource(T._constriction)


def test_behaviour_callers_that_do_not_pass_it_get_the_analysis_grid():
    """behavior.py works on the working grid and calls neck_sides without grid_res.
    The default has to be `res`, not a constant, or T10.18 changes silently."""
    assert inspect.signature(T.neck_sides).parameters["grid_res"].default is None
    assert "g = float(grid_res or res)" in inspect.getsource(T.neck_sides)


def test_the_fine_grid_is_inert_on_a_full_size_box():
    """Worth pinning because it bounds the risk of the switch: FINE_BUDGET_PX is 9 Mpx
    and a real analysis grid is 3.1-6.5 Mpx, so the step floors to 1 and `FINE_NECKS=1`
    changes nothing on a production box. Whatever is decided about the flag, raising the
    BUDGET is the separate decision that actually has blast radius."""
    import os
    old = os.environ.get("FINE_NECKS")
    os.environ["FINE_NECKS"] = "1"
    try:
        assert T._fine_res(40.0, (1769, 1774)) == 40.0    # fire_lake, 35 km radius
        assert T._fine_res(40.0, (2538, 2544)) == 40.0    # rouyn, 45 km radius
        assert T._fine_res(40.0, (800, 800)) < 40.0       # small box: it does engage
    finally:
        if old is None:
            os.environ.pop("FINE_NECKS", None)
        else:
            os.environ["FINE_NECKS"] = old


def test_only_odd_fine_steps_are_used():
    """The medial-axis window is `3 * grid_res` metres realised as an odd cell count.
    3*step is odd only when step is odd, so an even step forces the window WIDER than the
    analysis grid asks — 17% wider at 2x — which makes the ridge test stricter and finds
    FEWER necks on a finer grid.

    Measured on fire_lake: candidates 9813 at 1x, 6966 at 2x, 10463 at 3x. A 2x grid is
    measurably worse than the 1x grid it would replace, so an even step is snapped down
    rather than accepted."""
    import os
    old = os.environ.get("FINE_NECKS")
    os.environ["FINE_NECKS"] = "1"
    try:
        for px in (10_000, 40_000, 250_000, 1_000_000, 2_000_000, 3_140_000, 6_460_000):
            n = int(px ** 0.5)
            res = 40.0
            f = T._fine_res(res, (n, n))
            step = round(res / f)
            assert step % 2 == 1, f"{px} px chose an even step {step}"
            # and the window it implies is metrically exact
            rw = max(3, int(round(3.0 * res / f)) | 1)
            assert abs(rw * f - 3.0 * res) < 1e-6, \
                f"step {step} realises a {rw * f:.1f} m window, not {3.0 * res:.0f} m"
    finally:
        if old is None:
            os.environ.pop("FINE_NECKS", None)
        else:
            os.environ["FINE_NECKS"] = old


def test_snapping_down_never_exceeds_the_budget():
    """It only ever reduces the step, so a box that fitted still fits."""
    import inspect
    src = inspect.getsource(T._fine_res)
    assert "step - 1 if step % 2 == 0 else step" in src
    assert "max(1," in src, "a budget too small for any fine grid must land on 1x, not 0"
