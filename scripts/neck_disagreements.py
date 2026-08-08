#!/usr/bin/env python
"""Where exactly do the coarse and fine neck detectors disagree? (T9.10b)

The open question on this ticket is not arithmetic, it is ground truth: are the necks the
fine grid ADDS real pinch points, or artefacts of a sharper water outline? "3007 cells at
a median width of 208 m" is not something anyone can check. A list of places is.

Writes a GPX with two tracks' worth of waypoints:
  ADD-n  — the fine detector found a neck here and the coarse one did not
  DROP-n — the coarse detector found one here and the fine one did not

Each carries its measured neck width and score in the description, so a spot can be
judged against what the model claims about it.
"""
import os
import pathlib
import sys
import xml.sax.saxutils as sx

import numpy as np
import rasterio as rio
from pyproj import Transformer
from scipy import ndimage as ndi

sys.path.insert(0, "/app/src")
from moose_scout import terrain as T  # noqa: E402

BAR = 0.15
TOP = 10


def arm(cache, prof, shape, res, step):
    f_res = res / step
    f_tr, f_shape = T._grid_at(prof["transform"], shape, res, f_res)
    bar = T._barrier(cache, prof["crs"], f_tr, f_shape, f_res, shape if step == 1 else None)
    con, wid = T._constriction(bar, f_res, grid_res=res)
    if step > 1:
        con = T._block_reduce(con, step, "max", shape)
        wid = T._block_reduce(wid, step, "min", shape)
    return con, wid


def pick(mask, con, wid, tag, transform, to_wgs):
    """Top TOP connected blobs by peak score, as (name, lon, lat, desc)."""
    lab, n = ndi.label(mask)
    if not n:
        return []
    rows = []
    for i in range(1, n + 1):
        m = lab == i
        if m.sum() < 2:
            continue                     # a single cell is not a place
        peak = float(np.nanmax(con[m]))
        w = wid[m]
        w = w[np.isfinite(w)]
        rows.append((peak, i, float(np.nanmedian(w)) if w.size else float("nan"), int(m.sum())))
    rows.sort(reverse=True)
    out = []
    for k, (peak, i, w, cells) in enumerate(rows[:TOP], start=1):
        ys, xs = np.nonzero(lab == i)
        # the CENTRE of the neck, not the blob's bounding-box centre
        cy, cx = float(ys.mean()), float(xs.mean())
        x, y = transform * (cx + 0.5, cy + 0.5)
        lon, lat = to_wgs.transform(x, y)
        out.append((f"{tag}-{k}", lon, lat,
                    f"score {peak:.2f} · neck ~{w:.0f} m · {cells} cells"))
    return out


def main(cache, out_path, step):
    cache = pathlib.Path(cache)
    with rio.open(cache / "dem.tif") as s:
        prof = {"transform": s.transform, "crs": s.crs}
        shape, res = (s.height, s.width), abs(s.transform.a)
    to_wgs = Transformer.from_crs(prof["crs"], "EPSG:4326", always_xy=True)

    c_con, c_wid = arm(cache, prof, shape, res, 1)
    f_con, f_wid = arm(cache, prof, shape, res, step)
    mc, mf = c_con > BAR, f_con > BAR
    print(f"{cache.name}: coarse {int(mc.sum())} cells · fine({step}x) {int(mf.sum())} "
          f"· agreed {int((mc & mf).sum())}")

    pts = (pick(mf & ~mc, f_con, f_wid, "ADD", prof["transform"], to_wgs)
           + pick(mc & ~mf, c_con, c_wid, "DROP", prof["transform"], to_wgs))
    with open(out_path, "w") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<gpx version="1.1" creator="Transect T9.10b" '
                 'xmlns="http://www.topografix.com/GPX/1/1">\n')
        for name, lon, lat, desc in pts:
            fh.write(f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}">'
                     f'<name>{sx.escape(name)}</name>'
                     f'<desc>{sx.escape(desc)}</desc></wpt>\n')
        fh.write("</gpx>\n")
    for name, lon, lat, desc in pts:
        print(f"  {name:8s} {lat:.5f}, {lon:.5f}   {desc}")
    print(f"\nwrote {len(pts)} waypoints -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 3)
