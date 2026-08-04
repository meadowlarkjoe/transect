# Map-datapoint accuracy audit (#48)

Research-first audit of every calculated map datapoint: how the engine computes it
today, which assumptions are weak, the best-practice definition (cited), the data we
use vs. could add, and ranked recommendations. **No engine changes made** — this is for
you to read and prioritize. Each section was researched against the actual source and
the moose-ecology / hunting literature.

Datapoints covered: funnels · thermal refuge · thermal drift & wind/scent · glassing ·
rut/calling · saline/aquatic feeding · browse & disturbance-age · water crossings ·
access/routes/staging/camps.

---

## Executive synthesis — the patterns across all nine

**1. One data gap unlocks the most: the écoforestière layer (MRNF, south of ~52°N).**
`acquire/ecoforestiere.py` is a `NotImplementedError` stub, yet four datapoints are
crippled without it and its target values already sit in `config/species/moose.yaml` as
**dead config**:
- **Thermal refuge** can't see "conifer" or canopy closure (WorldCover lumps all trees).
- **Browse** can't see logging **cuts** or deciduous-vs-conifer regen (ticket #34).
- **Rut edges** fall back to a single-class tree/not-tree interspersion.
- **Funnels** miss forested/wooded wetland barriers.
Wiring this one WFS pull (same pattern as the working NBAC fetch) is the highest-leverage
data change in the whole audit.

**2. `ru.normalize()` keeps sneaking back in and breaks absolute scale.** The codebase
deliberately argues for fixed physical bounds (so "0.5" means the same in every AOI), but
the rut surface, the funnel term inside `hsm_rut`, and the behavior-engine refuge surface
all re-`normalize()` to per-AOI percentile ranks — the exact bug that made "huntability
0.85" mean "top of whatever box you drew." Thermal refuge was just fixed this way; the
same discipline needs to propagate.

**3. Several surfaces ride on one crude signal.**
- **Glassing = `normalize(dem)`** — pure elevation rank, no viewshed, no openness. Invents
  up to 4 "knobs" on flat closed-canopy ground. (A stale `viewshed` is even referenced in
  `cli.py` and `terrain.py` headers but never computed.)
- **Funnels** admit corridors up to **~1.4 km wide**, and place funnel *stands* at
  ~1.2 km gaps (the `min_score` floor is far too low) — no moose is funneled through that.
- **Rut edge = `4p(1−p)`** on a single WorldCover tree class in a 200 m box — can't tell a
  security-cover-to-opening seam (what a bull cruises) from a hardwood/conifer ecotone, and
  a 200 m blur destroys the sharp edge a caller actually sets up on.

**4. Water and wet ground are handled inconsistently, and one is backwards.**
- **Thermal refuge** *removed* water proximity ("feeding, not thermal") — but the
  physiology literature says wet substrate/standing water is the **strongest** cooling
  mechanism, more than canopy. That deletes cedar/black-spruce swamp refugia.
- **Crossings vs. walk-cost disagree**: `_walk_cost` makes all water impassable; `access.py`
  lets you ford streams. The drawn route refuses a crossing the ranking assumes.

**5. The pack-out — the thing that actually decides a DIY moose hunt — isn't modeled.**
Retrievability is `exp(-dist_road/2500)` on a cost surface where slope and land-cover are
absent, so a 600 lb haul straight up 25° through blowdown scores like a flat cutline. And
the "unpressured sweet spot" is mathematically unreachable (needs pressure weight > 0.6,
set to 0.25) — the output is, in the repo's own words, "a road-proximity map with habitat
texture."

**6. Missing high-value features the data already supports:** wallows (rut — the single
strongest attractant: wet × cover, buildable now), beaver ponds/flowages (feeding),
sun-relative + aspect-dependent thermal timing (drift), and a real disturbance-age driver
that includes cuts.

**7. Honesty gaps to close:**
- **"Saline / feeding"** flags a willow edge near water — no lick is detected. Rename.
- **Ford calls are stated with false confidence**; the downgrade ("you can wade this") is
  the direction that hurts people and gets the least hedging. Rapids/tidal channels are
  currently labeled fordable.
- **Thermal-drift** uses a fixed 08:00/17:00 clock, up to ~1.5 h wrong at the dawn window
  the app itself says "thermals win."

---

## Prioritized recommendations

