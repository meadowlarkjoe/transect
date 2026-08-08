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

**Empty as of 2026-08-07.** Everything that reached this band has been either fixed or
disproved. Worth recording how the last four went, because it is a pattern rather than a
coincidence: T6.1, T6.3 and T6.4 all began as "the model is doing something wrong" and
all three turned out to be the MEASUREMENT being wrong — a tautological null, a
mis-configured baseline, and four successive versions of the wrong choice-set. The engine
was in better shape than its instruments said every time.

The instruments are now written down rather than reconstructed (`focus_pool.tif`,
`FOCUS_DEBUG=1`), which is what should stop the next one.

### Band 2 — MISSING (a real gap you can see)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 1 | **T9.10b** Decide the fine-grid neck detector | `blocked` — the A/B now runs and the 7→3 collapse is fixed (it was two cell-denominated constants). What is left is ground truth Joe has to supply, plus a separate worker-memory call on `FINE_BUDGET_PX`. |
| 2 | **T10.13** Imagery season picker | The stale-window half is T10.16 above; this is the control and the high-res leaf-off source. |
| 3 | **E11** Forest survey read at a fraction of its resolution | Cross-referencing a guide's Cartes Xperts sheet showed the source carries species, height, age, drainage and slope; the engine reads cover class and density. Peatland landed (rev 32); the rest touches browse, thermal, refuge, travel, routes and wants a map layer. |
| 4 | **E12** A printed field sheet that replaces the bought map | `human` on scope — it is the largest epic here and it changes what the product IS. Shares one unsolved delivery problem with E11.6 and T10.22. |
| 5 | **T10.22** Serve the LiDAR hillshade as a basemap | Split out of T10.12, which established that the coverage is real. Delivery is solved (T0.6) — this now only needs the RENDER. |

**T10.4 + T10.9 done 2026-08-07** (engine rev 31). Water became one parent over beaver
ponds · wetlands · rivers & lakes, and the DRAW ORDER was inverted to match the rule —
the generic lake fill had been painting over the flowage the model calls a rut hub.
Browse became a parent over six KINDS OF FOOD (aquatic · regen new/prime/closing in ·
deciduous · other) filtered from one source, so every zone is drawn exactly once; the
engine stamps the kind, most specific first. "Recent cuts" stopped being a second
top-level row — an aged cut IS the regen layer — and its years survive as `dist_age`
("disturbed ~18 yr ago"). Provenance moved to the hover card, which is T10.9: all ten
explanatory popups are gone, `maplibregl.Popup` no longer appears in the file, hover
carries the whole explanation and click PINS it.

*Not named species.* The écoforestière stand map carries résineux / mélange / feuillus
CLASSES. "Deciduous & mixed" is as precise as the data honestly gets.

*Two defects found by measuring rather than reading:* a polygon clipping one burned cell
was named by that cell (every zone on `fire_lake` came back "regen prime"); and the
classifier converted whole rasters per polygon, gigabytes of copies on a large box.

**T10.3 done 2026-08-07** — every map feature class now carries its window (areas,
labels, camps, staging, sites, routes) and a season pill offers all-windows or one. It
composes with each layer's own filter rather than replacing it, features with no window
stay visible under every selection, and the derived shooter/scent geometry filters
separately because it is built from `window._sites` rather than the source. The sidebar
honours it and every area card names its window, preferring the METHOD when the windows
differ by weapon. Two things came from rendering it live rather than reading it:
`getStyle()` returns *undefined* before load (the same trap as T10.11, in a call that
sits in the source refresh where an exception aborts the rest of it), and suppressing
"rifle" as an unlabelled default left one chip saying "bow" and the other saying nothing.

**T10.11 + T10.10 done 2026-08-07** — terrain is now derived from pitch alone (past 12°
the mesh is on, at 0 it is released) and the checkbox is a shortcut that tilts the camera,
so a right-drag and the checkbox are the same act. The chip renders from `curBase` and the
live terrain state instead of being the literal string `<b>SAT</b><i>2D</i>`. Two things
were found by driving the live map that no static test would have caught: `setTerrain`
throws before the style is loaded, and the obvious `load`-once guard for it silently
recreates the original bug, because `isStyleLoaded()` drops to false on every ordinary
source update. The retry is on `idle`.

**T10.5 done 2026-08-07** — three faults stacked. In fixed-camp mode the camp is also
`draft.sites[0]`, so a numbered site dot was drawn at the identical coordinate; `setTab`
never hid those dots off Setup; and — the one that made the cabin vanish — a MapLibre
symbol carrying both an icon and a label is placed as a UNIT, so the camp's "A" losing a
collision to the dot's `text-allow-overlap` label deleted the icon with it. All symbol
layers with both are now `text-optional`, checked over the whole file rather than the two
that were broken.

**T10.6 done 2026-08-07** — the plate map was built from `baseStyle()`, imagery and nothing
else, and every `setLayoutProperty` that followed sat behind `if(m.getLayer(id))` and did
nothing. Five plates, all basemap, since T9.7. Now built from `map.getStyle()` (which
serialises the GeoJSON sources with their data inline — verified in the browser), icons
and patterns re-registered because images are not part of a style, terrain dropped and
the view framed on the areas. A plate with no plan layers on it now says so.

### Band 3 — UGLY (it works and reads badly)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 6 | **T10.7** PDF layout is browser print chrome | Timestamp, "Page 1 of 11" and the raw URL on every page. |
| 7 | **T10.14** Basemap rows are CSS gradients, not previews | A grey ramp standing in for hillshade tells you nothing about your ground. |

### Band 4 — PLATFORM (nobody sees it; it decides how fast the rest goes)

| # | Ticket | Why it is here |
|---|--------|----------------|
| 8 | **T0.3** Contract snapshot harness | Every refactor below needs a before/after diff to be safe. |
| 9 | **#84** Workers in their own container | Root cause of both deploy jams; a run still dies with the API. |
| 10 | **T4.1 → T4.2** Extract the Québec legal adapter, then make `UNRESOLVED` loud | The most province-locked file. T4.2 is blocked on it and has to be queued WITH it, not left as prose in this cell. |
| 11 | **T3.1 → T3.2 → T3.3** Species plug-ins | `whitetail_deer.yaml` is drafted and has never been run. |
| 12 | **T1.3 · T1.4 · T2.2 · T2.4** Generality | Layer groups, species prose, CRS, global fallback — all now unblocked. |
| 13 | **T6.2** Backtest against harvest density | Blocked by T6.1. |
| 14 | **T5.1 · T5.2 · T5.3** Research sweeps | Québec-wide, Ontario, Maine/NH. |
| 15 | **T8.1 → T8.2** Autonomous night shift | T8.2 is `human` — cadence is Joe's call. |
| 16 | **E7** Mobile | `human` — gated on a design AND on the field-vs-couch product answer. |

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

### T0.4 — Isolate the tests that contaminate each other · `done` (2026-08-07)
`test_synth_smoke` passed alone and failed in a full-suite run with `RasterioIOError:
.../fire_lake/huntability.tif`. Three synth checks therefore failed whatever the engine
did, so a genuine synth regression was indistinguishable from the noise.

**The cause, found and reproduced.** `test_legal.py` set `MOOSE_SCOUT_CACHE` with a plain
assignment at MODULE IMPORT, to get itself a hermetic empty cache — a reasonable thing to
want and a ruinous way to get it. From the moment pytest merely COLLECTED that file, every
later test resolved its cache to that temp directory. And `test_synth_smoke`'s skip guard
checked a HARDCODED path (`/app/cache/fire_lake`) while the test itself resolved through
the environment, so the two disagreed: the guard saw the container cache and let the test
run, the test looked somewhere empty and died.

