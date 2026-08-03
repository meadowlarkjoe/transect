# Moose Scout

DIY hunt-area intelligence for remote North American hunts. Turns public
geospatial data into a ranked, annotated scouting brief you can carry into the
field — starting with **moose in northern Quebec (Fire Lake / Fermont)**.

The target deliverable is a per-area map in the style of a SEPAQ *secteur de
chasse* sheet: topography + écoforestière cover overlay, annotated **focus
polygons**, **access/travel routes**, point features (wallows, glassing knobs,
base camp, parking), and numbered field notes — exportable to **OnX Hunt**
(GPX/KML) and to an **offline GeoPDF + tile pack** for zero-cell use.

## Why this exists

Google Maps is wrong in the bush (logging spurs only show on satellite; "roads"
wash out). Generic satellite land-cover is too coarse to find moose. And the
prettiest topo pick is worthless if it's inside an exclusive outfitter, the
wrong zone, or closed season. Moose Scout gates on **legality first**, models
**habitat** from stand-level forestry data, then co-locates habitat inside a
realistic **multi-modal extraction corridor** (truck / canoe / ATV / pack-out) —
because a bull is 400–600+ lb and pack-out is what actually kills DIY hunts.

## Pipeline

```
config → [0] legal/tenure mask → [1] acquire → [2] terrain → [3] habitat (HSM)
       → [4] access + extraction → [5] huntability + focus areas
       → [6] Claude synthesis → [7] export (OnX GPX/KML · GeoPDF · web map)
```

See `docs/` (planned) and `config/` for the moving parts. The design plan lives
at `~/.claude/plans/you-are-a-200iq-kind-shamir.md`.

## Quick start

```bash
make build          # build the GDAL/python geo image
make aoi=fire_lake legal    # resolve zone/season/tenure -> huntable mask
make aoi=fire_lake acquire  # pull DEM, écoforestière, hydro, roads, Sentinel-2
make aoi=fire_lake run       # full pipeline -> outputs/fire_lake/
```

Everything runs in Docker (Colima) — the host needs no GDAL. Outputs land in
`outputs/<aoi>/`.

## Status

Early scaffold. Module contracts and the data-source registry are in place;
stages are being filled in P0 → P6 (see the plan).
