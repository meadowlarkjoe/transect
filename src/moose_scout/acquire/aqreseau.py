"""AQréseau+ — Québec's OFFICIAL consolidated road network (MRNF / Adresses Québec).

Why this exists: OSM does not map most Québec logging roads. A hunter looked at OnX,
saw a forest road running straight through his camp, and our map said "no road data".
Measured on a 14 km box near Rivière des Outaouais: OSM returned nothing usable while
AQréseau+ returned 87 segments, 80 of them drivable class-4/5 forest roads.

That gap is not cosmetic. `dist_road` drives the capability gate (good ground gets
EXCLUDED as "13.8 km from a road" when a road runs through it), hunter pressure
(roadless reads as low pressure, inflating the score), pack-out cost, staging
placement and the vehicle-hunt reachability mask — so missing forest roads corrupt
the ranking AND the exclusions in opposite directions.

Service: servicescarto.mrnf.gouv.qc.ca ArcGIS REST, layer group "Carrossabilité",
which is a COMPLETE PARTITION of the network by drivability (verified: the four
leaves sum exactly to the layer total) and carries the attribute we most need:

    32 Carrossable      — drivable
    33 Non carrossable  — not drivable
    34 Impraticable     — impassable
    35 Inconnue         — unknown

Useful fields on every segment: Cls_CheFor (forest-road class CL1..CL5), ClsRte
(MTQ class), CarRte (drivability), Che_Multi (multi-use), NomRte/NoRte (name).
"""
from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request

BASE = ("https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/"
        "AQreseauPlus_WMS/MapServer")

# (layer id, drivability) — the Carrossabilité partition. Ordered so that if a
# segment somehow appears twice, the more permissive call is the one we keep last.
DRIVE_LAYERS = [(33, "no"), (34, "impassable"), (35, "unknown"), (32, "yes")]

PAGE = 1000
BUDGET_S = float(os.environ.get("AQRESEAU_BUDGET_S", "180"))


def _get(url: str, timeout: int = 60):
    req = urllib.request.Request(url, headers={"User-Agent": "transect/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _query_layer(layer: int, bbox, t0):
    """All features of one layer inside bbox, paged. bbox = (w, s, e, n) in WGS84."""
    w, s, e, n = bbox
    out, offset = [], 0
    while True:
        if time.time() - t0 > BUDGET_S:
            print(f"[aqreseau] budget hit at layer {layer}, offset {offset}")
            break
        q = urllib.parse.urlencode({
            "where": "1=1",
            "geometry": f"{w},{s},{e},{n}",
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326, "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "NomRte,NoRte,ClsRte,Cls_CheFor,CarRte,Che_Multi,Gestion",
            "returnGeometry": "true",
            "resultOffset": offset, "resultRecordCount": PAGE,
            "orderByFields": "OBJECTID",
            "f": "geojson",
        })
        try:
            j = _get(f"{BASE}/{layer}/query?{q}")
        except Exception as ex:                       # one bad page must not kill the pull
            print(f"[aqreseau] layer {layer} offset {offset} failed: {ex}")
            break
        feats = j.get("features") or []
        out.extend(feats)
        if len(feats) < PAGE:
            break
        offset += PAGE
    return out


def _road_class(props):
    """Map AQréseau+ attributes onto the classes the model already speaks
    (see export._road_class): artery | road | track.

    Forest-road class is the honest signal out here — CL1/CL2 are built to haul
    loaded trucks, CL4/CL5 are narrow spurs you take a pickup down carefully."""
    cf = (props.get("Cls_CheFor") or "").upper()
    cls = (props.get("ClsRte") or "").lower()
    if any(k in cls for k in ("autoroute", "nationale", "régionale", "regionale")):
        return "artery"
    if "collectrice" in cls:
        return "road"
    if cf.startswith(("CL1", "CL2", "01", "02")):
        return "road"          # built for loaded trucks
    if cf.startswith(("CL3", "03")):
        return "road"
    if cf.startswith(("CL4", "CL5", "04", "05")):
        return "track"         # narrow spur
    if "locale" in cls:
        return "road"
    return "track"


def fetch(ctx, cache) -> str:
    """Pull AQréseau+ for the AOI and write cache/aqreseau.gpkg (WGS84 lines).

    Returns a short status string for the coverage manifest. Never raises: a failure
    here degrades us to OSM-only, which is the behaviour we had before."""
    import geopandas as gpd
    from shapely.geometry import LineString, MultiLineString

    out = cache / "aqreseau.gpkg"
    bbox = ctx.aoi.bbox_wgs84()          # (minlon, minlat, maxlon, maxlat)
    t0 = time.time()
    rows, geoms = [], []
    seen = set()
    for layer, drive in DRIVE_LAYERS:
        for f in _query_layer(layer, bbox, t0):
            g = f.get("geometry") or {}
            gt, co = g.get("type"), g.get("coordinates")
            if not co:
                continue
            try:
                geom = LineString(co) if gt == "LineString" else MultiLineString(co)
            except Exception:
                continue
            p = f.get("properties") or {}
            # de-dupe across layers on rounded geometry, keeping the last (most
            # permissive) drivability call
            key = (round(geom.bounds[0], 6), round(geom.bounds[1], 6),
                   round(geom.bounds[2], 6), round(geom.bounds[3], 6), p.get("NoRte"))
            if key in seen:
                continue
            seen.add(key)
            geoms.append(geom)
            rows.append({"name": p.get("NomRte") or "", "no": p.get("NoRte") or "",
                         "cls": _road_class(p), "drive": drive,
                         "cls_chefor": p.get("Cls_CheFor") or "",
                         "cls_rte": p.get("ClsRte") or "",
                         "multi": p.get("Che_Multi") or ""})
    if not rows:
        return "absent: AQréseau+ returned no segments for this box"
    gdf = gpd.GeoDataFrame(rows, geometry=geoms, crs="EPSG:4326")
    gdf.to_file(out, driver="GPKG")
    drivable = int((gdf["drive"] == "yes").sum())
    print(f"[aqreseau] {len(gdf)} segments ({drivable} drivable) -> {out.name}")
    return f"ok: {len(gdf)} segments ({drivable} drivable)"
