"""Adding a season has to actually give you a date range (setup form).

Reported: "i can now add a different method of take but i can't add a different date
range? the seasons arent the same dates".

The engine has run a separate analysis per window since T9.2, with a per-window method of
take since T10.2. Nothing was missing from the model — the FORM was broken, in two ways
that compounded:

  1. A new season was pushed as ['', '', 'rifle']. Both date inputs were genuinely empty,
     and an empty `type=date` styled `border:none;background:none` renders as nothing at
     all. There was no visible field to fill in.
  2. The row laid out two date inputs, an arrow, a method select and a delete button on
     ONE flex line — measured live at 137+7+137+14+31 = 326 px of children in a 289 px
     row. The select was crushed to 14 px and on a narrow panel the dates were pushed out
     of view entirely.

And then submit filtered incomplete windows out with `w[0]&&w[1]`, so a season you thought
you had added silently did not exist in the result.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _code():
    return re.sub(r"//[^\n]*", "", APP.read_text())


def test_a_new_season_is_seeded_not_blank():
    """THE BUG. An empty date input with no border reads as no field at all."""
    src = _code()
    assert "draft.windows.push(['','','rifle'])" not in src.replace(" ", ""), \
        "a new season starts blank again"
    i = src.index("draft.windows.push(")
    assert "d[0]" in src[i:i + 120] and "d[1]" in src[i:i + 120], \
        "a new season is not seeded from the primary dates"


def test_the_seeded_method_differs_from_the_primary():
    """The whole reason to add a season is to compare — seeding it with the same weapon
    makes the row look like a duplicate of the one above it."""
    src = _code()
    i = src.index("draft.windows.push(")
    assert "draft.method==='bow'?'rifle':'bow'" in src[i:i + 200].replace(" ", "")


def test_the_row_does_not_put_everything_on_one_line():
    """326 px of children in a 289 px row, measured in the live app."""
    src = APP.read_text()
    assert 'class="winrow"' in src
    assert 'class="winrow__dates"' in src
    css = pathlib.Path("app/style.css").read_text()
    assert ".winrow{" in css.replace(" ", "")
    assert "grid-column:1 / -1" in css, "the dates do not get their own row"


def test_the_date_inputs_can_shrink_without_vanishing():
    css = pathlib.Path("app/style.css").read_text()
    i = css.index(".winrow__dates input[type=date]")
    seg = css[i:i + 200]
    assert "min-width:0" in seg.replace(" ", ""), \
        "a flex item with min-width:auto overflows its row instead of fitting"
    assert "color:var(--text)" in seg.replace(" ", "")


def test_an_incomplete_season_blocks_the_run_instead_of_vanishing():
    """Submit drops windows with `w[0]&&w[1]`. Without this check you add a season, run,
    and get a single-window result with nothing anywhere saying why."""
    src = APP.read_text()
    i = src.index("function missingSetup(){")
    body = src[i:src.index("\n}", i)]
    assert "draft.windows" in body
    assert "both dates for season" in body


def test_the_seasons_are_numbered_from_two():
    """The primary window is season 1, so the first EXTRA row is season 2 — numbering it
    1 would point the hunter at the wrong row."""
    src = APP.read_text()
    i = src.index("function missingSetup(){")
    body = src[i:src.index("\n}", i)]
    assert "const n=i+2;" in body


def test_each_season_still_carries_its_own_method_to_the_engine():
    """The half that already worked, pinned so the form fix cannot break it."""
    src = APP.read_text()
    i = src.index("windows:(draft.windows&&draft.windows.length)")
    seg = src[i:i + 420]
    assert "[w[0],w[1],w[2]||'rifle']" in seg.replace(" ", "")
    assert "draft.method||'rifle'" in seg.replace(" ", ""), \
        "the primary window lost its method"


def test_the_method_of_take_explainer_is_gone():
    """"none of that needs explaining on the input form... any hunter filling this out is
    going to understand that." The method still changes the model; the BRIEF is where
    that belongs, as a finding on ground rather than a lecture on a form."""
    src = _code()
    assert "A bow needs the bull inside" not in src
    assert "setup.methodnote" not in src
    assert "methodNote(" not in src, "the dynamic replacement is still wired"
