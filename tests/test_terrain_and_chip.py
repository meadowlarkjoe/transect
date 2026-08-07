"""3D is one state, and the chip reports it (T10.11 + T10.10).

Two halves of one complaint: "If i hold right and move my mouse click i can enter 3D
mode, but the basemap icon still shows 2D and the 3D terrain mode isnt activated."

T10.11 — TWO INDEPENDENT THINGS WORE THE NAME "3D". The map is built with `maxPitch:80`,
so a right-drag tilts the CAMERA. The terrain MESH was turned on only by the `#terr3d`
checkbox, and the exaggeration slider was guarded by `if(terrOn)`. Tilt without the
checkbox therefore gave a pitched FLAT map and a dead slider. Pitch is now the only
input; the checkbox is a shortcut that tilts the camera, and terrain follows.

T10.10 — THE CHIP WAS A CONSTANT. `<b>SAT</b><i>2D</i>`, written once into innerHTML and
wired to nothing, so it said SAT on Relief and 2D at 60 degrees of pitch. A status
readout that cannot be wrong is not a status readout.
"""
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\n}", i) + 2]


# ----------------------------------------------------------------- T10.10, the chip


def test_the_chip_is_not_a_constant():
    """THE BUG, stated as the thing that must never come back. Checked where the chip is
    BUILT — the string appears in a comment above, which is the point of the comment."""
    src = APP.read_text()
    i = src.index("mc.innerHTML=")
    block = src[i:src.index("`;", i)]
    assert 'id="mcSat"' in block, "the chip moved; this test is looking in the wrong place"
    assert "<b>" not in block.split('id="mcSat"')[1].split("</button>")[0], \
        "the chip is a hardcoded string again"


def test_the_chip_is_rendered_from_the_live_basemap_and_the_live_pitch():
    body = _fn("syncBaseChip")
    assert "BASE_CHIP[curBase]" in body, "the chip does not read the current basemap"
    assert "terrOn?'3D':'2D'" in body.replace(" ", ""), "the chip does not read terrain state"


def test_every_basemap_has_a_chip_label():
    """A basemap with no abbreviation would silently fall back to 'MAP' — which is the
    same not-a-readout failure in a quieter form."""
    src = APP.read_text()
    bases = re.search(r"const BASEMAPS=\[([^\]]*)\]", src).group(1)
    bases = {b.strip().strip("'\"") for b in bases.split(",") if b.strip()}
    chip = re.search(r"const BASE_CHIP=\{([^}]*)\}", src).group(1)
    have = set(re.findall(r"(\w+)\s*:", chip))
    assert bases <= have, f"no chip label for {sorted(bases - have)}"


def test_the_chip_is_resynced_when_the_basemap_changes():
    assert "syncBaseChip()" in _fn("switchBase")


# --------------------------------------------------------------- T10.11, one state


def test_terrain_is_derived_from_pitch_not_from_a_checkbox():
    body = _fn("applyTerrain")
    assert "map.getPitch()>TERRAIN_PITCH" in body.replace(" ", "")
    assert "terrOn=want" in body.replace(" ", ""), \
        "terrOn is not derived from the camera — it is a second state again"


def test_pitching_the_camera_is_what_turns_terrain_on():
    src = APP.read_text()
    assert "map.on('pitch',applyTerrain)" in src.replace(" ", ""), \
        "nothing reacts to pitch, so a right-drag still gives a pitched flat map"


def test_dropping_back_to_flat_releases_terrain():
    body = _fn("applyTerrain").replace(" ", "")
    assert "map.setTerrain(null)" in body


def test_the_checkbox_only_moves_the_camera():
    """If the checkbox still called setTerrain itself there would be two owners again,
    and they could disagree — which is the whole ticket."""
    src = APP.read_text()
    i = src.index("#terr3d').onchange")
    handler = src[i:src.index("};", i)]
    assert "easeTo" in handler and "pitch" in handler
    assert "setTerrain" not in handler, "the checkbox owns terrain again"


def test_the_exaggeration_slider_does_not_wait_for_a_checkbox():
    src = APP.read_text()
    i = src.index("#terrExag').oninput")
    handler = src[i:src.index("};", i)]
    assert "applyTerrain()" in handler
    assert "if(terrOn)" not in handler.replace(" ", ""), \
        "the slider is gated on the old checkbox state again"


def test_terrain_is_not_rebuilt_on_every_frame_of_the_ease():
    """`pitch` fires per frame; setTerrain per frame is a mesh rebuild per frame. The
    applied exaggeration is remembered so the call is idempotent."""
    body = _fn("applyTerrain")
    assert "_terrExagApplied" in body


def test_the_dem_source_terrain_asks_for_actually_exists():
    src = APP.read_text()
    assert re.search(r"dem:\{type:'raster-dem'", src), \
        "setTerrain({source:'dem'}) has no dem source to bind to"


def test_terrain_is_not_applied_before_the_style_is_loaded():
    """Caught in a live browser, not by any of the tests above: `setTerrain` throws
    "Style is not done loading" if it runs first, and a pitch event can arrive before
    load (a restored camera, an easeTo on open). An exception thrown inside a map
    listener is not a contained failure."""
    body = _fn("applyTerrain")
    assert "catch" in body and "map.once('idle',applyTerrain)" in body.replace(" ", "")
    assert "map.once('load'" not in body.replace(" ", ""), (
        "retrying on `load` is the trap: it fires once, but isStyleLoaded() drops back "
        "to false on every ordinary source update, so anyone tilting just after a plan "
        "opens would silently get no terrain — this ticket's bug in a new hat")
