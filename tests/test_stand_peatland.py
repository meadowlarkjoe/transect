"""The stand map's peatland stopped being dropped on the floor (T10.23, slice 1).

Found by cross-referencing a guide's Cartes Xperts sheet for 47.983333, −77.817500
against the model. The sheet renders the same MFFP écoforestière source the engine pulls,
and it shows "Dénudé humide" polygons the engine was silently discarding.

`_classify` returned None for any polygon with no `type_couv` — 39 of 599 stands over that
sheet, 6.5% of the ground. Almost every one carried `dep_sur` 7x (organic deposit) with
hydric drainage: peat bog and wet barren.

THAT WAS NOT NOTHING. `config/species/moose.yaml` has carried a `tourbiere` class with
browse 0.35 and wet 1.0 the whole time, and habitat.py's own comment said peatland was
"only reachable through land cover" — while terrain.py documents that WorldCover barely
sees boreal peatland (0.4% of one test AOI against 7.5% from GRHQ). A third source was in
hand and thrown away.
"""
import inspect

from moose_scout.acquire import ecoforestiere as E


def _p(**kw):
    base = dict(type_couv="", gr_ess="", origine="", an_origine="", perturb="",
                an_perturb="", cl_dens="", cl_haut="", cl_age="", cl_pent="",
                dep_sur="", cl_drai="")
    base.update(kw)
    return base


def test_an_organic_deposit_on_wet_ground_is_peatland():
    """THE BUG. Both of these were returning None."""
    assert E._classify(_p(dep_sur="7E", cl_drai="60"))[0] == E.T_TOURBIERE
    assert E._classify(_p(dep_sur="7T", cl_drai="50"))[0] == E.T_TOURBIERE


def test_both_conditions_are_required():
    """An organic deposit on well-drained ground is not a bog, and hydric drainage on
    mineral soil is not either. Loosening this to `dep_sur` alone would paint peatland
    across ordinary forest floor."""
    assert E._classify(_p(dep_sur="7E", cl_drai="30"))[0] is None
    assert E._classify(_p(dep_sur="4GA", cl_drai="60"))[0] is None


def test_genuinely_barren_ground_is_still_dropped():
    """Glacial and alluvial deposits with no cover are rock and gravel. `non_boise` scores
    browse −0.30 — calling them bog would be an invention in the hunter's favour, which
    is the worst direction to be wrong in."""
    assert E._classify(_p(dep_sur="3AE", cl_drai="60"))[0] is None
    assert E._classify(_p())[0] is None


def test_a_forested_stand_is_never_reclassified_as_peat():
    """The cover-type checks return first. A black-spruce stand ON peat is still a stand
    — it has a canopy, and its thermal cover is real."""
    for tc, want in (("R", E.T_RESINEUX), ("M", E.T_MELANGE), ("F", E.T_FEUILLU)):
        assert E._classify(_p(type_couv=tc, dep_sur="7E", cl_drai="60"))[0] == want


def test_a_dated_cut_on_peat_is_still_a_cut():
    got, yr = E._classify(_p(origine="CT", an_origine="2015", dep_sur="7E", cl_drai="60"))
    assert got == E.T_CUT and yr == 2015


def test_habitat_maps_the_new_code_to_the_config_class_that_already_existed():
    from moose_scout import habitat
    src = inspect.getsource(habitat.build) if hasattr(habitat, "build") else \
        inspect.getsource(habitat)
    assert '7: "tourbiere"' in src
    assert "{1: 0.05, 2: 0.35, 3: 0.30, 4: 0.55, 5: 0.45, 6: 0.30, 7: 0.35}" in src


def test_peatland_is_not_counted_as_thermal_cover():
    """`conifer_close` drives thermal refuge. A bog has no canopy, and a refuge drawn on
    open peat would send a hunter to sit in the middle of one on a warm afternoon."""
    from moose_scout import habitat
    src = inspect.getsource(habitat)
    assert "np.isin(st, [1, 2])" in src, "the conifer-closure mask changed shape"
    i = src.index("conifer_close = np.where(")
    assert "[1, 2]" in src[i:i + 80], "peat is being counted as conifer closure"


def test_the_measured_effect_is_recorded():
    """Over the sheet's 599 stands: dropped 39 → 11, peatland 28 (4.7%). The 11 that
    remain are the glacial and alluvial ones, which is correct."""
    assert E.T_TOURBIERE == 7
    assert E.ORGANIC_DEPOSITS == ("7",)
    assert E.HYDRIC_DRAINAGE == ("4", "5", "6")
