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
    dist_road = ru.read(cache / "dist_road.tif")[0]
    huntable = np.isfinite(hunt)
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
    if picked is None or not picked.any():
        source = "top-scoring cells (no focus areas in this cache)"
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
    # THE CEILING: the best n cells the model's OWN score can offer. A focus area is a
    # contiguous blob, so it necessarily swallows mediocre interior ground that a
    # cherry-picked top-n would skip. Without this the "+14% over random" reading is
    # unreadable — it does not say whether the box is uniformly mediocre or the
    # extraction is throwing the signal away.
    hunt_top, _ = stats(_top_mask(hunt, huntable, n))

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
        # 0 = no better than random, 1 = as good as the score allows.
        "capture": round((hunt_sel - hunt_rand) / (hunt_top - hunt_rand), 4)
        if hunt_top > hunt_rand else None,
        "patches_selected": comp_sel,
        "patches_random": comp_rand,
        # How much of the model's score is just "near a road".
        "spearman_hunt_vs_proximity": round(_spearman(hv, -dv), 4),
    }


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
    concentrates = cap is not None and cap >= 0.25
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
        f"  ceiling              {r['mean_hunt_ceiling']:.3f} is the best the model's own "
        f"score could do at this area;\n"
        f"                       the focus areas capture "
        f"{'n/a' if r['capture'] is None else format(100 * r['capture'], '.0f') + '%'} "
        f"of the gap between random and that ceiling\n"
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
