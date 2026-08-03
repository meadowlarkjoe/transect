"""Stage 4 — access, extraction & huntability.

Combines habitat with realistic retrieval and hunter pressure:
  dist_road.tif      metres to nearest drivable road (truck extraction)
  extraction.tif     0..1 ease of getting a 400-600 lb animal out (best of
                     truck-to-road and canoe-to-water within the decay range)
  pressure.tif       0..1 hunter pressure (rises near roads/access)
  huntability.tif    hsm × extraction × (1 − pressure_weight × pressure), the
                     moose sweet spot: high habitat that is retrievable but not
                     road-pressured (typically near water, off the main road).

Extraction modes come from config/model.yaml (truck / canoe / atv / backpack);
this first pass models the two that dominate at Fire Lake (truck-to-road,
canoe-to-water) and treats atv/backpack as extending the road/water decay range.
"""
from __future__ import annotations

import numpy as np

from .config import Context, cache_dir
from . import rasterio_utils as ru


def _dist(mask_bool, res):
    from scipy.ndimage import distance_transform_edt

    if mask_bool.any():
        return distance_transform_edt(~mask_bool) * res
    return np.full(mask_bool.shape, 1e6, dtype="float32")


def run(ctx: Context) -> None:
    cache = cache_dir(ctx.aoi.name)
    res = ctx.model.raster_resolution_m
    mcfg = ctx.model
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
    if roads is not None and (roads > 0).any():
        dist_road = _dist(roads > 0, res)
    else:
        dist_road = np.full(hsm.shape, 1e6, dtype="float32")  # no roads -> truck N/A
    ru.write(cache / "dist_road.tif", dist_road.astype("float32"), prof)

    # Extraction ease per mode = exp(-dist/decay); keep the best mode per cell.
    truck = np.exp(-dist_road / decay)
    canoe = np.exp(-dist_water / (decay * 1.2))     # water routes tolerate more distance
    extraction = np.maximum(truck, canoe).astype("float32")
    ru.write(cache / "extraction.tif", extraction, prof)

    # Hunter pressure: high near roads (access), decaying outward.
    pressure = np.exp(-dist_road / road_decay).astype("float32")
    ru.write(cache / "pressure.tif", pressure, prof)

    hunt = np.nan_to_num(hsm) * extraction * (1 - pw * pressure)
    hunt = ru.normalize(hunt)
    hunt[np.isnan(hsm)] = np.nan
    ru.write(cache / "huntability.tif", hunt.astype("float32"), prof)
