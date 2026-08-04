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

ENGINE_REVISION = 7

# What changed, newest first — the app shows this so "re-analyse?" is a decision,
# not a leap of faith.
REVISIONS = {
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