### Tier A — quick wins, no new data (definition-level engine changes)

| Datapoint | Change | Why |
|---|---|---|
| Glassing | Prominence (TPI) × visible-openness over feeding habitat; allow **zero** points | Kills invented knobs; encodes "commands the basin *and* overlooks openings" |
| Funnels | Score full width (`2·db`) as a **local minimum**, tighten cap to ≤200–300 m, raise `min_score` | Stops handing hunters km-wide "pinch points" |
| Thermal refuge | Re-admit wet/lowland cooling as `max(wet_cool, aspect_cool)`; demote aspect from gate to bonus | Restores cedar/spruce-swamp refugia; matches physiology |
| Rut / calling | Absolute cover-vs-browse edge; **add a wallow term (wet × cover)** | The wallow is the strongest rut attractant and is currently ignored |
| Saline/feeding | Rename to "Feeding edge"; drive the "aquatic sodium" tooltip off the season weight; mask off open water | Removes the false-lick implication + module disagreement |
| Crossings | Route rapids/tidal to "do not ford"; add a fall-flow/cold-water caveat; harden the bridge test | Safety inversions today |
| Thermal drift | Sun-relative switch (sunrise/sunset), aspect-dependent flip, wind-vs-thermal dominance flag | Fixed clock is the single largest error |
| Access | Routed slope/land-cover pack-out cost; unify the two water models; re-site camp **off** the road | Makes the layer about meat, not proximity |
| Cross-cutting | Remove the re-`normalize()` in rut/funnel/behavior surfaces | Restores absolute, comparable scores |

### Tier B — data-dependent, ranked by payoff

| Data source | Unlocks | Effort |
|---|---|---|
| **Carte écoforestière avec perturbations** (MRNF WFS) | Conifer/closure (refuge), cut-age browse #34, real stand edges (rut/funnels) | Medium — same pattern as NBAC; the config already assumes it |
| **MRNF / Forêt ouverte forest-road network + class** | Road quality #32, truer (shorter) pack-outs, staging eligibility, ATV mode | Medium — the code's own TODO |
| **GRHQ hydrography** (Strahler order, perenniality) | Crossing difficulty band, beaver-pond/flowage feeding, forested-wetland funnel barriers | Medium — open Québec dataset |
| **MFFP inventaire aérien** (moose density/zone) | Validation & weight calibration (feeds #23/#49) | Low — offline zone join |
| **Québec LiDAR** (CHM, 1 m DTM) | True canopy closure, eskers/benches, viewshed on canopy surface | Heavy — later |

### Not worth doing
- Mineral-lick detection (no public dataset — claiming licks would be dishonest).
- Hourly wind-by-elevation mesoscale models (the repo's own review calls the 10-day
  interior-QC forecast "≈ coin flip" — poor ROI for a plan made weeks out).
- Aquatic-macrophyte NDVI detection (only relevant in the summer, out of the hunt window).

---

# Detailed sections

Each section: how it's computed now, the weak assumptions, the best-practice
definition, data (current vs. available), and ranked fixes.

---

## 1. Funnels / passes

**Current calc** (`terrain.py:55-101`): `funnel = max(constriction, 0.6·topo)`.
`constriction` is the medial axis (local ridge of distance-to-barrier) where barrier =
WorldCover water(80) ∪ herbaceous-wetland(90); score rises as the cell nears a barrier,
capped at `db < 700 m` (half-width → **~1.4 km full corridor**). `topo` is a DEM Hessian
saddle gated to slope 5–20°. Consumed by `hsm_rut` (`habitat.py:241`, re-`normalize`d),
site placement (`synth.py`, floor `min_score=0.12` ≈ a **~1.2 km gap**), and
`funnel_zones` polygons at 0.4 (`contract.py`).

**Weak assumptions:** (a) barrier field misses **forested/wooded wetland** (treed bogs,
cedar/tamarack swamp) — the dominant boreal soft barrier — and narrow rivers under one
pixel; (b) it scores absolute passage width, not a **local minimum** (a straight 300 m
isthmus lights up end-to-end); (c) thresholds admit km-wide gaps as "funnels"; (d)
"passable" is binary — cliff, dense conifer wall, and open browse are identical; (e) the
5° gate throws out **eskers/beach ridges**, the drained lanes moose use across muskeg.

**Best-practice definition:** a pinch point is where passable travel ground is
constricted to a **local-minimum width between barriers** at a scale an animal is
actually forced through. Movement-ecology defines this via least-cost-corridor / circuit
**current density** (McRae et al. 2013), validated for moose against GPS collars. Boreal
moose use **riparian/wetland corridors as travel highways**; the highest-value forms are
land-bridge/narrows between two water bodies, dry esker across wetland, ridge saddle, and
a neck where the travelable band pinches. Moose readily cross a few-hundred-metre gap, so
a funnel should key on **≤200–400 m full width**, not ~1.4 km.

**Data:** now — WorldCover water/wetland, DEM; OSM rivers are fetched but **not** fed to
the barrier field. Add — OSM rivers (already cached, zero cost), GRHQ hydrography +
MELCC milieux humides (forested wetlands), écoforestière (wetland stand types), LiDAR
DTM (eskers/benches).

**Top fixes (ranked):** 1) fix width semantics (`2·db`), detect constriction *ratio*,
tighten cap to ≤200–300 m, raise `min_score`/polygon threshold — **no new data, biggest
win**; 2) complete the barrier field (rasterize cached OSM rivers now; forested wetland
later); 3) move to a graded travel-cost / circuit pinch detector; 4) rehabilitate the
topo channel for eskers + true saddles coupled to barriers; 5) stop re-`normalize`-ing
funnel inside `hsm_rut`.

