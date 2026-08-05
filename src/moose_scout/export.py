"""Stage 7 — export to field-ready, OnX-importable outputs.

Reads cache/<aoi>/features.geojson (+ rasters) and writes into outputs/<aoi>/:
  moose_scout.gpx    waypoints (sites/camp) + tracks (routes/funnels) for OnX
  moose_scout.kml    focus-area polygons + colored lines/points (OnX web import)
  map.png            rendered field map (hillshade + huntability + annotations)
  brief.md           the narrative brief (written by synth)

Colors/geometry follow config/output_legend.yaml so briefs read like the expert
sheets they model. OnX limits respected: GPX/KML only, <=4 MB, no KMZ/shapefile.
"""
from __future__ import annotations

import json

from .config import Context, cache_dir, load_legend, outputs_dir


def _legend_lookup():
    leg = load_legend()
    out = {}
    for group in ("routes", "sites"):
        for k, v in (leg.get(group) or {}).items():
            out[k] = v
    for k in ("funnel", "focus_area", "base_camp", "parking", "glassing"):
        if k in leg:
            out[k] = leg[k]
    return out


def _hex_to_kmlabgr(hexcol, alpha="ff"):
    h = hexcol.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"{alpha}{b}{g}{r}"


def run(ctx: Context) -> None:
    cache = cache_dir(ctx.aoi.name)
    out = outputs_dir(ctx.aoi.name)
    fc = json.loads((cache / "features.geojson").read_text())
    leg = _legend_lookup()

    _export_gpx(fc, leg, out / "moose_scout.gpx")
    _export_kml(fc, leg, out / "moose_scout.kml")
    _export_scout_data(ctx, fc, cache, out / "scout-data.js")
    try:
        _render_map(ctx, fc, leg, cache, out / "map.png")
    except Exception as e:  # map is best-effort; GPX/KML are the must-haves
        (out / "map_error.txt").write_text(str(e))
    try:
        _export_html(ctx, fc, leg, cache, out / "map.html")
    except Exception as e:
        (out / "html_error.txt").write_text(repr(e))


def _grid_260x175(ctx, cache, name, GW=260, GH=175):
    """Sample a cached raster onto the app's GW×GH grid over the AOI bbox, row-major
    (j*GW+i), lat from north — matching Transect's buildGrid() mapping exactly.
    Returns (values list, nodata-as -1 for huntability / mean for elev)."""
    import numpy as np
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    from . import rasterio_utils as ru

    arr, prof = ru.read(cache / name)
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    dst = np.full((GH, GW), np.nan, "float32")
    dst_tr = from_bounds(minlon, minlat, maxlon, maxlat, GW, GH)
    # AVERAGE (area-weighted) when downsampling ~7× from the 40 m grid — bilinear
    # only samples 2×2 and aliases into moiré/linear banding on a continuous field.
    reproject(arr, dst, src_transform=prof["transform"], src_crs=prof["crs"],
              dst_transform=dst_tr, dst_crs="EPSG:4326",
              src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.average)
    return dst  # shape (GH, GW), row 0 = north


_ARTERY = {"motorway", "trunk", "primary", "secondary"}
_SECONDARY = {"tertiary", "unclassified", "residential"}
_TRACKISH = {"track", "service"}


def _road_class(highway, other_tags):
    """Drivability class from the OSM highway tag, refined by surface/tracktype (#32):
      artery — paved through-road (Route 389 and the like)
      road   — secondary/local drivable road
      track  — resource / logging road: gravel, often rough or seasonal
    A drivable class is DOWNGRADED to 'track' when its surface reads unpaved. This is a
    display + honesty aid; the drivable raster (roads.tif) is unchanged."""
    hw = (highway or "").lower()
    ot = (other_tags or "").lower()
    unpaved = any(s in ot for s in ("gravel", "dirt", "ground", "unpaved", "fine_gravel",
                                    "compacted", "earth", "sand", "\"tracktype\""))
    if hw in _ARTERY:
        return "track" if unpaved else "artery"
    if hw in _SECONDARY:
        return "track" if unpaved else "road"
    if hw in _TRACKISH:
        return "track"
    return "road"


