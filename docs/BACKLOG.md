# Transect backlog

**THIS LIST IS THE QUEUE.** One ordering, here, and the epic sections below are reference
detail for the tickets named in it — not a second priority scheme. If a ticket is not in
this list it is not queued; if the order is wrong, change it HERE. Each ticket owns a
**done when** that is checkable, not a vibe.

**How it is ordered.** The field-report rule, applied to everything: a SILENTLY WRONG
answer outranks a MISSING one, which outranks an UGLY one. A hunter who is told the
wrong thing confidently has been actively harmed; one who is told nothing has only been
underserved. Within a band, cheaper first.

**Status keys:** `ready` · `blocked` · `in-progress` · `proposed` (awaiting review) · `done`
**Gate:** nothing marked `human` may be started by an agent.

---

## The queue

### Band 1 — SILENTLY WRONG (the product states something untrue)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 1 | **T10.16** Sentinel window frozen in 2023–24 | Every run's browse surface is built on 2-year-old imagery. No caveat anywhere. Cuts and burns since Sept 2024 are invisible. |
| 2 | **T10.1** Multi-window brief reports window 1 for everything | A bow hunter reads rifle-window advice with no way to tell. The engine already knows better — only the readout lies. |
| 3 | **T10.15** Hunt leg bushwhacks past a mapped trail | Draws a line to a place it then refuses to walk to. Diagnosed: one file missing from the walk-cost surface. |
| 4 | **T10.2** Method of take not modelled per window | Bow stands placed on rifle logic. Makes T10.1 half a fix — right labels, wrong stands. |
| 5 | **T10.18** A funnel should connect two places a moose wants | T10.17 made necks prove they are bottlenecks. A bottleneck between two barren outcrops is still a bad place to sit. |
| 6 | **T6.1** Null-model benchmark | The model is unfalsifiable, and rev 21 moved the huntability scale under constants that are still absolute. Load-bearing since 2026-08-06. |
| 7 | **T0.4** Tests that contaminate each other | Three synth tests fail regardless of the code, so a real regression is indistinguishable from the contamination. |

### Band 2 — MISSING (a real gap you can see)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 7 | **T10.6** PDF brief renders no analysis | Shipped in T9.7 on the strength of the plates existing; nobody checked what was on them. Basemap only. |
| 8 | **T10.5** Camp icon regressed to a numbered circle | Collateral from T9.3/T9.1. A camp is not a site index. |
| 9 | **T10.11 + T10.10** Pitch does not enable terrain; the SAT/2D chip is a constant | Two halves of one complaint, both small, both confirmed in the source. |
| 10 | **T9.10b** Decide the fine-grid neck detector | Built and gated off in rev 22. Needs a real A/B, not a permanent flag. |
| 11 | **T10.3** Which window an area belongs to is invisible | `areas[].window` already exists — this is display only. |
| 12 | **T10.4** Legend names data sources, not the animal | Browse and water both. The engine's source ranking is being handed to the reader to interpret. |
| 13 | **T10.9** Hover tooltip and click card disagree | Same feature, two panels, and the richer one is the one you have to discover. Settle with T10.4. |
| 14 | **T10.12** Relief mislabelled; LiDAR now deliverable | The row names the wrong source. HRDEM hillshade became real in T9.10. |
| 15 | **T10.8** Draw the area to analyse | Needs padded-box analysis + clipped output, which is also what retires the 5 km floor. |
| 16 | **T10.13** Imagery season picker | The stale-window half is T10.16 above; this is the control and the high-res leaf-off source. |

### Band 3 — UGLY (it works and reads badly)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 17 | **T10.7** PDF layout is browser print chrome | Timestamp, "Page 1 of 11" and the raw URL on every page. |
| 18 | **T10.14** Basemap rows are CSS gradients, not previews | A grey ramp standing in for hillshade tells you nothing about your ground. |

