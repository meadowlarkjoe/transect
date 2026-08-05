"""Water, wetland & land cover from ESA WorldCover (10 m, via Planetary Computer).

Replaces a slow/heavy OSM-Overpass water pull with one decimated COG read that
yields, on the canonical grid:
  water.tif      1 = permanent water body (class 80)
  wetland.tif    1 = herbaceous wetland (class 90)
  landcover.tif  raw WorldCover class (10 tree, 20 shrub, 30 grass, 60 bare,
                 80 water, 90 wetland, 100 moss/lichen, ...)

The classes feed the HSM directly (shrubland/grassland = browse, tree = cover,
water/wetland = aquatic forage) and are reliable north of the écoforestière limit.
"""
from __future__ import annotations

from ..config import Context, cache_dir
from .. import rasterio_utils as ru
from ..rasterio_utils import target_grid


def fetch(ctx: Context) -> None:
    import os

    import numpy as np
    import planetary_computer as pc
    import rasterio
    from pystac_client import Client

    os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
    cache = cache_dir(ctx.aoi.name)
    # All three outputs present → nothing to do. Without this, hydro re-queried the
    # STAC catalogue and re-warped WorldCover on every run, and it was the last source
    # still spending real time on a fully cached box.
    if all((cache / n).exists() and (cache / n).stat().st_size > 0
           for n in ("landcover.tif", "water.tif", "wetland.tif", "lcfrac_tree.tif")):
        print("[hydro] cached — skipping WorldCover")
        return

    minlon, minlat, maxlon, maxlat = ctx.aoi.bbox_wgs84()
    aoi_wgs = (minlon, minlat, maxlon, maxlat)
    dst_crs, dst_transform, W, H = target_grid(ctx)

    cat = Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                      modifier=pc.sign_inplace)
    items = list(cat.search(collections=["esa-worldcover"],
                            bbox=[minlon, minlat, maxlon, maxlat], limit=12).items())
    if not items:
        raise RuntimeError("no WorldCover item for AOI")
    # A 45 km box straddles WorldCover's 3° tiles, so one item covers only part of it —
    # reading a single item with an out-of-bounds window is what striped the map. Take
    # ALL tiles of the most-recent map year and mosaic them onto the canonical grid, each
    # via a window CLAMPED to its real extent (see ru.reproject_window).
    newest = max(i.properties.get("start_datetime", "") for i in items)
    tiles = [i for i in items if i.properties.get("start_datetime", "") == newest] or items

    # WorldCover classes that carry habitat meaning for us. Kept explicit: an unlisted
    # class simply has no fraction layer, rather than silently folding into another.
    FRAC_CLASSES = {10: "tree", 20: "shrub", 30: "grass", 40: "crop",
                    60: "bare", 80: "water", 90: "wetland", 100: "moss"}

    lc = np.zeros((H, W), dtype="uint8")
    frac = {name: np.zeros((H, W), dtype="float32") for name in FRAC_CLASSES.values()}
    covered = np.zeros((H, W), dtype=bool)

    for it in tiles:
        with rasterio.open(it.assets["map"].href) as src:
            arr, mask = ru.reproject_window(src, dst_crs, dst_transform, W, H, aoi_wgs,
                                            resampling="nearest")
            # NATIVE-RESOLUTION FRACTIONS (#77/#78). WorldCover is 10 m and the analysis
            # grid is typically 40 m, so the nearest-neighbour read above lets ONE native
            # pixel in sixteen decide the cell. The habitat model's dominant term is
            # cover↔food interspersion, which is precisely the sub-cell mixture that
            # throws away. Measure the real areal fraction of each class instead, at the
            # source's own resolution, and aggregate late.
            try:
                f, seen = ru.class_fractions(src, list(FRAC_CLASSES), dst_crs,
                                             dst_transform, W, H, aoi_wgs)
                for code, name in FRAC_CLASSES.items():
                    fill = seen & ~covered
                    frac[name][fill] = f[code][fill]
                covered |= seen
            except Exception as ex:      # degrade to the class map alone, and say so
                print(f"[hydro] native-resolution fractions unavailable: {ex}")
        if arr is None:
            continue
        fill = mask & (lc == 0)                       # first tile to cover a cell wins
        lc[fill] = np.rint(arr[fill]).astype("uint8")

    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "height": H, "width": W,
            "crs": dst_crs, "transform": dst_transform, "nodata": 0,
            "compress": "deflate", "tiled": True}

    def _save(name, arr):
        with rasterio.open(cache / name, "w", **prof) as dst:
            dst.write(arr.astype("uint8"), 1)

    _save("landcover.tif", lc)
    # Water and wetland stay categorical here for the layers that expect a mask, but the
    # FRACTION is what the barrier and browse terms should read: a cell that is 40 %
    # beaver flowage is neither dry land nor a lake, and rounding it either way is a
    # decision the model should not be making for the hunter.
    _save("water.tif", (lc == 80).astype("uint8"))
    _save("wetland.tif", (lc == 90).astype("uint8"))

    if covered.any():
        fprof = dict(prof, dtype="float32", nodata=-9999.0)
        for name, a in frac.items():
            with rasterio.open(cache / f"lcfrac_{name}.tif", "w", **fprof) as dst:
                dst.write(np.where(covered, a, -9999.0).astype("float32"), 1)
        pct = 100.0 * float(covered.mean())
        print(f"[hydro] native 10 m class fractions written for {len(frac)} classes "
              f"({pct:.0f}% of cells) — analysis grid {abs(dst_transform.a):.0f} m")
