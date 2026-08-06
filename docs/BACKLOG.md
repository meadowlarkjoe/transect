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

### T0.2 — Make the test suite runnable and real · `done` (2026-08-05)
99 tests run from `docker run --rm --entrypoint python -v "$PWD":/app -w /app
moose-scout:local -m pytest tests/ -q`. Two need node (absent in the image, pass on the
host); three are cross-test contamination in `test_synth_smoke` — see T0.4.
`tests/` has one file and `pytest` is not installed in the local env, so there is no
gate on any change.
**Done when:** `pytest` runs green from a documented command; a smoke test asserts a
cached Fire Lake contract loads and has non-empty `areas`, `waypoints`, `legend`.

### T0.3 — Contract snapshot harness · `ready`  *(blocked by T0.2)*
The refactors in E1–E4 must not change output. Needs a cheap before/after diff.
**Done when:** one command runs synth+transect on cached Fire Lake rasters and diffs
the resulting `transect.json` against a committed snapshot, reporting any field change.

### T0.4 — Isolate the tests that contaminate each other · `ready`
`test_synth_smoke` passes when its file runs alone (~95 s, a real pipeline) and fails in
~5 s in a full-suite run with `RasterioIOError: .../fire_lake/huntability.tif`. An
earlier test leaves a cache dir or env var behind. It currently HIDES real failures:
those three report as failing whatever the code does, so nobody can tell a genuine synth
regression from the contamination.
**Done when:** the full-suite result for those three matches the per-file result, and a
deliberately broken synth makes them fail for the right reason.

---

## E1 — Contract-driven legend *(unblocks the whole ladder)*

### T1.1 — Emit `legend[]` in the contract · `done` (2026-08-04, 7ca39c5)
`config/output_legend.yaml` exists but is used only for GPX/KML export; it never
reaches the app. The client's 22 `LAYERS` rows are hardcoded, including moose-specific
prose ("Strongest single predictor here").
**Done when:** `transect.json` carries `legend: [{key, group, name, note, hex, icon,
kind, edge, basis}]` covering every layer the app draws today, sourced from config
rather than literals.

### T1.2 — Client builds `LAYERS` from `DOC.legend` · `done` (2026-08-04)
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

### T2.1 — Make `region_profile` real · `done` (2026-08-04, 8d5090c)
Declared at `config.py:122`, read by nothing.
**Done when:** `config/regions/quebec_boreal.yaml` exists describing today's behaviour,
a resolver maps AOI centroid → region, and Fire Lake output is unchanged (T0.3 proves it).

### T2.2 — Derive `working_crs` from region · `blocked` *(by T2.1)*
`EPSG:32198` (Québec Lambert) is the global default in `model.yaml`.
**Done when:** CRS comes from the region; an AOI outside Québec gets a sane UTM zone.

### T2.3 — Coverage manifest in the contract · `done` (2026-08-04)
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

## E6 — Validation harness *(credibility gate — NOW LOAD-BEARING)*

**Status changed 2026-08-06.** This used to be about credibility. It is now blocking
correctness. The rev-21 browse rebuild moved the whole huntability scale, and every
constant downstream of it is ABSOLUTE and was calibrated against the old one:
`min_huntability`, `min_area_km2`, and the extent bars added the same day. Re-deriving
one of them by hand achieved nothing, which is exactly the guesswork this epic replaces.
It is what decides whether "1 focus area on 28 km2 of reachable ground" is the right
answer or an artefact.

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

---

## E9 — Field reports *(from real hunts; ordered by how wrong the answer is)*

Everything here came from using the thing. Ordered by the honest severity rule: a
SILENTLY WRONG answer outranks a missing one, which outranks an ugly one.

### T9.1 — Known sites 2–4 never reach the engine · `done` (2026-08-06)
`aoi.sites` is validated in `api.py`, threaded through `config.py`, echoed into
`doc.meta` — and read by NOTHING in the analysis. `sites[0]` is only the AOI centre; the
rest are drawn as client-side rings and discarded. Setup promises "up to 4 sites — each
gets its own analysis, ranked against the others".
Evidenced: two sites 50 km apart, `meta.radius_km` 9, both returned areas within 3 km of
site 1; site 2 produced nothing and said nothing. Worse than empty — the "Area 2" tab
reads as the second SITE but is a second focus area beside the first.
**Done when:** a 2-site request returns a result per site, each with its own areas/sites/
routes and a rank across sites; a site outside the box is either analysed or refused
loudly; and a test fails if `sites` has no consumer in the analysis path.
**Note:** acquire is shared via the geocache (~4 s warm), so the cost is the compute
stages per site, not per-site downloads. Build the N-runs harness here — T9.2 is then
nearly free.

