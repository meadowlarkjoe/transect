"""Which window an area belongs to, on the map (T10.3).

Reported: "They overlap. Im guessing these are different for each season, but thats not
clear on the map. Maybe... a slider or multi select on the map that allows you to either
see analysis for all dates vs analysis for a single date range."

Two windows share their geography — that is the whole point of running them together, and
it is why the areas land on top of each other. The engine has always known which is which
(`worker._merge` stamps `window` on every merged list item), so this is a DISPLAY control:
it filters, it never recomputes, reorders or rescores.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


def test_every_map_feature_class_carries_its_window():
    """A filter can only reach what the feature carries. Missing one source means that
    layer silently ignores the filter — a route from the wrong season still drawn."""
    body = _fn("buildSources")
    for src_name, anchor in (
        ("areas", "properties:{rank:a.rank,camp:a.camp"),
        ("areaLabels", "top:a.rank<=2"),
        ("camps", "properties:{id:c.id,fixed:!!c.fixed"),
        ("staging", "w.type==='parking'"),
        ("sites", "properties:{type:w.type,area:w.properties.focus_area"),
        ("routes", "const base={t:RT[r.type]"),
    ):
        i = body.index(anchor)
        assert "win:win(" in body[i:i + 260], f"{src_name} features carry no window"


def test_a_feature_with_no_window_stays_visible_under_every_selection():
    """Legacy and single-window plans. Hiding them would claim they belong to some OTHER
    window, which is a stronger claim than the data supports."""
    body = _fn("buildSources")
    assert "(o&&o.window!=null)?o.window:-1" in body.replace(" ", "")
    f = _fn("applyWindowFilter")
    assert "['==',['get','win'],-1]" in f.replace(" ", "")


def test_the_filter_composes_with_each_layer_s_own_filter():
    """THE TRAP. route-best filters on `t`, sites-wind on `windok`, route-ride-atv on
    `mode`. Overwriting those with a window filter would show every route as one colour
    and every site ring as lit."""
    f = _fn("applyWindowFilter")
    assert "_winBaseFilter" in f
    assert "base?['all',base,cond]:cond" in f.replace(" ", ""), \
        "the layer's own filter is being replaced rather than ANDed"


def test_the_base_filters_are_captured_once_not_every_call():
    """Capturing after a filter is applied would fold the window condition into the
    'base' and the selection could never be widened again."""
    f = _fn("applyWindowFilter")
    assert "if(!_winBaseFilter){" in f.replace(" ", "")


def test_one_window_offers_no_control():
    """A filter that filters nothing reads as broken, not absent."""
    body = _fn("buildWindowPill")
    assert "W.length<2" in body.replace(" ", "")
    assert "winSel=null" in body.replace(" ", ""), \
        "a stale selection survives into a single-window plan"


def test_the_sidebar_honours_the_map_filter():
    """A list of eight areas beside a map showing four is the same confusion again."""
    body = _fn("buildPanel")
    assert "DOC.camps.filter(inWindow)" in body
    assert "inWindow(a)" in body
    assert "if(!mine.length) return;" in body, "a camp heading is left standing empty"


def test_derived_geometry_follows_the_filter_too():
    """Shooters and scent are built from `window._sites`, not from the source, so a
    source-level filter cannot reach them — a bow-season shooter would stay on the map
    under a rifle-season selection."""
    body = _fn("buildShooters")
    assert "winSel==null||f.properties.win===winSel" in body.replace(" ", "")


def test_the_filter_is_reasserted_when_new_data_arrives():
    src = APP.read_text()
    i = src.index("setD('routes',S.routes);")
    assert "applyWindowFilter()" in src[i:i + 200]


def test_an_area_says_which_window_it_came_from():
    src = APP.read_text()
    card = src[src.index("function areaCard("):]
    card = card[:card.index("\n/* ---------------- drilldown")]
    assert card.count("windowTag(a)") >= 2, \
        "the excluded card and the normal card must both say it"


def test_the_tag_prefers_the_method_when_the_windows_differ_by_weapon():
    """What the hunter actually asked to see: "we need to indicate what the method of
    take is for each hunting date range"."""
    body = _fn("windowTag")
    assert "methods.size>1" in body.replace(" ", "")
    assert "W.length<2) return ''" in body.replace("  ", " "), \
        "a single-window run would be labelled 'season 1', which is noise"


def test_the_control_exists_in_the_page():
    assert 'id="winPill"' in pathlib.Path("app/app.html").read_text()
    assert "#winPill" in pathlib.Path("app/style.css").read_text()


def test_both_languages_have_the_strings():
    i18n = pathlib.Path("app/i18n.js").read_text()
    for k in ("win.cap", "win.all"):
        assert len(re.findall(rf"'{re.escape(k)}'\s*:", i18n)) == 2, \
            f"{k} is not defined in both en and fr"


def test_the_filter_survives_an_unloaded_style():
    """`getStyle()` returns UNDEFINED before load, not an empty style, and this runs from
    the source refresh — which can land first. Caught by driving the live map; the static
    tests above all passed with the broken guard, because they never called it.

    It retries on `idle` rather than skipping, and never on `load`: `load` fires once,
    but the style is momentarily unavailable during ordinary updates too. Exactly the
    mistake made and corrected in `applyTerrain` an hour earlier."""
    body = _fn("applyWindowFilter")
    assert "constst=(map&&map.getStyle)?map.getStyle():null" in body.replace(" ", "")
    assert "if(!st||!st.layers)" in body.replace(" ", "")
    assert "map.once('idle',applyWindowFilter)" in body.replace(" ", "")
    assert "map.once('load'" not in body.replace(" ", "")


def test_every_chip_names_its_method_when_the_windows_differ_by_weapon():
    """Seen live: suppressing "rifle" as the default left one chip reading "bow" and the
    other reading nothing, which asks the hunter to know what a blank means. The method
    is the thing they asked to see — "we need to indicate what the method of take is for
    each hunting date range"."""
    body = _fn("buildWindowPill")
    assert "methods.size>1?(w.method||'rifle'):''" in body.replace(" ", "")
    assert "w.method!=='rifle'?w.method" not in body.replace(" ", ""), \
        "rifle is being suppressed as an unlabelled default again"
