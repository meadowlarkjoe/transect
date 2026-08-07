"""Stage 3.5 — behavioral time/temperature occupancy surfaces.

This is the moose engine's core: it turns the *static* habitat sub-scores into
*where a bull actually is* as a function of time of day and temperature, so the
brief and app can say "here at first light, there by 1 p.m. if it's warm" rather
than showing one flat suitability map.

The biology (encoded in config/species/<sp>.yaml, cited there):
  • Moose are crepuscular. At first/last light they FEED on browse edges — young
    regen/cutblock/riparian willow — and in water (aquatic feeding is a sodium
    magnet; ponds yield ~4× terrestrial forage). Rut bulls specifically select
    forage-rich regen/cuts.
  • Moose are heat-sensitive. Above ~14 °C activity drops and they seek shade;
    by ~17 °C bedded heat-stress sets in, ~20 °C strong cover selection, ~25 °C
    body-temp rise/panting. So as midday warms they pull into cool conifer /
    north-aspect THERMAL REFUGE near water and hold there.
  • In the rut, bulls CRUISE — working cover↔opening edges and terrain funnels
    between bedding cover and feeding/wallow complexes, checking for cows.
  • Thermals steer travel and, more importantly, scent: morning air drains
    downslope then reverses upslope as the ground heats (and back downslope in
    the evening). That's captured as an approach note per period, plus a light
    slope-position bias, not a fabricated location shift.

Outputs on the working grid (cache/<aoi>/behavior/):
  feed.tif         dawn/dusk feeding surface (browse edge × aquatic sodium)
  refuge.tif       midday thermal refuge (cool conifer near water)
  cruise.tif       rut travel corridors (edge × funnel between cover & food)
  midday_cool.tif  midday occupancy when it's cool  (still feeding/loafing)
  midday_warm.tif  midday occupancy when it's hot   (refuge-dominant)
And behavior/periods.json — the per-period narrative + heat thresholds + the
grid→period mapping, consumed by export (SCOUT_DATA.BEHAVIOR) and the brief.

Robust to missing layers, exactly like habitat.py — it uses whatever acquisition
and the habitat stage produced.
"""
from __future__ import annotations

import json

import numpy as np

from .config import Context, cache_dir
from . import rasterio_utils as ru


def _opt(path):
    try:
        return ru.read(path)[0]
    except Exception:
        return None


def _prox(dist, optimal_m, falloff_m):
    """1.0 within optimal, decaying linearly to 0 by optimal+falloff."""
    if dist is None:
        return None
    out = np.ones_like(dist, dtype="float32")
    far = dist > optimal_m
    out[far] = np.clip(1 - (dist[far] - optimal_m) / max(falloff_m, 1), 0, 1)
    return out


def refuge_weight(t_max_c, heat) -> float:
    """Fraction [0,1] of midday spent in thermal refuge vs still feeding, as a
    ramp from heat_onset (shade-seeking begins) to heat_severe (strong cover
    selection). Below onset → ~0 (moose stay out feeding/loafing); at/above
    severe → 1 (holed up in cover). This is the single knob that makes midday
    temperature-dependent."""
    onset = float(heat.get("heat_onset_c", 14))
    severe = float(heat.get("heat_severe_c", 20))
    if t_max_c is None:
        return 0.5  # unknown → split the difference
    if severe <= onset:
        severe = onset + 1.0
    return float(np.clip((float(t_max_c) - onset) / (severe - onset), 0.0, 1.0))


