#!/usr/bin/env python
"""Coarse vs fine neck detection on one cached box (T9.10b).

WHY THIS IS A SCRIPT AND NOT A NOTE. Three Band 1 tickets in a row turned out to be the
MEASUREMENT being wrong rather than the model, every time because the instrument was
reconstructed from outside instead of written down. This is the instrument for the
funnel-population question. Run it; do not re-derive it.

    docker run --rm -v "$PWD/src:/app/src:ro" -v "$PWD/cache:/app/cache" \
      -v "$PWD/config:/app/config:ro" -v "$PWD/scripts:/app/scripts:ro" \
      -w /app --entrypoint python moose-scout:local \
      /app/scripts/ab_necks.py /app/cache/<box>

WHAT IT NEEDS. A cache with `dem.tif` AND the water vectors (`waterbodies.gpkg`,
`waterways.gpkg`) — the vectors are the whole premise of the fine grid, and without them
the fine barrier is bit-identical to the coarse one after folding back. It also needs a
grid the budget will let the fine detector engage on: `FINE_BUDGET_PX` is 9 Mpx, so a
real 35-45 km box (3.1-6.5 Mpx) floors the step to 1 and both arms are the same run.
Deep-analysis sub-caches are small enough but carry no vectors. To get both, crop a full
cache — see `_ab_small` in the T9.10b notes.

WHAT IT CANNOT TELL YOU. Whether the necks the fine grid ADDS are real. That is ground
truth and it needs someone who has walked the ground.
"""
import os
import pathlib
import sys

import numpy as np
import rasterio as rio

sys.path.insert(0, "/app/src")
from moose_scout import terrain as T  # noqa: E402

BAR = 0.15          # the polygonize admission threshold (contract.py)
COARSE_FLOOR = 113  # 40 m grid: 2*sqrt(2) cells, the narrowest width it can express


def arm(cache, prof, shape, res, fine):
    os.environ["FINE_NECKS"] = "1" if fine else "0"
    f_res = T._fine_res(res, shape)
    f_tr, f_shape = T._grid_at(prof["transform"], shape, res, f_res)
    barrier = T._barrier(cache, prof["crs"], f_tr, f_shape, f_res,
                         shape if f_res == res else None)
    con, wid = T._constriction(barrier, f_res, grid_res=res)
    audit = dict(getattr(T._constriction, "last_audit", {}) or {})
    if f_res != res:
        k = int(round(res / f_res))
        con = T._block_reduce(con, k, "max", shape)
        wid = T._block_reduce(wid, k, "min", shape)
        barrier = T._block_reduce(barrier.astype("float32"), k, "max", shape) > 0.5
    return f_res, con, wid, audit, barrier


def main(cache):
    cache = pathlib.Path(cache)
    with rio.open(cache / "dem.tif") as s:
        prof = {"transform": s.transform, "crs": s.crs}
        shape, res = (s.height, s.width), abs(s.transform.a)
    vec = [p.name for p in cache.glob("*.gpkg")]
    print(f"{cache.name}: {shape[0]}x{shape[1]} @ {res:.0f} m   vectors: {vec or 'NONE'}")
    if not vec:
        print("  !! no water vectors — the fine grid has no finer geometry to measure")

    R = {}
    for fine in (False, True):
        lab = "fine" if fine else "coarse"
        R[lab] = arm(cache, prof, shape, res, fine)
        f_res, con, wid, audit, bar = R[lab]
        m = con > BAR
        ws = wid[np.isfinite(wid) & m]
        print(f"\n--- {lab}: measured at {f_res:.2f} m ({res / f_res:.0f}x)")
        print(f"    {audit}")
        print(f"    barrier cells {int(bar.sum())}   over the {BAR} bar {int(m.sum())}")
        if ws.size:
            print(f"    widths: {len(np.unique(np.round(ws)))} distinct, "
                  f"{ws.min():.0f}-{ws.max():.0f} m, median {np.median(ws):.0f}")

    mc, mf = R["coarse"][1] > BAR, R["fine"][1] > BAR
    print(f"\nbarrier identical after folding back: "
          f"{bool((R['coarse'][4] == R['fine'][4]).all())}")
    print(f"cells: coarse {int(mc.sum())}  fine {int(mf.sum())}  agreed {int((mc & mf).sum())}  "
          f"coarse-only {int((mc & ~mf).sum())}  fine-only {int((mf & ~mc).sum())}")
    if mc.any():
        print(f"retained by fine: {100 * (mc & mf).sum() / mc.sum():.0f}% of coarse cells")
    g = R["fine"][2][np.isfinite(R["fine"][2]) & mf & ~mc]
    if g.size:
        print(f"gained {g.size} cells, median {np.median(g):.0f} m; "
              f"{100 * float((g < COARSE_FLOOR).mean()):.0f}% narrower than the "
              f"coarse grid's {COARSE_FLOOR} m floor — the rest are necks it missed for "
              f"other reasons, and whether they are real is a ground-truth question")


if __name__ == "__main__":
    main(sys.argv[1])
