# Moose Scout — research findings → model roadmap (2026-08-03)

Distilled from a literature sweep + a biological/statistical audit of the engine + a
front-end audit. Full agent outputs archived in the session tool-results.

---

## A. Findings that CONTRADICT what the engine currently does

| # | Engine does | Research says | Action |
|---|---|---|---|
| 1 | `rut_timing._lat_shift_days` shifts peak ~0.7 d/°N (±6 d) | **Latitude does NOT shift rut date.** Median conception = **2 Oct at 47.5°N (ND)** and **2 Oct at 63.5°N (Denali)** — 16° of latitude, zero shift. Alces geographic review: mating everywhere in 23 Sep–8 Oct. | **Delete the latitude shift.** Anchor peak at **Oct 2**, σ ≈ 6.5 d (from SD 4.5–8.0). |
| 2 | `behavior.py:114` weights feeding by `(0.35+0.65·sodium)` where sodium = dist_water | **Aquatic feeding runs ~June–mid Sept and is over before the season.** Moose get 94–96% of Na from aquatic plants, but use declines from late July. | **Zero the aquatic term after ~Sept 15.** Keep ponds as *corridor + riparian browse + acoustics*, not forage. |
| 3 | `access.py:181` blends toward **rut terrain** (edge×funnel) at peak rut | **At peak rut the sexes aggregate and bulls adopt cow habitat.** Mature bulls **stop feeding ~Sept 18–20** (Miquelle 1990). Oehlers 2011: sexes select similarly during rut, differently in spring. | **Blend toward a COW habitat surface at peak**, not terrain. Drop browse weighting for mature bulls after ~Sep 18. |
| 4 | `refuge_weight` ramps on fixed 14→20 °C | **14 °C (Renecker & Hudson 1986) is obsolete.** Same animals: threshold ≈15 °C spring vs **24 °C summer** (Ditmer 2018) — acclimatization-dependent. No autumn value published. | Keep the ramp shape; treat thresholds as **provisional**, add **solar load** (slope×aspect×sun angle×canopy) which matters more at Fermont's 4–12 °C October highs. |
| 5 | Model implies wallow prediction (`wallow_twi_min`, brief text) | **No peer-reviewed spatial ecology of wallows exists.** No density, no re-use rate, no terrain correlates. "Re-used yearly" is forum lore. | Predict **wallow-suitable ground** (mid-band TWI × cover adjacency × cow patch), label "inferred — no literature support", and collect user pins. |
| 6 | — | **Barometric pressure has no evidentiary basis in any cervid literature.** "Cold front" is a **temperature effect wearing a costume**. | Never implement barometric. Implement cold fronts as **temperature anomaly** only. |

## B. Findings that give us NEW, locally-validated signal

- **Old burns are the #1 predictor, validated in Zone 19 itself.** The 1988 MLCP zone-19 aerial survey found old burns (mixed/deciduous) correlate with moose numbers at **r = 0.62, p < 0.01**. Nothing else has this effect size + geographic specificity.
- **Disturbance-age curve** (well-established): use peaks **~15–22 yr**, avoided **0–8 yr** (browse below reach, no cover), declines after ~25–30 yr. Density peaks ~15 yr post-burn then declines ~9 %/yr. Carrying capacity **4–9 moose/km² well-regenerated vs ≤0.2 poorly regenerated** — so **age × regeneration composition**, not age alone (bluejoint grass exclusion: 150→1,350 kg/ha moist, 700→3,600 wet).
  - Data: **NBAC / Canadian National Fire Database** (free, burn year, national) — north of 52°N where écoforestière fails.
- **Zone 19 density ≈ 0.43 moose/10 km²** (1988 survey, 7,809 ± 2,260 over 225,210 km²) ⇒ **~20 km² per moose**. Strategy consequence: **sitting is near-hopeless; the objective function is COVERAGE**, not pixel-picking. Build a multi-stop calling-circuit optimizer.
- **Diel: the afternoon peak is ~15:00–16:00 — 1.5–2.5 h BEFORE dusk**, not last light (Hjort 2020, 622 GPS moose). Actionable: be in position early afternoon.
- **Rut home ranges** (Sweden, kernel): north male **3,498 ha** vs female **1,510 ha** (2.3×). Bulls **expand**, they do **not** make whitetail-style excursions. ⇒ model cow patches (~5 km²) as anchors and bull reachable-set (~35 km²) spanning 2–4 cow patches; **bull search corridors = least-cost routes between adjacent cow patches.**
- **Cow-calf avoid fresh cuts, hard**: detection prob **0.24** (cut <10 yr) vs **0.83** (11–25 yr) vs **0.94** (unsalvaged) — Thomas 2025. ~4× effect.
- **Road avoidance is 75–100 m for forest roads** (Québec, Gagnon 2024), not 500 m; ≥500 m only for high-traffic highway. Avoidance **relaxes at night**. Road-density response threshold ~0.2 km/km² summer.
- **Hunting displacement is contested** — best Swedish GPS study is literally titled "The non-impact of hunting on moose movement." Response is mainly **temporal (day→night)**, not large-scale flight. Don't over-model it. The useful product is **"where are other hunters not"** = cost-distance from access, sweet spot ~2–6 km walking cost.
- **Calling: zero peer-reviewed response-rate data exists.** "Carries 5 miles" is fabricated. Do NOT output a "% chance a bull responds." What IS real: bull grunts are lowest-frequency (propagate furthest); dawn/dusk **temperature inversions extend audible range 2–3×**; wind creates a downwind lobe / upwind shadow. Human voice at 60–70 dB **flushes 75 % of moose** (Bhardwaj 2022) — noise discipline is evidence-based.
  - ⇒ Model **acoustic reachability**, score a setup by `∑(call_reach × cow_habitat_probability)`.