### Band 4 — PLATFORM (nobody sees it; it decides how fast the rest goes)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 19 | **T0.3** Contract snapshot harness | Every refactor below needs a before/after diff to be safe. |
| 20 | **#84** Workers in their own container | Root cause of both deploy jams; a run still dies with the API. |
| 21 | **T4.1** Extract the Québec legal adapter | The most province-locked file. Blocks T4.2. |
| 22 | **T3.1 → T3.2 → T3.3** Species plug-ins | `whitetail_deer.yaml` is drafted and has never been run. |
| 23 | **T1.3 · T1.4 · T2.2 · T2.4** Generality | Layer groups, species prose, CRS, global fallback — all now unblocked. |
| 24 | **T6.2** Backtest against harvest density | Blocked by T6.1. |
| 25 | **T5.1 · T5.2 · T5.3** Research sweeps | Québec-wide, Ontario, Maine/NH. |
| 26 | **T8.1 → T8.2** Autonomous night shift | T8.2 is `human` — cadence is Joe's call. |
| 27 | **E7** Mobile | `human` — gated on a design AND on the field-vs-couch product answer. |

---

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

### T0.3 — Contract snapshot harness · `ready`
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

### T1.3 — Layer groups become data · `ready`
`MODEL ZONES / SITES & FEATURES / ACCESS & HYDRO` are hardcoded. A goat hunt needs
*ESCAPE TERRAIN*.
**Done when:** group names and order come from the contract.

### T1.4 — Move species prose into species config · `ready`
**Done when:** no species-specific sentence remains in `app.js`.

---

## E2 — Region resolver + data-source registry

### T2.1 — Make `region_profile` real · `done` (2026-08-04, 8d5090c)
Declared at `config.py:122`, read by nothing.
**Done when:** `config/regions/quebec_boreal.yaml` exists describing today's behaviour,
a resolver maps AOI centroid → region, and Fire Lake output is unchanged (T0.3 proves it).

### T2.2 — Derive `working_crs` from region · `ready`
`EPSG:32198` (Québec Lambert) is the global default in `model.yaml`.
**Done when:** CRS comes from the region; an AOI outside Québec gets a sane UTM zone.

### T2.3 — Coverage manifest in the contract · `done` (2026-08-04)
The honesty constraint: a region missing écoforestière must say so, not look identical.
**Done when:** every run emits `coverage: {source: native|fallback|absent}` and the
confidence score demonstrably drops when sources are absent.

### T2.4 — Global baseline adapter · `ready`
**Done when:** an AOI with no regional adapter still produces a plan from Copernicus
DEM + OSM + ESA WorldCover, labelled `fallback` throughout.

---

## E3 — Species model plug-ins

### T3.1 — Species declares its site taxonomy · `ready`
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

### T8.1 — Night-shift workflow · `ready`
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

### T9.8 — Abri sommaire / baux de villégiature · `done` (2026-08-07)
A leased rustic shelter on public land. NOT a legal barrier — the land stays huntable —
so it never gates access. It is a PRESSURE signal: someone hunts that ground every
season, and it is secondary evidence the ground is usable.
**Source resolved.** The regional queryable service the earlier pass found
(`services7.arcgis.com/.../LOC_LAS_regroupe_19juin2023`, Abitibi-only, June-2023) is
GONE — the whole ArcGIS org returns `400 Invalid URL` as of 2026-08-07, so the
cross-check named here is not possible and is also not needed: it was only ever a
regional proxy for the official layer, which we now hold directly. Données Québec
publishes that layer as a plain SHP download (`couche-des-droits-fonciers-baux`,
4 MB) — province-wide, all 17 admin regions, refreshed 2026-06-29, 48,004 point leases
+ 1,029 polygon leases. The WMS is still export-only and is not used.
**Classified, not swallowed whole.** 38 lease purposes, of which 34 are wind turbines,
telecom masts, billboards and tailings ponds. Four are somebody occupying the ground:
abri sommaire (9,843), villégiature (32,384), pourvoirie sans droits exclusifs (524 —
which also fills a known TFS gap, since tenure.py only sees outfitters WITH exclusive
rights), résidence principale (251).
**Measured:** Rouyn 8 km box → 86 abris + 3 cottages (backcountry hunting shelters);
Saguenay 25 km → 321 cottages, 0 abris (lake cottage country); Fire Lake 35 km → 135
leases of which 36 are infrastructure and dropped. The filter earns its keep.
**Expired leases are kept on purpose.** 8,390 of 48,004 have lapsed on paper, but a
lapsed lease does not demolish the cabin and the extract lags annual renewals. The
count is reported in the sidecar rather than silently applied.

