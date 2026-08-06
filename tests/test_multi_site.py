"""Known sites 2–4 must actually be analysed (T9.1).

THE BUG THIS EXISTS FOR. Setup has always said "up to 4 sites — each gets its own
analysis, ranked against the others". The engine never read past the first one: `sites`
was validated in api.py, threaded through config.py, echoed into doc.meta — and consumed
by NOTHING in the analysis. sites[0] doubled as the AOI centre; 2..4 were drawn as rings
on the client and thrown away.

Measured on a real run: two sites 50 km apart, meta.radius_km 9, both returned areas
within 3 km of site 1, and site 2 produced nothing. Worse than empty — the app showed an
"Area 2" tab, which reads as the second SITE but was a second focus area beside the
first. The hunter had no way to know only half their question was answered.

That is the worst class of defect this project can ship: not a crash, not a blank, but a
confident answer to a question nobody asked.
"""
import json

import pytest

from moose_scout import worker


# --------------------------------------------------------------- which sites get run


def test_sites_are_read_from_the_request():
    req = {"lat": 47.8, "lon": -77.8,
           "sites": [[47.8, -77.8], [47.9, -77.1], [48.0, -76.5]]}
    assert worker.sites_of(req) == [(47.8, -77.8), (47.9, -77.1), (48.0, -76.5)]


def test_a_request_with_no_sites_still_analyses_its_centre():
    """The common case — "find sites in this box" — must be untouched."""
    assert worker.sites_of({"lat": 47.8, "lon": -77.8}) == [(47.8, -77.8)]
    assert worker.sites_of({"lat": 47.8, "lon": -77.8, "sites": []}) == [(47.8, -77.8)]


def test_more_than_four_sites_are_clamped_not_silently_dropped_at_one():
    req = {"lat": 1.0, "lon": 1.0, "sites": [[i, i] for i in range(1, 9)]}
    assert len(worker.sites_of(req)) == 4


def test_a_malformed_site_is_skipped_rather_than_killing_the_run():
    req = {"lat": 47.8, "lon": -77.8,
           "sites": [[47.8, -77.8], ["x", None], [999, 999], [48.0, -76.5]]}
    assert worker.sites_of(req) == [(47.8, -77.8), (48.0, -76.5)]


def test_the_worker_actually_loops_over_them():
    """The whole defect was that nothing consumed `sites`. Pin the wiring, not just the
    helper — a helper nobody calls is exactly what was already there."""
    import inspect
    src = inspect.getsource(worker.run)
    assert "sites_of(req)" in src, "run() no longer asks which sites to analyse"
    assert "for si, (slat, slon) in enumerate(sites" in src, "run() no longer loops sites"
    assert "_merge(" in src, "per-site results are not being merged"


def test_each_site_gets_its_own_cache():
    """Sharing one cache directory would have site 2's rasters overwrite site 1's and
    report the wrong ground for both — a subtler version of the same silent-wrong-answer
    failure."""
    import inspect
    src = inspect.getsource(worker.run)
    assert 'f"{name}_s{si}"' in src, "sites are not given separate cache identities"


# ------------------------------------------------------------------------ the merge


def _doc(areas, extra=None):
    d = {"schema": "transect/1", "meta": {"center": {"lat": 1, "lon": 1}},
         "legal": {"zone": "13"}, "areas": areas, "waypoints": [], "routes": [],
         "camps": [], "browse_zones": []}
    if extra:
        d.update(extra)
    return d


def test_a_single_site_merge_is_the_document_itself():
    """One site must be byte-for-byte what it always was — no `sites` block, no site
    tags, nothing for the client to newly understand."""
    d = _doc([{"rank": 1, "area_km2": 5.0, "habitat_score": 0.4}])
    out = worker._merge([d], [(1.0, 1.0)])
    assert out == d
    assert "sites" not in out


def test_areas_from_every_site_survive_and_are_ranked_together():
    a = _doc([{"rank": 1, "area_km2": 4.0, "habitat_score": 0.30},     # 1.20
              {"rank": 2, "area_km2": 2.0, "habitat_score": 0.20}])    # 0.40
    b = _doc([{"rank": 1, "area_km2": 6.0, "habitat_score": 0.50}])    # 3.00  <- best
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    assert len(out["areas"]) == 3, "an area was dropped — this is the original bug"
    assert [x["rank"] for x in out["areas"]] == [1, 2, 3]
    top = out["areas"][0]
    assert top["site"] == 2 and top["area_km2"] == 6.0, \
        "ranking across sites did not pick the best ground"
    # ...and each area remembers where it ranked within its own site.
    assert top["site_rank"] == 1


