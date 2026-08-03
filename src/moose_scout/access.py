"""Stage 4 — access, extraction & (phase-weighted) huntability.

Combines habitat with realistic retrieval, hunter pressure, AND the hunter's own
Setup constraints (watercraft, how far they'll walk, and their hunt dates), so the
map actually reflects what THIS hunter can reach and hunt:

  dist_road.tif      metres to nearest drivable road. With **no watercraft** this is
                     a river-aware COST distance — real rivers are foot barriers, so
                     ground across a river from the road reads as far/unreachable
                     (you can't wade a river with a moose on your back). With a
                     boat it's straight-line (you can cross).
  extraction.tif     0..1 ease of getting a 400–600 lb animal out. Water (canoe/
                     motor) counts ONLY if the hunter has that craft.
  pressure.tif       0..1 hunter pressure (rises near roads/access).
  huntability.tif    hsm_phase × extraction × (1 − pressure_weight × pressure), where
                     hsm_phase re-weights the habitat by the RUT PHASE of the hunt
                     dates: at peak rut it leans on calling/travel terrain (funnels,
                     cruise corridors); off-peak it leans on feeding & thermal refuge.
"""
from __future__ import annotations

from datetime import date

import numpy as np

from .config import Context, cache_dir
from . import rasterio_utils as ru


def _dist(mask_bool, res):
    from scipy.ndimage import distance_transform_edt

    if mask_bool.any():
        return distance_transform_edt(~mask_bool) * res
    return np.full(mask_bool.shape, 1e6, dtype="float32")


def _river_barrier(cache, prof, shape):
    """Rasterize river/canal-class waterways as a foot-barrier mask (small streams
    are fordable, so they're NOT barriers). Empty mask if no vector water."""
    p = cache / "waterways.gpkg"
    if not p.exists():
        return np.zeros(shape, dtype=bool)
    try:
        import geopandas as gpd
        from rasterio.features import rasterize

        g = gpd.read_file(p)
        if "waterway" in g.columns:
            g = g[g["waterway"].isin(["river", "canal"])]      # streams are fordable
        if g.crs and prof.get("crs") and g.crs != prof["crs"]:
            g = g.to_crs(prof["crs"])
        geoms = [geom for geom in g.geometry if geom is not None and not geom.is_empty]
        if not geoms:
            return np.zeros(shape, dtype=bool)
        arr = rasterize(((geom, 1) for geom in geoms), out_shape=shape,
                        transform=prof["transform"], fill=0, default_value=1,
                        dtype="uint8", all_touched=True)
        return arr.astype(bool)
    except Exception:
        return np.zeros(shape, dtype=bool)


def _cost_dist_from_roads(roads_mask, barrier_mask, res):
    """Geodesic distance (metres) from road cells, treating barrier cells as
    impassable — so a river between you and the ground makes it 'far' on foot."""
    try:
        from skimage.graph import MCP_Geometric
    except Exception:
        return None
    starts = list(zip(*np.where(roads_mask)))
    if not starts:
        return None
    cost = np.ones(roads_mask.shape, dtype=np.float64)
    cost[barrier_mask] = np.inf                     # rivers = impassable on foot
    cost[roads_mask] = 1.0
    try:
        costs, _ = MCP_Geometric(cost).find_costs(starts)
    except Exception:
        return None
    d = (costs * res).astype("float32")
    d[~np.isfinite(d)] = 1e6                         # cut off by a river = unreachable
    return d


def _rut_emphasis(ctx) -> tuple:
    """(breeding, seeking) in 0..1 for the hunt dates.

    Two DIFFERENT quantities, deliberately:
      • breeding — how much of the breeding peak the dates cover. Drives the habitat
        blend toward COW habitat, because at peak rut the sexes aggregate, mature
        bulls have stopped feeding (~18–20 Sep) and the bull is where the cows are.
      • seeking  — how much the dates fall in the pre-peak searching phase, when
        bulls are travelling and callable. Drives weighting toward bull search
        corridors (cruise / funnels).
    Averaged across the hunt dates rather than max()'d, so one good day doesn't
    re-weight the entire map.
    """
    try:
        from . import rut_timing
        ph = rut_timing.phases(ctx)
        b, s = [], []
        for ds in ctx.aoi.season.target_dates:
            try:
                d = date.fromisoformat(ds)
            except Exception:
                continue
            bi = rut_timing.breeding_intensity(d, ph)
            b.append(bi)
            # seeking = callable-and-travelling but not yet tending
            s.append(max(0.0, rut_timing.responsiveness(d, ph) - bi))
        if not b:
            return 0.5, 0.25
        return float(sum(b) / len(b)), float(sum(s) / len(s))
    except Exception:
        return 0.5, 0.25


def _opt(path):
    try:
        return ru.read(path)[0]
    except Exception:
        return None


