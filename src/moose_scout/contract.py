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


def _raster_points(cache, tif, max_pts=120):
    """Centroids (lon,lat) of the connected blobs in a binary raster — for features too
    small to polygonize usefully (beaver ponds). Largest blobs first, capped at max_pts."""
    p = cache / tif
    if not p.exists():
        return []
    try:
        import numpy as np
        import rasterio
        from pyproj import Transformer
        from scipy import ndimage
        with rasterio.open(p) as src:
            a = src.read(1)
            T, crs = src.transform, src.crs
        lbl, n = ndimage.label(a > 0)
        if n == 0:
            return []
        sizes = ndimage.sum(np.ones_like(lbl), lbl, index=range(1, n + 1))
        cents = ndimage.center_of_mass(a > 0, lbl, index=range(1, n + 1))
        order = np.argsort(sizes)[::-1][:max_pts]
        to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        out = []
        for i in order:
            r, c = cents[i]
            x, y = T * (c + 0.5, r + 0.5)
            lon, lat = to_wgs.transform(x, y)
            out.append({"ll": [round(lon, 5), round(lat, 5)]})
        return out
    except Exception:
        return []


def _grhq_crossing_class(lon, lat):
    """Query GRHQ (Québec hydrographic network) at a crossing point → fordability from
    STRAHLER ORDER + PERENNIALITY, the real size/regime surrogates. A tiny per-point query
    (~0.15 s), so crossings — which are sparse, only where a route meets water — get a
    measured call instead of the OSM waterway-class guess. Returns (kind, why, basis) or
    None to fall back to the OSM class (service down / no coverage)."""
    import json
    import urllib.parse
    import urllib.request
    base = ("https://servicescarto.mrnf.gouv.qc.ca/pes/rest/services/Territoire/"
            "GRHQ_WMS/MapServer/15/query")
    d = 0.0035
    q = {"geometry": f"{lon-d},{lat-d},{lon+d},{lat+d}", "geometryType": "esriGeometryEnvelope",
         "inSR": "4326", "spatialRel": "esriSpatialRelIntersects", "where": "ENABLED=1",
         "outFields": "O_STRAHLER,PERENNITE,TYPECE", "returnGeometry": "false",
         "resultRecordCount": "20", "f": "json"}
    try:
        url = base + "?" + urllib.parse.urlencode(q)
        req = urllib.request.Request(url, headers={"User-Agent": "moose-scout/1.0"})
        with urllib.request.urlopen(req, timeout=12) as r:
            feats = json.loads(r.read().decode("utf-8", "replace")).get("features") or []
    except Exception:
        return None
    if not feats:
        return None
    types = {int(f["attributes"].get("TYPECE") or 0) for f in feats}
    if types & {12, 13, 46, 49}:          # rapids / falls / dam
        return "boat", "GRHQ: rapids, falls or a dam here — do NOT ford; cross at a bridge or by boat", "measured"
    best = max(feats, key=lambda f: int(f["attributes"].get("O_STRAHLER") or 0))
    a = best["attributes"]
    order = int(a.get("O_STRAHLER") or 0)
    per = (a.get("PERENNITE") or "").upper()
    peren = "permanent flow" if per == "P" else "intermittent" if per == "I" else "flow unclassed"
    if order >= 4 or (order >= 3 and per == "P"):
        return "boat", f"GRHQ: Strahler order {order}, {peren} — a substantial channel; plan a boat or a bridge", "measured"
    if order <= 1:
        return "ford", f"GRHQ: Strahler order {order}, {peren} — a small channel, usually wadeable at low water; still scout it", "measured"
    return "ford", f"GRHQ: Strahler order {order}, {peren} — scout before committing; it can run deep and fast after rain", "measured"


def _worldcover_lakes(cache, min_km2=0.06, simp=0.0006):
    """Polygonize the WorldCover water mask (water.tif, satellite — COMPLETE) into lake
    rings for DISPLAY. OSM hydrography is sparse in remote northern QC, so many large
    obvious lakes never drew; the satellite mask has them all. Returns rings in the same
    [[lon,lat],...] shape as the OSM `hydro['lakes']`."""
    import numpy as np
    from pyproj import Transformer
    from rasterio.features import shapes as rio_shapes
    from scipy.ndimage import binary_closing, binary_opening
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform
    try:
        w, prof = ru.read(cache / "water.tif")
    except Exception:
        return []
    mask = np.nan_to_num(w) > 0
    if not mask.any():
        return []
    res = abs(prof["transform"].a)
    it = max(1, int(round(60 / res)))
    mask = binary_closing(binary_opening(mask, iterations=it), iterations=it)
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    to_wgs = lambda g: shp_transform(lambda xs, ys: tr.transform(xs, ys), g)  # noqa: E731
    rings = []
    for g, v in rio_shapes(mask.astype("uint8"), mask=mask, transform=prof["transform"]):
        if v != 1:
            continue
        gm = shp_shape(g)
        if gm.area / 1e6 < min_km2:
            continue
        gw = to_wgs(gm).simplify(simp)
        for pp in (gw.geoms if gw.geom_type == "MultiPolygon" else [gw]):
            ring = [[round(x, 5), round(y, 5)] for x, y in pp.exterior.coords]
            if len(ring) >= 4:
                rings.append(ring)
    return rings


