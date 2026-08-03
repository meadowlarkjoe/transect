# Transect (app)

Self-contained scouting app that renders a Transect analysis (`transect.json`).
No Mapbox token, no server: **double-click `index.html`** (needs internet for
basemap tiles). Built on MapLibre GL (vendored).

## Use
- Left panel: legal/access gate, "what I'm looking for," Proposed Camps A/B/C,
  and ranked focus areas with pros/cons. Click an area → Phase-2 detail (its
  sites + optimal wind).
- Tools (right): Satellite / Topo / Hybrid basemaps, **3D terrain**, **Measure**,
  layer toggles.
- Weather bar (bottom): pick a day → sites turn **green** when that day's forecast
  wind fits their optimal approach ("wind-right").

## Load a different scout
Replace `data/transect.json` (and regenerate `data.js` = `window.TRANSECT_DATA=` +
that JSON + `;`) from the engine: `moose-scout transect --aoi <name>`.
