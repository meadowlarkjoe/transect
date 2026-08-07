"""Leases on public land (*baux*) — an ABRI SOMMAIRE or a *bail de villégiature* is a
rustic shelter or cabin someone rents from the province on terres du domaine de l'État.

THE ONE THING THIS LAYER MUST NEVER DO IS GATE ACCESS. The land around a leased
shelter stays crown land and stays huntable; the lease covers the building's footprint,
not the country. Wiring it anywhere near the legal gate would take huntable ground away
from the user on the strength of somebody else's cabin. It is a PRESSURE signal, and it
is a good one in both directions:

  * somebody hunts that ground every season — you will not have it to yourself; and
  * somebody thought it was worth building on, which is secondary evidence the ground
    is usable. `access.py` uses it only as a proximity term beside `dist_road`.

WHICH SOURCE. Two exist and only one is authoritative:

  * `services7.arcgis.com/.../LOC_LAS_regroupe_19juin2023` — the queryable one an
    earlier pass found. Abitibi ONLY, a June-2023 snapshot, and as of 2026-08-06 the
    whole ArcGIS org returns `400 Invalid URL` — it is gone. No cross-check is possible
    against it and none is needed: it was only ever a regional proxy for the layer below.
  * `Territoire/Droits_fonciers_WMS` — official and province-wide, but WMS export only:
    a picture, not features.
  * THIS ONE — the same official product as a plain SHP download from Données Québec
    (`couche-des-droits-fonciers-baux`). Province-wide, 48,004 point leases + 1,029
    polygon leases across all 17 administrative regions, refreshed 2026-06-29. 4 MB.

WHICH LEASES COUNT. `DE_PRECS_N` carries 38 purposes and most are not people:
wind turbines (1,223), telecom masts (422), billboards, tailings ponds. Four are
somebody occupying the ground, and only those are read (codes cross-checked against the
descriptions on the 2026-06-29 extract, which agree exactly):

    abri_sommaire     005, 006   9,843   a shelter in the FOREST — built to hunt and
                                         trap from, so the strongest signal here
    pourvoirie_camp   011          524   outfitter lodging on crown land. Doubles as a
                                         real gap-filler: tenure.py's TFS layer only
                                         holds outfitters WITH exclusive rights, so
                                         non-exclusive ones were invisible until now
    villegiature      002       32,384   a cottage. Usually lakeside and usually a
                                         summer thing, so it is weaker evidence of
                                         HUNTING pressure than an abri sommaire
    residence         001          251   somebody's actual home

EXPIRED LEASES ARE KEPT, DELIBERATELY. 8,390 of 48,004 carry a `DA_ECHEA` before today,
but a lapsed lease does not demolish the cabin, and the ministry's extract lags annual
renewals — filtering on expiry would erase thousands of real structures to look tidy.
The split is recorded in the sidecar instead, so the number is available rather than
silently applied.
"""
from __future__ import annotations

import json
import unicodedata

from ..config import Context, cache_dir
from . import _client

CACHE = "baux.geojson"
SIDECAR = "baux.json"

BAUX_URL = ("https://diffusion.mern.gouv.qc.ca/Diffusion/RGQ/Vectoriel/Theme/Local/"
            "Baux/SHP/baux.zip")

# Purpose text (accent- and case-folded) -> our class. Matched on the DESCRIPTION rather
# than `CO_PRECS_N`, because a code is a key into a ministry table we don't hold and can
# be re-used; the French purpose string is the thing that actually says what is there.
# The code column is kept in the output for auditing.
_KIND_BY_TEXT = (
    ("abri sommaire", "abri_sommaire"),
    ("pourvoirie sans droits", "pourvoirie_camp"),
    ("villegiature", "villegiature"),
    ("residence principale", "residence"),
)

LABELS = {
    "abri_sommaire": ("Rustic shelter (abri sommaire)", "Abri sommaire en forêt"),
    "pourvoirie_camp": ("Outfitter camp (no exclusive rights)",
                        "Hébergement en pourvoirie sans droits exclusifs"),
    "villegiature": ("Cottage lease (villégiature)", "Bail de villégiature"),
    "residence": ("Principal residence", "Résidence principale"),
}


def _fold(s) -> str:
    """Accent- and case-insensitive comparison key for the French purpose strings."""
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.lower().split())


def classify(purpose) -> str | None:
    """Purpose string -> our class, or None for the 34 purposes that are not a person
    occupying the ground (wind turbines, telecom, billboards, tailings ponds…)."""
    t = _fold(purpose)
    for needle, kind in _KIND_BY_TEXT:
        if needle in t:
            return kind
    return None


