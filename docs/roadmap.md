# Transect — roadmap to a multi-species, multi-region engine

**Status:** 0.1.0 — moose, Fire Lake AOI, Québec boreal.
**Written:** 2026-08-04.

---

## The thesis, and why the version ladder is not the hard part

The stated ladder is moose@FireLake → moose@QC → moose@Canada → moose@US →
moose@world → other species. That ordering is right, but it hides where the cost
actually is. Climbing it is **not** mostly a biology problem. Measured against the
current tree:

| What has to change | Evidence |
|---|---|
| The client hardcodes the legend | `app.js` carries **22 hardcoded `LAYERS` rows**, including the literal sentence *"Strongest single predictor here"* about burn regen — a moose/Fire-Lake claim compiled into the front end |
| Region logic has no seam | `region_profile` exists in `config.py:122` and is **read by nothing** |
| Québec is spread through the engine | **16 files** carry `quebec` / `ecoforestiere` / `NBAC` / `pourvoirie` / `EPSG:32198`; `legal.py` alone has 14 hits |
| The working CRS is a provincial default | `working_crs: EPSG:32198` (NAD83 / Québec Lambert) is the global default in `model.yaml` |
| Species configs are already good | `config/species/{moose,whitetail_deer,black_bear}.yaml` are real, weighted, cited models — this part is **ahead** of the rest |

So: the species layer is the healthiest thing here. The blockers are **(a) a client
that cannot render a legend it wasn't compiled with**, and **(b) an engine with no
concept of "where am I and what data exists here".** Every rung of the ladder is
gated on those two, which is why they are E1 and E2 and everything else waits.

### The honesty constraint that shapes the architecture

Transect's whole value proposition is that it does not render data it does not
have. Generalising multiplies the ways that promise can break: a US AOI has no
écoforestière, no NBAC burn history, no pourvoirie polygons. The failure mode is
**not** "the map is empty" — it's "the map looks identical and is quietly guessing."

Therefore every region/species epic carries a **coverage declaration** as a
first-class deliverable, not a footnote. A region that ships without one is not
done, however good its scores look.

---

## Structural shape: base engine + sub-engines

```
                    ┌───────────────────────────────┐
                    │  BASE ENGINE (geo, invariant) │
                    │  terrain · hydro · access ·   │
                    │  extraction · routing · wind  │
                    └───────────────┬───────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
      ┌───────▼───────┐    ┌────────▼────────┐   ┌────────▼────────┐
      │ REGION ADAPTER│    │ SPECIES MODEL   │   │ LEGAL ADAPTER   │
      │ what data     │    │ what the animal │   │ what you may    │
      │ exists here   │    │ wants           │   │ legally do here │
      │ + CRS + srcs  │    │ + derived layers│   │ + tenure + seas.│
      └───────┬───────┘    └────────┬────────┘   └────────┬────────┘
              └─────────────────────┼─────────────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ CONTRACT  (transect.json)     │
                    │ …including the LEGEND itself  │
                    └───────────────┬───────────────┘
                                    │
                    ┌───────────────▼───────────────┐
                    │ CLIENT — renders what it is   │
                    │ given, knows no species       │
                    └───────────────────────────────┘
```

The client becoming species-agnostic is the load-bearing change. A Rocky Mountain
goat hunt wants escape terrain, cliff bands, mineral licks, and glassing lines at
2 km — none of which exist in a moose legend. If the legend ships from the engine,
that is a config change. If it stays in `app.js`, it is a client release per
species, forever.

---

## Epics

Each epic states its **exit criterion** — the thing that must be demonstrably true,
not "the code is written."

### E0 — Make autonomous work safe *(prerequisite, blocks E8)*

Two facts make unattended work reckless today:

- **`transect-app` is not under version control.** ~150 KB of `app.js` with no
  history. An agent with a bad edit loses work with no undo.
- **There is effectively no test suite.** One file (`tests/test_legal.py`), and
  `pytest` isn't installed in the local env.

**Exit:** `transect-app` is a git repo with a clean baseline commit; `pytest` runs
green in CI-equivalent form locally; a smoke test asserts the contract loads and
the app boots headless. Until then, autonomous agents may **propose diffs only**,
never write to the working tree.

### E1 — Contract-driven legend *(unblocks the entire ladder)*

Move symbology from the client into `transect.json`. The engine already has
`config/output_legend.yaml`, but it is used **only** server-side for GPX/KML export
— it never reaches the app.

- Engine emits `legend: [{key, group, name, note, hex, icon, kind, edge, count, basis}]`.
- `app.js` builds `LAYERS` from `DOC.legend`, falling back to the current hardcoded
  array only when absent (so 0.1.0 plans keep working).
