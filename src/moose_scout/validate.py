"""Null-model benchmark — is the answer distinguishable from a trivial one? (T6.1)

THE PROBLEM THIS TICKET NAMED: "the model is currently unfalsifiable." There is no
ground truth for where moose are. No collar data, no harvest points at this resolution,
nothing to score a prediction against. That is exactly why the epic sat open, and it is
why a benchmark that waits for ground truth waits forever.

WHAT CAN BE ASKED WITHOUT GROUND TRUTH, and it is worth asking: does the model tell you
anything a five-line heuristic would not? Two null models:

  * ROAD — score every cell by how close it is to a road. This is the "just hunt where
    it is easy to get to" strategy, and it is what a hunter with a paper map already
    does. If the model's focus areas are the same ground a road buffer picks, the model
    is an expensive road buffer.
  * RANDOM — uniform noise over huntable ground, seeded. NOT compared by overlap: two
    independent same-sized selections from the same pool overlap at the area fraction by
    construction, so that number is a tautology and a check built on it passes for a
    literally random model (the first version of this file made exactly that mistake,
    and measured 4.0% against an expected 4.0%). Compared instead on CAPTURE — how much
    of the discrimination the model's own surface contains survives into the ground it
    hands you — and on coherence, since random selection is confetti.

The comparison is made at MATCHED AREA: each null model takes the same number of
hectares the real model chose, so the overlap is a fair like-for-like and not an
artefact of one selection being bigger.

WHAT THIS CANNOT TELL YOU, stated so nobody quotes it as more than it is: beating both
nulls does not mean the model is RIGHT. It means the model is doing something other than
tracing roads or throwing darts. Being wrong in an interesting way still fails a hunt.
Ground truth is T6.2 (harvest density), and that ticket stays open.
"""
from __future__ import annotations

import json
from pathlib import Path

SEED = 20260807
# Below this the best contiguous area barely beats a random draw, so the ground has no
# structure at this scale and `capture` is dividing by noise.
MIN_HEADROOM = 0.02


def _top_mask(score, huntable, n_cells):
    """The n_cells best huntable cells by `score`, as a boolean mask."""
    import numpy as np

    s = np.where(huntable, np.nan_to_num(score, nan=-np.inf), -np.inf)
    n_cells = int(min(n_cells, int(huntable.sum())))
    if n_cells <= 0:
        return np.zeros(score.shape, bool)
    flat = s.ravel()
    idx = np.argpartition(flat, -n_cells)[-n_cells:]
    out = np.zeros(flat.shape, bool)
    out[idx] = True
    return out.reshape(score.shape)


def _spearman(a, b):
    """Rank correlation, without pulling in scipy.stats for one number."""
    import numpy as np

    def rank(x):
        order = np.argsort(x, kind="mergesort")
        r = np.empty(len(x), dtype="float64")
        r[order] = np.arange(len(x), dtype="float64")
        return r

    if len(a) < 3:
        return float("nan")
    ra, rb = rank(a), rank(b)
    ra -= ra.mean(); rb -= rb.mean()
    den = float(np.sqrt((ra ** 2).sum() * (rb ** 2).sum()))
    return float((ra * rb).sum() / den) if den else float("nan")


