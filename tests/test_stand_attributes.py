"""The forest survey's attributes, ingested (E11.2).

The engine read `type_couv` and `cl_dens` and discarded the rest of every stand polygon,
which a guide's Cartes Xperts sheet for 47.983333, −77.817500 made obvious: the sheet
labels each polygon with its species composition, height, density and age, straight out
of the same MFFP response the engine already pays to download.

These tables are built from 1908 stands sampled around that sheet, not guessed at:
  cl_haut  3 (748) · 4 (643) · 5 (181) · 2 (67) · 6 (35) · 1 (4)
  cl_age   50 · 30 · VIR · JIN · JIR · VIN · 70 · 10 · 120 · 90 · 5050
  cl_pent  A (1432) · B (394) · C (42) · D (4)
  gr_ess   ENEN 45.9% · RXRX 8.3% · ENML 5.8% · BPBPSB 3.7% · ENENBP 3.5% …
"""
import inspect

from moose_scout.acquire import ecoforestiere as E


# ------------------------------------------------------------------ species -> browse


def test_the_two_orderings_this_whole_epic_is_about():
    """Black spruce is what the engine's own methodology calls a food desert, and it was
    scoring identically to black spruce CARRYING BIRCH. Inside `M`, birch-dominant was
    indistinguishable from fir-dominant."""
    assert E.ess_browse("ENENBP") > E.ess_browse("ENEN")
    assert E.ess_browse("BPBPSB") > E.ess_browse("SBSBBP")


def test_pure_black_spruce_scores_nothing():
    assert E.ess_browse("ENEN") == 0.0


def test_birch_and_aspen_are_the_money_species():
    for g in ("BPBP", "PTPT"):
        assert E.ess_browse(g) >= 0.95, g


def test_dominance_is_weighted_by_position():
    """`gr_ess` is ordered by dominance, so the same three species in a different order
    are a different stand."""
    assert E.ess_browse("BPBPSB") != E.ess_browse("SBBPBP")
    assert E.ess_browse("BPBPSB") > E.ess_browse("SBBPBP")


def test_browse_value_is_not_the_same_as_being_a_hardwood():
    """Balsam fir is a conifer and is genuinely browsed; larch is a conifer and is not.
    A deciduous/coniferous split would get both wrong."""
    assert E.ess_browse("SBSB") > E.ess_browse("MLML")


def test_an_unreadable_code_scores_nothing_rather_than_average():
    """Absent evidence is not evidence of forage, and the caller falls back to the cover
    class. A middling default would invent browse on ground nobody surveyed."""
    for g in ("", None, "X", "ZZ"):
        assert E.ess_browse(g) <= 0.10, g


# --------------------------------------------------------------------------- age


def test_even_aged_stands_read_their_number():
    assert E.stand_age("50") == 50 and E.stand_age("120") == 120


def test_uneven_aged_codes_get_a_representative_age():
    """J = jeune, V = vieux. 494 of 1908 sampled stands carry one of these, so dropping
    them would blank a quarter of the map."""
    assert E.stand_age("JIN") < E.stand_age("VIN")
    assert E.stand_age("JIR") < E.stand_age("VIR")


def test_a_two_storey_stand_takes_its_first_storey():
    """`5050` is two classes written together; the canopy belongs to the first."""
    assert E.stand_age("5050") == 50


def test_an_unknown_age_is_zero_not_a_guess():
    assert E.stand_age("") == 0 and E.stand_age("XX") == 0


# ------------------------------------------------------------------ height and reach


def test_height_classes_run_the_right_way():
    """Class 1 is the tallest. Inverting this would make canopy look like browse."""
    h = E.HEIGHT_M
    assert h["1"] > h["2"] > h["3"] > h["4"] > h["5"] > h["6"] > h["7"]


def test_the_browse_reach_is_a_moose_and_not_a_giraffe():
    assert 2.0 <= E.BROWSE_REACH_M <= 3.5


def test_only_the_short_classes_are_within_reach():
    """THE GATE THAT MAKES E11.3 SAFE. Species alone would promote 20 m paper birch to
    prime browse — it is prime BY SPECIES and out of reach BY HEIGHT, and `feuillus`
    currently scores 0.20 precisely because the class constant absorbs that."""
    within = [k for k, v in E.HEIGHT_M.items() if v <= E.BROWSE_REACH_M]
    assert set(within) == {"6", "7"}, within


# ------------------------------------------------------------------------- the ingest


def test_every_new_raster_is_written():
    src = inspect.getsource(E.fetch)
    for name in ("stand_height.tif", "stand_age.tif", "stand_slope.tif",
                 "stand_ess_browse.tif"):
        assert name in src, name


def test_the_attributes_merge_by_last_stand_not_by_maximum():
    """`cut_year` merges by maximum because the most recent cut wins. Height must NOT:
    a max smears the tallest stand in the page across every cell its neighbours touch,
    and height is the one field this must never exaggerate."""
    src = inspect.getsource(E.fetch)
    i = src.index("for shapes, acc, dt in ((hsh, hgt")
    seg = src[i:i + 500]
    assert "np.maximum" not in seg, "the survey attributes are being merged by maximum"
    assert "acc[pr > 0]" in seg


def test_the_display_copy_is_simplified_to_the_analysis_grid():
    """Measured: 198 vertices per stand, 5.5 MB for an 8 km box against 0.55 MB
    simplified — and a 35 km box would otherwise be some 400 MB of map layer. The model
    cannot resolve past its own cell size, so the extra detail is weight nobody reads."""
    src = inspect.getsource(E.fetch)
    assert "g.simplify(res_m)" in src


def test_the_polygon_cap_is_not_silent():
    """A cap that truncates in silence reads as "this is all the forest there is"."""
    src = inspect.getsource(E.fetch)
    assert "truncated" in src
    assert "stands.json" in src
    assert "the map layer is partial" in src


def test_a_display_failure_cannot_cost_the_analysis():
    src = inspect.getsource(E.fetch)
    i = src.index("import geopandas")
    seg = src[i:]
    assert "except Exception" in seg, "a gpkg write failure would propagate"
    assert seg.index("except Exception") < seg.index("stands.json") + 400


def test_the_new_artifacts_are_shareable():
    """They are acquire outputs keyed on geography — not sharing them means every box
    re-downloads a dense WFS pull the cache exists to avoid."""
    from moose_scout import geocache
    for name in ("stand_height.tif", "stand_age.tif", "stand_slope.tif",
                 "stand_ess_browse.tif", "stands.gpkg", "stands.json"):
        assert name in geocache.ARTIFACTS, name