def _aquatic_season_weight(ctx) -> float:
    """0..1 weight on AQUATIC FORAGE for the hunt dates.

    Moose aquatic feeding is sodium-driven and seasonal: terrestrial forage carries
    3–28 ppm sodium vs 2–9,400 ppm in aquatic macrophytes, and moose take 94–96% of
    their sodium aquatically — but the behaviour runs roughly early June → mid-
    September (~108 days) and is already declining from late July as macrophytes
    senesce. By the late-September/October hunt window it is effectively over, so a
    model that still weights feeding by pond proximity is modelling the wrong season.

    Full weight through July, ramping down across August–mid September, ~0 after
    about 20 September.
    """
    from datetime import date as _date

    doys = []
    for ds in (ctx.aoi.season.target_dates or []):
        try:
            doys.append(_date.fromisoformat(ds).timetuple().tm_yday)
        except Exception:
            pass
    if not doys:
        return 0.0                      # no dates → assume the hunt season, not summer
    doy = sum(doys) / len(doys)
    peak_end = 212                      # ~Jul 31 — full aquatic use
    over = 263                          # ~Sep 20 — effectively finished
    if doy <= peak_end:
        return 1.0
    if doy >= over:
        return 0.0
    return float(max(0.0, min(1.0, (over - doy) / (over - peak_end))))


# How much a neck's DESTINATIONS can change its score. This REORDERS and discounts; it
# must never delete. The linkage test (T10.17) already did the hard gating — anything
# reaching here is a proven bottleneck — and a neck joining two big blocks of security
# cover is a real travel route even though nothing about it is complementary.
#
# THE FLOOR IS 0.6 BECAUSE 0.35 DELETED THE LAYER. Measured on a funnel-rich box where
# every surviving neck is cover-to-cover in dense conifer: a 0.35 floor multiplied
# already-marginal geometry scores down past the contract's 0.15 polygonize bar and took
# the funnel count from 1 to 0. That bar was calibrated against UNWEIGHTED scores, so
# quietly moving the distribution underneath it is the rev-21 mistake exactly — an
# absolute constant left pointing at a distribution that has shifted.
DEST_FLOOR = 0.6
# A side is sampled within this of the neck. Beyond ~1.5 km you are describing the
# landscape, not what a moose steps into when it comes through.
SIDE_SAMPLE_M = 1500.0
# Two sides of the SAME good thing count for most of it — a moose shuttles between
# feeding areas and between cover blocks too — but the food-to-cover pairing is the
# classic and has to stay visibly ahead. At 0.6 the ordering is
# classic > same-kind > barren with real gaps between them.
SAME_KIND_WEIGHT = 0.6


def _weight_funnels_by_destination(cache, prof, feed, refuge):
    """Scale each funnel by what its two sides actually hold, and record the pairing.

    Writes terrain/funnel.tif in place and terrain/funnel_dest.json — the latter so the
    hover card can say WHICH two things a neck joins ("feeding regen to conifer cover")
    rather than just asserting a number.
    """
    from scipy import ndimage as ndi
    from scipy.ndimage import distance_transform_edt

    from . import terrain as terr

    fpath = cache / "terrain/funnel.tif"
    funnel = _opt(fpath)
    if funnel is None or not np.isfinite(funnel).any() or float(np.nanmax(funnel)) <= 0:
        return

    res = abs(prof["transform"].a)
    barrier = terr._barrier(cache, prof["crs"], prof["transform"], funnel.shape, res,
                            funnel.shape)
    passable = ~barrier
    db = (distance_transform_edt(passable) * res).astype("float32")

    f = np.clip(np.nan_to_num(feed), 0.0, 1.0)
    r = np.clip(np.nan_to_num(refuge), 0.0, 1.0)

    out = np.array(funnel, dtype="float32", copy=True)
    notes = []
    rad = max(1, int(round(SIDE_SAMPLE_M / res)))
    for blob, side_a, side_b, _second in terr.neck_sides(funnel > 0, passable, res, db):
        near = ndi.binary_dilation(blob, iterations=rad)
        a, b = side_a & near, side_b & near
        if not a.any() or not b.any():
            continue
        # THE 90th PERCENTILE, NOT THE MEAN. The question is "is there feeding ground
        # worth walking to on that side", and a mean over a 1.5 km disk answers a
        # different one — it averages the good patch away against everything around it.
        # Measured with means: every multiplier landed between 0.36 and 0.74, so the
        # layer was uniformly halved and the classic feed-to-cover neck scored barely
        # above two sides of the same bog. That is not a weighting, it is a deflation,
        # and it would have pushed funnels under the polygonize bar wholesale — the
        # rev-21 mistake wearing a different hat.
        fa, ra = _side_level(f, a), _side_level(r, a)
        fb, rb = _side_level(f, b), _side_level(r, b)
        # COMPLEMENTARY is the classic: food one side, security cover the other. Take
        # the better of the two orientations — which side is which is not something the
        # neck knows.
        comp = max(min(fa, rb), min(fb, ra))
        # ...but two sides of good ground of the SAME kind is still worth something; a
        # moose moves between feeding areas too. `both` is the weaker, always-available
        # floor so this does not become a purely complementary test.
        both = min(max(fa, ra), max(fb, rb))
        dest = float(np.clip(max(comp, SAME_KIND_WEIGHT * both), 0.0, 1.0))
        out[blob] = (funnel[blob] * (DEST_FLOOR + (1.0 - DEST_FLOOR) * dest)).astype("float32")
        notes.append({
            "feed": [round(fa, 3), round(fb, 3)],
            "refuge": [round(ra, 3), round(rb, 3)],
            "complementary": round(comp, 3),
            "dest": round(dest, 3),
            "joins": _describe_join(fa, ra, fb, rb),
        })

    ru.write(fpath, out, prof)
    if notes:
        try:
            (cache / "terrain/funnel_dest.json").write_text(json.dumps(notes))
        except Exception:
            pass
    print(f"[behavior] funnel destinations scored for {len(notes)} neck(s)")


