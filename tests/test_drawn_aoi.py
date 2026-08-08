"""Analyse a padded box, report the drawing (T10.8).

Asked: "right now we only do analysis by radius. and the minimum area is 5km. For a
hunting camp we are currently looking at buying, that area is too big. I have a smaller,
specific area that I want to analyze."

THE PART THAT MATTERS, and the reason the 5 km floor existed: the engine cannot answer
about a parcel using only the parcel. `dist_road` measures to a road usually OUTSIDE the
boundary; a land-bridge funnel needs the lakes on BOTH sides of the neck; TPI uses a 500 m
window, the pinch test 600 m, pressure decays over 1.5 km. A tight polygon analysed alone
reports "no access, no funnels" about ground that has both — confidently, which is the
worst way to be wrong.

So: analyse a PADDED box, clip the OUTPUT to the ring.
"""
import pytest

pytest.importorskip("shapely")

from moose_scout.config import AOI, DRAW_PAD_KM, LatLon, SeasonCfg
from moose_scout.contract import CLIP_MIN_OVERLAP, _clip_to_ring

RING = [(-78.50, 47.80), (-78.44, 47.80), (-78.44, 47.84), (-78.50, 47.84), (-78.50, 47.80)]


def _aoi(ring=RING, rad=14.0, pad=None):
    kw = {} if pad is None else {"pad_km": pad}
    return AOI(name="t", center=LatLon(lat=47.82, lon=-78.47), bbox_halfwidth_km=rad,
               ring=ring, season=SeasonCfg(year=2026,
                                           target_dates=["2026-10-01", "2026-10-10"]), **kw)


def _poly(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]


# ------------------------------------------------------------------------- the extent


def test_a_drawn_aoi_analyses_more_ground_than_it_was_given():
    """The whole point. The analysis box must exceed the ring on every side."""
    a = _aoi()
    minlon, minlat, maxlon, maxlat = a.bbox_wgs84()
    assert minlon < -78.50 and maxlon > -78.44
    assert minlat < 47.80 and maxlat > 47.84


def test_the_padding_clears_every_window_the_model_uses():
    """1.5 km pressure decay is the widest of them; anything less and a parcel would be
    told it has no hunter pressure because the road is just outside its own boundary."""
    assert DRAW_PAD_KM >= 1.5


def test_a_radius_aoi_is_completely_unaffected():
    a = AOI(name="t", center=LatLon(lat=47.82, lon=-78.47), bbox_halfwidth_km=14.0,
            season=SeasonCfg(year=2026, target_dates=["2026-10-01", "2026-10-10"]))
    assert a.drawn is False
    doc = {"areas": [{"geometry": {"type": "Polygon", "coordinates": [_poly(0, 0, 1, 1)]},
                      "rank": 1}]}
    assert _clip_to_ring(dict(doc), a)["areas"] == doc["areas"]


def test_the_grid_is_sized_from_the_box_being_analysed():
    """`effective_halfwidth_km`, not the stored radius. A drawn parcel carrying a
    leftover 35 km slider value would otherwise be gridded for a box 20x its size."""
    small = _aoi().effective_halfwidth_km()
    assert small < 6.0, small
    big = AOI(name="t", center=LatLon(lat=47.82, lon=-78.47), bbox_halfwidth_km=35.0,
              season=SeasonCfg(year=2026, target_dates=["2026-10-01", "2026-10-10"]))
    assert 34.0 < big.effective_halfwidth_km() < 36.0


def test_a_malformed_ring_falls_back_to_the_radius():
    """Three points is not a ring. It must not fail the run."""
    a = AOI(name="t", center=LatLon(lat=47.82, lon=-78.47), bbox_halfwidth_km=14.0,
            ring=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
            season=SeasonCfg(year=2026, target_dates=["2026-10-01", "2026-10-10"]))
    assert a.drawn is False
    assert 13.0 < a.effective_halfwidth_km() < 15.0


# ------------------------------------------------------------------------- the clipping


def test_a_zone_outside_the_parcel_is_dropped():
    doc = {"hunt_zones": [{"ll": _poly(-78.49, 47.81, -78.46, 47.83), "area_km2": 1},
                          {"ll": _poly(-78.30, 47.90, -78.28, 47.92), "area_km2": 1}]}
    out = _clip_to_ring(doc, _aoi())
    assert len(out["hunt_zones"]) == 1