### T9.9 — Browse sub-layer display · `done` (2026-08-06)
Stipple in a green ramp, indented under Browse / feeding, denser dots; IDENTIFY asks the
specific layers before the blanket one; cut zones carry their real years.

### T9.10 — Higher-resolution terrain · `done` (2026-08-07)
The premise was half right, and the half that was wrong is the point.

**The 30 m SOURCE was not the limit — the 40 m ANALYSIS GRID was.** Swapping MRDEM-30
for 1 m LiDAR under a fixed 40 m grid moved mean slope by 1.2% and mean |TPI| by 1.4%.
Nothing. Measuring the same LiDAR at 10 m instead doubled the peak slope inside a 40 m
cell, raised peak |TPI| by half, and took ground with |TPI| > 6 m from 62 to 82 km².
So the two ship together: a fine grid over MRDEM-30 would be interpolation rather than
information, and finer data under a coarse grid is a no-op.

**Necks were worse than coarse — they were censored.** On a 40 m grid the tightest neck
the detector could report was 113 m, and a real run returned four funnels all reporting
*exactly* 113 m: the quantization floor, not the terrain. Sub-100 m necks came back as
exactly zero on every box tested. Rasterizing water with `all_touched` (required, or
thin water vanishes) grows each shore by up to a cell, so a 100 m neck arrived as 0–1
cells. The same box now reports necks at 48, 53, 80, 93 m.

**The trap, and why total funnel area did not inflate.** Two constants in the detector
were in CELLS — the medial-axis test `size=3` and the off-barrier floor `db > res` — so
the detector asked a different question at every resolution. Left alone, moving to a
fine grid inflated total neck area 3.5×: an apparent improvement that was pure grid
artefact. In metres (120 m, 20 m) total neck area is flat-to-slightly-lower
(4.80 → 3.83 km², 6.84 → 5.94 km²) while sub-150 m neck ground went up 3–4×. That is
the shape a real resolution fix should have.

**Delivered:** HRDEM mosaic read decimated so GDAL serves it from the COG overviews
(aggregation in SOURCE space, never a whole-tile warp), nodata contamination inverted
exactly from a matching `read_masks` fraction, void-filled against MRDEM-30 by a
smoothed local delta (measured bias between the two products: 0.05 m, so no datum step
to correct), `dem_source.json` carrying the measured coverage into the manifest, and a
`prominence.tif` peak-per-cell layer that glassing reads — with its divisor moved 30 → 45
so the resolution upgrade does not silently re-saturate the term audit #56 unsaturated.
Coverage measured: Rouyn 92.7–99.99%, Fire Lake 41–54%.

**Left undone:** Québec's own 1 m LiDAR DTM (Données Québec, per-feuillet tiles) is not
wired — HRDEM covers the same managed south and is a single national mosaic. Worth
revisiting only if a box lands in an HRDEM gap that Québec has flown.

---

## E10 — What the second real multi-window run showed (2026-08-07)

From Joe running a two-window (rifle + bow) analysis on the live engine at
47.967, -77.809 and reading the exported PDF. Ordered by the honest severity rule: a
SILENTLY WRONG answer outranks a missing one, which outranks an ugly one.

