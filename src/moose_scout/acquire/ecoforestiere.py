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
                     4 recent cut/regen · 5 partial cut · 6 burn · 0 none/non-forest
  stand_closure.tif  float32 canopy closure 0..1 (from density class A–D)
  cut_year.tif       int16 year of the most recent CUT origin (0 = none) → browse age
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

    dst_crs, transform, w, h = target_grid(ctx)
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
    # Wall-clock budget: the écoforestière is dense and its geometry is heavy (~64 MB per
    # 8000 stands, no gzip), so a big box can be an ~800 MB / multi-minute download that
    # would blow the acquire step's per-source budget on the droplet. If we can't finish
    # inside BUDGET, DISCARD the partial pull and fall back cleanly to WorldCover + S2 —
    # a complete coarse layer beats a half-covered good one. (Env-tunable.)
    import time as _time
    BUDGET = float(os.environ.get("ECOFOR_BUDGET_S", "150"))
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
                clv = CLOSURE.get((props.get("cl_dens") or "").strip().upper()[:1], 0.0)
                if clv > 0:
                    csh.append((g, float(clv)))
                if code == T_CUT and cut_yr > 0:
                    ysh.append((g, int(cut_yr)))
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
        if len(page) < PAGE:
            break
        start += PAGE

    if not got_any:
        (cache / "ecoforestiere_absent.flag").write_text("1")
        return

    for name, arr, dt, nod in (("stand_type.tif", st, "int16", 0),
                               ("stand_closure.tif", cl, "float32", 0.0),
                               ("cut_year.tif", cy, "int16", 0)):
        prof = {"driver": "GTiff", "dtype": dt, "count": 1, "height": h, "width": w,
                "crs": dst_crs, "transform": transform, "nodata": nod,
                "compress": "deflate", "tiled": True}
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(arr, 1)
