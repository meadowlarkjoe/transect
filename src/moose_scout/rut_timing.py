"""Rut-timing prediction for the AOI.

Moose rut is photoperiod-triggered and highly synchronized: across most of the
range, peak breeding falls late September–early October, with gestation ~231 days
placing calving in late May/early June to hit the short northern green-up. Higher
latitudes rut slightly EARLIER and more compressed (calving must align with a
shorter summer), so we nudge the phenology by latitude off a 50°N anchor — a
days-scale shift, honestly small and flagged, not weeks.

Hunting phases (what the hunter actually cares about):
  • pre-rut  — bulls shed velvet, thrash, get vocal; cows not yet receptive.
               Cold-calling starts to pull; bulls increasingly mobile.
  • peak     — bulls actively seek/tend cows; calling most effective; bulls
               travel widely. The window to be in the woods.
  • post-rut — bulls spent and wary; a second estrus in unbred cows can spark a
               brief late flurry; calling less reliable.

Emitted as SCOUT_DATA.RUT and a brief section, and used to key calling guidance.
"""
from __future__ import annotations

from datetime import date, timedelta

# 50°N anchor for the peak-rut CENTRE, then shift by latitude. ~0.7 day earlier
# per degree north of 50°, capped, reflecting photoperiod-driven synchrony.
_ANCHOR_LAT = 50.0
_DAYS_PER_DEG = 0.7
_MAX_SHIFT_DAYS = 6


def _mmdd(year: int, mmdd: str) -> date:
    m, d = mmdd.split("-")
    return date(year, int(m), int(d))


def _lat_shift_days(lat: float) -> int:
    raw = -(lat - _ANCHOR_LAT) * _DAYS_PER_DEG
    return int(round(max(-_MAX_SHIFT_DAYS, min(_MAX_SHIFT_DAYS, raw))))


def phases(ctx) -> dict:
    """Latitude-adjusted rut windows for the AOI's season year, from the species
    config's base phenology. Returns {shift_days, pre, peak, post: [start,end]}."""
    sp = ctx.species
    rut = sp.rut or {}
    year = ctx.aoi.season.year
    shift = _lat_shift_days(ctx.aoi.center.lat)

    def win(key, default):
        a, b = (rut.get(key) or default)
        return [_mmdd(year, a) + timedelta(days=shift), _mmdd(year, b) + timedelta(days=shift)]

    return {
        "shift_days": shift,
        "pre": win("pre_rut", ["09-05", "09-22"]),
        "peak": win("peak_rut", ["09-23", "10-15"]),
        "post": win("post_rut", ["10-16", "10-31"]),
    }


def _peak_center(ph: dict) -> date:
    s, e = ph["peak"]
    return s + timedelta(days=(e - s).days // 2)


def classify(d: date, ph: dict) -> str:
    if ph["pre"][0] <= d <= ph["pre"][1]:
        return "pre-rut"
    if ph["peak"][0] <= d <= ph["peak"][1]:
        return "peak rut"
    if ph["post"][0] <= d <= ph["post"][1]:
        return "post-rut"
    return "outside rut window"


def responsiveness(d: date, ph: dict) -> float:
    """0..1 bull calling-responsiveness / activity, peaking at the rut centre and
    tapering across pre/post. A Gaussian centred on peak with ~11-day sigma so the
    peak window sits high and the shoulders fall off smoothly."""
    import math

    days = (d - _peak_center(ph)).days
    return round(math.exp(-(days * days) / (2 * 11.0 * 11.0)), 3)


GUIDANCE = {
    "pre-rut": "Bulls are getting vocal but cows aren't receptive yet — cold-calling "
               "(cow whines + the odd bull grunt) and raking brush can pull a curious bull; "
               "hunt sign and travel.",
    "peak rut": "Prime. Bulls are cruising for cows and most responsive to calling — "
                "aggressive cow-in-estrus sequences and bull grunts, work the funnels and "
                "wallows, be ready for a bull to come hard.",
    "post-rut": "Bulls are spent and wary — back off aggressive calling, hunt feeding sign "
                "and a possible second-estrus flurry; soft cow calls only.",
    "outside rut window": "Outside the rut — hunt food and travel patterns; calling is far "
                          "less reliable.",
}


def _temp_factor(day):
    """Weather damping on calling response. Rut response is TRIGGER-driven: warm days
    bed moose down and kill the calling response; a hard frost / cold snap fires it up.
    Returns (factor 0..1.0, note)."""
    if not day:
        return 1.0, ""
    hi, lo = day.get("t_max_c"), day.get("t_min_c")
    f, note = 1.0, ""
    if hi is not None:
        if hi >= 20:
            f, note = 0.4, "warm (>20 °C) — poor calling response; hunt shade/water, first & last light only"
        elif hi >= 17:
            f, note = 0.6, "mild (>17 °C) — response damped through midday"
        elif hi >= 14:
            f, note = 0.8, "moderate — good early/late, quiet midday"
        else:
            note = "cool — favourable for calling"
    if lo is not None and lo <= 0:
        f = min(1.0, f * 1.2)
        note = (note + " · " if note else "") + "hard frost overnight — trigger favourable"
    return round(f, 2), note


def summary(ctx, weather_days=None) -> dict:
    """Full rut payload for the app + brief: latitude-adjusted windows, per-target-date
    phase + responsiveness (damped by the forecast weather trigger), a Sept–Oct weekly
    calendar, and the peak date."""
    ph = phases(ctx)
    peak_c = _peak_center(ph)
    wd = {w.get("date"): w for w in (weather_days or []) if w.get("date")}

    def fmt(win):
        return [win[0].isoformat(), win[1].isoformat()]

    targets = []
    for ds in ctx.aoi.season.target_dates:
        try:
            d = date.fromisoformat(ds)
        except Exception:
            continue
        cls = classify(d, ph)
        base = responsiveness(d, ph)
        fac, wnote = _temp_factor(wd.get(ds))
        targets.append({"date": ds, "phase": cls,
                        "responsiveness": round(base * fac, 3),
                        "responsiveness_date": base, "weather_factor": fac,
                        "weather_note": wnote, "guidance": GUIDANCE.get(cls, "")})

    # Weekly calendar across the rut span (pre start .. post end), Mondays.
    cal = []
    d = ph["pre"][0]
    end = ph["post"][1]
    d = d - timedelta(days=d.weekday())  # back up to Monday
    while d <= end:
        cls = classify(d + timedelta(days=3), ph)  # mid-week representative
        cal.append({"week_of": d.isoformat(), "phase": cls,
                    "responsiveness": responsiveness(d + timedelta(days=3), ph)})
        d += timedelta(days=7)

    best = None
    if targets:
        best = max(targets, key=lambda t: t["responsiveness"])

    return {
        "peak_date": peak_c.isoformat(),
        "shift_days": ph["shift_days"],
        "windows": {"pre_rut": fmt(ph["pre"]), "peak_rut": fmt(ph["peak"]),
                    "post_rut": fmt(ph["post"])},
        "targets": targets,
        "best_target": best,
        "calendar": cal,
        "lat_note": (f"Phenology shifted {ph['shift_days']:+d} day(s) for {ctx.aoi.center.lat:.1f}°N "
                     "vs a 50°N anchor (northern moose rut slightly earlier). Approximate — rut "
                     "timing varies year to year; verify against local reports."),
        "trigger_note": ("Rut response is TRIGGER-driven, not a calendar certainty: a hard frost / "
                         "cold snap switches bulls on, a warm front shuts them off. The % is the "
                         "date-based expectation damped for the forecast high — treat it as a guide, "
                         "not a guarantee, and read the actual weather."),
    }
