"""Region resolver + coverage manifest (E2).

A REGION PROFILE is the set of assumptions that change when you leave a place:
which legal regime governs the hunt, and which data sources exist and how far each
one reaches. Before E2 the engine hardcoded Québec everywhere and a species'
``region_profile`` was read by nothing. Now the species names a profile
(``config/regions/<profile>.yaml``), this module loads it, and downstream code READS
it instead of a constant:

  * ``legal.py`` dispatches on ``legal_regime`` — a regime the engine doesn't
    implement raises loudly rather than silently applying Québec law elsewhere;
  * ``acquire`` skips a source whose coverage envelope excludes the AOI;
  * ``contract.py`` emits a per-run COVERAGE MANIFEST from the profile's ``sources``
    — the honest "what actually covered your box" readout the app shows.

Only the Québec regime is implemented today. A new region is a new yaml here plus
its data adapters; the *shape* the rest of the engine reads does not change.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from .config import Context, _load_yaml, config_dir

# Legal regimes legal.py actually implements. A profile naming anything else gets a
# loud "unverified — engine implements Québec regs only" flag, never silent QC law.
SUPPORTED_REGIMES = {"quebec"}

DEFAULT_PROFILE = "quebec_boreal"


def _fallback_region(profile: str) -> dict[str, Any]:
    """A minimal profile when no yaml exists — assume the Québec regime with no
    declared sources, so the manifest is empty rather than wrong."""
    return {
        "region_profile": profile or DEFAULT_PROFILE,
        "region": "quebec",
        "name_en": profile or DEFAULT_PROFILE,
        "legal_regime": "quebec",
        "sources": [],
    }


@lru_cache(maxsize=16)
def load_region(profile: str) -> dict[str, Any]:
    """Load a region profile by name (the value in a species' ``region_profile``)."""
    if not profile:
        profile = DEFAULT_PROFILE
    path = config_dir() / "regions" / f"{profile}.yaml"
    if not path.exists():
        return _fallback_region(profile)
    data = _load_yaml(path) or {}
    data.setdefault("region_profile", profile)
    data.setdefault("legal_regime", "quebec")
    data.setdefault("sources", [])
    return data


def resolve_region(ctx: Context) -> dict[str, Any]:
    """The region profile that governs this AOI — from its species' ``region_profile``."""
    return load_region(getattr(ctx.species, "region_profile", "") or DEFAULT_PROFILE)


def regime_supported(region: dict[str, Any]) -> bool:
    return (region.get("legal_regime") or "quebec") in SUPPORTED_REGIMES


def source_covers_aoi(cov: Optional[dict[str, Any]], bbox: tuple[float, float, float, float]) -> str:
    """One source's DECLARED coverage over an AOI bbox → 'in' | 'partial' | 'out'.

    Only hard latitude edges (``max_lat`` / ``min_lat``) are evaluated against the
    box; ``extent``/``country``/``region`` are descriptive and read as in-bounds
    (we can't cheaply test a national/provincial boundary here). 'partial' means the
    box straddles the edge — part of the AOI has the data, part falls back.
    """
    if not cov:
        return "in"
    _minlon, minlat, _maxlon, maxlat = bbox
    if "max_lat" in cov:
        lim = float(cov["max_lat"])
        if minlat >= lim:
            return "out"
        if maxlat > lim:
            return "partial"
    if "min_lat" in cov:
        lim = float(cov["min_lat"])
        if maxlat <= lim:
            return "out"
        if minlat < lim:
            return "partial"
    return "in"


def coverage_manifest(ctx: Context, region: Optional[dict[str, Any]] = None) -> list[dict[str, Any]]:
    """Per data source: is THIS AOI inside its declared coverage envelope?

    Pure and geo-free (bbox math only), so it's cheap and unit-testable. contract.py
    augments the result with the RUNTIME reality — did the source actually land a
    product in the cache — which needs the cache and so lives there, not here.
    """
    region = region or resolve_region(ctx)
    bbox = ctx.aoi.bbox_wgs84()
    out: list[dict[str, Any]] = []
    for s in region.get("sources", []) or []:
        status = source_covers_aoi(s.get("coverage"), bbox)
        entry = {
            "id": s.get("id"),
            "label": s.get("label_en", s.get("id")),
            "kind": s.get("kind"),
            "coverage": status,               # declared: in | partial | out
        }
        if status != "in" and s.get("out_caveat"):
            entry["note"] = s["out_caveat"]
        out.append(entry)
    return out
