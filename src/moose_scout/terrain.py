"""Stage 2 — terrain engine (numpy/scipy/skimage; no external binary).

From cache/<aoi>/dem.tif derive, on the working grid:
  slope.tif   — slope in degrees
  aspect.tif  — aspect in degrees (0=N, 90=E)
  tpi.tif     — topographic position (dem - focal mean); + ridge / - valley
  wet.tif     — wetness proxy 0..1 (low slope AND valley) → bog/wallow/flat flats
  funnel.tif  — saddle/pass strength 0..1 (Hessian eigenvalues of opposite sign)
                → Charles Dorris "passe naturel ou entonnoir"
  coolaspect.tif — 0..1 north-facing (thermal-refuge input)

These feed the HSM (habitat), the funnel/pass features, and thermal refuges.
"""
from __future__ import annotations

import json

from .config import Context, cache_dir
from . import rasterio_utils as ru


def run(ctx: Context) -> None:
    import numpy as np
    from scipy.ndimage import gaussian_filter, uniform_filter
    from skimage.feature import hessian_matrix, hessian_matrix_eigvals

    aoi = ctx.aoi.name
    dem_path = cache_dir(aoi) / "dem.tif"
    if not dem_path.exists():
        raise FileNotFoundError("dem.tif — run acquire first")
    tdir = cache_dir(aoi) / "terrain"
    tdir.mkdir(parents=True, exist_ok=True)

    dem, prof = ru.read(dem_path)
    res = abs(prof["transform"].a)  # metres/pixel
    mask = np.isfinite(dem)
    demf = dem.copy()
    demf[~mask] = np.nanmean(dem)
    demf = gaussian_filter(demf, sigma=1.0)

    # --- slope & aspect (gradient in metres) ---
    dzdy, dzdx = np.gradient(demf, res, res)
    slope = np.degrees(np.arctan(np.hypot(dzdx, dzdy)))
    aspect = (np.degrees(np.arctan2(dzdy, -dzdx)) + 360) % 360

    # --- TPI: elevation minus local mean (~500 m window) ---
    win = max(3, int(round(500 / res)) | 1)
    tpi = demf - uniform_filter(demf, size=win)

    # --- wetness proxy: valley bottoms & flats (low slope AND low TPI) ---
    # FIXED PHYSICAL BOUNDS, not percentiles: a percentile stretch makes every output
    # a within-AOI rank, so "0.85" means something different in every search box and
    # nothing is comparable between areas (or to a deep sub-box of itself).
    # TPI in metres below/above the 500 m neighbourhood; slope in degrees.
    wet = ru.normalize(-tpi, lo=-5.0, hi=15.0) * ru.normalize(slope, lo=0.0, hi=15.0, invert=True)

    # --- funnels / passes ------------------------------------------------------
    # A moose funnel is a TRAVEL CONSTRICTION — a neck of passable ground squeezed
    # between barriers — not merely a topographic saddle. In this boreal country the
    # dominant barriers are WATER and WETLAND: the classic funnel is the land bridge
    # between two lakes, or the narrows a travelling bull is forced through. The old
    # detector was a pure DEM Hessian saddle, which its own comment admitted is
    # "largely resampling noise" on the <2.5° ground that is most of this landscape —
    # so it scattered low-confidence funnels over flat terrain. Rebuilt as a
    # constriction detector on the water/wetland barrier field, with the topographic
    # saddle kept only as a minor contributor where the ground is actually steep
    # enough for a pass to mean something.
    from scipy.ndimage import distance_transform_edt, maximum_filter
    barrier = np.zeros(dem.shape, bool)
    # wetland_grhq.tif = MRNF GRHQ mapped wetlands (milieu humide) — real marsh/bog/fen a
    # moose routes AROUND, so it forms land-bridge funnels the soft wetness proxy misses (#62).
    # WATER ONLY. Wetland used to be in here on the assumption that "a moose routes
    # AROUND marsh/bog/fen" — my assumption, never measured, and wrong: a moose walks
    # through a bog perfectly well. It is just not a FUNNEL, because nothing is forced
    # through it. Treating bog as a barrier manufactured necks out of every strip of dry
    # ground between two bogs, which is a constriction only on paper.
    #
    # Bog still matters — it damps funnel quality further down, because a neck across wet
    # ground is not a preferred travel route — but it does not create one.
    for nm in ("water.tif",):
        try:
            w = ru.read(cache_dir(aoi) / nm)[0]
        except Exception:
            w = None
        if w is not None and w.shape == dem.shape:
            barrier |= np.nan_to_num(w) > 0
    # Narrow rivers OSM maps but the 10 m WorldCover water raster misses are real travel
    # barriers too — rasterize the OSM river/canal lines (lightly buffered) into the
    # barrier so funnels form between them. Zero new data (already cached, if acquired).
    try:
        import geopandas as gpd
        from rasterio.features import rasterize as _rasterize
        wl = cache_dir(aoi) / "waterways.gpkg"
        if wl.exists():
            gw = gpd.read_file(wl)
            if "waterway" in gw.columns:
                gw = gw[gw["waterway"].isin(["river", "canal"])]
            if len(gw):
                if gw.crs and gw.crs.to_epsg() != prof["crs"].to_epsg():
                    gw = gw.to_crs(prof["crs"])
                buf = gw.geometry.buffer(max(res, 15.0))          # give the line real width
                rr = _rasterize(((geom, 1) for geom in buf if geom is not None and not geom.is_empty),
                                out_shape=dem.shape, transform=prof["transform"], fill=0,
                                dtype="uint8", all_touched=True)
                barrier |= rr > 0
    except Exception:
        pass
    # ...and the OSM LAKE polygons. WorldCover (water.tif) misses lakes in remote areas,
    # so on a lake-rich AOI whose lakes are OSM-only the barrier saw no water at all and
    # the constriction detector found no necks → funnels came back empty ("NO DATA") on
    # exactly the ground richest in land-bridge funnels (user-reported). Same waterbodies
    # the map and the walk-cost barrier use, so all three agree on where the water is.
    try:
        import geopandas as gpd
        from rasterio.features import rasterize as _rasterize
        wb = cache_dir(aoi) / "waterbodies.gpkg"
        if wb.exists():
            gp = gpd.read_file(wb)
            if len(gp):
                if gp.crs and gp.crs.to_epsg() != prof["crs"].to_epsg():
                    gp = gp.to_crs(prof["crs"])
                rr = _rasterize(((geom, 1) for geom in gp.geometry if geom is not None and not geom.is_empty),
                                out_shape=dem.shape, transform=prof["transform"], fill=0,
                                dtype="uint8", all_touched=True)
                barrier |= rr > 0
    except Exception:
        pass

    constriction = np.zeros(dem.shape, "float32")
    if barrier.any():
        passable = ~barrier
        # Distance to the nearest barrier. The medial-axis (corridor-centre) value is the
        # corridor HALF-width, so full corridor width = 2*db. The old detector scored
        # absolute half-width up to 700 m — admitting ~1.4 km-wide "funnels" and lighting
        # a uniform isthmus end-to-end. A real funnel is a NECK: narrow in absolute terms
        # AND a local minimum of corridor width (it pinches HERE vs up/downstream).
        db = distance_transform_edt(passable) * res
        ridge = (db >= maximum_filter(db, size=3) - 1e-6) & passable & (db > res)
        full_w = 2.0 * db
        # HOW TIGHT IS TIGHT. This was (300 - w)/300, which scores a 250 m land bridge at
        # 0.17 — under the threshold that polygonizes a funnel at all. A 250 m neck
        # between two lakes is a strong funnel, not a marginal one. The old scaling
        # survived only because the topographic saddle was supplying most of the signal;
        # removing that term exposed it.
        #
        # Now: full strength at or below ~250 m, fading out by ~600 m. Below 250 m a
        # travelling bull is genuinely pinched; by 600 m he has room to go around, which
        # is the distinction the number is trying to capture.
        NECK_M = 600.0
        FULL_AT = 250.0
        narrow = np.clip((NECK_M - full_w) / (NECK_M - FULL_AT), 0.0, 1.0)
        # Local minimum: compare db to its ~600 m neighbourhood average; where the corridor
        # is markedly narrower than nearby, it is squeezing — that is the pinch.
        db_local = uniform_filter(db, size=max(3, int(round(600 / res)) | 1))
        pinch = np.clip((db_local - db) / (db_local + 1e-6), 0.0, 1.0)
        strength = narrow * (0.35 + 0.65 * pinch)
        constriction = np.where(ridge & (full_w < NECK_M), strength, 0.0).astype("float32")
        # THICKEN ENOUGH TO SURVIVE THE POLYGONIZER. The medial axis is a 1-px line; 120 m
        # made it ~3 px at 40 m, and _polygonize opens with 3 iterations — which erodes
        # 3 px before dilating and therefore deleted the entire ribbon. Measured: 7,444
        # cells scored, 7,223 survived smoothing, 0 survived the opening. Every funnel
        # the map has ever shown was a broad topo blob, because those were the only shapes
        # fat enough to live through it — which is precisely why they looked wrong on the
        # ground.
        #
        # 280 m is not a fudge to beat the morphology: a neck's zone of influence really
        # is a couple of hundred metres either side of the centreline — that is where you
        # would sit to watch it.
        constriction = maximum_filter(constriction, size=max(3, int(round(280 / res)) | 1))
        # PERSIST THE MEASUREMENT, not just the score. "Funnel / pass · 0.1 km²" tells a
        # hunter nothing about whether to believe it; "a 180 m neck" is checkable against
        # the map in front of them. Width is the honest unit for a constriction, and it
        # is the number that makes a bad funnel obviously bad.
        funnel_w = np.where(constriction > 0, full_w, np.nan).astype("float32")
        funnel_w = maximum_filter(np.nan_to_num(funnel_w, nan=0.0),
                                  size=max(3, int(round(280 / res)) | 1))
        funnel_w = np.where(constriction > 0, funnel_w, np.nan).astype("float32")
        ru.write(cache_dir(aoi) / "funnel_width.tif", funnel_w, prof)
        # How much of the barrier is WETLAND rather than open water. WorldCover barely
        # sees boreal peatland (0.4% of one test AOI, against 7.5% from MRNF GRHQ), so
        # when GRHQ is missing bog silently becomes PASSABLE and necks get drawn straight
        # through it — a funnel in the middle of a bog, which is not a funnel. Record the
        # share so the contract can caveat the layer instead of presenting it flat.
        try:
            _wet = np.zeros(dem.shape, bool)
            for nm in ("wetland.tif", "wetland_grhq.tif"):
                try:
                    w = ru.read(cache_dir(aoi) / nm)[0]
                    if w is not None and w.shape == dem.shape:
                        _wet |= np.nan_to_num(w) > 0
                except Exception:
                    pass
            (cache_dir(aoi) / "funnel_barrier.json").write_text(json.dumps({
                "barrier_frac": round(float(barrier.mean()), 4),
                "wetland_frac": round(float(_wet.mean()), 4),
                "grhq_present": (cache_dir(aoi) / "wetland_grhq.tif").exists()}))
        except Exception as _e:
            print(f"[terrain] funnel barrier note not written: {_e}")

    # topographic saddle — trustworthy ONLY on steep ground; near-zero and noisy on
    # flats, so gate it hard by slope instead of letting it dominate.
    Hxx, Hxy, Hyy = hessian_matrix(demf, sigma=max(1.0, 60.0 / res), order="rc",
                                   use_gaussian_derivatives=False)
    l1, l2 = hessian_matrix_eigvals([Hxx, Hxy, Hyy])
    saddle = np.where(l1 * l2 < 0, -(l1 * l2), 0.0)
    steep_gate = ru.normalize(slope, lo=5.0, hi=20.0)      # 0 below 5°, ramps to 20°
    topo = ru.normalize(saddle) * steep_gate

    # A FUNNEL MUST HAVE A NECK YOU CAN MEASURE.
    #
    # This was max(constriction, 0.6*topo), which let the topographic saddle create
    # funnels ON ITS OWN. Measured on a real AOI, that term produced 18,328 of 31,089
    # funnel cells — 59% — none of which had any measurable constriction, on ground whose
    # own code comment calls the saddle signal "largely resampling noise". Those are the
    # funnels that show up in the middle of a bog and cannot say how wide they are.
    #
    # Topo is now a BOOSTER of a real constriction, never a source of one: a saddle makes
    # an existing neck more compelling, but "steep-ish and slightly concave" is not a
    # funnel. Every funnel that survives can state its width.
    funnel = (constriction * (1.0 + 0.30 * np.clip(topo, 0.0, 1.0))).astype("float32")
    # Wet ground damps it: a neck a moose CAN cross but has no reason to prefer is a
    # weaker funnel than the same neck on dry ground.
    try:
        _wetpen = np.zeros(dem.shape, "float32")
        for nm in ("wetland.tif", "wetland_grhq.tif"):
            try:
                w = ru.read(cache_dir(aoi) / nm)[0]
                if w is not None and w.shape == dem.shape:
                    _wetpen = np.maximum(_wetpen, np.nan_to_num(w) > 0)
            except Exception:
                pass
        funnel = (funnel * (1.0 - 0.55 * _wetpen)).astype("float32")
    except Exception:
        pass
    funnel = np.clip(funnel, 0.0, 1.0).astype("float32")

    # --- cool (north-facing) aspect 0..1 for thermal refuge ---
    cool = (np.cos(np.radians(aspect)) + 1) / 2  # 1 at N(0/360), 0 at S(180)

    for name, arr in [
        ("slope", slope), ("aspect", aspect), ("tpi", tpi),
        ("wet", wet), ("funnel", funnel), ("coolaspect", cool),
    ]:
        a = arr.copy()
        a[~mask] = np.nan
        ru.write(tdir / f"{name}.tif", a, prof)