def _side_level(surface, mask):
    """How good the BEST of a side is, not how good it is on average."""
    vals = surface[mask]
    if vals.size == 0:
        return 0.0
    return float(np.percentile(vals, 90))


# Below this a side holds nothing worth crossing for; and the two scores have to differ
# by at least MARGIN before we are willing to call a side "feeding" rather than "cover".
BARE = 0.20
MARGIN = 0.10


def _describe_join(fa, ra, fb, rb):
    """Plain words for what a neck connects — the thing a hunter can disagree with.

    It must not manufacture a distinction. Calling feed 0.15 / refuge 0.22 "feeding
    ground to security cover" reads as a finding and is noise; below MARGIN the honest
    answer is that the two sides are much the same.
    """
    def side(fv, rv):
        if fv < BARE and rv < BARE:
            return "open ground"
        if abs(fv - rv) < MARGIN:
            return "mixed ground"
        return "feeding" if fv > rv else "cover"
    a, b = side(fa, ra), side(fb, rb)
    if a == b:
        return f"two sides of much the same {a}"
    if {a, b} == {"feeding", "cover"}:
        return "feeding ground to security cover"
    return f"{a} to {b}"


def run(ctx: Context) -> None:
    aoi = ctx.aoi.name
    cache = cache_dir(aoi)
    res = ctx.model.raster_resolution_m
    sp = ctx.species
    bdir = cache / "behavior"
    bdir.mkdir(parents=True, exist_ok=True)

    _, prof = ru.read(cache / "hsm.tif")
    shape = ru.read(cache / "hsm.tif")[0].shape

    browse = _opt(cache / "browse.tif")
    edge = _opt(cache / "edge.tif")
    cover = _opt(cache / "cover.tif")
    thermal = _opt(cache / "hsm_thermal.tif")
    rut = _opt(cache / "hsm_rut.tif")
    funnel = _opt(cache / "terrain/funnel.tif")
    tpi = _opt(cache / "terrain/tpi.tif")
    dist_water = _opt(cache / "dist_water.tif")

    water_nan = np.isnan(browse) if browse is not None else np.zeros(shape, bool)

    def z(a, fill=0.0):
        return np.nan_to_num(a, nan=fill) if a is not None else np.full(shape, fill, "float32")

    # --- water proximity, weighted by SEASON -------------------------------------
    # Aquatic feeding is a sodium-driven SUMMER behaviour: moose take 94–96% of their
    # sodium from aquatic macrophytes, but use runs ~June→mid-September and is already
    # declining from late July as macrophytes senesce. Weighting an October hunt by
    # aquatic forage is simply wrong — by then ponds matter as travel corridors,
    # riparian browse and calling amphitheatres, not as food.
    W = sp.water or {}
    water_prox = _prox(dist_water, W.get("wetland_optimal_m", 150),
                       max(W.get("wetland_falloff_m", 800) * 0.8, 200)) if dist_water is not None \
        else np.full(shape, 0.4, "float32")
    aq = _aquatic_season_weight(ctx)          # 1.0 mid-summer → ~0 by October
    # the water term never vanishes entirely (riparian browse + corridors persist),
    # it just stops being an aquatic-FORAGE magnet
    water_term = 0.35 + (0.30 + 0.35 * aq) * z(water_prox, 0.4)

    # --- FEEDING (dawn/dusk): young browse, on a cover→opening edge, near water.
    # Bulls (our rut target) over-select regen, so give browse a bull bonus.
    fcfg = _species_forage(sp)
    bull_bonus = float(fcfg.get("bull_regen_bonus", 0.2)) if fcfg.get("bull_prefers_regen") else 0.0
    br = z(browse)
    feed_raw = br * (0.5 + 0.5 * z(edge)) * water_term
    feed_raw = feed_raw * (1.0 + bull_bonus * br)     # regen over-selection by bulls
    feed = np.clip(feed_raw, 0.0, 1.0)                 # ABSOLUTE (audit #49) — not per-AOI rank
    feed[water_nan] = np.nan

    # --- THERMAL REFUGE (midday, warm): cool conifer near water. Reuse the HSM
    # thermal surface if present, else rebuild from cover × near-water.
    if thermal is not None:
        # Use the ABSOLUTE hsm_thermal surface as-is (audit #54): re-ranking it per-AOI
        # made the midday routing disagree with the map's fixed 0.5 refuge threshold.
        refuge = np.clip(np.nan_to_num(thermal), 0.0, 1.0)
    else:
        refuge = ru.normalize(z(cover) * z(_prox(dist_water, 100, 400), 0.3))
    refuge[water_nan] = np.nan

    # --- RUT CRUISE (bulls): edge/funnel corridors linking cover and forage. ---
    cruise_raw = z(rut) * (0.55 + 0.45 * np.clip(z(funnel), 0.0, 1.0))   # funnel already absolute
    cruise = np.clip(cruise_raw, 0.0, 1.0)             # ABSOLUTE — feeds hsm_phase (audit #49)
    cruise[water_nan] = np.nan

    # --- Light thermal/slope-position bias: at first light moose feed low (cold
    # air pooled in bottoms), so nudge dawn feeding toward valley bottoms. Small,
    # honest — the surfaces stay driven by forage, not fabricated by terrain.
    low = np.clip(ru.normalize(-z(tpi), lo=-15.0, hi=5.0), 0.0, 1.0)   # fixed bounds → absolute
    feed = np.clip(z(feed) * (0.85 + 0.15 * z(low, 0.5)), 0.0, 1.0)
    feed[water_nan] = np.nan

    # --- Midday anchors: cool = mostly still feeding/loafing with a little cover
    # pull; warm = refuge-dominant. export/ the brief pick the blend from forecast.
    midday_cool = np.clip(0.65 * z(feed) + 0.35 * z(refuge), 0.0, 1.0)
    midday_warm = np.clip(0.15 * z(feed) + 0.85 * z(refuge), 0.0, 1.0)
    for a in (midday_cool, midday_warm):
        a[water_nan] = np.nan

    # --- A FUNNEL HAS TO JOIN TWO PLACES A MOOSE WANTS (T10.18) -------------------
    # T10.17 made every neck prove it is a BOTTLENECK — that cutting it severs a
    # linkage — which killed the peninsulas. That test is pure geometry and cannot ask
    # the second question: a perfect neck between two barren rock outcrops is a perfect
    # bottleneck and a worthless place to sit.
    #
    # What concentrates moose movement is the shuttle between FOOD and SECURITY COVER —
    # which is the biology already stated at the top of this file, "bulls CRUISE...
    # terrain funnels between bedding cover and feeding/wallow complexes". So a neck is
    # worth what it CONNECTS: full credit for feed on one side and refuge on the other,
    # less for two sides of the same thing, and almost nothing for two sides of barren
    # ground.
    #
    # This lives here rather than in terrain.py for a hard reason: terrain runs before
    # habitat, so when funnel.tif is written there is no browse and no cover to read.
    # terrain.py owns the geometry, this owns what is on either side of it, and nothing
    # upstream of here reads funnel.tif (habitat does not; only synth and the contract
    # do), so refining it at this point cannot desync the HSM.
    try:
        _weight_funnels_by_destination(cache, prof, feed, refuge)
    except Exception as _e:  # noqa: BLE001 — a geometry-only funnel beats no funnel
        print(f"[behavior] funnel destination weighting skipped: {_e}")

    ru.write(bdir / "feed.tif", feed.astype("float32"), prof)
    ru.write(bdir / "refuge.tif", refuge.astype("float32"), prof)
    ru.write(bdir / "cruise.tif", cruise.astype("float32"), prof)
    ru.write(bdir / "midday_cool.tif", midday_cool.astype("float32"), prof)
    ru.write(bdir / "midday_warm.tif", midday_warm.astype("float32"), prof)

    # --- narrative + heat thresholds sidecar (consumed by brief + SCOUT_DATA) ---
    heat = sp.thermal_refuge or {}
    periods = {
        "heat": {
            "onset_c": heat.get("heat_onset_c", 14),
            "bedded_c": heat.get("heat_bedded_calm_c", 17),
            "severe_c": heat.get("heat_severe_c", 20),
            "bodytemp_c": heat.get("heat_bodytemp_c", 25),
        },
        "periods": [
            {"key": "dawn", "label": "First light", "grid": "feed",
             "thermal": "downslope (cold air draining) — approach from BELOW / downwind of the feed",
             "text": "Feeding on browse edges and in water — young regen, riparian willow, "
                     "cutblock seams, pond edges. Prime calling/ambush window."},
            {"key": "midday", "label": "Midday", "grid": "midday_cool",
             "grid_warm": "midday_warm", "temp_dependent": True,
             "thermal": "upslope (ground heating) — approach from ABOVE / downwind of the cover",
             "text": "Cool day: still catchable feeding and loafing near cover. Warm day "
                     f"(> {heat.get('heat_onset_c', 14)} °C): pulled into cool conifer / "
                     "north-aspect thermal refuge near water — hunt the shade, not the openings."},
            {"key": "dusk", "label": "Last light", "grid": "feed",
             "thermal": "downslope (evening drainage) — approach from BELOW / downwind of the feed",
             "text": "Back out feeding on the same browse-and-water edges. Second prime window."},
            {"key": "rut_cruise", "label": "Rut cruise (bulls)", "grid": "cruise",
             "thermal": "watch the wallow/funnel — sit downwind of the corridor",
             "text": "Rutting bulls travel cover↔opening edges and terrain funnels between "
                     "bedding and feeding/wallow complexes, checking for cows all day."},
        ],
        "grids": ["feed", "refuge", "cruise", "midday_cool", "midday_warm"],
    }
    (bdir / "periods.json").write_text(json.dumps(periods, indent=2))


def _species_forage(sp) -> dict:
    """SpeciesCfg doesn't model the raw `forage` block; read it back off the YAML
    so we honour bull_prefers_regen/bull_regen_bonus without a schema change."""
    try:
        from .config import config_dir, _load_yaml
        raw = _load_yaml(config_dir() / "species" / f"{sp.species}.yaml")
        return raw.get("forage", {}) or {}
    except Exception:
        return {}