def _infra_lines(cache):
    """Road + rail + trail as the app's infra format:
    [{t:'road'|'rail'|'trail', cls, name, ll:[[lon,lat],…]}]. OSM-sourced, simplified.
    Roads carry a DRIVABILITY class (#32) so the map can tell Route 389 from a logging
    spur; trails are foot-only and kept distinct. Empty list if a layer is absent."""
    import geopandas as gpd

    out = []
    # OSM first, then the OFFICIAL AQréseau+ layers. Both go to the MAP, not just the
    # engine's cost raster — a forest road the model routes down but the map never draws
    # is exactly the "no road data" the hunter was looking at. Motorised trails and rail
    # keep their OWN types ('trail'/'rail') so the client can toggle them separately and
    # nobody reads a quad trail as drivable.
    specs = [("roads.gpkg", "road"), ("rail.gpkg", "rail"), ("trails.gpkg", "trail"),
             ("aqreseau.gpkg", "road"), ("aq_trails.gpkg", "trail"), ("aq_rail.gpkg", "rail")]
    for name, t in specs:
        p = cache / name
        if not p.exists():
            continue
        try:
            g = gpd.read_file(p)
            if g.crs and g.crs.to_epsg() != 4326:
                g = g.to_crs(4326)
            has_cls = "cls" in g.columns          # AQréseau+ pre-classifies its own
            has_hw = "highway" in g.columns
            has_ot = "other_tags" in g.columns
            has_nm = "name" in g.columns
            g["geometry"] = g.geometry.simplify(0.0004)
            for i, geom in enumerate(g.geometry):
                if geom is None or geom.is_empty:
                    continue
                if has_cls:
                    cls = str(g["cls"].iloc[i] or t)   # AQréseau+ forest-road class
                elif t == "road":
                    cls = _road_class(g["highway"].iloc[i] if has_hw else None,
                                      g["other_tags"].iloc[i] if has_ot else None)
                else:
                    cls = t
                nm = g["name"].iloc[i] if has_nm else None
                nm = None if (nm is None or (isinstance(nm, float))) else str(nm)
                parts = geom.geoms if geom.geom_type == "MultiLineString" else [geom]
                for part in parts:
                    ll = [[round(x, 5), round(y, 5)] for x, y in part.coords]
                    if len(ll) >= 2:
                        rec = {"t": t, "cls": cls, "ll": ll}
                        if nm:
                            rec["name"] = nm
                        out.append(rec)
        except Exception:
            pass
    return out


def _behavior_payload(ctx, cache, wind):
    """SCOUT_DATA.BEHAVIOR: per-period narrative + occupancy grids (260×175) +
    heat thresholds + the expected-midday refuge weight from the hunt-window
    forecast. Lets the app add a time-of-day/temperature slider that swaps the
    heat overlay for 'where he is at 7 a.m. vs 1 p.m.'. Returns None if the
    behavior stage produced nothing (older cache / stage skipped)."""
    import numpy as np

    pj = cache / "behavior" / "periods.json"
    if not pj.exists():
        return None
    try:
        meta = json.loads(pj.read_text())
    except Exception:
        return None

    grids = {}
    for g in meta.get("grids", []):
        try:
            arr = _grid_260x175(ctx, cache, f"behavior/{g}.tif")
            grids[g] = [(-1.0 if not np.isfinite(v) else round(float(v), 4)) for v in arr.ravel()]
        except Exception:
            pass
    if not grids:
        return None

    # Expected midday: mean forecast high over the hunt window → refuge weight.
    from .behavior import refuge_weight
    heat = meta.get("heat", {})
    heat_c = {"heat_onset_c": heat.get("onset_c", 14), "heat_severe_c": heat.get("severe_c", 20)}
    temps = [d.get("tempC") for d in (wind or []) if d.get("tempC") is not None]
    tmax = round(sum(temps) / len(temps), 1) if temps else None
    w = round(refuge_weight(tmax, heat_c), 2)
    cls = "warm — expect a hard midday retreat to cover" if w >= 0.66 else \
          ("mild — partial midday cover use" if w >= 0.33 else
           "cool — moose stay out feeding/loafing through midday")
    return {
        "heat": heat,
        "periods": meta.get("periods", []),
        "grids": grids,
        "expected_midday": {"tmax_c": tmax, "refuge_weight": w, "class": cls,
                            "is_proxy": bool((wind or [{}])[0].get("is_proxy"))},
    }


