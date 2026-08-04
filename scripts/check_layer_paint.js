#!/usr/bin/env node
/* Static check: never set a paint/layout property on a layer type that cannot have it.
 *
 * This exists because of a real outage. `crossings` was converted from a `circle`
 * layer to a `symbol` layer for its icon badges, but applyHunt() kept calling
 * setPaintProperty('crossings','circle-radius',...). MapLibre throws on that. The
 * throw happened inside renderSetup(), which runs on the line immediately before
 * wireTabs() — so every tab button ended up with onclick === null and the entire
 * navigation was dead. Nothing caught it; it was found by a user clicking a tab.
 *
 * The class of bug is "a layer changed type and a caller did not". It is invisible
 * to eslint, invisible at parse time, and only throws on the code path that runs it.
 * So: parse the addLayer() calls to learn each layer's type, then check every
 * setPaintProperty/setLayoutProperty call against what that type actually supports.
 */
const fs = require('fs');
const path = process.argv[2] || 'app/app.js';
const src = fs.readFileSync(path, 'utf8');

// property prefix -> the only layer types that accept it
const PREFIX_TYPES = {
  'circle-': ['circle'],
  'fill-extrusion-': ['fill-extrusion'],
  'raster-': ['raster'],
  'heatmap-': ['heatmap'],
  'hillshade-': ['hillshade'],
  'icon-': ['symbol'],
  'text-': ['symbol'],
};
// these are shared or ambiguous enough not to be worth policing
const SAFE = ['visibility', 'fill-pattern', 'fill-color', 'fill-opacity', 'fill-outline-color',
              'line-color', 'line-width', 'line-opacity', 'line-dasharray', 'line-blur'];

const types = new Map();
for (const m of src.matchAll(/addLayer\(\{\s*id:\s*'([^']+)'\s*,\s*type:\s*'([^']+)'/g)) {
  types.set(m[1], m[2]);
}
// fill-* on a fill layer, line-* on a line layer — derive the rest from the prefix
function allowed(prop, type) {
  if (SAFE.includes(prop)) {
    if (prop.startsWith('fill-')) return type === 'fill';
    if (prop.startsWith('line-')) return type === 'line';
    return true;
  }
  for (const [pre, ok] of Object.entries(PREFIX_TYPES)) {
    if (prop.startsWith(pre)) return ok.includes(type);
  }
  return true;   // unknown property: not our business
}

const problems = [];
const call = /(?:setPaintProperty|setLayoutProperty)\(\s*'([^']+)'\s*,\s*'([^']+)'/g;
for (const m of src.matchAll(call)) {
  const [, layer, prop] = m;
  const type = types.get(layer);
  if (!type) continue;                     // built elsewhere or dynamic — cannot judge
  if (!allowed(prop, type)) {
    const line = src.slice(0, m.index).split('\n').length;
    problems.push(`${path}:${line}  layer '${layer}' is type '${type}' but is set '${prop}'`);
  }
}

if (problems.length) {
  console.error('Layer paint/layout mismatches (these throw at runtime):');
  problems.forEach(p => console.error('  ' + p));
  process.exit(1);
}
console.log(`layer paint check: ${types.size} layers, no type mismatches`);
