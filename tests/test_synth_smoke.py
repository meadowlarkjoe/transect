"""Synth must not crash on either hunt style.

The vehicle path derived its camp from area_stage before that dict was built —
an UnboundLocalError that only the vehicle branch hit, so a spike-only check
(what the original road-following verification used) sailed past it. This runs the
synth stage on a cached AOI in BOTH modes.
"""
import os
import shutil
import tempfile

import pytest


CACHE = "/app/cache/fire_lake"   # present only inside the engine container


def _cache_ready():
    """Is fire_lake's cache there IN THE PLACE THIS TEST WILL ACTUALLY LOOK?

    The skip used to test the hardcoded path above while the test itself resolved the
    cache through MOOSE_SCOUT_CACHE. When another module leaked that env var (T0.4 —
    test_legal set it at import time), the two disagreed: the guard saw the container
    cache and let the test run, the test looked somewhere empty and died on a missing
    raster in five seconds. It failed whatever the engine did, so it could not report a
    real synth regression.

    Resolving the same way the test does means a leak from anywhere makes this SKIP —
    honestly — instead of failing and blaming the code.
    """
    try:
        from moose_scout.config import cache_dir
        return (cache_dir("fire_lake") / "huntability.tif").exists()
    except Exception:
        return os.path.isdir(CACHE)


_SKIP = pytest.mark.skipif(not _cache_ready(),
                           reason="needs fire_lake's cache where this run resolves it")


@_SKIP
@pytest.mark.parametrize("style", ["spike", "vehicle"])
def test_synth_runs_for_hunt_style(style):
    from moose_scout.config import Context
    from moose_scout import synth
    ctx = Context.for_aoi("fire_lake")
    ctx.aoi.hunter.hunt_style = style
    synth.run(ctx)   # must not raise


def _routes(ctx):
    """Route features written by the run, by legend."""
    import json
    from moose_scout.config import cache_dir
    fc = json.loads((cache_dir(ctx.aoi.name) / "features.geojson").read_text())
    out = {}
    for f in fc["features"]:
        lg = f["properties"].get("legend") or ""
        if lg.startswith("route_"):
            out[lg] = out.get(lg, 0) + 1
    return out


@_SKIP
def test_a_camp_hunt_still_gets_routes():
    """A HUNT FROM A FIXED CAMP MUST STILL DRAW HUNT LINES.

    THE BUG THIS EXISTS FOR. Routing reconstructed its anchors by scanning the output
    features for `base_camp` pins. Then a hunt from a camp the hunter placed themselves
    correctly stopped emitting that pin — you do not hand someone their own input back as
    a recommendation — and routing lost the only thing it was anchored to. camp_by_area
    came back empty, sites_of() skipped every area for want of a camp, and every route
    vanished: zero hunt lines, zero access legs, on precisely the hunt style where the
    camp is the least ambiguous thing on the map. Nothing raised. The layer read NO DATA
    and the run looked successful.

    The two parametrised cases above BOTH passed against that broken code, because
    neither of them sets a fixed camp. A test only earns its keep if it would have failed.
    """
    from moose_scout.config import Context
    from moose_scout import synth
    ctx = Context.for_aoi("fire_lake")

    # A reference run with no fixed camp, to prove this AOI produces routes at all —
    # otherwise a zero below could just mean "nothing routable here" and the test would
    # be asserting the weather.
    synth.run(ctx)
    baseline = _routes(ctx)
    assert baseline, "AOI produces no routes even without a fixed camp — test is blind"

    # Now the same ground, hunted from a camp the hunter placed. Put it on a cell the
    # model already chose as good ground so the case is realistic rather than adversarial.
    import json
    from moose_scout.config import cache_dir
    fc = json.loads((cache_dir(ctx.aoi.name) / "features.geojson").read_text())
    area = next(f for f in fc["features"] if f["properties"].get("legend") == "focus_area")
    lon, lat = area["properties"]["centroid"] if "centroid" in area["properties"] else \
        area["geometry"]["coordinates"][0][0]

    ctx2 = Context.for_aoi("fire_lake")
    ctx2.aoi.hunter.fixed_camp = (lat, lon)
    ctx2.aoi.hunter.hunt_radius_km = 8.0
    ctx2.aoi.hunter.walk_hunt_km = 8.0
    synth.run(ctx2)
    camped = _routes(ctx2)

    assert camped, (
        "a fixed-camp hunt produced NO routes at all — the camp is known, the stands are "
        f"placed, and nothing joins them (baseline without a fixed camp: {baseline})")


@_SKIP
def test_routing_anchors_are_passed_in_not_rediscovered():
    """Guard the shape of the fix, not just this one symptom.

    Whether a camp gets DRAWN is a display decision. Whether routing knows where the
    hunter sleeps is not. Re-deriving the second from the first is what broke, so the
    anchor stays an argument.
    """
    import inspect
    from moose_scout import synth
    sig = inspect.signature(synth._add_routes)
    assert "camp_of_area" in sig.parameters, \
        "_add_routes must take its anchors as an argument, not scan for base_camp pins"
    src = inspect.getsource(synth.run)
    assert "camp_of_area=camp_of_area" in src, \
        "synth.run computes camp_of_area but stopped handing it to routing"