def _export_scout_data(ctx, fc, cache, path):
    """Emit Transect's full `window.SCOUT_DATA` (AREAS/POINTS/ROUTES §13-fixed +
    real GRID/ELEV/WIND/SOLAR/BOX §12) so the corrected model drops into the app."""
    import numpy as np

    def rnd(coord, n=5):
        return [round(coord[0], n), round(coord[1], n)]

    areas, points, routes = [], [], []
    for f in fc["features"]:
        p = f["properties"]
        g = f["geometry"]
        k = p["legend"]
        if k == "focus_area":
            ring = [[rnd(c) for c in g["coordinates"][0]]]
            areas.append({
                "rank": p["rank"], "area_km2": p.get("area_km2"),
                "hunt": p.get("mean_huntability"), "c": rnd(p["centroid"]),
                "why": p.get("why", ""), "pros": p.get("pros", []), "cons": p.get("cons", []),
                "stats": p.get("stats", {}), "rings": ring, "conf": p.get("conf"),
            })
        elif g["type"] == "Point":
            points.append({"t": k, "a": p.get("focus_area"),
                           "s": round(p["score"], 3) if p.get("score") is not None else None,
                           "e": int(p["elev_m"]) if p.get("elev_m") is not None else None,
                           "anchor": p.get("anchor"), "c": rnd(g["coordinates"])})
        elif g["type"] == "LineString":
            routes.append({"t": k, "c": [rnd(c) for c in g["coordinates"]]})

    areas.sort(key=lambda a: a["rank"])

    # --- §12 real layers: huntability grid, elevation, wind, solar, box ---
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    box = {"w": round(minlon, 6), "e": round(maxlon, 6),
           "n": round(maxlat, 6), "s": round(minlat, 6)}
    grid = elev = None
    try:
        hg = _grid_260x175(ctx, cache, "huntability.tif")
        grid = [(-1.0 if not np.isfinite(v) else round(float(v), 4)) for v in hg.ravel()]
    except Exception:
        pass
    try:
        eg = _grid_260x175(ctx, cache, "dem.tif")
        mean_e = float(np.nanmean(eg)) if np.isfinite(eg).any() else 600.0
        elev = [round(float(mean_e if not np.isfinite(v) else v), 1) for v in eg.ravel()]
    except Exception:
        pass

    # wind (Open-Meteo) + solar, in forecastFor()'s shape {from, kph, tempC}
    wind, solar = None, None
    try:
        from datetime import date

        from . import weather as wx

        wthr = wx.for_dates(ctx.aoi.center.lat, ctx.aoi.center.lon,
                            ctx.aoi.season.target_dates, today=date.today().isoformat())
        wind = [{"from": d.get("wind_from_deg"), "kph": d.get("wind_kmh"),
                 "tempC": d.get("t_max_c"), "date": d.get("date"),
                 "is_proxy": d.get("is_proxy")} for d in wthr.get("days", [])]

        def _hr(iso):
            t = str(iso).split("T")[-1][:5]
            hh, mm = t.split(":")
            return round(int(hh) + int(mm) / 60, 2)

        d0 = (wthr.get("days") or [{}])[0]
        if d0.get("sunrise"):
            solar = {"sunrise": _hr(d0["sunrise"]), "sunset": _hr(d0["sunset"]),
                     "source": wthr.get("source")}
    except Exception:
        pass

    infra = _infra_lines(cache) or None
    strat = None
    try:
        from .strategy import strategy as _strategy
        strat = _strategy(ctx)
    except Exception:
        pass
    behavior = None
    try:
        behavior = _behavior_payload(ctx, cache, wind)
    except Exception:
        pass
    rut = None
    try:
        from . import rut_timing
        rut = rut_timing.summary(ctx)
    except Exception:
        pass
    conf = None
    try:
        from . import confidence as _conf
        conf = _conf.overall(ctx, cache)
    except Exception:
        pass
    # Browse/feeding overlay (CarteXpert-style vegetation read): the persisted
    # browse sub-score on the app grid, so the map can shade feeding ground.
    browse = None
    try:
        bg = _grid_260x175(ctx, cache, "browse.tif")
        browse = [(-1.0 if not np.isfinite(v) else round(float(v), 3)) for v in bg.ravel()]
    except Exception:
        pass
    D = {"AREAS": areas, "POINTS": points, "ROUTES": routes, "BOX": box,
         "GW": 260, "GH": 175, "GRID": grid, "ELEV": elev, "WIND": wind, "SOLAR": solar,
         "INFRA": infra, "STRATEGY": strat, "BEHAVIOR": behavior,
         "RUT": rut, "CONFIDENCE": conf, "BROWSE": browse}
    js = "window.SCOUT_DATA = " + json.dumps({k: v for k, v in D.items() if v is not None}) + ";\n"
    path.write_text(js)


