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

import json
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


def _cost_dist_from_roads(roads_mask, barrier_mask, res, friction=None):
    """Cost-distance (metres) from road cells, treating barrier cells as impassable — so
    a river between you and the ground makes it 'far' on foot. With `friction` (a per-cell
    multiplier ≥1) this becomes an EFFORT distance: steep or thick ground is 'farther' to
    haul a quartered bull across than the same metres of flat cutline. friction=None gives
    the plain metric distance (for honest 'km to road' reporting)."""
    try:
        from skimage.graph import MCP_Geometric
    except Exception:
        return None
    starts = list(zip(*np.where(roads_mask)))
    if not starts:
        return None
    if friction is not None:
        cost = np.asarray(friction, dtype=np.float64).copy()
        cost[~np.isfinite(cost) | (cost < 1.0)] = 1.0
    else:
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


def _blocked_tenure_mask(ctx, prof, shape):
    """Rasterize the tenure polygons this hunter may NOT hunt (pourvoiries à droits
    exclusifs for a DIY resident, etc.).

    The legal gate is meant to be filter #1 — the design has always said so — but it
    only ever produced TEXT. Nothing masked the rasters, so the model would happily
    rank a focus area inside an exclusive outfitter concession where hunting it would
    be trespass. Returns (mask, [names]) or (None, []) when tenure data is absent.
    """
    import numpy as np
    try:
        from rasterio.features import rasterize
        from . import legal as lg
        patches = lg.classify_tenure(ctx)
        if not patches:
            return None, []
        north = ctx.aoi.center.lat >= lg.PARALLEL_52
        res_ = ctx.aoi.hunter.residency
        blocked, names = [], []
        for p in patches:
            if p.geometry is None:
                continue
            if lg._access_for(res_, p.tenure, north) in ("no", "outfitter"):
                blocked.append(p.geometry)
                names.append(f"{p.tenure.value}: {p.name}")
        if not blocked:
            return None, []
        arr = rasterize(((g, 1) for g in blocked), out_shape=shape,
                        transform=prof["transform"], fill=0, dtype="uint8",
                        all_touched=True)
        return arr.astype(bool), names
    except Exception:
        return None, []


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


# How strongly each class of lease implies somebody is hunting that ground. An abri
# sommaire in the forest exists TO hunt and trap from; a lakeside cottage is mostly a
# summer thing and its occupant may never carry a rifle. These are the honest ordering,
# not measured coefficients — model.yaml can override any of them.
_LEASE_WEIGHT = {
    "abri_sommaire": 1.00,
    "pourvoirie_camp": 0.90,
    "villegiature": 0.55,
    "residence": 0.45,
}


