"""The router must know about every line the map draws (T10.15).

Reported twice in one session, with screenshots: "It goes along one road and then
bushwacks to the location. But you could have just followed the road" and "Access line
follows road. Hunt line bushwacks for some reason." The second screenshot shows a dashed
trail running to the waypoint and the red route ignoring it to cut its own line through
the bush alongside.

THE CAUSE. `synth._linear_cost_layer` — which supplies the cheap-walking tier — read
`aq_trails.gpkg` and `aq_rail.gpkg` only, while `export.py` also DRAWS `trails.gpkg`.
The app was drawing a path to a place the router did not know how to walk to. Measured
across the cached runs, the share of the drawn network the router could not see:

    job_1a0c9d5b6618   46%   (30.3 km of trail)
    job_0e92b5ca580d   97%   (no AQréseau sentiers on that box at all)
    job_8892f779ddc9   92%
    job_20e209ca08d0    2%

THE PART THAT IS NOT SYMMETRIC, and getting it wrong would have swapped one wrong answer
for another. `aq_trails` is the official MOTORISED sentier network — quad and snowmobile.
`trails.gpkg` is OSM, and on these boxes it is entirely `path` (29) and `footway` (8):
foot trails. Both beat bushwhacking on foot. Only the first is something you ride. So
the walkable set grew and the ridable set did not.

HONEST NOTE ON THE OUTCOME. This changed no route on any cached box. The newly-visible
paths sit 4.4-12 km from every remaining bushwhack, and T10.20 had already put the legs
that prompted the report onto the motorised network. It is a consistency fix — the
router now knows about the same lines the map draws — not a measured improvement, and
the tests below pin the consistency rather than any route.
"""
import inspect
import re

from moose_scout import export, synth


def _drawn_by_class():
    """{class: {filename}} — what export.py actually puts on the map."""
    src = inspect.getsource(export)
    block = src[src.index("specs = ["):]
    block = block[:block.index("]") + 1]
    out = {}
    for fname, cls in re.findall(r'\("([^"]+\.gpkg)",\s*"([^"]+)"\)', block):
        out.setdefault(cls, set()).add(fname)
    assert out, "could not read export.py's drawn-layer list"
    return out


def _walkable_names():
    """The files `_linear_cost_layer` reads for the cheap-WALKING tier."""
    src = inspect.getsource(synth._linear_cost_layer)
    names = set(re.findall(r'"([^"]+\.gpkg)"', src))
    assert names, "could not read the walkable line list"
    return names


def _ridable_names():
    """...and the subset it reads when asked for MOTORISED only."""
    src = inspect.getsource(synth._linear_cost_layer)
    head = src[:src.index("if not motorised_only")]
    return set(re.findall(r'"([^"]+\.gpkg)"', head))


# ------------------------------------------------------------------ the reported bug


def test_every_trail_the_map_draws_is_walkable_by_the_router():
    """THE ONE THIS EXISTS FOR. Drawing a line the router refuses to use is how you get
    a route bushwhacking beside a perfectly good trail."""
    drawn = _drawn_by_class()
    walkable = _walkable_names()
    missing = (drawn.get("trail", set()) | drawn.get("rail", set())) - walkable
    assert not missing, (
        f"the map draws {sorted(missing)} but the walk-cost surface cannot see them — "
        f"routes will bushwhack alongside them")


def test_roads_reach_the_router_through_their_own_raster():
    """Roads are not in `_linear_cost_layer`; they arrive as roads.tif and get their own
    much cheaper tier. This checks they are not silently absent from BOTH."""
    src = inspect.getsource(synth._walk_cost)
    assert 'roads.tif' in src, "the walk cost no longer prices roads at all"


# ---------------------------------------------------- the asymmetry that must survive


def test_a_footpath_is_walkable_but_not_ridable():
    """OSM `path` and `footway` are foot trails. Putting them in the ATV network would
    send a quad down a hiking trail — a different wrong answer, not a fix."""
    walkable, ridable = _walkable_names(), _ridable_names()
    assert "trails.gpkg" in walkable
    assert "trails.gpkg" not in ridable, "OSM footpaths leaked into the ridable network"


def test_the_official_motorised_sentiers_are_ridable():
    ridable = _ridable_names()
    assert "aq_trails.gpkg" in ridable, "the official quad/snowmobile network is not ridable"


def test_the_ridable_set_is_a_subset_of_the_walkable_set():
    """Anything you can ride, you can also walk. The reverse is the whole point."""
    assert _ridable_names() <= _walkable_names()


def test_the_atv_network_asks_for_motorised_only():
    """The flag exists; this checks the ATV network actually passes it. Defaulting here
    is exactly how footpaths would become ridable without anyone noticing."""
    src = inspect.getsource(synth._mode_networks)
    assert "motorised_only=True" in src, \
        "the ATV network is taking the default (walkable) line set"


def test_the_walk_cost_takes_the_full_walkable_set():
    """...and conversely, the walking tier must NOT be restricted to motorised lines."""
    src = inspect.getsource(synth._walk_cost)
    call = [l for l in src.split("\n") if "_linear_cost_layer(" in l]
    assert call, "the walk cost no longer consults the linear-feature layer"
    assert "motorised_only" not in call[0], \
        "the walking tier is restricted to motorised lines — foot trails are invisible again"
