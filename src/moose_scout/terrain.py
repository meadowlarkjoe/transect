"""Stage 2 — terrain engine (numpy/scipy/skimage; no external binary).

From cache/<aoi>/dem.tif derive, on the working grid:
  slope.tif   — slope in degrees
  aspect.tif  — aspect in degrees (0=N, 90=E)
  tpi.tif     — topographic position (dem - focal mean); + ridge / - valley
  prominence.tif — the same, but the PEAK within each analysis cell measured on the
                LiDAR fine grid where one exists (T9.10). Glassing reads this; `wet`
                and the habitat surface keep the coarse tpi, which is what they want.
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


# Cells the fine grid may use. The distance transform below carries this as float64 and
# the maximum filters add their own copies, so this is the number that decides whether a
# 70 km box survives in a 4 GB worker. Deliberately the same budget acquire/dem.py uses
# for its source read — the two grids should be the same size, not two guesses.
FINE_BUDGET_PX = 9_000_000
FINEST_M = 5.0                      # past this, the water vectors have no more to say


def _fine_res(res: float, shape) -> float:
    """Resolution to measure necks at: as fine as the budget allows, in a whole-number
    ratio to the analysis grid so a fine cell nests exactly inside a working one.

    OFF BY DEFAULT, and the reason is worth keeping. Measured against synthetic ground
    truth the fine grid is unambiguously more accurate: an 80 m neck reads 160 m at 40 m
    and 100 m at 10 m, and a real 40 m run reported four separate funnels at EXACTLY
    113 m — the quantization floor, not the terrain. That part is proven.

    What is NOT proven is the effect on the funnel POPULATION. On Joe's 47.967, -77.809
    box the count went 7 -> 3. The three that remain are each within 71 m of one the old
    detector found — so nothing was invented or displaced — and the ones that vanished
    scored 0.53, 0.40, 0.33 and 0.24. Losing the 0.53 is not something I can justify from
    the evidence I have, and the obvious lever (relaxing the polygonize admission bar
    until the count comes back) is precisely the mistake rev 21 made: retuning an
    absolute constant to make a number look familiar.

    So the measurement improvement sits here, in the repo, behind a switch, until a real
    A/B on ground Joe knows says which count is right. `FINE_NECKS=1` turns it on.
    """
    import os

    if os.environ.get("FINE_NECKS", "0") in ("0", "off", "false"):
        return res
    h, w = shape
    step = min(int((FINE_BUDGET_PX / float(h * w)) ** 0.5), int(res / FINEST_M))
    return res / max(1, step)


def _grid_at(transform, shape, res: float, fine_res: float):
    """The same extent and origin as the analysis grid, at `fine_res`."""
    from rasterio.transform import Affine

    k = max(1, int(round(res / fine_res)))
    h, w = shape
    return transform * Affine.scale(1.0 / k), (h * k, w * k)


def _block_reduce(arr, k: int, how: str, out_shape):
    """Fold a fine grid back into its parent analysis cells.

    NaN-aware: `min` over widths must ignore the NaN that marks "not a neck here",
    otherwise a single non-neck fine cell would blank the whole working cell.
    """
    import numpy as np

    h, w = out_shape
    a = arr[: h * k, : w * k].reshape(h, k, w, k)
    if how == "max":
        return np.nanmax(np.where(np.isfinite(a), a, -np.inf), axis=(1, 3)).astype("float32")
    allnan = ~np.isfinite(a).any(axis=(1, 3))
    out = np.nanmin(np.where(np.isfinite(a), a, np.inf), axis=(1, 3)).astype("float32")
    return np.where(allnan, np.nan, out).astype("float32")


def _barrier(cache, crs, transform, shape, res: float, working_shape=None):
    """Water the moose is forced around, on whatever grid it is asked for.

    WATER ONLY. Wetland used to be in here on the assumption that "a moose routes AROUND
    marsh/bog/fen" — my assumption, never measured, and wrong: a moose walks through a
    bog perfectly well. It is just not a FUNNEL, because nothing is forced through it.
    Treating bog as a barrier manufactured necks out of every strip of dry ground between
    two bogs, which is a constriction only on paper. Bog still matters — it damps funnel
    quality further down, because a neck across wet ground is not a preferred travel
    route — but it does not create one.
    """
    import numpy as np

    out = np.zeros(shape, bool)
    # water.tif is a raster on the ANALYSIS grid, so it can only contribute when that is
    # the grid we are on; the vectors below carry the fine grid, and they are the ones
    # that hold real edge detail anyway.
    if working_shape is not None:
        try:
            w = ru.read(cache / "water.tif")[0]
            if w is not None and w.shape == working_shape:
                out |= np.nan_to_num(w) > 0
        except Exception:
            pass
    else:
        try:
            import rasterio
            from rasterio.enums import Resampling
            with rasterio.open(cache / "water.tif") as s:
                w = s.read(1, out_shape=shape, resampling=Resampling.nearest)
            out |= np.nan_to_num(w) > 0
        except Exception:
            pass

    try:
        import geopandas as gpd
        from rasterio.features import rasterize as _rasterize
    except Exception:
        return out

    def _burn(gdf, buffer_m=None):
        nonlocal out
        if gdf is None or not len(gdf):
            return
        try:
            if gdf.crs and crs is not None and gdf.crs.to_epsg() != crs.to_epsg():
                gdf = gdf.to_crs(crs)
            geoms = gdf.geometry if buffer_m is None else gdf.geometry.buffer(buffer_m)
            rr = _rasterize(((g, 1) for g in geoms if g is not None and not g.is_empty),
                            out_shape=shape, transform=transform, fill=0,
                            dtype="uint8", all_touched=True)
            out |= rr > 0
        except Exception as e:  # noqa: BLE001
            print(f"[terrain] barrier layer skipped: {e}")

    # Narrow rivers OSM maps but the 10 m WorldCover water raster misses are real travel
    # barriers too. The buffer is the LINE's real width, not a grid artefact — so it must
    # not shrink with the grid below what a river actually is.
    wl = cache / "waterways.gpkg"
    if wl.exists():
        try:
            gw = gpd.read_file(wl)
            if "waterway" in gw.columns:
                gw = gw[gw["waterway"].isin(["river", "canal"])]
            _burn(gw, max(res, 15.0))
        except Exception as e:  # noqa: BLE001
            print(f"[terrain] waterways skipped: {e}")

    # ...and the OSM LAKE polygons. WorldCover (water.tif) misses lakes in remote areas,
    # so on a lake-rich AOI whose lakes are OSM-only the barrier saw no water at all and
    # the constriction detector found no necks → funnels came back empty ("NO DATA") on
    # exactly the ground richest in land-bridge funnels (user-reported). Same waterbodies
    # the map and the walk-cost barrier use, so all three agree on where the water is.
    wb = cache / "waterbodies.gpkg"
    if wb.exists():
        try:
            _burn(gpd.read_file(wb))
        except Exception as e:  # noqa: BLE001
            print(f"[terrain] waterbodies skipped: {e}")
    return out


# A neck only counts if cutting it separates two REAL pieces of ground. Below
# MIN_SIDE_KM2 the smaller side is a stub — a peninsula tip, a spit, the closed end of a
# bay — and full credit needs FULL_SIDE_KM2 on the smaller side, which is about the
# scale of ground a moose actually shuttles between.
MIN_SIDE_KM2 = 0.5
FULL_SIDE_KM2 = 5.0
LINK_HALO_M = 6000.0        # how far around a neck to look before judging its two sides


def neck_sides(core, passable, res: float, db):
    """Yield (blob_mask, side_a, side_b, second_km2) for every neck in `core`.

    The two sides are full-grid boolean masks of the ground each neck joins, so a later
    stage can ask what is ON them. Sizes are in km2. This is the shared machinery behind
    both halves of the funnel test: `_linkage` here uses only the AREAS (is it a
    bottleneck at all — T10.17), and behavior.py uses the MASKS (do the two sides hold
    anything a moose wants — T10.18).

    THE BUG THIS EXISTS FOR. The constriction detector asks one question — "is this
    ground narrow, pinched between barriers?" — and that question is purely LOCAL. A
    peninsula neck answers yes. So does a spit, an island's tie-bar, and the closed end
    of a bay. Measured across every cached AOI before it was written: 25 of 25 candidates
    on one real box were dead ends. A dead end is not a weak funnel, it is the OPPOSITE
    of one — nothing is forced through a place that leads nowhere.

    The test is the standard connectivity one (Circuitscape calls these pinch points):
    a real bottleneck is where losing a little ground SEVERS A LINKAGE. Cut the neck and
    look at what it separated.

    TWO THINGS THAT LOOK RIGHT AND ARE NOT, both found by measurement:

    1. CUT ACROSS THE NECK, NOT ALONG IT. The medial axis runs ALONG the corridor
       centre, so deleting those cells leaves the flanks connected around the gap and
       severs nothing. The cut radius comes from `db` — the distance transform IS the
       local half-width.
    2. THE SIDES ARE THE PIECES THE NECK TOUCHES, not the biggest pieces nearby. Taking
       the two largest components in the window paired a peninsula stub with an
       unrelated region across a lake. Symptom: widening the halo 6 km -> 25 km moved
       survivors from 9 to 25 on one box and 47 to 66 on another — the verdict was being
       decided by how far we happened to look, which is not a property of the ground.
    """
    import numpy as np
    from scipy import ndimage as ndi

    lab, n = ndi.label(core > 0)
    if n == 0:
        return

    cell_km2 = res * res / 1e6
    halo = max(4, int(round(LINK_HALO_M / res)))
    for i, sl in enumerate(ndi.find_objects(lab), start=1):
        if sl is None:
            continue
        blob_full = lab == i
        rad = int(np.ceil(float(db[blob_full].max()) / res)) + 2
        pad = halo + rad
        y0 = max(0, sl[0].start - pad); y1 = min(core.shape[0], sl[0].stop + pad)
        x0 = max(0, sl[1].start - pad); x1 = min(core.shape[1], sl[1].stop + pad)
        win = passable[y0:y1, x0:x1]
        seed = blob_full[y0:y1, x0:x1]

        cut = ndi.binary_dilation(seed, iterations=rad)
        sublab, sn = ndi.label(win & ~cut)
        if sn < 2:
            continue                     # removing it separates nothing — walk around it

        ring = ndi.binary_dilation(cut, iterations=2) & ~cut & win
        touching = set(np.unique(sublab[ring])) - {0}
        if len(touching) < 2:
            continue                     # only one side — a dead end
        ranked = sorted(((int((sublab == tt).sum()), tt) for tt in touching), reverse=True)
        (na, ta), (nb, tb) = ranked[0], ranked[1]

        def _full(tag):
            m = np.zeros(core.shape, bool)
            m[y0:y1, x0:x1] = sublab == tag
            return m

        yield blob_full, _full(ta), _full(tb), float(nb * cell_km2)


def _linkage(core, passable, res: float, db):
    """0..1 per neck: how much of a LINKAGE it is. See `neck_sides`."""
    import numpy as np

    out = np.zeros(core.shape, "float32")
    for blob, _a, _b, second in neck_sides(core, passable, res, db):
        if second < MIN_SIDE_KM2:
            continue                     # a stub — this is a dead end, not a funnel
        out[blob] = min(1.0, second / FULL_SIDE_KM2)
    return out


def _constriction(barrier, res: float, grid_res: float | None = None):
    """(strength 0..1, neck width in metres) for every pinch in the passable ground.

    `res` is the grid this is MEASURED on; `grid_res` is the analysis grid the detector
    was calibrated against. They differ only when the fine grid is in use, and keeping
    them apart is what stops a resolution change from becoming a model change.
    """
    import numpy as np
    from scipy.ndimage import distance_transform_edt, maximum_filter, uniform_filter

    shape = barrier.shape
    if not barrier.any():
        return np.zeros(shape, "float32"), np.full(shape, np.nan, "float32")

    passable = ~barrier
    # Distance to the nearest barrier. The medial-axis (corridor-centre) value is the
    # corridor HALF-width, so full corridor width = 2*db. The old detector scored
    # absolute half-width up to 700 m — admitting ~1.4 km-wide "funnels" and lighting a
    # uniform isthmus end-to-end. A real funnel is a NECK: narrow in absolute terms AND a
    # local minimum of corridor width (it pinches HERE vs up/downstream).
    db = (distance_transform_edt(passable) * res).astype("float32")
    # BOTH OF THESE ARE IN METRES ON PURPOSE, AND BOTH ARE TIED TO THE ANALYSIS GRID.
    # They used to be `size=3` and `db > res` — "three cells" and "one cell" — which
    # asked a different question at every resolution. Moving the detector to a fine grid
    # (T9.10) would have quietly redefined the medial axis along with it: a 3x3 test at
    # 6.7 m accepts far more cells as corridor-centre than at 40 m, and left alone that
    # inflated total neck area 3.5x for a reason with nothing to do with the terrain.
    #
    # But the fix is NOT a hardcoded metre constant. `grid_res` is the ANALYSIS grid, and
    # 3x it is exactly what `size=3` meant there — so a 40 m box keeps asking its 120 m
    # question and a 20 m box keeps asking its 60 m one, while the fine grid asks that
    # same question with more precision. Hardcoding 120 m looked equivalent and was not:
    # measured on a real 20 m box it doubled the strictness and cut funnels from 7 to 2.
    ridge_m = 3.0 * float(grid_res or res)
    MIN_OFF_BARRIER_M = 20.0
    rw = max(3, int(round(ridge_m / res)) | 1)
    ridge = ((db >= maximum_filter(db, size=rw) - 1e-6) & passable
             & (db > max(res, MIN_OFF_BARRIER_M)))
    full_w = 2.0 * db
    # HOW TIGHT IS TIGHT. This was (300 - w)/300, which scores a 250 m land bridge at
    # 0.17 — under the threshold that polygonizes a funnel at all. A 250 m neck between
    # two lakes is a strong funnel, not a marginal one. Full strength at or below ~250 m,
    # fading out by ~600 m: below 250 m a travelling bull is genuinely pinched; by 600 m
    # he has room to go around, which is the distinction the number is trying to capture.
    NECK_M = 600.0
    FULL_AT = 250.0
    narrow = np.clip((NECK_M - full_w) / (NECK_M - FULL_AT), 0.0, 1.0)
    # Local minimum: compare db to its ~600 m neighbourhood average; where the corridor
    # is markedly narrower than nearby, it is squeezing — that is the pinch.
    db_local = uniform_filter(db, size=max(3, int(round(600 / res)) | 1))
    pinch = np.clip((db_local - db) / (db_local + 1e-6), 0.0, 1.0)
    strength = narrow * (0.35 + 0.65 * pinch)
    constriction = np.where(ridge & (full_w < NECK_M), strength, 0.0).astype("float32")

    # IS IT A LINKAGE, OR A DEAD END? Everything above measures SHAPE — narrow, pinched,
    # a local minimum of corridor width — and a peninsula neck satisfies all of it. This
    # is the test that asks what the neck actually connects, and it runs BEFORE the halo
    # below so the cut measures the real neck rather than its 280 m zone of influence.
    link = _linkage(constriction, passable, res, db)
    n_before = int((constriction > 0).sum())
    constriction = (constriction * link).astype("float32")
    _constriction.last_audit = {
        "candidates": n_before,
        "kept": int((constriction > 0).sum()),
        "passable_frac": round(float(passable.mean()), 4),
    }

    # THICKEN ENOUGH TO SURVIVE THE POLYGONIZER. The medial axis is a 1-px line; 120 m
    # made it ~3 px at 40 m, and _polygonize opens with 3 iterations — which erodes 3 px
    # before dilating and therefore deleted the entire ribbon. Measured: 7,444 cells
    # scored, 7,223 survived smoothing, 0 survived the opening. Every funnel the map ever
    # showed was a broad topo blob, because those were the only shapes fat enough to live
    # through it — which is precisely why they looked wrong on the ground.
    #
    # 280 m is not a fudge to beat the morphology: a neck's zone of influence really is a
    # couple of hundred metres either side of the centreline — that is where you would
    # sit to watch it. It is in METRES, so it survives the change of grid unchanged.
    halo = max(3, int(round(280 / res)) | 1)
    constriction = maximum_filter(constriction, size=halo)
    # PERSIST THE MEASUREMENT, not just the score. "Funnel / pass · 0.1 km²" tells a
    # hunter nothing about whether to believe it; "a 180 m neck" is checkable against the
    # map in front of them. Width is the honest unit for a constriction, and it is the
    # number that makes a bad funnel obviously bad.
    width = np.where(constriction > 0, full_w, np.nan).astype("float32")
    width = maximum_filter(np.nan_to_num(width, nan=0.0), size=halo)
    width = np.where(constriction > 0, width, np.nan).astype("float32")
    return constriction, width


def _prominence_fine(fine_path, out_shape, res: float):
    """Peak topographic position within each analysis cell, measured on the LiDAR grid.

    Returns a working-grid array with NaN where the fine DEM has no data. Signed peak,
    not absolute: a cell that straddles a knob and a gully is a knob for glassing
    purposes, and a pure |.| would call a deep hole a high point.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter, uniform_filter

    fine, fprof = ru.read(fine_path)
    fres = abs(fprof["transform"].a)
    k = int(round(res / fres))
    h, w = out_shape
    if k < 2 or fine.shape[0] < h * k or fine.shape[1] < w * k:
        return None

    ok = np.isfinite(fine)
    if not ok.any():
        return None
    filled = np.where(ok, fine, np.nanmean(fine)).astype("float32")
    filled = gaussian_filter(filled, sigma=1.0)
    win = max(3, int(round(500 / fres)) | 1)
    tpi_f = filled - uniform_filter(filled, size=win)
    tpi_f = np.where(ok, tpi_f, np.nan)

    blk = tpi_f[: h * k, : w * k].reshape(h, k, w, k)
    okb = ok[: h * k, : w * k].reshape(h, k, w, k)
    hi = np.nanmax(np.where(okb, blk, -np.inf), axis=(1, 3))
    lo = np.nanmin(np.where(okb, blk, np.inf), axis=(1, 3))
    peak = np.where(np.abs(hi) >= np.abs(lo), hi, lo)
    return np.where(okb.any(axis=(1, 3)), peak, np.nan).astype("float32")


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

    # --- prominence: the small knobs a 40 m grid cannot hold (T9.10) ---------------
    # `tpi` above is a LANDSCAPE measure — height over a 500 m neighbourhood — and 40 m
    # is a perfectly good grid for that. Glassing asks a different question: is there a
    # rise HERE you can see from. An 80 m knob is two cells at 40 m and the sigma-1
    # smoothing flattens it; at 10 m it is eight cells and survives.
    #
    # Measured on the Rouyn box: the peak |TPI| inside a 40 m cell is 1.52x larger when
    # measured at 10 m, and ground with |TPI| > 6 m goes 62 -> 82 km2. That is what the
    # LiDAR buys — swapping the SOURCE alone under a fixed 40 m grid moved mean |TPI| by
    # 1.4%, which is nothing. Written as its own layer rather than overwriting tpi.tif,
    # because tpi.tif also drives `wet` and the habitat surface, and a peak statistic is
    # the wrong input for those — a wetness proxy wants the cell's typical position, not
    # its highest corner.
    prominence = None
    fine_path = cache_dir(aoi) / "dem_fine.tif"
    if fine_path.exists():
        try:
            prominence = _prominence_fine(fine_path, dem.shape, res)
        except Exception as e:  # noqa: BLE001 — the coarse tpi is always there to fall back on
            print(f"[terrain] fine prominence skipped: {e}")
    if prominence is None:
        prominence = tpi.copy()
    else:
        # Voids in the LiDAR: no fine measurement, so use the coarse one rather than a
        # hole. A NaN here would silently delete glassing points over unflown ground.
        prominence = np.where(np.isfinite(prominence), prominence, tpi)

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
    # ...AND IT IS MEASURED ON A FINER GRID THAN THE ANALYSIS RUNS ON (T9.10).
    # A neck is a WIDTH, and the 40 m analysis grid was destroying the widths that
    # matter most. Two lakes 100 m apart are 2.5 cells apart; each is rasterized with
    # `all_touched` (which we must, or thin water vanishes entirely), so each grows by
    # up to a cell and the neck arrives as 0-1 cells — a wild width, or no neck at all.
    # Every funnel under ~150 m was being erased or mis-measured, and those are the good
    # ones: 250 m is where `narrow` already scores full strength.
    #
    # The barrier is built from the water VECTORS, so this sharpens every box whether or
    # not LiDAR covers it. On a fine grid the same 100 m neck is 10 cells and loses ~20 m
    # to the same dilation instead of ~80 m.
    f_res = _fine_res(res, dem.shape)
    f_tr, f_shape = _grid_at(prof["transform"], dem.shape, res, f_res)
    barrier_f = _barrier(cache_dir(aoi), prof["crs"], f_tr, f_shape, f_res,
                         dem.shape if f_res == res else None)
    constriction_f, width_f = _constriction(barrier_f, f_res, grid_res=res)
    print(f"[terrain] necks measured at {f_res:.1f} m "
          f"({'analysis grid' if f_res == res else f'{res / f_res:.0f}x the analysis grid'})")

    # Back onto the analysis grid. Score by MAX and width by MIN, both deliberately:
    # a 40 m cell containing a neck IS neck ground, and the tightest measurement inside
    # it is the honest one to report. Averaging would dilute exactly the narrow necks
    # this whole change exists to recover.
    if f_res != res:
        k = int(round(res / f_res))
        constriction = _block_reduce(constriction_f, k, "max", dem.shape)
        funnel_w = _block_reduce(width_f, k, "min", dem.shape)
        barrier = _block_reduce(barrier_f.astype("float32"), k, "max", dem.shape) > 0.5
    else:
        constriction, funnel_w, barrier = constriction_f, width_f, barrier_f

    if barrier.any():
        ru.write(cache_dir(aoi) / "funnel_width.tif", funnel_w.astype("float32"), prof)
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
            # Carry the LINKAGE audit too, so "no funnels" can explain itself. An empty
            # layer with no reason reads as broken; "the ground here is 91% continuous,
            # so nothing is forced anywhere" is a finding a hunter can use.
            _audit = getattr(_constriction, "last_audit", {}) or {}
            (cache_dir(aoi) / "funnel_barrier.json").write_text(json.dumps({
                "barrier_frac": round(float(barrier.mean()), 4),
                "wetland_frac": round(float(_wet.mean()), 4),
                "grhq_present": (cache_dir(aoi) / "wetland_grhq.tif").exists(),
                "neck_candidates": _audit.get("candidates"),
                "necks_kept": _audit.get("kept"),
                "passable_frac": _audit.get("passable_frac")}))
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
        ("prominence", prominence),
        ("wet", wet), ("funnel", funnel), ("coolaspect", cool),
    ]:
        a = arr.copy()
        a[~mask] = np.nan
        ru.write(tdir / f"{name}.tif", a, prof)