**Reproduced and proved,** in the container with the cache mounted: old code → 3 failures
in 1.55 s; fixed → clean. With the cache resolvable, they now RUN (23.8 s, a real
pipeline) and the per-file result matches the full-suite result.

**Both fixes generalised.** `test_legal` uses an autouse fixture with `monkeypatch` so the
isolation undoes itself; the smoke guard resolves the cache the same way the test does, so
a leak from anywhere makes it SKIP honestly rather than fail and blame the code.
`test_no_global_leaks.py` parses every test module and fails if any of them writes a
path-shaping env var at import — it immediately caught a second, milder instance in
`test_fine_terrain`, whose hand-rolled save/restore would have leaked `FINE_NECKS` on any
failing assert.

**What it uncovered.** With the noise gone, one assertion still fails and it is real:
`[synth] capability gate: 37 of 37 focus areas excluded; 0 viable areas promoted` — the
fire_lake fixture produces no viable areas at all, so no routes. Verified against the
commit before T10.20, so it is not a routing regression. Filed as T0.5.

### T0.5 — "Access unknown" was being reported as "cut off by water" · `done` (2026-08-07)
Surfaced by T0.4 the moment the test contamination stopped masking it: on the fire_lake
cache, synth logged `capability gate: 37 of 37 focus areas excluded; 0 viable areas
promoted to ranks 1..0`. No areas, no routes, nothing to hunt.

**Not a stale fixture — a real bug, and a confidently wrong one.** `roads.tif` is missing
from that cache, so `access.py` fills `dist_road` with its 1e6 placeholder and raises
`access_unknown.flag`. The gate read `dr >= 5e5` and told the hunter, of every area:
*"No boat — this ground is cut off from every road by water. A canoe or boat would open
it."* Specific, checkable, actionable — and built on having no data at all.

Two conditions had been collapsed into one sentinel range: WATER-LOCKED (roads exist and
the cost-distance found no walkable path — a real finding) and NO ROAD DATA (acquire never
landed a network — a placeholder).

**The lesson had already been learned one file away.** `access.py` refuses to zero the
extraction surface when the network is missing, falls back to a neutral 0.85, and raises
the flag *precisely so the rest of the engine can tell the difference* — its comment says
"ACCESS UNKNOWN ≠ ACCESS IMPOSSIBLE ... that is the model asserting 'nothing here is
reachable' on the basis of having no data at all, which is exactly backwards." The fix
was applied in one place and not the other, and the gate went on making the mistake it
had been warned about, for long enough that the test which should have caught it was
itself broken.

**Measured after, same cache:** 37 areas, **0 excluded**, 111 routes, and all four synth
smoke tests pass in a real 74 s pipeline run.

The gate's real job is untouched: out-of-range ground is still excluded when access WAS
modelled, water-locked is still water-locked, and a fixed camp still gates on distance
from camp. A missing flag reads as access-known, because defaulting to "unknown" would
disable the gate everywhere — the opposite failure.

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

### T6.1 — Null-model benchmark · `done` (2026-08-07)
The ticket's own words: "the model is currently unfalsifiable. This is the highest-value
ticket in the backlog and the one most easily deferred forever."

**Why it kept being deferred, and how it stopped being blocked.** There is no ground
truth for where moose are — no collars, no harvest points at this resolution. A benchmark
that waits for that waits forever. But a different question needs none of it: *does the
model tell you anything a five-line heuristic would not?* `moose_scout.validate` answers
that against two nulls at MATCHED AREA — a road-proximity buffer, and random huntable
ground.

**Measured on three real boxes:**

| | overlap with a road buffer | rank corr. with road proximity | capture |
|---|---|---|---|
| job_0e92b5ca580d | 4.7% | +0.056 | **16%** |
| job_20e209ca08d0 | 0.4% | +0.078 | **20%** |
| job_8892f779ddc9 | 11.3% | +0.202 | **6%** |

**It is not a road buffer** — that much is now established rather than assumed.

**But CAPTURE is the finding, and it is uncomfortable.** Capture is the share of the
discrimination the model's own huntability surface contains that survives into the ground
it hands you: 0 = no better than a random draw, 1 = as good as the surface allows. The
surface separates well — a matched-area top-N of it averages 0.43–0.45 against 0.22–0.24
for random ground, nearly double. The focus areas average 0.25–0.27. **The extraction is
throwing away 80–94% of the discrimination the model computed.** Some loss is inherent
(a focus area must be contiguous, so it swallows mediocre interior), but 6% is not
inherent. That is T6.3.

**The threshold was left where it fails.** `beats_random` requires capture ≥ 0.25, so the
benchmark reports FALSE on two of three real boxes. Moving it until it went green is the
rev-21 mistake, and a test now pins the measured values so nobody does.

**A mistake this nearly shipped with, recorded because it passed every reading until it
was run.** The random null was first an OVERLAP test. That number is a tautology — two
independent same-sized selections from the same pool overlap at the area fraction by
construction — and it measured 4.0% against an expected 4.0%. A check built on it passes
for a literally random model.

**What it must never be quoted as:** beating both nulls does not mean the answer is
right. Ground truth is T6.2, which stays open.

### T6.3 — Extent is gated on the raw value, and the earlier numbers were wrong · `done` (2026-08-07)
Opened by T6.1. Chasing it corrected the benchmark twice and then corrected the FINDING
itself — all three corrections were mine.

**Benchmark correction 1 — the null was given choices the model never had.** `validate`
drew from every finite cell of huntability.tif, but synth crops a 2 km border first:
399.5 km² against 256.5 km² reachable.

**Benchmark correction 2 — the ceiling was unreachable by construction.** Capture was
measured against the best n CELLS, maximally fragmented; no walkable area could reach it.
The fair target is the best CONTIGUOUS area of the same size.

**Correction 3, and the one that mattered most: my sweep's "baseline" was not what
ships.** It forced `smoothing_m` to 350 while the shipped value is 200. Re-run against
the real configuration — and after T0.5's gate fix — the numbers are very different from
the 6/16/20% this ticket was opened on:

| box | shipped | + extent_raw_frac 0.70 |
|---|---|---|
| job_0e92b5ca580d | 0.018 | **0.030** |
| job_8892f779ddc9 | no headroom | no headroom |
| job_20e209ca08d0 | **0.408** | **0.460** |

So the extraction was already doing far better than reported. The premise "discards
80–94%" was an artefact of measuring a mis-configured run.

**What shipped, and it is a modest change.** A cell must now clear
`min_huntability × extent_raw_frac` on its OWN raw value, not only on the smoothed
surface. The mechanism is sound — thresholding a 200 m Gaussian is right for deciding
SHAPE and wrong for deciding QUALITY, because a blur lifts poor ground over the bar
wherever it sits beside good ground, and measured, that let an area grow until 64–73% of
it was below the landscape mean. Coherence survives because closing + fill-holes absorb
isolated rejects, so only poor REGIONS are excluded.

0.70 is where the evidence stopped, not where capture looked best: 0.85 scored higher on
one box but halved the area count on two of three, and 1.0 produced ZERO areas on all
three. fire_lake still returns 37 areas. Better ground is worth nothing if it is not
enough ground to hunt.

**A trap caught on the way:** with zero focus areas the benchmark falls back to
top-scoring cells, which trivially beat the oracle — so the settings that produced NO
areas reported capture 2.3–3.2, the most flattering possible number for the worst
possible outcome. `capture` is now None when the extraction produced nothing.

