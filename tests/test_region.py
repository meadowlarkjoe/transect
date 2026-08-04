"""E2 — region resolver + coverage manifest.

Pure, geo-free checks (bbox math + yaml load), so they run in a bare clone.
"""
from moose_scout.region import (
    SUPPORTED_REGIMES,
    coverage_manifest,
    load_region,
    regime_supported,
    source_covers_aoi,
)


def test_quebec_profiles_load_and_are_supported():
    for prof in ("quebec_boreal", "quebec_mixedwood"):
        r = load_region(prof)
        assert r["region_profile"] == prof
        assert r["legal_regime"] in SUPPORTED_REGIMES
        assert regime_supported(r)
        assert r["sources"], "a region must declare its data sources"


def test_unknown_profile_falls_back_to_quebec_regime_no_sources():
    r = load_region("idaho_panhandle")
    # No silent foreign law: fall back to the Québec regime with NO declared sources
    # so the manifest is empty rather than wrong.
    assert r["legal_regime"] == "quebec"
    assert r["sources"] == []


def test_source_covers_aoi_hard_lat_edge():
    cov = {"max_lat": 52.0}
    assert source_covers_aoi(cov, (-67, 52.3, -66, 52.7)) == "out"      # wholly north
    assert source_covers_aoi(cov, (-67, 51.8, -66, 52.2)) == "partial"  # straddles
    assert source_covers_aoi(cov, (-72, 48.0, -71, 48.4)) == "in"       # wholly south


def test_descriptive_coverage_reads_in_bounds():
    for cov in ({"extent": "global"}, {"country": "canada"}, {"region": "quebec"}, None):
        assert source_covers_aoi(cov, (-67, 52.3, -66, 52.7)) == "in"


class _AOI:
    def __init__(self, bbox):
        self._b = bbox

    def bbox_wgs84(self):
        return self._b


class _Species:
    region_profile = "quebec_boreal"


class _Ctx:
    def __init__(self, bbox):
        self.aoi = _AOI(bbox)
        self.species = _Species()


def test_manifest_marks_ecoforestiere_fallback_north_of_52():
    # A box wholly north of the 52nd parallel: écoforestière is out, carries its caveat.
    m = coverage_manifest(_Ctx((-67.6, 52.2, -67.1, 52.5)))
    eco = next(e for e in m if e["id"] == "ecoforestiere")
    assert eco["coverage"] == "out"
    assert eco.get("note")
    # A global source is in-coverage everywhere.
    s2 = next(e for e in m if e["id"] == "sentinel2")
    assert s2["coverage"] == "in"


def test_manifest_all_in_for_southern_box():
    m = coverage_manifest(_Ctx((-72.0, 48.0, -71.5, 48.3)))
    assert all(e["coverage"] == "in" for e in m)