def _export_gpx(fc, leg, path):
    import gpxpy.gpx as g

    gpx = g.GPX()
    for f in fc["features"]:
        p = f["properties"]
        k = p.get("legend")
        info = leg.get(k, {})
        name = info.get("label_en", k)
        geom = f["geometry"]
        if geom["type"] == "Point":
            lon, lat = geom["coordinates"]
            desc = " ".join(f"{kk}={vv}" for kk, vv in p.items() if kk != "legend")
            gpx.waypoints.append(g.GPXWaypoint(lat, lon, name=f"{name}", description=desc))
        elif geom["type"] == "LineString":
            trk = g.GPXTrack(name=name)
            seg = g.GPXTrackSegment()
            seg.points = [g.GPXTrackPoint(lat, lon) for lon, lat in geom["coordinates"]]
            trk.segments.append(seg)
            gpx.tracks.append(trk)
        elif geom["type"] == "Polygon":
            trk = g.GPXTrack(name=f"{name} #{p.get('rank','')}")
            seg = g.GPXTrackSegment()
            seg.points = [g.GPXTrackPoint(lat, lon) for lon, lat in geom["coordinates"][0]]
            trk.segments.append(seg)
            gpx.tracks.append(trk)
    path.write_text(gpx.to_xml())


def _export_kml(fc, leg, path):
    import simplekml

    kml = simplekml.Kml()
    for f in fc["features"]:
        p = f["properties"]
        k = p.get("legend")
        info = leg.get(k, {})
        color = info.get("color", "#ffff00")
        name = info.get("label_en", k)
        geom = f["geometry"]
        if geom["type"] == "Point":
            lon, lat = geom["coordinates"]
            pt = kml.newpoint(name=name, coords=[(lon, lat)])
            pt.style.iconstyle.color = _hex_to_kmlabgr(color)
        elif geom["type"] == "LineString":
            ls = kml.newlinestring(name=name, coords=geom["coordinates"])
            ls.style.linestyle.color = _hex_to_kmlabgr(color)
            ls.style.linestyle.width = 3
        elif geom["type"] == "Polygon":
            pol = kml.newpolygon(name=f"{name} #{p.get('rank','')}",
                                 outerboundaryis=geom["coordinates"][0])
            pol.style.linestyle.color = _hex_to_kmlabgr(color)
            pol.style.linestyle.width = 2
            pol.style.polystyle.color = _hex_to_kmlabgr(color, alpha="40")
    kml.save(str(path))