- **Predation: near-null for adult moose.** 20-yr before/after wolf experiment (Sand 2021): clear-cuts p=0.97, young forest p=0.79, old forest p=0.89 — only bogs declined. Don't build a landscape-of-fear layer.
- **Second estrus lands ~27 Oct — after the season.** Don't model a second-rut bump in the huntable window.

## C. Engine audit — what the model actually is

> "A weighted blend of ESA WorldCover class codes, distance-to-water, and DEM curvature,
> percentile-stretched seven times, multiplied by an exponential decay from roads."

Critical defects:
1. **Claims capabilities it does not have.** `synth.methodology()` tells the user browse comes from "cutblocks/burns 5–25 yr"; `confidence.py` emits "Stand-level écoforestière vegetation coverage" for every southern AOI. **`acquire/ecoforestiere.py` is a `NotImplementedError` stub.** No stand age, no burn age. ~60 % of `moose.yaml`/`model.yaml` is dead config never read by any code.
2. **`normalize()` (p2/p98) applied 7× in a chain** ⇒ every score is a **within-AOI rank**. "huntability 0.85" is not comparable across AOIs, or even to a `deep_areas.py` sub-box of itself. Legend thresholds mean **31 % of every AOI is always "high."**
3. **Access dominates.** `hunt = hsm_phase · extraction · (1−0.25·pressure)`; extraction spans ~4 decades while habitat spans [0,1]. At the rank-1 area's 11 km from road, extraction = **0.012** vs 0.67 at 1 km — a 55× multiplicative penalty. **The huntability map is a road-proximity map with habitat texture.**
4. **The advertised "unpressured sweet spot" is mathematically impossible** with current constants: an interior optimum requires `pressure_weight > road_decay/extraction_decay = 0.6`; it's set to **0.25**, so the model always prefers roadside.
5. **`edge` measures mixture, not adjacency** — a checkerboard scores the same as a clean seam; and WorldCover is resampled `nearest` 10→40 m, destroying the 10–60 m seam before measuring it.
6. **`funnel` is Hessian noise** on ≤2.5° slopes — and it propagates into hsm_rut → cruise → rut_calling sites → funnel_zones shipped to the app.
7. **Zero validation.** The MFFP harvest CSV is downloaded and used only as a display string; `sources.yaml` even states the intent ("validate HSM against real kill density").

## D. Front-end audit — the engine is ~2× smarter than the screen

Broken:
- **Wind-fit rendering doesn't exist.** Legend promises a green ring; `windok` is computed but no layer reads it. The day picker visibly does nothing.
- **Real routes are never drawn.** `DOC.routes` (370–1090 pts, terrain-following) exists but the map draws **fantasy straight lines** camp→centroid instead. Crossings anchor to invisible lines.
- **Dead heat pipeline** (~60 lines) targeting a source that's never added.

Computed and wasted: `behavior.periods` (the "what do I do now" cards), rut weekly calendar, `strategy.stand_minutes` (UI says 30 min, model says 45), per-area `packin_km_by_area`, sunrise/sunset + `t_min`, `legal.season_summary` + the Zone-19 sud/nord warning, `confidence.caveats`, density estimate + source.

Unanswered hunter questions: "where this morning vs midday given wind+temp", "which area on which day", **"how do I get 600 lb out"** (no packout math at all), "what changes if it's warm", "I found a wallow — now what".

Field reality: **offline = dead app** (all tiles/glyphs/geocoding remote, no service worker), GPX loses the intelligence (no `<sym>`, no wind notes), no print stylesheet, no geolocation, no mobile breakpoints.

---

## E. Prioritized plan

**Tier 0 — honesty (hours).** Strip claims we can't back: stand-age/burn language in `methodology()`, the false écoforestière confidence driver, wallow instructions with no wallow layer, viewshed/wind-conditioned-route claims in docs. Fix the 30-vs-45 min contradiction.

**Tier 1 — highest value.**
1. **Burn-age layer from NBAC** + age-response curve (peak 15–22 yr, ~0 below 8 yr). The one locally validated predictor (r=0.62 in zone 19).
2. **Absolute scale**: normalize once, on fixed physical bounds — makes scores comparable and the legend meaningful.
3. **Split habitat from access**: report "A+ habitat, 11 km pack-out" as two axes instead of multiplying a 4-decade exponential into the habitat score.
4. **Fix rut model**: drop latitude shift, anchor Oct 2 σ6.5; blend toward **cow habitat** at peak; kill aquatic weighting after Sept 15.

**Tier 2 — front-end (mostly free, data already computed).**
5. Fix wind-fit rendering; draw the **real routes**, delete the fake straight lines.
6. **"Today" card**: sunrise/sunset + temp vs thresholds → the matching `behavior.periods` + wind-right sites.
7. **Packout reality line** on every area: "kill here ⇒ 11 km ⇒ 5 loads ≈ 2 hard days."
8. Day × area planner grid; rut calendar sparkline; surface confidence/density where decisions happen.

**Tier 3 — new capability.**
9. Coverage/route objective (calling circuit optimizer) — correct for 20 km²/moose.
10. Acoustic reachability model (viewshed × wind lobe × inversion bonus).
11. Field sign logging → validation data → Boyce index. 20–50 kill/sign points is enough.
12. Offline tile pack.

**Validation before more tuning:** null-model benchmark (free, one afternoon) — does the full HSM beat `−dist_road` alone? Then zone-level regression against the harvest CSV already cached.