The through-line in three of these: **T9.2 shipped the model change and not the
readout.** `_merge` really does run every (site × window) as its own analysis and tag
every area with its window — that part is tested and correct. But the BRIEF, the map and
the PDF header all still speak as if there were one window. So the engine knows the
difference and the product does not, which is the worst possible split: it looks like
one answer and is secretly two.

### T10.1 — A multi-window brief reports the first window's analysis for everything · `ready`
Reported: "It gave me two focus areas. They overlap... the brief for both areas provides
its analysis based on the first date range. The only place where the different time
windows are compared is at the top."
Confirmed in the export: the header reads `dates 2026-10-10 → 2026-10-25` — one window —
on a run that had two, and "Your dates & the rut" reasons from that one window only.
This is SILENTLY WRONG, not merely thin: a bow hunter reads post-rut advice written for
the rifle window and has no way to tell.
**Done when:** each window gets its own complete briefing — its own focus areas,
strategy, stands and rut read — and the comparison between windows is an ADDITIONAL
section, not a substitute for either. The per-window verdict block from T9.2 stays as
the lead.

### T10.2 — Method of take is not modelled per window · `ready`
Reported: "shooting locations for a bow (max 30/40yds) are going to be different for
those with a rifle (longer range, need visibility more than proximity — can reach out
further / less concern about local scent as you wont be as close)."
Today the weapon is not an input at all, so both windows get identically-placed stands.
That makes T10.1 half a fix: separate briefs that still recommend the same 200 m
sightline to a bow hunter are still the wrong answer, just labelled correctly.
**Done when:** a window carries its method of take; shooter placement, the scent-wick
arc and the glassing/visibility weighting all read it. A bow window wants proximity,
cover and wind discipline; a rifle window wants sightline.

### T10.3 — Which window an area belongs to is invisible on the map · `ready`
Reported: "They overlap. Im guessing these are different for each season, but thats not
clear on the map. Maybe... a slider or multi select on the map that allows you to either
see analysis for all dates vs analysis for a single date range."
`areas[].window` already exists (T9.2) — this is a display control, not new modelling.
**Done when:** with more than one window the map offers all-windows vs a single window,
and an area always says which window it came from.

### T10.4 — The legend describes DATA SOURCES where it should describe the ANIMAL · `ready`
Two reports, one principle. On browse: "Recent cuts are under browse/feeding but also
their own thing... I dont care about seeing them all individually to this level. Im more
curious about the TYPE of browse (aquatic vegetation, regen (prime), regen (new), regen
(closing), specific species of vegetation that moose like)... I want the legend to show
things that hunters actually care about and not rely on them to have to evaluate the
relative quality of a data source. **this is true for everything we show, not just
browse/feeding.**" On water: "Water is a parent class. Inside that should be beaver
ponds, wetlands, rivers&lakes... Duplication should be eliminated. Data of higher
specificity (ex beaver pond) should outrank general data (ex. waterbody). Same logic for
feeding / browse."

**The principle, stated once:** a layer group is named for the thing on the ground; its
sublayers are KINDS of that thing, not the sources that found it; and where two sources
describe the same ground the more specific one wins and the general one does not draw
underneath it. Ranking sources is the model's job — rev 21 already built exactly that
ordering for browse (dated cut > dated burn > surveyed stand > satellite) and then
handed the result to the reader to interpret, which is the error.

Today's legend fails this twice over. Browse/feeding exposes four rows named "from dated
cuts", "from dated burns", "from the stand map", "from satellite land cover" — pure
provenance — while "Recent cuts" ALSO stands alone as its own row, so the same cutblock
is drawn and counted twice. Water has no parent at all: Rivers & lakes, Wetlands and
Beaver ponds are three unrelated rows in ACCESS & HYDRO, and a beaver flowage is drawn
over the waterbody that already covers it.