---

## 2. Thermal refuge

**Current calc** (`habitat.py:227-233`, just reworked): `thermal = dense·(0.10 +
0.90·coolp)`, `dense = ramp(cover, 0.60→0.85)`, `coolp = ramp(cool, 0.50→0.90) ·
slope_gate(slope/8)`. Absolute scale; polygonized at 0.5. **Flat ground can never reach
0.5** — refuge is, in practice, "dense forest on cool slopes only." `cover` is WorldCover
tree(10)=0.9 refined by NDVI — undifferentiated conifer vs. hardwood.

**Weak assumptions:** (a) cool aspect is made the **necessary gate**, but the largest
multi-population GPS study (Mumma et al. 2020) found **no support** for north-slope
selection — **canopy cover dominates**; (b) water/wet ground was **removed** ("feeding,
not thermal") — but physiology says **wet substrate/standing water is the strongest
cooling mechanism**, more than canopy (Thompson 2021, McCann 2013, van Beest 2012) — this
deletes cedar/black-spruce swamp refugia; (c) "dense cover" is **conifer-blind**
(WorldCover + Sept NDVI can't separate leafed hardwood from conifer), though
`moose.yaml` already specifies `cover_class: resineux, canopy_closure_min: 0.7`; (d) the
slope gate excludes flats — exactly where lowland-conifer refuge lives; (e)
`behavior.py:164` re-`normalize`s the surface, disagreeing with the absolute 0.5
threshold; (f) relevance is temperature-conditional (>~14–17 °C) but drawn as a static
polygon.

**Best-practice definition:** dense **mature conifer canopy (≥~50–70% closure)** made
usable as a midday retreat by **either (a) proximity to water/wetland or wet lowland
[primary], or (b) a cool N/NE aspect on sloped ground [secondary]**. Heat-stress onset
~14 °C, bedded ~17 °C calm / ~24 °C with wind (the `moose.yaml` thresholds are
well-calibrated). The model currently has this **backwards** (aspect mandatory, water
dropped) and can't see conifer.

**Data:** now — WorldCover, DEM slope/aspect, `dist_water` (computed but excluded), NDVI.
Add — **écoforestière** (species + `classe de densité` = closure; the highest-value add,
config already assumes it), LiDAR CHM (true closure), leaf-off/red-edge conifer proxy,
or a zero-data lowland-conifer proxy (tree ∩ near-wetland/low-TPI).

**Top fixes (ranked):** 1) re-admit wet/lowland cooling as `max(wet_cool, aspect_cool)` —
**zero new data, highest impact**; 2) demote aspect to a bonus (removes the flat-ground
exclusion); 3) stop `ru.normalize` in `behavior.py`, use the absolute surface; 4) make
conifer + closure the core of `dense` via écoforestière **(new data)**; 5) LiDAR closure
gate (optional); 6) gate the layer's salience on forecast temperature.

---

## 3. Thermal drift / wind & scent

