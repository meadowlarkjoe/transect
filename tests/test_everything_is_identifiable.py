"""If it is drawn, you can ask what it is. No exceptions, and no reminders needed.

Reported, and fairly: "no tooltip / explainability for the abri sommarie/ shelters.
everything should have that i shoudlnt have to mention this."

IDENTIFY's own header has said this from the start — "Every drawn thing on this map is a
claim, and a claim you can't name is worse than one you can't see" — and eight layers were
shipping without one anyway: the feeding-edge band, thermal drift, all five travel-mode
legs, and boundaries. The principle was written down and nothing enforced it, so each new
layer was one more chance to forget.

This is the enforcement. It is deliberately a GATE rather than a list of eight fixes,
because the fixes age out and the gate does not.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _block(start, end):
    src = APP.read_text()
    i = src.index(start)
    return src[i:src.index(end, i)]


def _identify_layer_ids():
    return set(re.findall(r"\{lyr:'([^']+)'", _block("const IDENTIFY = [", "\n];")))


def _lyr_map():
    blk = _block("const LYR_MAP=", "]};") + "]"
    out = {}
    for m in re.finditer(r"([a-zA-Z0-9_-]+):\[([^\]]*)\]", blk):
        out[m.group(1)] = [x.strip().strip("'") for x in m.group(2).split(",") if x.strip()]
    return out


def _drawable_rows():
    """(legend key, layer ids) for every row that actually draws something."""
    blk = _block("const LAYERS=[", "\n];")
    lyr = _lyr_map()
    rows = []
    marks = [(m.start(), m.group(1)) for m in re.finditer(r"\{k:'([a-zA-Z0-9_-]+)'", blk)]
    for n, (i, k) in enumerate(marks):
        j = marks[n + 1][0] if n + 1 < len(marks) else len(blk)
        seg = re.sub(r"//[^\n]*", "", blk[i:j])
        m = re.search(r"lyr:'([a-zA-Z0-9_-]+)'", seg)
        if not m:
            continue                      # parent rows draw nothing of their own
        ids = lyr.get(m.group(1)) or []
        if ids:
            rows.append((k, ids))
    return rows


def _raster_layer_ids():
    """Layers declared in the BASE STYLE as raster tiles.

    The one honest exemption below. `queryRenderedFeatures` returns FEATURES, and a
    raster tile has none — there is nothing to hand a hover card. `boundaries` is an Esri
    reference-tile overlay, so an entry for it could never fire; adding one looked like
    coverage and would have been dead wiring. That is a real limit, not a lowered bar,
    which is why it is named here rather than waved through.
    """
    src = APP.read_text()
    i = src.index("function baseStyle(")
    blk = src[i:src.index("\nfunction ", i + 10)]
    return set(re.findall(r"\{id:'([^']+)',type:'raster'", blk))


def test_every_drawn_VECTOR_layer_can_be_identified():
    """THE GATE. A layer the hunter can switch on and cannot interrogate is a coloured
    shape with no claim attached — and they should not have to report each one."""
    ident = _identify_layer_ids()
    raster = _raster_layer_ids()
    gaps = []
    for k, ids in _drawable_rows():
        vector = [i for i in ids if i not in raster]
        if not vector:
            continue                      # raster-only row — see above
        if not any(i in ident for i in vector):
            gaps.append(k)
    assert not gaps, (
        "these layers draw and cannot be identified: " + ", ".join(sorted(gaps)))


def test_the_raster_exemption_covers_exactly_one_row_and_not_more():
    """It is a limit of raster tiles, so it must never quietly grow into a way of
    excusing a vector layer somebody did not want to write a card for."""
    raster = _raster_layer_ids()
    assert "boundaries" in raster
    excused = [k for k, ids in _drawable_rows() if all(i in raster for i in ids)]
    assert excused == ["boundaries"], excused


def test_the_gate_is_actually_looking_at_something():
    """A gate that silently matches nothing passes forever."""
    rows = _drawable_rows()
    assert len(rows) > 20, f"only found {len(rows)} drawable rows — the parser is broken"
    assert len(_identify_layer_ids()) > 20


def test_identify_never_points_at_a_layer_that_is_not_drawn():
    """The reverse failure: an entry for a layer id that no longer exists is dead weight
    that quietly never fires."""
    src = APP.read_text()
    added = set(re.findall(r"addLayer\(\{id:'([^']+)'", src))
    # layers added dynamically by helper (shooters/scent/annotations) are legitimate too
    dynamic = {"shooters", "shooters-label", "shooterLines", "scent", "scent-label", "scentArc"}
    dangling = {l for l in _identify_layer_ids() if l not in added and l not in dynamic}
    assert not dangling, f"IDENTIFY points at layers that are never added: {sorted(dangling)}"


def test_the_travel_legs_each_say_what_they_are_travelled_by():
    """They exist because a walk and a carry are not the same trip (T10.20). An unnamed
    coloured line is exactly the confusion that ticket was written for."""
    blk = _block("const IDENTIFY = [", "\n];")
    for lid in ("route-ride-atv", "route-ride-boat", "route-foot-trail",
                "route-foot-bush", "route-portage"):
        assert f"{{lyr:'{lid}'," in blk, f"{lid} has no hover entry"


def test_the_machine_staying_put_is_said_where_it_matters():
    """The single most consequential thing about a ride leg, and it was only ever in a
    commit message and a legend note."""
    blk = _block("const IDENTIFY = [", "\n];")
    i = blk.index("{lyr:'route-ride-atv',")
    assert "stays where you step off" in blk[i:i + 700]