def test_a_zone_that_merely_grazes_the_edge_is_dropped():
    """A feature sharing a sliver with the parcel is not a finding about the parcel."""
    doc = {"hunt_zones": [{"ll": _poly(-78.4405, 47.81, -78.30, 47.83), "area_km2": 1}]}
    assert _clip_to_ring(doc, _aoi())["hunt_zones"] == []


def test_the_overlap_bar_is_a_share_not_a_touch():
    assert 0.0 < CLIP_MIN_OVERLAP < 0.5


def test_focus_area_ranks_stay_contiguous_after_a_drop():
    """Rank is an identity the brief, the map badges and the routes all key on. A gap
    would leave "Area 2" on the map with no Area 2 in the list."""
    doc = {"areas": [
        {"geometry": {"type": "Polygon", "coordinates": [_poly(-78.30, 47.90, -78.28, 47.92)]}, "rank": 1},
        {"geometry": {"type": "Polygon", "coordinates": [_poly(-78.49, 47.81, -78.46, 47.83)]}, "rank": 2},
        {"geometry": {"type": "Polygon", "coordinates": [_poly(-78.48, 47.815, -78.45, 47.825)]}, "rank": 3}]}
    out = _clip_to_ring(doc, _aoi())
    assert [a["rank"] for a in out["areas"]] == [1, 2]


def test_routes_are_never_clipped():
    """The road you drive in on starts outside the parcel. Clipping it would amputate the
    approach and then report the stump as the way in."""
    from moose_scout import contract
    assert "routes" not in contract._CLIP_RING_KEYS
    doc = {"routes": [{"type": "route_access", "coords": [[-78.2, 47.9], [-78.47, 47.82]]}]}
    assert len(_clip_to_ring(doc, _aoi())["routes"]) == 1


def test_a_staging_point_outside_the_parcel_survives():
    """Staging is where you leave the truck — on a road, and therefore usually outside a
    boundary. Dropping it leaves every route starting from nowhere."""
    doc = {"waypoints": [{"type": "parking", "lat": 47.90, "lon": -78.30},
                         {"type": "rut_calling", "lat": 47.90, "lon": -78.30},
                         {"type": "rut_calling", "lat": 47.82, "lon": -78.47}]}
    out = _clip_to_ring(doc, _aoi())["waypoints"]
    assert [w["type"] for w in out] == ["parking", "rut_calling"]
    assert out[1]["lat"] == 47.82


def test_the_document_says_which_mode_produced_it_and_how_much_padding():
    out = _clip_to_ring({"areas": []}, _aoi())
    assert out["aoi_mode"] == "drawn"
    assert out["aoi_pad_km"] == DRAW_PAD_KM
    assert out["aoi_ring"][0] == [-78.5, 47.8]
    assert out["aoi_clip"]["min_overlap"] == CLIP_MIN_OVERLAP


def test_a_clip_failure_keeps_the_feature_rather_than_losing_it():
    """Over-reporting is recoverable by looking at the map. Silently dropping a focus
    area is not — and a clip must never be able to lose an analysis."""
    doc = {"hunt_zones": [{"ll": "not a polygon", "area_km2": 1}],
           "areas": [{"geometry": None, "rank": 1}]}
    out = _clip_to_ring(doc, _aoi())
    assert len(out["hunt_zones"]) == 1
    assert len(out["areas"]) == 1


# ------------------------------------------------------------------------ saying so


def test_the_brief_says_it_looked_beyond_the_boundary():
    """It leads the caveats rather than trailing them: it changes how every number below
    it reads. Scores are relative within the PADDED box, and features were removed for
    being outside a line rather than for being poor ground — a hunter who does not know
    that reads an empty corner of their parcel as "nothing here"."""
    from moose_scout.synth import _mode_caveats

    class _Ctx:
        aoi = _aoi()
    c = _mode_caveats(_Ctx())
    assert len(c) == 1
    assert f"{DRAW_PAD_KM:g} km" in c[0]
    assert "BEYOND" in c[0]
    assert "Routes are the exception" in c[0]


