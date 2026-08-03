"""Rut-timing prediction for the AOI.

Moose rut is photoperiod-triggered and remarkably synchronized. The key finding —
and it contradicts common hunting lore — is that **latitude does NOT meaningfully
shift the rut date in North America**: median conception is 2 Oct at 47.5°N (North
Dakota, fetal back-dating, n=45, SD 8.0 d) and 2 Oct at 63.5°N (Denali, 191 directly
observed mountings, all copulations 24 Sep – 8 Oct). Sixteen degrees of latitude,
zero shift. A multi-region review puts most mating everywhere in 23 Sep – 8 Oct.
So we anchor on **2 October** and do not shift by latitude. What varies with
latitude is parturition timing relative to green-up, not conception date.

The second key distinction: **peak BREEDING is not peak bull VULNERABILITY.**
  • seeking (pre-rut) — bulls maximally mobile and maximally callable; cows not
        yet receptive so a bull is actively searching. This is the best CALLING
        window of the year, and it precedes peak breeding.
  • peak breeding     — bulls are tending individual cows for days at a time, so
        they're locally sedentary and *less* responsive to calling. Mature bulls
        have also stopped feeding (~18–20 Sep onward), so they are no longer in
        feeding habitat: they're where the COWS are.
  • post-rut          — bulls spent and wary; unbred cows re-cycle (~24 d) and
        satellite bulls re-mobilize, so response partially recovers.

Gestation ~231 d (mean; 87% of observations 225–236 d) places calving late May.
The second estrus lands ~27 Oct — after most Québec seasons close — so we do NOT
model a huntable second-rut bump.

Emitted as doc["rut"] and drives calling guidance + the habitat phase blend.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

# Peak CONCEPTION anchor — latitude-invariant (see module docstring).
_PEAK_MONTH, _PEAK_DAY = 10, 2
# Breeding-intensity spread. Field SDs run 4.5 d (captive, observed) to 8.0 d
# (wild, fetal back-dated); 6.5 splits them.
_BREED_SIGMA = 6.5
# Calling response peaks in the SEEKING phase, ~6 d before the breeding peak,
# then partially recovers post-peak as unbred cows re-cycle.
_CALL_OFFSET_DAYS = -6.0
_CALL_SIGMA = 8.0
_POST_BUMP_OFFSET = 12.0
_POST_BUMP_SIGMA = 6.0
_POST_BUMP_WEIGHT = 0.30


def _mmdd(year: int, mmdd: str) -> date:
    m, d = mmdd.split("-")
    return date(year, int(m), int(d))


def peak_date(ctx) -> date:
    """The peak-breeding anchor: 2 October, every latitude."""
    return date(ctx.aoi.season.year, _PEAK_MONTH, _PEAK_DAY)


def phases(ctx) -> dict:
    """Behavioural rut windows around the 2 Oct breeding peak. These are hunting
    phases, not just calendar thirds — see the module docstring."""
    pk = peak_date(ctx)
    return {
        "shift_days": 0,                                   # kept for contract compatibility
        "peak_date": pk,
        # seeking: bulls searching + most callable
        "pre": [pk - timedelta(days=20), pk - timedelta(days=4)],
        # peak breeding: tending, locally sedentary, with the cows
        "peak": [pk - timedelta(days=3), pk + timedelta(days=6)],
        # post: spent bulls, re-cycling cows
        "post": [pk + timedelta(days=7), pk + timedelta(days=29)],
    }


def _peak_center(ph: dict) -> date:
    return ph["peak_date"]


def classify(d: date, ph: dict) -> str:
    if ph["pre"][0] <= d <= ph["pre"][1]:
        return "seeking (pre-rut)"
    if ph["peak"][0] <= d <= ph["peak"][1]:
        return "peak rut"
    if ph["post"][0] <= d <= ph["post"][1]:
        return "post-rut"
    return "outside rut window"


def breeding_intensity(d: date, ph: dict) -> float:
    """0..1 share of breeding activity on this date — a Gaussian on the 2 Oct peak.
    This drives the HABITAT blend (at peak, hunt where the cows are), NOT calling."""
    days = (d - _peak_center(ph)).days
    return round(math.exp(-(days * days) / (2 * _BREED_SIGMA ** 2)), 3)


def responsiveness(d: date, ph: dict) -> float:
    """0..1 bull CALLING responsiveness. Deliberately NOT centred on peak breeding:
    bulls are most callable while still searching for a first cow (seeking phase),
    drop off while tending one, then partially recover as unbred cows re-cycle."""
    pk = _peak_center(ph)
    x = (d - pk).days
    main = math.exp(-((x - _CALL_OFFSET_DAYS) ** 2) / (2 * _CALL_SIGMA ** 2))
    post = math.exp(-((x - _POST_BUMP_OFFSET) ** 2) / (2 * _POST_BUMP_SIGMA ** 2))
    return round(min(1.0, main + _POST_BUMP_WEIGHT * post), 3)


GUIDANCE = {
    "seeking (pre-rut)":
        "The best calling window of the year. Bulls are on their feet searching and cows "
        "aren't receptive yet, so a lone bull will come a long way to a cow call. Cold-call "
        "aggressively from funnels and edges, rake brush, and keep moving between setups.",
    "peak rut":
        "Bulls are tending individual cows for days at a time — locally sedentary and LESS "
        "responsive to calling than a week earlier. Hunt where the COWS are (feeding edges, "
        "security cover), not where a lone bull would travel. A bull without a cow will still "
        "come hard, so keep calling — just expect silence from the tied-up ones.",
    "post-rut":
        "Bulls are spent and wary. Back off aggressive calling to soft cow calls, hunt feeding "
        "sign as they try to recover weight, and watch for a late flurry as unbred cows re-cycle "
        "(~24 days after the peak) and satellite bulls re-mobilize.",
    "outside rut window":
        "Outside the rut — hunt food and travel patterns; calling is far less reliable.",
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


def _fmt(d: date) -> str:
    return f"{d.strftime('%b')} {d.day}"


def _hunt_read(ph: dict, targets: list, peak_c: date) -> str:
    """A personalized paragraph: where THIS hunt lands relative to the rut, and how
    hunting these specific dates changes the way the area gets hunted (and what the
    huntability map is leaning on). Not generic phase boilerplate."""
    if not targets:
        return ""
    ds = sorted(t["date"] for t in targets)
    d0, d1 = date.fromisoformat(ds[0]), date.fromisoformat(ds[-1])
    mid = d0 + timedelta(days=(d1 - d0).days // 2)
    cls = classify(mid, ph)
    to_peak = (peak_c - mid).days                      # +ve = before peak, -ve = after
    best = max(targets, key=lambda t: t.get("responsiveness", 0))
    resp = int(round(best.get("responsiveness", 0) * 100))
    span = _fmt(d0) if d0 == d1 else f"{_fmt(d0)}–{_fmt(d1)}"

    # where it lands
    if cls == "peak rut":
        where = (f"Your hunt (<b>{span}</b>) lands {'squarely on' if abs(to_peak) <= 3 else 'inside'} the "
                 f"breeding peak (~{_fmt(peak_c)})" + ("" if abs(to_peak) <= 3
                 else f", {abs(to_peak)} day(s) {'before' if to_peak > 0 else 'past'} the centre")
                 + ".")
        how = ("Worth knowing: peak <i>breeding</i> is not peak <i>callability</i>. Mature bulls are tending "
               "individual cows for days at a time — locally sedentary and quieter to the call than they were "
               "a week earlier — and they stopped feeding around 18–20 Sep, so they're no longer in the "
               "feeding habitat. <b>Hunt where the cows are:</b> security cover beside good feed, not lone-bull "
               "travel terrain. A bull that hasn't found a cow will still come hard, so keep calling — just "
               "expect silence from the tied-up ones. The map is weighted toward <b>cow habitat</b> for these dates.")
    elif cls.startswith("seeking"):
        where = (f"Your hunt (<b>{span}</b>) is in the <b>seeking phase</b>, ~{max(to_peak,0)} day(s) before the "
                 f"~{_fmt(peak_c)} breeding peak.")
        how = ("This is arguably the <b>best calling window of the year</b> — better than the peak itself. Bulls "
               "are on their feet searching and no cow is receptive yet, so a lone bull will travel a long way "
               "to a cow call. Cold-call aggressively from funnels and edges, rake brush, and keep moving "
               "between setups rather than sitting. The map leans on <b>bull search corridors and feeding "
               "edges</b> for these dates.")
    elif cls == "post-rut":
        where = (f"Your hunt (<b>{span}</b>) is post-rut, ~{abs(to_peak)} day(s) after the ~{_fmt(peak_c)} "
                 "peak — bulls are spent and wary.")
        how = ("<b>Back off aggressive calling</b> (soft cow calls only) and hunt <b>feeding sign</b> hard as "
               "bulls try to recover weight before winter. Unbred cows re-cycle about 24 days after the peak, "
               "which can spark a brief late flurry. The map leans toward <b>feeding and thermal cover</b>.")
    else:
        where = (f"Your hunt (<b>{span}</b>) falls outside the core rut window (peak ~{_fmt(peak_c)}).")
        how = ("Calling is far less reliable now — hunt <b>food and travel patterns</b>: feeding edges, "
               "water, and the trails between bedding and forage. The map is weighted to feeding ground "
               "rather than rut terrain.")

    read = f"{where} {how}"
    # weather trigger, if the forecast/proxy says anything notable across the window
    wnotes = [t.get("weather_note") for t in targets if t.get("weather_note")]
    if wnotes:
        read += (f" <b>Weather for your dates:</b> {wnotes[0]}" +
                 (" — and a warm spell will knock the calling response down further, so lean on the "
                  "first/last-light feeding sits" if resp < 55 else "."))
    read += f" (Best of your dates ≈ {resp}% calling responsiveness.)"
    return read


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
                        "breeding_intensity": breeding_intensity(d, ph),
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
        "hunt_read": _hunt_read(ph, targets, peak_c),
        "shift_days": ph["shift_days"],
        "windows": {"pre_rut": fmt(ph["pre"]), "peak_rut": fmt(ph["peak"]),
                    "post_rut": fmt(ph["post"])},
        "targets": targets,
        "best_target": best,
        "calendar": cal,
        "lat_note": ("Peak breeding is anchored at ~2 October and is NOT shifted for latitude: "
                     "median conception is 2 Oct at 47.5°N and 2 Oct at 63.5°N (16° of latitude, no "
                     "shift), and most mating range-wide falls in 23 Sep – 8 Oct. Year-to-year and "
                     "cow-condition variation (SD ≈ 5–8 days) exceeds any latitude effect — verify "
                     "against local reports."),
        "phase_note": ("Peak BREEDING is not peak CALLABILITY. Bulls are most responsive to calling "
                       "while still searching (the seeking phase, roughly the two weeks before the "
                       "peak); during peak breeding they're tending cows and go quiet, then partially "
                       "re-engage as unbred cows re-cycle. The % below is calling responsiveness, "
                       "not breeding activity."),
        "trigger_note": ("Rut response is TRIGGER-driven, not a calendar certainty: a hard frost / "
                         "cold snap switches bulls on, a warm front shuts them off. The % is the "
                         "date-based expectation damped for the forecast high — treat it as a guide, "
                         "not a guarantee, and read the actual weather."),
    }
