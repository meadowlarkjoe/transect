"""Local OSM extract reader — the durable replacement for live Overpass.

Live Overpass turned out to be the worst dependency in the pipeline:
  • overpass-api.de and kumi.systems block this host's IP outright;
  • maps.mail.ru answers but took 8043 s (2 h 14 m) for one 70 km road-dense box;
  • overpass.osm.ch answers in 13 s with ZERO features — it only holds Switzerland;
  • private.coffee is quick on small queries and still bogs down on a large box.
Losing the road network is not cosmetic: with no watercraft it used to zero out the
whole huntability surface, so the map came back empty.

A Geofabrik regional extract removes the problem entirely — one download, then every
AOI is a local bbox read: fast, repeatable, rate-limit free and offline. GDAL's OSM
driver is already in the image, so this needs no new dependency.

Set OSM_PBF to the extract path (default /app/osm/quebec-latest.osm.pbf).
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

PBF = os.environ.get("OSM_PBF", "/app/osm/quebec-latest.osm.pbf")
# GDAL's OSM driver needs to be told to keep the tags we filter on.
_OSMCONF = """[general]
attribute_name_laundering=yes
[points]
osm_id=yes
attributes=highway,waterway,natural,water,landuse,railway
[lines]
osm_id=yes
attributes=highway,waterway,railway,natural,water,landuse
[multipolygons]
osm_id=yes
attributes=natural,water,landuse,waterway
[multilinestrings]
osm_id=yes
attributes=waterway,railway
[other_relations]
osm_id=yes
attributes=natural,water
"""


def available() -> bool:
    try:
        return Path(PBF).is_file() and Path(PBF).stat().st_size > 1_000_000
    except Exception:
        return False


def _conf_path() -> str:
    p = Path(tempfile.gettempdir()) / "osmconf_transect.ini"
    if not p.exists():
        p.write_text(_OSMCONF)
    return str(p)


def read_bbox(bbox, layer: str, where: str | None = None):
    """Read one OSM layer clipped to bbox=(minlon,minlat,maxlon,maxlat).

    `layer` is a GDAL OSM layer: 'lines' or 'multipolygons'.
    Returns a GeoDataFrame (possibly empty); None if the extract isn't present.
    """
    if not available():
        return None
    import geopandas as gpd

    minlon, minlat, maxlon, maxlat = bbox
    out = Path(tempfile.mkdtemp()) / "clip.gpkg"
    cmd = ["ogr2ogr", "-f", "GPKG", str(out), PBF, layer,
           "-spat", str(minlon), str(minlat), str(maxlon), str(maxlat),
           "-oo", "CONFIG_FILE=" + _conf_path(),
           "-nlt", "PROMOTE_TO_MULTI", "-skipfailures"]
    if where:
        cmd += ["-where", where]
    env = dict(os.environ, OSM_MAX_TMPFILE_SIZE="2000", CPL_LOG="/dev/null")
    try:
        subprocess.run(cmd, check=True, env=env, timeout=900,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        g = gpd.read_file(out)
        return g.set_crs(4326, allow_override=True) if len(g) else g
    except Exception:
        return None
    finally:
        try:
            out.unlink(missing_ok=True)
            out.parent.rmdir()
        except Exception:
            pass


# --- convenience wrappers matching what roads.py needs -----------------------
DRIVE_WHERE = ("highway IN ('motorway','trunk','primary','secondary','tertiary',"
               "'unclassified','residential','track','service')")
RAIL_WHERE = "railway IN ('rail','narrow_gauge','light_rail')"
WATERLINE_WHERE = "waterway IN ('river','stream','canal','tidal_channel','rapids')"
WATERPOLY_WHERE = "natural = 'water' OR landuse = 'reservoir'"


def roads(bbox):
    return read_bbox(bbox, "lines", DRIVE_WHERE)


def rail(bbox):
    return read_bbox(bbox, "lines", RAIL_WHERE)


def waterways(bbox):
    return read_bbox(bbox, "lines", WATERLINE_WHERE)


def waterbodies(bbox):
    return read_bbox(bbox, "multipolygons", WATERPOLY_WHERE)