def benchmark(cache: Path, sample: int = 200_000) -> dict:
    """Score the model's chosen ground against the two null models.

    Returns a dict of measurements, not a verdict — the caller decides what passes.
    """
    import numpy as np

    from . import rasterio_utils as ru

    cache = Path(cache)
    hunt = ru.read(cache / "huntability.tif")[0]
    prof = ru.read(cache / "huntability.tif")[1]
    dist_road = ru.read(cache / "dist_road.tif")[0]

    # COMPARE AGAINST THE POOL THE MODEL COULD ACTUALLY CHOOSE FROM. The first version
    # drew its nulls from every finite cell of huntability.tif, but synth crops a 2 km
    # border before extracting anything — focal and Hessian filters produce artefacts at
    # the raster edge, so that ground is never a candidate. Measured on one box: 399.5
    # km2 finite against 256.5 km2 the model can reach, so a third of the random null's
    # pool was ground the model was never allowed to pick. A null model has to be given
    # the same choices as the thing it is a null for.
    res = abs(prof["transform"].a)
    pool = cache / "focus_pool.tif"
    if pool.exists():
        # THE POOL, AS THE EXTRACTION RECORDED IT (T6.4). Guessing this from outside
        # failed four times: first the 2 km border crop was missed entirely, then it was
        # applied but the reachability/camp-radius mask was not. On one box the model's
        # real choice set was rows 254-754 of a 1008-row raster, and the "best possible
        # area" the benchmark held it to sat outside that window — so it was measured
        # against ground it was forbidden to pick, and judged for not picking it.
        huntable = np.nan_to_num(ru.read(pool)[0]) > 0.5
    else:
        # Older cache: the border crop is the part that can be reconstructed safely.
        m = max(5, int(round(2000 / res)))
        huntable = np.isfinite(hunt)
        huntable[:m, :] = False
        huntable[-m:, :] = False
        huntable[:, :m] = False
        huntable[:, -m:] = False
    huntable &= np.isfinite(hunt)
    if not huntable.any():
        return {"ok": False, "why": "no huntable ground in this cache"}

    # The model's own selection: the ground it actually put a focus area on. Falling
    # back to its top-scoring cells lets this run on a cache whose synth stage never
    # produced areas — the null models are still meaningful there.
    picked, source = None, "focus_areas"
    fa = cache / "focus_areas.geojson"
    if fa.exists():
        try:
            picked = _rasterize_areas(fa, cache)
        except Exception:
            picked = None
    no_areas = picked is None or not picked.any()
    if no_areas:
        # An extraction that produced NOTHING cannot be scored on how well it selected.
        # The fallback below exists so the road null is still measurable on such a cache,
        # but `capture` must come back None — top-scoring cells trivially beat the oracle
        # and a sweep reported 2.3-3.2 for settings whose real result was ZERO areas,
        # which is the most flattering possible number for the worst possible outcome.
        source = "top-scoring cells (NO focus areas — capture is not meaningful)"
        picked = _top_mask(hunt, huntable, max(1, int(0.05 * huntable.sum())))

    n = int(picked.sum())
    frac = n / float(huntable.sum())

    # ROAD null: closer is better. Matched area.
    road_score = -np.nan_to_num(dist_road, nan=np.inf)
    road_pick = _top_mask(road_score, huntable, n)

    # RANDOM null: the floor. Seeded so the number is reproducible.
    rng = np.random.default_rng(SEED)
    rand_pick = _top_mask(rng.random(hunt.shape), huntable, n)

    def overlap(m):
        return float((picked & m).sum() / max(1, n))

    # THE RANDOM NULL CANNOT BE AN OVERLAP TEST, and the first version of this file got
    # that wrong. Two independent same-sized selections from the same pool overlap at
    # the area fraction BY CONSTRUCTION — measured 4.0% against an expected 4.0%, 6.3%
    # against 6.3%. That number is a tautology, and a check built on it passes for a
    # literally random model. What the random null CAN establish is that the selection
    # mechanism works at all: the chosen ground has to concentrate the model's own score
    # and be coherent country rather than confetti.
    from scipy import ndimage as ndi

    def stats(m):
        vals = np.nan_to_num(hunt[m])
        _lab, ncomp = ndi.label(m)
        return (float(vals.mean()) if vals.size else 0.0, int(ncomp))

    hunt_sel, comp_sel = stats(picked)
    hunt_rand, comp_rand = stats(rand_pick)
    # TWO CEILINGS, and only one of them is a fair target.
    #
    # `hunt_top` is the best n CELLS the score can offer — cherry-picked and maximally
    # fragmented. No focus area could ever reach it, because an area has to be ground you
    # can walk. Reported for scale, never used as the yardstick: against it every result
    # looks like a failure, which is uninformative.
    #
    # `hunt_oracle` is the best CONTIGUOUS region of the same size — same shape of thing
    # the model is asked to produce, at the best available place. That is the honest
    # target, and the difference between the two is stark: on one real box the model
    # scored 0.248, cherry-picked cells 0.435, and the fair oracle 0.322. Judged against
    # 0.435 the model captured 1%; judged against what a contiguous area could actually
    # achieve, 5% — still poor, but now a claim about the EXTRACTION rather than about
    # the impossibility of contiguity. On a second box the oracle itself reached only
    # 0.253 against 0.248 random, which says that box has almost no structure at this
    # scale and the model's near-random result is honest.
    hunt_top, _ = stats(_top_mask(hunt, huntable, n))
    hunt_oracle, _ = stats(_oracle_blob(hunt, huntable, n))

    # Correlation over a sample of huntable cells — the full grid is tens of millions.
    idx = np.flatnonzero(huntable.ravel())
    if len(idx) > sample:
        idx = rng.choice(idx, size=sample, replace=False)
    hv = np.nan_to_num(hunt.ravel()[idx])
    dv = np.nan_to_num(dist_road.ravel()[idx], nan=1e6)
    dv = np.where(np.isfinite(dv), dv, 1e6)

    return {
        "ok": True,
        "selection_source": source,
        "huntable_cells": int(huntable.sum()),
        "selected_cells": n,
        "selected_frac": round(frac, 4),
        # Overlap with a same-sized selection made by the ROAD null. Meaningful,
        # because a road buffer is a specific piece of ground, not a shuffle.
        "overlap_road": round(overlap(road_pick), 4),
        # Against RANDOM, measured on concentration and coherence rather than overlap.
        "mean_hunt_selected": round(hunt_sel, 4),
        "mean_hunt_random": round(hunt_rand, 4),
        "mean_hunt_ceiling": round(hunt_top, 4),
        "mean_hunt_oracle": round(hunt_oracle, 4),
        # 0 = no better than random, 1 = as good as a contiguous area of this size can be.
        # None when there is nothing to capture: on ground with no structure at this
        # scale the denominator is noise, and it produced a meaningless -26% on a real
        # box whose oracle beat random by 0.005.
        "capture": round((hunt_sel - hunt_rand) / (hunt_oracle - hunt_rand), 4)
        if (not no_areas and (hunt_oracle - hunt_rand) >= MIN_HEADROOM) else None,
        # When the oracle barely beats random there is no structure to exploit at this
        # scale, and a low capture says nothing about the extraction.
        "oracle_headroom": round(hunt_oracle - hunt_rand, 4),
        "patches_selected": comp_sel,
        "patches_random": comp_rand,
        # How much of the model's score is just "near a road".
        "spearman_hunt_vs_proximity": round(_spearman(hv, -dv), 4),
    }


