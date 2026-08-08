"""A stand says what the survey says about it (E11.6).

A guide's Cartes Xperts sheet labels every polygon `R ENML 75% 10m` — cover type, species
composition, density, height — and that label IS the product a hunter pays for, because
you can hold it against what you are looking at. The engine stores all four fields; this
is the card that says the same sentence back and then translates it.
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


def test_the_card_rebuilds_the_sheets_own_label():
    body = _fn("standLabel")
    for f in ("type_couv", "gr_ess", "closure", "height_m"):
        assert f in body, f"the label drops {f}, which is on the printed sheet"


def test_the_species_codes_are_translated_not_just_echoed():
    """`ENML` is not a sentence. The point of holding gr_ess is that a hunter can read
    it — echoing the code alone would leave them exactly where the raw sheet does."""
    body = _fn("standSpecies")
    assert "ESS_NAME" in body
    # Do NOT space-strip here: it strips the spaces INSIDE the string literals too, so
    # "black spruce" could never match. Same needle bug as the unloaded-style test.
    src = _code()
    assert "EN:'black spruce'" in src
    assert "BP:'white birch'" in src
    assert "PT:'trembling aspen'" in src


def test_the_species_names_are_not_a_second_copy_of_the_browse_weights():
    """Those live in acquire/ecoforestiere.py and score what a stand is worth to EAT.
    This says what the letters MEAN. Duplicating the weights is how the two drift."""
    src = _code()
    i = src.index("const ESS_NAME=")
    seg = src[i:src.index("}", i)]
    assert not re.search(r":\s*[01]?\.\d", seg), "browse weights have been copied into the name table"


def test_dominance_order_survives_into_the_reading():
    """`gr_ess` is ordered by dominance — BPBPSB is a birch stand with fir in it, and
    SBBPBP is not the same place."""
    body = _fn("standSpecies")
    assert "codes.push" in body and "i+=2" in body.replace(" ", "")


def test_a_repeated_code_is_not_read_out_twice():
    """`ENEN` is pure black spruce, not "black spruce, black spruce"."""
    body = _fn("standSpecies")
    assert "includes(c)" in body


def test_it_says_when_the_stand_is_out_of_reach():
    """The distinction species alone cannot make, and the one that stops this card
    contradicting the browse layer: 20 m birch is prime BY SPECIES and food for nobody."""
    # Bounded by the NEXT entry rather than a character count — the block grows, and a
    # fixed window just measures how much has been added since the test was written.
    src = APP.read_text()
    i = src.index("{lyr:'stands',")
    seg = src[i:src.index("{lyr:'huntZones',", i)]
    assert "Taller than a moose reaches" in seg


def test_it_sits_below_the_specific_features_it_covers():
    """The survey covers essentially the whole box. Ordered any higher, every hover would
    report the forest type and bury the funnel or the stand actually under the cursor."""
    src = APP.read_text()
    ident = src[src.index("const IDENTIFY = ["):]
    ident = ident[:ident.index("\n];")]
    assert ident.index("{lyr:'stands',") > ident.index("{lyr:'funnelZones',")
    assert ident.index("{lyr:'stands',") > ident.index("{lyr:'sites',")
    # ...but above the blanket huntability band, which is the least specific thing here
    assert ident.index("{lyr:'stands',") < ident.index("{lyr:'huntZones',")


def test_a_cut_is_not_called_a_food_desert():
    """CAUGHT LIVE. A cut or burn carries no `gr_ess` — the stand was removed — so
    `ess_browse` is 0, and reading that as "nothing here a moose eats" had this card
    calling a 2015 cut barren while the browse layer correctly scored it prime regen.
    Absence of a species list is not evidence of absent food."""
    src = APP.read_text()
    i = src.index("{lyr:'stands',")
    seg = src[i:src.index("{lyr:'huntZones',", i)]
    assert "if(p.gr_ess && p.ess_browse!=null)" in seg, \
        "the species verdict fires without species again"
    assert "the REGENERATION" in seg, "a disturbance says nothing about what it is worth"


def test_a_disturbance_is_not_labelled_stand():
    """No cover type and no species means the survey mapped a DISTURBANCE, not a stand.
    "Stand" was the label agreeing with itself rather than with the map."""
    body = _fn("standLabel")
    assert "'Stand'" not in body
    assert "Cut or burn" in body
