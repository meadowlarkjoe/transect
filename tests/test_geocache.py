"""Gates on the geography-keyed acquire cache (#79).

The dangerous failure here is not a cache miss — it is a cache HIT that hands one
job's work to another. So these tests care most about what may be shared and when
two boxes are allowed to be considered the same box.
"""
import os
from pathlib import Path

from moose_scout import geocache


# THE REAL AOI, NOT A STUB. The stub used to carry `center` and `bbox_halfwidth_km` and
# nothing else, which was fine right up until the key started reading `bbox_wgs84()` —
# then every test here failed on a test double that had quietly stopped resembling the
# thing it doubled. A cache key is exactly the wrong place to be testing a lookalike.
from moose_scout.config import AOI, LatLon, SeasonCfg  # noqa: E402


def _aoi(lat=47.815, lon=-78.456, rad=14.0, ring=None):
    return AOI(name="t", center=LatLon(lat=lat, lon=lon), bbox_halfwidth_km=rad,
               ring=ring, season=SeasonCfg(year=2026, target_dates=["2026-10-01", "2026-10-10"]))


class _Model:
    def __init__(self, res=40.0, crs="EPSG:32198"):
        self.raster_resolution_m = res
        self.working_crs = crs


class _Ctx:
    def __init__(self, lat=47.815, lon=-78.456, rad=14.0, res=40.0, crs="EPSG:32198",
                 ring=None):
        self.aoi = _aoi(lat, lon, rad, ring)
        self.model = _Model(res, crs)


def test_key_is_stable_for_the_same_box():
    assert geocache.key(_Ctx()) == geocache.key(_Ctx())


def test_key_changes_with_every_input_that_changes_the_data():
    base = geocache.key(_Ctx())
    assert geocache.key(_Ctx(lat=47.9)) != base, "moving the box must miss"
    assert geocache.key(_Ctx(lon=-78.9)) != base, "moving the box must miss"
    assert geocache.key(_Ctx(rad=20.0)) != base, "a bigger box needs more data"
    assert geocache.key(_Ctx(res=20.0)) != base, "a finer grid is a different raster"
    assert geocache.key(_Ctx(crs="EPSG:3979")) != base, "a different CRS is a different grid"


def test_key_ignores_a_sub_metre_nudge():
    """4 dp is ~11 m — well under any resolution we analyse at, so a box dragged by a
    pixel on screen must still hit rather than trigger a fresh multi-minute fetch."""
    assert geocache.key(_Ctx(lat=47.81500)) == geocache.key(_Ctx(lat=47.815001))


def test_artifacts_are_only_ever_acquire_outputs():
    """The allowlist must never grow a DERIVED layer. `access_unknown.flag` is the
    cautionary example: it looks like source data and is actually one hunter's
    reachability verdict, so sharing it would leak that verdict to the next job."""
    root = Path(__file__).resolve().parent.parent / "src" / "moose_scout"
    banned = []
    for name in geocache.ARTIFACTS:
        writers = set()
        for py in root.rglob("*.py"):
            if py.name == "geocache.py":
                continue
            txt = py.read_text()
            # a real writer names the file next to a write call
            for pat in (f'ru.write(cache / "{name}"', f'ru.write(c / "{name}"',
                        f'(cache / "{name}").write_text', f'(cache / "{name}").write_bytes',
                        f'to_file(cache / "{name}"', f'"{name}", "w"'):
                if pat in txt:
                    writers.add(py)
        outside = [w for w in writers if "acquire" not in str(w)]
        if outside:
            banned.append((name, [w.name for w in outside]))
    assert not banned, f"shared artifacts written outside acquire/: {banned}"


def test_publish_then_restore_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    monkeypatch.setenv("GEOCACHE", "1")
    ctx = _Ctx()
    job1 = tmp_path / "job_a"
    job1.mkdir()
    (job1 / "dem.tif").write_bytes(b"elevation")
    (job1 / "roads.gpkg").write_bytes(b"roads")
    (job1 / "hsm.tif").write_bytes(b"DERIVED - must not travel")

    put = geocache.publish(ctx, job1)
    assert set(put) == {"dem.tif", "roads.gpkg"}

    job2 = tmp_path / "job_b"
    job2.mkdir()
    got = geocache.restore(ctx, job2)
    assert set(got) == {"dem.tif", "roads.gpkg"}
    assert (job2 / "dem.tif").read_bytes() == b"elevation"
    assert not (job2 / "hsm.tif").exists(), "a derived layer must never be shared"


