"""Engine revision — the identity of the ANALYSIS, not the software.

Bump ENGINE_REVISION whenever a change would make the same inputs produce a
materially different plan: model weights, focus-area extraction, routing, access
or reachability rules, site placement, the legal gate. Do NOT bump it for
front-end work, refactors, logging or docs — a hunter does not need to be told to
re-run because a comment changed.

Saved plans record the revision they were computed under. The app compares that to
the live engine and OFFERS a re-run; it never invalidates or rewrites a stored
plan. A plan the model can no longer reproduce is still the plan someone made
notes against, and deleting it because we improved the code would be a worse
failure than showing a slightly stale one.
"""

ENGINE_REVISION = 15

# What changed, newest first — the app shows this so "re-analyse?" is a decision,
# not a leap of faith.
REVISIONS = {
    15: "Reads Québec's OFFICIAL road network (AQréseau+/MRNF) instead of OpenStreetMap "
        "alone. OSM does not map most logging roads out here — a camp sitting on a forest "
        "road was being reported as roadless — and distance-to-road drives reachability, "
        "hunter pressure, pack-out cost and staging, so the whole plan shifts. Forest-road "
        "CLASS is read too (a class-1 haul road is not a class-5 spur). Official BRIDGES "
        "now settle water crossings: an open bridge means you drive over it (which can "
        "bring a focus area back into range), a CLOSED one is flagged before you trust the "
        "route. Quad/snowmobile TRAILS and RAIL grades are read as their own thing — never "
        "drivable, but far faster than bushwhacking on foot and the corridors moose "
        "themselves travel.",
    14: "Focus areas are now gated on YOUR kit. Ground you cannot reach with the "
        "transport you listed — water-locked with no boat, or past the distance you said "
        "you'd cover — is no longer offered as a recommendation. It is still shown, ranked "
        "behind the viable areas and outlined in RED with the reason it is out, so you can "
        "judge whether bringing a canoe or an ATV is worth it. The areas you CAN work are "
        "promoted into its place, and stands/routes are computed only for those. The model "
        "also stopped crediting 'canoe extraction' as a plus to hunters who have no boat.",
    13: "Reads the MRNF GRHQ hydrography. Mapped WETLANDS (marsh/bog/fen) now form the "
        "land-bridge funnels and slow the walk-in, so funnels appear on lake-and-bog ground "
        "the terrain proxy missed. BEAVER PONDS (GRHQ flowages) are scored as a RUT HUB — a "
        "pond beside security cover lifts the calling/ambush value where bulls scent-mark and "
        "cows follow (not fall forage, which is gone by the hunt). Both are new map layers.",
    12: "Water now agrees across the map, the routes and the funnels. The OSM lakes the map "
        "draws are burned into the walking-cost barrier, so a hunt line goes AROUND a lake "
        "instead of drawing a foot crossing straight across open water when the shore route "
        "is just as easy — a crossing is only drawn where going around genuinely isn't an "
        "option. The same lakes feed the funnel detector, so land-bridge funnels now form on "
        "lake-rich ground that previously came back empty ('NO DATA').",
    11: "Focus areas are now admitted by an ABSOLUTE quality bar, not your box's own top "
        "quartile — so a genuinely poor area returns few or zero focus areas and says so, "
        "instead of always dressing up its least-bad ground. Areas are ranked by expected "
        "encounters (size × habitat quality) and capped to a chunk a party can actually work "
        "in a day, rather than one 180 km² blob.",
    10: "Habitat weighting rebalanced to the validated moose HSI (Allen 1987): the food×cover "
        "INTERSPERSION (edge) is now the dominant driver, and the standalone distance-to-water "
        "term is cut way down — it was over-weighting open water as forage, which is a summer "
        "behaviour that's over before the hunt.",
    9: "Huntability is now a true ABSOLUTE score again: the cow/bull and rut-cruise/feed "
       "sub-surfaces were still being percentile-ranked within your box, which quietly "
       "made 'huntability 0.85' mean 'top of whatever you drew'. Now every layer is on a "
       "real 0–1 scale, so scores are comparable between areas. The reachability edge also "
       "fades in smoothly instead of drawing a faint ring at the limit of your walk.",
    8: "Lakes are now foot barriers (no boat), so the model no longer 'walks across' open "
       "water — islands in a lake can't score huntable or win a focus area. Ground you "
       "can't reach at all (across water without a boat, or beyond your stated walk) is "
       "excluded rather than floored.",
    7: "South of ~52°N the model now reads the MRNF écoforestière map: real stand species, "
       "canopy closure and dated logging cuts. Thermal refuge keys on actual conifer + "
       "closure (not 'any tree'), and browse counts cuts by age — the dominant food source "
       "in commercial forest. Large southern boxes take a few minutes longer to fetch it.",
    6: "Fixed a bug that gutted the browse/food layer across any AOI with burns (the "
       "disturbance-age step propagated NaN and zeroed browse on all never-burned ground) "
       "— habitat now reads the whole area, not a sliver. Reachability is now driven by "
       "how far you said you'll walk (access + hunt walk) rather than a fixed decay, and "
       "access DISCOUNTS rather than ERASES habitat, so the map no longer collapses to a "
       "road corridor. Funnels show at a lower bar.",
    5: "Accuracy pass across the map datapoints: funnels now flag genuine necks (≤300 m, "
       "local constriction) instead of km-wide gaps; thermal refuge counts wet/lowland "
       "cover (cedar/spruce swamp), not just cool slopes; calling sites add wallows and a "
       "real cover↔opening seam; glassing keys on prominence over openings and can place "
       "none on flat closed ground; feeding sites are renamed from the misleading "
       "'saline'; rapids are never called fordable; and pack-out cost now accounts for "
       "slope and cover, with camp set back from the haul road.",
    4: "Land cover and NDVI now mosaic every tile/scene covering the box with each read "
       "clamped to its source (fixes horizontal banding that appeared on any AOI larger "
       "than one satellite tile and pulled focus areas onto the artefact); thermal refuge "
       "is now specific densely-forested cool slopes instead of washing over the whole "
       "box.",
    3: "NDVI now mosaics multiple Sentinel-2 scenes and masks nodata (fixes horizontal "
       "coverage-gap banding that suppressed scores); thermal-refuge and calling-site "
       "surfaces soft-combine instead of a brittle product (no more zero sites on "
       "water-sparse ground); funnels detect real water/wetland constrictions, not DEM "
       "noise; and rut PHASE (seeking/peak/post) now drives strategy and the site mix.",
    2: "Per-area staging and camps, hunt lines confined to their own focus area, "
       "roads followed and water treated as impassable, focus areas no longer "
       "capped by a fixed separation, graded water crossings (bridge/ford/boat), "
       "likelihood bands from habitat with access as a separate reachability gate, "
       "and party size shaping area size and setup count.",
    1: "Initial Fire Lake model: rut timing anchored to Oct 2, burn-age browse "
       "layer, absolute huntability scale, thermal refuge and aquatic-feeding decay.",
}


def describe(since):
    """Revision notes newer than `since`, newest first."""
    if since is None:
        return []
    return [REVISIONS[r] for r in sorted(REVISIONS, reverse=True) if r > since]
