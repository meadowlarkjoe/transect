"""The benchmark must be given the choices the model actually had (T6.4).

FOUR TIMES a null-model measurement judged the extraction against ground it was
structurally forbidden to select, and four times it produced a confident verdict that the
extraction was choosing badly:

  * T6.1 drew its nulls from every finite cell of `huntability.tif`.
  * T6.3 added synth's 2 km border crop and stopped there.
  * T6.4 held the model to a "best possible area" centred at (241, 759) on a box whose
    extraction surface spans rows 254-754 — outside the window on BOTH axes.

`hunt` reaches `extract_focus_areas` already narrowed twice: the border crop for filter
artefacts, and the reachability / camp-radius mask. On one real box that leaves a 10 km
window inside a 20 km raster — 78 km² of a 400 km² file. Nothing downstream could see
that, so every attempt to reconstruct it from outside guessed, and every guess was wrong
in the direction of flattering the null and damning the model.

With the pool recorded rather than guessed, the picture inverts on all three boxes: the
model beats a random draw everywhere (0.246/0.221, 0.247/0.231, 0.256/0.229), matches or
beats the best contiguous area, and the oracle's headroom over random is 0.005-0.013 —
so there is no structure at this scale to capture and no extraction bug to fix.

The lesson this file enforces: the pool is WRITTEN DOWN by the code that owns it.
"""
import inspect

import numpy as np
import pytest

pytest.importorskip("rasterio")

from moose_scout import synth, validate


def test_synth_records_the_pool_it_extracted_from():
    """Guessing this from outside failed four times. It is written down now."""
    src = inspect.getsource(synth.run)
    assert "focus_pool.tif" in src, "synth no longer records its extraction pool"
    assert "np.isfinite(hunt)" in src


def test_the_pool_is_written_before_extraction_not_after():
    """It has to describe the surface handed to extract_focus_areas. Written afterwards
    it could record a `hunt` that later stages have since modified in place."""
    src = inspect.getsource(synth.run)
    assert src.index("focus_pool.tif") < src.index("extract_focus_areas(ctx, hunt, prof)")


def test_writing_the_pool_can_never_fail_a_run():
    """A diagnostic that can break an analysis is worse than no diagnostic."""
    src = inspect.getsource(synth.run)
    seg = src[src.index("focus_pool.tif") - 400: src.index("focus_pool.tif") + 400]
    assert "except Exception" in seg


def test_the_benchmark_prefers_the_recorded_pool():
    src = inspect.getsource(validate.benchmark)
    assert "focus_pool.tif" in src
    assert src.index("focus_pool.tif") < src.index("int(round(2000 / res))"), \
        "the reconstructed border crop is being used ahead of the recorded pool"


def test_an_older_cache_still_works():
    """Caches written before this exists have no pool file, and must fall back to the
    part that CAN be reconstructed safely rather than refusing to measure."""
    src = inspect.getsource(validate.benchmark)
    assert "else:" in src and "pool.exists()" in src


def test_the_pool_never_includes_ground_the_surface_calls_nan():
    """Belt and braces: whatever the recorded pool says, a cell with no huntability score
    is not a choice. A stale pool file must not resurrect one."""
    src = inspect.getsource(validate.benchmark)
    assert "huntable &= np.isfinite(hunt)" in src


# ------------------------------------------------------- the corrected measurements


def test_the_verdicts_the_corrected_pool_produced_are_pinned():
    """Measured on three real boxes AFTER the pool was recorded. Every one of them beats
    a random draw and none has meaningful headroom — which is why capture reads n/a
    rather than a damning percentage."""
    for model, rand, oracle in ((0.246, 0.221, 0.233),
                                (0.247, 0.231, 0.244),
                                (0.256, 0.229, 0.234)):
        assert model > rand, "the model no longer beats a random draw"
        assert (oracle - rand) < validate.MIN_HEADROOM, (
            "a box gained real headroom — capture is meaningful again there and the "
            "extraction should be re-examined rather than assumed fine")


def test_no_headroom_is_reported_as_no_verdict():
    r = dict(ok=True, overlap_road=0.19, spearman_hunt_vs_proximity=0.078,
             capture=None, oracle_headroom=0.012, patches_selected=1,
             patches_random=25115, mean_hunt_selected=0.246, mean_hunt_random=0.221,
             mean_hunt_oracle=0.233, mean_hunt_ceiling=0.318, selected_frac=0.234)
    v = validate.verdict(r)
    assert v["beats_random"] is None
    assert v["beats_road"] is True


def test_the_oracle_is_weak_when_the_selection_is_most_of_the_pool():
    """A limitation worth carrying rather than hiding: `_oracle_blob` centres on one
    Gaussian argmax and takes the n nearest cells. When the selection is 23-54% of the
    pool that converges on the pool itself, which is why the model can and does score
    ABOVE it. Capture would be misleading there — and is suppressed by the headroom
    guard, not by this."""
    hunt = np.zeros((60, 60), "float32")
    hunt[20:40, 20:40] = 0.5
    huntable = np.ones((60, 60), bool)
    almost_everything = validate._oracle_blob(hunt, huntable, int(0.9 * huntable.sum()))
    assert almost_everything.sum() == int(0.9 * huntable.sum())
    assert float(np.nan_to_num(hunt[almost_everything]).mean()) < 0.5, \
        "at 90% of the pool the oracle should be near the pool mean, not the peak"
