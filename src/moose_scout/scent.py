"""Scent / urine lure placement (#73).

Calling puts a cow in a bull's ears. Scent is what he checks before he believes it.

A rutting bull that answers a call almost never walks straight in — he swings
**downwind of the calling position** and scent-checks the air for the cow he just
heard. That circle is the single most predictable thing he does, and it is where
most hunts are lost: he finds human scent instead of cow scent, and leaves without
ever being seen.

So the geometry is not "hang a wick near your stand". It is:

    upwind ─────────────────────────────────────────────► downwind
      CALLER ●·······················○ wicks ·········● SHOOTER
        0 m                          45 m               70 m
                                  (± 25 m crosswind)

  * the **caller** stays upwind and keeps calling,
  * the **shooter** sits ~70 m downwind, on the arc the bull will swing through,
  * the **wicks** go across that arc at ~45 m — 25 m short of the shooter — so the
    bull cuts cow scent BEFORE he reaches the shooter's own scent cone, stops to
    work it out, and does that inside a range the shooter can use.

Two flankers either side of the centre wick widen the scent line, because the bull
picks his own arc and a single wick is a thread he can walk past.

None of this is a raster product: it depends entirely on the wind on the day, so the
engine ships the DOCTRINE (distances, cadence, legality) and the client places the
points live from the wind scrubber, exactly as it does for shooter positions.

LEGALITY IS NOT A DETAIL. Québec bans natural cervid urine and byproducts for
hunting — with moose explicitly excepted (use since spring 2020, sale/purchase since
19 September 2024). So a moose hunter may use moose urine where a deer hunter may
not touch deer urine, and the exception is under review for the next moose management
plan. That is exactly the kind of rule that changes between seasons, so it ships as a
`verify` flag, never as a settled fact.
"""
from __future__ import annotations

# Placement geometry, in metres from the calling position along the DOWNWIND bearing.
# Kept here (not in the client) so the brief, the map and the tests all quote one
# source; the client only supplies the wind.
GEOMETRY = {
    "shooter_m": 70,        # existing caller/shooter split — the arc the bull swings
    "wick_m": 45,           # 25 m short of the shooter: he stops in range, not past it
    "flank_m": 25,          # crosswind offset of the two flanking wicks
    "height_m": [1.0, 1.5], # off the ground: it disperses, and it stays out of the mud
    "count": 3,
}


def _cadence(day):
    """How often the wicks need refreshing on a given forecast day.

    Volatile scent leaves faster when it is warm and when wind strips it; rain
    removes it outright. Thresholds are deliberately coarse — this is a reminder to
    the hunter, not a claim to model evaporation.
    """
    t = day.get("t_max_c")
    w = day.get("wind_kmh")
    p = day.get("precip_mm")
    t = 10.0 if t is None else float(t)
    w = 10.0 if w is None else float(w)
    p = 0.0 if p is None else float(p)

    if t > 15 or w > 20:
        hours, why = 2, "warm and/or windy — scent strips off the wick fast"
    elif t > 8 or w > 12:
        hours, why = 3, "mild — normal refresh"
    else:
        hours, why = 4, "cold and calm — scent holds; one top-up per sit is enough"

    washed = p >= 1.0
    if washed:
        why += "; rain forecast — a wet wick is a dead wick, re-apply after it passes"
    return {"date": day.get("date"), "refresh_hours": hours, "why": why,
            "rain_reset": washed, "precip_mm": round(p, 1)}


def legality(species: str, region_code: str | None):
    """What the hunter must confirm before packing a bottle. Returns None where we
    have nothing specific to say, rather than inventing reassurance."""
    if (region_code or "").lower().startswith("qc") or region_code is None:
        if (species or "").lower() == "moose":
            return {
                "status": "allowed_with_exception",
                "text": ("Québec bans urine and other natural byproducts from cervids for "
                         "hunting — **moose is the stated exception**, for use (since spring 2020) "
                         "and for sale/purchase (since 19 September 2024). Deer urine is out "
                         "entirely, including as an ingredient."),
                "verify": ("The moose exception is under review for the next moose management "
                           "plan. Confirm it still stands for your season before you buy or "
                           "carry it, and keep the label — the exception is species-specific and "
                           "the onus is on you to show what is in the bottle."),
                "why": "Chronic wasting disease: prions persist in urine, saliva and soil.",
                "source": "MELCCFP — CWD control measures",
            }
        return {
            "status": "prohibited",
            "text": ("Québec prohibits urine and other natural byproducts from cervids for "
                     "hunting, with moose the only exception. That covers deer urine, tarsal "
                     "gland and any lure containing them."),
            "verify": "Confirm the current rule for your species and season before you travel.",
            "why": "Chronic wasting disease: prions persist in urine, saliva and soil.",
            "source": "MELCCFP — CWD control measures",
        }
    return None


def plan(ctx, weather: dict | None):
    """The scent block for the contract: geometry, per-day cadence, legality, and the
    handling rules that decide whether any of it works."""
    species = getattr(ctx.aoi, "species", "moose")
    region = getattr(getattr(ctx, "region", None), "code", None)
    days = ((weather or {}).get("days") or [])
    return {
        "geometry": GEOMETRY,
        "placement": (
            "Wicks go **across the downwind arc**, {wick} m downwind of the calling position "
            "and {flank} m either side of the caller→shooter line — {gap} m short of the shooter. "
            "A bull swings downwind to scent-check the cow he heard before he shows himself; "
            "this puts cow scent on that arc so he stops and works it out in range, instead of "
            "carrying on until he finds you."
        ).format(wick=GEOMETRY["wick_m"], flank=GEOMETRY["flank_m"],
                 gap=GEOMETRY["shooter_m"] - GEOMETRY["wick_m"]),
        "cadence": [_cadence(d) for d in days],
        "handling": [
            "Hang wicks at {a:.1f}–{b:.1f} m — off the ground it disperses, and it stays "
            "out of the mud.".format(a=GEOMETRY["height_m"][0], b=GEOMETRY["height_m"][1]),
            "Bottle and wicks go in a sealed bag until you are at the stand. Scent on your "
            "gloves, boots or pack turns your whole walk-in into a scent trail that leads "
            "a bull to the wrong place.",
            "Walk in on a line that does NOT cross where the wicks will hang — hang them "
            "last, on your way to the shooting position.",
            "Collect the wicks when you leave. Left hanging, they keep working the arc on "
            "days you are not there and teach a bull the spot means nothing.",
            "A fresh wallow beats any bottle. If you find one, set up on it and use scent "
            "only to hold him a few seconds longer.",
        ],
        "legality": legality(species, region),
    }