def _wgs84_overlay_jpg(ctx, cache, out_jpg):
    """Reproject hillshade+huntability to an EPSG:4326-aligned RGB JPEG so it
    registers under a Leaflet ImageOverlay. JPEG (not RGBA PNG) keeps the inlined
    data URI small — the whole self-contained map stays well under ~1 MB. Where
    huntability is nodata (open water), fall back to bare hillshade so terrain
    still shows. Returns [[S,W],[N,E]] bounds."""
    import imageio.v2 as imageio
    import numpy as np
    from matplotlib import colormaps
    from matplotlib.colors import LightSource
    from rasterio.transform import from_bounds
    from rasterio.warp import Resampling, reproject

    from . import rasterio_utils as ru

    dem, prof = ru.read(cache / "dem.tif")
    hunt = ru.read(cache / "huntability.tif")[0]
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    Wd = 1100
    Hd = max(1, int(Wd * (maxlat - minlat) / (maxlon - minlon)))
    dst_tr = from_bounds(minlon, minlat, maxlon, maxlat, Wd, Hd)

    def warp(a):
        d = np.full((Hd, Wd), np.nan, "float32")
        reproject(a, d, src_transform=prof["transform"], src_crs=prof["crs"],
                  dst_transform=dst_tr, dst_crs="EPSG:4326",
                  src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear)
        return d

    hunt4 = warp(hunt)
    # PURE huntability (turbo): red = model says best moose ground, blue = worst.
    # The basemap supplies terrain — do NOT blend hillshade in (that made it read
    # as topography). Where there's no score (open water), go neutral grey.
    heat = colormaps["turbo"](np.clip(np.nan_to_num(hunt4), 0, 1))[..., :3]
    grey = np.full_like(heat, 0.5)
    m = np.isfinite(hunt4)[..., None]
    rgb = np.where(m, heat, grey)
    imageio.imwrite(out_jpg, (rgb * 255).astype("uint8"), quality=82)
    return [[minlat, minlon], [maxlat, maxlon]]


def _roads_geojson(cache):
    """Roads as WGS84 GeoJSON for the map (best-effort)."""
    import geopandas as gpd

    p = cache / "roads.gpkg"
    if not p.exists():
        return None
    g = gpd.read_file(p)
    if g.crs and g.crs.to_epsg() != 4326:
        g = g.to_crs(4326)
    g["geometry"] = g.geometry.simplify(0.0003)
    return json.loads(g[["geometry"]].to_json())