**Current calc:** two disconnected systems. (a) The arrow field is **front-end only**
(`app.js:1686-1703`): DEM aspect → downslope bearing, flipped 180° on a **hardcoded clock**
`thermalRising = h>=8 && h<=17`; built on a ~2×-decimated DEM, Field-tab only, minzoom
11.5. (b) Forecast-wind site scoring (`wind.py`) is pure geometry (wind-in-your-face on
approach, ±45°) and never consults slope. The two never reconcile.

**Weak assumptions:** (a) fixed 08:00/17:00 switch **ignores sunrise/sunset** — in the
late-Sept/Oct QC window the 08:00 upslope flip is up to ~1.5 h late for the exact dawn
window the app says "thermals win"; (b) binary flip ignores the **transition window** (the
riskiest, directionless time); (c) every arrow flips at the same instant regardless of
**aspect** — but the flip is sun-driven, so east faces flip early and shaded N/W faces lag
hours (and N faces are the refuge slopes); (d) **no wind–thermal reconciliation** — a site
can be greened "wind-right" while katabatic drainage pours scent downslope into the
animal; (e) scale mismatch — sold as per-stand at z11.5 but computed on hundreds-of-metre
cells.

**Best-practice definition:** diurnal slope flow — daytime **anabatic** (upslope),
nighttime **katabatic** (downslope, ~10–30 km/h). Timing is **sun-relative and
aspect-dependent**: morning flip ~30 min–1 h after sunrise (aspect-varying), evening
downslope in the last ~30–45 min of light. Approach downhill AM / uphill PM; never set up
below the animal at dawn. **Prevailing wind >~20–25 km/h overrides thermals**; below that
thermals govern the dawn/dusk lulls. Moose olfaction is directional ("stereo") over long
range — scent discipline is the single highest-value output.

**Data:** now — decimated DEM aspect + clock hour; forecast wind (separate). Add (cheap,
high value) — **real sunrise/sunset + solar azimuth** (pure astronomy, no source), aspect
(already in DEM) for per-slope flip, and wire the already-present forecast wind into a
**thermal-vs-wind dominance** flag. Skip hourly mesoscale wind (poor ROI). *Note: ticket
attribution "#27" is wrong — GH #27 is unrelated; the per-position time-scrubbed idea
lives in `hunter-review.md:56` / `design-improvements.md:12`.*

**Top fixes (ranked):** 1) sun-relative switch timing (replaces the 08/17 clock) — no new
data, largest error; 2) aspect-dependent flip; 3) reconcile thermals + forecast wind into
one dominance flag feeding site-greening; 4) show the transition window as uncertain;
5) honest resolution (finer DEM or relabel as valley-scale); 6) encode thermal strength.

---

## 4. Glassing points

**Current calc** (`synth.py:443`): `glass = normalize(dem)` masked to huntable ground —
**the entire definition**. Top-k highest cells per focus area (`peak_local_max`). **No
viewshed, no line-of-sight, no openness** — though `cli.py:94` and the `terrain.py` header
reference a viewshed that is never computed.

**Weak assumptions:** (a) "highest = best" is false on flat boreal ground — the "peak" may
be metres of relief and confer no advantage, yet up to 4 points are still emitted; (b)
value is **what a point overlooks**, not its height — a high cell in closed canopy scores
max and is useless; (c) no **prominence/relief** term (absolute elevation, not height above
the basin); (d) per-AOI `normalize` again; (e) static advice ("glass the openings from
high ground") even with no openings in sight; no sun/wind.

**Best-practice definition:** a locally **prominent** cell (height above the basin it
overlooks) with **broad line-of-sight over open, glassable feeding habitat**
(willow/wetland/regen-cutblock/burn edge) within optical range, positioned to keep
morning/evening **sun at the glasser's back**, off the skyline, reachable without blowing
scent into the basin. "A little elevation to peer *down into the willows*" (MeatEater);
"overlook large expanses of willow" (ADFG). In flat/forested country the honest answer is
often **no glassing point** — the tactic degrades to calling/still-hunting.

**Data:** now — DEM only. Available unused (no new acquisition) — `tpi.tif` (prominence),
`cover`/neighbourhood tree-fraction (openness, already at `habitat.py:189`), landcover /
wetland / burn (what's visible), wind. New/heavier — a **true viewshed** (GDAL
`ViewshedGenerate` or vectorised LOS, feasible on a shortlist of candidates), or LiDAR CHM
for canopy-aware sightlines.

**Top fixes (ranked):** 1) replace raw DEM with `normalize(tpi_pos) · visible_openness`
over feeding habitat — no new data; 2) add a `min_score` floor and **allow zero**;
3) score by glassable feeding habitat within ~0.8–2 km; 4) fix per-AOI normalization
(fixed bounds); 5) conditional advice with sun/wind; 6) true viewshed only if 1–3 prove
insufficient (and on a canopy surface, not bare-earth, or it over-promises).

