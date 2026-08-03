"""Transect data contract.

Assembles the analysis outputs into a single stable JSON document the Transect
app binds to: legal gate, methodology, **proposed camps** (focus areas grouped +
sited at nearest access with pack-in distances), ranked areas (with why/pros/cons),
typed waypoints (each with **optimal approach wind**), routes, roads, and
weather-by-date. Writes outputs/<aoi>/transect.json.
"""
from __future__ import annotations

import json
import math
from datetime import date

from .config import Context, cache_dir, outputs_dir
from . import wind as windmod
from . import rasterio_utils as ru


def _polygonize(ctx, cache, tif, bands, min_km2=1.5, smooth_m=320, per_class=8, simp=0.0008):
    """Classify a 0..1 raster into a FEW cohesive class polygons (defined areas, not
    heat). `bands` = [(name, lo)] ascending; a cell takes the highest class whose lo
    it meets. Heavy smoothing + morphology + top-N-by-area keeps it legible + light."""
    import numpy as np
    from pyproj import Transformer
    from rasterio.features import shapes as rio_shapes
    from scipy.ndimage import binary_closing, binary_fill_holes, binary_opening, uniform_filter
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform

    try:
        arr, prof = ru.read(cache / tif)
    except Exception:
        return []
    res = abs(prof["transform"].a)
    finite = np.isfinite(arr)
    if not finite.any():
        return []
    sm = uniform_filter(np.where(finite, arr, 0.0), size=max(1, int(round(smooth_m / res))))
    sm[~finite] = np.nan
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    to_wgs = lambda g: shp_transform(lambda xs, ys: tr.transform(xs, ys), g)
    it = max(1, int(round(120 / res)))

    cls_id = np.zeros(arr.shape, dtype="int32")
    for i, (_name, lo) in enumerate(bands, start=1):
        cls_id[np.nan_to_num(sm) >= lo] = i
    cls_id[~finite] = 0

    out = []
    for i, (name, _lo) in enumerate(bands, start=1):
        mask = cls_id == i
        if not mask.any():
            continue
        mask = binary_fill_holes(binary_closing(binary_opening(mask, iterations=it), iterations=it * 2))
        polys = []
        for g, v in rio_shapes(mask.astype("uint8"), mask=mask, transform=prof["transform"]):
            if v != 1:
                continue
            gm = shp_shape(g)
            if gm.area / 1e6 >= min_km2:
                polys.append(gm)
        polys.sort(key=lambda p: p.area, reverse=True)
        for gm in polys[:per_class]:
            gw = to_wgs(gm).simplify(simp)
            for pp in (gw.geoms if gw.geom_type == "MultiPolygon" else [gw]):
                ring = [[round(x, 5), round(y, 5)] for x, y in pp.exterior.coords]
                if len(ring) >= 4:
                    out.append({"cls": name, "ll": ring, "area_km2": round(gm.area / 1e6, 1)})
    return out


def _browse_zones(ctx, cache, min_km2=0.8, smooth_m=280):
    """Browse/feeding zones split BY TYPE (from land cover), each with what it is and
    when moose feed on it. Separate from huntability."""
    import numpy as np
    from pyproj import Transformer
    from rasterio.features import shapes as rio_shapes
    from scipy.ndimage import binary_closing, binary_opening, uniform_filter
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform

    try:
        browse, prof = ru.read(cache / "browse.tif")
    except Exception:
        return []
    lc = None
    try:
        lc = ru.read(cache / "landcover.tif")[0]
    except Exception:
        return []
    if lc is None:
        return []
    res = abs(prof["transform"].a)
    br = uniform_filter(np.nan_to_num(browse), size=max(1, int(round(smooth_m / res))))
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    to_wgs = lambda g: shp_transform(lambda xs, ys: tr.transform(xs, ys), g)

    TYPES = {
        20: ("Shrub / regen browse", "Willow, birch, aspen and mountain-ash at moose height — the money browse.",
             "First & last light; heaviest use early season and through the rut."),
        90: ("Riparian / wetland browse", "Alder edges plus emergent/submergent aquatics — sodium-rich aquatic feeding.",
             "Dawn & dusk feeding; midday water use in warm weather."),
        30: ("Herbaceous opening", "Grass and forbs in openings — lighter browse, best at the edges.",
             "Early-season and green-up; edges at first/last light."),
        10: ("Forest-edge browse", "Regenerating conifer/mixedwood edge — the cover-to-forage seam.",
             "All day where cover meets forage; prime travel/feeding edge."),
    }
    it = max(1, int(round(120 / res)))
    out = []
    for cls, (name, what, when) in TYPES.items():
        mask = (lc == cls) & (br > 0.4)
        if not mask.any():
            continue
        mask = binary_closing(binary_opening(mask, iterations=it), iterations=it * 2)
        polys = []
        for g, v in rio_shapes(mask.astype("uint8"), mask=mask, transform=prof["transform"]):
            if v == 1:
                gm = shp_shape(g)
                if gm.area / 1e6 >= min_km2:
                    polys.append(gm)
        polys.sort(key=lambda p: p.area, reverse=True)
        for gm in polys[:8]:
            gw = to_wgs(gm).simplify(0.0008)
            for pp in (gw.geoms if gw.geom_type == "MultiPolygon" else [gw]):
                ring = [[round(x, 5), round(y, 5)] for x, y in pp.exterior.coords]
                if len(ring) >= 4:
                    out.append({"type": name, "what": what, "when": when,
                                "area_km2": round(gm.area / 1e6, 1), "ll": ring})
    return out