### T9.2 — Bow vs rifle: multiple date windows compared · `done` (2026-08-06)
Not a prose change: the habitat surface is phase-weighted (`habitat_phase.tif`,
cow-weighted at peak rut vs feed-weighted post-rut), so mid-Sept bow and Oct rifle are
different MODEL RUNS with different site mixes and stands.
**Done when:** Setup accepts N date windows, the brief carries a per-window verdict plus
a comparison, and acquire runs once for all of them.

### T9.3 — Camp-hunt brief answers the right question · `done` (2026-08-06)
For a fixed camp the brief still ranks areas against each other. The areas around a
cabin are COMPLEMENTS, not competitors. The question is "how good is hunting this cabin,
and which area on which conditions".
**Done when:** a fixed-camp brief leads with a verdict on the CAMP (habitat + access
rolled up across everything reachable, with its caveats), then a rotation keyed to
wind/temperature/rut phase. `optimal_wind` per waypoint and the per-day weather already
exist — this is a join, not new modelling.
**Also worth surfacing:** which stands are wind-ROBUST across many directions. For a
cabin you hunt every year, a blind that only works on a north wind is worth far less
than one that works on four. Nothing scores this today.

### T9.4 — Stack a hover card per feature under the cursor · `done` (2026-08-06)
IDENTIFY shows the first match only, so reading a spot means toggling layers on and off.
**Done when:** hovering ground covered by several layers shows a card per feature, in the
existing priority order.

### T9.5 — See all your plans on one map · `done` (2026-08-06)
**Done when:** the dashboard can draw every saved plan's areas at once, and the app can
show other plans as a background layer.

### T9.6 — Share a plan by email; attribute drawings · `done` (2026-08-06)
Decisions taken: CO-EDIT, and invites to unregistered addresses wait and resolve on
sign-up. Shares are keyed by email so that resolution needs no reconciliation step.
Owner-only for re-sharing and delete. Co-edit collisions are reported via a version
check, not merged. No email is sent by the app.
No sharing primitive exists: every plan query filters on `uid`, and drawings live inside
the plan blob with no author.
**Decisions first (Joe):** read-only vs co-edit for a shared plan — recommend read-only,
co-edit needs conflict handling the blob cannot express; and whether sharing to an email
with no account holds a pending invite — recommend yes, a hunting party is exactly the
case where the other person has not signed up.
**Done when:** a `plan_shares` table + endpoints, `GET /plans` returns owned + shared
with an explicit role, drawings carry `author_uid`/`author_email` shown in the panel and
the hover tooltip. Do NOT send email from the app without explicit approval.

### T9.7 — Download Brief PDF · `done` (2026-08-06)
Written brief plus per-layer map plates (overview, browse/feeding, thermal refuge,
topography) each with an explainer of what it means and what its limits are.
**Done when:** one button produces a PDF whose plates match what the app draws — drive
the existing MapLibre map offscreen rather than re-implementing symbology server-side —
with scale bar, north arrow and datum, because this is the artifact that goes in a pack
where there is no cell service.

### T9.8 — Abri sommaire / baux de villégiature · `ready`  ← NEXT
A leased rustic shelter on public land. NOT a legal barrier — the land stays huntable —
so it must never gate access. It is a PRESSURE signal: someone hunts that ground every
season, and it is secondary evidence the ground is usable.
Sources checked today: the queryable one
(`services7.arcgis.com/.../LOC_LAS_regroupe_19juin2023`, 3160 pts, `Type_de_ba` =
"Bail d'abri sommaire" | "Bail de villegiature") is ABITIBI-ONLY and a June-2023
snapshot; the official province-wide one
(`Territoire/Droits_fonciers_WMS`, layer 0 "Droits fonciers ponctuels") does NOT support
query — WMS export only.
**Done when:** the official data is loaded via the Donnees Quebec download with a
coverage envelope declared in the region profile, cross-checked against the regional
service over Abitibi, and wired as a proximity term beside `dist_road` in hunter
pressure — never as a barrier.

### T9.9 — Browse sub-layer display · `done` (2026-08-06)
Stipple in a green ramp, indented under Browse / feeding, denser dots; IDENTIFY asks the
specific layers before the blanket one; cut zones carry their real years.

### T9.10 — Higher-resolution terrain · `ready`
`acquire/dem.py` pulls MRDEM-30 (NRCan, 30 m) and every terrain product derives from it,
including funnel neck widths and the glassing prominence term. A 30 m grid cannot resolve
a 100 m neck or a small knob — which is what the relief basemap shows and the model does
not. Quebec publishes 1 m LiDAR DTM over much of the managed south (the same ground where
ecoforestiere is strongest); NRCan HRDEM is the alternative.
**Done when:** the finer DTM is read at native resolution and aggregated in SOURCE space
(a 1 m DTM over a 9 km box is ~81 M cells — do not warp it whole), with a declared
coverage envelope and an honest fallback to MRDEM-30, and the new water detail is fed to
the funnel barrier AND the display together (the rev-12 lesson).
