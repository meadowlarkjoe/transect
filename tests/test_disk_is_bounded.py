"""The box's footprint has to be bounded, not proportional to how many people use it.

Asked: "once a plan is finished, does the unused data that was used during analysis get
pruned? Otherwise if we open this up to people its going to be carrying shitloads of data"

It did not. `_prune_caches` was written, documented, and NEVER CALLED. Measured on the
live droplet: 65 job caches against a stated RESCOPE_KEEP of 25, the oldest five days
old, 3.2 GB.

The two halves behaved differently and that is worth keeping straight. The GEOGRAPHY
cache was bounded the whole time — `acquire` calls `geocache.prune`, and it was sitting
at 8 slots against a cap of 12. It was only the PER-JOB caches growing without limit,
which is the half nobody checked because the other half looked fine.
"""
import inspect
import re

from moose_scout import api, geocache, jobstore


def test_the_job_cache_pruner_is_actually_called():
    """THE BUG. A pruner nobody calls is a comment about disk hygiene."""
    src = inspect.getsource(api)
    calls = [m for m in re.finditer(r"(?<!def )_prune_caches\(\)", src)]
    assert calls, "_prune_caches is defined and never called again"


def test_it_is_defined_before_the_thread_that_calls_it():
    """The reaper thread starts at import time and its body is inside a bare `except`.
    With the definition below it, a first tick that beat module load would raise
    NameError into that except and prune nothing, forever, in silence. It sleeps 30 s
    first so it happened to work — ordering it properly means it does not have to."""
    src = inspect.getsource(api)
    assert src.index("def _prune_caches") < src.index("threading.Thread(target=_reap_orphans")


def test_it_runs_on_the_reaper_rather_than_on_a_run():
    """Hanging cleanup off an analysis means a quiet week leaves the disk full. The
    reaper is the one thing guaranteed to tick regardless."""
    src = inspect.getsource(api._reap_orphans)
    assert "_prune_caches()" in src


def test_pruning_takes_the_outputs_with_the_cache():
    """`outputs/<job>/transect.json` is written per job too. Freeing 160 MB of rasters
    and leaving the document beside it is half a cleanup."""
    src = inspect.getsource(api._prune_caches)
    assert "outputs_dir" in src


def test_every_growing_store_has_a_stated_ceiling():
    """The actual answer to "will this carry shitloads of data". Each of these is a FIXED
    ceiling — more hunters means more rows in sqlite and more artefacts inside their own
    budget, not more of these."""
    from moose_scout import artifacts
    assert api.RESCOPE_KEEP > 0                      # job caches
    assert geocache.prune.__defaults__[0] > 0        # geography slots
    assert artifacts.BUDGET_BYTES > 0                # per-plan artefacts
    assert jobstore.prune.__defaults__[0] > 0        # job state


def test_a_cleanup_failure_cannot_take_the_api_down():
    src = inspect.getsource(api._prune_caches)
    assert "except Exception" in src
