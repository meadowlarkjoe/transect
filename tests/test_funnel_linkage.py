"""A funnel connects two places. A peninsula connects one place to nothing.

Reported from the map: "peninsulas are being identified as funnels. These are probably
the opposite of funnels. they are dead ends."

He is right, and it was not a near-miss. The constriction detector asks exactly one
question — "is this ground narrow, pinched between barriers?" — and that question is
purely LOCAL. A peninsula neck answers yes. So does a spit, an island's tie-bar, and the
closed end of a bay. Measured across every cached AOI before the fix: on his box 25 of
25 candidates were dead ends, and on ground that is ~95% continuous the rate is much the
same everywhere. The layer was mostly wrong, and wrong in the specific way that sends
someone to sit on ground no travelling bull has a reason to cross.

The test is the standard one from connectivity ecology — Circuitscape's "pinch points",
where losing a little ground SEVERS A LINKAGE. Cut the neck; look at what it separated.

Two things that look right and are not, both caught by measurement rather than by
reading the code, and both pinned below because both would silently return:

  1. CUT ACROSS THE NECK, NOT ALONG IT. The medial axis runs ALONG the corridor centre,
     so deleting those cells leaves the flanks connected around the gap and severs
     nothing at all.
  2. THE SIDES ARE THE PIECES THE NECK TOUCHES, not the two biggest pieces nearby.
     Taking the largest components in the window paired a peninsula stub with an
     unrelated region across a lake. Symptom: widening the search halo 6 km -> 25 km
     moved survivors from 9 to 25 on one box and 47 to 66 on another — the verdict was
     decided by how far we happened to look, which is not a property of the ground.
"""
import numpy as np
import pytest

pytest.importorskip("scipy")

from moose_scout import terrain

RES = 40.0
N = 400                      # a 16 km box at 40 m


def _cores(barrier, res=RES):
    """The pre-linkage neck cores, exactly as _constriction builds them."""
    from scipy.ndimage import distance_transform_edt, maximum_filter, uniform_filter

    passable = ~barrier
    db = (distance_transform_edt(passable) * res).astype("float32")
    ridge = (db >= maximum_filter(db, size=3) - 1e-6) & passable & (db > max(res, 20.0))
    full_w = 2.0 * db
    narrow = np.clip((600.0 - full_w) / 350.0, 0.0, 1.0)
    db_local = uniform_filter(db, size=max(3, int(round(600 / res)) | 1))
    pinch = np.clip((db_local - db) / (db_local + 1e-6), 0.0, 1.0)
    core = np.where(ridge & (full_w < 600.0), narrow * (0.35 + 0.65 * pinch), 0.0)
    return core.astype("float32"), passable, db


def _isthmus(gap_cells=8):
    """Two big land masses joined ONLY by a land bridge. The real thing."""
    b = np.zeros((N, N), bool)
    b[150:175, :] = True                                        # water across the box...
    c = N // 2
    b[150:175, c - gap_cells // 2: c + gap_cells // 2] = False   # ...except the bridge
    return b


def _peninsula(gap_cells=8):
    """A spit poking into open water: narrow at its base, and it leads nowhere."""
    b = np.zeros((N, N), bool)
    b[150:, :] = True                                           # one big lake
    c = N // 2
    b[150:260, c - gap_cells // 2: c + gap_cells // 2] = False   # the spit
    return b


def _survivors(barrier, res=RES):
    from scipy import ndimage as ndi

    core, passable, db = _cores(barrier, res)
    link = terrain._linkage(core, passable, res, db)
    _lab, n = ndi.label((core * link) > 0)
    return n, core, link


# --------------------------------------------------------------- the reported bug


def test_a_peninsula_is_not_a_funnel():
    """THE REPORTED BUG. The detector must still FIND the neck — it is genuinely narrow —
    and must then refuse to call it a funnel."""
    core, _p, _d = _cores(_peninsula())
    assert (core > 0).any(), "the fixture is wrong: no neck was detected at all"
    n, _core, _link = _survivors(_peninsula())
    assert n == 0, "a peninsula neck was reported as a funnel"


def test_a_real_land_bridge_still_is_one():
    """The other half. A test that only ever says no would 'fix' this by deleting the
    feature."""
    n, core, link = _survivors(_isthmus())
    assert n >= 1, "a genuine isthmus between two land masses was rejected"
    assert float(link.max()) == pytest.approx(1.0), \
        "a bridge joining two full-box land masses should be a maximal linkage"


def test_ground_you_can_walk_around_is_not_a_funnel():
    """Open ground with two ponds in it. Narrow between them, but nothing is forced:
    remove the gap and the landscape is still one connected piece."""
    b = np.zeros((N, N), bool)
    yy, xx = np.mgrid[0:N, 0:N]
    b |= ((yy - 200) ** 2 + (xx - 170) ** 2) < 40 ** 2
    b |= ((yy - 200) ** 2 + (xx - 240) ** 2) < 40 ** 2
    n, _c, _l = _survivors(b)
    assert n == 0, "a gap between two ponds in open ground was called a funnel"


# ------------------------------------------------- the two near-misses, pinned


def test_the_cut_goes_ACROSS_the_neck_not_along_it():
    """The medial axis runs along the corridor. Cutting only those cells leaves the
    flanks joined around the gap, so nothing is ever severed and every neck fails.
    The cut radius has to come from `db`, which IS the local half-width."""
    import inspect

    src = inspect.getsource(terrain._linkage)
    assert "db[blob_full].max()" in src, "the cut radius no longer follows the corridor width"


def test_the_verdict_does_not_depend_on_how_far_we_look():
    """A property of the ground cannot change because the search window changed. This
    failed badly before the adjacency fix: 9 -> 25 survivors between a 6 km and a 25 km
    halo on one real box."""
    got = []
    for halo in (6000.0, 25000.0):
        prev = terrain.LINK_HALO_M
        terrain.LINK_HALO_M = halo
        try:
            got.append(_survivors(_isthmus())[0])
        finally:
            terrain.LINK_HALO_M = prev
    assert got[0] == got[1], f"the halo decided the answer: {got}"


def test_the_sides_must_be_the_pieces_the_neck_touches():
    """A peninsula next to a big unrelated land mass across water. If the test takes the
    two biggest pieces NEARBY rather than the two the neck actually joins, the stub gets
    paired with that unrelated mass and passes."""
    b = _peninsula()
    b[300:, :] = False              # a large unrelated land mass beyond the lake
    b[290:300, :] = True            # ...separated from everything by water
    n, _c, _l = _survivors(b)
    assert n == 0, "the stub was paired with an unrelated region across the water"


# ------------------------------------------------------------------- reporting


def test_an_empty_funnel_layer_records_why():
    """'No funnels' with no explanation reads as a broken model. The audit is what lets
    the contract say 'nothing here is forced anywhere' instead of showing a blank."""
    terrain._constriction(_peninsula(), RES, grid_res=RES)
    audit = getattr(terrain._constriction, "last_audit", None)
    assert audit and audit["candidates"] > 0 and audit["kept"] == 0
    assert 0.0 < audit["passable_frac"] < 1.0
