"""Density-driven hunt strategy.

The single biggest strategic fork in moose hunting: is this LOW-density country
(few animals over big ground — you must *call to pull one in*, cover ground, use
scent to draw), or HIGH-density (enough animals that *sitting tight over sign,
food and scent* and staying quiet beats covering ground)? Everything downstream —
calling intensity, how much you move, stand length, attractant emphasis — keys
off this. The density signal comes from the MFFP aerial inventory where it exists,
else a bioclimatic prior (flagged as an estimate).
"""
from __future__ import annotations

from .config import Context


def density_estimate(ctx: Context) -> dict:
    """(moose/10 km², source, is_estimate). Aerial inventory if published for the
    zone, else a bioclimatic prior by latitude/biome."""
    per10 = None
    source = None
    if ctx.aoi.species == "moose" and ctx.aoi.zone_hint:
        try:
            from .acquire import zones as z

            eff = z.effort_context(ctx.aoi.zone_hint)
            if eff and eff.get("density_per_10km2"):
                per10 = float(eff["density_per_10km2"])
                source = eff.get("source", "MFFP aerial inventory")
        except Exception:
            pass
    if per10 is not None:
        return {"per_10km2": per10, "source": source, "is_estimate": False}

    # Bioclimatic prior — northern pessière (spruce-moss) is poor moose habitat and
    # runs low; southern mixedwood carries more. Honest fallback, flagged.
    lat = ctx.aoi.center.lat
    prior = 0.6 if lat >= 52 else (1.8 if lat >= 49 else 3.2)
    return {"per_10km2": prior, "source": "bioclimatic prior (no aerial survey for this zone)",
            "is_estimate": True}


PROFILES = {
    "low": {
        "density_class": "low",
        "headline": "Low density — call to pull them in.",
        "approach": "Reach out and bring a bull to you; cover ground to find fresh sign.",
        "calling": "Aggressive: long cold-calling sets — cow-in-estrus whines, bull grunts, "
                   "brush-raking. Relocate between stations to search big country.",
        "stand_minutes": 45,
        "movement": "Mobile — hit several calling stations dawn and dusk; follow fresh sign.",
        "attractants": "High value — a wallow you FIND on the ground is the best stand site in the "
                       "country (note: the map cannot predict wallow locations; no published method "
                       "exists, so this is a find-it-on-foot job). A mock wallow / cow-in-estrus scent "
                       "can tip a lonely bull (check Quebec baiting rules).",
        "calling_weight": 1.0, "ambush_weight": 0.3,
        "why": "Few animals over a lot of ground: if you sit and wait, nothing walks by. "
               "You have to advertise and make one come find you.",
    },
    "moderate": {
        "density_class": "moderate",
        "headline": "Moderate density — call, but hunt the sign.",
        "approach": "Balance calling with ambushing the best fresh sign.",
        "calling": "Measured: call the funnels and edges, but don't over-call; back off if a "
                   "bull hangs up. Let terrain do some of the work.",
        "stand_minutes": 30,
        "movement": "Semi-mobile — 2–3 quality setups per day tied to sign and wind.",
        "attractants": "Wallows and saline at pinch points help; keep calling pressure light.",
        "calling_weight": 0.6, "ambush_weight": 0.6,
        "why": "Enough animals that good sign is worth sitting, but still thin enough that "
               "calling pulls the odd traveller in.",
    },
    "high": {
        "density_class": "high",
        "headline": "High density — sit tight over sign and scent.",
        "approach": "Patience over prime sign and food beats covering ground.",
        "calling": "Minimal — soft cow calls only; heavy calling just educates bulls. Let them "
                   "come to food, water and scent on their own schedule.",
        "stand_minutes": 60,
        "movement": "Low — pick the best wallow / feeding edge / saline and stay put; all-day "
                    "sits are viable in the rut.",
        "attractants": "Saline and scent at wallows and feeding pinch points; low calling pressure.",
        "calling_weight": 0.3, "ambush_weight": 1.0,
        "why": "With animals around, the bull that busts you calling is one you'll never see; "
               "quiet ambush over the right sign wins.",
    },
}


def classify(per10: float) -> str:
    if per10 < 1.2:
        return "low"
    if per10 < 3.0:
        return "moderate"
    return "high"


def strategy(ctx: Context) -> dict:
    from . import rut_timing
    d = density_estimate(ctx)
    cls = classify(d["per_10km2"])
    prof = dict(PROFILES[cls])
    prof.update(density_per_10km2=round(d["per_10km2"], 2),
                density_source=d["source"], density_is_estimate=d["is_estimate"])

    # PHASE SETS THE TACTIC; DENSITY MODULATES IT. The density profile alone told a
    # seeking-phase hunt and a peak-phase hunt the same thing — but those are opposite
    # games (advertise-and-call vs sit-on-the-cows-and-shut-up). So overlay the phase:
    # the phase decides calling philosophy and what to hunt, density decides how hard
    # you have to work to make contact.
    phase = rut_timing.dominant_phase(ctx)
    tw = rut_timing.PHASE_TACTIC[phase]
    prof["rut_phase"] = phase
    prof["phase_guidance"] = rut_timing.GUIDANCE.get(
        {"seeking": "seeking (pre-rut)", "peak": "peak rut",
         "post": "post-rut", "outside": "outside rut window"}[phase], "")
    prof["calling_weight"] = round(min(1.0, prof["calling_weight"] * tw["calling"]), 2)
    prof["ambush_weight"] = round(min(1.0, prof["ambush_weight"] * tw["ambush"]), 2)
    prof["stand_minutes"] = int(round(prof["stand_minutes"] * tw["stand_scale"]))
    # Headline leads with the phase, since that's the bigger lever this week.
    _PH = {"seeking": "Seeking (pre-rut) — call aggressively and cover ground.",
           "peak": "Peak rut — hunt the cows; call less, sit longer.",
           "post": "Post-rut — hunt food; soft cow calls, watch for a late flurry.",
           "outside": "Outside the rut — hunt food and travel; calling is unreliable."}
    prof["phase_headline"] = _PH[phase]
    # Attractants are baiting-adjacent and REGULATED — never recommend them blind.
    prof["scent_warning"] = (
        "⚠ Scents, lures, mineral/saline sites and bait are regulated and vary by zone — "
        f"some are prohibited. Verify the current Zone {ctx.aoi.zone_hint or '?'} rules on "
        "quebec.ca before using ANY attractant. When in doubt, don't — calling and hunting "
        "sign are always legal; a citation ends the hunt.")
    return prof