def _cut_zones(ctx, cache):
    """Recent logging cuts (écoforestière) as AGE-CLASSED polygons — distinct from burn
    regen. Fresh cuts are open with little browse yet; 10–25 yr regen is prime browse;
    26–40 yr is closing in. Older cuts read like mature forest and are dropped."""
    import numpy as np
    from pyproj import Transformer
    from rasterio.features import shapes as rio_shapes
    from scipy.ndimage import binary_closing, binary_opening
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform
    try:
        cy, prof = ru.read(cache / "cut_year.tif")
    except Exception:
        return [], {}
    cy = np.nan_to_num(cy)
    if not (cy > 0).any():
        return [], {}
    year = int(ctx.aoi.season.year)
    age = np.where(cy > 0, year - cy, -1)
    res = abs(prof["transform"].a)
    tr = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)
    to_wgs = lambda g: shp_transform(lambda xs, ys: tr.transform(xs, ys), g)  # noqa: E731
    it = max(1, int(round(90 / res)))
    out = []
    for name, lo, hi in (("fresh", 0, 9), ("regen", 10, 25), ("closing", 26, 40)):
        mask = (age >= lo) & (age <= hi)
        if not mask.any():
            continue
        mask = binary_closing(binary_opening(mask, iterations=it), iterations=it)
        polys = []
        for g, v in rio_shapes(mask.astype("uint8"), mask=mask, transform=prof["transform"]):
            if v == 1:
                gm = shp_shape(g)
                if gm.area / 1e6 >= 0.06:
                    polys.append(gm)
        polys.sort(key=lambda p: p.area, reverse=True)
        for gm in polys[:14]:
            gw = to_wgs(gm).simplify(0.0006)
            for pp in (gw.geoms if gw.geom_type == "MultiPolygon" else [gw]):
                ring = [[round(x, 5), round(y, 5)] for x, y in pp.exterior.coords]
                if len(ring) >= 4:
                    out.append({"cls": name, "ll": ring, "area_km2": round(gm.area / 1e6, 1)})
    v = cy[cy > 0]
    meta = {"first_year": int(v.min()), "last_year": int(v.max()),
            "pct_of_aoi": round(float((cy > 0).mean()) * 100, 1)}
    return out, meta


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


def _group_camps(areas, cache, threshold_km=15.0, fixed=None):
    """Cluster focus-area centroids into camps; site each at nearest road access.

    `fixed`: (lat, lon) of a camp the HUNTER placed. When set there is nothing to
    cluster and nothing to site — the answer was given to us.

    THE BUG THIS GUARD EXISTS FOR. This is an INDEPENDENT camp-finder, and it knew
    nothing about a fixed camp: it clustered the focus areas and dropped a camp on the
    nearest road to their centroid. On a cabin hunt that put "Camp A" 630 m from the
    cabin the hunter had just pointed at, so the map showed their camp AND a second
    invented one beside it — after we had already stopped emitting a base_camp pin for
    exactly this reason. Worse than the duplicate icon: `packin_km_by_area` was measured
    from the invented site, so the pack-out distances in the brief were for a camp that
    does not exist.

    Three places used to work out where camp is — synth, routing and here. Two of them
    are now told. This is the third.
    """
    if fixed:
        members = [(a["properties"]["rank"],
                    a["properties"]["centroid"][1], a["properties"]["centroid"][0])
                   for a in areas]
        packin = {m[0]: round(_haversine_km(fixed, (m[1], m[2])), 1) for m in members}
        return [{
            "id": "A",
            "member_areas": sorted(m[0] for m in members),
            "site": {"lat": round(fixed[0], 5), "lon": round(fixed[1], 5)},
            "access_type": "yours",
            # The client uses this to say "your camp" instead of "base camp", and to
            # avoid drawing a recommendation pin on top of the hunter's own marker.
            "fixed": True,
            "packin_km_by_area": packin,
            "max_packin_km": max(packin.values()) if packin else None,
        }]
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