---

## 5. Rut / calling sites

**Current calc** (`habitat.py:235-243`): `rut = edge·(0.40 + 0.30·norm(funnel) +
0.30·wet_prox)`, re-`normalize`d. `edge = 4p(1−p)` on WorldCover tree class, 200 m window.
Placement `synth.py` scales with party size; **phase weighting** (`rut_timing.py`) shifts
site counts and tactics across seeking/peak/post — that temporal model is **sound**.

**Weak assumptions (all spatial):** (a) `edge` is single-class tree/not-tree — can't tell
a **security-cover-to-opening seam** (what a bull cruises) from a hardwood/conifer
ecotone, though `cover` and `browse` surfaces exist two blocks up; (b) the **200 m box
blurs** the sharp edge a caller sets up on; (c) `wet_prox` rewards nearness to any water
but **omits wallows** — the strongest rut attractant; (d) double `normalize` ranks mosaic
noise; (e) the 0.40 floor makes edge the sole gate and caps funnels at a 30% bonus, even
in the seeking phase when bulls travel corridors; (f) no wind/downwind term (bulls circle
downwind).

**Best-practice definition:** the feature is a **structural cover↔opening seam**
(security timber against low regen/opening), plus **wallows** (wet depressions with
bull-urine pheromone — "extremely difficult to resist at peak"), with **wind** governing
the setup (call into/crosswind; bull circles downwind). Regenerating cuts are prime rut
ground (they grow the browse that concentrates cows). Seeking = cold-call funnels/edges &
keep moving; peak = hunt where the cows are; post = soft calls at feeding sign.

**Data:** now — WorldCover edge, funnel, wetland proximity. Add — **wallow terrain (wet ×
cover, fine scale — feasible now, highest-value)**; écoforestière stand edges + cutblocks;
downwind-huntability if a wind vector exists; MFFP harvest density as a coarse per-zone
prior only.

**Top fixes (ranked):** 1) redefine `edge` as absolute cover-vs-browse contrast; 2) **add
a wallow term**; 3) rebalance so funnels aren't capped at 30% and let **phase reshape the
surface**, not just counts; 4) écoforestière edges/cuts (new data); 5) downwind term.
Temporal model needs no change.

---

## 6. Saline / aquatic feeding sites

**Current calc:** `saline_blind` points come from a feeding surface — **nothing saline**.
`feed_surf = b_feed` (`behavior.py:156`: browse × cover/opening edge × water term) or
fallback `hunt·exp(-dist_water/400)`. The aquatic-sodium multiplier `aq`
(`behavior.py:78`) **decays to ~0 by Sep 20**, so for a real hunt it's a browse-edge sit.
No lick, seep, or soil-sodium data exists anywhere.

**Weak assumptions:** (a) the **"Saline" label is inaccurate/dishonest** — a hunter
expects a flagged lick; the app flagged a willow edge; the internal key `saline_blind`
fuses lick+blind, neither computed; (b) the placed-point tooltip says "aquatic sodium"
**year-round** even though the module zeroes it in-season — the two disagree; (c) points
can land on **open water** (fallback maximizes as dist_water→0); (d) `edge` is a coarse
proxy.

**Best-practice definition:** moose are crepuscular ("first & last light" is sound);
**aquatic feeding is real but strongly seasonal (late spring–summer)** — shallow bays,
**beaver ponds**, slow streams with sodium-rich macrophytes. By the Sept/Oct hunt it's
**over**; in-season these are **browse-edge / riparian-willow** sits. Legally, a *saline*
(salt/mineral lick) is **regulated and zone-specific** in Québec (and natural moose-urine
sale is prohibited as of April 2026) — the honest posture is the existing `scent_warning`,
not a recommended salt site.

