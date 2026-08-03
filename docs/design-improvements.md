# Improving on the manual expert map

We adopt the **output symbology** of La Chasse avec Charles Dorris / Les Cartes
Xperts (see `config/output_legend.yaml`) because experienced Quebec moose hunters
already read it fluently. But the analysis *behind* the symbols is upgraded from
a hand-drawn, static, one-shot sheet to something quantitative, dynamic, and
condition-aware.

| Dimension | Manual expert sheet | Moose Scout |
|---|---|---|
| Focus areas | Eyeballed dashed loops | Ranked from HSM × extraction rasters, with a confidence score and the layers that drove each pick |
| Routes | Fixed diel/temp classes | Same classes, but **wind- and thermal-conditioned** and regenerated per forecast so you enter downwind |
| Weather | Implicit ("s'il fait chaud") | Pulls the **forecast for your actual hunt dates**; auto-selects route class + thermal refuges from predicted temps |
| Extraction | Not shown | Every rut/kill candidate carries a **multi-modal pack-out plan** (mode, route, effort/time) |
| Glassing / calling sites | Eyeballed | **Computed viewshed** knobs; calling stations sited by funnel × rut features × wind × acoustics |
| Roads | Footnoted "accessibility not verified" | **Cross-checked vs. current Sentinel-2**, per-segment confidence; unmapped spurs surfaced |
| Stand age | Legend buckets (10–30 yr, >30 yr) | **Exact age from dated *perturbations***; can project when a cut peaks as browse |
| Hunter pressure | Not modeled | **Pressure surface** (distance from roads/towns/parking) → unpressured-but-extractable sweet spot |
| Lifecycle | One-shot | **Feedback loop**: log sign / trail-cam / past kills → re-rank |
| Scale | One sector by hand | Whole zone ranked → drill into best sectors |

Non-negotiables carried from the manual approach:
- Every generated site is still tagged **"à valider sur le terrain"** — the model
  produces a prioritized hypothesis, not a guarantee.
- Symbol semantics (colors/geometry) stay 1:1 with the legend so briefs remain
  readable and OnX-importable.
