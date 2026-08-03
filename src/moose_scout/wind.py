"""Wind helpers for approach planning.

The key tactic: approach a calling/glassing site from your camp with the wind in
your face, so your scent blows away from where the animal is expected. So the
**optimal wind** (the direction wind should come FROM) is the bearing from the
site back toward your approach origin (the camp/access). Then the app can compare
that to the forecast wind for each day and tell you which sites are "wind-right."
"""
from __future__ import annotations

import math

_COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def bearing(from_lat, from_lon, to_lat, to_lon) -> float:
    """Initial compass bearing FROM -> TO, degrees 0..360 (0=N, 90=E)."""
    p1, p2 = math.radians(from_lat), math.radians(to_lat)
    dl = math.radians(to_lon - from_lon)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def compass(deg: float) -> str:
    return _COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def optimal_wind(site_lat, site_lon, approach_lat, approach_lon) -> dict:
    """Optimal wind to hunt `site` when approaching from `approach` (camp/access):
    wind should come FROM the site toward the approach, i.e. into the hunter's
    face. Returns {from_deg, from_compass, approach_deg, note}."""
    approach_deg = bearing(approach_lat, approach_lon, site_lat, site_lon)  # camp->site travel
    from_deg = (approach_deg + 180) % 360                                    # wind FROM site->camp
    return {
        "from_deg": round(from_deg, 1),
        "from_compass": compass(from_deg),
        "approach_deg": round(approach_deg, 1),
        "approach_compass": compass(approach_deg),
        "note": f"Approach from the {compass(bearing(site_lat, site_lon, approach_lat, approach_lon))} "
                f"(camp side); hunt it on a wind out of the {compass(from_deg)}.",
    }


def wind_ok(optimal_from_deg: float, actual_from_deg: float, tolerance_deg: float = 45) -> bool:
    """Is the actual wind within tolerance of optimal (both 'from' bearings)?"""
    d = abs((optimal_from_deg - actual_from_deg + 180) % 360 - 180)
    return d <= tolerance_deg