**Done when:**
* **Water** is one parent with sublayers — beaver ponds · wetlands · rivers & lakes —
  each independently toggleable, and a cell is drawn by its MOST SPECIFIC layer only
  (a beaver pond is not also a generic waterbody).
* **Browse/feeding** sublayers are named by what the animal eats and what stage it is
  in: aquatic vegetation · regen new / prime / closing in · named species where the
  stand map has them. "Recent cuts" stops being a second top-level row.
* **Provenance moves to the hover card**, where T9.4 already stacks a card per feature —
  the honest place for "this came from a surveyed cut with a year on it".
* The same test is applied to every remaining group: does this row name something a
  hunter cares about, or something the engine cares about?

### T10.5 — The camp icon regressed to a numbered circle · `ready`
Reported: "For a camp style hunt we use to show a CAMP icon with a cabin at the camp
location. Now it just shows a number 1 in a circle."
Almost certainly collateral from T9.3 (`camp_plan`) or T9.1 (per-site numbering), where
a fixed camp started being rendered as a SITE index. Visible in the screenshot: a plain
amber "1" where the tent/cabin pin used to be.
**Done when:** a fixed camp draws its own icon, and site numbering never claims a camp.

### T10.6 — The PDF brief renders no analysis · `ready`
Reported: "None of the analysis / polygons / waypoints / etc. render on the PDF."
Confirmed: each of the five plate pages carries exactly one image — the basemap — so the
offscreen map T9.7 drives is painting terrain and none of the plan layers. T9.7 was
declared done on the strength of the plates existing; nobody checked what was ON them.
That is the exact failure mode the "verify the artifact" rule exists for, repeated.
**Done when:** every plate shows the same features the app draws for that layer, and a
test fails if a plate comes back with no plan geometry on it.

### T10.7 — PDF layout is browser print chrome · `ready`
Reported: "The design/layout of the PDF needs to be polished."
Every page carries `2026-08-07, 8:47 AM`, `Page 1 of 11` and the raw plan URL — the
print-to-PDF headers and footers, not a designed page. That was the accepted cost of
choosing print-to-PDF over a vendored library (T9.7); it is now the visible cost.
**Done when:** the export reads as a document — its own header/footer, page numbering
and typography — with the browser's chrome suppressed.

### T10.8 — Draw the area to analyse, instead of only a radius · `ready`
Asked: "right now we only do analysis by radius. and the minimum area is 5km. For a
hunting camp we are currently looking at buying, that area is too big. I have a smaller,
specific area that I want to analyze... have it default to search radius, but also give
people the option to draw an area for analysis using our area draw tool."

**Feasible, and cheaper than it looks.** Everything downstream already runs on a
rectangle: `target_grid` builds a tight axis-aligned raster from `aoi.bbox_wgs84()`, and
nothing in the engine knows or cares that the rectangle came from a radius. A drawn
polygon supplies the same two things — a bbox and a centre.

**THE PART THAT MATTERS, and the reason the 5 km floor exists.** The engine cannot
answer about a parcel using only the parcel. `dist_road` measures to a road that is
usually OUTSIDE the boundary; a land-bridge funnel needs the lakes on BOTH sides of the
neck; TPI uses a 500 m window, the pinch test a 600 m one, and pressure decays over
1.5 km. Analysing a tight polygon alone would report "no access, no funnels" about
ground that has both. So: **analyse a PADDED bbox (~2–3 km beyond the drawing) and clip
the OUTPUT to the polygon.** Focus areas, stands and routes get intersected with the
drawn shape; routes are allowed to leave it, because the road you drive in on does.
With the padding restoring the context, the 5 km minimum can go — it was protecting
against exactly this failure.

**Done when:** setup offers radius (default) or draw-an-area; a drawn AOI stores its
ring, analyses a padded box, and clips reported features to the ring; the brief says
which mode produced it and how much padding was used; and the geocache keys on the
PADDED bbox so redrawing a similar parcel still hits a warm cache.