def run(ctx: Context) -> None:
    cache = cache_dir(ctx.aoi.name)
    res = ctx.model.raster_resolution_m
    mcfg = ctx.model
    hunter = ctx.aoi.hunter
    wc = getattr(hunter, "watercraft", "none")
    decay = float((mcfg.extraction or {}).get("decay", 2500))
    pw = float((mcfg.pressure or {}).get("weight_in_ranking", 0.25))
    road_decay = float((mcfg.pressure or {}).get("road_decay_m", 1500))

    hsm, prof = ru.read(cache / "hsm.tif")
    dist_water = ru.read(cache / "dist_water.tif")[0]

    roads = None
    try:
        roads = ru.read(cache / "roads.tif")[0]
    except Exception:
        pass
    has_roads = roads is not None and (roads > 0).any()

    # --- distance to road: river-aware on foot (no boat), straight-line with a boat ---
    if has_roads:
        if wc == "none":
            barrier = _river_barrier(cache, prof, hsm.shape)
            dist_road = _cost_dist_from_roads(roads > 0, barrier, res)
            if dist_road is None:                       # skimage missing / failed → fall back
                dist_road = _dist(roads > 0, res)
        else:
            dist_road = _dist(roads > 0, res)           # boat can cross rivers
    else:
        dist_road = np.full(hsm.shape, 1e6, dtype="float32")   # no roads → truck N/A
    ru.write(cache / "dist_road.tif", dist_road.astype("float32"), prof)

    # --- extraction ease: truck always; water ONLY if the hunter has the craft ---
    truck = np.exp(-dist_road / decay)
    if wc == "none":
        extraction = truck.astype("float32")            # no boat → no water access at all
    else:
        water_decay = decay * (1.8 if wc == "motor" else 1.2)   # a motor reaches further
        canoe = np.exp(-dist_water / water_decay)
        extraction = np.maximum(truck, canoe).astype("float32")
    ru.write(cache / "extraction.tif", extraction, prof)

    pressure = np.exp(-dist_road / road_decay).astype("float32")
    ru.write(cache / "pressure.tif", pressure, prof)

    # --- phase-weighted habitat: let the HUNT DATES steer what "good" means -------
    # breeding → hunt COW habitat (bull is with the cows, and has stopped feeding)
    # seeking  → hunt BULL search corridors (cruise/funnels) — the callable phase
    # neither  → hunt feeding + thermal refuge
    r_breed, r_seek = _rut_emphasis(ctx)
    base = np.nan_to_num(hsm)
    hsm_rut = _opt(cache / "hsm_rut.tif")
    cow = _opt(cache / "hsm_cow.tif")
    bull = _opt(cache / "hsm_bull.tif")
    cruise = _opt(cache / "behavior" / "cruise.tif")
    feed = _opt(cache / "behavior" / "feed.tif")
    refuge = _opt(cache / "behavior" / "refuge.tif")
    if refuge is None:
        refuge = _opt(cache / "hsm_thermal.tif")
    if feed is None:
        feed = _opt(cache / "browse.tif")

    def _n(a):
        return np.nan_to_num(ru.normalize(a)) if a is not None else None

    # bull travel corridors (seeking phase)
    seek_term = None
    for c in (_n(cruise), _n(hsm_rut)):
        seek_term = c if seek_term is None else np.maximum(seek_term, c)
    # cow habitat (breeding phase) — fall back to feed+cover if the surface is absent
    cow_term = _n(cow)
    # ordinary feeding/refuge (outside the rut)
    forage_term = _n(bull)
    if forage_term is None:
        forage_term = _n(feed)
    food_parts = [p for p in (forage_term, _n(refuge)) if p is not None]
    food_term = None
    if food_parts:
        food_term = food_parts[0] if len(food_parts) == 1 else \
            0.6 * food_parts[0] + 0.4 * food_parts[1]
    if cow_term is None:
        cow_term = food_term

    parts, wts = [], []
    if cow_term is not None:
        parts.append(cow_term); wts.append(r_breed)
    if seek_term is not None:
        parts.append(seek_term); wts.append(r_seek)
    if food_term is not None:
        parts.append(food_term); wts.append(max(0.0, 1.0 - r_breed - r_seek))
    tot = sum(wts)
    if parts and tot > 0:
        phase_sig = sum(w * p for w, p in zip(wts, parts)) / tot
        hsm_phase = ru.normalize(0.4 * base + 0.6 * phase_sig)
    else:                                               # missing sub-scores → base only
        hsm_phase = ru.normalize(base)

    hunt = hsm_phase * extraction * (1 - pw * pressure)
    hunt = ru.normalize(hunt)
    hunt[np.isnan(hsm)] = np.nan
    ru.write(cache / "huntability.tif", hunt.astype("float32"), prof)
