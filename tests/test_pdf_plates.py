"""A plate has to show the PLAN, not a picture of the ground (T10.6).

Reported: "None of the analysis / polygons / waypoints / etc. render on the PDF." The
exported document carried exactly one image per plate page, and every one of them was
basemap.

THE CAUSE, and it is worth stating plainly because T9.7 shipped this and declared it
done: the offscreen map used for plates was built from `baseStyle()` — imagery and
nothing else — and then `_plateShot` called `setLayoutProperty` on the plan layer ids.
Every one of those calls sat behind `if(m.getLayer(id))`, which was always false, so
every one silently did nothing. Five plates, all basemap, for weeks.

That is the same failure this codebase keeps producing: a name matched in one namespace
and defined in another, guarded in a way that turns "missing" into "quietly skipped".
"""
import pathlib
import re

import pytest

APP = pathlib.Path("app/app.js")


def _fn(name):
    src = APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


def _plate_map_src():
    src = APP.read_text()
    i = src.index("async function _plateMap(")
    return src[i:src.index("\nasync function ", i + 10)]


def test_the_plate_map_is_built_from_the_live_style():
    """THE BUG. `baseStyle()` is imagery only — a map built from it has no plan layers,
    so nothing the plate asks for can exist on it."""
    src = _plate_map_src()
    assert "map.getStyle()" in src, "the plate map is not built from the live style"
    assert "style:baseStyle()" not in src.replace(" ", ""), \
        "the plate map is back on a bare basemap"


def test_the_plate_map_registers_the_same_images():
    """Images are NOT part of a serialised style. A symbol layer whose icon is missing
    draws nothing — the same silent blank, one level down."""
    src = _plate_map_src()
    assert "addIcons(m)" in src and "registerPatterns(m)" in src


def test_the_image_helpers_can_target_a_map_other_than_the_live_one():
    for fn in ("registerPatterns", "addIcons"):
        body = _fn(fn)
        assert "tgt" in body, f"{fn} still hardcodes the on-screen map"
        assert "const M=tgt||map" in body


def test_every_plate_row_resolves_to_real_layers():
    """A plate naming a row that maps to nothing is a silently empty plate. The rows are
    matched against BOTH the legend key and its layer group, because the huntability
    bands are three rows sharing one group."""
    src = APP.read_text()
    plates = src[src.index("const PLATES=["):]
    plates = plates[:plates.index("\n];")]
    rows = set(re.findall(r"rows:\[([^\]]*)\]", plates))
    named = {r.strip().strip("'\"") for grp in rows for r in grp.split(",") if r.strip()}

    lyr = src[src.index("const LYR_MAP="):]
    lyr = lyr[:lyr.index("]};") + 1]
    groups = set(re.findall(r"([a-zA-Z0-9_]+):\s*\[", lyr))
    keys = set(re.findall(r"\{k:'([a-zA-Z0-9_-]+)'", src[src.index("const LAYERS=["):]))

    missing = {n for n in named if n not in groups and n not in keys}
    assert not missing, f"plates name rows that resolve to no layer: {sorted(missing)}"


def test_a_plate_with_no_plan_layers_says_so():
    """The durable protection. Silence is what let this ship: a blank plate looked
    exactly like a working one."""
    src = APP.read_text()
    i = src.index("async function _plateShot(")
    body = src[i:src.index("\nfunction ", i + 10)]
    assert "no plan layers" in body, "a blank plate is silent again"


def test_plates_are_flat_and_framed_on_the_plan():
    """A pitched hillshade is a picture; a plate framed on wherever the hunter was
    looking can miss the focus areas entirely, which is as useless as a blank one."""
    src = _plate_map_src()
    assert "setTerrain(null)" in src
    assert "fitBounds" in src
