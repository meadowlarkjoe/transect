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
                         "access_flag": p.get("access_flag"), "boat_required": p.get("boat_required", False),
                         "habitat_score": p.get("habitat_score"), "retrieval_score": p.get("retrieval_score"),
                         "stats": p.get("stats"), "conf": p.get("conf"),
                         # reachability under THIS hunter's setup. An unreachable area
                         # still ships — dimmed with its reason — because hiding good
                         # ground you can't get to is worse than showing it.
                         "reachable": p.get("reachable", True),
                         "unreachable_why": p.get("unreachable_why"),
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
        doc["rut"] = rut_timing.summary(ctx, weather_days=wthr.get("days"))
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
    try:
        doc["recommendations"] = _recommendations(ctx, cache, doc.get("rut"), area_out)
    except Exception:
        doc["recommendations"] = []

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
    # thermal refuge (cool-conifer bedding) and funnels are AREAS, not points.
    try:
        doc["refuge_zones"] = _polygonize(ctx, cache, "hsm_thermal.tif",
                                          [("refuge", 0.5)], min_km2=0.5, smooth_m=200, per_class=10)
    except Exception:
        doc["refuge_zones"] = []
    try:
        doc["funnel_zones"] = _polygonize(ctx, cache, "terrain/funnel.tif",
                                          [("funnel", 0.15)], min_km2=0.04, smooth_m=90, per_class=18)
    except Exception:
        doc["funnel_zones"] = []

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

        def _classify(pt, weak_kind):
            """weak_kind is what the waterway class alone would say."""
            if bridges is not None:
                ptb = _PT(pt).buffer(BRIDGE_M / m_per_deg)
                local = bridges.intersection(ptb)
                # a real crossing: a mapped bridge near the point that itself crosses water
                if not local.is_empty and (_water_all is None or local.intersects(_water_all)):
                    return "bridge", "road bridge mapped across the water here", "measured"
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
            for union, weak in ((danger_union, "danger"), (big_union, "river"),
                                (small_union, "stream")):
                if union is None:
                    continue
                for p in _pts(cc, union):
                    kind, why, basis = _classify(p, weak)
                    crossings.append({"route": leg, "ll": p, "kind": kind,
                                      "why": why, "basis": basis})
            if lake_union is not None:
                for p in _pts(cc, lake_union):
                    kind, why, basis = _classify(p, "river")   # open water: never a ford
                    if kind == "ford":
                        kind, why = "boat", "open water — not a stream"
                    crossings.append({"route": leg, "ll": p, "kind": kind,
                                      "why": why + " (lake shore)", "basis": basis})
    except Exception:
        pass
    doc["crossings"] = crossings
    doc["crossings_note"] = (
        "Crossing calls are graded. 'Measured' means a bridge is mapped at the point. "
        "'Inferred' means it rests on the OSM waterway class alone — no width, ford or "
        "riverbank data ships for this area, so treat a boat call as 'assume the worst "
        "until you see it'. A ford call is a possibility, not a promise — depth and "
        "current are unmeasured. In the fall hunt window rain and snowmelt can raise "
        "levels feet per hour and cold water turns a failed ford dangerous fast; cross "
        "early morning (lowest flow), face upstream, and unbuckle your pack.")

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
