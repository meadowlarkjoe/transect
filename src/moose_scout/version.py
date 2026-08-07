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

ENGINE_REVISION = 30

# What changed, newest first — the app shows this so "re-analyse?" is a decision,
# not a leap of faith.
REVISIONS = {
    30: "Focus areas stop growing into ground that is only good by association. The "
        "engine works out where an area reaches using a smoothed version of the map, "
        "which is right for getting a sensible SHAPE and wrong for judging quality — a "
        "blur lifts poor ground over the bar wherever it sits next to good ground, and "
        "on one area two thirds of it was below the average for the whole box. Each "
        "cell now has to be decent on its own account as well. Expect areas to be a "
        "little smaller and tighter around the ground that earned them; the number of "
        "areas is unchanged.",
    29: "Fixed a case where an area could be thrown out — and told you it was cut off "
        "from every road by water — when the truth was that we never managed to fetch "
        "a road network for that box at all. Not knowing how you get somewhere is not "
        "the same as knowing you cannot. On one test area this had excluded all 37 "
        "focus areas and left no routes; it now returns all 37. If access could not be "
        "modelled the brief already says so, and areas are no longer refused on the "
        "strength of a placeholder.",
    28: "You can now tell it what you are carrying, per season. A bow needs the bull "
        "inside about 35 m, so the shooter now sets up 40 m downwind of the caller "
        "instead of 70, the scent wicks come in with him, and glassing knobs — a rifle "
        "tactic, since spotting a bull you cannot reach is not a plan — are weighted "
        "down in favour of the necks and calling setups that bring him close. Rifle "
        "plans are unchanged. Set it beside your dates, and separately for each extra "
        "season you compare.",
    27: "Routes now say what each stretch is travelled BY, and the map draws them "
        "differently: ridden on a quad, on the water, walked along a trail, or "
        "bushwhacking. Before, a route was worked out as a WALK and the ridable parts "
        "were coloured in afterwards — which produced walk-then-ride-then-walk on every "
        "route, i.e. boarding a machine parked in the middle of the bush. The machine "
        "now starts where you do and STAYS where you step off it, so you get one ride "
        "and then you are on foot, and the map marks where you left it. On a real quad "
        "hunt this took the walking from about 5 km down to a few hundred metres. The "
        "bushwhack figure is the one that matters for a pack-out, and it is now "
        "reported on its own.",
    26: "If you gave the analysis more than one set of dates, each one now gets its own "
        "brief. Before, the engine ran every window properly but the brief showed the "
        "FIRST window's answer under all of them — so a bow-season area came with "
        "rifle-season advice, the wrong rut read, the wrong day plan, and nothing "
        "saying which dates it was written for. Pick an area and everything under it is "
        "now written for that area's window, with the dates named at the top of each "
        "section, and the exported PDF lists every window instead of just the first. "
        "The comparison at the top is unchanged. Nothing about the analysis itself "
        "moved — this was only ever the readout.",
    25: "The satellite greenness behind the browse layer is current again, and it is "
        "no longer looking at snow. Two faults in one line: the imagery window was "
        "frozen in 2023-24, so every analysis used the same two-year-old pictures no "
        "matter when you ran it; and because that window crossed a winter and the "
        "engine picked the CLEAREST scenes, it was picking snowfields — a third of the "
        "scenes over one test area were December, at 90% snow. Snow reads as bare "
        "ground, so greenness came back too low over more than a third of some areas. "
        "It now uses only leaf-on summer imagery from the current season where there is "
        "enough of it, falling back a year where there is not, and the brief tells you "
        "the actual dates it used and marks the data down when they are old. Expect "
        "browse to firm up on real regenerating ground.",
    24: "Funnels now say what they JOIN, and are scored on it. A neck is only worth "
        "sitting on if both ends lead somewhere a moose wants to be — the classic is "
        "feeding ground on one side and security cover on the other, which is the "
        "movement a funnel actually funnels. Each funnel now carries that in plain "
        "words: 'feeding ground to security cover', or 'two sides of much the same open "
        "ground' when that is the truth. A neck between two barren patches still counts "
        "as a bottleneck — it just stops being ranked as a place to hunt. Nothing is "
        "removed by this and your focus areas, stands and routes are unchanged; funnels "
        "are reordered.",
    23: "Funnels are now tested for whether they actually connect anything. A funnel is "
        "a place travel is FORCED through — and a peninsula neck, a spit or the closed "
        "end of a bay is narrow but leads nowhere, which is the opposite. Checked "
        "against every saved analysis: on some ground every single 'funnel' the map "
        "showed was a dead end. Expect far fewer funnels, and on open country expect "
        "none — where that happens the layer now tells you why instead of just going "
        "blank. Nothing else about your plan changes: same focus areas, same stands, "
        "same routes.",
    22: "Terrain now uses 1 m LiDAR (NRCan HRDEM) wherever it has been flown — the "
        "brief tells you how much of your box it covered, and falls back to the 30 m "
        "national DEM everywhere else. Glassing knobs are scored from that finer "
        "terrain, so a small rise is no longer flattened away before the model sees it. "
        "And leased shelters on crown land — abris sommaires, chalets de villégiature, "
        "outfitter camps — now count toward hunter pressure and can be shown on the "
        "map. They never restrict where you may hunt; they are evidence somebody else "
        "is already hunting there. Focus areas, stands and routes are unchanged. "
        "(Measuring funnel neck widths on a finer grid is built but not switched on: it "
        "is demonstrably more accurate — the old grid could not express a neck tighter "
        "than about 113 m and reported that same number for every tight funnel — but it "
        "also finds fewer funnels, and that part is not yet validated on ground anyone "
        "has walked.)",
    21: "The browse and feeding layer is rebuilt, and it can now tell you where its "
        "answer came from. It reads five different things — a 10 m satellite "
        "classification, greenness, mapped fire perimeters with a year on them, the "
        "forest-stand map, and logging cuts with their cut date — and it used to simply "
        "take whichever of them scored HIGHEST. That had a consequence worth stating "
        "plainly: the roughest source set a floor no better source could get under. A "
        "block of closed spruce that the forest survey had physically walked and mapped "
        "as having nothing to eat still scored moderate browse, because a satellite "
        "looking down saw green. On one real area that put 42% of the ground above the "
        "halfway mark, which is why the layer came out as a few enormous shapes instead "
        "of the patchwork it should be. Now the most PRECISE source that covers a spot "
        "decides it — a dated cut beats the stand map beats the satellite — and the "
        "others corroborate, so ground where everything agrees is separated from ground "
        "resting on one weak signal. Each input is now computed and stored separately, "
        "which is what will let the map break the layer into its parts — that part is "
        "not built yet, so for now this is still one browse layer, computed better. "
        "Two errors were fixed on the way: partial cuts, which keep their overstory, "
        "were being scored as prime regeneration — the highest browse class in the model "
        "— and the moose biology file that all these numbers were supposed to come from "
        "was being loaded and then ignored, so the values in it had quietly drifted from "
        "the ones actually used. Expect browse to tighten onto real regenerating ground, "
        "conifer to fall away, and feeding sites and focus areas to move with it.",
    20: "Hunts from a camp you placed get their routes back. If you told us where your "
        "camp or cabin is, the plan was drawing your stands and then nothing joining "
        "them — no approach lines from camp, no access leg in. The cause was ours and "
        "it was recent: we had just stopped dropping a 'base camp' pin on a camp you "
        "had told us about yourself, which was right, except that the router was "
        "finding the camp by looking for that pin. Take the pin away and it could no "
        "longer see where you sleep, so it drew nothing at all — silently, with the "
        "layer simply reading no data. Where you sleep and whether we draw a marker "
        "for it are now two separate things. Expect approach lines from camp to every "
        "stand, and the walk-in leg, on camp and cabin hunts.",
    19: "Funnels are real necks now, and every one can tell you how wide it is. Two "
        "things were wrong. A bog was being treated as a barrier, on the assumption that "
        "a moose routes around marsh — it does not; it walks through. Treating bog as a "
        "wall invented a funnel out of every strip of dry ground between two bogs. And "
        "the topographic saddle could create a funnel entirely on its own: on one real "
        "area that produced 59% of all funnel ground, none of it with any measurable "
        "constriction, on terrain too flat for a saddle to mean anything. Funnels are now "
        "built only from genuine water necks, a saddle only strengthens a neck that is "
        "already there, and wet ground weakens one — a crossing a moose CAN make but has "
        "no reason to prefer. Each funnel now reports its neck width, so you can check it "
        "against the map instead of taking our word for it. Expect far fewer funnels, all "
        "of them on ground you can see the reason for.",
    18: "Glassing knobs are actually on high points now. The prominence term saturated "
        "at 12 m above the surrounding country — a low bar in rolling boreal ground, so "
        "a large share of cells tied at maximum and the choice came down entirely to "
        "which had the most feeding habitat nearby. Height had stopped discriminating. "
        "It now scales over ~30 m, AND the spot has to sit near the local summit rather "
        "than merely above average height, which had been putting knobs mid-slope with "
        "a hillside behind them blocking half the view. Expect fewer glassing points, on "
        "better ground. Also: a hunt from a camp you placed yourself no longer draws a "
        "'base camp' pin on top of it — you told us where camp is, and handing that back "
        "as a recommendation was noise.",
    17: "Land cover is now read at its OWN resolution instead of being flattened to the "
        "analysis grid. The satellite product is 10 m and the analysis grid is usually "
        "40 m, so every cell used to be decided by ONE pixel in sixteen — a patch that "
        "is genuinely half regen and half conifer came out as whichever the coin landed "
        "on. The engine now measures what fraction of each cell is tree, shrub, wetland "
        "and so on, and scores the mixture. That matters most for the cover-to-food EDGE, "
        "which is the single strongest term in the model: seams inside a cell were "
        "invisible before and are now the tightest edges on the map. Expect browse and "
        "edge to shift, some focus areas to move onto ground that was previously "
        "averaged away, and stand placement to follow. Processing is tiled, so the finer "
        "measurement does not cost more memory on a big box.",
    16: "Adds SCENT placement to every calling setup. A bull that answers a call swings "
        "downwind to scent-check the cow before he shows himself — the plan now marks "
        "where to hang wicks across that arc (45 m downwind of the call, 25 m either "
        "side, deliberately short of the shooter so he stops in range instead of "
        "walking on into your own scent). The wicks move with the wind as you scrub "
        "days. Refresh cadence comes off the forecast: every 2 h warm or windy, 4 h "
        "cold and calm, and re-applied after rain, which the plan now pulls in. Also "
        "states the Québec legal position — natural cervid urine is prohibited for "
        "hunting with MOOSE the stated exception, so a moose hunter may use moose urine "
        "while deer urine is out entirely — and flags that the exception is under "
        "review for the next moose management plan.",
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
