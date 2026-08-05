"""Weather-by-date for the hunt window (Open-Meteo, free, no key).

For dates within ~16 days we could use the forecast; hunt dates are usually
months out, so we pull the **prior-year same-dates** from the archive as a
climatological proxy (labelled as such). Returns daily temp, dominant wind, and
sunrise/sunset — enough to drive the app's wind/weather calendar and to flag
which sites are wind-right on which days.
"""
from __future__ import annotations

import json
import ssl
import urllib.request
from datetime import date

ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
FORECAST = "https://api.open-meteo.com/v1/forecast"
_SSL = ssl.create_default_context()
_DAILY = ("temperature_2m_max,temperature_2m_min,"
          "wind_speed_10m_max,wind_direction_10m_dominant,sunrise,sunset,"
          # rain washes a scent wick out entirely, so the lure refresh cadence (#73)
          # needs precipitation, not just temperature and wind.
          "precipitation_sum")


def _get(url: str, params: dict) -> dict:
    from urllib.parse import urlencode

    req = urllib.request.Request(url + "?" + urlencode(params),
                                 headers={"User-Agent": "moose-scout/0.1"})
    with urllib.request.urlopen(req, context=_SSL, timeout=30) as r:
        return json.load(r)


def for_dates(lat: float, lon: float, dates: list[str], today: str | None = None) -> dict:
    """Daily weather for the target dates. Uses forecast when the date is within
    ~16 days of `today` (YYYY-MM-DD), else prior-year archive as a proxy.
    Returns {source, days: [{date, is_proxy, t_min, t_max, wind_from_deg,
    wind_from_compass, wind_kmh, sunrise, sunset}]}."""
    from .wind import compass

    if not dates:
        return {"source": "none", "days": []}
    start, end = min(dates), max(dates)

    proxy = True
    try:
        if today:
            days_out = (date.fromisoformat(start) - date.fromisoformat(today)).days
            proxy = days_out > 15 or days_out < 0
    except Exception:
        proxy = True

    if proxy:
        # prior-year same window
        s = date.fromisoformat(start).replace(year=date.fromisoformat(start).year - 1)
        e = date.fromisoformat(end).replace(year=date.fromisoformat(end).year - 1)
        data = _get(ARCHIVE, {"latitude": lat, "longitude": lon,
                              "start_date": s.isoformat(), "end_date": e.isoformat(),
                              "daily": _DAILY, "timezone": "auto"})
        source = f"Open-Meteo archive (prior-year proxy {s.isoformat()}..{e.isoformat()})"
    else:
        data = _get(FORECAST, {"latitude": lat, "longitude": lon,
                               "start_date": start, "end_date": end,
                               "daily": _DAILY, "timezone": "auto"})
        source = "Open-Meteo forecast"

    d = data.get("daily", {})
    days = []
    for i, dt in enumerate(d.get("time", [])):
        wf = d.get("wind_direction_10m_dominant", [None] * len(d["time"]))[i]
        days.append({
            "date": dt, "is_proxy": proxy,
            "t_min_c": d.get("temperature_2m_min", [None])[i],
            "t_max_c": d.get("temperature_2m_max", [None])[i],
            "wind_from_deg": wf,
            "wind_from_compass": compass(wf) if wf is not None else None,
            "wind_kmh": d.get("wind_speed_10m_max", [None])[i],
            "precip_mm": d.get("precipitation_sum", [None] * len(d["time"]))[i],
            "sunrise": d.get("sunrise", [None])[i],
            "sunset": d.get("sunset", [None])[i],
        })
    return {"source": source, "days": days}
