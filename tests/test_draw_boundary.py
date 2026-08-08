"""Reshaping a shape, and the analysis boundary not being an annotation.

Three reports in one message:

  "if i click on a line when editing any area, i should be able to add new verticies.
   I should be able to click on a vertices to delete it"
  "when I am drawing an area for analysis - it pulls me to the overview tab instead of
   staying on Setup which is confusing"
  "This shoudl also be seperate for the normal areas and not added to the drawing list.
   Its a one-and-done thing"

The third is a design error of mine: I reused `drawSaved`, the notes-and-markup list, for
something there is exactly one of and which is replaced when redrawn. It belongs on the
DRAFT beside the radius, and it now lives there.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _code():
    return re.sub(r"//[^\n]*", "", APP.read_text())


def _has(needle, hay):
    """Whitespace-insensitive containment, stripping BOTH sides.

    Written once because hand-rolling `needle in hay.replace(" ", "")` bit four separate
    times today: stripping only the haystack also strips the spaces inside string
    literals and identifiers, so `let _vertMode='move'` could never match anything.
    """
    return re.sub(r"\s+", "", needle) in re.sub(r"\s+", "", hay)


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


# ------------------------------------------------------- the boundary is not a drawing


def test_the_boundary_lives_on_the_draft_not_in_the_drawings_list():
    src = _code()
    assert "draft.aoiRing" in src
    body = _fn("selectedRing")
    assert "drawSaved" not in body and "drawnAreas" not in body


def test_drawing_the_boundary_never_touches_the_drawings_list():
    """It appeared under MY DRAWINGS as "Areas · 1" and had to be picked out of a list."""
    # Bounded to the IF branch. The `else` beside it is the CORRECT path for a real
    # annotation, and a fixed window swallows it and reads as failure.
    src = _code()
    i = src.index("if(window._aoiDrawPending){")
    seg = src[i:src.index("} else {", i)]
    assert "drawSaved.push" not in seg, "the boundary is being filed as an annotation again"
    assert _has("draft.aoiRing=ring", seg)


def test_an_ordinary_area_still_goes_to_the_drawings_list():
    """The branch has to keep working for actual annotations."""
    src = _code()
    i = src.index("if(window._aoiDrawPending){")
    seg = src[i:i + 600]
    assert "} else {" in seg and "drawSaved.push" in seg


def test_drawing_the_boundary_does_not_leave_setup():
    """The map is beside the panel the whole time; there was never a reason to leave."""
    src = _code()
    i = src.index("_adb.onclick")
    seg = src[i:i + 400]
    assert "setTab('overview')" not in seg, "it still jumps to Overview to arm the tool"
    assert "setDrawTool('area')" in seg


def test_finishing_the_boundary_does_not_move_the_tab_either():
    src = _code()
    i = src.index("if(window._aoiDrawPending){")
    seg = src[i:src.index("} else {", i)]
    assert "setTab(" not in seg


# ------------------------------------------------------------------ reshaping verbs


def test_add_and_remove_are_modes_rather_than_guesses():
    """A bare click on a shape you are editing is ambiguous — new point, or the start of
    a drag? A mode answers that before you click instead of surprising you after."""
    src = _code()
    assert _has("let _vertMode='move'", src)
    assert "function setVertMode(" in src
    assert "id=\"deAdd\"" in src and "id=\"deRm\"" in src


def test_a_new_point_lands_on_the_segment_it_was_clicked_on():
    body = _fn("_nearestSeg")
    assert "map.project" in body, "distance is measured in degrees, not on screen"
    assert "Math.hypot" in body


def test_segment_distance_is_measured_on_SCREEN_not_in_degrees():
    """A longitude degree is about 0.67 of a latitude one at this latitude, so a
    degree-space distance quietly favours north-south edges."""
    body = _fn("_nearestSeg")
    assert "e.lngLat" not in body
    assert "const P=map.project(pt)" in body


def test_a_click_that_misses_the_outline_does_nothing():
    """Rather than inserting a point wherever the nearest edge happens to be."""
    body = _fn("_addVertAt")
    assert _has("seg.d>24", body)


def test_a_shape_cannot_be_reduced_below_a_shape():
    """Refusing beats silently producing a degenerate ring whose area is nonsense."""
    body = _fn("_removeVert")
    assert "toastDraw" in body
    assert _has("r.length<=", body)


def test_removing_the_first_corner_keeps_the_ring_closed():
    """A polygon repeats its first point last. Splicing index 0 without repairing the
    closure leaves an open ring, and every area calculation after it is wrong."""
    body = _fn("_removeVert")
    assert _has("r[r.length-1]=r[0].slice()", body)


# --------------------------------------------------- the boundary is editable too


def test_the_boundary_can_still_be_reshaped_after_leaving_the_drawings_list():
    """Moving it out of `drawSaved` would otherwise have made it the one shape that
    cannot be edited."""
    src = _code()
    assert _has("const _AOI_EDIT_ID=-1", src)
    body = _fn("_drawById")
    assert "_AOI_EDIT_ID" in body


def test_every_edit_verb_writes_back_to_the_draft():
    """`_aoiFeature` builds a NEW object on each lookup, so an edit to it is discarded
    unless copied back — and forgetting it in one of the three verbs would make exactly
    one of drag/add/remove silently do nothing."""
    src = _code()
    assert src.count("_aoiWriteBack(") >= 4, "not every verb writes back"
    for fn in ("_vertMove", "_removeVert", "_addVertAt"):
        assert "_aoiWriteBack" in _code()[_code().index(f"function {fn}("):][:1400], fn
