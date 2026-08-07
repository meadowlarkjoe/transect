"""Terrain is measured finer than the analysis grid runs (T9.10).

The backlog framed this as "MRDEM-30 is the limit on funnels and glassing". Measured,
that turned out to be only half right and the tests below pin the half that was wrong,
because it is the half a future change is most likely to undo.

  * Swapping the SOURCE (30 m -> 1 m LiDAR) under a fixed 40 m analysis grid moved mean
    slope by 1.2% and mean |TPI| by 1.4%. Nothing. The 40 m GRID was the limit.
  * Measuring the same LiDAR at 10 m instead doubled the peak slope inside a 40 m cell
    and raised peak |TPI| by half; ground with |TPI| > 6 m went 62 -> 82 km2.
  * For necks it was starker. On a 40 m grid the tightest neck the detector could
    report was 113 m — not because none were narrower, but because 113 m is roughly
    where the grid quantizes. Sub-100 m necks came back as EXACTLY ZERO on every box.
    At 6.7 m the same box reports necks down to 48 m and 0.51 km2 of sub-100 m neck.

So the two halves have to ship together, and the constants that decide "how narrow is
narrow" have to be in METRES. That last point is the trap this file mostly guards: two
of them were in CELLS (`size=3`, `db > res`), which meant the detector asked a different
question at every resolution. Left alone, moving to a fine grid inflated total neck area
3.5x — an apparent improvement that was pure grid artefact.
"""
import os

import numpy as np
import pytest

pytest.importorskip("scipy")
pytest.importorskip("rasterio")

from moose_scout import terrain


@pytest.fixture(autouse=True)
def _fine_on(monkeypatch):
    """These tests are about the fine grid, so they turn it on. The default-off
    behaviour has its own test above."""
    monkeypatch.setenv("FINE_NECKS", "1")


def _lakes_with_a_neck(res, neck_m, span_m=8000.0):
    """Two big land masses joined ONLY by a neck of `neck_m`, rasterized at `res`.

    This used to be two water bars with a uniform strip of land between them, which is
    not a neck at all — it is a corridor, and its "sides" were 0.16 km2 slivers. The
    linkage test (test_funnel_linkage.py) rightly threw the whole thing out. A fixture
    for measuring neck WIDTH still has to be a real bottleneck, or it is measuring
    something the model no longer believes in.
    """
    n = int(span_m / res)
    b = np.zeros((n, n), bool)
    y0, y1 = int(n * 0.45), int(n * 0.55)
    b[y0:y1, :] = True                                   # water spanning the box...
    half = max(1, int(round(neck_m / res / 2)))
    c = n // 2
    b[y0:y1, c - half: c + half] = False                 # ...except the neck
    return b


# ------------------------------------------------------- the constants are in metres


def _measured(res, neck_m):
    _c, w = terrain._constriction(_lakes_with_a_neck(res, neck_m), res)
    vals = w[np.isfinite(w)]
    return float(np.median(vals)) if vals.size else None


@pytest.mark.parametrize("neck_m", [80.0, 150.0, 300.0])
def test_a_finer_grid_measures_a_known_neck_more_accurately(neck_m):
    """THE ONE THAT MATTERS, and it is about ACCURACY, not agreement.

    Water is rasterized with `all_touched` — mandatory, or thin water disappears — so
    each shore grows by up to one cell and every neck reads about 2 cells too wide. That
    error is a fixed number of CELLS, which makes it a fixed number of METRES only once
    you fix the grid: an 80 m neck measures ~160 m at 40 m and ~100 m at 10 m. Both are
    over, but only one is usable, and at 40 m the error is as large as the neck itself.
    """
    coarse, fine = _measured(40.0, neck_m), _measured(10.0, neck_m)
    assert fine is not None, f"a {neck_m:.0f} m neck vanished at 10 m"
    assert abs(fine - neck_m) <= 0.5 * neck_m + 30.0, \
        f"a {neck_m:.0f} m neck measured {fine:.0f} m at 10 m"
    if coarse is None:
        return          # 80 m: the coarse grid cannot see it at all — the whole point
    # "No materially worse", not "strictly better". Where the coarse grid happens to
    # land near the true width the two agree to within a cell of quantization noise —
    # a 150 m neck reads 160.0 m coarse and 161.2 m fine — and demanding a strict
    # improvement there would be asserting on noise. The claim being pinned is that the
    # fine grid never trades away accuracy, and wins where the coarse grid is censoring.
    assert abs(fine - neck_m) <= abs(coarse - neck_m) + 0.5 * 40.0, \
        f"the fine grid was materially less accurate: true {neck_m}, 40 m {coarse}, 10 m {fine}"


def test_the_coarse_grid_cannot_express_a_narrow_neck_at_all():
    """The censoring this task exists to remove, stated as a fact rather than a hope.
    A real run reported four separate funnels at EXACTLY 113 m — the quantization floor,
    not the terrain. If a future change makes the 40 m grid accurate for an 80 m neck,
    this test should fail and the fine grid can be reconsidered."""
    coarse = _measured(40.0, 80.0)
    assert coarse is None or coarse >= 130.0, \
        f"40 m unexpectedly resolved an 80 m neck as {coarse:.0f} m — recheck the premise"