### T6.4 — There was no extraction bug; the benchmark had the wrong pool, four times · `done` (2026-08-07)
Resolved, and the answer overturns T6.1, T6.3 and T6.4 alike.

**The question was: why doesn't the ground at the oracle centre become a candidate?**
Instrumenting the real `_find` — after three failed attempts to reconstruct it from
outside — answered it in one line. The extraction surface on that box spans **rows
254-754, cols 255-755**. The "best possible area" the benchmark was holding the model to
sat at **(241, 759)** — outside the window on BOTH axes. The model was not picking the
wrong ground. It is structurally forbidden from picking that ground.

**`hunt` reaches the extraction narrowed twice** — the 2 km border crop for filter
artefacts, and the reachability / camp-radius mask. On that box it leaves 78 km² of a
400 km² raster. Nothing downstream could see it, so every attempt to reconstruct the pool
guessed, and every guess erred in the same direction: flattering the null, damning the
model.

| measurement | pool it used | verdict it gave |
|---|---|---|
| T6.1 | every finite cell (399 km²) | "captures 6-20%" |
| T6.3 | + 2 km border crop (256 km²) | "captures 1.8-40.8%" |
| **T6.4** | **recorded by synth (78 km²)** | **beats random on every box** |

**Corrected measurements, all three boxes:**

| box | pool km² | model | random | fair oracle | headroom |
|---|---|---|---|---|---|
| job_0e92b5ca580d | 78.3 | **0.246** | 0.221 | 0.233 | 0.012 |
| job_8892f779ddc9 | 34.3 | **0.247** | 0.231 | 0.244 | 0.013 |
| job_20e209ca08d0 | 49.0 | **0.256** | 0.229 | 0.234 | 0.005 |

The model beats a random draw on every box and matches or beats the best contiguous area
on every box. Oracle headroom is 0.005-0.013 throughout — below the 0.02 floor — so there
is no structure at this scale to capture, `capture` correctly reports n/a, and there is
no extraction bug to fix.

**The durable fix is that the pool is now WRITTEN DOWN.** `synth` records
`focus_pool.tif` — the exact surface it extracted from — before extracting, and
`validate` reads it. Guessing it from outside failed four consecutive times; this ends
that class of error rather than correcting its fifth instance.

**A limitation kept rather than hidden:** `_oracle_blob` centres on one Gaussian argmax
and takes the n nearest cells, so when the selection is 23-54% of the pool it converges
on the pool itself — which is why the model can score ABOVE it. The headroom guard
suppresses `capture` there, which is the right outcome, but the oracle is weak at those
fractions and a better construction would be needed if a box ever showed real headroom.

**What this does NOT overturn:** T6.3's extent fix stands on its own evidence (an area
grew until 64-73% of it was below the landscape mean, and trimming to its best half
doubled the score of the ground handed over). T6.1's road-null result stands too — 0.4-19%
overlap and weak rank correlation, on any pool.

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

### T10.1 — A multi-window brief reported window 1's analysis for everything · `done` (2026-08-07)
Reported: "It gave me two focus areas. They overlap... the brief for both areas provides
its analysis based on the first date range. The only place where the different time
windows are compared is at the top." Confirmed in the exported PDF, whose header read
`dates 2026-10-10 → 2026-10-25` on a run that had two windows.

**Narrower than it looked, and worse.** T9.2 got the MODEL right — `_merge` really does
run every (site × window) as its own analysis and tag every area, waypoint and route
with its window. What it missed is that `base` is plan 1's whole document and only the
LISTS were merged. Every non-list section — rut read, strategy, recommendations,
weather, day plan, scent, wind, camp plan — stayed plan 1's. The engine computed the
right answer twice and the product showed one of them under both.

Verified on the exact run that was reported (windows Oct 10–25 and Sep 26–Oct 4): the
first now reads "post-rut, ~15 days after the ~Oct 2 peak" and the second "lands squarely
on the breeding peak". Before, both areas got the post-rut read.

**Fixed:** `WINDOW_SECTIONS` names the nine dated sections and `_merge` carries each
window's own copy into `windows[i].brief`. The app's brief and area-detail panel read
the section belonging to THAT AREA's window via `wsec()`, falling back to the top level
for single-window runs and for plans saved before this existed. Headings name the window
when there is more than one. The PDF header states every window instead of the first.
The top level still carries window 1's sections so older clients and saved plans keep
rendering — labelled `meta.top_level_window`, because unlabelled is the bug.

A parametrised test now asserts that EVERY name in `WINDOW_SECTIONS` is carried, and a
static check refuses any top-level dated read inside `renderBrief`. Adding a dated
section to the contract without adding it to that tuple is exactly how this returns.

**Note for T10.2:** the strategy HEADLINE did not differ between the two windows on that
run, because it is driven by zone density rather than rut phase. Carrying it per window
is right regardless; making it phase-aware is a separate question.


### T10.2 — Method of take is modelled per window · `done` (2026-08-07)
Reported alongside the multi-window brief: "we need to indicate what the method of take
is for each hunting date range, as shooting locations for a bow (max 30/40yds) are going
to be different for those with a rifle (longer range, need visibility more than proximity
— can reach out further / less concern about local scent as you wont be as close)."

Method of take was not an input at all. That made T10.1 half a fix: correctly labelled
bow advice that still put the shooter 70 m from the caller — twice a bow's effective
range — and still recommended glassing knobs a bow hunter cannot use.

**It belongs to the WINDOW**, because a window is usually a season and a season is
usually a weapon, which is how it was reported. It rides as an optional third element of
each window (`["2026-09-12","2026-09-20","bow"]`) so every request that ever worked still
works, and a two-element window is still a rifle window.

**What it actually changes**, measured on a real box, same ground, rifle vs bow:

| | rifle | bow |
|---|---|---|
| shooter downwind of caller | 70 m | **40 m** |
| scent wicks | 45 m | **28 m** |
| effective range quoted | 200 m | 35 m |
| glassing sites placed | 3 | **2** |

The scent layout is a function of the weapon because its whole purpose is to stop the
bull at a distance the shooter can USE — the gap between wick and shooter must fit inside
the effective range, which a test now pins for every method. The site mix gets a method
weighting that MULTIPLIES the rut-phase weighting rather than replacing it (a bow hunt in
the seeking phase is still a calling hunt): glassing 0.4x, calling 1.25x, funnels 1.3x.
Rifle weights are all 1.0, so every existing plan is unmoved.

The client was drawing the shooter at a literal `0.07` km — a rifle setup drawn for
everybody. It now reads `DOC.scent.geometry`, which the wicks already did.

**Caught by running it:** `_crew_plan` has no `ctx`, so quoting the geometry there raised
a NameError — the same class of bug the routing code's own comment warns about. The
distance is a parameter now, not a lookup.

### T10.3 — Which window an area belongs to is invisible on the map · `done` (2026-08-07)
Reported: "They overlap. Im guessing these are different for each season, but thats not
clear on the map. Maybe... a slider or multi select on the map that allows you to either
see analysis for all dates vs analysis for a single date range."
`areas[].window` already exists (T9.2) — this is a display control, not new modelling.
**Done when:** with more than one window the map offers all-windows vs a single window,
and an area always says which window it came from.

### T10.4 — The legend describes DATA SOURCES where it should describe the ANIMAL · `done` (2026-08-07)
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