def _export_html(ctx, fc, leg, cache, path):
    """Interactive Leaflet map: streaming base layers (satellite/topo/OSM/terrain)
    + inlined huntability overlay + roads + PER-AREA toggles + a swatch legend.
    Focus-area popups carry the written 'why / pros / watch-outs'."""
    import base64

    from .config import assets_dir

    ad = assets_dir() / "leaflet"
    leaflet_js = (ad / "leaflet.js").read_text()
    leaflet_css = (ad / "leaflet.css").read_text()

    overlay_tag, bounds = "null", None
    ov = path.parent / "_overlay.jpg"
    try:
        bounds = _wgs84_overlay_jpg(ctx, cache, ov)
        overlay_tag = json.dumps("data:image/jpeg;base64," + base64.b64encode(ov.read_bytes()).decode())
        ov.unlink(missing_ok=True)
    except Exception:
        bounds = None

    # group features: per focus area (polygon + its sites) + a shared group.
    areas, shared = {}, []
    for f in fc["features"]:
        p = f["properties"]
        fa = p.get("focus_area") or (p.get("rank") if p["legend"] == "focus_area" else None)
        if fa is not None:
            areas.setdefault(fa, []).append(f)
        else:
            shared.append(f)

    def color_of(k):
        return leg.get(k, {}).get("color", "#ffcc00")

    def label_of(k):
        return leg.get(k, {}).get("label_en", k)

    area_layers = []
    for rank in sorted(areas):
        feats = areas[rank]
        poly = next((x for x in feats if x["properties"]["legend"] == "focus_area"), None)
        title = f"Focus Area {rank}"
        if poly:
            pp = poly["properties"]
            title += f" — {pp.get('area_km2','?')} km² (hunt {pp.get('mean_huntability','?')})"
        area_layers.append({"rank": rank, "title": title,
                            "geojson": {"type": "FeatureCollection", "features": feats}})
    shared_gj = {"type": "FeatureCollection", "features": shared}

    # legend swatches (only types actually present)
    present = {f["properties"]["legend"] for f in fc["features"]}
    order = ["focus_area", "rut_calling", "thermal_refuge", "saline_blind", "funnel",
             "glassing", "validate_ground", "base_camp", "parking",
             "route_best", "route_midday_hot"]
    legend_items = [{"label": label_of(k), "color": color_of(k),
                     "shape": ("poly" if k == "focus_area" else
                               "line" if k.startswith("route") else "dot")}
                    for k in order if k in present]

    color_map = {k: color_of(k) for k in present}
    lat, lon = ctx.aoi.center.lat, ctx.aoi.center.lon

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Moose Scout — {ctx.aoi.title}</title>
<style>{leaflet_css}
html,body,#map{{height:100%;margin:0}}
.info,.legend{{background:#111;color:#eee;padding:8px 10px;font:12px system-ui;border-radius:6px}}
.info{{max-width:300px}} .legend{{max-width:230px;line-height:1.7}}
.legend i{{display:inline-block;width:14px;height:14px;margin-right:6px;vertical-align:-2px;border:1px solid #000}}
.legend .dot{{border-radius:50%}} .legend .line{{height:0;border:0;border-top:3px dashed}}
.legend .poly{{background:transparent;border:2px solid}}
.leaflet-popup-content{{font:13px system-ui;max-width:280px}} h4{{margin:.2em 0}} ul{{margin:.2em 0 .2em 1em;padding:0}}
.arealbl div{{width:30px;height:30px;border-radius:50%;background:#111;color:#fff;border:3px solid #fff;
  box-shadow:0 1px 4px rgba(0,0,0,.6);font:bold 16px system-ui;text-align:center;line-height:26px}}
.arealbl.top div{{background:#127a2e}}</style></head>
<body><div id="map"></div>
<script>{leaflet_js}</script>
<script>
var COLORS={json.dumps(color_map)};
var esriAttr='Tiles © Esri', osmAttr='© OpenStreetMap contributors';
var sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:esriAttr+' — World Imagery'}});
var topo=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:esriAttr+' — World Topo'}});
var otopo=L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:17,attribution:osmAttr+', SRTM | © OpenTopoMap'}});
var osm=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:osmAttr}});
var terrain=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Hillshade/MapServer/tile/{{z}}/{{y}}/{{x}}',{{maxZoom:19,attribution:esriAttr+' — Hillshade'}});
var map=L.map('map',{{center:[{lat},{lon}],zoom:11,layers:[sat]}});
var baseLayers={{'Satellite (Esri)':sat,'Topographic':topo,'OpenTopoMap':otopo,'OpenStreetMap':osm,'Terrain / hillshade':terrain}};
var overlays={{}};

var bounds={json.dumps(bounds)}, overlay={overlay_tag};
// Heat is the underlying model surface — available as a toggle, OFF by default.
// The tool leads with discrete ranked AREAS, not a broad heatmap.
if(overlay&&bounds){{ overlays['Huntability model (heat)']=L.imageOverlay(overlay,bounds,{{opacity:0.5}}); map.fitBounds(bounds); }}

var roads={json.dumps(_roads_geojson(cache))};
if(roads){{ overlays['Roads']=L.geoJSON(roads,{{style:{{color:'#ff5a1f',weight:2,opacity:0.9}}}}).addTo(map); }}

