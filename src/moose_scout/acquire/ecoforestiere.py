"""Écoforestière stand data — MRNF "Carte écoforestière à jour (avec perturbations)".

The habitat backbone south of ~52°N: real stand SPECIES (résineux / mélangé / feuillu),
CANOPY CLOSURE (density class A–D), and dated DISTURBANCES (cuts + burns). This is what
lets thermal refuge see conifer + closure (not "any tree"), lets browse count logging
CUTS by age (the dominant browse source in commercial forest, not just fire), and gives
the rut edge real cover/opening structure.

Live WFS (MapServer, verified): geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi, WFS 2.0.0,
layer `ms:ori_pee_close_scale` (peuplements écoforestiers), native EPSG:32198. A bbox
entirely NORTH of the ~52°N inventory limit returns HTTP 400 — treated as "no coverage",
not an error, so the pipeline falls back to WorldCover + Sentinel-2 there.

Writes (on the working grid; 0 / nodata where no stand):
  stand_type.tif     int16 cover-type code — 1 résineux · 2 mélangé · 3 feuillu ·
                     4 recent cut/regen · 5 partial cut · 6 burn · 7 tourbière ·
                     0 none/non-forest
  stand_closure.tif  float32 canopy closure 0..1 (from density class A–D)
  cut_year.tif       int16 year of the most recent CUT origin (0 = none) → browse age
  stand_height.tif   float32 representative stand height in METRES (0 = unknown)
  stand_age.tif      int16 stand age in years (0 = unknown; uneven-aged classes mapped)
  stand_slope.tif    float32 slope class as a percent grade (0 = unknown)
  stand_ess_browse.tif  float32 0..1 browse value of the SPECIES composition (E11.2)
  stands.gpkg        the polygons with their survey attributes, for the map (E11.6)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..config import Context, cache_dir
from ..rasterio_utils import target_grid

WFS = os.environ.get("ECOFOR_WFS", "https://geoegl.msp.gouv.qc.ca/ws/mffpecofor.fcgi")
LAYER = os.environ.get("ECOFOR_LAYER", "ms:ori_pee_close_scale")
NATIVE_CRS = "EPSG:32198"
GEOJSON = "application/json; subtype=geojson; charset=iso-8859-1"

# Stand-origin / perturbation codes (MRNF 5e inventaire). Origin = disturbance that
# established the stand (>75% BA removed); perturbation = partial (25–75%).
CUT_ORIGINS = {"CT", "CTSP_T", "CTSP_U", "CPR", "CPRS_U", "CPT", "CPPTM_U", "RPS",
               "P", "PL", "PLR"}                       # total harvest / plantation origin
BURN_ORIGINS = {"BR"}
PARTIAL_CUTS = {"CP", "CJ", "CJB", "CJG", "CJPG", "CPS", "CPR_T", "CPR_U", "CEA", "EJ", "EC"}

# cover-type code the raster carries
T_RESINEUX, T_MELANGE, T_FEUILLU, T_CUT, T_PARTIAL, T_BURN = 1, 2, 3, 4, 5, 6
# PEATLAND, which used to be dropped on the floor (T10.23). A stand with no `type_couv`
# is not forest, and `_classify` returned None for all of them — 39 of 599 polygons over
# the 47.98, -77.82 sheet, 6.5% of the ground. Almost every one carries `dep_sur` 7x
# (organic deposit) with hydric drainage: peat bog and wet barren.
#
# That is not nothing. `config/species/moose.yaml` has carried a `tourbiere` class with
# browse 0.35 and wet 1.0 the whole time, and habitat.py's own comment said it was "only
# reachable through land cover" — while terrain.py documents that WorldCover barely sees
# boreal peatland (0.4% of one test AOI against 7.5% from GRHQ). A third source for it
# was in hand and thrown away.
T_TOURBIERE = 7
ORGANIC_DEPOSITS = ("7",)          # dep_sur 7E / 7T — organique épais / mince
HYDRIC_DRAINAGE = ("4", "5", "6")  # imparfait / mauvais / très mauvais

# --------------------------------------------------------------- E11.2: the rest of it
# Measured over 1908 stands around 47.98, -77.82, which is what these tables are built
# from rather than guessed at.

# `cl_haut` — MFFP height class → representative stand height in METRES.
# Sampled: 3 (748) · 4 (643) · 5 (181) · 2 (67) · 6 (35) · 1 (4).
HEIGHT_M = {"1": 24.0, "2": 19.5, "3": 14.5, "4": 9.5, "5": 5.5, "6": 3.0, "7": 1.0}

# A moose browses to roughly 3 m. So a stand's OWN foliage is food only in the short
# classes; taller stands feed an animal through their understory, which is a different
# claim and one this raster must not silently make. This is the gate that stops species
# data promoting 20 m hardwood to prime browse — see E11.3.
BROWSE_REACH_M = 3.0

# `cl_age` — even-aged stands carry a number; uneven-aged carry a letter code.
# J = jeune, V = vieux; IN = inéquienne, IR = irrégulière. Sampled: 50 · 30 · VIR · JIN ·
# JIR · VIN · 70 · 10 · 120 · 90 · 5050 (a two-storey stand, first storey wins).
UNEVEN_AGE = {"JIN": 40, "JIR": 40, "VIN": 100, "VIR": 100}

# `cl_pent` — slope class → representative PERCENT grade.
SLOPE_PCT = {"A": 1.5, "B": 6.0, "C": 12.0, "D": 23.0, "E": 35.0, "F": 50.0}

# `gr_ess` — the field the engine used to throw away entirely. It is a run of 2-character
# species codes, dominant first, repeated for a pure stand (ENEN = black spruce, pure).
#
# The value here is BROWSE VALUE TO A MOOSE, not "is it a hardwood". Balsam fir is a
# conifer and is genuinely browsed; larch is a conifer that is not. Black spruce is the
# thing this whole engine calls a food desert, and it is 46% of the sampled ground.
ESS_BROWSE = {
    # the money species
    "BP": 1.00, "BG": 0.95, "BJ": 0.85,          # bouleaux — paper / grey / yellow birch
    "PT": 1.00, "PE": 0.95, "PB": 0.90, "PA": 0.90,   # peupliers — aspen / poplar
    "SO": 0.95,                                   # sorbier — mountain-ash
    "ER": 0.70, "ES": 0.65, "EA": 0.70, "EO": 0.70,   # érables
    "FN": 0.60, "FA": 0.60, "FP": 0.55,           # frênes
    "FX": 0.70, "FI": 0.75, "FT": 0.60, "FH": 0.60,   # feuillus indéterminés / intolérants
    "CT": 0.55, "CR": 0.50, "CB": 0.50, "CC": 0.50,   # cerisiers / chênes
    "OA": 0.55, "TA": 0.55,                       # orme / tilleul
    # conifers a moose will actually take
    "SB": 0.35, "SE": 0.30,                       # sapin baumier — real winter browse
    "PG": 0.10, "PB_": 0.10, "PI": 0.10, "PS": 0.10,  # pins
    "TO": 0.20, "PU": 0.20,                       # thuya / pruche
    # conifers it will not
    "EN": 0.00, "EB": 0.05, "EP": 0.05, "EU": 0.05, "EV": 0.05,   # épinettes
    "ML": 0.05, "ME": 0.05, "MH": 0.05, "MJ": 0.05,               # mélèzes
    "RX": 0.05,                                   # résineux indéterminés
}
# Position weights: gr_ess is ordered by dominance, so the first pair carries the stand.
ESS_WEIGHTS = (0.5, 0.3, 0.2)

# Vertex de-duplication for the DISPLAY copy, in metres. Deliberately far finer than the
# analysis grid — see the note at the simplify call for the measurement that set it.
VEC_SIMPLIFY_M = float(os.environ.get("ECOFOR_SIMPLIFY_M", "1.0"))


def ess_browse(gr_ess: str) -> float:
    """0..1 browse value of a stand's species composition, dominance-weighted.

    Returns 0.0 for an unreadable or empty code rather than a middling guess: absent
    evidence is not evidence of forage, and the caller falls back to the cover class.
    """
    s = (gr_ess or "").strip().upper()
    codes = [s[i:i + 2] for i in range(0, len(s) - len(s) % 2, 2)]
    if not codes:
        return 0.0
    tot = wsum = 0.0
    for i, c in enumerate(codes[:3]):
        w = ESS_WEIGHTS[i] if i < len(ESS_WEIGHTS) else 0.0
        wsum += w
        tot += w * ESS_BROWSE.get(c, 0.10)     # unknown code: assume near-nil, not average
    return round(tot / wsum, 4) if wsum else 0.0


def stand_age(cl_age: str) -> int:
    """Stand age in years, 0 when unknown. Uneven-aged classes get a representative age."""
    s = (cl_age or "").strip().upper()
    if not s:
        return 0
    if s in UNEVEN_AGE:
        return UNEVEN_AGE[s]
    if s.isdigit():
        # `5050` is a two-storey stand written as two classes; the FIRST storey is the
        # one the canopy belongs to.
        return int(s[:2]) if len(s) == 4 else int(s)
    return 0
# density class A–D → mid canopy-closure fraction (A 80–100, B 60–80, C 40–60, D 25–40)
CLOSURE = {"A": 0.90, "B": 0.70, "C": 0.50, "D": 0.32}


def _fetch_page(bbox_native: str, start: int, count: int, timeout: int = 90):
    # The MapServer WFS accepts the query CRS ONLY as a suffix on BBOX (a separate SRSNAME
    # alongside it 400s), and then returns geometry in EPSG:4326 (lon,lat) regardless — so
    # we pass the bbox in native Lambert with the CRS appended and reproject the OUTPUT
    # from 4326. `quote` (not quote_plus) keeps the OUTPUTFORMAT spaces as %20, which the
    # server requires.
    q = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetFeature",
         "TYPENAMES": LAYER,
         "BBOX": bbox_native + ",urn:ogc:def:crs:EPSG::32198",
         "COUNT": str(count), "STARTINDEX": str(start), "OUTPUTFORMAT": GEOJSON}
    url = WFS + "?" + urllib.parse.urlencode(q, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={"User-Agent": "moose-scout/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace")), None
    except urllib.error.HTTPError as e:
        return None, e.code               # 400 = bbox outside the écoforestière extent
    except Exception:
        return None, -1


def _classify(props):
    """(cover-type code, cut_year) from a stand's attributes; None if non-forest/unknown."""
    def _yr(v):
        try:
            y = int(str(v)[:4])
            return y if 1900 < y < 2100 else 0
        except Exception:
            return 0
    origine = (props.get("origine") or "").strip().upper()
    perturb = (props.get("perturb") or "").strip().upper()
    tc = (props.get("type_couv") or "").strip().upper()
    if origine in CUT_ORIGINS:
        return T_CUT, _yr(props.get("an_origine"))
    if origine in BURN_ORIGINS:
        return T_BURN, 0
    if perturb in PARTIAL_CUTS:
        return T_PARTIAL, _yr(props.get("an_perturb"))
    if tc == "R":
        return T_RESINEUX, 0
    if tc == "M":
        return T_MELANGE, 0
    if tc == "F":
        return T_FEUILLU, 0
    # NOT FOREST — but not nothing either (T10.23). An organic deposit on hydric ground
    # is peatland, and the polygon says so even though it carries no cover type. Both
    # conditions are required: an organic deposit on well-drained ground is not a bog,
    # and hydric drainage under a forest cover was already handled above.
    dep = (props.get("dep_sur") or "").strip()
    drai = (props.get("cl_drai") or "").strip()
    if dep[:1] in ORGANIC_DEPOSITS and drai[:1] in HYDRIC_DRAINAGE:
        return T_TOURBIERE, 0
    return None, 0