### T10.9 — Hover tooltip and the click card are two different explanations · `ready`
Reported: "the explainability layer exists but it only appears on click, separate from
tooltip. these should be combined."
Visible in the screenshot: the hover tooltip says "Browse / feeding · mostly the
satellite land cover (100%) · sources partly agree · score 0.562 · 5.3 km²" while a
separate click popup says "Riparian / wetland browse · 5.3 km² · Alder edges plus
emergent/submergent aquatics · When: dawn & dusk... Score: 0.562 · Why: mostly the
satellite land cover". Same feature, same numbers, two panels, and the RICHER one (the
When/Why) is the one you have to discover by clicking.
Related to T10.4: once provenance moves off the legend it belongs here, so these two
should be settled together.
**Done when:** one panel per feature carries the whole explanation — what it is, when to
hunt it, the score and where the score came from — and hovering shows it. Click should
pin it, not reveal different content.

### T10.10 — The SAT/2D chip is hardcoded HTML and never updates · `ready`
Reported: "the basemap icon still shows 2D... Even if i manually activate, the basemap
pill doesnt update."
Confirmed, and it is literal: `mc.innerHTML = ... <b>SAT</b><i>2D</i>` — a constant
string written once at map setup. It is wired to nothing. So it says SAT while you are
on Relief, and 2D while you are pitched to 60°. `syncCompass` already listens on
`rotate`/`pitch` right beside it; this needs the same treatment.
**Done when:** the chip reads the live basemap and the live pitch/terrain state, and a
test fails if either is rendered from a constant.

### T10.11 — Pitching the camera does not turn terrain on · `ready`
Reported: "If i hold right and move my mouse click i can enter 3D mode, but... the 3D
terrain mode isnt activated. Terrain exageration doesnt work until that mode is active."
Two independent things wear the name "3D". The map is created with `maxPitch:80`, so
right-drag tilts the CAMERA — but `map.setTerrain({source:'dem'})` is only ever called
from the `#terr3d` checkbox handler, and the exaggeration slider is guarded by
`if(terrOn)`. Tilt without the checkbox gives a pitched FLAT map and a dead slider,
which is exactly the "3D that isn't 3D" being described.
**Done when:** pitching past a threshold enables terrain (and the chip agrees), the
exaggeration slider works whenever the map is pitched, and dropping back to 0° releases
terrain. One state, not two.

### T10.12 — Relief is mislabelled, and LiDAR is now genuinely available · `ready`
Asked: "Is releif and Lidar not the same? Should we remove lidar from below?"
**No, and no — keep it.** They are different by ~30x and the panel is currently lying
about one of them:
* **Relief** is labelled `CDEM HILLSHADE`. It is not CDEM. It is
  `server.arcgisonline.com/.../Elevation/World_Hillshade` — Esri's global hillshade,
  mixed-resolution. It is also capped at z14, and not by Esri: the ceiling comes from
  the terrarium DEM this app declares for `setTerrain`. So the row states the wrong
  source AND gives no hint why it goes soft before the imagery does.
* **LiDAR (HD topo)** would be 1 m bare earth. As of T9.10 we can actually deliver it:
  the HRDEM mosaic publishes `<tile>-mosaic-1m-dtm_hillshade.tif` beside the DTM we now
  read, and `dem_source.json` already records the measured coverage fraction for the
  box. "NOT AVAILABLE FOR THIS AOI" can stop being a placeholder and become a real
  per-AOI answer — true over Rouyn (92.7%), honest over the far north.
The COGs are not tiles, so serving them means either a tile endpoint or — cheaper, and
consistent with how every other engine raster reaches the app — rendering an AOI-sized
hillshade at analysis time.
**Done when:** Relief states its real source and why it stops at z14; the LiDAR row is
enabled exactly when HRDEM covers the box, and says what fraction.