def test_a_radius_run_gets_no_such_caveat():
    from moose_scout.synth import _mode_caveats

    class _Ctx:
        aoi = AOI(name="t", center=LatLon(lat=47.82, lon=-78.47), bbox_halfwidth_km=14.0,
                  season=SeasonCfg(year=2026, target_dates=["2026-10-01", "2026-10-10"]))
    assert _mode_caveats(_Ctx()) == []


# --------------------------------------------------------------------- the setup form

import pathlib as _pl  # noqa: E402
import re as _re  # noqa: E402

_APP = _pl.Path("app/app.js")


def _code():
    return _re.sub(r"//[^\n]*", "", _APP.read_text())


def _fn(name):
    src = _APP.read_text()
    i = src.index(f"function {name}(")
    return src[i:src.index("\nfunction ", i + 10)]


def test_setup_offers_both_modes_with_radius_as_the_default():
    src = _code()
    assert 'data-aoimode="radius"' in src and 'data-aoimode="drawn"' in src
    body = _fn("aoiModeUI")
    assert "draft.aoiMode==='drawn'" in body.replace(" ", "")


def test_you_can_select_drawn_mode_before_you_have_drawn_anything():
    """THIS TEST PINNED THE BUG. It used to assert that `aoiMode` required a drawn area
    to return 'drawn' — which is true and was also the whole problem, because the panel
    holding the "Draw an area on the map" button was gated on that same answer. You
    needed an area to reach the button that lets you draw one. Reported as "i cannot
    select Drawn area".

    Two questions, kept apart now: `aoiModeUI` is which panel you are LOOKING at and
    follows what you picked; `aoiMode` is which mode is SATISFIED and needs a shape."""
    ui = _fn("aoiModeUI")
    assert "drawnAreas" not in ui, "the door is gated on having already gone through it"
    assert "draft.aoiMode==='drawn'" in ui.replace(" ", "")
    src = _code()
    assert "aoiModeUI()==='drawn'" in src.replace(" ", ""), \
        "the panel does not follow the user's choice"


def test_the_effective_mode_still_requires_a_shape():
    """The guard the old version was reaching for is still here — it just moved off the
    door. A drawn run with no ring must never quietly become a radius run."""
    body = _fn("aoiMode")
    assert "drawnAreas().length" in body


def test_choosing_drawn_with_nothing_drawn_blocks_the_run_by_name():
    src = _APP.read_text()
    i = src.index("function missingSetup(){")
    body = src[i:src.index("\n}", i)]
    assert "aoiModeUI()==='drawn'" in body.replace(" ", "")
    assert "draw one on the map" in body


def test_the_ring_comes_from_a_shape_actually_on_the_map():
    body = _fn("drawnAreas")
    assert "dtype==='area'" in body.replace(" ", "")
    assert "length>=4" in body.replace(" ", ""), "a 3-point ring is not a polygon"


def test_the_grid_and_the_estimate_are_sized_from_the_analysed_box():
    """THE TRAP. A drawn parcel carries whatever the radius slider last held, so quoting
    `draft.radius` offers a 35 km box's grid and run estimate for a 2 km parcel."""
    src = _code()
    assert "estimateMinutes(draft.radius" not in src, "a run estimate still quotes the slider"
    body = _fn("_syncResUI")
    assert "aoiHalfwidthKm()" in body
    assert "resBounds(draft.radius)" not in body


def test_the_client_padding_matches_the_engine():
    """Two constants describing one number. They are checked against each other rather
    than merely both existing."""
    from moose_scout.config import DRAW_PAD_KM as engine_pad
    m = _re.search(r"const AOI_PAD_KM=([\d.]+);", _code())
    assert m, "the client lost its padding constant"
    assert float(m.group(1)) == float(engine_pad)


def test_the_radius_slider_handler_is_guarded():
    """It does not exist in drawn mode, and `rad.oninput` on null throws — which would
    kill every handler wired after it, silently, the moment you switched modes."""
    src = _APP.read_text()
    i = src.index("const rad=document.getElementById('radius');")
    seg = src[i:i + 1200]
    assert "if(rad){" in seg


def test_the_request_carries_the_ring_and_still_carries_a_radius():
    """The radius is the fallback for an older client reopening the plan, and for a ring
    the engine rejects as malformed — falling back to a sane box beats falling back to
    nothing."""
    src = _APP.read_text()
    assert "ring:_ring||null," in src
    i = src.index("ring:_ring||null,")
    assert "radius_km:" in src[i - 200:i]