def fetch(ctx: Context) -> None:
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.features import rasterize
    from shapely.geometry import shape as shp_shape
    from shapely.ops import transform as shp_transform

    cache = cache_dir(ctx.aoi.name)
    if (cache / "stand_type.tif").exists():
        return

    # E2: the region profile declares this source's coverage edge (écoforestière
    # thins to nothing north of ~52°N). If the whole AOI is outside it, don't even
    # attempt the heavy WFS pull that would only 400 — record absence and let habitat
    # fall back to WorldCover + Sentinel-2, exactly as the in-fetch 400 path does.
    try:
        from ..region import resolve_region, source_covers_aoi

        _srcs = {s.get("id"): s for s in (resolve_region(ctx).get("sources") or [])}
        _cov = (_srcs.get("ecoforestiere") or {}).get("coverage")
        if source_covers_aoi(_cov, ctx.aoi.bbox_wgs84()) == "out":
            (cache / "ecoforestiere_absent.flag").write_text("region")
            return
    except Exception:
        pass  # coverage check is an optimisation; the in-fetch 400 path still guards

    dst_crs, transform, w, h = target_grid(ctx)
    res_m = float(ctx.model.raster_resolution_m)
    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()

    # WFS bbox in native Lambert (easting,northing → minX,minY,maxX,maxY)
    to_native = Transformer.from_crs("EPSG:4326", NATIVE_CRS, always_xy=True)
    xs, ys = zip(*[to_native.transform(x, y) for x, y in
                   ((minlon, minlat), (minlon, maxlat), (maxlon, minlat), (maxlon, maxlat))])
    bbox = f"{min(xs):.1f},{min(ys):.1f},{max(xs):.1f},{max(ys):.1f}"

    to_dst = Transformer.from_crs("EPSG:4326", dst_crs, always_xy=True)   # output is 4326
    proj = lambda g: shp_transform(lambda xx, yy: to_dst.transform(xx, yy), g)  # noqa: E731

    # Rasterize PER PAGE and merge into the accumulators — the écoforestière is dense
    # (100k+ stands over a big box), so holding every geometry in memory OOMs the VM.
    st = np.zeros((h, w), "int16")
    cl = np.zeros((h, w), "float32")
    cy = np.zeros((h, w), "int16")
    # E11.2 — the attributes that arrive in the SAME response and were being discarded.
    # Free to collect; the download is the cost and it is already paid.
    hgt = np.zeros((h, w), "float32")     # metres
    age = np.zeros((h, w), "int16")       # years, 0 = unknown
    slp = np.zeros((h, w), "float32")     # percent grade
    esb = np.zeros((h, w), "float32")     # 0..1 browse value of the species composition
    # ...and the polygons themselves, for a map layer that can show what the survey says
    # (E11.6). A raster cannot carry `ENENBP`, and that label is the whole reason a guide's
    # sheet is worth looking at.
    vec = []
    seen_stands = 0
    truncated = False
    # Wall-clock budget: the écoforestière is dense and its geometry is heavy (~64 MB per
    # 8000 stands, no gzip), so a big box can be an ~800 MB / multi-minute download that
    # would blow the acquire step's per-source budget on the droplet. If we can't finish
    # inside BUDGET, DISCARD the partial pull and fall back cleanly to WorldCover + S2 —
    # a complete coarse layer beats a half-covered good one. (Env-tunable.)
    import time as _time
    # Full-stand pull is worth the wait (richest habitat signal); the budget is a safety
    # net for a genuinely stuck fetch, not a speed cap. Big boxes take several minutes.
    BUDGET = float(os.environ.get("ECOFOR_BUDGET_S", "800"))
    # A cap on the DISPLAY copy only. The rasters take every stand; this stops a dense
    # 70 km box turning a map layer into a hundred-megabyte download nobody asked for.
    MAX_VEC = int(os.environ.get("ECOFOR_MAX_VEC", "40000"))
    t0 = _time.time()
    got_any = False
    start, PAGE = 0, 8000
    while True:
        if _time.time() - t0 > BUDGET:
            (cache / "ecoforestiere_absent.flag").write_text("budget")
            return                        # too slow here → clean WorldCover fallback
        doc, err = _fetch_page(bbox, start, PAGE)
        if err == 400 and start == 0 and not got_any:
            # entirely north of the inventory limit — habitat leans on WorldCover + S2.
            (cache / "ecoforestiere_absent.flag").write_text("1")
            return
        if doc is None:
            break
        page = doc.get("features") or []
        if not page:
            break
        tsh, csh, ysh = [], [], []
        hsh, ash, ssh, esh = [], [], [], []
        for f in page:
            try:
                props = f.get("properties") or {}
                code, cut_yr = _classify(props)
                if code is None:
                    continue
                g = proj(shp_shape(f["geometry"]))
                if g.is_empty:
                    continue
                tsh.append((g, int(code)))
                seen_stands += 1
                if len(vec) >= MAX_VEC:
                    truncated = True
                clv = CLOSURE.get((props.get("cl_dens") or "").strip().upper()[:1], 0.0)
                if clv > 0:
                    csh.append((g, float(clv)))
                if code == T_CUT and cut_yr > 0:
                    ysh.append((g, int(cut_yr)))
                _h = HEIGHT_M.get((props.get("cl_haut") or "").strip()[:1], 0.0)
                _a = stand_age(props.get("cl_age"))
                _s = SLOPE_PCT.get((props.get("cl_pent") or "").strip().upper()[:1], 0.0)
                _e = ess_browse(props.get("gr_ess"))
                if _h > 0:
                    hsh.append((g, float(_h)))
                if _a > 0:
                    ash.append((g, int(_a)))
                if _s > 0:
                    ssh.append((g, float(_s)))
                if _e > 0:
                    esh.append((g, float(_e)))
                if len(vec) < MAX_VEC:
                    # DE-DUPLICATED, NOT GENERALISED. This first shipped simplified to
                    # the ANALYSIS GRID, on the reasoning that the model cannot resolve
                    # past its own cell size. That reasoning was wrong: the analysis grid
                    # bounds what the MODEL sees, not what the MAP should draw, and a
                    # stand boundary is exactly the thing a hunter reads closely — the
                    # cover-to-forage seam is where you put a stand. At 40 m the boundary
                    # moved 58.8 m at worst and 34.5 m on average. On a 1:11,000 sheet
                    # that is millimetres of visible error.
                    #
                    # Measured, 599 real stands at ~190 vertices each:
                    #     tol   size    worst move
                    #       1 m  48%       1.5 m
                    #       2 m  35%       2.9 m
                    #       5 m  24%       6.5 m
                    #      40 m  11%      58.8 m
                    # HALF the file goes in the first metre, because most of those
                    # vertices are near-collinear redundancy. And écoforestière is
                    # photo-interpreted at 1:20,000, so its own positional accuracy is
                    # around ±10 m — a 1 m tolerance sits well inside the source's own
                    # error. It removes encoding, not information.
                    #
                    # This does NOT solve payload and must not be mistaken for solving it:
                    # a 35 km box is ~84,000 stands, ~170 MB even at 1 m. Shipping that to
                    # a browser is a DELIVERY problem (E11.6), not a geometry one.
                    try:
                        gs = g.simplify(VEC_SIMPLIFY_M)
                        if gs.is_empty or not gs.is_valid:
                            gs = g
                    except Exception:
                        gs = g
                    vec.append({"geometry": gs, "cls": int(code),
                                "gr_ess": (props.get("gr_ess") or "").strip(),
                                "type_couv": (props.get("type_couv") or "").strip(),
                                "height_m": float(_h), "age_yr": int(_a),
                                "slope_pct": float(_s), "ess_browse": float(_e),
                                "closure": float(clv), "cut_year": int(cut_yr or 0),
                                "dep_sur": (props.get("dep_sur") or "").strip(),
                                "cl_drai": (props.get("cl_drai") or "").strip()})
            except Exception:
                continue
        if tsh:
            got_any = True
            pst = rasterize(tsh, out_shape=(h, w), transform=transform, fill=0,
                            dtype="float32").astype("int16")
            st = np.where(pst > 0, pst, st)
        if csh:
            pcl = rasterize(csh, out_shape=(h, w), transform=transform, fill=0.0,
                            dtype="float32")
            cl = np.maximum(cl, pcl)
        if ysh:
            pcy = rasterize(ysh, out_shape=(h, w), transform=transform, fill=0,
                            dtype="float32").astype("int16")
            cy = np.maximum(cy, pcy)          # most recent cut wins (higher year)
        # These merge by "last stand wins where it has a value", matching `st` — NOT by
        # maximum. A max would smear the tallest stand in the page across every cell its
        # neighbours touch, and height is the one field this must not exaggerate.
        for shapes, acc, dt in ((hsh, hgt, "float32"), (ash, age, "int16"),
                                (ssh, slp, "float32"), (esh, esb, "float32")):
            if not shapes:
                continue
            pr = rasterize(shapes, out_shape=(h, w), transform=transform, fill=0,
                           dtype="float32")
            acc[pr > 0] = pr[pr > 0].astype(dt) if dt == "int16" else pr[pr > 0]
        if len(page) < PAGE:
            break
        start += PAGE

    if not got_any:
        (cache / "ecoforestiere_absent.flag").write_text("1")
        return

    for name, arr, dt, nod in (("stand_type.tif", st, "int16", 0),
                               ("stand_closure.tif", cl, "float32", 0.0),
                               ("cut_year.tif", cy, "int16", 0),
                               ("stand_height.tif", hgt, "float32", 0.0),
                               ("stand_age.tif", age, "int16", 0),
                               ("stand_slope.tif", slp, "float32", 0.0),
                               ("stand_ess_browse.tif", esb, "float32", 0.0)):
        prof = {"driver": "GTiff", "dtype": dt, "count": 1, "height": h, "width": w,
                "crs": dst_crs, "transform": transform, "nodata": nod,
                "compress": "deflate", "tiled": True}
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(arr, 1)

    # THE POLYGONS, so the map can show what the survey actually says (E11.6). A raster
    # cannot carry `ENENBP`, and that label is the whole reason a guide's sheet is worth
    # looking at. Best-effort: this is a display artefact, and failing to write it must
    # never cost anyone the analysis that was already computed above.
    try:
        import geopandas as gpd

        if vec:
            gdf = gpd.GeoDataFrame(
                [{k: v for k, v in row.items() if k != "geometry"} for row in vec],
                geometry=[row["geometry"] for row in vec], crs=dst_crs)
            gdf.to_file(cache / "stands.gpkg", driver="GPKG", layer="stands")
        # A CAP THAT TRUNCATES IN SILENCE reads as "this is all the forest there is".
        # Say so, in the log and in a sidecar the map can render as a caveat.
        if truncated:
            print(f"[ecoforestiere] stand polygons capped at {MAX_VEC} of "
                  f"{seen_stands} — the map layer is partial; the RASTERS are complete")
        json.dump({"stands": len(vec), "seen": seen_stands,
                   "truncated": bool(truncated), "cap": MAX_VEC,
                   "simplify_m": VEC_SIMPLIFY_M},
                  open(cache / "stands.json", "w"))
    except Exception as e:  # noqa: BLE001
        print(f"[ecoforestiere] stand polygons not written: {e}")