def _haversine_km(a, b):
    (lat1, lon1), (lat2, lon2) = a, b
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def _road_coords(cache):
    try:
        import geopandas as gpd

        p = cache / "roads.gpkg"
        if not p.exists():
            return []
        g = gpd.read_file(p)
        if g.crs and g.crs.to_epsg() != 4326:
            g = g.to_crs(4326)
        pts = []
        for geom in g.geometry:
            if geom is None:
                continue
            try:
                pts.extend([(y, x) for x, y in geom.coords])          # LineString
            except NotImplementedError:
                for part in geom.geoms:                                # MultiLineString
                    pts.extend([(y, x) for x, y in part.coords])
        return pts[::5]  # thin
    except Exception:
        return []


def _nearest(pt, pts):
    if not pts:
        return None
    return min(pts, key=lambda q: _haversine_km(pt, q))


def _group_camps(areas, cache, threshold_km=15.0):
    """Cluster focus-area centroids into camps; site each at nearest road access."""
    cents = [(a["properties"]["rank"],
              a["properties"]["centroid"][1], a["properties"]["centroid"][0]) for a in areas]
    n = len(cents)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _haversine_km((cents[i][1], cents[i][2]), (cents[j][1], cents[j][2])) < threshold_km:
                parent[find(i)] = find(j)

    clusters = {}
    for idx, (rank, lat, lon) in enumerate(cents):
        clusters.setdefault(find(idx), []).append((rank, lat, lon))

    roads = _road_coords(cache)
    camps = []
    for ci, (_root, members) in enumerate(sorted(clusters.items(),
                                                 key=lambda kv: -len(kv[1]))):
        letter = chr(ord("A") + ci)
        clat = sum(m[1] for m in members) / len(members)
        clon = sum(m[2] for m in members) / len(members)
        site = _nearest((clat, clon), roads) or (clat, clon)
        access = "road" if roads else "water/centroid"
        packin = {m[0]: round(_haversine_km(site, (m[1], m[2])), 1) for m in members}
        camps.append({
            "id": letter,
            "member_areas": sorted(m[0] for m in members),
            "site": {"lat": round(site[0], 5), "lon": round(site[1], 5)},
            "access_type": access,
            "packin_km_by_area": packin,
            "max_packin_km": max(packin.values()) if packin else None,
        })
    return camps