**Data:** now — WorldCover, NDVI, OSM water, burn, DEM. Add — **beaver-pond/flowage
detection via GRHQ hydrography** (the single defensible upgrade). Do **not** attempt
lick detection (no dataset).

**Top fixes (ranked):** 1) **rename** to "Feeding edge (dawn/dusk)" in legend/app/key —
fixes the honesty problem at the root; 2) drive the tooltip off the season weight; 3) keep
salines out of the recommendation, keep the warning prominent; 4) mask points off open
water; 5) beaver-pond weighting via GRHQ; 6) no lick detection.

---

## 7. Browse / forage & disturbance age

**Current calc** (`habitat.py`): WorldCover class weights (`BROWSE_LC`: shrub 1.0, grass
0.7, wetland 0.6, **tree 0.2 flat**) refined by NDVI, **overridden by a burn disturbance-age
curve** (NBAC; near-0 <5 yr, plateau 18–22, 0.45 @35, 0.10 @200) and a water-proximity
term at HSM weight 0.25. The rich `cover_types` browse curve in `moose.yaml` is **dead
config** (écoforestière stub). **Logging cuts contribute zero** unless WorldCover happens
to call them shrub (ticket #34).

**Weak assumptions:** (a) **cuts are invisible** — burns get a validated curve, equal-age
clearcuts get 0.2; in commercial-forest QC, logging (not fire) makes browse — the biggest
gap; (b) all forest = 0.2 flat, discarding feuillus/mélange/résineux; (c) shrub = 1.0
uniformly (willow regen and ericaceous heath scored alike); (d) NDVI is summer canopy
greenness, not winter twig biomass at moose height; (e) water at 0.25 as a forage magnet
is **season-mismatched** (aquatic feeding peaks in June, not the rut) and treats a deep
lake like a sodium-rich flowage.

**Best-practice definition:** preferred browse is **deciduous** — willow, birch, aspen,
mountain-ash, mountain-maple, red-osier, hazel (conifer is a snow-depth fallback). The
post-disturbance curve favours **~10–30 yr** regen (moose positively associated 6–35 yr,
negative >35 yr) — suggesting a **wider productive plateau and gentler post-27 decline**
than the current curve, and cuts differ from burns (deciduous suckering vs. planted
conifer). Aquatic feeding is **sodium-driven, seasonal, and site-selective** for shallow
productive ponds.

**Data:** now — WorldCover (single stale epoch), NDVI, NBAC. Add — **écoforestière avec
perturbations** (dated cuts + species/age/density — the logging-cut layer, #34); MFFP
inventaire aérien density for curve calibration (extends the existing r=0.62 zone-19
validation).

**Top fixes (ranked):** 1) **build the cut layer (#34)** and feed cut-age through the
same disturbance-age curve as burns (unified years-since-disturbance) — biggest gap;
2) split deciduous vs conifer instead of tree→0.2; 3) recalibrate the age curve vs local
inventory (widen plateau, soften decline); 4) make aquatic/water season- & productivity-
aware (reserve it for shallow ponds/flowages, tag summer); 5) fix shrub over-credit &
epoch staleness.

---

## 8. Water crossings

**Current calc** (`contract.py:546-696`): route ∩ waterway → crossing points, classified
by a 3-branch tree — road `bridge=yes` within 30 m → **bridge/measured**; else stream →
**ford/inferred**; else river/canal → **boat/inferred**; lake-shore always boat. Each
carries a `basis` (measured/inferred) honesty tag.

**Weak assumptions:** (a) the promised **"TAGGED/ford" middle tier doesn't exist** —
`FORD_WIDTH_M` is dead and `roads.py:115` **drops** the `ford`/`width`/`intermittent`
columns before `contract.py` sees them; (b) **`waterway` class = difficulty** — an OSM
"stream" can be chest-deep and fast; (c) **rapids and tidal channels fall into the ford
bucket** — a safety inversion (never ford a rapid); (d) the 30 m bridge test doesn't
verify the bridge spans *this* water; (e) **no depth/velocity/bottom/season** — yet the
season is fall, when levels rise and cold water turns a failed ford lethal; (f) the
**ford downgrade is stated flatly** while boat calls get hedged — the dangerous direction
gets the least caution.