def test_a_different_box_does_not_see_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    job1 = tmp_path / "job_a"
    job1.mkdir()
    (job1 / "dem.tif").write_bytes(b"elevation")
    geocache.publish(_Ctx(), job1)

    job2 = tmp_path / "job_b"
    job2.mkdir()
    assert geocache.restore(_Ctx(lat=50.0), job2) == []
    assert not (job2 / "dem.tif").exists()


def test_restore_never_clobbers_a_layer_the_job_already_has(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    ctx = _Ctx()
    job1 = tmp_path / "job_a"
    job1.mkdir()
    (job1 / "dem.tif").write_bytes(b"from the store")
    geocache.publish(ctx, job1)

    job2 = tmp_path / "job_b"
    job2.mkdir()
    (job2 / "dem.tif").write_bytes(b"freshly fetched")
    geocache.restore(ctx, job2)
    assert (job2 / "dem.tif").read_bytes() == b"freshly fetched"


def test_shared_copies_are_read_only(tmp_path, monkeypatch):
    """Nothing may write THROUGH a shared hardlink into another job's cache."""
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    ctx = _Ctx()
    job1 = tmp_path / "job_a"
    job1.mkdir()
    (job1 / "dem.tif").write_bytes(b"elevation")
    geocache.publish(ctx, job1)
    stored = geocache.slot(ctx) / "dem.tif"
    assert not (stored.stat().st_mode & 0o222), "store must be read-only"


def test_off_switch_disables_both_directions(tmp_path, monkeypatch):
    monkeypatch.setenv("MOOSE_SCOUT_CACHE", str(tmp_path))
    monkeypatch.setenv("GEOCACHE", "0")
    ctx = _Ctx()
    job1 = tmp_path / "job_a"
    job1.mkdir()
    (job1 / "dem.tif").write_bytes(b"elevation")
    assert geocache.publish(ctx, job1) == []
    job2 = tmp_path / "job_b"
    job2.mkdir()
    assert geocache.restore(ctx, job2) == []


# ---------------------------------------------------------------- drawn AOIs (T10.8)

_RING = [(-78.50, 47.80), (-78.44, 47.80), (-78.44, 47.84), (-78.50, 47.84),
         (-78.50, 47.80)]


def test_a_drawn_aoi_keys_on_its_own_box_not_on_a_leftover_radius():
    """THE BUG THE OLD KEY WOULD HAVE HAD. A drawn AOI takes its extent from its padded
    ring and carries whatever `bbox_halfwidth_km` the slider happened to hold — so on the
    old centre+radius key, two completely different parcels drawn from the same map view
    would have collided, and `restore` hardlinks with NO shape check."""
    a = geocache.key(_Ctx(ring=_RING))
    b = geocache.key(_Ctx(ring=[(-77.50, 46.80), (-77.44, 46.80),
                                (-77.44, 46.84), (-77.50, 46.84), (-77.50, 46.80)]))
    assert a != b, "two different parcels share a cache slot"


def test_a_drawn_aoi_ignores_the_radius_it_is_not_using():
    """The converse: the same ring with a different stored radius is the same analysis
    box, so it must HIT. Otherwise every slider nudge throws away a warm cache."""
    assert geocache.key(_Ctx(rad=14.0, ring=_RING)) == geocache.key(_Ctx(rad=40.0, ring=_RING))


def test_a_drawn_aoi_and_a_radius_aoi_never_collide():
    assert geocache.key(_Ctx(ring=_RING)) != geocache.key(_Ctx())


def test_the_padding_is_part_of_the_key():
    """The cache holds rasters on the PADDED grid. Two runs that pad differently are not
    looking at the same ground, however similar the drawing."""
    c1, c2 = _Ctx(ring=_RING), _Ctx(ring=_RING)
    c2.aoi = c2.aoi.model_copy(update={"pad_km": 5.0})
    assert geocache.key(c1) != geocache.key(c2)