def _recommendations(ctx, cache, rut, areas):
    """The 'how to do better' section: the highest-leverage changes to THIS plan —
    a boat to unlock water-locked ground, shifting dates into the rut, a spike camp
    to extend reach. Computed from the hunter's own constraints + their spatial cost."""
    import numpy as np

    recs = []
    h = ctx.aoi.hunter
    wc = getattr(h, "watercraft", "none")
    walk_km = float(getattr(h, "walk_access_km", 6.0) or 6.0)
    style = getattr(h, "hunt_style", "spike")

    # 1) DATES vs the rut — usually the biggest lever if they're off-peak
    if rut and rut.get("peak_date") and rut.get("targets"):
        try:
            targets = rut["targets"]
            best = max(targets, key=lambda t: t.get("responsiveness", 0))
            bestpct = int(round(best.get("responsiveness", 0) * 100))
            ds = sorted(t["date"] for t in targets)
            mid = date.fromisoformat(ds[len(ds) // 2])
            pk = date.fromisoformat(rut["peak_date"])
            delta = (pk - mid).days
            if abs(delta) >= 5 and bestpct < 78:
                when = f"{abs(delta)} day{'s' if abs(delta) != 1 else ''} {'later' if delta > 0 else 'earlier'}"
                recs.append({"icon": "📅", "impact": "high",
                    "text": (f"<b>Move your dates ~{when}</b>, toward the ~{pk.strftime('%b %-d')} rut peak. "
                             f"You're at ~{bestpct}% calling responsiveness now — at the peak bulls are "
                             "cruising for cows and come to the call. It's the single biggest change you can make.")})
        except Exception:
            pass

    # 2) WATERCRAFT — how much prime ground is locked behind water with no boat
    if wc == "none":
        try:
            hsm = ru.read(cache / "hsm.tif")[0]
            dw = ru.read(cache / "dist_water.tif")[0]
            dr = ru.read(cache / "dist_road.tif")[0]
            fin = np.isfinite(hsm)
            thr = float(np.nanpercentile(hsm[fin], 80))
            top = fin & (hsm >= thr)
            locked = top & (dw < 250) & (dr > walk_km * 1000)   # prime, water-edge, road-far
            reach = top & (dr < walk_km * 1000)
            lk, rc = int(locked.sum()), int(reach.sum())
            if lk > 0.20 * max(rc, 1):
                pct = int(round(100 * lk / max(lk + rc, 1)))
                recs.append({"icon": "🛶", "impact": "high",
                    "text": (f"<b>A canoe or boat would unlock a lot of prime habitat.</b> Around {pct}% of the "
                             "best ground here lines water that's cut off from the road on foot — with a "
                             "boat those water-edge complexes (and their aquatic feeding) come into play.")})
        except Exception:
            pass
    boat_areas = [a for a in areas if a.get("boat_required")]
    if wc == "none" and boat_areas:
        n = len(boat_areas)
        recs.append({"icon": "🛶", "impact": "med",
            "text": (f"{n} ranked area{'s' if n != 1 else ''} {'are' if n != 1 else 'is'} cut off by a "
                     f"river — a boat would put {'them' if n != 1 else 'it'} back in play.")})

    # 3) WALK / STYLE — good ground just past the reach limit
    far = [a for a in areas if a.get("access_flag") and not a.get("boat_required")]
    if far and style == "vehicle":
        recs.append({"icon": "⛺", "impact": "med",
            "text": ("<b>A spike camp would extend your reach.</b> Some of the strongest ground is too far "
                     "to return to the truck from nightly — camping in cuts the daily walk and puts you on "
                     "animals at first and last light.")})
    elif far:
        recs.append({"icon": "🥾", "impact": "low",
            "text": (f"Willing to push your walk-in past {walk_km:.0f} km? A couple of the stronger areas "
                     "sit just beyond it.")})

    # 4) honest ground-truth nudge — always worth saying
    recs.append({"icon": "🔎", "impact": "low",
        "text": ("Every pick here is a hypothesis. A day of boots-on-ground before the hunt — checking sign "
                 "and hanging a couple of cameras on the funnels — will sharpen these more than anything else.")})
    return recs


def build(ctx: Context) -> dict:
    cache = cache_dir(ctx.aoi.name)
    fc = json.loads((cache / "features.geojson").read_text())
    feats = fc["features"]
    areas = [f for f in feats if f["properties"]["legend"] == "focus_area"]
    waypoints = [f for f in feats if f["geometry"]["type"] == "Point"
                 and f["properties"]["legend"] != "focus_area"]
    routes = [f for f in feats if f["geometry"]["type"] == "LineString"]

    _fixed = getattr(ctx.aoi.hunter, "fixed_camp", None)
    camps = _group_camps(areas, cache, fixed=(tuple(_fixed) if _fixed else None))
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
                         "access_flag": p.get("access_flag"), "boat_required": p.get("boat_required", False),
                         "habitat_score": p.get("habitat_score"), "retrieval_score": p.get("retrieval_score"),
                         "stats": p.get("stats"), "conf": p.get("conf"),
                         # reachability under THIS hunter's setup. An unreachable area
                         # still ships — dimmed with its reason — because hiding good
                         # ground you can't get to is worse than showing it.
                         "reachable": p.get("reachable", True),
                         "unreachable_why": p.get("unreachable_why"),
                         # CAPABILITY GATE: 'ok' areas are the formal recommendations
                         # (sites + routes computed); 'excluded' ones are shown ranked
                         # behind them with the reason they're out, so the hunter can
                         # judge whether different kit is worth bringing.
                         "status": p.get("status", "ok"),
                         "excluded_reason": p.get("excluded_reason"),
                         "walk_in_km": p.get("walk_in_km"),
                         "crew": p.get("crew"),
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
                 "extraction_modes": ctx.aoi.hunter.extraction_modes,
                 "watercraft": getattr(ctx.aoi.hunter, "watercraft", "none"),
                 "hunt_style": getattr(ctx.aoi.hunter, "hunt_style", "spike"),
                 # A cabin hunt runs on spike semantics, so hunt_style alone cannot tell
                 # anyone downstream that the hunter sleeps at a camp they named. Without
                 # this the brief had to ask the SETUP PANEL what kind of hunt this was —
                 # live, mutable state that has already drifted by the time a saved plan
                 # is reopened, and which once described a cabin hunt as "back to the
                 # truck nightly". A plan should be readable from the plan.
                 "fixed_camp": (list(ctx.aoi.hunter.fixed_camp)
                                if getattr(ctx.aoi.hunter, "fixed_camp", None) else None),
                 "hunt_radius_km": getattr(ctx.aoi.hunter, "hunt_radius_km", None),
                 "transport": getattr(ctx.aoi.hunter, "transport", {}) or {},
                 "sites": [list(s) for s in (getattr(ctx.aoi.hunter, "sites", None) or [])] or None,
                 "walk_access_km": getattr(ctx.aoi.hunter, "walk_access_km", 6.0),
                 "walk_hunt_km": getattr(ctx.aoi.hunter, "walk_hunt_km", 3.0),
                 "rut_emphasis": None},
        "legal": {"zone": la.zone, "north_of_52": la.north_of_52,
                  "diy_possible": la.diy_possible,
                  "huntable_tenures": [t.value for t in la.huntable_tenures],
                  "flags": la.flags, "verify": la.verify,
                  "season_summary": la.season_summary},
        "methodology": methodology(ctx),
        "camps": camps,
        "areas": area_out,
        "waypoints": wp_out,
        # ATV (#69): legs/ride_km/walk_km ride along when the hunter listed an ATV, so
        # the map can draw the ridable stretch differently from the part they walk, and
        # the brief can quote the WALK distance (the pack-out reality) not the total.
        "routes": [dict({"type": r["properties"]["legend"],
                         "coords": r["geometry"]["coordinates"]},
                        **{k: r["properties"][k] for k in ("legs", "ride_km", "walk_km")
                           if k in r["properties"]})
                   for r in routes],
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
        doc["rut"] = rut_timing.summary(ctx, weather_days=wthr.get("days"))
    except Exception:
        doc["rut"] = None
    # SCENT / LURE (#73). Placement depends on the wind on the day, so the engine ships
    # the doctrine and per-day refresh cadence; the client places the wicks live off the
    # wind scrubber, the same way it derives shooter positions.
    try:
        from . import scent as _scent
        doc["scent"] = _scent.plan(ctx, wthr)
    except Exception as e:
        print(f"[contract] scent plan unavailable: {e}")
        doc["scent"] = None
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
    try:
        doc["recommendations"] = _recommendations(ctx, cache, doc.get("rut"), area_out)
    except Exception:
        doc["recommendations"] = []
    # Field-plan sections (#67): calling script, ordered day plan, ground-truth checklist.
    # Structured (same producers that render brief.md) so the app's Brief tab shows them
    # instead of only the markdown export carrying them. Grounded in phase + area count.
    try:
        from . import synth as _synth
        n_gt = sum(1 for w in wp_out if w.get("type") == "validate_ground")
        doc["field_plan"] = {
            "calling_sequence": _synth.calling_sequence(ctx),
            "day_plan": _synth.day_plan(ctx, len(area_out)),
            "ground_truth": _synth.ground_truth_checklist(ctx, n_gt),
            # Scent is a calling tactic, so it belongs beside the calling script rather
            # than in a corner of its own (#73).
            "scent": _synth.scent_section(ctx, doc.get("scent")),
        }
    except Exception:
        doc["field_plan"] = None

    # TENURE / OUTFITTER BOUNDARIES — the legal gate is filter #1, so it has to be
    # visible, not just narrated. Emitted with a huntable flag per polygon so the map
    # can draw "you may not hunt here" distinctly from "bookable".
    try:
        from . import legal as _lg
        from shapely.geometry import mapping as _map
        from shapely.ops import transform as _tf
        from pyproj import Transformer as _T
        pts = _lg.classify_tenure(ctx) or []
        north = ctx.aoi.center.lat >= _lg.PARALLEL_52
        resid = ctx.aoi.hunter.residency
        out_t = []
        for p in pts:
            if p.geometry is None:
                continue
            acc = _lg._access_for(resid, p.tenure, north)
            g = p.geometry
            try:                               # tenure source is EPSG:32198
                if getattr(g, "is_empty", False):
                    continue
                tr = _T.from_crs("EPSG:32198", "EPSG:4326", always_xy=True)
                if abs(g.bounds[0]) > 180:     # projected → reproject for the app
                    g = _tf(lambda xs, ys: tr.transform(xs, ys), g)
            except Exception:
                pass
            gg = g.simplify(0.0008)
            out_t.append({"tenure": p.tenure.value, "name": p.name, "access": acc,
                          "huntable": acc in ("yes", "draw"),
                          "geometry": _map(gg)})
        doc["tenure_zones"] = out_t[:60]
    except Exception:
        doc["tenure_zones"] = []
    try:
        doc["blocked_tenure"] = json.loads((cache / "blocked_tenure.json").read_text())
    except Exception:
        doc["blocked_tenure"] = None

    # Tell the app plainly when the road network never arrived, so "no areas" reads as
    # a DATA gap rather than a verdict about the ground.
    try:
        doc["access_unknown"] = (cache / "access_unknown.flag").read_text().strip() == "1"
    except Exception:
        doc["access_unknown"] = False

    # BURN REGENERATION — the strongest browse predictor we have, and the only one with
    # local validation (old burns correlate with moose numbers at r=0.62 in this zone).
    # It drives the browse score, so it must be visible: a hunter should be able to see
    # WHY a zone scored, and burns are the answer more often than anything else here.
    try:
        doc["burn_zones"] = _polygonize(ctx, cache, "burn_browse.tif",
                                        [("regen", 0.35), ("prime", 0.80)])
        yrs = {}
        try:
            by, _p = ru.read(cache / "burn_year.tif")
            import numpy as _np
            v = by[_np.isfinite(by) & (by > 0)]
            if v.size:
                yrs = {"first_year": int(v.min()), "last_year": int(v.max()),
                       "pct_of_aoi": round(float((by > 0).mean()) * 100, 1)}
        except Exception:
            pass
        doc["burn_meta"] = yrs
    except Exception:
        doc["burn_zones"] = []
        doc["burn_meta"] = {}

    # Recent logging cuts (écoforestière) — their own age-classed layer, distinct from
    # fire regen. The dominant browse-creating disturbance in commercial forest.
    try:
        doc["cut_zones"], doc["cut_meta"] = _cut_zones(ctx, cache)
    except Exception:
        doc["cut_zones"], doc["cut_meta"] = [], {}

    # classified suitability + browse zones (defined clickable areas, not heat)
    try:
        # ABSOLUTE thresholds on an absolute surface. The old bands (0.42/0.6/0.76)
        # were tuned against a percentile-stretched raster, which guaranteed ~31% of
        # EVERY AOI came out "high" no matter how poor the ground actually was. These
        # are fixed cut-offs: a weak area should return few or no high zones, and a
        # genuinely good one should return many. That is the point of the rescale.
        # BANDS SHOW HABITAT, NOT REACHABILITY.
        #
        # These used to band `huntability` = habitat x retrieval, so prime ground you
        # simply cannot get to was scored DOWN into "low" — painted the same colour as
        # genuinely poor habitat. That breaks the rule the whole interface rests on:
        # excluded ground must never look like low-scoring ground, and a hunter is
        # entitled to see that the good stuff exists and is out of reach for a stated
        # reason. Access belongs in the FOCUS AREA gate (which is about your setup),
        # not in the picture of where the animals are.
        band_src = "habitat_phase.tif" if (cache / "habitat_phase.tif").exists() else "huntability.tif"
        doc["hunt_zones"] = _polygonize(ctx, cache, band_src,
                                        [("low", 0.25), ("medium", 0.40), ("high", 0.55)])
        doc["bands_source"] = ("habitat" if band_src.startswith("habitat")
                               else "huntability (legacy cache — access is baked in)")
    except Exception:
        doc["hunt_zones"] = []
    try:
        doc["browse_zones"] = _browse_zones(ctx, cache)
    except Exception:
        doc["browse_zones"] = []
    # FEEDING EDGE as the BAND it is (#70). A single icon on a seam that runs for
    # kilometres misrepresents the finding — the point marker still says "sit here",
    # but the polygon shows how far the workable edge actually extends. Small + thin,
    # so a low min area and light smoothing.
    try:
        doc["feed_edge_zones"] = _polygonize(ctx, cache, "feed_edge.tif",
                                             [("feed_edge", 0.35)], min_km2=0.25,
                                             smooth_m=160, per_class=14, simp=0.0005)
    except Exception:
        doc["feed_edge_zones"] = []
    # thermal refuge (cool-conifer bedding) and funnels are AREAS, not points.
    try:
        doc["refuge_zones"] = _polygonize(ctx, cache, "hsm_thermal.tif",
                                          [("refuge", 0.5)], min_km2=0.5, smooth_m=200, per_class=10)
    except Exception:
        doc["refuge_zones"] = []
    try:
        doc["funnel_zones"] = _polygonize(ctx, cache, "terrain/funnel.tif",
                                          [("funnel", 0.15)], min_km2=0.04, smooth_m=90, per_class=18)
        # THE NECK WIDTH, per funnel. "Funnel / pass · 0.1 km²" is unfalsifiable — it
        # says nothing a hunter can check against the map in front of them. "a 180 m
        # neck" is the measurement the feature is actually claiming, and it is what makes
        # a bad funnel obviously bad (user: "one is in the middle of a bog").
        try:
            import numpy as _np
            import rasterio as _rio
            from rasterio.features import geometry_mask as _gmask
            fw = cache / "funnel_width.tif"
            if fw.exists() and doc["funnel_zones"]:
                with _rio.open(fw) as _s:
                    _w = _s.read(1).astype("float32")
                    _nd = _s.nodata
                    if _nd is not None:
                        _w[_w == _nd] = _np.nan
                    # The rings are WGS84 lon/lat; the raster is projected. Masking a
                    # geographic polygon against a metric transform yields an EMPTY mask
                    # and no width — silently, which is how the first version of this
                    # shipped reporting nothing at all.
                    from pyproj import Transformer as _TR
                    _fwd = _TR.from_crs("EPSG:4326", _s.crs, always_xy=True)
                    for z in doc["funnel_zones"]:
                        try:
                            _ring = [list(_fwd.transform(x, y)) for x, y in z["ll"]]
                            g = {"type": "Polygon", "coordinates": [_ring]}
                            m = _gmask([g], out_shape=_w.shape, transform=_s.transform,
                                       invert=True, all_touched=True)
                            vals = _w[m & _np.isfinite(_w)]
                            if vals.size:
                                z["neck_m"] = int(round(float(_np.nanmin(vals))))
                        except Exception:
                            pass
        except Exception as _e:
            print(f"[contract] funnel neck widths unavailable: {_e}")
        # And say when the barrier that DEFINES a funnel is incomplete. WorldCover barely
        # sees boreal peatland; without MRNF GRHQ, bog reads as passable ground and necks
        # get drawn through it. That is a caveat on the layer, not a silent degradation.
        try:
            import json as _json
            bn = cache / "funnel_barrier.json"
            if bn.exists():
                doc["funnel_meta"] = _json.loads(bn.read_text())
        except Exception:
            pass
    except Exception:
        doc["funnel_zones"] = []
    # GRHQ wetlands (marsh/bog/fen) as a display layer — the barrier that shapes the
    # funnels + the travel context (#62). Bigger min area so it reads as complexes, not speckle.
    try:
        doc["wetland_zones"] = _polygonize(ctx, cache, "wetland_grhq.tif",
                                           [("wetland", 0.5)], min_km2=0.5, smooth_m=140, per_class=30)
    except Exception:
        doc["wetland_zones"] = []
    # Beaver ponds (GRHQ Mare) as small points — a rut hub worth a stand. Tiny features, so
    # emit centroids rather than polygons.
    try:
        doc["beaver_ponds"] = _raster_points(cache, "beaver_pond.tif", max_pts=120)
    except Exception:
        doc["beaver_ponds"] = []

    # --- exact vector hydrography (OSM) — narrow rivers the raster misses, for
    # crisp display + route river-crossing detection. ---
    hydro = {"rivers": [], "lakes": []}
    big_union = small_union = danger_union = None   # river/canal (boat) · stream (ford) · rapids (avoid)
    try:
        import geopandas as gpd
        from shapely.geometry import LineString as _LS
        from shapely.ops import unary_union

        BIG = {"river", "canal"}        # generally need a boat to cross
        # Rapids / tidal / waterfalls are the one class you NEVER ford — they were
        # falling into the "stream => fordable" bucket, a safety inversion (audit #58).
        DANGER = {"rapids", "tidal_channel", "waterfall"}
        danger_union = None
        wl = cache / "waterways.gpkg"
        if wl.exists():
            g = gpd.read_file(wl)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            g["geometry"] = g.geometry.simplify(0.00018)
            wcol = "waterway" if "waterway" in g.columns else None
            lines, big_ls, small_ls, danger_ls = [], [], [], []
            for _, row in g.iterrows():
                geom = row.geometry
                if geom is None or geom.is_empty:
                    continue
                wv = str(row[wcol]) if wcol else ""
                cls = "danger" if wv in DANGER else "river" if wv in BIG else "stream"
                for part in (geom.geoms if geom.geom_type == "MultiLineString" else [geom]):
                    coords = list(part.coords)
                    ll = [[round(x, 5), round(y, 5)] for x, y in coords]
                    if len(ll) >= 2:
                        lines.append({"cls": "river" if cls == "danger" else cls, "ll": ll})
                        (big_ls if cls == "river" else danger_ls if cls == "danger"
                         else small_ls).append(_LS(coords))
            hydro["rivers"] = lines
            big_union = unary_union(big_ls) if big_ls else None
            small_union = unary_union(small_ls) if small_ls else None
            danger_union = unary_union(danger_ls) if danger_ls else None
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
    # Fill the gaps OSM leaves in remote country with the complete satellite water mask,
    # so no large obvious lake is missing (OSM stays for crisp/named edges on top). This
    # also feeds the crossing detector below, so routes over unmapped lakes get flagged.
    try:
        hydro["lakes"] = (hydro.get("lakes") or []) + _worldcover_lakes(cache)
    except Exception:
        pass
    doc["hydro"] = hydro

    # --- crossings on routes ---------------------------------------------------
    # This used to be a flat binary: waterway=river => "needs a boat", anything else
    # => "fordable". That asserted as fact something we had no evidence for. A named
    # river with a highway bridge over it is not an obstacle at all, and a river we
    # cannot measure is not the same as one we measured and found wide.
    #
    # What OSM actually offers here, in descending order of trustworthiness:
    #   bridge  — a road tagged bridge=yes within BRIDGE_M of the point. MEASURED.
    #   ford    — a way tagged ford=yes, or width/intermittent tags. TAGGED.
    #   class   — waterway=river/canal vs stream/brook/ditch. INFERRED, weak.
    # Anything resting on the last one says so, so the hunter knows the difference
    # between "we checked" and "we guessed". In this AOI 0 of 10 river lines carry a
    # riverbank polygon and none carry a width tag, so most calls ARE the weak one.
    BRIDGE_M = 30.0          # a bridge node and a route crossing rarely coincide exactly
    FORD_WIDTH_M = 4.0       # tagged narrower than this and you can wade it
    crossings = []
    try:
        from shapely.geometry import LineString as _LS, Point as _PT
        from shapely.ops import unary_union as _uu

        # bridge geometry from the road network we already fetched
        bridges = None
        try:
            import geopandas as gpd
            rl = cache / "roads.gpkg"
            if rl.exists():
                gr = gpd.read_file(rl)
                if gr.crs and gr.crs.to_epsg() != 4326:
                    gr = gr.to_crs(4326)
                col = "other_tags" if "other_tags" in gr.columns else None
                if col is not None:
                    br = gr[gr[col].fillna("").str.contains('"bridge"=>"yes"', regex=False)]
                    if len(br):
                        bridges = _uu(list(br.geometry))
        except Exception:
            bridges = None

        # deg -> m at this latitude, so BRIDGE_M is a real distance not a degree fudge
        import math as _m
        latr = _m.radians(ctx.aoi.center.lat)
        m_per_deg = 111320.0 * max(0.2, _m.cos(latr))

        def _pts(route_coords, union):
            out = []
            inter = _LS(route_coords).intersection(union)
            for gg in getattr(inter, "geoms", [inter]):
                if not gg.is_empty and gg.geom_type == "Point":
                    out.append([round(gg.x, 5), round(gg.y, 5)])
            return out

        # All water lines, so a "bridge" call can require the bridge to actually cross
        # water near the point (not merely sit within 30 m of a parallel ditch/rail).
        _water_all = None
        try:
            _wparts = [u for u in (big_union, small_union, danger_union) if u is not None]
            _water_all = _uu(_wparts) if _wparts else None
        except Exception:
            _water_all = None

        _grhq_cache = {}

        # OFFICIAL bridges (AQréseau+ point layer, with status). This outranks every
        # other signal: a mapped open bridge means you drive over the water, and a
        # mapped CLOSED one means a route that looks drivable isn't. Without it most
        # calls here rest on the OSM waterway class alone — the weakest evidence we
        # have — which is how a bridged river came back as "assume a boat" and could
        # exclude a perfectly reachable focus area.
        aq_open = aq_closed = None
        try:
            import geopandas as _gpd
            _bp = cache / "aq_bridges.gpkg"
            if _bp.exists():
                _b = _gpd.read_file(_bp)
                if _b.crs and _b.crs.to_epsg() != 4326:
                    _b = _b.to_crs(4326)
                _o = _b[_b["state"] == "open"] if "state" in _b.columns else _b
                _c = _b[_b["state"] == "closed"] if "state" in _b.columns else _b.iloc[0:0]
                if len(_o):
                    aq_open = _uu(list(_o.geometry))
                if len(_c):
                    aq_closed = _uu(list(_c.geometry))
        except Exception:
            aq_open = aq_closed = None

        def _classify(pt, weak_kind):
            """weak_kind is what the waterway class alone would say."""
            _tol = BRIDGE_M / m_per_deg
            if aq_closed is not None and _PT(pt).distance(aq_closed) <= _tol:
                return ("boat", "AQréseau+: the bridge here is CLOSED — do not count on "
                                "driving it; plan another way in", "measured")
            if aq_open is not None and _PT(pt).distance(aq_open) <= _tol:
                return "bridge", "AQréseau+: mapped bridge, open", "measured"
            if bridges is not None:
                ptb = _PT(pt).buffer(BRIDGE_M / m_per_deg)
                local = bridges.intersection(ptb)
                # a real crossing: a mapped bridge near the point that itself crosses water
                if not local.is_empty and (_water_all is None or local.intersects(_water_all)):
                    return "bridge", "road bridge mapped across the water here", "measured"
            # GRHQ gives the real Strahler order + perenniality — a MEASURED size/regime
            # call — instead of the OSM waterway-class guess. Cache per rounded point so a
            # route touching the same stream twice hits the network once. (Lake shores
            # pass weak_kind='river' and are handled after this, so we only GRHQ streams.)
            if weak_kind in ("stream", "river"):
                key = (round(pt[0], 4), round(pt[1], 4))
                if key not in _grhq_cache:
                    _grhq_cache[key] = _grhq_crossing_class(pt[0], pt[1])
                if _grhq_cache[key] is not None:
                    return _grhq_cache[key]
            if weak_kind == "danger":
                return "boat", ("mapped as rapids / fast water — DO NOT ford; cross at a "
                                "bridge or well downstream on calm water"), "inferred"
            if weak_kind == "stream":
                return "ford", ("mapped as a stream — possibly wadeable at LOW water, but "
                                "depth and current are unmeasured; scout before you commit"), "inferred"
            return "boat", "mapped as a river; no bridge and no width data", "inferred"

        # Lakes are POLYGONS. The detector only ever intersected river/stream LINES,
        # so a route drawn straight across open water produced no crossing marker
        # whatsoever — the single worst version of this bug, because the map showed
        # a walking line over a lake and said nothing about it.
        lake_union = None
        try:
            from shapely.geometry import Polygon as _POLY
            polys = [_POLY(ring) for ring in hydro.get("lakes", []) if len(ring) >= 4]
            if polys:
                lake_union = _uu(polys).boundary      # crossing = cutting the SHORE
        except Exception:
            lake_union = None

        for r in routes:
            cc = r["geometry"]["coordinates"]
            if len(cc) < 2:
                continue
            leg = r["properties"]["legend"]
            fa = r["properties"].get("focus_area")
            for union, weak in ((danger_union, "danger"), (big_union, "river"),
                                (small_union, "stream")):
                if union is None:
                    continue
                for p in _pts(cc, union):
                    kind, why, basis = _classify(p, weak)
                    crossings.append({"route": leg, "focus_area": fa, "ll": p, "kind": kind,
                                      "why": why, "basis": basis})
            if lake_union is not None:
                for p in _pts(cc, lake_union):
                    kind, why, basis = _classify(p, "river")   # open water: never a ford
                    if kind == "ford":
                        kind, why = "boat", "open water — not a stream"
                    crossings.append({"route": leg, "focus_area": fa, "ll": p, "kind": kind,
                                      "why": why + " (lake shore)", "basis": basis})
    except Exception:
        pass
    doc["crossings"] = crossings

    # --- CAPABILITY GATE, second pass: boat-only CROSSINGS -----------------------
    # synth's gate only sees distance-to-road, so an area a short walk from a road but
    # on the far side of an unbridgeable river passed it. Crossings are only classified
    # HERE (after routing), so the boat check has to run here too: if the way in crosses
    # water that needs a boat and the hunter told us they have none, that area is not a
    # recommendation. Re-rank so viable areas keep ranks 1..n, exactly like synth's pass.
    try:
        from .synth import _hunter_kit
        _kit = _hunter_kit(ctx.aoi.hunter)
        if not _kit["boat"] and area_out:
            _boat_areas = {c.get("focus_area") for c in crossings
                           if c.get("kind") == "boat" and c.get("focus_area") is not None}
            _hit = [a for a in area_out
                    if a["rank"] in _boat_areas and a.get("status", "ok") == "ok"]
            for a in _hit:
                a["status"] = "excluded"
                a["excluded_reason"] = ("No boat — the way in crosses water that needs one "
                                        "(see the crossing markers on its route). A canoe or "
                                        "boat would open it.")
            if _hit:
                _ok = [a for a in area_out if a.get("status", "ok") == "ok"]
                _ex = [a for a in area_out if a.get("status", "ok") != "ok"]
                _remap = {}
                for _new, a in enumerate(_ok + _ex, 1):
                    _remap[a["rank"]] = _new
                for a in area_out:
                    a["rank"] = _remap[a["rank"]]
                for w in wp_out:
                    _fa = (w.get("properties") or {}).get("focus_area")
                    if _fa in _remap:
                        w["properties"]["focus_area"] = _remap[_fa]
                for c in crossings:
                    if c.get("focus_area") in _remap:
                        c["focus_area"] = _remap[c["focus_area"]]
                area_out.sort(key=lambda a: a["rank"])
                print(f"[contract] boat-crossing gate: {len(_hit)} area(s) excluded "
                      f"(no boat); {len(_ok)} viable")
    except Exception as e:
        print(f"[contract] boat-crossing gate skipped: {e}")
    doc["crossings_note"] = (
        "Crossing calls are graded. 'Measured' means a mapped bridge, or a GRHQ call from "
        "the stream's Strahler order and perenniality (permanent vs intermittent). "
        "'Inferred' rests on the OSM waterway class alone. Either way a ford call is a "
        "possibility, not a promise — depth and current still aren't measured. In the fall "
        "hunt window rain and snowmelt can raise levels feet per hour and cold water turns "
        "a failed ford dangerous fast; cross early morning (lowest flow), face upstream, "
        "and unbuckle your pack.")

    # Legend (E1): the map-layer PROSE — name/note/group per layer key — travels in the
    # contract as DATA so the client renders it instead of hardcoding moose language. Visual
    # symbology (colour/icon/texture) stays with the client generator; a different species
    # config supplies different groups + prose with no app change. See config/species/*.yaml.
    try:
        from .config import load_species_legend
        _lg = load_species_legend(ctx.aoi.species)
        doc["legend"] = _lg["legend"]
        doc["legend_groups"] = _lg["groups"]
        # #71: for layers that come from an official dataset rather than our model, the
        # honest "why" is naming the SOURCE — not inventing a rationale. The client shows
        # this on hover so a hunter can tell "we measured this" from "we inferred this".
        from .confidence import SOURCE_NOTES as _SN
        doc["layer_provenance"] = {k: {"source": v[0], "conf": v[1]} for k, v in _SN.items()}
    except Exception:
        doc["legend"] = []
        doc["legend_groups"] = []

    # Region + coverage manifest (E2): which legal/data regime governs this AOI, and —
    # per declared data source — whether the box is IN its coverage and whether the
    # source actually landed a product this run. This is the honest "what covered your
    # box" readout: a source declared in-coverage that returned nothing reads 'missing',
    # not a silent gap; one outside its envelope reads 'fallback' with the caveat.
    try:
        from .region import coverage_manifest, resolve_region

        _region = resolve_region(ctx)
        doc["region"] = {
            "profile": _region.get("region_profile"),
            "name": _region.get("name_en"),
            "legal_regime": _region.get("legal_regime"),
        }
        # source id -> the cache product that proves it landed (None = no bulk probe).
        _PRODUCT = {
            "ecoforestiere": "stand_type.tif", "nbac": "burn_year.tif",
            "sentinel2": "ndvi.tif", "worldcover": "landcover.tif",
            "cdem": "dem.tif", "osm": "roads.gpkg", "grhq": "wetland_grhq.tif",
        }
        _man = coverage_manifest(ctx, _region)
        for e in _man:
            decl = e.get("coverage")            # declared: in | partial | out
            prod = _PRODUCT.get(e.get("id"))
            if decl == "out":
                e["status"] = "fallback"
            elif prod is None:
                e["status"] = decl              # no runtime probe (e.g. grhq per-crossing)
            elif (cache / prod).exists():
                e["status"] = "partial" if decl == "partial" else "ok"
            else:
                e["status"] = "missing"
                e.setdefault("note", "Declared in coverage but no data landed this run "
                             "(source error or timed out) — this layer is degraded.")
        doc["coverage_manifest"] = _man
    except Exception:
        doc["region"] = None
        doc["coverage_manifest"] = []

    # Stamp the analysis with the engine revision that produced it, so a saved plan
    # can tell whether the model has moved on since. See version.py.
    try:
        from .version import ENGINE_REVISION
        doc["engine_revision"] = ENGINE_REVISION
    except Exception:
        pass

    out = outputs_dir(ctx.aoi.name) / "transect.json"
    out.write_text(json.dumps(doc, indent=2))
    return doc
