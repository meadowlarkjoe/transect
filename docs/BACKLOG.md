# Transect backlog

The queue the night shift reads. Ordered: the top unblocked ticket is the next one
worked. Each ticket owns a **done when** that is checkable, not a vibe.

**Status keys:** `ready` · `blocked` · `in-progress` · `proposed` (awaiting review) · `done`
**Gate:** nothing marked `human` may be started by an agent.

---

## E0 — Make autonomous work safe *(blocks everything in E8)*

### T0.1 — Put the front end under version control · `done` (2026-08-04)
I had this wrong: the repo always existed — `moose-scout` IS
github.com/meadowlarkjoe/transect, and `app/` is the tracked front end. What had
happened is worse and less obvious: I was editing and deploying from a LOOSE COPY
at `~/transect-app` that was not the repo, so the live site ran a full day ahead of
git (52 KB of `app.js` existing nowhere but one directory and Cloudflare).
Resolved: the copy was synced into `app/` and committed, and `deploy.sh` now refuses
to run outside the repo or with a dirty tree, so live cannot outrun git silently
again. `~/transect-app` is marked stale.

### T0.2 — Make the test suite runnable and real · `ready`
`tests/` has one file and `pytest` is not installed in the local env, so there is no
gate on any change.
**Done when:** `pytest` runs green from a documented command; a smoke test asserts a
cached Fire Lake contract loads and has non-empty `areas`, `waypoints`, `legend`.

### T0.3 — Contract snapshot harness · `ready`  *(blocked by T0.2)*
The refactors in E1–E4 must not change output. Needs a cheap before/after diff.
**Done when:** one command runs synth+transect on cached Fire Lake rasters and diffs
the resulting `transect.json` against a committed snapshot, reporting any field change.

---

## E1 — Contract-driven legend *(unblocks the whole ladder)*

### T1.1 — Emit `legend[]` in the contract · `ready`
`config/output_legend.yaml` exists but is used only for GPX/KML export; it never
reaches the app. The client's 22 `LAYERS` rows are hardcoded, including moose-specific
prose ("Strongest single predictor here").
**Done when:** `transect.json` carries `legend: [{key, group, name, note, hex, icon,
kind, edge, basis}]` covering every layer the app draws today, sourced from config
rather than literals.

### T1.2 — Client builds `LAYERS` from `DOC.legend` · `blocked` *(by T1.1, T0.1)*
**Done when:** deleting the hardcoded array leaves Fire Lake rendering identically,
and a synthetic non-moose contract renders a different legend with no client change.

### T1.3 — Layer groups become data · `blocked` *(by T1.1)*
`MODEL ZONES / SITES & FEATURES / ACCESS & HYDRO` are hardcoded. A goat hunt needs
*ESCAPE TERRAIN*.
**Done when:** group names and order come from the contract.

### T1.4 — Move species prose into species config · `blocked` *(by T1.1)*
**Done when:** no species-specific sentence remains in `app.js`.

---

## E2 — Region resolver + data-source registry

### T2.1 — Make `region_profile` real · `ready`
Declared at `config.py:122`, read by nothing.
**Done when:** `config/regions/quebec_boreal.yaml` exists describing today's behaviour,
a resolver maps AOI centroid → region, and Fire Lake output is unchanged (T0.3 proves it).

### T2.2 — Derive `working_crs` from region · `blocked` *(by T2.1)*
`EPSG:32198` (Québec Lambert) is the global default in `model.yaml`.
**Done when:** CRS comes from the region; an AOI outside Québec gets a sane UTM zone.

### T2.3 — Coverage manifest in the contract · `blocked` *(by T2.1)*
The honesty constraint: a region missing écoforestière must say so, not look identical.
**Done when:** every run emits `coverage: {source: native|fallback|absent}` and the
confidence score demonstrably drops when sources are absent.

### T2.4 — Global baseline adapter · `blocked` *(by T2.1, T2.3)*
**Done when:** an AOI with no regional adapter still produces a plan from Copernicus
DEM + OSM + ESA WorldCover, labelled `fallback` throughout.

---

## E3 — Species model plug-ins

### T3.1 — Species declares its site taxonomy · `blocked` *(by T1.1)*
`synth.py` hardcodes `rut_calling` / `thermal_refuge` / `saline_blind` / `glassing`.
**Done when:** site types come from the species config; adding one needs no `synth.py` edit.

### T3.2 — Registered derived-layer builders · `blocked` *(by T3.1)*
Burn-regen age banding is a *moose* predictor, not a universal one.
**Done when:** a species config names which derived layers to build; burn-regen is
registered as one of them rather than being unconditional.

### T3.3 — Exercise `whitetail_deer.yaml` end to end · `blocked` *(by T3.1)*
It is drafted and has never been run. Unexercised config is not evidence of generality.
**Done when:** a whitetail run on a Québec AOI completes and its legend differs
appropriately from moose.

---

## E4 — Legal / tenure adapters

### T4.1 — Extract the Québec legal adapter · `ready`
`legal.py` is the most province-locked file (14 Québec hits).
**Done when:** an adapter interface exists, Québec is one implementation, and Fire Lake
legal output is unchanged.

### T4.2 — `UNRESOLVED` is loud, never silent · `blocked` *(by T4.1)*
**Done when:** an out-of-jurisdiction AOI returns `UNRESOLVED` and the app shows an
unmissable banner; it must never imply legality it did not verify.

---

## E5 — Research pipeline

### T5.1 — First autonomous research pass: moose × Québec (beyond Fire Lake) · `ready`
Extends 0.1.0's Fire Lake findings to provincial scope. Écoforestière coverage stops
near 52°N — the profile must say what changes north of it.
**Done when:** `docs/proposals/` holds a cited species×region profile with gaps declared.

### T5.2 — Data-source sweep: Ontario · `ready`
First province outside Québec. Proves the E2 abstraction against real, different data.
**Done when:** a verified source table exists with test-bbox results for every layer.

### T5.3 — Data-source sweep: Maine / New Hampshire · `ready`
First US jurisdiction; no écoforestière analogue.
**Done when:** as T5.2, plus an explicit note on what replaces stand-level forestry.

---

## E6 — Validation harness *(credibility gate)*

### T6.1 — Null-model benchmark · `ready`
The model is currently unfalsifiable. This is the highest-value ticket in the backlog
and the one most easily deferred forever.
**Done when:** a harness scores the model against (a) distance-to-road and (b) random
points in huntable ground, and reports whether it beats them at Fire Lake.

### T6.2 — Backtest against harvest density · `blocked` *(by T6.1)*
**Done when:** modelled huntability correlates (or demonstrably does not) with published
zone harvest density, and the result is reported either way.

---

## E7 — Mobile *(GATED — human)*

All of M1–M8 in `docs/roadmap.md` are `blocked` pending a mobile design from Joe.
**Also blocked on a product answer:** field tool (offline, gloves, sunlight) or couch
tool (reviewing a desk-built plan)? These imply different builds.

---

## E8 — Autonomous infrastructure

### T8.1 — Night-shift workflow · `blocked` *(by T0.1, T0.2)*
**Done when:** one command picks the top unblocked ticket, runs engineer → reviewer,
and leaves a branch plus `docs/proposals/<ticket>.md`. It must refuse to run while
T0.1/T0.2 are open.

### T8.2 — Schedule it · `blocked` *(by T8.1)* · `human`
Cadence and scheduling are Joe's call.