### T10.5 — The camp icon regressed to a numbered circle · `done` (2026-08-07)
Reported: "For a camp style hunt we use to show a CAMP icon with a cabin at the camp
location. Now it just shows a number 1 in a circle."
Almost certainly collateral from T9.3 (`camp_plan`) or T9.1 (per-site numbering), where
a fixed camp started being rendered as a SITE index. Visible in the screenshot: a plain
amber "1" where the tent/cabin pin used to be.
**Done when:** a fixed camp draws its own icon, and site numbering never claims a camp.

**Cause — three faults, and the guess in this ticket was wrong about all three.** It was
not `camp_plan` or per-site numbering emitting a site index. (a) In fixed-camp mode the
camp is also `draft.sites[0]`, so `drawDraft` emitted a numbered dot at the identical
coordinate. (b) `setTab` hides `draft-fill`/`draft-line` off Setup and `draft-camp` once a
result exists, but never hid `draft-site`/`draft-site-n` — the Setup preview survived onto
every tab. (c) THE DISAPPEARANCE: a MapLibre symbol carrying an icon AND a label is placed
as a unit, and with neither part optional a label that cannot be placed takes the icon
with it. `icon-allow-overlap` exempts the icon from collision testing, not the pair. The
dot sets `text-allow-overlap` so it always wins; the camp's "A" lost, and the cabin went
with it.

**Fixed.** No numbered dot in fixed-camp mode, the preview dots hide off Setup, and every
symbol layer carrying both an icon and a label is `text-optional`. `tests/test_camp_marker.py`
checks that last one over ALL symbol layers, not the two that were broken — (a) and (b)
are specific mistakes, (c) is a trap any new labelled layer can fall into.

### T10.6 — The PDF brief renders no analysis · `done` (2026-08-07)
Reported: "None of the analysis / polygons / waypoints / etc. render on the PDF."
Confirmed: each of the five plate pages carries exactly one image — the basemap — so the
offscreen map T9.7 drives is painting terrain and none of the plan layers. T9.7 was
declared done on the strength of the plates existing; nobody checked what was ON them.
That is the exact failure mode the "verify the artifact" rule exists for, repeated.
**Done when:** every plate shows the same features the app draws for that layer, and a
test fails if a plate comes back with no plan geometry on it.

**Cause.** `_plateMap()` built the offscreen map from `baseStyle()` — imagery and nothing
else. `_plateShot()` then set visibility on the plan layer ids behind `if(m.getLayer(id))`,
which was ALWAYS false, so every toggle silently did nothing. The guard that was there to
be defensive is what made the failure invisible.

**Fixed.** The plate map is built from `map.getStyle()`, which serialises the GeoJSON
sources with their data inline (verified in-browser: `typeof data === 'object'`, a real
FeatureCollection). Images are NOT part of a style, so `addIcons` and `registerPatterns`
re-run against the plate map — both now take an optional target. Terrain is dropped and
the view is fit to the areas, because a pitched hillshade is a picture and a plate framed
on wherever the hunter last looked can miss the focus areas entirely. A plate whose own
layers are all missing or hidden now logs `[pdf] plate has no plan layers on it`.
`tests/test_pdf_plates.py` pins all of it, including that every row named by `PLATES`
resolves to real layers.

### T10.7 — PDF layout is browser print chrome · `ready`
Reported: "The design/layout of the PDF needs to be polished."
Every page carries `2026-08-07, 8:47 AM`, `Page 1 of 11` and the raw plan URL — the
print-to-PDF headers and footers, not a designed page. That was the accepted cost of
choosing print-to-PDF over a vendored library (T9.7); it is now the visible cost.
**Done when:** the export reads as a document — its own header/footer, page numbering
and typography — with the browser's chrome suppressed.

### T10.8 — Draw the area to analyse, instead of only a radius · `done` (2026-08-08)
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

**Done 2026-08-08.** `bbox_wgs84()` is the single source of truth for the extent in both
modes, and `effective_halfwidth_km()` sizes the grid, the resolution panel and the run
estimate from the box actually being analysed — a drawn parcel carries whatever the
radius slider last held, so quoting it offered a 35 km box's grid for a 2 km parcel.
Clipping keeps what overlaps the ring by ≥10%; **routes are never clipped** (the road you
drive in on starts outside, and clipping it would amputate the approach and report the
stump as the way in) and a **parking waypoint outside the line survives** (staging is on
a road; dropping it leaves every route starting from nowhere). A clip that fails KEEPS
the feature — over-reporting is recoverable by looking at the map, silently losing a
focus area is not.

*The 5 km floor stays for RADIUS mode,* and that is deliberate rather than an oversight:
the padding that retires it only exists for a drawn ring. A 3 km radius box has the same
missing-context problem the floor was protecting against.

*One thing the ticket asked for that correctness would not allow.* "the geocache keys on
the PADDED bbox so redrawing a similar parcel still hits a warm cache" — it keys on the
padded bbox, but NOT loosely. `restore` hardlinks the cached rasters in with no shape
check, so a key that matched a box we did not analyse hands the run a misaligned grid
rather than a miss. Rounding stays at 4 dp (~11 m); a parcel redrawn further out than
that pays for a re-fetch. Existing cache slots are invalidated by the new key.

Its test used an `_AOI` stub carrying `center` and `bbox_halfwidth_km`, which stopped
resembling the real thing the moment the key read `bbox_wgs84()` — every test in the file
failed on a double that had quietly drifted. It uses the real `AOI` now.

### T10.9 — Hover tooltip and the click card are two different explanations · `done` (2026-08-07)
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

### T10.10 — The SAT/2D chip is hardcoded HTML and never updates · `done` (2026-08-07)
Reported: "the basemap icon still shows 2D... Even if i manually activate, the basemap
pill doesnt update."
Confirmed, and it is literal: `mc.innerHTML = ... <b>SAT</b><i>2D</i>` — a constant
string written once at map setup. It is wired to nothing. So it says SAT while you are
on Relief, and 2D while you are pitched to 60°. `syncCompass` already listens on
`rotate`/`pitch` right beside it; this needs the same treatment.
**Done when:** the chip reads the live basemap and the live pitch/terrain state, and a
test fails if either is rendered from a constant.

### T10.11 — Pitching the camera does not turn terrain on · `done` (2026-08-07)
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

### T10.12 — Relief is mislabelled, and LiDAR is now genuinely available · `done` (2026-08-07)
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

**Done, except the serving half — which is now T10.22.** Relief says `ESRI WORLD
HILLSHADE · MIXED RES` and carries the reason it goes soft at z14 (the elevation under a
hillshade cannot carry honest detail past it), tied to `RELIEF_MAXZ` rather than a
hardcoded number. The LiDAR row reads `coverage_frac` from the coverage manifest and
gives a per-AOI answer: the measured percentage where HRDEM covers the box, "NOT FLOWN
HERE" where it does not, and "run predates the HRDEM mosaic" for an old plan — which is
not the same as 0%, and reporting it as 0% would be inventing a measurement.

It is deliberately still not SELECTABLE, and the row says so. A switch that does nothing
is the T10.10 mistake. Nearly shipped reading `DOC.data_manifest`; the field is
`coverage_manifest`, and the failure would have been silent — `.find` on an empty array
returns undefined and the row degrades to "no reading", which looks exactly like an old
plan.

### E11 — The forest survey is read at a fraction of its resolution · `ready`
Joe supplied a Cartes Xperts écoforestière sheet for 47.983333, −77.817500 — the T9.10b
box — to cross-reference. It renders the same MFFP source this engine pulls, and it is
carrying detail per polygon that the engine throws away at the door. His read of it:

