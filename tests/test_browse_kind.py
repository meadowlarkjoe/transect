"""Browse is named for what the animal eats, not for what found it (T10.4, browse half).

Asked: "Im more curious about the TYPE of browse (aquatic vegetation, regen (prime),
regen (new), regen (closing), specific species of vegetation that moose like)... I want
the legend to show things that hunters actually care about and not rely on them to have
to evaluate the relative quality of a data source. this is true for everything we show."

The legend split browse into "from dated cuts", "from dated burns", "from the stand map",
"from satellite land cover" — pure provenance, and provenance is the ENGINE's business.
Ranking those sources is a job rev 21 already did; handing the result to the reader to
interpret is the error.

WHAT IS NOT HERE, AND WHY: named species. The écoforestière stand map carries résineux /
mélange / feuillus CLASSES, not species. Calling a polygon "willow" because it is feuillus
would be inventing precision, so the deciduous kind says what the data actually says.
"""
import numpy as np
import pytest

pytest.importorskip("rasterio")

from moose_scout.contract import KIND_MIN_SHARE, _browse_kind


def _grid(fill=0.0, shape=(10, 10)):
    return np.full(shape, fill, dtype="float64")


def _inside(frac=1.0, shape=(10, 10)):
    m = np.zeros(shape, bool)
    n = int(round(frac * shape[0] * shape[1]))
    m.flat[:n] = True
    return m


def test_aquatic_outranks_everything():
    """Sodium feeding is its own behaviour at its own time of day, so it wins even on
    ground that is also a prime-aged cut."""
    assert _browse_kind(90, _inside(), _grid(2010), None, None, 2026) == "aquatic"


def test_a_dated_disturbance_gives_the_stage():
    for year, expect in ((2020, "regen_new"), (2010, "regen_prime"), (1995, "regen_closing")):
        assert _browse_kind(20, _inside(), _grid(year), None, None, 2026) == expect


def test_ground_disturbed_beyond_forty_years_is_not_regen_at_all():
    """It reads like mature forest — claiming otherwise is the thing that makes a browse
    layer untrustworthy."""
    assert _browse_kind(20, _inside(), _grid(1970), None, None, 2026) is None


def test_the_most_recent_disturbance_is_the_live_one():
    """Ground that burned in 1990 and was cut in 2020 is a new cut, not closing regen."""
    assert _browse_kind(20, _inside(), _grid(2020), _grid(1990), None, 2026) == "regen_new"


def test_a_disturbance_must_actually_cover_the_ground():
    """THE BUG THIS CAUGHT. Without a share test a polygon clipping a single burned cell
    was named by that cell — and on the fire_lake box every zone came back "regen prime",
    which is precision the data has not got."""
    cut = _grid(0.0)
    cut.flat[:5] = 2010                      # 5% of a 100-cell zone
    assert _browse_kind(20, _inside(), cut, None, None, 2026) is None
    cut = _grid(0.0)
    cut.flat[:50] = 2010                     # 50%, comfortably over the bar
    assert _browse_kind(20, _inside(), cut, None, None, 2026) == "regen_prime"


def test_the_share_bar_is_a_share_of_the_ZONE_not_of_the_raster():
    """A zone covering a tenth of the box must be judged on its own ten cells."""
    cut = _grid(0.0)
    cut.flat[:10] = 2010
    assert _browse_kind(20, _inside(0.1), cut, None, None, 2026) == "regen_prime"


def test_the_stand_map_only_speaks_when_nothing_dated_does():
    """Ranked below a dated disturbance on purpose — 'Beats the satellite, loses to a
    dated disturbance' was already the model's ordering."""
    stand = _grid(3.0)                       # feuillus everywhere
    assert _browse_kind(20, _inside(), _grid(2010), None, stand, 2026) == "regen_prime"
    assert _browse_kind(20, _inside(), None, None, stand, 2026) == "deciduous"


def test_conifer_is_not_browse():
    """Code 1 is résineux. A spruce stand is cover, not food."""
    assert _browse_kind(20, _inside(), None, None, _grid(1.0), 2026) is None


def test_a_zone_with_nothing_under_it_keeps_its_land_cover_name():
    assert _browse_kind(20, _inside(), None, None, None, 2026) is None
    assert _browse_kind(20, None, _grid(2010), None, None, 2026) is None


def test_the_share_threshold_is_a_named_constant():
    assert 0.2 <= KIND_MIN_SHARE <= 0.6


def test_the_rasters_are_converted_once_not_per_polygon():
    """`np.nan_to_num(arr)` inside the per-polygon helper copied the whole raster on
    every call. Three rasters times up to 32 polygons on a 6.5 Mpx box is gigabytes of
    copies — measured, the worker died outright (exit 137). The same defect was already
    there for the two provenance rasters and is fixed with it."""
    import inspect
    from moose_scout import contract
    src = inspect.getsource(contract._browse_kind)
    assert "nan_to_num" not in src, "the classifier converts per polygon again"
    zones = inspect.getsource(contract._browse_zones)
    for name in ("codes = src_r[inside]", "a = agr_r[inside]"):
        assert name in zones, "a provenance raster is converted per polygon again"
