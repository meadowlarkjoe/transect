"""Water is a parent class, and the specific outranks the general (T10.4, water half).

Asked: "Water is a parent class. Inside that should be beaver ponds, wetlands,
rivers&lakes... Duplication should be eliminated. Data of higher specificity (ex beaver
pond) should out rank genereal data (ex. waterbody)."

Today's legend had three unrelated rows — Rivers & lakes and Wetlands under ACCESS &
HYDRO, Beaver ponds stranded over in SITES & FEATURES — which asks the hunter to know
that a flowage, a bog and a lake are the same subject.

AND THE DRAW ORDER SAID THE OPPOSITE OF THE RULE. Wetlands and beaver ponds were added
first and the generic lake FILL went in over both, so a flowage the model calls a rut hub
was painted over by the waterbody that merely contains it.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _layers():
    src = APP.read_text()
    block = src[src.index("const LAYERS=["):]
    block = block[:block.index("\n];")]
    return block


def _row(k):
    b = _layers()
    i = b.index(f"{{k:'{k}',")
    return b[i:b.index("\n {k:'", i + 5)] if "\n {k:'" in b[i:] else b[i:]


def test_water_is_a_parent_with_three_kinds_under_it():
    b = _layers()
    assert "{k:'water'," in b and "parent:true" in _row("water")
    for k in ("beaver", "wetland", "openwater"):
        assert "sub:'water'" in _row(k), f"{k} is not a kind of water"


def test_the_parent_draws_nothing_of_its_own():
    """It is the subject, not a layer. Giving it an `lyr` would double-draw its children."""
    assert "lyr:" not in _row("water"), "the water parent draws its own geometry"


def test_beaver_ponds_left_the_sites_group():
    assert "group:'ACCESS & HYDRO'" in _row("beaver"), \
        "beaver ponds are stranded in SITES & FEATURES again"


def test_the_three_kinds_are_still_independently_toggleable():
    """Grouping them must not merge them — that was the other way to get this wrong."""
    for k in ("beaver", "wetland", "openwater"):
        assert re.search(r"lyr:'\w+'", _row(k)), f"{k} lost its own layer binding"


def test_toggling_the_parent_carries_its_children():
    src = APP.read_text()
    i = src.index("function applyLayer(r){")
    body = src[i:src.index("\nfunction ", i + 10)]
    assert "if(r.parent){" in body.replace(" ", "")
    assert "LAYERS.filter(x=>x.sub===r.k)" in body


def test_a_child_switching_on_switches_its_parent_on():
    """Otherwise the parent reads OFF while its own ground is drawn."""
    src = APP.read_text()
    i = src.index("function applyLayer(r){")
    body = src[i:src.index("\nfunction ", i + 10)]
    assert "x.k===r.sub&&x.parent" in body.replace(" ", "")


def test_open_water_is_pushed_under_the_wetlands():
    """THE RULE, as draw order. And it must be done by pushing open water DOWN — a bare
    moveLayer() raises to the very top, which would put lake fill over the camps, staging
    pins, crossings and area badges added before that point."""
    src = APP.read_text()
    i = src.index("['lakes','lakes-line','rivers'].forEach")
    seg = src[i:i + 240]
    assert "map.moveLayer(id,'wetlandZones')" in seg, \
        "open water is not being placed beneath the wetlands"
    assert "map.moveLayer(id)" not in seg, \
        "a bare moveLayer raises to the top, over the site symbology"


def test_the_reorder_runs_after_every_water_layer_exists():
    """moveLayer on a layer that is not added yet is a no-op that fails silently."""
    src = APP.read_text()
    reorder = src.index("['lakes','lakes-line','rivers'].forEach")
    for lid in ("lakes", "lakes-line", "rivers", "wetlandZones", "beaverPonds"):
        assert src.index(f"addLayer({{id:'{lid}'") < reorder, \
            f"{lid} is added after the reorder, so the move silently does nothing"


def test_the_layer_map_follows_the_rename():
    src = APP.read_text()
    lyr = src[src.index("const LYR_MAP="):]
    lyr = lyr[:lyr.index("]};") + 1]
    assert "openwater:['lakes'" in lyr
    # `openwater:` CONTAINS `water:`, so this needs a boundary, not a substring.
    assert not re.search(r"[{,\s]water:\['lakes'", lyr), \
        "the old water binding survives and shadows it"


def test_both_languages_name_the_parent_and_the_general_case():
    i18n = pathlib.Path("app/i18n.js").read_text()
    for k in ("lay.water", "lay.openwater", "lay.water.n", "lay.openwater.n"):
        assert len(re.findall(rf"'{re.escape(k)}'\s*:", i18n)) == 2, f"{k} missing a language"
