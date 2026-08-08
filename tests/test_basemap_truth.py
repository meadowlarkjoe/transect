"""The basemap panel has to name what it is actually showing (T10.12).

Asked: "Is releif and Lidar not the same? Should we remove lidar from below?"

No, and no — and the panel was making that impossible to answer, because it was lying
about one row and blanket-denying the other:

  * RELIEF was labelled `CDEM HILLSHADE`. It is Esri's global World_Hillshade, mixed
    resolution, not a Canadian product at all. It also blurs before the imagery does,
    with nothing saying why — which reads as a broken layer rather than a real ceiling.
  * LiDAR said "NOT AVAILABLE FOR THIS AOI" on every box. That stopped being true at
    T9.10: the HRDEM mosaic is read for real and `dem_source.json` records the MEASURED
    coverage fraction, which reaches the app in the coverage manifest. Over Rouyn that is
    92.7%. "Not available" there is the same class of lie as the CDEM label.

WHAT IS DELIBERATELY STILL NOT OFFERED: selecting LiDAR as a basemap. The HRDEM COGs are
not tiles, so serving them needs an AOI-sized hillshade rendered at analysis time AND a
way to keep serving it after the geography cache is pruned — a saved plan reopened months
later must not 404 its basemap. That is T10.22. A switch that does nothing would be the
T10.10 mistake again.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _code():
    return re.sub(r"//[^\n]*", "", APP.read_text())


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


def test_relief_names_its_real_source():
    """THE LIE. It is Esri, not CDEM."""
    src = _code()
    assert "CDEM HILLSHADE" not in src, "the relief row claims to be CDEM again"
    assert "ESRI WORLD HILLSHADE" in src


def test_relief_says_why_it_stops_early():
    src = _code()
    assert "BASE_WHY" in src
    i = src.index("const BASE_WHY=")
    assert "RELIEF_MAXZ" in src[i:i + 300], \
        "the explanation hardcodes a zoom instead of naming the constant that sets it"


def test_the_explanation_actually_renders():
    """A note nobody draws is a comment."""
    body = _fn("buildBaseDock")
    assert "BASE_WHY[b]" in body


def test_the_lidar_row_reads_the_measured_coverage():
    body = _fn("baseAdds")
    assert "coverage_frac" in body
    assert "OF THIS BOX" in body


def test_it_reads_the_manifest_under_its_real_name():
    """`coverage_manifest`, not `data_manifest`. Getting this wrong is SILENT: `.find` on
    an empty array returns undefined and the row falls back to "no coverage reading",
    which looks exactly like an old plan. Caught before shipping, and only by checking
    the contract rather than trusting the name."""
    body = _fn("hrdemEntry")
    assert "DOC.coverage_manifest" in body
    assert "DOC.data_manifest" not in body


def test_a_box_with_no_lidar_says_that_rather_than_a_percentage():
    body = _fn("baseAdds")
    assert "NOT FLOWN HERE" in body


def test_an_old_plan_says_it_has_no_reading_rather_than_claiming_zero():
    """A plan computed before the HRDEM mosaic has no fraction at all. Reporting that as
    0% would be inventing a measurement."""
    body = _fn("baseAdds")
    assert "f===null" in body.replace(" ", "")
    assert "RUN PREDATES" in body


def test_the_row_never_becomes_selectable_by_accident():
    """Until T10.22 there is nothing to select. `ok:true` here would draw a live checkbox
    over a basemap that does not exist."""
    body = _fn("baseAdds")
    assert "ok:true" not in body.replace(" ", "")


def test_a_box_that_has_lidar_is_not_labelled_no_data():
    """"NO DATA" next to "1 M BARE EARTH OVER 93% OF THIS BOX" contradicts itself."""
    body = _fn("buildBaseDock")
    assert "HAVE IT" in body


def test_the_contract_still_publishes_what_this_reads():
    """The app-side half is worthless if the engine stops emitting it."""
    src = pathlib.Path("src/moose_scout/contract.py").read_text()
    assert 'e["coverage_frac"]' in src
    assert 'e["native_res_m"]' in src
    assert 'doc["coverage_manifest"] = _man' in src
