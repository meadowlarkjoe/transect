"""Configuration models and loaders.

All tunable knobs live in ``config/*.yaml``; this module validates them into
typed objects. Heavy geo libraries are NOT imported here so that lightweight
stages (e.g. ``legal``) and tests can load config without the full GDAL stack.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml
from pydantic import BaseModel, Field


# --- paths -------------------------------------------------------------------
def config_dir() -> Path:
    return Path(os.environ.get("MOOSE_SCOUT_CONFIG", "config"))


def assets_dir() -> Path:
    return Path(os.environ.get("MOOSE_SCOUT_ASSETS", "assets"))


def cache_dir(aoi: str) -> Path:
    root = Path(os.environ.get("MOOSE_SCOUT_CACHE", "cache"))
    d = root / aoi
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs_dir(aoi: str) -> Path:
    root = Path(os.environ.get("MOOSE_SCOUT_OUTPUTS", "outputs"))
    d = root / aoi
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f) or {}


# --- models ------------------------------------------------------------------
Residency = Literal["quebec_resident", "non_resident_canada", "non_resident_foreign"]
ExtractionMode = Literal["truck", "canoe", "atv", "backpack"]
# METHOD OF TAKE (T10.2). Not a label — it changes how close the animal has to come
# and therefore where the shooter sits, what the wicks are for, and whether a glassing
# knob is any use at all. Effective ranges are the ethical-shot conventions hunters
# actually work to, not equipment maxima.
Method = Literal["rifle", "bow", "muzzleloader"]
Watercraft = Literal["none", "canoe", "motor"]
HuntStyle = Literal["spike", "vehicle"]


def _walk(v, default: float, lo: float, hi: float) -> float:
    """Coalesce an unset walk distance, then clamp it.

    `is None`, never `or`. A hunter who answers 0 has told us something — that they
    will not walk that leg at all — and `v or default` silently replaces that answer
    with six kilometres, which then re-ranks their whole map. Unset and zero are
    different facts and only one of them gets a default.
    """
    if v is None:
        return default
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))



class LatLon(BaseModel):
    lat: float
    lon: float


class SeasonCfg(BaseModel):
    year: int
    target_dates: list[str] = Field(default_factory=list)
    weapon: str = "rifle"


class HunterCfg(BaseModel):
    residency: Residency = "quebec_resident"
    extraction_modes: list[ExtractionMode] = Field(
        default_factory=lambda: ["truck", "canoe", "atv", "backpack"]
    )
    party_size: int = 2
    # Setup constraints that must actually shape the spatial analysis:
    watercraft: Watercraft = "none"      # none → rivers are foot barriers, no water access
    hunt_style: HuntStyle = "spike"      # spike = can camp out; vehicle = return to truck nightly
    # What you are carrying. A window is usually a SEASON, and a season is usually a
    # weapon, so this is set per window (see worker.methods_of) and defaults to rifle.
    method: Method = "rifle"
    # Multi-select transportation from Setup ({"canoe","motor","atv"} -> bool). ATV/SxS is the
    # one that changes the model: tracks/trails become drivable, camp can sit further in, and
    # camp->hunt routes split into ride vs walk legs (see synth).
    transport: Dict[str, bool] = Field(default_factory=dict)
    # Known-sites mode: up to 4 (lat, lon) centres the hunter already has in mind, ranked
    # against each other. sites[0] doubles as the AOI centre.
    sites: Optional[List[Tuple[float, float]]] = None
    walk_access_km: float = 6.0          # how far off a road you'll walk in (road → camp/area)
    walk_hunt_km: float = 3.0            # how far from camp you'll hunt (camp → site)
    # HUNT-FROM-A-FIXED-CAMP. When set, the hunter has already chosen where they're
    # basing: skip camp-finding, anchor camp/staging THERE, and narrow the whole
    # analysis to a circle around it (they only hunt what they can walk from camp).
    fixed_camp: Optional[Tuple[float, float]] = None   # (lat, lon), or None for auto
    hunt_radius_km: Optional[float] = None             # analysis radius from a fixed camp


# How far beyond a DRAWN boundary the analysis still has to look (T10.8).
#
# The engine cannot answer about a parcel using only the parcel, and this is the whole
# reason the 5 km radius floor existed. `dist_road` measures to a road that is usually
# OUTSIDE the boundary. A land-bridge funnel needs the lakes on BOTH sides of the neck.
# TPI uses a 500 m window, the pinch test 600 m, and hunter pressure decays over 1.5 km.
# Analysed alone, a tight polygon would report "no access, no funnels" about ground that
# has both — confidently, which is the worst way to be wrong.
#
# 2.5 km clears every one of those windows with room to spare. It is padding on the
# ANALYSIS only: the reported features are clipped back to the ring.
DRAW_PAD_KM = 2.5


class AOI(BaseModel):
    """Area of interest — the unit of analysis.

    Two ways to say where: a CENTRE AND A RADIUS (the default), or a DRAWN RING. They
    meet at `bbox_wgs84()`, which is the single source of truth for the analysis extent —
    everything downstream builds on that rectangle and neither knows nor cares which mode
    produced it.
    """

    name: str
    title: str = ""
    species: str = "moose"
    center: LatLon
    bbox_halfwidth_km: float = 35.0
    # A drawn boundary as [(lon, lat), ...]. When set it REPLACES the radius as the
    # extent — padded for analysis, and clipped back to for reporting.
    ring: Optional[list[Tuple[float, float]]] = None
    pad_km: float = DRAW_PAD_KM
    zone_hint: Optional[str] = None    # documented zone until boundaries are wired
    season: SeasonCfg
    hunter: HunterCfg = Field(default_factory=HunterCfg)
    notes: str = ""

    @property
    def drawn(self) -> bool:
        return bool(self.ring) and len(self.ring) >= 4

    def bbox_wgs84(self) -> tuple[float, float, float, float]:
        """(minlon, minlat, maxlon, maxlat). Simple metric->degree approximation
        that is plenty accurate for an AOI-sized box at boreal latitudes.

        For a drawn AOI this is the ring's own bbox PADDED by `pad_km` — see DRAW_PAD_KM
        for why analysing the ring alone gives confidently wrong answers.
        """
        import math

        if self.drawn:
            lons = [p[0] for p in self.ring]
            lats = [p[1] for p in self.ring]
            mid = (min(lats) + max(lats)) / 2.0
            dlat = self.pad_km / 111.0
            dlon = self.pad_km / (111.0 * math.cos(math.radians(mid)))
            return (min(lons) - dlon, min(lats) - dlat,
                    max(lons) + dlon, max(lats) + dlat)
        hw_km = self.bbox_halfwidth_km
        dlat = hw_km / 111.0
        dlon = hw_km / (111.0 * math.cos(math.radians(self.center.lat)))
        return (
            self.center.lon - dlon,
            self.center.lat - dlat,
            self.center.lon + dlon,
            self.center.lat + dlat,
        )

    def effective_halfwidth_km(self) -> float:
        """Half the LONGER side of the analysis box, in km.

        Resolution scaling and the memory ceiling are sized from this rather than from
        `bbox_halfwidth_km`, because a drawn AOI's extent comes from its ring and the
        stored halfwidth would be describing a box that is not being analysed. One
        source of truth — `bbox_wgs84()` — and this reads it.
        """
        import math

        minlon, minlat, maxlon, maxlat = self.bbox_wgs84()
        mid = (minlat + maxlat) / 2.0
        km_lat = (maxlat - minlat) * 111.0
        km_lon = (maxlon - minlon) * 111.0 * math.cos(math.radians(mid))
        return max(km_lat, km_lon) / 2.0


class ModelCfg(BaseModel):
    version: int = 1
    working_crs: str = "EPSG:32198"
    io_crs: str = "EPSG:4326"
    raster_resolution_m: float = 20.0
    wind: dict[str, Any] = Field(default_factory=dict)
    weather: dict[str, Any] = Field(default_factory=dict)
    extraction: dict[str, Any] = Field(default_factory=dict)
    pressure: dict[str, Any] = Field(default_factory=dict)
    confidence: dict[str, Any] = Field(default_factory=dict)
    focus_areas: dict[str, Any] = Field(default_factory=dict)


class SpeciesCfg(BaseModel):
    species: str
    scientific_name: str = ""
    region_profile: str = ""
    cover_types: dict[str, dict[str, Any]] = Field(default_factory=dict)
    water: dict[str, Any] = Field(default_factory=dict)
    terrain: dict[str, Any] = Field(default_factory=dict)
    thermal_refuge: dict[str, Any] = Field(default_factory=dict)
    rut: dict[str, Any] = Field(default_factory=dict)
    diel: dict[str, Any] = Field(default_factory=dict)
    hsm_weights: dict[str, float] = Field(default_factory=dict)


# --- loaders -----------------------------------------------------------------
def load_aoi(name: str) -> AOI:
    return AOI(**_load_yaml(config_dir() / "aoi" / f"{name}.yaml"))


def load_species(name: str) -> SpeciesCfg:
    return SpeciesCfg(**_load_yaml(config_dir() / "species" / f"{name}.yaml"))


@lru_cache(maxsize=1)
def load_model() -> ModelCfg:
    return ModelCfg(**_load_yaml(config_dir() / "model.yaml"))


@lru_cache(maxsize=1)
def load_sources() -> dict[str, Any]:
    return _load_yaml(config_dir() / "sources.yaml")


@lru_cache(maxsize=1)
def load_legend() -> dict[str, Any]:
    return _load_yaml(config_dir() / "output_legend.yaml")


def load_species_legend(name: str) -> dict[str, Any]:
    """The map-layer legend PROSE for a species (E1): name/note/group per layer key,
    plus the ordered group list. Loaded from the raw species yaml so it stays outside the
    strict SpeciesCfg model. Empty if the species config carries no legend."""
    try:
        y = _load_yaml(config_dir() / "species" / f"{name}.yaml")
    except Exception:
        return {"legend": [], "groups": []}
    return {"legend": y.get("legend", []) or [], "groups": y.get("legend_groups", []) or []}


class Context(BaseModel):
    """Everything a stage needs, resolved once per run."""

    aoi: AOI
    species: SpeciesCfg
    model: ModelCfg

    @classmethod
    def for_aoi(cls, name: str) -> "Context":
        aoi = load_aoi(name)
        return cls(aoi=aoi, species=load_species(aoi.species), model=load_model())
