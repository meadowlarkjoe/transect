# Transect — Expert Field Review (experienced DIY moose hunter)

Reviewer persona: 25+ yr DIY moose hunter, roadless boreal / northern Quebec–Labrador,
calls own bulls, packs own meat. Review of the current Transect feature set.

## Bottom line
Good bones. The habitat model, rut phenology, density-driven calling logic, and the
caller/shooter-downwind setup show real biology. But it's a **pre-trip planning tool
that will mislead if treated as a field tool**, and it models habitat well and
**sign / weather-trigger / logistics-reality poorly**. Moose are hunted on fresh sign,
felt wind, and where you can physically drag 500 lb of meat — most of that isn't in
the tool yet.

## Sound (keep)
- Density-driven strategy (low → call & cover ground; high → sit) — correct for Zone 19.
- Caller + shooter ~70 m downwind (bull circles to scent-check) — real woodsmanship.
- Latitude-adjusted rut, peak ~Oct 2; responsiveness curve concept.
- Thermal refuge midday + dawn/dusk feeding edges; aquatic/riparian emphasis.
- Confidence scoring (satellite vs stand data) — rare and excellent, keep front & center.

## Naive / will mislead
1. **Rut responsiveness is a date curve; real response is trigger-driven** — first hard
   frost / cold snap switches it on, warm fronts shut it off. Couple responsiveness to
   the actual forecast (cold-snap detection), not the calendar.
2. **Calling is one "aggressive" mode** — should be phase-aware (pre-rut cow whines/soft
   grunts; peak estrus + bull grunts/raking; post-rut back off) + "work it 30–45 min and
   MOVE, don't over-call" discipline.
3. **Wind: forecast wind is the least useful at dawn** — katabatic drainage/thermals win
   the dawn/dusk windows. Weight thermals over forecast wind for those windows; show
   forecast confidence (10-day interior QC forecast ≈ coin flip).
4. **Bull-vs-cow behavior absent** — at peak rut the bull is where the COWS are. Re-weight
   toward cow-concentration habitat (prime riparian/regen) at peak, bull-security cover
   early/post.
5. Temp thresholds fine but pair with overnight low / first-frost flag (the *change* matters).
6. Moon: fine to omit — don't build it at the expense of the weather-trigger feature.

## Missing (the decisive 60%)
- **SIGN + a feedback loop** — log fresh vs old tracks/droppings/browse/rubs and
  **wallows** (rut gold), and re-rank zones / upweight nearby calling stations. Biggest gap.
- **Burn-age & regen-age layers** (Canadian Fire DB / NBAC + NDVI time-series) — a 6–15 yr
  burn is a moose factory, a fresh burn is empty; decisive in this fire-scarred country.
- **Explicit meat-extraction / pack-out plan per kill site**, and DOWNGRADE great-call /
  bad-pack-out zones (a bull you can't get out before it sours = wasted tag).
- **Regs + safety layer** — Zone 19 season/sex/tag; **legality of scents/"saline sites"
  (baiting-adjacent!)**; no-cell mapping; sat-comm/InReach prompt; bear on gut pile;
  cold-water/hypothermia at crossings; Rte 389 fuel/last-services/weather.

## Field usability — currently ~80% desk toy
Route 389 / Fire Lake has **no cell signal**. An online-only web map is invisible during
the hunt. Needs:
1. **Offline-first** (tiles + computed layers cached before losing signal).
2. **GPX/KML export to OnX / Garmin GPSMAP+InReach / Gaia** — nobody navigates a canoe off
   a browser.
3. GPS "where am I on the plan" + record track (offline).
4. In-field sign/wallow pin capture (ties to feedback loop).
5. Glanceable "point into the wind for THIS station right now" readout.
6. Printable/PDF one-pager per focus area (battery-dead fallback).

## Top improvements (ranked, why it fills a tag)
1. Offline + GPX/KML export — the plan is invisible in the field otherwise.
2. Couple rut responsiveness to the weather forecast (cold-snap trigger) — don't burn
   mornings calling into warm dead air.
3. In-field sign logging + feedback loop — fresh wallow beats any polygon.
4. Explicit pack-out plan per kill site; downgrade bad-recovery zones — recoverable > callable.
5. Regs + safety layer — a tag or a life lost ends the hunt harder than being skunked.
6. Phase-aware calling + don't-over-call discipline.
7. Peak-rut re-weighting toward cow-concentration areas.
8. Burn-age / regen-age layers.

## Actively misleading / dangerous (fix first)
- **"Mock wallow / estrus scent" and "saline/feeding sites" recommended with NO regs check**
  — baiting-adjacent, varies by zone; default to WARNING not recommendation.
- **Over-confident green zones/sites on 7–10 day forecast + satellite-only cover** — never
  show confidence you don't have.
- **Date-based responsiveness %** presented as certainty — tie to weather or caveat hard.
- **Remote A+ zones with no meat-recovery / safety reality check** — spoilage & safety traps.
- **Forecast wind greening sites while ignoring dawn thermal drainage** — scent pours into
  the bog you're calling.