### T10.13 — Leaf-off and "recent imagery" are placeholders; the season picker was never built · `ready`
Asked: "Can we find a source for leaf off imagery?... Same with recent imagery. We
talked about letting the user pick what time of year / map they are using but i dont
know if that ever got added."
**It was never added** — there is no season or imagery control anywhere in setup or the
app. And checking turned up something worse than a missing feature:
`acquire/sentinel.py` hardcodes `datetime="2023-07-01/2024-09-15"`. That window is
~2 years stale, so the NDVI feeding the browse surface is built from 2023–24 imagery
regardless of when you run it. That is a MODEL input going quietly out of date, not a
basemap nicety, and it outranks the rest of this item.

Sources that actually exist, cheapest first:
* **Leaf-off, 10 m — nearly free.** We already pull Sentinel-2. An April or late-October
  low-cloud composite is the same code with a different window. Coarse, but it is the
  only leaf-off that costs nothing.
* **Bare earth, 1 m — better than leaf-off for what he wants.** The HRDEM DTM hillshade
  (T10.12) strips vegetation entirely, so old skid trails, benches and ground structure
  show through canopy that no leaf-off photo would penetrate. Leaf-off shows you the
  ground between the trees; a DTM shows you the ground under them.
* **Leaf-off, 20–30 cm — real work.** Québec's MERN orthophotos, often flown in spring
  leaf-off, distributed per-feuillet with no single mosaic endpoint.

**Done when:** the Sentinel window is derived from the run date rather than frozen;
setup exposes the imagery season where it changes the answer; and the basemap panel's
additional-imagery rows reflect what was actually acquired for THIS box instead of three
permanent "NOT WIRED" placeholders.

### T10.14 — Basemap rows need previews, not CSS gradients · `ready`
Asked: "For our available basemap types. shoudl have previews beside the type."
Today `BASE_SWATCH` is four hand-written `linear-gradient()` strings — a grey ramp
standing in for hillshade, a green-brown ramp for satellite. They convey nothing about
what the basemap will look like over YOUR ground.
**Done when:** each row shows a real tile from the current view centre, so the choice is
made on the actual ground rather than on a generic swatch.

### T10.17 — Peninsulas were being called funnels · `done` (2026-08-07)
Reported from the map: "peninsulas are being identified as funnels. These are probably
the opposite of funnels. they are dead ends."
Correct, and it was not a near-miss. The constriction detector asked exactly one
question — is this ground narrow, pinched between barriers? — and that question is
purely LOCAL. A peninsula neck answers yes. So does a spit, an island tie-bar and the
closed end of a bay.
**Measured before the fix, across every cached AOI:** on his own box 25 of 25 candidates
were dead ends. On another, 10 of 36. The layer was mostly wrong, and wrong in the
specific way that sends someone to sit on ground no travelling bull has a reason to
cross.
**The fix** is the standard connectivity test — Circuitscape's pinch points, where
losing a little ground SEVERS A LINKAGE. Cut the neck; look at what it separated. Two
substantial regions is a funnel; one region and a stub is a dead end; one region means
you can walk around it and nothing is funnelled at all.
**Two things that looked right and were not,** both caught by measurement rather than by
reading the code, and both now pinned by tests:
* **Cut ACROSS the neck, not along it.** The medial axis runs ALONG the corridor centre,
  so deleting those cells leaves the flanks joined around the gap and severs nothing.
  The cut radius has to come from the distance transform, which IS the local half-width.
* **The sides are the pieces the neck TOUCHES,** not the two biggest pieces nearby.
  Taking the largest components in the window paired a peninsula stub with an unrelated
  region across a lake. Symptom that caught it: widening the search halo 6 km → 25 km
  moved survivors 9 → 25 on one box and 47 → 66 on another. The verdict was being
  decided by how far we happened to look.
