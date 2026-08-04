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