def _lease_pressure(ctx, cache, prof, shape):
    """0..1 pressure around leased shelters (cache/<aoi>/baux.geojson), or None.

    None means "we have no lease data" and leaves `pressure` exactly as the road term
    left it — the same distinction access_unknown draws for roads. An empty file is NOT
    None: "no cabins in this box" is a real answer and deserves the zero it gets.
    """
    import json

    src = cache / "baux.geojson"
    if not src.exists():
        return None
    try:
        fc = json.loads(src.read_text())
        feats = fc.get("features") or []
    except Exception as e:  # noqa: BLE001
        print(f"[access] baux.geojson unreadable, no lease pressure: {e}")
        return None

    mcfg = getattr(ctx, "model", None)
    pcfg = (getattr(mcfg, "pressure", None) or {}) if mcfg else {}
    decay = float(pcfg.get("camp_decay_m", 1200) or 1200)
    weights = dict(_LEASE_WEIGHT)
    weights.update({str(k): float(v) for k, v in (pcfg.get("camp_weight") or {}).items()})

    out = np.zeros(shape, dtype="float32")
    if not feats:
        return out

    from scipy.ndimage import distance_transform_edt

    # One distance transform PER CLASS, so a strong signal never gets diluted by a weak
    # one nearby: the nearest cabin is what matters, and which KIND of cabin it is.
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", prof["crs"], always_xy=True)
    inv = ~prof["transform"]
    res = abs(prof["transform"].a)
    by_kind: dict[str, np.ndarray] = {}
    for f in feats:
        kind = (f.get("properties") or {}).get("kind") or "villegiature"
        try:
            lon, lat = f["geometry"]["coordinates"][:2]
            x, y = tr.transform(float(lon), float(lat))
            c, r = inv * (x, y)
            ci, ri = int(c), int(r)
        except Exception:
            continue
        if not (0 <= ri < shape[0] and 0 <= ci < shape[1]):
            continue
        seeds = by_kind.setdefault(kind, np.ones(shape, dtype=bool))
        seeds[ri, ci] = False          # False = seed, for distance_transform_edt

    for kind, seeds in by_kind.items():
        w = float(weights.get(kind, 0.5))
        if w <= 0 or seeds.all():
            continue
        d = distance_transform_edt(seeds, sampling=(res, res)).astype("float32")
        out = np.maximum(out, (w * np.exp(-d / decay)).astype("float32"))
    return np.clip(out, 0.0, 1.0).astype("float32")


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

    # Loaded-pack-out friction (audit #60): a 400–600 lb quartered bull is hauled at
    # <1 mph, so steep ground and thick cover cost far more than the same metres of open
    # flat. Build a per-cell multiplier from slope + land-cover; the EFFORT cost-distance
    # below rides on it, while the reported dist_road stays TRUE metres (honest km).
    _slope = _opt(cache / "terrain" / "slope.tif")
    _lc = _opt(cache / "landcover.tif")
    friction = np.ones(hsm.shape, dtype="float32")
    if _slope is not None:
        friction = friction + np.clip(np.nan_to_num(_slope), 0, 60) / 6.0   # loaded: steep bites
    if _lc is not None:
        friction = friction + np.where(_lc == 90, 3.0, 0.0)   # herbaceous wetland slog
        friction = friction + np.where(_lc == 10, 0.5, 0.0)   # closed forest / blowdown

    # --- distance to road: river-aware on foot (no boat), straight-line with a boat ---
    dist_effort = None
    if has_roads:
        if wc == "none":
            barrier = _river_barrier(cache, prof, hsm.shape)
            # LAKES are foot barriers too — you can't walk across open water without a
            # boat. _river_barrier only rasterizes river/canal LINES, so the cost-distance
            # "walked across" a lake to an island, making the island score huntable and
            # win a focus area. Add the WorldCover water mask (lakes + wide rivers).
            _wmask = _opt(cache / "water.tif")
            if _wmask is not None and _wmask.shape == hsm.shape:
                barrier = barrier | (np.nan_to_num(_wmask) > 0)
            dist_road = _cost_dist_from_roads(roads > 0, barrier, res)              # TRUE metres
            dist_effort = _cost_dist_from_roads(roads > 0, barrier, res, friction)  # pack-out effort
            if dist_road is None:                       # skimage missing / failed → fall back
                dist_road = _dist(roads > 0, res)
        else:
            dist_road = _dist(roads > 0, res)           # boat can cross rivers
    else:
        dist_road = np.full(hsm.shape, 1e6, dtype="float32")   # no roads → truck N/A
    ru.write(cache / "dist_road.tif", dist_road.astype("float32"), prof)

    # --- reachability = HOW FAR YOU SAID YOU'LL WALK, not a magic decay -------------
    # The old exp(-dist/2500) faded reachability on an arbitrary constant unrelated to the
    # hunter's own budget — so ground the hunter would happily walk to scored as "far",
    # and (via the huntability product) the map collapsed to a road corridor. Instead:
    # ground within your stated foot budget (access-walk + hunt-walk) of a road is
    # reachable; a soft tail lets you push ~60% past it. The EFFORT distance is used, so
    # steep or thick ground shrinks how far that budget actually carries you.
    walk_km = (float(getattr(hunter, "walk_access_km", 2.0) or 0.0)
               + float(getattr(hunter, "walk_hunt_km", 4.0) or 0.0))
    walk_m = max(1000.0, walk_km * 1000.0)
    reach_d = dist_effort if dist_effort is not None else dist_road
    truck = np.clip(1.0 - (reach_d - walk_m) / (0.6 * walk_m), 0.0, 1.0)
    if wc == "none":
        extraction = truck.astype("float32")            # no boat → foot access only
    else:
        # a boat extends access along water: reachable within a paddle + a short carry
        paddle_m = walk_m * (3.0 if wc == "motor" else 2.0)
        canoe = np.clip(1.0 - (dist_water - paddle_m) / (0.6 * paddle_m), 0.0, 1.0)
        extraction = np.maximum(truck, canoe).astype("float32")

    # ACCESS UNKNOWN ≠ ACCESS IMPOSSIBLE. If no road network was acquired (a big box can
    # blow the Overpass budget), dist_road is 1e6 and exp(-1e6/2500) underflows to 0 —
    # which, with no watercraft, zeroes huntability across the ENTIRE AOI and returns an
    # empty map. That is the model asserting "nothing here is reachable" on the basis of
    # having no data at all, which is exactly backwards. Fall back to a neutral,
    # explicitly-flagged value and let the contract tell the user access wasn't modelled.
    access_unknown = not has_roads
    if access_unknown:
        extraction = np.full(hsm.shape, 0.85, dtype="float32")
    ru.write(cache / "extraction.tif", extraction, prof)
    try:
        (cache / "access_unknown.flag").write_text("1" if access_unknown else "0")
    except Exception:
        pass

    pressure = np.exp(-dist_road / road_decay).astype("float32")
    if access_unknown:
        pressure = np.zeros(hsm.shape, dtype="float32")   # unknown roads → don't invent pressure
    # LEASED SHELTERS (T9.8). A road is where hunters can GET to; an abri sommaire is
    # where one of them already IS, every season. Roads alone miss the camp you can only
    # reach by water or quad, and they miss the difference between a road nobody uses and
    # a road with nine cabins on it.
    #
    # Deliberately additive and deliberately NOT a barrier: this never touches the legal
    # gate or huntability. The ground around somebody's cabin is still crown land and
    # still yours to hunt — it is just less likely to be quiet.
    #
    # It also survives `access_unknown`. When the road network failed to acquire we
    # refuse to invent road pressure, but a lease we DID acquire is direct evidence
    # regardless of whether we mapped the road to it.
    lease = _lease_pressure(ctx, cache, prof, hsm.shape)
    if lease is not None:
        # Two independent reasons to expect company — combine as probabilities, not by
        # max: a cabin ON a road is more pressured than either fact alone implies.
        pressure = (1.0 - (1.0 - pressure) * (1.0 - lease)).astype("float32")
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

    # These surfaces are already on a real 0..1 scale — clip, don't re-rank. Every
    # extra percentile stretch turns an absolute score back into a within-AOI rank.
    def _n(a):
        return np.clip(np.nan_to_num(a), 0, 1) if a is not None else None

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
        hsm_phase = np.clip(0.4 * base + 0.6 * phase_sig, 0, 1)
    else:                                               # missing sub-scores → base only
        hsm_phase = np.clip(base, 0, 1)
    ru.write(cache / "habitat_phase.tif", hsm_phase.astype("float32"), prof)

    # TWO AXES, reported separately as well as combined. A hunter needs to see
    # "A+ habitat, 11 km pack-out" — not one number in which a 4-decade exponential
    # decay from the road has silently eaten the habitat signal.
    retrieval = np.clip(extraction * (1 - pw * pressure), 0, 1).astype("float32")
    ru.write(cache / "retrieval.tif", retrieval, prof)

    # Access DISCOUNTS habitat, it does not ERASE it. Multiplying straight by retrieval
    # let a 4-decade exponential decay from the road (and, with no boat, the river-barrier
    # foot-reachability) zero out huge regions — so the huntability surface collapsed to
    # the road-connected band and the rest of the AOI simply wasn't drawn ("the engine
    # isn't evaluating the whole area"). It also made the map hostage to how complete the
    # road fetch happened to be. Floor the access term: unreachable good habitat still
    # shows (as lower tiers, with the pack-out cost stated), reachable ground is brightest.
    ACCESS_FLOOR = 0.35
    # The floor DISCOUNTS habitat you can reach but must work for; it does NOT rescue
    # ground you cannot reach at all — across open water with no boat, or beyond your walk
    # budget. That stays ~0 so it neither draws nor wins a focus area (e.g. an island in a
    # lake). With a boat, islands ARE reachable, so retrieval there is > 0 and they show.
    # Soft ramp, not a hard reachable/unreachable step: a `retrieval > 0.02` cliff drew a
    # ~0.36·hsm contour RING at the edge of the walk budget that read as a real landscape
    # feature (audit #49). Fade the floor in over retrieval 0→0.05 so cut-off ground still
    # goes cleanly to 0 (no island / beyond-budget focus areas) without a hard edge.
    gate = np.clip(retrieval / 0.05, 0.0, 1.0)
    access_term = (gate * (ACCESS_FLOOR + (1.0 - ACCESS_FLOOR) * retrieval)).astype("float32")
    hunt = np.clip(hsm_phase * access_term, 0, 1)
    hunt[np.isnan(hsm)] = np.nan

    # LEGAL GATE — filter #1, and it must bite on the raster, not just the prose.
    # Ground you may not legally hunt is not "low-scoring", it is out of play, so it
    # is masked to NaN before focus areas are extracted.
    blocked, bnames = _blocked_tenure_mask(ctx, prof, hunt.shape)
    if blocked is not None and blocked.any():
        hunt[blocked] = np.nan
        try:
            (cache / "blocked_tenure.json").write_text(json.dumps(
                {"pct_of_aoi": round(float(blocked.mean()) * 100, 1), "names": bnames[:12]}))
        except Exception:
            pass
    ru.write(cache / "huntability.tif", hunt.astype("float32"), prof)
