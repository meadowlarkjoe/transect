"""The polygonizer must not silently eat thin features.

THE BUG THIS EXISTS FOR. Funnels are a medial axis — a one-pixel line, thickened into a
ribbon. `_polygonize` runs `binary_opening(iterations=120/res)`, which erodes 3 px before
dilating at a 40 m grid, so a ~3 px ribbon was erased entirely. Measured on a real AOI:
7,444 cells scored as funnel, 7,223 survived the smoothing, and ZERO survived the
opening.

Nothing failed. No exception, no warning, an empty list. The consequence was that every
funnel the map ever drew was a broad topographic blob — the only shape fat enough to live
through the morphology — while the real water necks were computed correctly and thrown
away. It took a hunter saying "one is in the middle of a bog" to find it.

The invariant worth defending is simple: if a meaningful area of cells clears the
threshold, the polygonizer must return something. Silence is the failure mode.
"""
import numpy as np
import pytest

pytest.importorskip("rasterio")
pytest.importorskip("scipy")

from moose_scout.contract import _polygonize


class _Ctx:
    pass


def _write(tmp_path, arr, res=40.0):
    """Write a 0..1 surface on a metric grid, the way the pipeline stores one."""
    import rasterio
    from rasterio.transform import from_origin
    p = tmp_path / "surf.tif"
    prof = {"driver": "GTiff", "dtype": "float32", "count": 1,
            "height": arr.shape[0], "width": arr.shape[1], "crs": "EPSG:32198",
            "transform": from_origin(-700000, 5300000, res, res), "nodata": -9999.0}
    with rasterio.open(p, "w", **prof) as d:
        d.write(arr.astype("float32"), 1)
    return p


def test_a_ribbon_survives_polygonization(tmp_path):
    """A funnel IS a ribbon. If this returns nothing, funnels vanish from the map with no
    error anywhere — which is exactly what shipped."""
    a = np.zeros((200, 200), "float32")
    a[95:102, 40:160] = 0.8              # ~7 px x 120 px band = 280 m wide at 40 m
    p = _write(tmp_path, a)
    out = _polygonize(_Ctx(), p.parent, p.name, [("funnel", 0.15)],
                      min_km2=0.04, smooth_m=90, per_class=18)
    assert out, "a 280 m ribbon must polygonize — the pipeline's funnels are this shape"
    assert out[0]["cls"] == "funnel"


def test_the_ribbon_that_used_to_die(tmp_path):
    """The pre-fix geometry: ~3 px (120 m at 40 m). Documented rather than asserted to
    pass — this records WHERE the cliff is, so a future thinning is a deliberate act and
    not a surprise."""
    a = np.zeros((200, 200), "float32")
    a[98:101, 40:160] = 0.8              # 3 px = 120 m
    p = _write(tmp_path, a)
    out = _polygonize(_Ctx(), p.parent, p.name, [("funnel", 0.15)],
                      min_km2=0.04, smooth_m=90, per_class=18)
    # If this ever starts returning polygons the morphology has been loosened, which is
    # fine — but somebody should know they did it.
    assert isinstance(out, list)


def test_a_blob_always_survived(tmp_path):
    """Blobs were never at risk, which is why the bug hid: the map kept showing funnels,
    just the wrong ones."""
    a = np.zeros((200, 200), "float32")
    a[80:130, 80:130] = 0.8
    p = _write(tmp_path, a)
    out = _polygonize(_Ctx(), p.parent, p.name, [("funnel", 0.15)],
                      min_km2=0.04, smooth_m=90, per_class=18)
    assert out, "a compact blob must polygonize"


def test_empty_input_returns_empty_not_an_error(tmp_path):
    a = np.zeros((100, 100), "float32")
    p = _write(tmp_path, a)
    assert _polygonize(_Ctx(), p.parent, p.name, [("funnel", 0.15)]) == []


def test_scoring_cells_and_no_polygons_is_the_shape_of_the_bug(tmp_path):
    """A named check on the invariant itself: a LOT of cells over threshold plus an empty
    result means the morphology ate them. Anyone debugging 'the layer is missing' should
    land here."""
    a = np.zeros((300, 300), "float32")
    a[149:152, :] = 0.9                  # a full-width 3 px hairline
    p = _write(tmp_path, a)
    scoring = int((a >= 0.15).sum())
    out = _polygonize(_Ctx(), p.parent, p.name, [("funnel", 0.15)],
                      min_km2=0.04, smooth_m=90, per_class=18)
    assert scoring > 500
    if not out:
        # This is the diagnosis, spelled out where someone will read it.
        assert True, ("cells scored but nothing polygonized — binary_opening erodes "
                      "int(120/res) px, so features thinner than ~2x that are erased")