> "All of this additional resolution on the forest should be exposed visually on the map
> and I feel like this gives us a whole new level of detail that should be accounted for
> in the engine as it relates to moose behaviour for feeding and the areas that they want
> to take refuge, etc. This probably impacts the models for browse/feeding, thermal,
> refuge, travel, routes, etc."

That is right, and it is why this is an epic rather than a browse fix. `_classify` reads
`type_couv` and `cl_dens` and discards the rest. Measured over that sheet, 599 stands:

| field | state | what it is | what it should reach |
|---|---|---|---|
| `type_couv` | **used** | R 418 · M 113 · F 17 | the model's whole vocabulary today |
| `cl_dens` | **used** | density A–D → closure | cover, thermal refuge |
| `dep_sur` + `cl_drai` | **used (T10.23.1)** | organic + hydric = peatland | browse, wet, walk cost |
| `gr_ess` | discarded | ENEN 45.9% · BPBPSB 3.7% · ENENBP 3.5% … | browse quality, thermal cover |
| `cl_haut` | discarded | height class | **whether browse is reachable at all** |
| `cl_age` | discarded | 50 · 30 · JIN · JIR · VIR | stand age with no cut record needed |
| `cl_pent` | discarded | slope class | travel cost, glassing |

**T10.23.1 — peatland · `done` (2026-08-08, rev 32).** Organic deposit on hydric drainage
is now `T_TOURBIERE`. Dropped stands 39 → 11; the 11 that remain are glacial and alluvial
barren, which is correct — `non_boise` scores browse −0.30, and calling rock a bog would
be an invention in the hunter's favour. Peat is deliberately not conifer closure: a
thermal refuge on open bog would send someone to sit in one on a warm afternoon.

**T10.23.2 — ingest the rest of the attributes.** `gr_ess`, `cl_haut`, `cl_age`,
`cl_pent` onto the working grid. Prerequisite for everything below, and worth doing as
one pass because they arrive in the same WFS response the engine already pays for.
*Done when:* the rasters exist, are covered by the geocache artifact allowlist, and a
box with no écoforestière coverage still runs.

**T10.23.3 — species-aware browse, gated on HEIGHT.** The reason this is one ticket and
not two: species alone over-claims. Mature paper birch is prime browse *by species* and
out of reach *by height*, and `feuillus` currently scores 0.20 precisely because the class
constant is absorbing that. Browse has to be `species value × reachability(cl_haut)`, or
it will confidently promote 20 m hardwood.
*Done when:* ENENBP outscores ENEN for browse; a tall feuillus stand does not outscore a
short one; and the T10.4 legend can finally name what was asked for.

**T10.23.4 — thermal refuge and cover by species, not "any conifer".** Closure is already
used; which conifer is not. Larch drops its needles.
*Done when:* refuge prefers dense SB/EN closure over an equally dense larch stand.

**T10.23.5 — travel and routes from drainage, deposit and slope.** `cl_drai` and
`dep_sur` say where the ground is wet and soft, and `cl_pent` says where it is steep —
all three are walk cost, and all three are currently guessed from land cover. This is also
what would stop a route being drawn straight across a bog.
*Done when:* walk cost reads them where the survey covers the box, and the route legs
change measurably on ground where drainage and land cover disagree.

**T10.23.6 — show it. A forest layer on the map.** The guide's sheet is valuable to Joe
*because you can look at it* — species, height, density, cut year, per polygon. The engine
will hold all of that and the map shows none of it.
*Done when:* a Forest group renders stands by species and stage with the survey's own
labels available on the hover card, and it reads as one system with the browse kinds
rather than a second opinion beside them.

**DELIVERY IS THE HARD PART, and simplification is not the answer to it.** E11.2 first
shipped these polygons generalised to the analysis grid to keep the file small. That was
the wrong trade and Joe caught it: the analysis grid bounds what the MODEL sees, not what
the MAP should draw, and a stand boundary is exactly what a hunter reads closely — the
cover-to-forage seam is where you put a stand. Measured at 40 m the boundary moved 58.8 m
at worst, 34.5 m on average; on a 1:11,000 sheet that is millimetres of visible error.

It is de-duplicated at 1 m now — 48% of raw for a 1.5 m worst-case move, because most of
the ~190 vertices per stand are near-collinear redundancy, and écoforestière's own
photo-interpreted accuracy is about ±10 m. That removes encoding, not information.

Which leaves the real number: **a 35 km box is roughly 84,000 stands and ~170 MB even at
1 m.** That cannot go to a browser whole, and coarsening it until it fits would trade away
the thing the layer is FOR. So this ticket owns a delivery decision — clip to the focus
areas, serve on demand by viewport, or vector-tile it — and it shares that decision with
T10.22, which needs a per-job asset route for the same reason. Neither should invent its
own.

**E11.7 — the disturbance vocabulary the engine still ignores.** Found while answering
whether the queue reaches parity with the guide's map. Over 1908 stands on that sheet's
ground the engine drops, silently:

* `origine` **ES** (37 stands) — *épidémie sévère*. A stand-replacing insect outbreak.
  It kills the canopy and flushes browse much as a burn does, and the guide's legend gives
  it its own category. `BURN_ORIGINS` is `{"BR"}` alone, so this reads as undisturbed.
* `origine` **CBA** (18) — *coupe par bandes*, strip cutting. Not in `CUT_ORIGINS`.
* `perturb` **EL** (112), **EPC** (76), **EPR** (8), **EPC_SYS** (7) — light outbreak and
  precommercial thinning. **203 stands, 10.6% of the ground.** EPC matters in the opposite
  direction to everything else here: thinning REMOVES competing hardwood, so it should
  *lower* browse, and the engine cannot currently know that.

**Done when:** severe outbreak is treated as the stand-replacing disturbance it is, strip
cuts are cuts, thinning is a browse penalty rather than nothing, and the map legend can
render the same disturbance classes the guide's sheet does.

**The standing risk across all of it.** Écoforestière thins out north of ~52°N and stops.
Every model that starts reading these fields has to degrade to the satellite path outside
the coverage, and the manifest has to say which one answered — or a northern box will
quietly get a worse model with no sign that it did.

### E12 — A printed field sheet that replaces the bought map · `ready`
Asked directly: if the queue is finished, does that remove the need to buy Cartes Xperts?
Answered honestly: no, and not because the model is behind — because they sell a
different KIND of thing. E11 makes the analysis better. This epic is about the artefact.

**What they actually sell, measured rather than assumed.** One sheet, 2160 × 1728 pt =
**30 × 24 inches at 1:11,000**, covering **8.38 × 6.71 km (56 km²)** centred on the
hunter's ground. (Recorded because the first read of it was wrong: the file was described
as 285 pages — that was a size estimate, `pdfinfo` says one.) On it: the écoforestière
stands rendered and LABELLED with the survey's own codes, harvest and perturbation
polygons with years, classified roads, hydrography, contours, place names, a full legend
of ~60 species codes plus harvest/disturbance/deposit vocabulary, a graticule in both
lat/lon and Lambert, a scale bar, and the data currency stamped.

**What Transect has that the sheet cannot.** The model — ranked focus areas, rut phase,
routing and pack-out, staging, wind and scent geometry, pressure, the legal gate. None of
that is in question here.

**What Transect does NOT have, and this epic is the list.**

