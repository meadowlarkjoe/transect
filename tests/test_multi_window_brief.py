"""Each window gets its OWN brief, not window 1's under every heading (T10.1).

Reported from a real two-window run: "the brief for both areas provides its analysis
based on the first date range. The only place where the different time windows are
compared is at the top." Confirmed in the exported PDF, whose header read
`dates 2026-10-10 → 2026-10-25` — one window — on a run that had two.

WHAT WAS ACTUALLY BROKEN, because it is a narrower thing than it looks. T9.2 got the
MODEL right: `_merge` really does run every (site × window) as its own analysis and tag
every area, waypoint and route with its window. What it missed is that `base` is plan
1's whole document, and only the LISTS were merged. Every non-list section — the rut
read, the strategy, the recommendations, the weather, the day plan — stayed plan 1's.

So a bow-season area was briefed with rifle-season advice, and nothing anywhere said
which dates the advice was written for. That is the worst shape a bug can take: the
engine computed the right answer, once per window, and the product then showed one of
them under all of them.

These tests pin the reporting, since the model was never the problem.
"""
import pytest

from moose_scout import worker


BOW = ["2026-09-12", "2026-09-20"]
RIFLE = ["2026-10-10", "2026-10-25"]


def _plans(windows, coords=((1.0, 1.0),)):
    return [{"site": si, "lat": c[0], "lon": c[1], "window": wi, "dates": list(w)}
            for si, c in enumerate(coords, start=1)
            for wi, w in enumerate(windows, start=1)]


def _doc(tag, areas=1):
    """A contract with every dated section carrying a recognisable marker."""
    return {
        "schema": "transect/1", "legal": {"zone": "13"}, "meta": {"target_dates": []},
        "areas": [{"rank": 1, "area_km2": 5.0, "habitat_score": 0.4}] * areas,
        "waypoints": [], "routes": [], "camps": [], "browse_zones": [],
        "rut": {"hunt_read": f"{tag} rut read", "phase_note": f"{tag} phase",
                "targets": [{"phase": tag, "date": "2026-01-01", "responsiveness": 0.5}]},
        "strategy": {"headline": f"{tag} strategy", "calling": f"{tag} calling"},
        "recommendations": [f"{tag} recommendation"],
        "field_plan": {"day_plan": f"{tag} day plan", "calling_sequence": f"{tag} seq"},
        "weather": {"summary": f"{tag} weather"},
        "behavior": {"periods": f"{tag} periods"},
        "scent": {"note": f"{tag} scent"},
        "wind": {"prevailing": f"{tag} wind"},
    }


# ------------------------------------------------------------------ the reported bug


def test_each_window_carries_its_own_dated_sections():
    """THE ONE THIS EXISTS FOR. Before the fix these all came back 'bow' — window 1's —
    whichever window you were reading."""
    out = worker._merge([_doc("bow"), _doc("rifle")], _plans([BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    assert w[1]["brief"]["rut"]["hunt_read"] == "bow rut read"
    assert w[2]["brief"]["rut"]["hunt_read"] == "rifle rut read"
    assert w[2]["brief"]["strategy"]["headline"] == "rifle strategy"
    assert w[2]["brief"]["recommendations"] == ["rifle recommendation"]
    assert w[2]["brief"]["field_plan"]["day_plan"] == "rifle day plan"
    assert w[2]["brief"]["weather"]["summary"] == "rifle weather"


@pytest.mark.parametrize("section", worker.WINDOW_SECTIONS)
def test_every_dated_section_is_carried(section):
    """A section that is a function of the dates but is NOT carried silently falls back
    to window 1 — which is exactly how this bug worked. Adding a dated section to the
    contract without adding it here brings it straight back."""
    out = worker._merge([_doc("bow"), _doc("rifle")], _plans([BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    if section in _doc("rifle"):
        assert section in w[2]["brief"], f"{section} is not carried per window"
        assert "rifle" in str(w[2]["brief"][section])


def test_a_window_carries_the_dates_it_was_written_for():
    """The brief has to be able to SAY which dates it is for. The reported export said
    one window's dates on a two-window run and that was the whole tell."""
    out = worker._merge([_doc("bow"), _doc("rifle")], _plans([BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    assert w[1]["dates"] == BOW and w[2]["dates"] == RIFLE
    assert w[1]["start"] == BOW[0] and w[1]["end"] == BOW[1]


def test_the_top_level_says_which_window_it_belongs_to():
    """The top level still carries window 1's sections so older clients and saved plans
    keep rendering. That is only safe if it is labelled — unlabelled, it is the bug."""
    out = worker._merge([_doc("bow"), _doc("rifle")], _plans([BOW, RIFLE]))
    assert out["meta"]["top_level_window"] == 1
    assert out["rut"]["hunt_read"] == "bow rut read"      # window 1, and now it says so


# --------------------------------------------------------------- it stays proportionate


def test_a_single_window_run_is_completely_unchanged():
    """No `windows` block, no label, nothing new to read. Most hunts are one window and
    must not pay for this."""
    d = _doc("only")
    out = worker._merge([d], _plans([RIFLE]))
    assert out == d
    assert "windows" not in out and "top_level_window" not in (out.get("meta") or {})


def test_sites_do_not_get_a_window_brief():
    """Two sites in ONE window is not a multi-window run; the dated sections are shared
    and duplicating them per site would be noise."""
    out = worker._merge([_doc("a"), _doc("b")], _plans([RIFLE], coords=((1.0, 1.0), (2.0, 2.0))))
    assert "windows" not in out
    assert len(out["sites"]) == 2


def test_a_failed_window_is_flagged_and_carries_no_brief():
    """A window that did not run has nothing to say, and must not borrow the other's."""
    out = worker._merge([_doc("bow"), None], _plans([BOW, RIFLE]))
    w = {x["window"]: x for x in out["windows"]}
    assert w[2]["ok"] is False and "brief" not in w[2]
    assert w[1]["brief"]["rut"]["hunt_read"] == "bow rut read"


# ------------------------------------------------------------------- the app reads it


def test_the_brief_reads_the_area_s_window_and_never_the_top_level():
    """The engine has been computing this correctly all along — the failure was entirely
    in the reporting, so this is the assertion that matters."""
    import pathlib
    import re

    src = pathlib.Path("app/app.js").read_text()
    assert "function wsec(" in src and "function windowOf(" in src

    start = src.index("function renderBrief(){")
    end = src.index("\nfunction ", src.index("briefSection(FP.day_plan", start))
    body = src[start:end]
    stale = re.findall(r"DOC\.(rut|strategy|field_plan|recommendations)\b", body)
    assert not stale, f"the brief still reads top-level dated sections: {set(stale)}"
