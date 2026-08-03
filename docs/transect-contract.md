# Transect data contract (`transect.json`, schema `transect/1`)

The stable JSON the Transect app binds to. One file per AOI:
`outputs/<aoi>/transect.json`. Produced by `moose-scout transect --aoi <name>`
(also runs at the end of `run`). All coordinates are **WGS84 lat/lon**.

## Top level

| key | type | notes |
|---|---|---|
| `schema` | string | `"transect/1"` |
| `meta` | object | aoi, title, species, center{lat,lon}, radius_km, target_dates[], residency, extraction_modes[] |
| `legal` | object | zone, north_of_52, diy_possible, huntable_tenures[], flags[], verify[], season_summary |
| `methodology` | object | summary, factors_weighted[], then, caveats[] — the "what I'm looking for" copy |
| `camps` | array | proposed camps (grouped areas), see below |
| `areas` | array | ranked focus areas, see below |
| `waypoints` | array | typed sites, each with optimal_wind, see below |
| `routes` | array | {type, coords:[[lon,lat],…]} |
| `weather` | object | {source, days:[…]}, see below |
| `layers` | object | references to the huntability raster + roads |
| `disclaimer` | string | ground-truth caveat |

## `camps[]`  (Proposed Camp A/B/C)

```json
{ "id": "A", "member_areas": [1,2], "site": {"lat":52.57988,"lon":-67.43481},
  "access_type": "road", "packin_km_by_area": {"1":21.6,"2":10.7}, "max_packin_km": 21.6 }
```
Focus areas within ~15 km cluster into one camp; the camp is sited at the nearest
road access to the cluster; `packin_km_by_area` is the straight-line pack-in to
each member area (the real access/extraction cost).

## `areas[]`

```json
{ "rank":1, "camp":"A", "area_km2":17.7, "huntability":0.933,
  "centroid":[lon,lat], "why":"…", "pros":["…"], "cons":["…"],
  "stats":{"dist_water_m":98,"dist_road_m":21000,"mean_slope_deg":1.0},
  "geometry": { "type":"Polygon", "coordinates":[…] } }
```

## `waypoints[]`

```json
{ "type":"rut_calling", "lat":52.62, "lon":-67.76,
  "properties": { "legend":"rut_calling", "focus_area":1, "camp":"A",
    "score":0.9, "elev_m":650, "min_stand_minutes":30,
    "optimal_wind": { "from_deg":101.5, "from_compass":"ESE",
      "approach_deg":281.5, "approach_compass":"WNW",
      "note":"Approach from the E (camp side); hunt it on a wind out of the ESE." } } }
```
`type` ∈ rut_calling · thermal_refuge · saline_blind · funnel · glassing ·
validate_ground · base_camp · parking. **optimal_wind** is the wind the site
should be hunted on (approach from the camp with wind in your face).

## `weather`

```json
{ "source":"Open-Meteo archive (prior-year proxy 2025-09-25..2025-10-05)",
  "days":[ { "date":"2025-09-25","is_proxy":true,"t_min_c":5.3,"t_max_c":16.1,
    "wind_from_deg":225,"wind_from_compass":"SW","wind_kmh":16.9,
    "sunrise":"…T06:21","sunset":"…T18:20" } ] }
```
Hunt dates are usually >16 days out → prior-year archive as a climatology proxy
(`is_proxy:true`); within ~16 days it switches to live forecast. Compare each
day's `wind_from_deg` to a waypoint's `optimal_wind.from_deg` (±45°) to tell the
user which sites are "wind-right" that morning — this drives the wind calendar.
