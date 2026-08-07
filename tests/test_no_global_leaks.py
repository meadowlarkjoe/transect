"""No test may change the world for the tests that come after it (T0.4).

THE BUG THIS CLOSES. `test_legal.py` set `MOOSE_SCOUT_CACHE` with a plain assignment at
MODULE IMPORT, to get itself a hermetic empty cache. That is a reasonable thing to want
and a ruinous way to get it: from the moment pytest merely COLLECTED that file, every
later test in the session resolved its cache to that temp directory. `test_synth_smoke`
then looked for fire_lake's rasters somewhere they had never been written and died with
`RasterioIOError: .../fire_lake/huntability.tif` in about five seconds — instead of
running the real ~95 s pipeline it exists to exercise.

Run alone it passed. Run in the suite it failed whatever the engine code did. A test that
always fails cannot report a regression, so three synth checks were silently worth
nothing, and any real synth break would have been indistinguishable from the noise.

Two fixes, and this file guards the general form of both:
  * isolation has to UNDO ITSELF — an autouse fixture with monkeypatch, never a plain
    assignment at import;
  * a skip guard has to resolve state THE SAME WAY the test does, so a leak from anywhere
    makes the test skip honestly rather than fail and blame the code.
"""
import ast
import pathlib

import pytest

TESTS = pathlib.Path(__file__).parent

# Environment variables that change where the engine reads and writes. Setting any of
# these at import time reaches every test collected afterwards.
GLOBAL_ENV = {"MOOSE_SCOUT_CACHE", "MOOSE_SCOUT_OUTPUTS", "GEOCACHE", "FINE_NECKS",
              "HRDEM", "OVERPASS_URL", "ACQUIRE_SOURCE_TIMEOUT"}


def _module_level_env_writes(path):
    """`os.environ[...] = ...` or `os.environ.update(...)` at module scope."""
    tree = ast.parse(path.read_text())
    out = []
    for node in tree.body:                      # module scope only — that is the point
        # A function or class BODY does not run at import, so an assignment inside one
        # is function-scoped and harmless. Walking into them made this flag a test that
        # sets an env var inside itself, which is not the bug.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assign):
                for tgt in sub.targets:
                    if (isinstance(tgt, ast.Subscript)
                            and isinstance(tgt.value, ast.Attribute)
                            and tgt.value.attr == "environ"):
                        key = getattr(tgt.slice, "value", None)
                        out.append(key)
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "update"
                    and isinstance(sub.func.value, ast.Attribute)
                    and sub.func.value.attr == "environ"):
                out.append("<update>")
    return [k for k in out if k is not None]


@pytest.mark.parametrize("path", sorted(TESTS.glob("test_*.py")), ids=lambda p: p.name)
def test_no_test_module_sets_a_path_env_var_at_import(path):
    """THE ONE THAT MATTERS. `os.environ[...] = ...` at module scope fires on COLLECTION
    and never undoes itself, so it reaches every test in the session — including ones in
    other files that have no idea it happened."""
    leaked = [k for k in _module_level_env_writes(path) if k in GLOBAL_ENV or k == "<update>"]
    assert not leaked, (
        f"{path.name} sets {leaked} at import time. Use an autouse fixture with "
        f"monkeypatch.setenv so the isolation undoes itself — this is exactly how "
        f"test_synth_smoke was made to fail for reasons that had nothing to do with synth.")


def test_setdefault_is_still_allowed():
    """`os.environ.setdefault` is fine and several modules rely on it: it only fills a
    gap and cannot steal a value a real run set. The check above must not ban it."""
    src = (TESTS / "test_legal.py").read_text()
    assert "os.environ.setdefault" in src
    assert not _module_level_env_writes(TESTS / "test_legal.py")


def test_the_smoke_guard_resolves_the_cache_the_way_the_test_does():
    """A skip guard that checks a hardcoded path while the test resolves through the
    environment is how a leak turns into a failure instead of a skip."""
    src = (TESTS / "test_synth_smoke.py").read_text()
    assert "cache_dir(\"fire_lake\")" in src, \
        "the skip guard no longer resolves the cache the way the test does"
    assert "not os.path.isdir(CACHE)" not in src, \
        "the hardcoded skip guard is back — a leak will fail instead of skipping"