**E12.1 — render at a TRUE SCALE, not a screenshot.** T10.6/T10.7 produce plates of the
app. A field sheet is a different artefact: a stated scale (1:11,000 default), a scale
bar, a graticule, north, and a margin that carries the legend. *Done when:* the export
states its scale and a measured distance on the paper matches the ground.

**E12.2 — the stands, labelled the way the survey labels them.** E11.2 already fetches
`gr_ess`, height, density and age per polygon. The sheet's value is that every stand
carries `R ENML 75% 10m` where you can read it. *Done when:* a printed stand carries its
own code, and the map legend explains the vocabulary rather than assuming it.

**E12.3 — contours, and ours should be better than theirs.** There are none anywhere in
this codebase — checked. Theirs come from a national 10 m product. We already fetch HRDEM
1 m LiDAR and record its coverage per box (T10.12), so we can generate contours from a
surface 10× finer where it is flown, and fall back to MRDEM-30 where it is not. *Done
when:* contours render at a sensible interval for the scale, say which DEM produced them,
and never imply LiDAR precision on ground that only had the 30 m fallback.

**E12.4 — the full disturbance and deposit vocabulary.** Shares its data work with E11.7
(ES severe outbreak, CBA strip cut, EL/EPC thinning — 10.6% of the sampled ground) and
E11.2's `dep_sur`. The engine ingests it; here it has to be legible on paper.

**E12.5 — tile an AOI across sheets.** One sheet is 56 km². A 4 km drawn parcel fits
inside one; **a 35 km radius box is 88 of them.** So this needs an index sheet and a tiling
scheme, or a deliberate answer that the field sheet covers the focus areas rather than the
whole box. *Done when:* an AOI of any size produces a coherent, numbered set with an index.

**E12.6 — a file you own.** They sell an artefact that keeps working with no battery, no
signal and no subscription. Ours is a hosted service over a pruned cache. *Done when:* the
export is a self-contained file — GeoPDF or equivalent — plus GPX of the plan, and it
does not stop working when the job cache is swept.

**The honest cost.** E12.1–E12.4 are a rendering pipeline the app does not have today:
print-scale cartography is not the screen map with a bigger viewport, and 88-sheet tiling
is a real piece of work. This is the largest epic in the file. It is also the one that
changes what the product IS — from a thing you consult to a thing you carry.

**And the sequencing that matters:** E12.2 depends on E11.2 (done) and shares its delivery
problem with E11.6 and T10.22. All three want the same missing piece — a way to get a
large per-job artefact to the hunter and keep it working afterwards. That should be
decided once, for all three, before any of them builds its own.

### T0.6 — Delivery for large per-plan artefacts · `done` (2026-08-08)
Three tickets independently needed the same missing piece and were each about to invent
it: **E11.6** (the forest layer — 2.7 MB for an 8 km box, ~170 MB for a 35 km one),
**T10.22** (the LiDAR hillshade) and **E12.2** (the printed field sheet). Decided once,
in `src/moose_scout/artifacts.py`, before any of them built its own.

**The trap all three would have fallen into** is serving out of the job cache. Job state
prunes at 48 h and the geography cache prunes on its own budget, so a layer works for an
afternoon and then quietly 404s for anyone reopening a saved plan. A JOB is an event; a
PLAN is what someone comes back to. The store is keyed to the plan and lives under
`/app/data`, a persistent host mount, so it survives container recreation by construction.

**Measured on the live droplet before deciding:** 7 plans, 11 users, plan blobs averaging
586 KB in sqlite (max 1.5 MB), a 3.2 GB geography cache, 59 GB free. That ruled out the
plan blob — base64ing 170 MB into a row read in full on every plan open — and ruled out
object storage *for now*: right at scale, wrong dependency at this size. The interface
does not change when that flips, which is the point of having one.

**What makes it safe rather than merely small:** a missing artefact is an ANSWER. `state()`
distinguishes *evicted, re-run to rebuild* from *this plan never had one*, and the route
answers **410 with the reason** rather than a bare 404 — because an empty layer and a
swept layer look identical on a map, and a hunter reading the first concludes there is
nothing on the ground. Everything else here is reversible; that is not.

Also: eviction drops WHOLE plans (half a plan's layers is a map inconsistent with
itself); the route reuses `_plan_access` so a shared plan's party sees its layers rather
than meeting a second, quietly divergent ACL; promotion happens on SAVE so abandoned
experiments cost no disk; deleting a plan takes its artefacts; and the worker stamps
`meta.job_id` so a plan reopened on another device still knows which run produced it.

**Unblocks E11.6, T10.22 and E12.2.** None of them should add a delivery path of its own.

### T10.22 — Serve the LiDAR hillshade as a basemap · `ready`
T10.12 established that HRDEM coverage is real and measured per box. What is missing is a
way to LOOK at it. The COGs are not tiles, so this means rendering an AOI-sized hillshade
at analysis time — the HRDEM mosaic publishes `<tile>-mosaic-1m-dtm_hillshade.tif` beside
the DTM the engine already reads.

**The part that makes this more than an afternoon,** and the reason it was split out
rather than rushed at the end of a long session: there is no per-job asset route on the
API today, and the geography cache is pruned. A hillshade served straight out of that
cache would work for an hour and then quietly 404 for anyone reopening a saved plan —
the silent-breakage pattern this codebase keeps getting bitten by. Retention has to be
decided BEFORE the render, not after.

**Done when:** selecting LiDAR shows the 1 m hillshade over the covered part of the box,
a plan reopened after the cache is pruned either still renders it or says plainly why it
cannot, and the basemap row becomes selectable exactly when there is something to select.

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

### T10.18 — A funnel should connect two places a moose WANTS · `done` (2026-08-07)
The other half of T10.17, and his own framing of it: "some sort of terrain featue that
concentrates movement between two areas that would be interesting to them."
T10.17 made a funnel prove it is a BOTTLENECK. It could not ask what is on either side,
so a perfect neck between two barren rock outcrops was still a perfect funnel. What
concentrates moose movement is the shuttle between FOOD and SECURITY COVER — which is
the biology `behavior.py` already stated at the top of its own file: "bulls CRUISE...
terrain funnels between bedding cover and feeding/wallow complexes".
**Where it lives, and why it had to move.** `terrain.py` runs before `habitat.py`, so
when `funnel.tif` is written there is no browse and no cover to read. Terrain now
exposes `neck_sides()` — the cut machinery from T10.17 — and `behavior.py` uses the side
MASKS to score what each neck joins. Nothing between the two reads `funnel.tif` (habitat
does not; only synth and the contract do), so refining it there cannot desync the HSM.
**Two things measurement corrected:**
* **Means washed the answer out.** With a mean over the 1.5 km sample radius every
  multiplier on a real box landed between 0.36 and 0.74 — the layer uniformly halved,
  and the classic feed-to-cover neck scored barely above two sides of the same bog. That
  is a deflation, not a weighting, and it would have pushed funnels under the polygonize
  bar wholesale: the rev-21 mistake wearing a different hat. The 90th percentile answers
  the question actually being asked — is there anything worth walking to on that side.
* **The classic has to win by a visible margin.** At a 0.6 same-kind weight, two sides of
  identical cover scored 0.60 against 0.64 for the best real feed-to-cover neck. At 0.45
  the top four necks on that box are all "feeding ground to security cover".
**Reported, not just scored:** each funnel now carries `joins` — "feeding ground to
security cover", "two sides of much the same open ground" — because that is a claim a
hunter can check on the ground and reject. The description refuses to invent a
distinction it cannot see: below a 0.10 margin between feed and refuge it says the two
sides are much the same rather than dressing up noise as a finding.
**Deliberately floors rather than zeroes** (`DEST_FLOOR = 0.35`): a neck that survived
the linkage test IS a bottleneck whatever grows on it, and zeroing on habitat would
delete the layer over burnt or rocky country where the geometry is still true.

