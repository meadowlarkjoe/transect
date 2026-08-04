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


@pytest.mark.skipif(not os.path.isdir(CACHE), reason="needs the engine cache (runs in-container)")
@pytest.mark.parametrize("style", ["spike", "vehicle"])
def test_synth_runs_for_hunt_style(style):
    from moose_scout.config import Context
    from moose_scout import synth
    ctx = Context.for_aoi("fire_lake")
    ctx.aoi.hunter.hunt_style = style
    synth.run(ctx)   # must not raise