function popup(f){{
  var p=f.properties, k=p.legend, h='<h4>'+({json.dumps({k: label_of(k) for k in present})}[k]||k)+'</h4>';
  if(k=='focus_area'){{
    if(p.why) h+='<p>'+p.why+'</p>';
    if(p.pros&&p.pros.length) h+='<b>Pros</b><ul><li>'+p.pros.join('</li><li>')+'</li></ul>';
    if(p.cons&&p.cons.length) h+='<b>Watch-outs</b><ul><li>'+p.cons.join('</li><li>')+'</li></ul>';
  }} else {{ for(var kk in p){{ if(kk!='legend'&&kk!='focus_area') h+='<b>'+kk+':</b> '+p[kk]+'<br>'; }} }}
  return h;
}}
function mkLayer(gj){{
  return L.geoJSON(gj,{{
    style:function(f){{var c=COLORS[f.properties.legend]||'#ffcc00';
      return {{color:f.properties.legend=='focus_area'?'#000':c,weight:3,fillColor:c,
        fillOpacity:f.geometry.type=='Polygon'?0.06:0.1,
        dashArray:(f.properties.legend||'').indexOf('route')>=0?'6,6':null}};}},
    pointToLayer:function(f,ll){{return L.circleMarker(ll,{{radius:6,color:'#fff',weight:1.5,
      fillColor:COLORS[f.properties.legend]||'#ffcc00',fillOpacity:0.95}});}},
    onEachFeature:function(f,l){{l.bindPopup(popup(f));}}
  }});
}}
var AREAS={json.dumps(area_layers)};
AREAS.forEach(function(A){{
  var g=mkLayer(A.geojson).addTo(map); overlays[A.title]=g;
  A.geojson.features.forEach(function(f){{
    if(f.properties.legend=='focus_area'){{
      var c=f.properties.centroid;  // [lon,lat]
      var badge=L.marker([c[1],c[0]],{{icon:L.divIcon({{
        className:'arealbl'+(f.properties.rank<=2?' top':''),
        html:'<div>'+f.properties.rank+'</div>',iconSize:[30,30],iconAnchor:[15,15]}}),
        zIndexOffset:1000}}).bindPopup(popup(f));
      g.addLayer(badge);
    }}
  }});
}});
var shared={json.dumps(shared_gj)};
if(shared.features.length) overlays['Base camps & routes']=mkLayer(shared).addTo(map);

L.control.layers(baseLayers,overlays,{{collapsed:false}}).addTo(map);

var legend=L.control({{position:'bottomleft'}});
legend.onAdd=function(){{var d=L.DomUtil.create('div','legend');
  var items={json.dumps(legend_items)};
  var h='<b>Huntability</b> (model score)<br>'+
    '<div style="height:10px;border-radius:2px;margin:3px 0;background:linear-gradient(to right,#3b4cc0,#22c78f,#f9e721,#d23105)"></div>'+
    '<small>Lower&nbsp;←&nbsp;&nbsp;→&nbsp;Higher</small><hr style="border-color:#333;margin:6px 0"><b>Legend</b><br>';
  items.forEach(function(it){{
    var st='background:'+it.color+';border-color:'+it.color+';';
    if(it.shape=='line') st='border-top-color:'+it.color+';';
    if(it.shape=='poly') st='border-color:#000;';
    h+='<i class="'+it.shape+'" style="'+st+'"></i>'+it.label+'<br>';
  }});
  h+='<i class="line" style="border-top-color:#ff5a1f;"></i>Roads<br>';
  d.innerHTML=h; return d;}};
legend.addTo(map);

// --- measure tool (self-contained): click to add points, shows total km ---
var mMode=false, mPts=[], mLine=null, mMarks=[];
var measure=L.control({{position:'topleft'}});
measure.onAdd=function(){{
  var b=L.DomUtil.create('div','info'); b.style.cursor='pointer'; b.style.padding='6px 8px';
  b.innerHTML='📏 Measure'; b.id='measbtn';
  L.DomEvent.disableClickPropagation(b);
  b.onclick=function(){{ mMode=!mMode; b.innerHTML=mMode?'📏 Measuring… (click points; click here to stop)':'📏 Measure';
    if(!mMode){{ if(mLine)map.removeLayer(mLine); mMarks.forEach(function(x){{map.removeLayer(x);}}); mPts=[];mMarks=[];mLine=null; }} }};
  return b;}};
