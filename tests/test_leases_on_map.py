"""Leases are drawn — and until now you could not ask what one was (T9.8 follow-up).

Asked simply: "are these plotted on map?" They are, and checking turned up three gaps
that had shipped with them.

  1. THE COUNT LIED. The contract caps the points it ships at 400 so a lease-dense box
     does not carry thousands of dots, which is fine — but the legend read
     `points.length`, so it showed "400" and sounded like the whole story.
  2. NO HOVER CARD. The map drew them in THREE COLOURS the model genuinely distinguishes
     — an abri sommaire is a hunting camp, a villégiature is a summer cottage — and
     nothing anywhere said which was which. "Every drawn thing on this map is a claim,
     and a claim you can't name is worse than one you can't see" (IDENTIFY's own note).
  3. THE LEGEND DID NOT KEY ITS OWN COLOURS.

The pressure surface always used every lease in the box. The cap bounds the DRAWING, not
the model — which is exactly why saying so matters.
"""
import inspect
import pathlib
import re

APP = pathlib.Path("app/app.js")


def _code():
    return re.sub(r"//[^\n]*", "", APP.read_text())


def test_the_legend_counts_what_is_in_the_box_not_what_fits_on_the_map():
    src = _code()
    i = src.index("{k:'leases',")
    row = src[i:src.index("\n {k:'", i + 5)]
    assert "L.count" in row, "the legend is back to counting the capped points"
    assert "truncated" in row, "a truncated count does not say so"


def test_the_contract_publishes_both_numbers():
    from moose_scout import contract
    src = inspect.getsource(contract.build)
    assert '"shown"' in src and '"truncated"' in src
    assert "LEASE_POINT_CAP" in src, "the cap is a bare literal again"


def test_the_cap_bounds_the_drawing_and_not_the_model():
    """The pressure term reads the full lease set from the raster path; only the doc's
    point list is capped. If that ever stops being true the layer becomes a model input
    with a silent 400-item ceiling."""
    from moose_scout import access
    src = inspect.getsource(access)
    assert "400" not in src or "LEASE_POINT_CAP" not in src


def test_a_lease_can_be_named_by_hovering_it():
    src = APP.read_text()
    ident = src[src.index("const IDENTIFY = ["):]
    ident = ident[:ident.index("\n];")]
    assert "{lyr:'leases'," in ident, "leases are drawn and still cannot be identified"
    i = ident.index("{lyr:'leases',")
    seg = ident[i:i + 900]
    for kind in ("abri_sommaire", "pourvoirie_camp", "villegiature", "residence"):
        assert kind in seg, f"{kind} has no hover text"


def test_the_hover_card_says_pressure_not_permission():
    """The one thing a hunter could badly misread off this layer."""
    src = APP.read_text()
    i = src.index("{lyr:'leases',")
    seg = src[i:i + 900]
    assert "does not restrict where you may hunt" in seg.lower()


def test_the_legend_explains_the_three_colours_it_draws():
    src = _code()
    i = src.index("{k:'leases',")
    row = src[i:src.index("\n {k:'", i + 5)]
    assert "Rust" in row and "outfitter" in row and "cottage" in row


def test_the_map_still_distinguishes_the_kinds_it_claims_to():
    """The legend now promises three colours. The paint has to deliver them."""
    src = APP.read_text()
    i = src.index("id:'leases',type:'circle'")
    seg = src[i:i + 600]
    assert "'abri_sommaire'" in seg and "'pourvoirie_camp'" in seg
