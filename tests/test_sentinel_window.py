"""The satellite greenness must be current, and it must be leaf-on (T10.16).

Two bugs lived in one hardcoded line, `datetime="2023-07-01/2024-09-15"`.

THE ONE THAT WAS REPORTED as a missing feature: the window was a literal, so every run
built its browse surface from 2023-24 imagery no matter when it ran, drifting further
out of date every day. Cuts and burns newer than Sept 2024 were invisible to the
greenness term — on ground whose whole browse story is disturbance age.

THE ONE THAT WAS FOUND WHILE FIXING IT, which is worse: that window spanned a boreal
winter, and scenes were ranked by LOWEST CLOUD. Snow is not cloud. A snowfield reads as
a beautifully clear scene, so the composite was being fed snow — measured on the live
catalogue, 3 of the 10 scenes over Fire Lake were 2023-12-08 at 87-93% snow, and 2 of 10
over Rouyn were 2023-11-25 at 54%. Snow reflects high in both red and NIR, so its NDVI
collapses toward zero and drags the per-pixel median down with it. Removing those scenes
moved mean NDVI 0.272 -> 0.320 at Rouyn (p10 0.149 -> 0.225) and shifted 38% of the box
by more than 0.05; 12% of cells at Fire Lake. The browse surface had been reading
systematically LOW, silently, over more than a third of some boxes.

NDVI for browse means LEAF-ON greenness. There is no version of that question a December
scene helps answer.
"""
from datetime import date

import pytest

from moose_scout.acquire import sentinel as s2


# ------------------------------------------------------------------- it follows time


def test_the_window_is_not_a_literal():
    """The bug, stated as a test. If a date range is ever hardcoded here again, the
    imagery starts ageing the moment it ships."""
    import inspect

    # `fetch`, not the module: the module docstring quotes the old literal on purpose,
    # as the record of what went wrong. What matters is that no literal reaches the
    # catalogue.
    src = inspect.getsource(s2.fetch)
    assert "2023-07-01" not in src and "2024-09-15" not in src
    assert "season_windows(today)" in src, "the search no longer derives its window"


@pytest.mark.parametrize("today,expected_newest", [
    (date(2026, 8, 7), 2026),      # mid-season: this summer, clamped to today
    (date(2026, 12, 31), 2026),    # after season: this summer, complete
    (date(2026, 5, 1), 2025),      # before green-up: this season has not begun
    (date(2027, 3, 15), 2026),
])
def test_the_newest_season_tracks_the_run_date(today, expected_newest):
    assert s2.season_windows(today)[0][0].year == expected_newest
    assert s2.imagery_epoch(today) == expected_newest


def test_an_unstarted_season_is_never_searched():
    """Asking for imagery from a summer that has not happened returns nothing, and
    'nothing' would fall through to an exception rather than to last year."""
    for w in s2.season_windows(date(2026, 5, 1)):
        assert w[0] <= date(2026, 5, 1)


def test_a_mid_season_window_stops_at_today():
    start, end = s2.season_windows(date(2026, 7, 1))[0]
    assert end == date(2026, 7, 1), "asked the catalogue for imagery from the future"


def test_windows_are_newest_first_so_fresh_imagery_wins():
    """The fetch stops as soon as it has enough scenes. Newest-first is what makes a box
    with good current cover never reach back a year."""
    years = [w[0].year for w in s2.season_windows(date(2026, 8, 7))]
    assert years == sorted(years, reverse=True)
    assert len(years) >= 3, "no fallback if this summer is clouded out"


# -------------------------------------------------------------------- it is leaf-on


def test_every_window_is_inside_the_growing_season():
    """THE SNOW BUG. A window that spans a winter WILL pick up snow, because the ranking
    that finds clear scenes cannot tell a snowfield from a clear day."""
    for start, end in s2.season_windows(date(2026, 12, 31)):
        assert (start.month, start.day) >= (6, 1), f"window starts too early: {start}"
        assert (end.month, end.day) <= (9, 30), f"window ends too late: {end}"


class _Item:
    def __init__(self, cloud, snow):
        self.properties = {"eo:cloud_cover": cloud, "s2:snow_ice_percentage": snow}


def test_a_snowy_scene_is_rejected_however_clear_it_is():
    """The exact scenes that were being composited: 2023-12-08 over Fire Lake at 93%
    snow and 0.3% cloud — the lowest-cloud scene in the whole window."""
    assert not s2._usable(_Item(cloud=0.3, snow=93.0))
    assert not s2._usable(_Item(cloud=0.0, snow=54.0))
    assert not s2._usable(_Item(cloud=1.0, snow=6.0))


def test_a_clear_summer_scene_is_kept():
    assert s2._usable(_Item(cloud=0.2, snow=0.0))
    assert s2._usable(_Item(cloud=12.0, snow=0.001))


def test_a_cloudy_scene_is_still_rejected():
    assert not s2._usable(_Item(cloud=40.0, snow=0.0))


def test_a_missing_snow_property_does_not_reject_the_scene():
    """Not every item carries s2:snow_ice_percentage. Treating absent as 100% would
    empty the catalogue."""
    it = _Item(cloud=1.0, snow=0.0)
    it.properties.pop("s2:snow_ice_percentage")
    assert s2._usable(it)


# ------------------------------------------------------- the cache cannot hide staleness


def test_the_cache_is_keyed_on_the_imagery_epoch():
    """The geography cache keys on GEOMETRY alone, so without this it would serve one
    season's greenness forever — which is how the window came to be two years stale
    without anyone noticing."""
    import inspect

    src = inspect.getsource(s2.fetch)
    assert 'epoch' in src and 'side.exists()' in src, \
        "a bare ndvi.tif is once again enough to skip the fetch"

    from moose_scout import geocache
    assert "ndvi.json" in geocache.ARTIFACTS, \
        "the sidecar is not shared, so a cache hit restores the raster without its date"