measure.addTo(map);
map.on('click',function(e){{ if(!mMode)return;
  mPts.push(e.latlng);
  mMarks.push(L.circleMarker(e.latlng,{{radius:3,color:'#fff',fillColor:'#111',fillOpacity:1}}).addTo(map));
  if(mLine)map.removeLayer(mLine);
  mLine=L.polyline(mPts,{{color:'#fff',weight:2,dashArray:'4,4'}}).addTo(map);
  var tot=0; for(var i=1;i<mPts.length;i++) tot+=map.distance(mPts[i-1],mPts[i]);
  mLine.bindTooltip((tot/1000).toFixed(2)+' km',{{permanent:true,direction:'top'}}).openTooltip(mPts[mPts.length-1]);
}});

var info=L.control({{position:'topright'}});
info.onAdd=function(){{var d=L.DomUtil.create('div','info');
 d.innerHTML='<b>Moose Scout — {ctx.aoi.title}</b><br>Heat = model huntability (red best). '+
 'Switch basemap / toggle each area ↗ · click a focus area for the <i>why</i> + pros/cons · '+
 '<b>the box is the analysed area</b> · à valider sur le terrain.';return d;}};
info.addTo(map);
</script></body></html>"""
    path.write_text(html)


def _render_map(ctx, fc, leg, cache, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import LightSource
    from pyproj import Transformer

    from . import rasterio_utils as ru

    dem, prof = ru.read(cache / "dem.tif")
    hunt = ru.read(cache / "huntability.tif")[0]
    T = prof["transform"]
    h, w = dem.shape
    extent = [T.c, T.c + w * T.a, T.f + h * T.e, T.f]  # xmin,xmax,ymin,ymax (m)

    fig, ax = plt.subplots(figsize=(12, 12), dpi=110)
    ls = LightSource(azdeg=315, altdeg=45)
    hs = ls.hillshade(np.nan_to_num(dem), vert_exag=3, dx=T.a, dy=-T.e)
    ax.imshow(hs, cmap="gray", extent=extent, origin="upper")
    ax.imshow(np.ma.masked_invalid(hunt), cmap="turbo", alpha=0.5, extent=extent,
              origin="upper", vmin=0, vmax=1)

    tr = Transformer.from_crs("EPSG:4326", prof["crs"], always_xy=True)

    def xy(lon, lat):
        return tr.transform(lon, lat)

    seen = set()
    for f in fc["features"]:
        p = f["properties"]
        k = p["legend"]
        info = leg.get(k, {})
        color = info.get("color", "#ffff00")
        label = info.get("label_en", k) if k not in seen else None
        seen.add(k)
        geom = f["geometry"]
        if geom["type"] == "Point":
            x, y = xy(*geom["coordinates"])
            ax.plot(x, y, "o", color=color, markersize=7, markeredgecolor="k",
                    markeredgewidth=0.6, label=label)
        elif geom["type"] == "LineString":
            xs, ys = zip(*[xy(lo, la) for lo, la in geom["coordinates"]])
            ax.plot(xs, ys, "--", color=color, linewidth=2, label=label)
        elif geom["type"] == "Polygon":
            xs, ys = zip(*[xy(lo, la) for lo, la in geom["coordinates"][0]])
            ax.plot(xs, ys, "-", color="black", linewidth=2, label=label)
            ax.annotate(f"#{p.get('rank','')}", (np.mean(xs), np.mean(ys)),
                        color="black", fontsize=13, fontweight="bold", ha="center")

    ax.set_title(f"Moose Scout — {ctx.aoi.title}  ·  huntability + focus areas",
                 fontsize=14)
    ax.set_xlabel("Easting (m, EPSG:32198)")
    ax.set_ylabel("Northing (m)")
    ax.legend(loc="upper right", fontsize=7, framealpha=0.9, ncol=2)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