### T10.20 — Routes now say what they are TRAVELLED BY · `done` (2026-08-07)
Reported: "I indicated on setup i had an ATV/SXS. On the analysis, i can't see any
difference between routes to be travelled on ATV vs things to be walked... and it should
be able to chain sections of those together - and understand if you go from boat/atv to
walk, the boat/atv is going to stay where it is and not be available for future legs."

**It was worse than invisible.** Routes were computed on the WALKING cost surface and
then, if the hunter had an ATV, every cell that happened to sit on ridable ground was
labelled "atv" after the fact. Measured on his own run, every hunt route came back
`foot → atv → foot` — walk away from camp, board a machine parked in the middle of the
bush, ride, step off, walk on. And `route_access`, the leg you would most obviously ride,
had no modes at all.

**The rule, which is also what makes the search cheap:** the vehicle starts wherever you
do and stays where you step off it, so a leg has at most ONE vehicle segment and nothing
may be ridden after it. Enforced structurally by the router, not checked afterwards.

**Two things measurement corrected, both mine:**
* **Nothing rode at all** at first, because camp sat 715 m off the mapped trail network
  and the strict rule refused to start a ride there. Joe's rules settled it: a quad is
  co-located with staging and a vehicle reaches ANY hunt camp — so a bounded rough spur
  (1.5 km) encodes "it got here somehow" without becoming "quads go anywhere".
* **Then it rode 0.6 km and walked 4.2 km of ridable trail.** `_walk_cost` prices a road
  at 0.05 as a routing ATTRACTOR, not as effort, so ride costs set from honest effort
  (0.15/cell) were three times dearer than walking the same road. Ride costs are now
  priced against that surface (~5x cheaper than walking it, about the speed ratio).

**Result on his run:** hunt legs went from ~5 km walked to `atv 5.3–7.0 km → bushwhack
0.06–0.8 km`, the access leg is a single ride end to end, and each route carries
`km_by_mode` plus `vehicle_left_at` — where the machine actually spends the day, which
is neither camp nor the stand.

**Joe's rules, recorded because no data settles them:** ATV co-located with staging and
reaches any camp; a motorboat rides on the trailer so it launches only where a DRIVABLE
road meets water, not a quad track; a canoe is portaged and can reach water over trails,
roads and a short bushwhack.

**Display:** four modes now draw differently — ridden (solid amber, heavy), on the water
(solid blue, heavy), walked-trail (thin dashed), walked-bushwhack (dotted) — each with
its own legend row and count. The old rendering was a single 30%-opacity casing, which
is exactly why it read as "no difference".

### T10.21 — A portage is not an extraction route · `done` (2026-08-07)
Joe, setting the canoe rule for T10.20: "canoe... can be portaged betwene locations (but
routes like that might not be reasonable for extraction)."

T10.20 let a canoe reach water over a carry, which is right for getting IN. Coming out is
a different problem, and the model reported one `walk_km` covering both directions. The
pack-out read was worse: it ignored the route entirely and used straight-line distance to
the nearest road — a number that charges you for ground a boat or a quad carries the load
over for free, and that cannot see a portage at all.

**Now:** a foot leg adjacent to a boat leg is named `portage` and drawn heavier than a
bushwhack, because it is the worst ground on the route. Every route reports `carry_km` —
the distance walked UNDER LOAD, with water and ridden legs costed at one trip and a
portage at the loads PLUS the boat. Measured on a real quad run: 1.62 km of bushwhack
becomes **11.3 km under load**, while 7.18 km of quad costs nothing.

The pack-out read uses that when it exists and falls back to distance-to-road for plans
computed earlier, and it says so out loud when a portage is involved.

### T10.15 — The router could not see the trails the map draws · `done` (2026-08-07)
Reported twice in one session with screenshots: "It goes along one road and then
bushwacks to the location. But you could have just followed the road" and "Access line
follows road. Hunt line bushwacks for some reason" — the second showing a dashed trail
running to the waypoint and the red route cutting its own line through the bush beside it.

**The cause was one missing file.** `_linear_cost_layer`, which supplies the cheap-walking
tier, read `aq_trails.gpkg` and `aq_rail.gpkg` only, while `export.py` also DRAWS
`trails.gpkg`. The app was drawing a path to a place the router did not know how to walk
to. Share of the drawn network invisible to the router, measured across the cached runs:

| box | invisible |
|---|---|
| job_1a0c9d5b6618 (the reported one) | **46%** — 30.3 km of trail |
| job_0e92b5ca580d | 97% — no AQréseau sentiers on that box at all |
| job_8892f779ddc9 | 92% |
| job_20e209ca08d0 | 2% |

**The part that is not symmetric,** and getting it wrong would have swapped one wrong
answer for another: `aq_trails` is the official MOTORISED sentier network, while
`trails.gpkg` is OSM and on these boxes is entirely `path` (29) and `footway` (8). Both
beat bushwhacking on foot; only the first is something you ride. So the walkable set
grew (32.0 → 66.4 km on the reported box) and the ridable set did not. Feeding OSM
footways to the ATV network would have sent a quad down a hiking trail.

**IT CHANGED NO ROUTE ON ANY CACHED BOX, and that is worth stating rather than dressing
up.** The newly-visible paths sit 4.4–12 km from every remaining bushwhack, and T10.20
had already moved the legs that prompted the report onto the motorised network. This is
a consistency fix — the router now knows about the same lines the map draws — not a
measured improvement. The value is that the next box where a footpath DOES run beside a
stand is no longer routed as if the path were not there.

`test_router_sees_the_map.py` reads `export.py`'s own drawn-layer list and fails if
anything drawn as a trail or rail is missing from the walkable set, or if a footpath ever
leaks into the ridable one.

### T10.16 — The Sentinel window was frozen, and was compositing snow · `done` (2026-08-07)
Found while answering a basemap question; it outranked what prompted it, and then turned
out to be two bugs in one hardcoded line.

**The reported half.** `acquire/sentinel.py` read `datetime="2023-07-01/2024-09-15"` — a
literal — so the greenness behind every browse score was built from 2023–24 imagery no
matter when the analysis ran, ageing further every day it stood. Cuts and burns newer
than Sept 2024 were invisible to the greenness term, on ground whose whole browse story
is disturbance age.

**The half that was worse.** That window spanned a boreal winter, and scenes were ranked
by LOWEST CLOUD. Snow is not cloud — a snowfield reads as a beautifully clear scene.
Measured against the live catalogue: **3 of the 10 scenes composited over Fire Lake were
2023-12-08 at 87–93% snow**, and 2 of 10 over Rouyn were 2023-11-25 at 54%. Snow reflects
high in both red and NIR, so its NDVI collapses toward zero and drags the per-pixel
median with it. Removing those scenes moved mean NDVI **0.272 → 0.320 at Rouyn** (p10
0.149 → 0.225) and shifted **38% of the box by more than 0.05**; 12% of cells at Fire
Lake. The browse surface had been reading systematically LOW, silently, over more than a
third of some boxes.

