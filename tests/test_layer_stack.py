"""Water is context and belongs under the model (reported from a live run).

Two separate faults, one symptom — "wetland is too opaque and blocks everything else.
waterways should be low in the layer stack".

  1. `applyLayer` FORCED every non-`solid` fill to 0.9, overriding whatever the layer was
     declared with. Wetland is added at 0.22 and was painted at 0.9. The value in the
     addLayer call was decorative — a per-layer choice that nothing honoured.
  2. Water was added ABOVE the huntability bands, the browse zones and the forest survey,
     so it covered the things the map is opened to read.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _code():
    return re.sub(r"//[^\n]*", "", APP.read_text())


def _order():
    return [m.group(1) for m in re.finditer(r"addLayer\(\{id:'([^']+)'", APP.read_text())]


def test_a_layer_may_keep_the_opacity_it_was_declared_with():
    src = _code()
    i = src.index("if(ty==='fill') map.setPaintProperty(id,'fill-opacity'")
    seg = src[i:i + 220]
    assert "r.alpha!=null?r.alpha" in seg.replace(" ", ""), \
        "the blanket 0.9 override is back and layer opacities are decorative again"


def test_wetland_states_its_own_alpha():
    src = _code()
    i = src.index("{k:'wetland',")
    row = src[i:src.index("\n {k:'", i + 5)]
    assert "alpha:0.22" in row.replace(" ", "")


def test_water_is_moved_beneath_the_model():
    src = _code()
    i = src.index("['lakes','lakes-line','rivers','wetlandZones','wetlandZones-line']")
    seg = src[i:i + 240]
    assert "map.moveLayer(id,'huntZones')" in seg.replace(" ", ""), \
        "water is not being sunk below the lowest model layer"


def test_the_specific_still_draws_over_the_general():
    """T10.4's rule has to survive the move: beaver pond over wetland over open water.
    Moving each before `huntZones` in this order preserves exactly that."""
    src = _code()
    i = src.index("['lakes','lakes-line','rivers','wetlandZones','wetlandZones-line']")
    lst = src[i:src.index("]", i)]
    assert lst.index("lakes") < lst.index("rivers") < lst.index("wetlandZones")


def test_beaver_ponds_are_not_sunk_with_the_fills():
    """They are POINTS. A dot hides nothing, and dropping it under the model would bury
    the one water feature that is a hunting FINDING rather than context."""
    src = _code()
    i = src.index("['lakes','lakes-line','rivers','wetlandZones','wetlandZones-line']")
    assert "beaverPonds" not in src[i:src.index("]", i)]


def test_the_reorder_runs_after_every_layer_it_names_exists():
    """moveLayer on a layer not yet added is a silent no-op."""
    src = APP.read_text()
    at = src.index("['lakes','lakes-line','rivers','wetlandZones','wetlandZones-line']")
    for lid in ("lakes", "lakes-line", "rivers", "wetlandZones", "wetlandZones-line", "huntZones"):
        assert src.index(f"addLayer({{id:'{lid}'") < at, f"{lid} is added after the reorder"