def _oracle_blob(hunt, huntable, n):
    """The best CONTIGUOUS region of n cells — the fair target for a focus area.

    Centred on the strongest ground at the area's own scale (a Gaussian whose sigma
    follows the area radius, so it finds the best NEIGHBOURHOOD rather than the best
    pixel), then the n nearest huntable cells. Same size, same shape of thing, best
    available place.
    """
    import numpy as np
    from scipy.ndimage import gaussian_filter

    hv = np.nan_to_num(hunt)
    sigma = max(2.0, float(np.sqrt(n / np.pi)) / 2.0)
    sm = gaussian_filter(np.where(huntable, hv, 0.0), sigma=sigma)
    sm = np.where(huntable, sm, -1.0)
    cy, cx = np.unravel_index(int(np.argmax(sm)), sm.shape)
    Y, X = np.ogrid[:hunt.shape[0], :hunt.shape[1]]
    dist = np.where(huntable, (Y - cy) ** 2 + (X - cx) ** 2, np.inf).ravel()
    n = int(min(n, int(huntable.sum())))
    idx = np.argpartition(dist, n - 1)[:n] if n > 1 else [int(np.argmin(dist))]
    out = np.zeros(hv.size, bool)
    out[idx] = True
    return out.reshape(hv.shape)


def _rasterize_areas(path: Path, cache: Path):
    import geopandas as gpd
    import numpy as np
    from rasterio.features import rasterize

    from . import rasterio_utils as ru

    prof = ru.read(cache / "huntability.tif")[1]
    shape = ru.read(cache / "huntability.tif")[0].shape
    g = gpd.read_file(path)
    if not len(g):
        return np.zeros(shape, bool)
    if g.crs and str(g.crs) != str(prof["crs"]):
        g = g.to_crs(prof["crs"])
    geoms = [x for x in g.geometry if x is not None and not x.is_empty]
    if not geoms:
        return np.zeros(shape, bool)
    return rasterize([(x, 1) for x in geoms], out_shape=shape,
                     transform=prof["transform"], fill=0, dtype="uint8").astype(bool)


