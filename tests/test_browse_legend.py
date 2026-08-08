"""The browse legend names food, not sources (T10.4, front end).

The four sublayers were "from dated cuts", "from dated burns", "from the stand map",
"from satellite land cover". Ranking those sources is a job the engine already does; the
legend handed the result to the reader to interpret, which is the error the ticket names.

And "Recent cuts" stood alone as a SECOND top-level row over the same cutblocks browse
was already drawing — "Recent cuts are under browse/feeding but also their own thing?"
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")
KINDS = ["brRegenPrime", "brAquatic", "brRegenClosing", "brDeciduous", "brRegenNew", "brOther"]


def _code():
    """The file with comments stripped. Every one of these checks asks whether a name is
    still USED, and the comments deliberately name the things that were removed — reading
    the raw file makes each of them permanently red."""
    return re.sub(r"//[^\n]*", "", APP.read_text())


def _layers():
    src = APP.read_text()
    b = src[src.index("const LAYERS=["):]
    return b[:b.index("\n];")]


def test_the_source_named_sublayers_are_gone():
    """THE BUG, as the thing that must not come back."""
    src = _code()
    for dead in ("browseCut", "browseBurn", "browseStand", "browseLc",
                 "browse_cut_zones", "browse_lc_zones", "browseSub"):
        assert dead not in src, f"{dead} is back — the legend is naming sources again"


def test_browse_is_a_parent_over_kinds_of_food():
    b = _layers()
    i = b.index("{k:'browse',")
    row = b[i:b.index("\n {k:'", i + 5)]
    assert "parent:true" in row
    assert "lyr:" not in row, "the parent draws its own composite as well as its children"
    for k in KINDS:
        assert f"{{k:'{k}'," in b and "sub:'browse'" in b[b.index(f"{{k:'{k}',"):][:400]


def test_every_zone_is_drawn_by_exactly_one_kind():
    """The filters must partition the source. `other` is the catch-all — without it a
    zone the engine could not classify would simply never draw."""
    src = APP.read_text()
    filters = re.findall(r"id:'(br\w+)',type:'fill',source:'browseZones',filter:\['==',\['get','kind'\],'(\w+)'\]", src)
    assert len(filters) == 6, filters
    assert {k for _, k in filters} == {
        "regen_prime", "aquatic", "regen_closing", "deciduous", "regen_new", "other"}


def test_a_zone_with_no_kind_still_draws():
    """`kind:z.kind||'other'` — a MapLibre filter cannot compare against null, so a plan
    saved before T10.4 would have vanished from the map entirely."""
    src = APP.read_text()
    assert "kind:z.kind||'other'" in src


def test_recent_cuts_is_not_a_second_top_level_row():
    b = re.sub(r"//[^\n]*", "", _layers())
    assert "{k:'cuts'," not in b
    assert "cutZones" not in _code(), "the cut layers are still added"


def test_the_cut_years_survived_the_row_that_carried_them():
    """The only thing that row had which the regen stages do not. Deleting it without
    this would have lost real information — a 1998 cut and a 2012 cut are both 'prime'
    and are not the same walk."""
    src = APP.read_text()
    assert "distAge:(z.dist_age!=null?z.dist_age:null)" in src
    assert "disturbed ~${p.distAge} yr ago" in src


def test_the_brief_plate_no_longer_names_a_layer_that_does_not_exist():
    src = APP.read_text()
    plates = src[src.index("const PLATES=["):]
    plates = plates[:plates.index("\n];")]
    assert "'cuts'" not in plates
    assert "brRegenPrime" in plates


def test_the_kinds_are_ordered_by_what_they_are_worth_to_the_animal():
    """Prime browse first. A legend sorted by data source put "from dated cuts" first
    because it was the best EVIDENCE, which is not the same question."""
    b = re.sub(r"//[^\n]*", "", _layers())
    order = [k for k in re.findall(r"\{k:'(br[A-Z]\w+)',", b)]
    assert order[0] == "brRegenPrime", order
    assert order.index("brRegenNew") > order.index("brRegenClosing"), order


def test_both_languages_name_every_kind():
    i18n = pathlib.Path("app/i18n.js").read_text()
    for k in KINDS:
        for key in (f"lay.{k}", f"lay.{k}.n"):
            assert len(re.findall(rf"'{re.escape(key)}'\s*:", i18n)) == 2, \
                f"{key} is missing a language"


def test_the_row_does_not_blame_the_data_for_a_gap_that_is_ours():
    """T10.4 shipped this row saying the stand map "has classes, not species". That was
    WRONG, and a guide's Cartes Xperts sheet for 47.98, -77.82 is what showed it: every
    polygon on that map is labelled with its species composition, straight out of the
    same MFFP source this engine pulls. The WFS returns `gr_ess`;
    acquire/ecoforestiere.py reads only `type_couv` and throws the rest away.

    So the row may say the engine does not USE species. It may not say the survey does
    not HAVE them — that is blaming the data for our own gap, and it is the sort of claim
    that quietly closes a question that should stay open (T10.23)."""
    b = _layers()
    i = b.index("{k:'brDeciduous',")
    row = b[i:b.index("\n {k:'", i + 5)]
    assert "classes, not species" not in row, "the row asserts a falsehood about the source"
    assert "does not use yet" in row or "not use yet" in row
