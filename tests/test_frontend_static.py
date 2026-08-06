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


def test_unit_formatters_cannot_throw_on_a_missing_value():
    """A FORMATTER MUST NEVER TAKE DOWN THE PAGE.

    km(null) threw `null is not an object (evaluating 'v.toFixed')`, and because the
    analysis view renders in one pass, one missing number blanked the ENTIRE result. The
    value was camp.max_packin_km, which the contract emits as null — correctly — when a
    camp has no member areas; two of the six call sites passed it straight in.

    The engine is right to say "unknown" with a null. The display's job is to show that,
    not to explode: an unknown distance is a dash, not a blank screen. A stated ZERO is
    a different thing and must still print as a real number.
    """
    src = open(APP).read()
    assert "const km = (v) => !_n(v)" in src or "const km=(v)=>!_n(v)" in src, \
        "km() no longer guards a non-finite value before calling toFixed"
    assert "const metres = (m) => !_n(m)" in src or "const metres=(m)=>!_n(m)" in src, \
        "metres() no longer guards a non-finite value"
    # The guard has to be a FINITE test, not truthiness — otherwise a real 0 km becomes
    # a dash and the hunter is told we don't know a distance we measured as zero.
    assert "typeof v === 'number' && isFinite(v)" in src or \
           "typeof v==='number'&&isFinite(v)" in src, \
        "the guard must test finiteness, not truthiness — a measured 0 is not unknown"


def test_every_brief_plate_names_layers_that_exist():
    """A PLATES entry naming a key that resolves to nothing renders a blank map with a
    confident caption under it — the same silently-empty failure as a toggle that flips
    no layer, and harder to notice because a map plate always LOOKS like a map.

    Row keys and layer-group names live in different namespaces (the huntability bands
    are three rows sharing one `huntZones` group), so a plate may legitimately name
    either — but it must name something.
    """
    import re
    src = open(APP).read()
    plate_keys = set()
    for m in re.finditer(r"rows:\[([^\]]*)\]", src):
        plate_keys.update(re.findall(r"'([^']+)'", m.group(1)))
    row_keys = set(re.findall(r"\{k:'([^']+)'", src))
    lyr_vals = set(re.findall(r"lyr:'([^']+)'", src))
    lyr_map = set(re.findall(r"^\s*([A-Za-z0-9_-]+):\[", src, re.M))
    known = row_keys | lyr_vals | lyr_map
    unknown = sorted(k for k in plate_keys if k not in known)
    assert not unknown, f"brief plates name layers that do not exist: {unknown}"
