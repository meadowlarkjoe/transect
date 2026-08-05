"""Static gates on the front end. No browser — just the failure classes that have
actually shipped and cannot be caught by parsing alone."""
import subprocess
import os

ROOT = os.path.dirname(os.path.dirname(__file__))
APP = os.path.join(ROOT, "app", "app.js")


def test_no_layer_paint_type_mismatch():
    """A setPaintProperty on the wrong layer type throws at runtime and today took
    the whole tab bar down with it. Caught statically now."""
    r = subprocess.run(["node", os.path.join(ROOT, "scripts", "check_layer_paint.js"), APP],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_app_js_parses():
    r = subprocess.run(["node", "--check", APP], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _lyr_map(src):
    """The LYR_MAP object: {row key: [map layer ids]}. Sliced textually because the
    file is not a module we can import."""
    import re
    start = src.index("const LYR_MAP=")
    end = src.index("]};", start)          # the object ends on its last layer array
    body = src[start:end]
    out = {}
    for k, v in re.findall(r"([a-zA-Z0-9_]+):\s*(\[[^\[\]]*\])", body):
        ids = re.findall(r"'([^']+)'", v)
        if ids:                       # skip expression arrays, which are not layer lists
            out[k] = ids
    return out


def test_layer_rows_and_toggles_agree():
    """A LAYERS row whose key is missing from LYR_MAP draws a switch that controls
    nothing: it looks live and does nothing when clicked. The reverse — a LYR_MAP entry
    with no row — is dead wiring nobody can reach."""
    import re
    src = open(APP).read()
    start = src.index("const LAYERS=[")
    rows = set(re.findall(r"\{k:'([a-zA-Z0-9_]+)'", src[start:src.index("\n];", start)]))
    lyr = set(_lyr_map(src))
    assert not (rows - lyr), f"LAYERS rows with no LYR_MAP entry: {sorted(rows - lyr)}"


def test_toggled_layer_ids_exist():
    """Every map layer id a toggle flips must actually be added, or the toggle no-ops."""
    import re
    src = open(APP).read()
    # layers are added both singly and as style-spec arrays of {id:…} objects
    added = set(re.findall(r"addLayer\(\{\s*id:'([^']+)'", src))
    added |= set(re.findall(r"\{id:'([^']+)',type:'(?:raster|fill|line|symbol|circle)'", src))
    referenced = {i for ids in _lyr_map(src).values() for i in ids}
    unknown = sorted(referenced - added)
    assert not unknown, f"LYR_MAP references layer ids never added: {unknown}"
