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
attributes=natural,water,landuse,waterway,building,leisure,amenity
[multilinestrings]
osm_id=yes
attributes=waterway,railway
[other_relations]
osm_id=yes
attributes=natural,water
"""


# A derived, spatially-indexed GPKG holding only the four layers we actually use.
# Reading the raw .pbf works but costs ~60 s per query because GDAL re-parses the whole
# 1.1 GB file every time; querying this instead is a bbox lookup against an R-tree.
# Built once by build_index() (scripts/build_osm_index.py).
GPKG = os.environ.get("OSM_GPKG", str(Path(PBF).with_suffix("")) + "_index.gpkg")
_LAYERS = {
    "roads": ("lines", "highway IN ('motorway','trunk','primary','secondary','tertiary',"
                       "'unclassified','residential','track','service')"),
    "rail": ("lines", "railway IN ('rail','narrow_gauge','light_rail')"),
    "waterways": ("lines", "waterway IN ('river','stream','canal','tidal_channel','rapids')"),
    "waterbodies": ("multipolygons", "natural = 'water' OR landuse = 'reservoir'"),
    # Developed ground. NOT a cadastre — Québec parcel data isn't open (the MSP WMS
    # refuses it, Données Québec doesn't carry it, and the assessment-unit layer is
    # Montréal-only). But you cannot hunt private land, so ignoring it entirely is
    # worse than an honest inference: mapped residential/farm/industrial landuse and
    # building footprints are almost certainly private or occupied.
    "builtup": ("multipolygons",
                "landuse IN ('residential','farmland','farmyard','industrial','commercial',"
                "'retail','quarry','cemetery','allotments','village_green','recreation_ground') "
                "OR building IS NOT NULL OR leisure IN ('park','golf_course')"),
}


def has_index() -> bool:
    try:
        return Path(GPKG).is_file() and Path(GPKG).stat().st_size > 100_000
    except Exception:
        return False


def available() -> bool:
    if has_index():
        return True
    try:
        return Path(PBF).is_file() and Path(PBF).stat().st_size > 1_000_000
    except Exception:
        return False


def build_index(verbose: bool = True) -> bool:
    """One-time: pull the four layers we use out of the .pbf into an indexed GPKG."""
    if not Path(PBF).is_file():
        return False
    ok = False
    for name, (layer, where) in _LAYERS.items():
        cmd = ["ogr2ogr", "-f", "GPKG", GPKG, PBF, layer,
               "-nln", name, "-where", where,
               "-oo", "CONFIG_FILE=" + _conf_path(),
               "-nlt", "PROMOTE_TO_MULTI", "-skipfailures",
               "-lco", "SPATIAL_INDEX=YES"]
        if ok:
            cmd.insert(3, "-update")           # append into the same file
        env = dict(os.environ, OSM_MAX_TMPFILE_SIZE="2000", CPL_LOG="/dev/null")
        try:
            if verbose:
                print(f"  building {name}…", flush=True)
            subprocess.run(cmd, check=True, env=env, timeout=5400,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            ok = True
        except Exception as e:  # noqa: BLE001
            if verbose:
                print(f"  {name} FAILED: {e}", flush=True)
    return ok


def _conf_path() -> str:
    p = Path(tempfile.gettempdir()) / "osmconf_transect.ini"
    if not p.exists():
        p.write_text(_OSMCONF)
    return str(p)


def read_indexed(bbox, name: str):
    """Fast path: bbox query against the prebuilt, spatially-indexed GPKG."""
    if not has_index():
        return None
    try:
        import geopandas as gpd
        g = gpd.read_file(GPKG, layer=name, bbox=tuple(bbox))
        return g.set_crs(4326, allow_override=True) if len(g) else g
    except Exception:
        return None


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
BUILTUP_WHERE = ("landuse IN ('residential','farmland','farmyard','industrial','commercial',"
                 "'retail','quarry','cemetery','allotments','village_green','recreation_ground') "
                 "OR building IS NOT NULL OR leisure IN ('park','golf_course')")


def _get(bbox, name, layer, where):
    g = read_indexed(bbox, name)          # indexed GPKG: ~1 s
    if g is not None:
        return g
    return read_bbox(bbox, layer, where)  # raw .pbf: ~60 s


TRAIL_WHERE = "highway IN ('path','footway','bridleway','cycleway')"


def roads(bbox):
    return _get(bbox, "roads", "lines", DRIVE_WHERE)


def trails(bbox):
    """Foot trails (path/footway/bridleway). Not in the prebuilt index — reads the raw
    .pbf (~60 s), which is fine: boreal trails are sparse and this runs once per AOI."""
    return _get(bbox, "trails", "lines", TRAIL_WHERE)


def rail(bbox):
    return _get(bbox, "rail", "lines", RAIL_WHERE)


def waterways(bbox):
    return _get(bbox, "waterways", "lines", WATERLINE_WHERE)


def waterbodies(bbox):
    return _get(bbox, "waterbodies", "multipolygons", WATERPOLY_WHERE)


def builtup(bbox):
    """Developed / likely-private ground. An inference, not a cadastre — label it so."""
    return _get(bbox, "builtup", "multipolygons", BUILTUP_WHERE)
