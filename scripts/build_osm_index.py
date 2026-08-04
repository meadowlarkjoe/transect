"""One-time: derive a small, spatially-indexed GPKG from the big Geofabrik .pbf.

Reading the raw 1.1 GB extract works but costs ~60 s per layer per AOI because GDAL
re-parses the whole file. This pulls out just the four layers the model uses, once,
so every later AOI read is an R-tree bbox lookup instead.

    docker exec transect-api python3 /app/scripts/build_osm_index.py
"""
import time
from moose_scout.acquire import osm_local as L

print("PBF:", L.PBF)
print("GPKG:", L.GPKG)
t = time.time()
ok = L.build_index()
print(f"{'built' if ok else 'FAILED'} in {time.time()-t:.0f}s  ·  indexed={L.has_index()}")
