# Validating the model against reality (#63)

Every audit so far — #48 through #51 — checked whether the code does what it *intends*.
None asked whether the intention is **correct**. The engine says this ground is better
than that ground; nothing has ever tested that claim against animals.

This is the design for that test, the ground truth that exists, and the wall it currently
hits. Written down because the design turned out to matter more than the data hunt, and
because the next person to try this should not repeat the search.

---

## The design correction that matters

The obvious test — *"does huntability correlate with harvest?"* — is **wrong**, and would
have produced a confident false positive.

Harvest reflects **hunter effort at least as much as moose density**. Zone 01 (Gaspésie:
roaded, close to population) tops the harvest table at ~5,500 animals; zone 17
(Nord-du-Québec) sits near the bottom at a measured density of 0.52 moose/10 km². That
ordering is substantially about access, not habitat.

And `huntability` **deliberately contains an access and pressure term**. So correlating
huntability against harvest would partly be correlating an access model against an access
artefact — a strong result that says nothing about whether we understand moose.

**So: validate the HABITAT surface (`hsm.tif`) against DENSITY, not `huntability.tif`
against harvest.** Access is the thing being controlled for, not the thing being tested.

A useful second experiment falls straight out of that: if habitat predicts density and
huntability predicts harvest, the model is doing both of its jobs. If huntability predicts
harvest but habitat does not predict density, the engine is an accessibility map wearing a
biology costume.

---

## Ground truth: what exists

| Source | Form | Resolution | Usable? |
|---|---|---|---|
| Moose harvest statistics | **CSV, machine-readable**, 1971–2025, by zone/year/sex/weapon | hunting zone | ✅ already fetched by `acquire/zones.py` |
| Aerial inventory density | per-zone **PDF reports**, stratified random sampling on a 60 km² parcel grid, density ± CI | hunting zone | ⚠️ PDFs only, and the mffp.gouv.qc.ca URLs now 404 after the ministry reorganisation |
| Hunting-zone boundaries | **not published as open geodata** | — | ❌ blocker (see below) |
| Tenure (pourvoirie/ZEC/réserve) | TRQ ArcGIS MapServer, 17 layers | polygon | ✅ already integrated |

Checked and ruled out for zone boundaries: `TRQ_WMS` (tenure only, no zones),
`Tirage_au_sort_WFS` (a single "Terrains" layer), and the MRNF service catalogue
(`Territoire` folder — 33 services, none of them hunting zones).

### The methodological catch in the inventory data

The inventory's **strata are built from harvest density**: *"Une stratification du
territoire a été réalisée à partir des résultats de chasse sportive de 2019 à 2021
(densité de la récolte moyenne sur 3 ans)."*

So inventory density and harvest density are **not independent of each other**. They are
both independent of *our* model, which is what this test needs — but they cannot be used
to cross-validate one another, and a result that agrees with both is one result, not two.

---

## The blocker

**Without zone boundary polygons there is no denominator.** Harvest counts cannot become
harvest *density*, an AOI cannot be reliably assigned to a zone (the engine currently uses
a hand-checked `zone_hint`, which `zones.py` already flags for verification), and a
zone-level correlation has no x-axis.

Ways forward, cheapest first:

1. **Ask.** `geoboutique@mrnf.gouv.qc.ca` distributes the recreational-territory layers;
   hunting zones may be available on request or under a licence.
2. **Digitise from the published zone maps.** Québec publishes hunting-zone maps as PDF /
   image. Coarse, manual, and good enough for a *zone-level* correlation — the zones are
   enormous and their exact edges do not change the mean of anything.
3. **Skip zones entirely** and use the inventory **parcels** (60 km², 10 × 6 km) as the
   unit, if a report's appendix carries parcel coordinates. Far better resolution, and
   much closer to the scale a hunter actually plans at.

---

## The resolution problem, stated honestly

| Unit | Scale |
|---|---|
| Hunting zone | 5,000 – 50,000 km² |
| Inventory parcel | 60 km² |
| A Transect AOI | ~5,000 km² (70 km box) |
| A model cell | 40 m |

A zone-level test can validate **ranking across regions** and calibrate the **absolute
scale**. It can say nothing about whether an individual stand is good. Any writeup of a
zone-level result must say that in the same breath, or it is overselling by a factor of a
million in area.

Parcel-level (60 km²) would be a genuinely useful resolution and is worth the effort of
chasing.

---

## What this is also the gate for

Native 10 m class fractions (#77/#78) moved the model's **dominant** term — cover↔food
interspersion — from:

| | mean | p90 | cells > 0.5 |
|---|---|---|---|
| before (categorical, one pixel in sixteen decided the cell) | 0.033 | **0.000** | 3.7 % |
| after (measured areal fractions, food-paired) | 0.248 | 0.859 | 24.3 % |

A p90 of **zero** means the old term was effectively dead across 90 % of the AOI, for the
input weighted most heavily. The old number was clearly broken. Whether 24 % is *correctly
calibrated* is a biology question, and the honest answer is that nobody knows yet — which
is exactly why tuning it further by eye would be fitting the histogram to my taste rather
than to moose.

Pairs with **#23** (null-model harness): once ground truth exists, the real question is
whether the model beats a dumb baseline — *"close to a road and near water"*. If it does
not, that is worth knowing before anyone hunts on it, and certainly before it is shared
publicly.

**A null result is a real result here.** If the model does not correlate, the right
response is to weaken the claims the app makes, not to bury the finding.