- Species/region prose (`"Strongest single predictor here"`) moves to the species
  config where it can be true per-species.
- Layer groups become data too — a goat hunt needs *ESCAPE TERRAIN*, not *ACCESS & HYDRO*.

**Exit:** deleting the hardcoded `LAYERS` array leaves the Fire Lake plan rendering
byte-identically, and a synthetic non-moose contract renders a different legend with
no client change.

### E2 — Region resolver + data-source registry

Make `region_profile` real. Resolve AOI centroid → region → the adapter set,
projection, and an explicit coverage manifest.

- `config/regions/*.yaml`: bbox/geometry, `working_crs`, available sources, legal adapter.
- Resolver picks the region; unknown regions degrade to a **global baseline**
  (SRTM/Copernicus DEM, OSM hydro/roads, ESA WorldCover, VIIRS/MODIS fire) rather
  than failing.
- Every run emits `coverage: {source: status}` — `native` / `fallback` / `absent`.
- `working_crs` derives from the region (UTM zone or provincial Lambert), not a constant.

**Exit:** an AOI in Montana produces a valid plan with an explicit coverage manifest
naming what it did **not** have, and the confidence score reflects the downgrade.

### E3 — Species model plug-ins (derived layers, not just weights)

`config/species/*.yaml` already carries weights. What it cannot yet express is
**species-specific derived layers**: burn-regen age bands are a *moose* predictor;
a goat model wants slope-band escape terrain and cliff proximity.

- A species config declares which derived layers to compute and how to band them.
- `synth.py` stops hardcoding `rut_calling` / `thermal_refuge` / `saline_blind` and
  reads a species' site taxonomy.
- Site types, icons, and copy all flow to the legend via E1.

**Exit:** adding a species is a YAML file plus (where needed) one registered layer
builder — no edits to `synth.py`, `contract.py`, or the client.

### E4 — Legal / tenure adapters per jurisdiction

`legal.py` is the most province-locked file (14 Québec hits): zones, ZEC,
réserve faunique, pourvoirie, MWA rules.

- Adapter interface: `resolve(aoi) -> {zone, season, weapon_rules, tenure_polygons, citations}`.
- Québec adapter = today's behaviour, extracted intact.
- Unknown jurisdiction returns `UNRESOLVED` **loudly** — a plan may still render,
  but the legal gate says it could not be verified. It must never silently imply legality.

**Exit:** a US-state AOI returns `UNRESOLVED` with an honest banner instead of
Québec zone semantics quietly misapplied.

### E5 — Research pipeline (feeds E2/E3, autonomous)

The Fire Lake pass produced genuinely good biology (rut anchoring, burn-age bands,
thermal thresholds with citations). That process should be repeatable and mostly
unattended.

- A research agent produces a **structured, cited** species×region profile —
  never free prose that a human must transcribe into YAML.
- Output is a draft `config/species/*.yaml` + `config/regions/*.yaml` with every
  claim carrying a source, and an explicit *"what I could not find"* section.
- **Drafts land as proposals for review, never straight into `config/`.** A
  hallucinated weight is indistinguishable from a researched one once merged.

**Exit:** one command drafts a reviewed-ready profile for a named species×region
with citations and gaps enumerated.

### E6 — Validation harness *(the credibility gate)*

The model is still **unfalsifiable** — this was true at 0.1.0 and generalising
multiplies the risk. Without this, "moose in Montana" is an unverifiable claim.

- Null-model benchmark: does the model beat "distance to road" and "random points
  within huntable ground"?
- Backtest against harvest-density statistics where published.
- Ground-truth loop: field pins feed back as labelled observations.

**Exit:** every region ships a published score against the null model. A region that
cannot beat random is shipped **labelled as such**, or not shipped.

### E7 — Mobile responsive *(GATED — see below)*

**Blocked on you supplying a mobile design.** Desktop-first was explicit in the
current handoff and a field/phone tier was declared out of scope. Tickets are
drafted below so the work is ready to start the day the design lands, but no
implementation begins before then — guessing a responsive layout for a
map-plus-three-rails interface would mean rework, not progress.

### E8 — Autonomous build infrastructure

See "The night shift" below. Gated on **E0**.

---

## Version ladder mapped to epics

