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

ENGINE_REVISION = 2

# What changed, newest first — the app shows this so "re-analyse?" is a decision,
# not a leap of faith.
REVISIONS = {
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