**Fixed:** the search walks growing-season windows derived from the run date, newest
first, stopping as soon as it has enough scenes — so a box with good current cover never
reaches back a year, and one clouded out all summer degrades to last season rather than
to nothing. Snow-flagged scenes are rejected outright (>5%). The imagery dates land in
`ndvi.json`, reach the coverage manifest, and cost confidence when the freshest usable
scene is two or more seasons old. The geography cache keys on the imagery EPOCH, because
it keys on geometry alone and would otherwise serve one season's greenness forever —
which is how this went two years stale without anyone noticing.

**Measured after:** Rouyn now composites 10 leaf-on scenes all from summer 2026
(29 Jun – 3 Aug), NDVI mean 0.467. Fire Lake needs two seasons (2026 + one 2025 scene)
and lands at 0.325.

**Worth knowing:** the NDVI browse curve in `habitat.py` uses absolute breakpoints
(`(n-0.15)/0.5`, cover above 0.5) that are textbook LEAF-ON values — so correcting the
input moves it into that calibration rather than out of it. That is the argument, not a
measurement; see T10.19.

### T10.19 — Browse calibration re-checked against leaf-on NDVI · `done` (2026-08-07)
Opened as my own debt from T10.16, which moved mean NDVI on a real box from 0.272 to
0.467 by fixing a frozen, snow-contaminated window. The browse and cover curves it feeds
use ABSOLUTE breakpoints, so rev 21's lesson applied directly. My argument at the time —
that 0.15/0.65/0.8 "look like textbook leaf-on values" — was plausible and was not
evidence, which is why this ticket existed.

**Ground truth used:** the écoforestière stand map. It is surveyed, carries real species
and canopy closure, and is independent of NDVI, so it can say whether the curve ranks
ground the way people who walked it did.

**What it showed, on two boxes:**

| class | NDVI p50 | browse_n | browse FINAL |
|---|---|---|---|
| conifer | 0.41 | 0.53 | **0.000** |
| recent cut | 0.43 | 0.58 | **0.430** |
| mixed | 0.49 | 0.68 | 0.250 |
| deciduous | 0.56 | 0.78 | 0.200 |

The NDVI term is a **bad browse discriminator**, and two things about it are wrong on
their own terms: it scores closed conifer at 0.53 — moderate browse, for ground the
surveyors recorded as having nothing to eat — and it ranks mature DECIDUOUS above a
recent CUT, which is backwards for anything eaten at browse height. A fresh cut is bare
ground and slash; a mature stand is a wall of leaves; the cut reads lower. Land cover is
no better: +0.03 between cut and conifer against NDVI's +0.05.

**The breakpoints stay anyway, and now that is a measurement rather than an argument.**
Rev 21 put both terms in the LANDCOVER tier and the containment holds:
* where the stand map covers, it overrides outright — **+0.43** separation between cut
  and conifer, which NDVI and land cover together could not reach (+0.09);
* where it does not (north of ~52°N), NDVI carries 40% of that tier, and swapping the
  contaminated input for honest leaf-on moved browse on closed tree cover only
  **0.269 → 0.325**, with the fraction above 0.5 **unchanged at 6.1%**.

Re-deriving the curve would be tuning a term that is outvoted wherever it matters — and
no monotone NDVI→browse mapping can fix it, because cut sits BELOW deciduous in NDVI and
ABOVE it in browse.

**What now guards it:** `test_browse_precision.py` fails if the landcover tier is ever
promoted, if a surveyed source is dropped, or if the tiers tie. The curve's two known
weaknesses are pinned as tests too, so nobody re-opens the tiering believing this term
is sound. The measurements are recorded in `habitat.py` beside the constants.

**Left open:** the real fix for northern boxes is not a better NDVI curve, it is a
surveyed source north of the écoforestière limit. That is T5.1's territory.

### T9.10b — Decide the fine-grid neck detector · `blocked` *(needs Joe's ground truth)*
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

**2026-08-07 — the blocking anomaly is resolved, and it was never the terrain.** The
7 → 3 collapse was two constants in `neck_sides` denominated in CELLS: the cut reached
`+ 2` cells past the local half-width, and the ring that asks what the cut touches was
`iterations=2`. 80 m each on the 40 m analysis grid, 27 m on a 13 m fine one — the exact
"three cells / one cell" mistake `_constriction` documents at length, left standing one
function away. The error is not symmetric: a thinner cut fails to SEVER (thrown out as
"separates nothing") and a thinner ring TOUCHES fewer components (thrown out as a dead
end), so a finer grid was being pushed toward rejection twice over.

Measured on an 800×800 crop of `fire_lake` carrying the water vectors, fine grid 13.3 m:

| | candidates | kept | coarse cells the fine arm drops |
|---|---|---|---|
| before | 1937 → 2284 | 228 → **77** | 2595 (85%) |
| after | 1937 → 2284 | 228 → **436** | 717 (24%) |

The finer medial axis was always finding MORE candidates; the whole collapse was in
admission. Fixed, the fine arm retains 76% of the coarse necks and distinct widths go
19 → 98 with the floor dropping 113 m → 53 m. The fix is provably a no-op at
`res == grid_res`, so nothing shipping today moves (`tests/test_neck_scale.py`).

**Two things this did NOT settle, and they are why this is now `blocked` rather than
done:**

1. **Are the added necks real?** The fine arm gains 3007 cells at a median width of
   208 m, and only 16% of those are narrower than the coarse grid's 113 m floor — so
   most are not simply "necks the grid could not express". That is ground truth.
2. **The switch is inert on a real box anyway.** `FINE_BUDGET_PX` is 9 Mpx and a 35–45 km
   analysis grid is 3.1–6.5 Mpx, so the step floors to 1 and `FINE_NECKS=1` changes
   nothing in production. The decision with actual blast radius is whether to raise the
   BUDGET, which is a worker-memory measurement, not a modelling call.

The instrument is `scripts/ab_necks.py` — written down, not reconstructed.

**2026-08-07, later — both of those turned out to be work rather than decisions, and one
of them was another constant.**

*Memory.* The detector alone, peak RSS in a 4 GB container: 0.31 GB at 1×, 0.69 GB at 2×,
1.35 GB at 3× on a 3.1 Mpx box; 0.42 / 1.20 GB at 1×/2× on a 6.5 Mpx one. 4× on a mid box
is killed. Affordable — but this is the detector in isolation, not a full run with the
habitat stack live, so it is a FLOOR and not yet a verdict on the budget.
`scripts/necks_memory.py`.

*And a real defect fell out of it.* `_constriction` asks for a medial-axis window of
`3 * grid_res` metres and realises it as `maximum_filter(size=rw)`, which must be an ODD
cell count to be symmetric — so the exact count `3*step` is forced UP whenever it is even.
At 2× that turns the 120 m window into 140 m: 17% wider, a stricter ridge test, and FEWER
candidates on a FINER grid. Measured on fire_lake: candidates 9813 at 1×, **6966 at 2×**,
10463 at 3×. Even steps are now snapped down — a 2× grid measures worse than the 1× grid
it would replace. This is also what rouyn's 222 → 125 at 2× was, which had looked like the
old collapse returning.

*Places, not statistics.* `scripts/neck_disagreements.py` writes a GPX of the ten
highest-scoring necks the fine grid ADDS and the ten it DROPS, each with its measured
width — `outputs/neck_disagreements_fire_lake.gpx`. The pattern is favourable but is not
proof: adds score 0.74–0.83 at 138–304 m necks; drops score 0.35–0.50 and several are
2–7 cell fragments. **Caveat that matters: fire_lake is 52.34°N, −67.36 — it is the only
cached box carrying the water vectors the fine grid needs, and it is almost certainly not
ground Joe has walked.** Producing this list for his own country needs a run there first.