def verdict(r: dict) -> dict:
    """Turn measurements into the two claims this benchmark can actually support."""
    if not r.get("ok"):
        return dict(r, beats_road=None, beats_random=None)
    # "Beats random" means the selection is doing its job: it concentrates the model's
    # own score well above a random draw of the same size, and it returns coherent
    # country rather than scattered cells. This is a check on the SELECTION MECHANISM —
    # it deliberately does not claim the score itself is right, which would be circular.
    # CAPTURE is the principled number: what share of the discrimination the model's own
    # surface contains actually survives into the ground it hands you. A selection that
    # keeps under a quarter of it is not doing its job, whatever the surface underneath
    # is worth. The threshold is a floor, not a target — it exists to FAIL loudly, and
    # on first measurement it failed on two of three real boxes (6% and 16% capture).
    cap = r.get("capture")
    if cap is None:
        # Nothing to capture — the honest verdict is "not applicable", not "failed".
        return dict(r, beats_road=bool(r["overlap_road"] < 0.75
                                       and abs(r["spearman_hunt_vs_proximity"]) < 0.75),
                    beats_random=None)
    concentrates = cap >= 0.25
    coherent = r["patches_selected"] * 5 < max(1, r["patches_random"])
    beats_random = bool(concentrates and coherent)
    # "Beats road" means: it is not just a road buffer. Two ways to fail — picking the
    # same ground, or ranking it the same way.
    beats_road = r["overlap_road"] < 0.75 and abs(r["spearman_hunt_vs_proximity"]) < 0.75
    return dict(r, beats_road=bool(beats_road), beats_random=bool(beats_random))


def report(cache: Path) -> str:
    r = verdict(benchmark(cache))
    if not r.get("ok"):
        return f"{Path(cache).name}: {r.get('why')}"
    return (
        f"{Path(cache).name}\n"
        f"  selection            {r['selected_cells']} cells "
        f"({100 * r['selected_frac']:.1f}% of huntable ground, from {r['selection_source']})\n"
        f"  overlap vs ROAD      {100 * r['overlap_road']:.1f}%   "
        f"(a road buffer of the same size picks this much of the same ground)\n"
        f"  vs RANDOM            mean score {r['mean_hunt_selected']:.3f} against "
        f"{r['mean_hunt_random']:.3f} for a random draw of the same size;\n"
        f"                       {r['patches_selected']} patches against "
        f"{r['patches_random']} (random selection is confetti)\n"
        f"  fair oracle          {r['mean_hunt_oracle']:.3f} is the best CONTIGUOUS area of "
        f"this size (cherry-picked cells reach {r['mean_hunt_ceiling']:.3f},\n"
        f"                       which no walkable area could);\n"
        f"                       the focus areas capture "
        f"{'n/a' if r['capture'] is None else format(100 * r['capture'], '.0f') + '%'} "
        f"of the gap between random and that oracle\n"
        f"                       (oracle headroom over random: {r['oracle_headroom']:.3f} — "
        f"below ~0.02 there is no structure at this scale to capture)\n"
        f"  rank corr vs road proximity  {r['spearman_hunt_vs_proximity']:+.3f}\n"
        f"  -> distinguishable from a road buffer: {r['beats_road']}\n"
        f"  -> distinguishable from random:        {r['beats_random']}\n"
        f"  NOTE: this says the model is doing something other than tracing roads or\n"
        f"        throwing darts. It does not say the answer is right — that needs\n"
        f"        ground truth, which is T6.2.")


def main(argv=None):
    import sys
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        print("usage: python -m moose_scout.validate <cache_dir> [<cache_dir>...]")
        return 2
    for a in args:
        print(report(Path(a)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
