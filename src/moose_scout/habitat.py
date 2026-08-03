"""Stage 3 — Moose Habitat Suitability Model (HSM).

Weighted overlay on the canonical grid. North of the écoforestière limit the
vegetation signal comes from Sentinel-2 NDVI (browse/cover proxy) rather than
stand polygons. Robust to missing layers — uses what acquisition produced.

Outputs (cache/<aoi>/):
  hsm.tif             0..1 suitability
  hsm_thermal.tif     thermal-refuge score ("climatiseur à orignaux")
  hsm_rut.tif         rut/calling-site score (edge × funnel × wetland)
  dist_water.tif      metres to nearest water (for extraction + reporting)
"""
from __future__ import annotations

import numpy as np

from .config import Context, cache_dir
from . import rasterio_utils as ru


def _opt(path):
    try:
        return ru.read(path)[0]
    except Exception:
        return None


def _dist(mask_bool, res):
    from scipy.ndimage import distance_transform_edt

    if mask_bool.any():
        return distance_transform_edt(~mask_bool) * res
    return np.full(mask_bool.shape, 1e6, dtype="float32")


def _prox(dist, optimal_m, falloff_m):
    """1.0 within optimal, decaying to 0 by optimal+falloff."""
    out = np.ones_like(dist, dtype="float32")
    far = dist > optimal_m
    out[far] = np.clip(1 - (dist[far] - optimal_m) / max(falloff_m, 1), 0, 1)
    return out


def run(ctx: Context) -> None:
    from scipy.ndimage import generic_filter, uniform_filter

    aoi = ctx.aoi.name
    cache = cache_dir(aoi)
    tdir = cache / "terrain"
    res = ctx.model.raster_resolution_m
    sp = ctx.species
    W = sp.water or {}

    _, prof = ru.read(tdir / "slope.tif")
    slope = _opt(tdir / "slope.tif")
    tpi = _opt(tdir / "tpi.tif")
    wet = _opt(tdir / "wet.tif")
    funnel = _opt(tdir / "funnel.tif")
    cool = _opt(tdir / "coolaspect.tif")
    ndvi = _opt(cache / "ndvi.tif")
    water = _opt(cache / "water.tif")
    wetland = _opt(cache / "wetland.tif")
    shape = slope.shape

    # --- water: prefer OSM raster; fall back to very-low NDVI as water ---
    if water is not None:
        water_mask = water > 0
    elif ndvi is not None:
        water_mask = ndvi < 0.0
    else:
        water_mask = np.zeros(shape, bool)
    wetland_mask = (wetland > 0) if wetland is not None else np.zeros(shape, bool)

    dist_water = _dist(water_mask | wetland_mask, res)
    ru.write(cache / "dist_water.tif", dist_water.astype("float32"), prof)

    # --- browse / cover / edge from WorldCover classes, refined by NDVI ---
    #   browse: shrub/grass/wetland/regen high, conifer low
    #   cover:  mature tree high
    #   edge:   tree <-> opening interface (moose feed at the seam)
    lc = _opt(cache / "landcover.tif")
    BROWSE_LC = {20: 1.0, 30: 0.7, 90: 0.6, 100: 0.3, 40: 0.5, 10: 0.2, 60: 0.05, 80: 0.0}
    COVER_LC = {10: 0.9, 20: 0.35, 90: 0.15}
    edge = np.full(shape, 0.3, dtype="float32")
    if lc is not None:
        browse_lc = np.zeros(shape, "float32")
        cover_lc = np.zeros(shape, "float32")
        for k, v in BROWSE_LC.items():
            browse_lc[lc == k] = v
        for k, v in COVER_LC.items():
            cover_lc[lc == k] = v
        tree = (lc == 10).astype("float32")
        p = uniform_filter(tree, size=max(3, int(round(200 / res)) | 1))
        edge = ru.normalize(4 * p * (1 - p))              # peaks at 50/50 tree:open
    else:
        browse_lc = cover_lc = None

    if ndvi is not None:
        n = np.clip(ndvi, -0.2, 0.9)
        browse_n = np.clip((n - 0.15) / 0.5, 0, 1) * np.clip(1 - (n - 0.8) / 0.15, 0, 1)
        cover_n = np.clip((n - 0.5) / 0.4, 0, 1)
    else:
        browse_n = cover_n = None

    if browse_lc is not None and browse_n is not None:
        browse = 0.6 * browse_lc + 0.4 * browse_n
        cover = 0.6 * cover_lc + 0.4 * cover_n
    elif browse_lc is not None:
        browse, cover = browse_lc, cover_lc
    elif browse_n is not None:
        browse, cover = browse_n, cover_n
        edge = ru.normalize(uniform_filter((n - uniform_filter(n, 5)) ** 2, 5))
    else:
        browse = wet.copy()
        cover = np.full(shape, 0.4, dtype="float32")

    # --- water/forage proximity ---
    water_score = _prox(dist_water, W.get("wetland_optimal_m", 150), W.get("wetland_falloff_m", 800))

    # --- terrain: valley bottoms, wet flats, gentle ground ---
    terr = ru.normalize(-tpi) * 0.5 + ru.normalize(wet) * 0.3 \
        + ru.normalize(slope, invert=True) * 0.2
    steep = slope > sp.terrain.get("avoid_steep_slope_deg", 25)

    wts = sp.hsm_weights
    hsm = (wts.get("browse", .35) * np.nan_to_num(browse)
           + wts.get("cover", .2) * np.nan_to_num(cover)
           + wts.get("water", .25) * np.nan_to_num(water_score)
           + wts.get("terrain", .1) * np.nan_to_num(terr)
           + wts.get("edge_density", .1) * np.nan_to_num(edge))
    hsm = ru.normalize(hsm)
    hsm[water_mask] = np.nan          # can't hunt open water
    hsm[steep] = hsm[steep] * 0.3     # heavily discount steep ground
    ru.write(cache / "hsm.tif", hsm.astype("float32"), prof)

    # Persist the sub-scores so the behavioral stage (behavior.py) can build
    # time/temperature occupancy surfaces without recomputing the veg model.
    for nm, arr in (("browse", browse), ("cover", cover), ("edge", edge)):
        a = ru.normalize(np.nan_to_num(arr))
        a[water_mask] = np.nan
        ru.write(cache / f"{nm}.tif", a.astype("float32"), prof)

    # --- thermal refuge: cool aspect + cover + near water ---
    thermal = np.nan_to_num(cool) * np.nan_to_num(cover) * _prox(dist_water, 100, 400)
    thermal[water_mask] = np.nan
    ru.write(cache / "hsm_thermal.tif", ru.normalize(thermal).astype("float32"), prof)

    # --- rut/calling sites: cover<->opening edge × funnel × near wetland ---
    wet_prox = _prox(_dist(wetland_mask | water_mask, res), 200, 1000)
    rut = np.nan_to_num(edge) * (0.5 + 0.5 * ru.normalize(funnel)) * wet_prox
    rut[water_mask] = np.nan
    ru.write(cache / "hsm_rut.tif", ru.normalize(rut).astype("float32"), prof)