**Best-practice definition:** hazard is **depth × velocity**, not class. Knee-deep is the
practical solo limit; above thigh = find another way; if a floated stick outruns a walk,
too fast. **Strainers** (submerged wood) are a top killer; **rapids: never ford**. Fall
rain/snowmelt raise levels feet-per-hour and cold water causes cold-shock "in minutes."
**Strahler order** is a recognized width/discharge surrogate.

**Data:** now — OSM waterway class + `bridge=yes`; WorldCover water (unused here). Add
(a width/flow proxy **without** OSM width) — **GRHQ / GRHQ-HR** (native Strahler/Horton
order + perenniality — top pick, QC-native), **MERIT Hydro** (actual river-width raster,
coarse fallback), HydroSHEDS flow-accumulation, or DEM-derived flow accumulation
(zero new dependency).

**Top fixes (ranked):** 1) replace the class-driven ford/boat binary with an **order- or
width-based band** (GRHQ Strahler + perenniality; MERIT fallback); 2) **rapids/tidal →
"do not ford"** — immediate, no new data; 3) add perenniality + a fall/cold-water caveat;
4) resolve the phantom TAGGED tier (widen kept columns or delete dead code); 5) harden the
bridge test (must intersect the water; separate footbridges); 6) frame fords as
**uncertain, never confident**.

---

## 9. Access, routes, staging & camps

**Current calc:** walking-friction (`synth.py:688`) `cost = 1 + slope/10`, +3 for
wetland (**the only land-cover term**), roads = 0.05, water = impassable. Staging = one
pin per area at its nearest road cell. Base camp (`synth.py:511`) `exp(-access/600) ·
exp(-dist_water/500) · hunt` — **pulled toward the road**. Routes are camp→stand
least-cost *approach* only. Retrievability (`access.py`) = `exp(-dist_road/2500)` on a
cost surface where **slope & land-cover are absent**; `huntability = hsm · retrieval`.
Roads rasterized to a **uniform 1** (no class/surface). `validate_ground` = the
huntability **argmax** (verifies nothing new). ATV mode declared in config but **never
modeled**.

**Weak assumptions:** (a) the **pack-out isn't routed** — the loaded haul (kill→road) is a
smooth road-distance decay ignoring slope/land-cover, so 600 lb up 25° = a flat cutline
— the largest gap; (b) **two inconsistent water models** (walk-cost impassable vs.
access.py fordable streams); (c) roads are **binary** — Route 389, a graded main, a rough
two-track, and a washed-out winter road are all 0.05 and valid staging; (d) camp is sited
**toward** the haul road, opposite to field practice (camp off it), with no flat/dry/legal
check; (e) `validate_ground` restates the best pixel instead of probing the weakest
assumption; (f) slope is nearly inert and symmetric (no loaded-downhill penalty); (g) the
**"unpressured sweet spot" is unreachable** (needs pressure weight >0.6, set to 0.25) —
"a road-proximity map with habitat texture."

**Best-practice definition:** the objective is **"retrievable meat before it spoils,"**
not "close to a road." A bull can exceed 1,000 lb → **7–9 back-pack loads at <1 mph** →
proximity to motorized access (ATV/boat/truck) and cool weather should **gate whether a
spot is even huntable**; experienced DIY hunters apply hard retrieval rules ("recoverable
> callable"). Multi-modal extraction (canoe/jet-boat/ATV/Argo/truck, chained) is normal.
Québec law requires removing all edible flesh + 48 h registration — a plan that strands
meat is **non-compliant**. Camp near water, central, but **off the main haul road**, on
legal Crown-land.

**Data:** now — OSM roads (uniform), DEM slope, water/wetland. Add — **MRNF/Forêt ouverte
forest-road network + class** (authoritative, far more complete than OSM in remote QC;
fixes under-counted spurs that inflate pack-out distances; enables road quality #32 and
winter-road exclusion); OSM/provincial **trails + ATV** layers; reuse DEM+land-cover for a
real anisotropic haul cost (zero new data).

**Top fixes (ranked):** 1) **routed, slope- & land-cover-aware pack-out cost**, reported as
"N loads × distance ≈ X hard days" — makes the layer about meat; 2) ingest the MRNF
forest-road network + class, stop treating roads as binary (fixes spurs + #32); 3) unify
the two water models; 4) fix the pressure constant (or split habitat/access into two
reported axes); 5) re-site camp **off** the road with legality/dryness; 6) redefine
`validate_ground` as an uncertainty probe; 7) model the declared ATV mode.
