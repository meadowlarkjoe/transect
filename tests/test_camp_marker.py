"""A camp draws a camp, not a site index (T10.5).

Reported: "For a camp style hunt we use to show a CAMP icon with a cabin at the camp
location. Now it just shows a number 1 in a circle."

THREE FAULTS STACKED, and only the third is the durable one.

  1. In fixed-camp mode the camp is also `draft.sites[0]`, so `drawDraft` emitted a
     numbered site dot — an amber circle labelled "1" — at the identical coordinate as
     the camp badge. Numbering a single camp "1" says nothing to begin with.
  2. `setTab` hides `draft-fill` / `draft-line` off Setup and hides `draft-camp` once a
     result exists, but never hid `draft-site` / `draft-site-n`. The Setup preview dots
     survived onto Overview, Field and Brief, on top of the analysis's own markers.
  3. THE ACTUAL DISAPPEARANCE. A MapLibre symbol carrying both an icon and a label is
     placed as a UNIT. With neither part optional, a label that cannot be placed takes
     the ICON down with it — `icon-allow-overlap` exempts the icon from collision
     testing, not the pair. The numbered dot sets `text-allow-overlap`, so it always
     wins the collision, and the camp's own "A" losing it deleted the cabin.

Fault 3 is why this file exists: 1 and 2 are specific mistakes, but any symbol layer that
grows a label can reintroduce the vanishing icon. The invariant is checked over ALL of
them, not just the camp.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _symbol_layers():
    """Every addLayer({type:'symbol'}) block, as (id, body)."""
    src = APP.read_text()
    out = []
    for m in re.finditer(r"addLayer\(\{id:'([^']+)',type:'symbol'", src):
        i = m.start()
        depth, j = 0, src.index("{", i + len("addLayer("))
        for k in range(j, len(src)):
            if src[k] == "{":
                depth += 1
            elif src[k] == "}":
                depth -= 1
                if depth == 0:
                    out.append((m.group(1), src[i:k + 1]))
                    break
    return out


def test_no_symbol_layer_can_lose_its_icon_to_its_own_label():
    """THE INVARIANT. An icon that vanishes because its label collided is a marker the
    hunter cannot see and cannot explain — which is exactly how this was reported."""
    bad = [lid for lid, body in _symbol_layers()
           if "icon-image" in body and "text-field" in body
           and "'text-optional':true" not in body.replace(" ", "")]
    assert not bad, (
        f"symbol layers carry both an icon and a label without text-optional: {bad}. "
        f"A label that cannot be placed will take the icon with it.")


def test_there_are_symbol_layers_with_both_to_check():
    """Guards the test above from passing vacuously if the parser stops matching."""
    both = [lid for lid, body in _symbol_layers()
            if "icon-image" in body and "text-field" in body]
    assert "camps" in both and "draft-camp" in both, both


def test_the_camp_is_not_drawn_as_a_numbered_site():
    src = APP.read_text()
    i = src.index("function drawDraft(")
    body = src[i:src.index("\nlet _boxCleanup", i)]
    dot = body.index("properties:{site:1,n:String(i+1)}")
    guard = body.rindex("if(!draft.fixedCampMode)", 0, dot)
    assert dot - guard < 120, "the numbered site dot is drawn for a fixed camp again"


def test_the_setup_preview_dots_do_not_survive_onto_the_analysis():
    src = APP.read_text()
    i = src.index("const dv=(name==='setup')?'visible':'none';")
    seg = src[i:i + 400]
    for lid in ("draft-fill", "draft-line", "draft-site", "draft-site-n"):
        assert f"'{lid}'" in seg, f"{lid} is not hidden off Setup"


def test_the_camp_still_has_an_icon_at_all():
    """The other way to show no cabin: ask for an image nobody registered."""
    src = APP.read_text()
    icon_for = src[src.index("const ICON_FOR"):]
    icon_for = icon_for[:icon_for.index("};")]
    assert re.search(r"base_camp:'(\w+)'", icon_for)
    glyph = re.search(r"base_camp:'(\w+)'", icon_for).group(1)
    icons = pathlib.Path("app/icons.js").read_text()
    assert re.search(rf'^\s*"?{glyph}"?\s*:', icons, re.M), \
        f"base_camp maps to glyph '{glyph}', which icons.js does not define"
    shape = src[src.index("const SHAPE = {"):]
    assert "base_camp:" in shape[:shape.index("};")], \
        "base_camp left SHAPE, so addIcons no longer registers the image"