**Result across the cached set:** water-poor boxes (91–96% passable) keep 0–14 of their
candidates; genuinely lake-riddled ones keep hundreds with sides up to 73 km². The test
discriminates on the geography rather than on a threshold.
**Left for later:** whether the two sides are worth MOVING between — feed on one, cover
on the other — is the other half of what makes a funnel, and it is a habitat question.
`terrain.py` runs before `habitat.py`, so that weighting belongs in a later stage. See
T10.18.

### T10.18 — A funnel should connect two places a moose WANTS · `ready`
The other half of T10.17, and his own framing of it: "some sort of terrain featue that
concentrates movement between two areas that would be interesting to them."
T10.17 makes a funnel prove it is a BOTTLENECK. It does not ask what is on either side.
A perfect neck between two barren rock outcrops is a perfect bottleneck and a worthless
place to sit; a moose moves between food and security cover, so the necks that matter
are the ones joining feeding ground to bedding/thermal cover.
The constraint that shapes the work: `terrain.py` runs before `habitat.py`, so terrain
can only supply the geometry. The destination weighting has to happen in a later stage
that can see `browse.tif`, `cover.tif` and the refuge surfaces.
**Done when:** a neck's score is weighted by what its two sides actually hold — full
credit for feed one side and cover the other, little for two sides of the same barren
ground — and the hover card says which two things it joins.

### T10.15 — The hunt leg bushwhacks past a mapped trail · `ready`
Reported twice in one session, with screenshots: "It goes along one road and then
bushwacks to the location. But you could have just followed the road to basically the
same location" and "Access line follows road. Hunt line bushwacks for some reason."
**Diagnosed, and it is one missing file.** `_linear_cost_layer` in `synth.py` builds the
cheap-walking mask from `aq_trails.gpkg` and `aq_rail.gpkg` only. It never reads
`trails.gpkg` — the OSM foot/quad trails. But `export.py` DOES draw `trails.gpkg` on the
map. So the dashed trail visible in the screenshot is a line the router cannot see: the
app is drawing a path to a place it does not know how to walk to, then routing around it.
The access leg looks right because roads.tif IS in the surface; only walking is blind.
**Done when:** the walk-cost surface reads every linear feature the map draws, and a test
fails if the two sets diverge — the same class of bug as the waterbodies one that made
least-cost paths swim across lakes.

### T10.16 — The Sentinel window is frozen in 2023–24 · `ready`
Found while answering the basemap question, and it outranks what prompted it.
`acquire/sentinel.py` hardcodes `datetime="2023-07-01/2024-09-15"`. Nothing derives it
from the run date, so the NDVI feeding the browse surface is built from imagery that was
already ~2 years old on 2026-08-07 and gets older every day this stands. Cuts and burns
newer than Sept 2024 are invisible to the greenness term — on ground whose whole browse
story is disturbance age, that is the input most likely to be wrong.
It is also silent: no caveat, no date in the brief, nothing that would make a hunter
suspect the satellite half of the answer is stale.
**Done when:** the window is derived from the run date, the brief states the imagery
dates it actually got, and the model says so when the freshest usable scene is old.

### T9.10b — Decide the fine-grid neck detector · `ready`
Built, tested and committed in rev 22, switched OFF behind `FINE_NECKS=1`.
Its ACCURACY is settled: an 80 m neck reads 160 m on the 40 m analysis grid and 100 m at
10 m, and a real run reported four separate funnels at exactly 113 m — the grid's
quantization floor rather than the terrain. What is unsettled is the POPULATION: on
47.967, -77.809 the funnel count went 7 → 3. Nothing moved or was invented (each
survivor sits within 71 m of one the old detector found) but the four that vanished
scored 0.53, 0.40, 0.33 and 0.24, and losing the 0.53 is not defensible from the
evidence to hand. Relaxing the polygonize admission bar until the count came back is the
rev-21 mistake exactly.
**Done when:** the two versions are compared on ground Joe has walked, and the switch is
either removed (on) or the code is (off) — not left as a permanent flag.
