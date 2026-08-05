# Expansion playbook — new region, new species

A repeatable script for taking Transect somewhere new, so expansion is a **procedure we
improve** rather than a bespoke effort we rediscover. Every time a phase surprises us —
a novel data source, a defect that slipped through, a species assumption that didn't
travel — the fix goes back into this file.

Two independent paths that meet at the end:

```
REGION path  A → B → C → D ─┐
                            ├─→ F  validate together, then ship
SPECIES path E1 → E2 ───────┘
```

The paths are separable on purpose: moose@Abitibi and whitetail@Québec share region
work; moose@Québec and moose@Fennoscandia share species work. Never redo the shared half.

---

## Phase A — inventory what we already have

Before researching anything new, write down what exists and **what each source actually
feeds**. A source is only real if something downstream consumes it.

Current inventory (`src/moose_scout/acquire/`):

| Module | Source | Feeds |
|---|---|---|
| `dem.py` | CDEM / HRDEM (NRCan) | slope, aspect, TPI, TWI, viewshed, funnels |
| `sentinel.py` | Sentinel-2 L2A (Planetary Computer STAC) | NDVI → browse proxy, confidence |
| `fire.py` | NBAC burned area (CWFIS WFS) | burn-age browse — strongest single predictor |
| `ecoforestiere.py` | MRNF carte écoforestière | stand species, canopy closure, dated cuts |
| `grhq.py` | MRNF GRHQ hydrography | wetlands (funnel + walk barrier), beaver ponds (rut hub), crossing order/perenniality |
| `hydro.py` / `osm_local.py` | OSM + ESA WorldCover | lakes, rivers, water barriers, display |
| `roads.py` | OSM | drivable network (unioned with AQréseau+) |
| `aqreseau.py` | **AQréseau+ (MRNF)** | official roads incl. forest-road class, bridges (+status), quad/snowmobile sentiers, rail |
| `tenure.py` | MRNF tenure | pourvoirie / ZEC / réserve — the legal gate |
| `zones.py` | MRNF hunting zones | zone resolution, seasons |

**Rule:** a new source must name the model term or map layer it changes. "Nice to have"
data that feeds nothing is not integrated — it is a ticket.

---

## Phase B — research sources for the new area

Work the checklist below, and **explicitly hunt for sources previous areas lacked** —
that's where the step-change accuracy lives (AQréseau+ was exactly this: OSM had almost
no logging roads, and `dist_road` drives reachability, pressure, pack-out and staging).

For each candidate record: endpoint + protocol, licence, coverage envelope, update
cadence, native resolution, and **which existing model term it replaces or improves**.

- Terrain: national DEM, LiDAR where it exists
- Vegetation/forestry: stand inventory, harvest history, fire history
- Hydrography: network with flow class/perenniality, wetlands, waterbodies
- Access: official road network **with class**, bridges **with status**, motorised trails, rail
- Tenure/legal: who may hunt where, zones, seasons, weapon rules
- Wildlife: harvest statistics, aerial inventory/density, telemetry studies

**Traps, learned the hard way:**
- *A fast empty answer looks like success.* Probe every endpoint with a query you know
  should return features; assert a non-zero count.
- *Thematic layer groups are usually one feature class rendered N ways.* Find the
  partition (AQréseau+ "Carrossabilité" leaves sum exactly to the layer total) instead
  of summing overlapping groups.
- *Layers in one service can have different schemas.* A shared `outFields` list 400s on
  the odd one out; a bare `except` then reports it as "no data". Request per-layer fields
  and **surface the error**.
- *Coverage has edges.* Record the envelope (écoforestière stops at ~52°N) and degrade
  loudly, never silently.

---

## Phase C — integrate + normalize

- One module per source in `acquire/`, mirroring `grhq.py`/`aqreseau.py`: paged, bbox
  clipped, time-budgeted (`*_BUDGET_S`), **never raises** — a failure degrades to the
  previous behaviour and says so.