def test_a_narrow_neck_is_invisible_at_the_analysis_grid_and_visible_below_it():
    """The finding this task exists for: an 80 m neck cannot be MEASURED on a 40 m grid,
    and comes back either absent or badly wrong. It must be right on a fine grid."""
    fine_c, fine_w = terrain._constriction(_lakes_with_a_neck(8.0, 80.0), 8.0)
    vals = fine_w[np.isfinite(fine_w)]
    assert vals.size, "an 80 m neck was not detected even at 8 m"
    assert 40.0 <= float(np.median(vals)) <= 130.0, \
        f"an 80 m neck measured {float(np.median(vals)):.0f} m"


def test_a_neck_is_strongest_where_it_is_tightest():
    c, _ = terrain._constriction(_lakes_with_a_neck(10.0, 120.0), 10.0)
    wide, _ = terrain._constriction(_lakes_with_a_neck(10.0, 550.0), 10.0)
    assert c.max() > wide.max(), "a 120 m pinch did not outscore a 550 m one"


def test_open_ground_has_no_necks():
    c, w = terrain._constriction(np.zeros((200, 200), bool), 20.0)
    assert c.max() == 0.0 and not np.isfinite(w).any()


# ------------------------------------------------------------------ the grid contract


def test_the_fine_grid_is_off_until_a_real_ab_says_the_new_funnel_count_is_right(monkeypatch):
    """The measurement is proven; the population effect is not. See _fine_res.

    monkeypatch rather than a hand-rolled save/restore: the restore only runs if the
    assert passes, so a failure here would have leaked the flag into every later test.
    That is the T0.4 bug in miniature."""
    monkeypatch.delenv("FINE_NECKS", raising=False)
    assert terrain._fine_res(40.0, (452, 453)) == 40.0


def test_the_fine_grid_is_a_whole_number_of_analysis_cells():
    """The fine grid nests inside the analysis grid so terrain can fold it back by
    reshape. A ragged ratio would mean resampling a measurement, which is how a peak
    statistic quietly becomes an average one."""
    for shape in [(452, 453), (1008, 1011), (2400, 2400), (100, 100)]:
        for res in (20.0, 40.0):
            f = terrain._fine_res(res, shape)
            k = res / f
            assert abs(k - round(k)) < 1e-9, f"ratio {k} at {shape} / {res} m"
            assert f <= res


def test_the_fine_grid_respects_the_memory_budget():
    """A 70 km box at 40 m is 1750^2; a naive 4x fine grid is 49 M cells carried through
    a float64 distance transform, which does not fit in the worker."""
    shape = (1750, 1750)
    f = terrain._fine_res(40.0, shape)
    cells = (shape[0] * 40.0 / f) * (shape[1] * 40.0 / f)
    assert cells <= terrain.FINE_BUDGET_PX * 1.001, f"{cells:.0f} cells at {f} m"


def test_a_tiny_box_does_not_grind_below_the_useful_limit():
    """Past ~5 m the water vectors have nothing more to say, and the extra cells buy
    only time."""
    assert terrain._fine_res(40.0, (60, 60)) >= terrain.FINEST_M


def test_block_reduce_keeps_the_tightest_neck_and_the_strongest_score():
    fine = np.array([[1.0, 9.0, 2.0, 2.0],
                     [3.0, 4.0, 2.0, 2.0],
                     [5.0, 5.0, 7.0, 7.0],
                     [5.0, 5.0, 7.0, 7.0]], dtype="float32")
    assert terrain._block_reduce(fine, 2, "max", (2, 2)).tolist() == [[9.0, 2.0], [5.0, 7.0]]
    assert terrain._block_reduce(fine, 2, "min", (2, 2)).tolist() == [[1.0, 2.0], [5.0, 7.0]]


def test_block_reduce_min_ignores_the_not_a_neck_cells():
    """Width is NaN wherever there is no neck. A single NaN must not blank the parent
    cell — that would delete every neck that does not fill its whole 40 m square."""
    fine = np.array([[np.nan, 180.0], [np.nan, np.nan]], dtype="float32")
    out = terrain._block_reduce(fine, 2, "min", (1, 1))
    assert out[0, 0] == pytest.approx(180.0)
    allnan = terrain._block_reduce(np.full((2, 2), np.nan, "float32"), 2, "min", (1, 1))
    assert not np.isfinite(allnan[0, 0])


# ------------------------------------------------------------- prominence vs the tpi


def test_glassing_reads_prominence_and_rescales_for_it():
    """The prominence layer is a PEAK, so the same knob reads ~1.5x higher in metres
    than the cell mean did. Feeding it to the old /30 divisor would have pushed the
    same cells back into the saturation that audit #56 removed — a resolution upgrade
    silently re-breaking the calibration it was meant to help."""
    import inspect

    from moose_scout import synth
    src = inspect.getsource(synth)
    assert 'terrain/prominence.tif' in src
    assert "45.0 if prom_is_peak else 30.0" in src


def test_wetness_keeps_the_coarse_tpi():
    """`wet` and the habitat surface want the cell's TYPICAL position, not its highest
    corner. Pointing them at a peak statistic would make every knob edge read dry."""
    import inspect

    src = inspect.getsource(terrain.run)
    wet_line = [l for l in src.split("\n") if l.strip().startswith("wet = ")]
    assert wet_line and "prominence" not in wet_line[0], wet_line
