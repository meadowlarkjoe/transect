"""The data contract is the promise the front end binds to. Lock its shape.

These do not run the pipeline — they load a committed sample transect.json and
assert the fields the app reads actually exist. A field the engine stops emitting is
a field the client silently renders as blank; this is the cheapest place to catch it.
"""
import json
import os

import pytest

# Rouyn: a COMPLETE fresh pipeline run (real roads, habitat_phase present).
# Fire Lake's committed fixture is a legacy cache missing habitat_phase, which
# is why the canonical shape fixture is rouyn.
SAMPLE = os.path.join(os.path.dirname(__file__), "fixtures", "rouyn.transect.json")


@pytest.fixture(scope="module")
def doc():
    if not os.path.exists(SAMPLE):
        pytest.skip("no committed contract fixture yet (see tests/fixtures/README)")
    with open(SAMPLE) as f:
        return json.load(f)


def test_top_level_keys(doc):
    for k in ("meta", "areas", "waypoints", "routes", "hunt_zones",
              "legal", "crossings", "hydro"):
        assert k in doc, f"contract missing top-level '{k}'"


def test_areas_carry_reachability(doc):
    # the reachability gate must reach the client, or unreachable ground looks fine
    for a in doc["areas"]:
        assert "reachable" in a, "area missing reachability flag"
        if not a["reachable"]:
            assert a.get("unreachable_why"), "unreachable area with no reason stated"


def test_bands_come_from_habitat(doc):
    # likelihood bands must not fold access in — that hid prime, hard-to-reach ground
    assert doc.get("bands_source", "").startswith("habitat")


def test_crossings_are_graded(doc):
    for c in doc.get("crossings", []):
        assert c.get("kind") in ("bridge", "ford", "boat"), f"ungraded crossing: {c}"
        assert c.get("basis") in ("measured", "inferred")


def test_engine_revision_stamped(doc):
    assert isinstance(doc.get("engine_revision"), int), "contract must stamp its revision"
