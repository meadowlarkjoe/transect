"""Native-resolution class fractions (#77/#78).

The claim being tested is specific: aggregating a fine categorical raster into a coarse
analysis grid by AREAL FRACTION preserves the sub-cell mixture that nearest-neighbour
sampling destroys. If that stops being true the habitat model's dominant term quietly
degrades, with nothing visibly broken — so it gets a test.
"""
import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from moose_scout import rasterio_utils as ru


def _src(tmp_path, arr, res=10.0, origin=(0.0, 1000.0), crs="EPSG:32198"):
    from rasterio.transform import from_origin
    p = tmp_path / "src.tif"
    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1,
            "height": arr.shape[0], "width": arr.shape[1], "crs": crs,
            "transform": from_origin(origin[0], origin[1], res, res), "nodata": 0}
    with rasterio.open(p, "w", **prof) as d:
        d.write(arr.astype("uint8"), 1)
    return p


def _dst_grid(W, H, res=40.0, origin=(0.0, 1000.0)):
    from rasterio.transform import from_origin
    return "EPSG:32198", from_origin(origin[0], origin[1], res, res), W, H


def test_half_and_half_cell_reads_as_half(tmp_path):
    """A 40 m cell covering 10 m pixels that are half tree, half shrub must report
    0.5/0.5 — the exact case nearest-neighbour resolves as a coin flip."""
    fine = np.full((4, 4), 20, dtype="uint8")     # shrub
    fine[:, :2] = 10                              # left half tree
    src_p = _src(tmp_path, fine)
    crs, tr, W, H = _dst_grid(1, 1)
    with rasterio.open(src_p) as s:
        frac, seen = ru.class_fractions(s, [10, 20], crs, tr, W, H,
                                        _bounds_wgs84(src_p))
    assert seen[0, 0]
    assert frac[10][0, 0] == pytest.approx(0.5, abs=0.02)
    assert frac[20][0, 0] == pytest.approx(0.5, abs=0.02)


def test_fractions_sum_to_one_over_a_full_classification(tmp_path):
    rng = np.random.default_rng(0)
    fine = rng.choice([10, 20, 30, 80], size=(40, 40)).astype("uint8")
    src_p = _src(tmp_path, fine)
    crs, tr, W, H = _dst_grid(10, 10)
    with rasterio.open(src_p) as s:
        frac, seen = ru.class_fractions(s, [10, 20, 30, 80], crs, tr, W, H,
                                        _bounds_wgs84(src_p))
    total = sum(frac[k] for k in (10, 20, 30, 80))
    assert np.allclose(total[seen], 1.0, atol=0.05)


def test_a_minority_class_survives(tmp_path):
    """One tree pixel in sixteen is 6 % tree, not 0 % — and 'not 0' is the whole point:
    nearest-neighbour would drop it entirely unless it happened to be the sampled pixel."""
    fine = np.full((4, 4), 20, dtype="uint8")
    fine[0, 0] = 10
    src_p = _src(tmp_path, fine)
    crs, tr, W, H = _dst_grid(1, 1)
    with rasterio.open(src_p) as s:
        frac, _ = ru.class_fractions(s, [10, 20], crs, tr, W, H, _bounds_wgs84(src_p))
    assert 0.0 < frac[10][0, 0] < 0.25


def test_tiling_does_not_change_the_answer(tmp_path):
    """#76: the tiled path exists to bound memory, not to change results. A one-row
    budget must produce exactly what an unbounded pass produces."""
    rng = np.random.default_rng(7)
    fine = rng.choice([10, 20], size=(64, 64)).astype("uint8")
    src_p = _src(tmp_path, fine)
    crs, tr, W, H = _dst_grid(16, 16)
    with rasterio.open(src_p) as s:
        big, _ = ru.class_fractions(s, [10, 20], crs, tr, W, H, _bounds_wgs84(src_p),
                                    budget_px=10 ** 9)
    with rasterio.open(src_p) as s:
        tiny, _ = ru.class_fractions(s, [10, 20], crs, tr, W, H, _bounds_wgs84(src_p),
                                     budget_px=1)
    assert np.allclose(big[10], tiny[10], atol=1e-6)
    assert np.allclose(big[20], tiny[20], atol=1e-6)


def test_interspersion_is_higher_than_the_categorical_estimate(tmp_path):
    """The point of the change, stated as a measurement: a finely interleaved mosaic
    has real sub-cell edge that the categorical map cannot express."""
    fine = np.indices((40, 40))[1] % 2 * 10 + 10        # alternating 10/20 columns
    src_p = _src(tmp_path, fine.astype("uint8"))
    crs, tr, W, H = _dst_grid(10, 10)
    with rasterio.open(src_p) as s:
        frac, seen = ru.class_fractions(s, [10, 20], crs, tr, W, H, _bounds_wgs84(src_p))
    p = frac[10]
    sub = np.clip(4 * p * (1 - p), 0, 1)
    assert sub[seen].mean() > 0.9, "a 50/50 interleave is maximal interspersion"


def _bounds_wgs84(path):
    from rasterio.warp import transform_bounds
    with rasterio.open(path) as s:
        return transform_bounds(s.crs, "EPSG:4326", *s.bounds)


def test_geographic_source_into_metric_grid_stays_bounded(tmp_path):
    """THE BUG THIS EXISTS FOR: the source was EPSG:4326 (degrees) and the analysis grid
    metric, so comparing their pixel sizes directly overstated the ratio by ~10,000x.
    The block factor went absurd, the row budget collapsed to one, and the container was
    OOM-killed — a change meant to RAISE the resolution ceiling lowered it instead.

    A degrees-in / metres-out call must produce sane fractions without exploding."""
    from rasterio.transform import from_origin
    deg = 8.333e-5                                  # ~10 m at the equator
    fine = np.indices((240, 240))[1] % 2 * 10 + 10  # alternating classes
    p = tmp_path / "geo.tif"
    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": 240, "width": 240,
            "crs": "EPSG:4326", "transform": from_origin(-79.0, 48.0, deg, deg),
            "nodata": 0}
    with rasterio.open(p, "w", **prof) as d:
        d.write(fine.astype("uint8"), 1)

    from rasterio.warp import transform_bounds
    with rasterio.open(p) as s:
        wgs = transform_bounds(s.crs, "EPSG:4326", *s.bounds)
        l, b, r, t = transform_bounds("EPSG:4326", "EPSG:32198", *wgs)
        W = H = 15                                   # ~40 m cells over the same ground
        tr = from_origin(l, t, (r - l) / W, (t - b) / H)
        frac, seen = ru.class_fractions(s, [10, 20], "EPSG:32198", tr, W, H, wgs)

    assert seen.any(), "a fully overlapping source must produce coverage"
    tot = frac[10] + frac[20]
    assert np.allclose(tot[seen], 1.0, atol=0.1)
    assert 0.2 < float(frac[10][seen].mean()) < 0.8, "a 50/50 interleave must read near half"
