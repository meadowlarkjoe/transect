#!/usr/bin/env python
"""What does raising FINE_BUDGET_PX actually cost? (T9.10b)

The fine neck detector is inert on every box anyone really runs: the budget is 9 Mpx and
a 35-45 km analysis grid is 3.1-6.5 Mpx, so the step floors to 1x. Deciding whether to
raise it was called "a worker-memory measurement" and then left unmeasured, which is not
a decision, it is a deferral. This measures it.

Peak RSS of the DETECTOR ALONE, so the number is a floor rather than a full-run figure —
a real run has the habitat stack live at the same time. Run it under the worker's real
limit (`docker run -m 4g`) to find out whether it survives at all.
"""
import os
import pathlib
import resource
import sys

import numpy as np
import rasterio as rio

sys.path.insert(0, "/app/src")
from moose_scout import terrain as T  # noqa: E402


def peak_gb():
    r = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes. The container is Linux.
    return r / (1024 ** 2) if sys.platform.startswith("linux") else r / (1024 ** 3)


def main(cache, steps):
    cache = pathlib.Path(cache)
    with rio.open(cache / "dem.tif") as s:
        prof = {"transform": s.transform, "crs": s.crs}
        shape, res = (s.height, s.width), abs(s.transform.a)
    px = shape[0] * shape[1]
    print(f"{cache.name}: {shape[0]}x{shape[1]} @ {res:.0f} m = {px / 1e6:.2f} Mpx")
    print(f"baseline peak {peak_gb():.2f} GB (before any detector work)\n")

    for step in steps:
        # Force the step rather than going through FINE_BUDGET_PX, so the measurement is
        # of the GRID, not of the budget arithmetic.
        f_res = res / step
        f_tr, f_shape = T._grid_at(prof["transform"], shape, res, f_res)
        print(f"--- step {step}x -> {f_res:.1f} m, {f_shape[0]}x{f_shape[1]} "
              f"= {f_shape[0] * f_shape[1] / 1e6:.1f} Mpx")
        try:
            bar = T._barrier(cache, prof["crs"], f_tr, f_shape, f_res,
                             shape if step == 1 else None)
            con, wid = T._constriction(bar, f_res, grid_res=res)
            audit = dict(getattr(T._constriction, "last_audit", {}) or {})
            if step > 1:
                con = T._block_reduce(con, step, "max", shape)
            print(f"    candidates {audit.get('candidates')} · kept {audit.get('kept')} "
                  f"· passable {audit.get('passable_frac')} · peak RSS {peak_gb():.2f} GB")
            del bar, con, wid
        except MemoryError:
            print(f"    MemoryError at {step}x · peak RSS {peak_gb():.2f} GB")
            return
    budget = int(px * max(steps) ** 2)
    print(f"\nFINE_BUDGET_PX would need to be >= {budget / 1e6:.1f}e6 "
          f"for {max(steps)}x on a box this size (it is "
          f"{T.FINE_BUDGET_PX / 1e6:.0f}e6).")


if __name__ == "__main__":
    main(sys.argv[1], [int(x) for x in sys.argv[2].split(",")])