def fetch(ctx: Context) -> None:
    """Download the province-wide baux once, clip to the AOI, keep the occupancy
    classes, and write cache/<aoi>/baux.geojson.

    Always writes — an empty collection means "no leased shelters in this box", which is
    a real and useful answer, and is what stops access.py from telling the difference
    between 'nobody here' and 'we never looked'. That distinction is why the sidecar
    exists.
    """
    out = cache_dir(ctx.aoi.name) / CACHE
    if out.exists() and out.stat().st_size > 0:
        return

    import geopandas as gpd
    import pandas as pd

    shared = _client.shared_dir() / "baux.zip"
    _client.download(BAUX_URL, shared)

    # Both layers: Baux_p is the 48 k centroids, Baux_s the 1 k surveyed outlines. A
    # lease appears in one or the other, never both, so they concatenate cleanly.
    parts = []
    for layer in ("Baux_p", "Baux_s"):
        try:
            g = gpd.read_file(f"zip://{shared}", layer=layer)
        except Exception as e:  # noqa: BLE001 — one layer missing must not lose the other
            print(f"[baux] layer {layer} unreadable: {e}")
            continue
        if len(g):
            parts.append(g)
    if not parts:
        _write_empty(out, cache_dir(ctx.aoi.name) / SIDECAR, "download unreadable")
        return

    gdf = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=parts[0].crs)

    # Clip to the AOI in the SOURCE crs (EPSG:32198), then store in WGS84 like every
    # other vector product in the cache.
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    try:
        from shapely.geometry import box
        bb = gpd.GeoSeries([box(minlon, minlat, maxlon, maxlat)], crs=4326).to_crs(gdf.crs)
        gdf = gdf[gdf.intersects(bb.iloc[0])]
    except Exception as e:  # noqa: BLE001
        print(f"[baux] bbox clip failed, using bounds filter: {e}")
        gdf = gdf.cx[minlon:maxlon, minlat:maxlat]

    purpose_col = _client.pick_field(gdf.columns, "DE_PRECS_N", "precs")
    code_col = _client.pick_field(gdf.columns, "CO_PRECS_N")
    end_col = _client.pick_field(gdf.columns, "DA_ECHEA", "echea")

    n_all = len(gdf)
    if n_all and purpose_col:
        gdf = gdf.assign(kind=gdf[purpose_col].map(classify))
        gdf = gdf[gdf["kind"].notna()]
    else:
        gdf = gdf.iloc[0:0].assign(kind=[])

    if len(gdf):
        try:
            gdf = gdf.to_crs(4326)
        except Exception:
            pass
        # A polygon lease is stored as its centroid: everything downstream measures
        # DISTANCE to a shelter, and the outline of a 1 ha lot adds nothing to that.
        gdf = gdf.assign(geometry=gdf.geometry.representative_point())

    today = _today()
    expired = 0
    keep = {"kind": list(gdf["kind"])} if len(gdf) else {"kind": []}
    if len(gdf) and end_col is not None:
        ends = gdf[end_col].astype(str).str.slice(0, 10)
        expired = int((ends < today).sum())
        keep["lease_end"] = list(ends)
    if len(gdf) and code_col is not None:
        keep["code"] = [str(v) for v in gdf[code_col]]

    feats = []
    for i, geom in enumerate(gdf.geometry if len(gdf) else []):
        if geom is None or geom.is_empty:
            continue
        kind = keep["kind"][i]
        en, fr = LABELS.get(kind, (kind, kind))
        props = {"kind": kind, "label_en": en, "label_fr": fr}
        for k in ("lease_end", "code"):
            if k in keep:
                props[k] = keep[k][i]
        feats.append({"type": "Feature", "properties": props,
                      "geometry": {"type": "Point",
                                   "coordinates": [round(geom.x, 6), round(geom.y, 6)]}})

    out.write_text(json.dumps({"type": "FeatureCollection", "features": feats}))

    counts: dict[str, int] = {}
    for f in feats:
        k = f["properties"]["kind"]
        counts[k] = counts.get(k, 0) + 1
    (cache_dir(ctx.aoi.name) / SIDECAR).write_text(json.dumps({
        "source": "MRNF droits fonciers (baux) — Données Québec",
        "url": BAUX_URL,
        "leases": len(feats),
        "by_kind": counts,
        "expired_kept": expired,        # kept on purpose — see the module docstring
        "candidates_in_box": n_all,     # before the occupancy-class filter
        "ok": True,
    }))
    print(f"[baux] {len(feats)} occupancy leases in box (of {n_all} leases of any purpose): "
          f"{counts or 'none'}")


def _today() -> str:
    import datetime as _dt
    return _dt.date.today().isoformat()


def _write_empty(out, sidecar, why: str) -> None:
    out.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    try:
        sidecar.write_text(json.dumps({"leases": 0, "by_kind": {}, "ok": False, "note": why}))
    except Exception:
        pass
    print(f"[baux] no data: {why}")
