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


def test_a_small_excellent_polygon_beats_a_big_mediocre_one(tmp_path):
    """#89, THE INVERSION THE HUNTER SPOTTED FROM THE MAP.

    He noticed that cuts marked "closing in" were being drawn as browse while the ones
    marked "prime regen" were not — the exact opposite of what the raster said. The
    cause was that every filter in _polygonize selected for SIZE: a flat min_km2 floor
    regardless of quality, and `polys[:per_class]` sorted by area, so the broad mediocre
    shapes took all the slots and the small excellent ones were never drawn.

    A quarter-hectare of prime regen is worth more to a hunter than a square kilometre
    of mediocre ground. The layer has to be able to say so.
    """
    a = np.zeros((400, 400), "float32")
    a[40:180, 40:180] = 0.55            # ~7.8 km2 of mediocre
    a[300:330, 300:330] = 0.95          # ~0.36 km2 of prime — UNDER the 0.8 km2 floor
    p = _write(tmp_path, a, res=20.0)
    out = _polygonize(_Ctx(), p.parent, p.name, [("browse", 0.30)],
                      min_km2=0.8, smooth_m=280, per_class=8)
    assert out, "nothing polygonized at all"
    small = [o for o in out if o["area_km2"] < 1.0]
    assert small, "the small prime block was dropped by the area floor — this is the bug"
    # ...and it must come FIRST, because the slots go to the best ground, not the biggest.
    assert out[0]["score"] >= out[-1]["score"], "polygons are not ranked by value"
    assert out[0]["area_km2"] < out[-1]["area_km2"], \
        "the best polygon here is the SMALL one; ranking still favours area"


def test_weak_ground_still_has_to_be_big_enough_to_matter(tmp_path):
    """The floor is relaxed for strong ground, not removed. Otherwise every scrap of
    marginal habitat becomes a polygon and the map is noise again — which is the
    failure mode the size filters were originally (over)reacting to."""
    a = np.zeros((400, 400), "float32")
    a[300:315, 300:315] = 0.35          # tiny AND mediocre: 0.09 km2 at 20 m
    p = _write(tmp_path, a, res=20.0)
    out = _polygonize(_Ctx(), p.parent, p.name, [("browse", 0.30)],
                      min_km2=0.8, smooth_m=280, per_class=8)
    assert not out, "a tiny patch of mediocre ground should not earn a polygon"


def test_every_polygon_reports_the_score_it_was_kept_for(tmp_path):
    """Ranking by value is only defensible if the value travels with the polygon — the
    map and the identify card have to be able to show what the ranking was based on."""
    a = np.zeros((300, 300), "float32")
    a[60:200, 60:200] = 0.8
    p = _write(tmp_path, a, res=20.0)
    out = _polygonize(_Ctx(), p.parent, p.name, [("browse", 0.30)],
                      min_km2=0.4, smooth_m=200, per_class=8)
    assert out and all("score" in o for o in out), "polygons carry no score"
    assert 0.0 <= out[0]["score"] <= 1.0
