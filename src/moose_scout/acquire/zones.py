"""Hunting zone resolution + moose harvest statistics by zone.

Zone boundaries aren't cleanly published as open geodata, so until a boundary
layer is wired, the zone is taken from the AOI's documented (cross-checked)
``zone_hint`` and flagged for verification. The moose harvest CSV (by zone / year
/ sex-age) IS open data — we cache it and expose recent numbers to rank areas and
validate the habitat model.
"""
from __future__ import annotations

import csv

from ..config import Context, cache_dir
from . import _client

BOUNDARY_CACHE = "zones_chasse.geojson"
_STATS_BASE = ("https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/"
               "Faune/Statistiques_chasse/CSV/statistiques_chasse_Quebec_%s.csv")
# Species -> MFFP harvest CSV slug (species-agnostic).
SPECIES_CSV = {"moose": "orignal", "whitetail_deer": "cerf", "black_bear": "ours",
               "caribou": "caribou", "turkey": "dindon"}


def _csv_slug(species: str) -> str:
    return SPECIES_CSV.get(species, "orignal")


def _stats_url(species: str) -> str:
    return _STATS_BASE % _csv_slug(species)


def _stats_cache(species: str) -> str:
    return f"{_csv_slug(species)}_harvest.csv"


def fetch(ctx: Context) -> None:
    """Acquire the province-wide harvest CSV for the AOI's species (shared cache).
    A zone-boundary layer is a TODO; zone assignment uses the AOI zone_hint."""
    sp = ctx.aoi.species
    _client.download(_stats_url(sp), _client.shared_dir() / _stats_cache(sp))


def zone_for_point(ctx: Context, lat: float, lon: float) -> str | None:
    """Return the zone id at (lat, lon). Uses a cached boundary layer if present,
    otherwise the AOI's documented zone_hint."""
    path = cache_dir(ctx.aoi.name) / BOUNDARY_CACHE
    if path.exists():
        import json

        from shapely.geometry import Point, shape

        pt = Point(lon, lat)
        for feat in json.loads(path.read_text()).get("features", []):
            if shape(feat["geometry"]).contains(pt):
                props = feat.get("properties", {})
                return str(props.get("zone") or props.get("ZONE") or props.get("id"))
    return ctx.aoi.zone_hint


ETAT_URL = (
    "https://cdn-contenu.quebec.ca/cdn-contenu/faune/documents/gestion-especes/"
    "Bilans/etat-situation-population-orignaux-2025-zone-chasse-%s.pdf"
)


def effort_context(zone: str) -> dict | None:
    """Cross-reference harvest against EFFORT: pull the zone's MFFP
    'état de situation' PDF (published for some zones only) and extract success
    rate, hunter count, and aerial-inventory density. Returns None when no such
    doc exists (e.g. zone 19) — the caller must then treat raw harvest as a weak,
    non-effort-normalized signal rather than a success measure.
    """
    if not zone:
        return None
    try:
        import io
        import ssl
        import urllib.request

        from pypdf import PdfReader
    except Exception:
        return None
    import re

    try:
        req = urllib.request.Request(ETAT_URL % zone, headers={"User-Agent": "moose-scout/0.1"})
        data = urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=40).read()
        txt = " ".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    except Exception:
        return None  # no doc for this zone

    low = " ".join(txt.split())
    out: dict = {"source": ETAT_URL % zone}

    m = re.search(r"succ[eè]s de chasse global[^%]*?(\d{1,2})\s*%", low, re.I)
    if m:
        out["success_global_pct"] = int(m.group(1))
    m = re.search(r"m[aâ]le adulte[^%]*?(\d{1,2})\s*%", low, re.I)
    if m:
        out["success_male_adult_pct"] = int(m.group(1))
    m = re.search(r"([\d\s]{3,})\s*chasseurs", low)
    if m:
        out["hunters"] = int(m.group(1).replace(" ", ""))
    m = re.search(r"densit[eé][^0-9]{0,40}([\d],?\d?)\s*orignal", low, re.I)
    if m:
        out["density_per_10km2"] = m.group(1).replace(",", ".")
    return out if len(out) > 1 else None


def zone_stats(zone: str, species: str = "moose", last_n_years: int = 5) -> dict | None:
    """Recent harvest for a zone/species from the cached CSV: total by year and the
    most-recent female/male/young split (a coarse density/quality signal).
    Defensive across the per-species CSV schemas."""
    path = _client.shared_dir() / _stats_cache(species)
    if not path.exists() or not zone:
        return None
    z = str(zone).zfill(2)
    rows = []
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if str(r.get("Zone", "")).zfill(2) != z:
                continue
            if "Engins" in r and r.get("Engins") not in ("Tous", None, ""):
                continue  # avoid double-counting per-weapon rows when a total exists
            rows.append(r)
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("Annee", ""))
    recent = rows[-last_n_years:]
    by_year = {r["Annee"]: int(r["Total_general"]) for r in recent}
    last = recent[-1]
    return {
        "zone": z,
        "harvest_by_year": by_year,
        "latest_year": last["Annee"],
        "latest_total": int(last["Total_general"]),
        "latest_male_adult": int(last.get("Male_adulte", 0) or 0),
        "latest_female_adult": int(last.get("Femelle_adulte", 0) or 0),
    }
