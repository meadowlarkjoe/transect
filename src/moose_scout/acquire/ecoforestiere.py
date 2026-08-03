"""Écoforestière stand data (species/age/height/density + dated perturbations).

The habitat backbone. Normalizes raw peuplement attributes into the cover_type
codes used by config/species/moose.yaml (coupe_recente, regeneration, resineux,
tourbiere, ...) and computes exact STAND AGE from perturbation dates so we can
project when a cut peaks as browse. North of ~52°N coverage thins — the caller
then leans on the Sentinel-2 fallback (see sentinel.py) and flags lower
confidence.
"""
from __future__ import annotations

from ..config import Context

# Raw MRNF class/perturbation codes -> our normalized cover_type keys.
# Filled in against real attribute values on first pull (verify_on_first_pull).
COVER_CODE_MAP: dict[str, str] = {}


def fetch(ctx: Context) -> None:
    """TODO(P2): WFS pull of carte-ecoforestiere-avec-perturbations for the bbox;
    normalize to cover_type + stand_age_years; rasterize to the working grid as
    cache/<aoi>/cover.tif and cache/<aoi>/stand_age.tif."""
    raise NotImplementedError("écoforestière fetch — P2")