def build(ctx: Context) -> dict:
    cache = cache_dir(ctx.aoi.name)
    fc = json.loads((cache / "features.geojson").read_text())
    feats = fc["features"]
    areas = [f for f in feats if f["properties"]["legend"] == "focus_area"]
    waypoints = [f for f in feats if f["geometry"]["type"] == "Point"
                 and f["properties"]["legend"] != "focus_area"]
    routes = [f for f in feats if f["geometry"]["type"] == "LineString"]

    camps = _group_camps(areas, cache)
    area_to_camp = {a: c["id"] for c in camps for a in c["member_areas"]}
    camp_site = {c["id"]: (c["site"]["lat"], c["site"]["lon"]) for c in camps}

    # optimal wind per waypoint, approached from its area's camp
    wp_out = []
    for f in waypoints:
        lon, lat = f["geometry"]["coordinates"]
        p = dict(f["properties"])
        fa = p.get("focus_area")
        cid = area_to_camp.get(fa)
        if cid and cid in camp_site:
            alat, alon = camp_site[cid]
            p["camp"] = cid
            p["optimal_wind"] = windmod.optimal_wind(lat, lon, alat, alon)
        wp_out.append({"type": p["legend"], "lat": round(lat, 6), "lon": round(lon, 6),
                       "properties": p})

    # attach camp id + pack-in to each area
    area_out = []
    for a in areas:
        p = dict(a["properties"])
        cid = area_to_camp.get(p["rank"])
        p["camp"] = cid
        area_out.append({"rank": p["rank"], "camp": cid,
                         "area_km2": p.get("area_km2"),
                         "huntability": p.get("mean_huntability"),
                         "centroid": p.get("centroid"),
                         "why": p.get("why"), "pros": p.get("pros"), "cons": p.get("cons"),
                         "stats": p.get("stats"), "conf": p.get("conf"),
                         "geometry": a["geometry"]})

    # legal + methodology + weather
    from .legal import assess
    from .synth import methodology
    from . import weather as wx

    la = assess(ctx)
    try:
        wthr = wx.for_dates(ctx.aoi.center.lat, ctx.aoi.center.lon,
                            ctx.aoi.season.target_dates, today=date.today().isoformat())
    except Exception as e:
        wthr = {"source": f"unavailable: {e}", "days": []}

    doc = {
        "schema": "transect/1",
        "meta": {"aoi": ctx.aoi.name, "title": ctx.aoi.title, "species": ctx.aoi.species,
                 "center": {"lat": ctx.aoi.center.lat, "lon": ctx.aoi.center.lon},
                 "radius_km": ctx.aoi.bbox_halfwidth_km,
                 "target_dates": ctx.aoi.season.target_dates,
                 "residency": ctx.aoi.hunter.residency,
                 "extraction_modes": ctx.aoi.hunter.extraction_modes},
        "legal": {"zone": la.zone, "north_of_52": la.north_of_52,
                  "diy_possible": la.diy_possible,
                  "huntable_tenures": [t.value for t in la.huntable_tenures],
                  "flags": la.flags, "verify": la.verify,
                  "season_summary": la.season_summary},
        "methodology": methodology(ctx),
        "camps": camps,
        "areas": area_out,
        "waypoints": wp_out,
        "routes": [{"type": r["properties"]["legend"],
                    "coords": r["geometry"]["coordinates"]} for r in routes],
        "weather": wthr,
        "layers": {"huntability_raster": "map.html overlay / huntability.tif (EPSG:32198)",
                   "roads": "roads.gpkg"},
        "disclaimer": "Prioritized hypothesis to ground-truth on foot — à valider sur le terrain.",
    }

    # --- rich model layers (heat grid, behaviour, rut, confidence, browse) so the
    # MapLibre app can render the surface + day plan, not just polygons. Reuses the
    # export helpers; every block is best-effort. ---
    from . import export as _ex

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    doc["box"] = {"w": round(minlon, 6), "e": round(maxlon, 6),
                  "n": round(maxlat, 6), "s": round(minlat, 6)}

    # coarse elevation grid (decimated) — powers the thermal-drift arrow field.
    try:
        import numpy as np
        eg = _ex._grid_260x175(ctx, cache, "dem.tif")       # (175, 260), row 0 = north
        dec = eg[::2, ::2]                                    # ~(88, 130)
        gh2, gw2 = dec.shape
        mean_e = float(np.nanmean(dec)) if np.isfinite(dec).any() else 600.0
        doc["elev"] = {"gw": gw2, "gh": gh2,
                       "v": [int(round(mean_e if not np.isfinite(v) else v)) for v in dec.ravel()]}
    except Exception:
        doc["elev"] = None

    # wind list (forecastFor shape) for behaviour's expected-midday
    wind_list = [{"from": d.get("wind_from_deg"), "kph": d.get("wind_kmh"),
                  "tempC": d.get("t_max_c"), "date": d.get("date"),
                  "is_proxy": d.get("is_proxy")} for d in wthr.get("days", [])]
    doc["wind"] = wind_list
    for key, fn in (("behavior", lambda: _ex._behavior_payload(ctx, cache, wind_list)),
                    ("infra", lambda: _ex._infra_lines(cache))):
        try:
            doc[key] = fn()
        except Exception:
            doc[key] = None
    # Zones (not heat) drive the map now — drop the heavy behaviour raster grids,
    # keep the narrative (periods/heat thresholds/expected midday).
    if isinstance(doc.get("behavior"), dict):
        doc["behavior"].pop("grids", None)
    try:
        from . import rut_timing
        doc["rut"] = rut_timing.summary(ctx)
    except Exception:
        doc["rut"] = None
    try:
        from . import confidence as _conf
        doc["confidence"] = _conf.overall(ctx, cache)
    except Exception:
        doc["confidence"] = None
    try:
        from .strategy import strategy as _strategy
        doc["strategy"] = _strategy(ctx)
    except Exception:
        doc["strategy"] = None

    # classified suitability + browse zones (defined clickable areas, not heat)
    try:
        doc["hunt_zones"] = _polygonize(ctx, cache, "huntability.tif",
                                        [("low", 0.42), ("medium", 0.6), ("high", 0.76)])
    except Exception:
        doc["hunt_zones"] = []
    try:
        doc["browse_zones"] = _browse_zones(ctx, cache)
    except Exception:
        doc["browse_zones"] = []

    # --- exact vector hydrography (OSM) — narrow rivers the raster misses, for
    # crisp display + route river-crossing detection. ---
    hydro = {"rivers": [], "lakes": []}
    big_union = small_union = None      # river/canal (boat) vs stream (fordable)
    try:
        import geopandas as gpd
        from shapely.geometry import LineString as _LS
        from shapely.ops import unary_union

        BIG = {"river", "canal"}        # generally need a boat to cross
        wl = cache / "waterways.gpkg"
        if wl.exists():
            g = gpd.read_file(wl)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            g["geometry"] = g.geometry.simplify(0.00018)
            wcol = "waterway" if "waterway" in g.columns else None
            lines, big_ls, small_ls = [], [], []
            for _, row in g.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue
                cls = "river" if (wcol and str(row[wcol]) in BIG) else "stream"
                for part in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
                    coords = list(part.coords)
                    ll = [[round(x, 5), round(y, 5)] for x, y in coords]
                    if len(ll) >= 2:
                        lines.append({"cls": cls, "ll": ll})
                        (big_ls if cls == "river" else small_ls).append(_LS(coords))
            hydro["rivers"] = lines
            big_union = unary_union(big_ls) if big_ls else None
            small_union = unary_union(small_ls) if small_ls else None
        wp = cache / "waterbodies.gpkg"
        if wp.exists():
            g = gpd.read_file(wp)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            g["geometry"] = g.geometry.simplify(0.00018)
            polys = []
            for geom in g.geometry:
                if geom is None or geom.is_empty:
                    continue
                for part in (geom.geoms if geom.geom_type == "MultiPolygon" else [geom]):
                    ring = [[round(x, 5), round(y, 5)] for x, y in part.exterior.coords]
                    if len(ring) >= 4:
                        polys.append(ring)
            hydro["lakes"] = polys
    except Exception:
        pass
    doc["hydro"] = hydro

    # river crossings on routes — classified: 'river' needs a boat, 'stream' is a
    # ford. (App hides/keeps them per the hunter's watercraft in Setup.)
    crossings = []
    try:
        from shapely.geometry import LineString as _LS

        def _pts(route_coords, union):
            out = []
            inter = _LS(route_coords).intersection(union)
            for gg in getattr(inter, "geoms", [inter]):
                if not gg.is_empty and gg.geom_type == "Point":
                    out.append([round(gg.x, 5), round(gg.y, 5)])
            return out

        for r in routes:
            cc = r["geometry"]["coordinates"]
            if len(cc) < 2:
                continue
            leg = r["properties"]["legend"]
            if big_union is not None:
                for p in _pts(cc, big_union):
                    crossings.append({"route": leg, "ll": p, "kind": "river"})
            if small_union is not None:
                for p in _pts(cc, small_union):
                    crossings.append({"route": leg, "ll": p, "kind": "stream"})
    except Exception:
        pass
    doc["crossings"] = crossings

    out = outputs_dir(ctx.aoi.name) / "transect.json"
    out.write_text(json.dumps(doc, indent=2))
    return doc