def test_every_area_says_which_site_it_belongs_to():
    """An area, a stand and a route on different ground must never read as one plan."""
    a = _doc([{"rank": 1, "area_km2": 1.0, "habitat_score": 0.1}])
    b = _doc([{"rank": 1, "area_km2": 1.0, "habitat_score": 0.2}])
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    assert {x["site"] for x in out["areas"]} == {1, 2}


def test_the_summary_says_how_the_sites_compare():
    """The actual question a hunter asks by entering four coordinates."""
    a = _doc([{"rank": 1, "area_km2": 4.0, "habitat_score": 0.30}])
    b = _doc([{"rank": 1, "area_km2": 6.0, "habitat_score": 0.50}])
    out = worker._merge([a, b], [(47.8, -77.8), (47.9, -77.1)])
    s = {x["site"]: x for x in out["sites"]}
    assert s[1]["lat"] == 47.8 and s[2]["lat"] == 47.9
    assert s[2]["best_habitat"] == 0.5
    assert s[2]["best_rank_overall"] == 1 and s[1]["best_rank_overall"] == 2
    assert out["meta"]["multi_site"] is True


def test_a_site_that_produced_nothing_is_reported_not_hidden():
    """A site with no qualifying ground is a FINDING. Dropping it silently is how the
    original bug read to a hunter."""
    a = _doc([{"rank": 1, "area_km2": 4.0, "habitat_score": 0.30}])
    b = _doc([])
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    s = {x["site"]: x for x in out["sites"]}
    assert s[2]["ok"] is True and s[2]["areas"] == 0
    assert len(out["sites"]) == 2


def test_a_site_that_FAILED_is_flagged_and_the_others_still_return():
    """One bad site must not cost the hunter the other three."""
    a = _doc([{"rank": 1, "area_km2": 4.0, "habitat_score": 0.30}])
    out = worker._merge([a, None], [(1.0, 1.0), (2.0, 2.0)])
    s = {x["site"]: x for x in out["sites"]}
    assert s[2]["ok"] is False and "could not be analysed" in s[2]["note"]
    assert len(out["areas"]) == 1


def test_the_shared_scaffolding_comes_from_one_site_not_a_blend():
    """Legal gate, legend and methodology describe a place. Merging verdicts across
    sites would invent a claim nobody computed."""
    a = _doc([{"rank": 1, "area_km2": 1.0, "habitat_score": 0.1}],
             {"legal": {"zone": "13"}, "methodology": {"x": 1}})
    b = _doc([{"rank": 1, "area_km2": 9.0, "habitat_score": 0.9}],
             {"legal": {"zone": "27"}, "methodology": {"x": 2}})
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    assert out["legal"]["zone"] == "13", "legal came from somewhere other than site 1"
    assert out["methodology"]["x"] == 1


def test_map_layers_from_all_sites_are_carried():
    a = _doc([], {"browse_zones": [{"ll": [[0, 0]], "area_km2": 1}]})
    b = _doc([], {"browse_zones": [{"ll": [[1, 1]], "area_km2": 2}]})
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    assert len(out["browse_zones"]) == 2
    assert {z["site"] for z in out["browse_zones"]} == {1, 2}


def test_camp_ids_do_not_collide_across_sites():
    """Each site's contract letters its own camps from A, so two sites both produce a
    "Camp A" — and the app finds an area's camp by matching that letter. Left alone,
    site 2's areas attach to site 1's camp and the brief sends the hunter to the wrong
    cabin. Same family as every other bug this week: two things deriving the same
    identity independently.
    """
    a = _doc([{"rank": 1, "area_km2": 1.0, "habitat_score": 0.1, "camp": "A"}],
             {"camps": [{"id": "A", "site": {"lat": 1, "lon": 1}}]})
    b = _doc([{"rank": 1, "area_km2": 9.0, "habitat_score": 0.9, "camp": "A"}],
             {"camps": [{"id": "A", "site": {"lat": 2, "lon": 2}}]})
    out = worker._merge([a, b], [(1.0, 1.0), (2.0, 2.0)])
    ids = [c["id"] for c in out["camps"]]
    assert len(set(ids)) == 2, f"camp ids collided: {ids}"
    # every area must point at a camp that exists, and at ITS OWN site's camp
    by_site = {c["site"]: c["id"] for c in out["camps"]}
    for ar in out["areas"]:
        assert ar["camp"] == by_site[ar["site"]], "an area was attached to another site's camp"