| Version | Scope | Requires | New risk |
|---|---|---|---|
| **0.1.0** | moose @ Fire Lake | — | shipped |
| **0.1.1** | moose @ Québec | E1, E2 (QC), E6 | écoforestière thins north of 52°N |
| **0.1.2.x** | moose @ other CA provinces | E2 (per-province), E4 | tenure/season regimes differ per province |
| **0.1.3.x** | moose @ US states | E2 (US sources), E4 (state adapters) | no écoforestière analogue; draw/tag systems |
| **0.1.4.x** | moose @ Fennoscandia etc. | E2 (global baseline), i18n | different subspecies behaviour; metric/legal divergence |
| **0.2.x** | second species (elk or whitetail) | E1, E3, E5, E6 | first true test that the legend generalises |
| **0.3.x+** | mountain goat / sheep | E3 (vertical terrain), new legend groups | escape terrain, cliff bands — a genuinely different map |

**Sequencing note:** 0.1.2 (other provinces) is a *worse* second step than it looks.
Each province is a fresh legal adapter for the same animal — high integration cost,
low model learning. Doing **0.2.x (a second species in Québec)** earlier proves the
E1/E3 abstractions against data you already have and already trust. Recommend:
0.1.1 → 0.2.0 (whitetail @ QC, configs already drafted) → then fan out regionally.

---

## The night shift — autonomous progression

### What it may and may not do

Bounded deliberately. The failure mode for unattended agents on this codebase is not
bad code, it is **plausible-looking model claims** merged without evidence.

**May:** research and draft configs (as proposals); write tests; refactor toward the
E1–E4 seams behind existing behaviour; run the pipeline on cached rasters; produce
diffs and reports; keep the backlog groomed.

**May not:** deploy (`deploy.sh`), touch the droplet or Caddy, mutate `config/species/*`
or `config/regions/*` directly, alter model weights outside a proposal, or push to
`main`. Anything that changes what a hunter is told is a human decision.

### Shape

```
.claude/
  agents/
    transect-researcher.md     species×region biology, cited, gaps declared
    transect-datasource.md     find/verify open geodata for a region, prove a fetch
    transect-engineer.md       implement one backlog ticket on a branch
    transect-reviewer.md       adversarial review; refute before accepting
    transect-hunter.md         reads the PLAN as a hunter: "would I actually walk this?"
    transect-groomer.md        keep BACKLOG.md ordered, unblocked, honest
  workflows/
    night-shift.js             pick ticket → implement → review → report
    research-pass.js           fan out research for a species×region matrix cell
docs/
  roadmap.md                   this file
  BACKLOG.md                   the queue the night shift reads
  proposals/                   agent output awaiting your review
```

The reviewer is deliberately adversarial and defaults to rejection: with generated
model changes, a wrong-but-plausible weight is worse than no change, because it is
invisible once merged.

The **hunter** is the separate gate that matters most. Reviewers read code; the hunter
reads the resulting plan and asks whether they would drive six hours for it. Every
defect that has actually reached Joe — the 28 km chained access route, hunt lines from
a camp 40 km away, paths across open lakes, nine focus areas collapsed to two by an
arbitrary constant, a base camp for a hunter who said "vehicle" — passed every code
check and failed the moment a person looked at the map. That failure mode gets its own
agent.

### Cadence

A scheduled run picks the top unblocked ticket, does one bounded piece of work,
and leaves a branch plus a report in `docs/proposals/`. It stops on any ambiguity
rather than guessing. You review in the morning; nothing reaches a hunter unreviewed.

---

## Mobile tickets — drafted, gated on your design

Not started. Listed so the work is shovel-ready when the design arrives.

| # | Ticket | Note |
|---|---|---|
| M1 | Responsive shell: tab bar, panel, map | The 380 px ledger + 46 px rails + cards assume ≥1100 px |
| M2 | Layers card → bottom sheet | 296 px card at `left:420` has nowhere to go on a phone |
| M3 | Tool + view rails → collapsed toolbar | Two 46 px rails cost ~15% of a phone's width |
| M4 | Hover identify → tap identify | There is no hover on touch; the identify card needs a dismiss |
| M5 | 44 px touch targets, sunlight contrast | Explicitly deferred in the current handoff |
| M6 | Map controls / scale bar reflow | Scale bar is pinned `left:404 bottom:12` |
| M7 | Setup form on mobile | Numeric steppers, date inputs, search results list |
| M8 | Brief / Field reading view | Long prose in a 380 px column does not translate |

**Open question for you:** is mobile a *field* tool (offline, gloves, sunlight,
one-handed) or a *couch* tool (reviewing a plan you built at a desk)? Those are
different products. The field answer implies offline tiles and much larger targets;
the couch answer is mostly reflow. I would not start M1 without knowing which.

---

## What I am not claiming

- That the model is correct anywhere, including Fire Lake. E6 exists because it is
  currently unfalsifiable.
- That species configs for `whitetail_deer` and `black_bear` are validated. They are
  drafted and unexercised — no run has used them end to end.
- That the region list above is complete. It is a plan, not a survey of open geodata.