- Normalize into the vocabulary the model already speaks (road → `artery|road|track`;
  water → the barrier union). New vocabulary only when the concept is genuinely new —
  and then it needs its own cost tier, not a borrowed one (motorised sentiers are **not**
  roads: you can't drive them, so they must never feed `dist_road`).
- Rasterize vector barriers with `all_touched=True` so narrow streams, necks and small
  ponds can't vanish on a coarse grid.
- Register in `config/regions/<profile>.yaml` with its coverage envelope so
  `region.coverage_manifest` reports in/partial/out **and** whether it actually landed.
- Bump `ENGINE_REVISION` whenever the same inputs now produce a materially different plan.

---

## Phase D — cross-reference the UI (do not skip)

The failure mode this phase exists to prevent: **the engine reads a source the map never
draws.** AQréseau+ shipped engine-only at first — the router used forest roads while the
map still showed "no road data," which is exactly what the user was looking at.

For every new source, confirm all five:

1. It reaches the **map payload** (`export._infra_lines` / a `*_zones` emitter), not just
   a cost raster.
2. It has a **layer row** with its own toggle, and a distinct one where the thing is
   distinct (trails ≠ roads).
3. **Legend prose** in `config/species/<species>.yaml` says what it is and what it is
   *not* (source of truth; the client's hardcoded strings are only a fallback).
4. **Explainability**: sourced layers appear in `confidence.SOURCE_NOTES` so hover names
   the source; modelled features get reasons from `confidence.site_explain`.
5. The **brief** reflects the local source (methodology caveats name what actually
   covered this box).

---

## Phase E — species

### E1. Research-based behavioural profile
For a new species, build `config/species/<name>.yaml` from the literature, not from
analogy: cover types with browse/cover weights, water relationship, terrain preference,
rut/seasonality phases and what each phase changes, diel pattern and thermal limits, HSM
term weights, and the legend prose (names/notes/groups) so the whole UI re-labels itself
with no app change.

**State the evidence class per term.** "Validated HSI" (moose: Allen 1987) and "inferred
from a related species" must not be presented with the same confidence.

### E2. Local modifiers
Behaviour is regional. Same species, different country: rut timing shifts with latitude,
forage differs, pressure and access culture differ. Keep a **base species model** plus a
**region modifier**, never a forked species file — the model should improve continuously
in one place and be adjusted locally, so a fix in the base reaches every region.

Ask explicitly: *does hunting strategy change here?* If yes, that belongs in the brief
and possibly in the site mix, not just in the weights.

---

## Phase F — validate before shipping

- Run a real AOI end to end; compare against the previous engine revision and explain
  every difference you did not intend.
- Verify against ground truth the user can check (OnX, a known camp, a known road).
- Confirm the coverage manifest is honest: sources declared in-coverage that returned
  nothing must read `missing`, not silently pass.
- Re-check the **capability gate** after any access-data change — better road data moves
  both the ranking and the exclusions, in opposite directions.
- **Existing cached plans do not benefit until re-run.** Say so plainly (see #79 for
  making that re-run cheap).

---

## Running this as background work

Each phase is a discrete, checkable unit of work with a written artifact, which is what
makes it safe to run unattended:

| Phase | Artifact | Autonomy |
|---|---|---|
| A | source inventory table | safe |
| B | candidate source dossier (endpoint, licence, coverage, model term) | safe — research only |
| C | `acquire/*.py` + region yaml + rev bump | safe, gated on tests |
| D | UI cross-reference checklist, all five confirmed | safe |
| E1 | species yaml + evidence classes | **needs review** — biology claims |
| E2 | region modifiers | **needs review** |
| F | validation report vs previous revision | safe to run, **findings need review** |

Anything asserting *what animals do* gets human review. Everything mechanical — fetching,
normalizing, wiring, cross-referencing, validating — can run on its own.
