"""Leased shelters are hunter PRESSURE and nothing else (T9.8).

The whole risk in this feature is one mistake: letting somebody else's cabin take
huntable ground away from the user. An abri sommaire is a lease over a building on
terres du domaine de l'État — the land around it stays crown land and stays open. So
the tests that matter here are the ones that pin what this layer must NOT touch.

The second thing pinned is the class filter. `DE_PRECS_N` carries 38 purposes and only
four are a person occupying the ground; the other 34 are wind turbines, telecom masts,
billboards and tailings ponds. A wind farm generating hunter pressure would be a
quietly wrong answer of exactly the kind that never gets caught by looking at a map.
"""
import json

import pytest

from moose_scout.acquire import baux


# ------------------------------------------------------------------ which leases count


@pytest.mark.parametrize("purpose,kind", [
    ("Fins d'abri sommaire en forêt", "abri_sommaire"),
    ("Fins de villégiature", "villegiature"),
    ("Fins de résidence principale", "residence"),
    ("Fins d'hébergement dans une pourvoirie sans droits exclusifs", "pourvoirie_camp"),
])
def test_the_four_occupancy_purposes_are_recognised(purpose, kind):
    assert baux.classify(purpose) == kind


@pytest.mark.parametrize("purpose", [
    "Fins de production et de transmission d'électricité par éolienne",
    "Fins d'équipements de télécommunication",
    "Fins de panneau-réclame",
    "Fins de parc à résidus miniers",
    "Fins de culture",
    "Fins d'utilité publique",
])
def test_infrastructure_leases_are_not_people(purpose):
    """1,223 wind turbines and 422 telecom masts are in this file. None of them hunt."""
    assert baux.classify(purpose) is None


def test_matching_ignores_accents_and_case():
    """The purpose strings are French and arrive from a DBF whose encoding we do not
    control. Matching must not hinge on whether the é survived the trip."""
    assert baux.classify("FINS DE VILLEGIATURE") == "villegiature"
    assert baux.classify("fins d'abri sommaire en foret") == "abri_sommaire"


def test_an_unknown_purpose_is_not_guessed():
    assert baux.classify("") is None
    assert baux.classify(None) is None
    assert baux.classify("Fins de quelque chose de tout à fait nouveau") is None


# --------------------------------------------------------------- pressure, not a gate


def _fc(*pts):
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"kind": k},
         "geometry": {"type": "Point", "coordinates": [lon, lat]}}
        for lon, lat, k in pts]}


@pytest.fixture()
def grid(tmp_path):
    """A small real grid in the working CRS, centred on a known lon/lat."""
    rasterio = pytest.importorskip("rasterio")
    pytest.importorskip("scipy")
    from pyproj import Transformer
    from rasterio.transform import from_origin

    lon, lat, res, n = -78.456, 47.815, 40.0, 120
    x, y = Transformer.from_crs("EPSG:4326", "EPSG:32198", always_xy=True).transform(lon, lat)
    tr = from_origin(x - res * n / 2, y + res * n / 2, res, res)
    prof = {"crs": rasterio.crs.CRS.from_epsg(32198), "transform": tr}
    return tmp_path, prof, (n, n), (lon, lat)


def _pressure(tmp_path, prof, shape, fc):
    from moose_scout import access
    (tmp_path / "baux.geojson").write_text(json.dumps(fc))
    ctx = type("C", (), {"model": type("M", (), {"pressure": {}})()})()
    return access._lease_pressure(ctx, tmp_path, prof, shape)


def test_no_lease_file_leaves_the_road_term_alone(grid):
    """Absent data must read as 'we did not look', not as 'nobody is here'. The same
    distinction access_unknown draws for roads."""
    tmp_path, prof, shape, _ = grid
    from moose_scout import access
    ctx = type("C", (), {"model": type("M", (), {"pressure": {}})()})()
    assert access._lease_pressure(ctx, tmp_path, prof, shape) is None


def test_an_empty_box_is_zero_pressure_not_unknown(grid):
    """'No cabins in this box' is a real answer and earns a real zero."""
    tmp_path, prof, shape, _ = grid
    p = _pressure(tmp_path, prof, shape, _fc())
    assert p is not None and float(p.max()) == 0.0


def test_pressure_is_highest_at_the_cabin_and_decays(grid):
    tmp_path, prof, shape, (lon, lat) = grid
    p = _pressure(tmp_path, prof, shape, _fc((lon, lat, "abri_sommaire")))
    import numpy as np
    peak = np.unravel_index(int(np.argmax(p)), p.shape)
    assert abs(peak[0] - shape[0] // 2) <= 1 and abs(peak[1] - shape[1] // 2) <= 1
    assert p.max() == pytest.approx(1.0, abs=0.02)
    assert p[0, 0] < 0.25, "pressure did not decay across a 4.8 km box"


def test_an_abri_sommaire_outranks_a_cottage_on_the_same_spot(grid):
    """A shelter in the forest is built to hunt from; a lakeside cottage is mostly a
    summer thing. If these scored the same the class filter would be decoration."""
    tmp_path, prof, shape, (lon, lat) = grid
    hi = _pressure(tmp_path, prof, shape, _fc((lon, lat, "abri_sommaire"))).max()
    lo = _pressure(tmp_path, prof, shape, _fc((lon, lat, "villegiature"))).max()
    assert hi > lo


def test_the_nearest_cabin_wins_rather_than_the_crowd(grid):
    """Per-class distance transforms combined by max: one abri sommaire must not be
    diluted by three distant cottages, and three cottages must not sum into an abri."""
    tmp_path, prof, shape, (lon, lat) = grid
    many = _pressure(tmp_path, prof, shape,
                     _fc((lon, lat, "villegiature"), (lon + 0.001, lat, "villegiature"),
                         (lon, lat + 0.001, "villegiature")))
    one = _pressure(tmp_path, prof, shape, _fc((lon, lat, "villegiature")))
    assert float(many.max()) == pytest.approx(float(one.max()), abs=1e-4)


def test_leases_never_appear_in_the_legal_or_huntable_path():
    """THE ONE THAT MATTERS. A lease covers a building, not the country around it.
    If this layer ever reaches legal.py or the huntable mask, somebody loses ground
    they are entitled to hunt — so no module on that path may even mention it."""
    import inspect

    from moose_scout import legal
    for mod in (legal,):
        src = inspect.getsource(mod)
        assert "baux" not in src.lower(), f"{mod.__name__} references the lease layer"

    from moose_scout import access
    src = inspect.getsource(access)
    # It may only be read by the pressure surface.
    assert "_lease_pressure(" in src
    assert "huntable" not in src.split("_lease_pressure")[1][:2000].lower()


def test_pressure_combines_with_roads_instead_of_replacing_them():
    """A cabin ON a road is more pressured than either fact alone implies — so the two
    terms compose as independent probabilities, not by max (which would let a cabin
    silently erase a road's contribution)."""
    import inspect

    from moose_scout import access
    src = inspect.getsource(access.run)
    assert "(1.0 - pressure) * (1.0 - lease)" in src
