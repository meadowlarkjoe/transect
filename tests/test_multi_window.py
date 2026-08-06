"""Bow season and rifle season are different model runs (T9.2).

Requested as: "It would be nice if i could add bow season seperately and then the brief
could break down the pros/cons of each available hunting window."

The temptation is to treat this as presentation — same analysis, two date headings. It
is not. The habitat surface is PHASE-WEIGHTED (habitat_phase.tif: cow-weighted at peak
rut, feed-weighted after it), and behavior, synth and the contract all read the dates
too. Mid-September bow and late-October rifle produce genuinely different huntability,
different site mixes and different stands ON THE SAME GROUND. Rendering one run's answer
under two headings would be a lie that looks like a feature.

So a window is a run, and this file pins that it is treated as one.
"""
import pytest

from moose_scout import worker


BOW = ["2026-09-12", "2026-09-20"]
RIFLE = ["2026-10-10", "2026-10-25"]


# ------------------------------------------------------------ which windows get run


def test_windows_are_read_from_the_request():
    assert worker.windows_of({"windows": [BOW, RIFLE]}) == [BOW, RIFLE]


def test_a_request_with_no_windows_uses_its_target_dates():
    """The common case must be untouched — one window, exactly as before."""
    assert worker.windows_of({"target_dates": RIFLE}) == [RIFLE]
    assert worker.windows_of({"target_dates": RIFLE, "windows": []}) == [RIFLE]


def test_windows_are_clamped_rather_than_unbounded():
    """Every window is a full model run; an unbounded list is an unbounded bill."""
    req = {"windows": [[f"2026-09-{d:02d}", f"2026-09-{d+1:02d}"] for d in range(1, 9)]}
    assert len(worker.windows_of(req)) == 4


def test_a_malformed_window_is_skipped_not_fatal():
    assert worker.windows_of({"windows": [BOW, None, ["", ""], RIFLE]}) == [BOW, RIFLE]


# ------------------------------------------------------- windows compose with sites


def test_the_worker_runs_every_site_x_window_pair():
    """Two camps compared across bow and rifle is four analyses, and the hunter asked
    for all four. The loop must be the cross product, not one or the other."""
    import inspect
    src = inspect.getsource(worker.run)
    assert "windows_of(req)" in src, "run() never asks which windows to analyse"
    assert 'for si, (lat, lon) in enumerate(sites' in src and "for wi, w in enumerate(windows" in src, \
        "plans are not the cross product of sites and windows"


def test_each_plan_gets_its_own_cache_including_the_window():
    """Two windows on the SAME ground would otherwise share a cache, and the second's
    phase-weighted habitat would overwrite the first's — one answer under two headings,
    which is the exact failure this feature exists to avoid."""
    import inspect
    src = inspect.getsource(worker.run)
    assert "w{pl['window']}" in src, "the cache identity does not include the window"


def test_the_dates_actually_reach_the_sub_request():
    """A window that does not change target_dates changes nothing at all."""
    import inspect
    src = inspect.getsource(worker.run)
    assert 'target_dates=pl["dates"]' in src, "the plan's dates never reach build_ctx"


# ------------------------------------------------------------------------ the merge


def _plans(coords, windows):
    return [{"site": si, "lat": c[0], "lon": c[1], "window": wi, "dates": list(w)}
            for si, c in enumerate(coords, start=1)
            for wi, w in enumerate(windows, start=1)]


def _doc(areas, rut=None):
    d = {"schema": "transect/1", "meta": {}, "legal": {"zone": "13"}, "areas": areas,
         "waypoints": [], "routes": [], "camps": [], "browse_zones": []}
    if rut:
        d["rut"] = rut
    return d


def _area(km2, hab):
    return {"rank": 1, "area_km2": km2, "habitat_score": hab}


def test_one_window_is_unchanged():
    """A single-window run must produce no `windows` block and nothing new to read."""
    d = _doc([_area(5, 0.4)])
    out = worker._merge([d], _plans([(1.0, 1.0)], [RIFLE]))
    assert out == d
    assert "windows" not in out


def test_each_window_gets_its_own_verdict():
    bow = _doc([_area(4.0, 0.45)], rut={"hunt_read": "seeking phase — call aggressively",
                                        "targets": [{"phase": "seeking"}]})
    rifle = _doc([_area(6.0, 0.25)], rut={"hunt_read": "post-rut — hunt feeding sign",
                                          "targets": [{"phase": "post"}]})
    out = worker._merge([bow, rifle], _plans([(1.0, 1.0)], [BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    assert len(w) == 2
    assert w[1]["start"] == BOW[0] and w[1]["end"] == BOW[1]
    assert w[1]["phase"] == "seeking" and w[2]["phase"] == "post"
    assert "call aggressively" in w[1]["rut_read"]
    assert w[1]["best_habitat"] == 0.45 and w[2]["best_habitat"] == 0.25
    assert out["meta"]["multi_window"] is True and out["meta"]["window_count"] == 2


def test_areas_carry_their_window_so_two_weeks_never_read_as_one_plan():
    bow = _doc([_area(4.0, 0.45)])
    rifle = _doc([_area(6.0, 0.25)])
    out = worker._merge([bow, rifle], _plans([(1.0, 1.0)], [BOW, RIFLE]))
    assert {a["window"] for a in out["areas"]} == {1, 2}
    assert all("site" in a for a in out["areas"])


def test_ranking_still_spans_everything_compared():
    """area x habitat: 6.0*0.25 = 1.50 beats 4.0*0.45 = 1.80? No — 1.80 wins. The point
    is that the comparison is made ACROSS windows, not within one."""
    bow = _doc([_area(4.0, 0.45)])       # 1.80
    rifle = _doc([_area(6.0, 0.25)])     # 1.50
    out = worker._merge([bow, rifle], _plans([(1.0, 1.0)], [BOW, RIFLE]))
    assert out["areas"][0]["window"] == 1
    assert [a["rank"] for a in out["areas"]] == [1, 2]


def test_sites_and_windows_compose():
    """Two camps across two seasons is four plans, and both summaries must be right."""
    docs = [_doc([_area(4.0, 0.40)]),   # site1 bow
            _doc([_area(4.0, 0.20)]),   # site1 rifle
            _doc([_area(9.0, 0.50)]),   # site2 bow
            _doc([_area(1.0, 0.10)])]   # site2 rifle
    plans = _plans([(1.0, 1.0), (2.0, 2.0)], [BOW, RIFLE])
    out = worker._merge(docs, plans)
    assert len(out["areas"]) == 4
    s = {x["site"]: x for x in out["sites"]}
    w = {x["window"]: x for x in out["windows"]}
    assert s[2]["best_habitat"] == 0.5          # site 2 holds the best single area
    assert w[1]["areas"] == 2 and w[2]["areas"] == 2
    assert w[1]["total_km2"] == 13.0            # 4.0 + 9.0 across both sites in bow
    assert out["meta"]["multi_site"] and out["meta"]["multi_window"]


def test_a_window_that_failed_is_flagged_and_the_other_still_returns():
    bow = _doc([_area(4.0, 0.4)])
    out = worker._merge([bow, None], _plans([(1.0, 1.0)], [BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    assert w[2]["ok"] is False and "could not be analysed" in w[2]["note"]
    assert len(out["areas"]) == 1
