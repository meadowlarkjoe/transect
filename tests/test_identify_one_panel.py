"""One panel per feature, and hovering shows it (T10.9).

Reported: "the explainability layer exists but it only appears on click, separate from
tooltip. these should be combined."

There were TWO explanations of the same feature. The hover card said "Browse / feeding ·
mostly the satellite land cover (100%) · sources partly agree · score 0.562 · 5.3 km²".
A separate click popup said "Riparian / wetland browse · 5.3 km² · Alder edges plus
emergent/submergent aquatics · When: dawn & dusk... Score: 0.562 · Why: mostly the
satellite land cover". Same feature, same numbers — and the RICHER of the two was the one
you had to discover by clicking.

Ten popups had grown this way, including a tenure card carrying a LEGAL restriction and a
site card carrying the attractant warning. Click-to-discover is the wrong place for
either. All of that prose is now IDENTIFY's `body`; hover renders it and click pins it.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _identify():
    src = APP.read_text()
    return src[src.index("const IDENTIFY = ["):src.index("\n];", src.index("const IDENTIFY = ["))]


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


def test_there_are_no_explanatory_popups_left():
    """THE BUG. A second panel is a second explanation, and they drift."""
    assert "maplibregl.Popup" not in APP.read_text(), \
        "a click popup is back — that is a second panel saying its own thing"


def test_the_hover_card_renders_the_full_explanation():
    body = _fn("idCardHTML")
    assert "def.body&&def.body(p)" in body.replace(" ", "")
    assert 'class="idbody"' in body


def test_a_body_that_throws_cannot_blank_the_whole_card():
    """One bad feature would otherwise take out the explanation for every layer under
    the cursor, since the cards render in one pass."""
    body = _fn("idCardHTML")
    assert "try{" in body and "catch" in body


def test_the_features_that_had_the_richest_popups_carry_a_body():
    """These are the ones whose click panel said something the hover did not."""
    ident = _identify()
    for lyr in ("browseZones", "burnZones", "funnelZones", "refugeZones", "huntZones",
                "tenureBlocked", "tenureZones-line-ok", "sites"):
        i = ident.index(f"{{lyr:'{lyr}',")
        nxt = ident.find("{lyr:'", i + 6)
        seg = ident[i:nxt if nxt > 0 else len(ident)]
        assert "body:" in seg, f"{lyr} lost the prose its popup used to carry"


def test_every_browse_kind_carries_its_note():
    """Was four SOURCE entries; T10.4 made it six KIND entries, and each still has to
    explain itself in the one panel."""
    ident = _identify()
    assert len(re.findall(r"body:\(\)=>brNote\('br\w+'\)", ident)) == 6


def test_the_legal_restriction_is_not_click_to_discover():
    """A tenure popup was the only place that said CLOSED to you. It is now in the
    hover body, and its prose lives in a function rather than inside a popup builder."""
    assert "function tenureBody(" in APP.read_text()
    assert "CLOSED to you" in _fn("tenureBody")


def _build_identify():
    """Scoped to buildIdentify. `map.on('mousemove'` and `map.on('click'` each appear
    several times in this file for unrelated features — the first version of these two
    tests read the AOI drag handler and the site-drop handler instead."""
    src = APP.read_text()
    i = src.index("function buildIdentify(){")
    return src[i:src.index("\nfunction ", i + 10)]


def test_click_pins_rather_than_revealing():
    assert "idPinned=true" in _build_identify().replace(" ", "")
    seg = _build_identify()
    assert "if(idPinned) return;" in seg, "a pinned card is still overwritten by the mouse"


def test_clicking_bare_ground_releases_the_pin():
    """The only gesture anyone tries first."""
    seg = _build_identify()
    i = seg.index("map.on('click',e=>{")
    seg = seg[i:]
    assert "idPinned=false" in seg.replace(" ", "")
    assert "window._siteDropArm" in seg, (
        "an armed site-drop click would also pin an explanation of the ground it landed "
        "on — the same rule onFeat already applies for drawTool")


def test_selecting_an_area_survives_because_it_is_an_action():
    """`areas-fill` is the one click that should still DO something rather than explain."""
    assert "onFeat('areas-fill',e=>selectArea(" in APP.read_text()


def test_a_pinned_card_can_be_reached_and_read():
    """The card is pointer-events:none while hovering, which is right — it must not eat
    the mouse. Pinned it has to accept the pointer, or it cannot be scrolled or selected."""
    css = pathlib.Path("app/style.css").read_text()
    assert "#idCard.pinned{pointer-events:auto" in css.replace(" ", "")
    assert "#idCard.pinned{overflow:auto}" in css.replace(" ", "")


def test_clearing_the_card_also_clears_the_pin():
    """Otherwise a stale pin blocks every future hover, with nothing on screen."""
    body = _fn("clearIdentify")
    assert "idPinned=false" in body.replace(" ", "")
