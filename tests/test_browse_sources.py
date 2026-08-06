"""Browse is a composite, and the way it is composed is the model.

THE THREE DEFECTS THIS PINS, all found by reading the code the hunter was doubting:
he said the browse layer looked "very coarse", produced "large polygons in areas where
there are probably dozens of different types of browse", and carried "no explainer
notes on why it is calculated". All three were the same line of code.

browse.tif was np.maximum() over land cover, NDVI, a burn-age curve, a stand-species
table and a cut-age curve. That:

  1. DESTROYED PROVENANCE. Nothing recorded which source set a cell — which is exactly
     why no explainer could be written. The information was thrown away, not merely
     left un-surfaced.
  2. MADE CORROBORATION WORTHLESS. Prime on one indicator scored identically to prime
     on all four.
  3. LET THE COARSEST SOURCE SET THE FLOOR. A precise, dated, surveyed layer could only
     ever RAISE a score. Measured on a real AOI: closed conifer averaged 0.297 browse
     because a 10 m satellite said "green", while the forest-stand map that had
     physically surveyed those polygons scores conifer at or below zero. 42% of that
     AOI scored over 0.5, which is where the big undifferentiated polygons came from.

And one plain mislabel found on the way: acquire/ecoforestiere.py defines stand code 5
as T_PARTIAL — coupe partielle, a cut that RETAINS its overstory — while habitat.py
called code 5 "regen" and gave it 0.85, the highest browse of any class. Partial cuts
were scored as prime regeneration. That survived because the species config those
numbers claimed to come from was never actually read.
"""
import numpy as np
import pytest

pytest.importorskip("yaml")

from moose_scout.config import load_species


SPECIES = load_species("moose")


# --------------------------------------------------------------------------- config


def test_the_species_config_actually_carries_the_browse_table():
    """If this is empty the wiring below is meaningless — the whole multi-species story
    rests on biology living in config rather than in Python literals."""
    ct = SPECIES.cover_types
    assert ct, "moose.yaml cover_types did not load"
    for key in ("resineux", "melange", "feuillus", "coupe_recente", "coupe_partielle"):
        assert key in ct, f"{key} missing from cover_types"
        assert "browse" in ct[key], f"{key} has no browse value"


def test_partial_cut_is_not_prime_regeneration():
    """THE MISLABEL. Stand code 5 is coupe partielle. It keeps its overstory, so it is a
    browse-and-cover MIX, not the money class. The old table gave it 0.85 — higher than
    anything else — under a comment calling it "regen"."""
    ct = SPECIES.cover_types
    assert ct["coupe_partielle"]["browse"] < ct["regeneration"]["browse"], \
        "a partial cut cannot out-browse full regeneration"
    assert ct["coupe_partielle"]["browse"] <= 0.6, \
        "coupe partielle scoring like prime regen is the bug this test exists for"
    # ...and it keeps cover, which is the whole point of leaving the overstory up.
    assert ct["coupe_partielle"]["cover"] > ct["coupe_recente"]["cover"]


def test_closed_conifer_is_poor_browse_in_the_config():
    """The value the satellite used to override. Config says conifer is at best nothing
    to eat; the raster clamps at 0, but it must not be FLOORED at 0.3 by land cover."""
    assert SPECIES.cover_types["resineux"]["browse"] <= 0.0


def test_habitat_reads_the_config_rather_than_a_second_copy_of_it():
    """The comment used to claim "(from config/species/moose.yaml cover_types)" while the
    numbers were literals. A comment is not a wire."""
    import inspect
    from moose_scout import habitat
    src = inspect.getsource(habitat.run)
    assert "cover_types" in src, "habitat no longer reads the species cover_types table"
    assert "STAND_CLASS" in src, "the raster-code -> config-class map is gone"
    # The raster taxonomy and the config taxonomy differ; the map between them must be
    # written down rather than assumed positionally.
    assert '5: "coupe_partielle"' in src, \
        "stand code 5 must map to coupe partielle (acquire/ecoforestiere.py T_PARTIAL = 5)"


# ------------------------------------------------------------------- the combine


def _combine(sources, support_w=0.25):
    """The precedence combine, mirrored here so the ordering can be tested on scalars.

    Kept deliberately small: this asserts the RULE (most precise source present wins,
    the rest corroborate), which is the thing that changed.
    """
    order = ["cut", "burn", "stand", "landcover"]
    present = [n for n in order if n in sources]
    base = sources[present[0]]
    others = [sources[n] for n in present[1:]]
    support = sum(others) / len(others) if others else base
    return float(np.clip(base * (1 - support_w) + support * support_w, 0, 1))


def test_a_surveyed_stand_can_LOWER_a_satellite_guess():
    """THE CORE FIX, and the one max() made impossible. Closed conifer: the stand map
    surveyed it and says nothing to eat; land cover says "green". Under max() the answer
    was 0.30 and the survey counted for nothing."""
    old = max(0.0, 0.30)                     # what np.maximum did
    new = _combine({"stand": 0.0, "landcover": 0.30})
    assert old == pytest.approx(0.30)
    assert new < 0.15, f"the stand map still cannot correct the satellite (got {new})"


def test_a_dated_cut_outranks_both_stand_and_land_cover():
    """A fresh 2-year cut is poor browse — regen is below moose height. Land cover sees
    shrub and calls it prime. The dated polygon is the better evidence and must win."""
    new = _combine({"cut": 0.10, "stand": 0.55, "landcover": 1.0})
    assert new < 0.5, f"a 2-yr cut is not prime browse (got {new})"
    assert max(0.10, 0.55, 1.0) == 1.0        # what it used to score


def test_agreement_and_disagreement_are_distinguishable():
    """max() gave the same answer for 'one source says prime' and 'all four say prime'.
    They are different evidence and must produce different numbers."""
    unanimous = _combine({"cut": 0.9, "stand": 0.9, "landcover": 0.9})
    lonely = _combine({"cut": 0.9, "stand": 0.1, "landcover": 0.1})
    assert unanimous > lonely, "corroboration must count for something"
    assert max(0.9, 0.9, 0.9) == max(0.9, 0.1, 0.1)   # under max() they were identical


def test_authority_still_dominates_its_corroborators():
    """Corroboration adjusts; it does not vote the authoritative source down. A prime
    dated cut surrounded by disagreement is still good ground."""
    v = _combine({"cut": 1.0, "stand": 0.0, "landcover": 0.0})
    assert v >= 0.7, f"the dated cut lost control of its own cell (got {v})"


def test_a_lone_source_is_returned_unchanged():
    """North of the écoforestière limit there IS only land cover. It must pass through,
    not be dragged toward a support value that does not exist."""
    assert _combine({"landcover": 0.62}) == pytest.approx(0.62)
