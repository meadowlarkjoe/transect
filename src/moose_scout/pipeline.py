"""Stage orchestration. Stages operate on cached files, so each can run
independently and re-runs are cheap. `run_all` executes the full chain."""
from __future__ import annotations

from collections.abc import Callable

from .config import Context

# Ordered analysis chain (the legal gate runs first, separately, in the CLI).
STAGES: dict[str, Callable[[Context], None]] = {}


def _register() -> None:
    from . import access, behavior, contract, habitat, synth, terrain
    from . import export as export_stage
    from .acquire import run as acquire_run

    STAGES.update(
        acquire=acquire_run,
        terrain=terrain.run,
        habitat=habitat.run,
        behavior=behavior.run,
        access=access.run,
        synth=synth.run,
        export=export_stage.run,
        contract=contract.build,
    )


def run_stage(name: str, ctx: Context) -> None:
    if not STAGES:
        _register()
    if name not in STAGES:
        raise KeyError(f"unknown stage {name!r}; known: {', '.join(STAGES)}")
    STAGES[name](ctx)


def run_all(ctx: Context) -> None:
    if not STAGES:
        _register()
    for name in STAGES:
        run_stage(name, ctx)
