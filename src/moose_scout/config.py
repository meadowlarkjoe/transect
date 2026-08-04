"""Configuration models and loaders.

All tunable knobs live in ``config/*.yaml``; this module validates them into
typed objects. Heavy geo libraries are NOT imported here so that lightweight
stages (e.g. ``legal``) and tests can load config without the full GDAL stack.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional, Tuple

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
Watercraft = Literal["none", "canoe", "motor"]
HuntStyle = Literal["spike", "vehicle"]


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
    walk_access_km: float = 6.0          # how far off a road you'll walk in (road → camp/area)
    walk_hunt_km: float = 3.0            # how far from camp you'll hunt (camp → site)
    # HUNT-FROM-A-FIXED-CAMP. When set, the hunter has already chosen where they're
    # basing: skip camp-finding, anchor camp/staging THERE, and narrow the whole
    # analysis to a circle around it (they only hunt what they can walk from camp).
    fixed_camp: Optional[Tuple[float, float]] = None   # (lat, lon), or None for auto
    hunt_radius_km: Optional[float] = None             # analysis radius from a fixed camp


class AOI(BaseModel):
    """Area of interest — the unit of analysis."""

    name: str
    title: str = ""
    species: str = "moose"
    center: LatLon
    bbox_halfwidth_km: float = 35.0
    zone_hint: Optional[str] = None    # documented zone until boundaries are wired
    season: SeasonCfg
    hunter: HunterCfg = Field(default_factory=HunterCfg)
    notes: str = ""

    def bbox_wgs84(self) -> tuple[float, float, float, float]:
        """(minlon, minlat, maxlon, maxlat). Simple metric->degree approximation
        that is plenty accurate for an AOI-sized box at boreal latitudes."""
        import math

        hw_km = self.bbox_halfwidth_km
        dlat = hw_km / 111.0
        dlon = hw_km / (111.0 * math.cos(math.radians(self.center.lat)))
        return (
            self.center.lon - dlon,
            self.center.lat - dlat,
            self.center.lon + dlon,
            self.center.lat + dlat,
        )


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


class Context(BaseModel):
    """Everything a stage needs, resolved once per run."""

    aoi: AOI
    species: SpeciesCfg
    model: ModelCfg

    @classmethod
    def for_aoi(cls, name: str) -> "Context":
        aoi = load_aoi(name)
        return cls(aoi=aoi, species=load_species(aoi.species), model=load_model())
