"""Land-tenure polygons from the MRNF *Territoires fauniques structurés* (TFS)
layer: ZEC, réserves fauniques, refuges fauniques, pourvoiries à droits
exclusifs, etc. Province-wide GeoJSON (EPSG:32198) cached once and clipped per
AOI.

Feeds the legal gate's HUNTABLE mask. Any AOI area NOT covered by a TFS polygon
is crown land (terres du domaine de l'État) — huntable DIY by a Quebec resident.
Non-exclusive outfitters do NOT appear here (they operate on crown land), so
their absence is expected, not missing data.

Decoded TFS attributes (ogrinfo): DE_TSJP = tenure class, NM_TSJP = name.
"""
from __future__ import annotations

import json

from ..config import Context, cache_dir
from ..legal import Tenure, TenurePatch
from . import _client

CACHE = "tenure.geojson"
TFS_URL = (
    "https://diffusion.mffp.gouv.qc.ca/Diffusion/DonneeGratuite/"
    "Faune/TFS/GEOJSON/Territoires_Fauniques_Structures.geojson"
)

# DE_TSJP class string (lowercased) -> our Tenure enum.
_DE_TSJP_MAP: dict[str, Tenure] = {
    "pourvoirie à droits exclusifs": Tenure.POURVOIRIE_EXCLUSIVE,
    "zone d'exploitation contrôlée": Tenure.ZEC,
    "réserve faunique": Tenure.RESERVE,
    "refuge faunique": Tenure.REFUGE,
    "aire faunique communautaire": Tenure.OTHER,   # fishing-oriented — verify
    "petit lac aménagé": Tenure.OTHER,             # managed lake — verify
}


def _classify(de_tsjp: str | None) -> Tenure:
    return _DE_TSJP_MAP.get((de_tsjp or "").strip().lower(), Tenure.OTHER)


def fetch(ctx: Context) -> None:
    """Download the province-wide TFS once, clip to the AOI, normalize the tenure
    class, and write cache/<aoi>/tenure.geojson (always — an empty result means
    'all crown land', which is a valid, huntable answer)."""
    out = cache_dir(ctx.aoi.name) / CACHE
    # Already clipped for this box → done. Re-reading and re-clipping the province-wide
    # TFS took ~15 s on every run, including runs where the geography cache had just
    # handed us the finished file.
    if out.exists() and out.stat().st_size > 0:
        return

    shared = _client.shared_dir() / "TFS.geojson"
    _client.download(TFS_URL, shared)

    gdf = _client.read_clip(shared, ctx)

    if len(gdf) == 0:
        out.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
        return

    de_field = _client.pick_field(gdf.columns, "de_tsjp") or "DE_TSJP"
    nm_field = _client.pick_field(gdf.columns, "nm_tsjp") or "NM_TSJP"
    gdf = gdf.copy()
    gdf["tclass"] = gdf[de_field].map(lambda v: _classify(v).value)
    gdf["tname"] = gdf.get(nm_field, "")
    gdf["tclass_fr"] = gdf[de_field]
    gdf[["tclass", "tname", "tclass_fr", "geometry"]].to_file(out, driver="GeoJSON")


def load_tenure_patches(ctx: Context) -> list[TenurePatch]:
    """Read the clipped tenure file as TenurePatch objects. Raises
    FileNotFoundError if not acquired (gate reports UNVERIFIED). An empty list is
    a valid result: the AOI is entirely crown land."""
    path = cache_dir(ctx.aoi.name) / CACHE
    if not path.exists():
        raise FileNotFoundError(CACHE)

    fc = json.loads(path.read_text())
    features = fc.get("features", [])
    shape = None
    if features:
        from shapely.geometry import shape  # lazy — only when geometry present

    patches: list[TenurePatch] = []
    for feat in features:
        props = feat.get("properties", {})
        tenure = Tenure(props.get("tclass", Tenure.OTHER.value))
        geom = feat.get("geometry")
        patches.append(
            TenurePatch(
                tenure=tenure,
                name=str(props.get("tname", "")),
                geometry=shape(geom) if (geom and shape) else None,
            )
        )
    return patches
