"""Sharing a plan, and co-editing it without flattening each other (T9.6).

Decisions taken by the owner of this product, recorded because the code below only makes
sense against them: sharing grants CO-EDIT, and an invite to an address with no account
is accepted and waits — "they get access once they sign up".

The waiting is why shares are keyed by EMAIL rather than by user id. A hunting party is
exactly the case where the other person has not signed up yet, so the share simply sits
in the table until someone signs in with that address and the join starts matching. No
pending-invite table, no reconciliation job, nothing to go stale.

Also pinned here: a pre-existing authorization hole found while adding this. PUT /plans
used `ON CONFLICT(id) DO UPDATE` with no owner check, so any signed-in account could
overwrite any plan whose id it knew. Plan ids are client-side uuids, so it was
impractical rather than open — but it was never an authorization decision, and sharing
makes it one.
"""
import json
import time

import pytest

api = pytest.importorskip("moose_scout.api")


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DB_PATH", str(tmp_path / "t.db"))
    yield


def _user(email, pw="x"):
    con = api._db()
    con.execute("INSERT INTO users(email, pw, created) VALUES(?,?,?)",
                (email, api._hash_pw(pw), time.time()))
    uid = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    tok = "tok-" + email
    con.execute("INSERT INTO sessions(token, uid, created) VALUES(?,?,?)",
                (tok, uid, time.time()))
    con.commit(); con.close()
    return uid, "Bearer " + tok


def _plan(pid, uid, name="P", data=None):
    con = api._db()
    con.execute("INSERT INTO plans(id, uid, name, data, updated, version) VALUES(?,?,?,?,?,?)",
                (pid, uid, name, json.dumps(data or {}), time.time(), 1))
    con.commit(); con.close()


# ------------------------------------------------------------------- who sees what


def test_a_plan_you_own_is_yours_and_says_so():
    uid, auth = _user("a@x.com")
    _plan("p1", uid)
    out = api.get_plans(authorization=auth)
    assert [p["id"] for p in out["plans"]] == ["p1"]
    assert out["plans"][0]["role"] == "owner"
    assert out["plans"][0]["owner_email"] is None


def test_a_shared_plan_appears_for_the_invitee_and_is_marked_shared():
    """A hunter editing someone else's plan without knowing it is the same class of
    surprise as a plan silently overwritten."""
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner)
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    out = api.get_plans(authorization=mauth)
    assert [p["id"] for p in out["plans"]] == ["p1"]
    assert out["plans"][0]["role"] == "edit"
    assert out["plans"][0]["owner_email"] == "owner@x.com"


def test_an_invite_to_an_unregistered_address_waits_and_then_works():
    """THE DECISION THIS DESIGN EXISTS FOR. The share is accepted before the account
    exists and starts working the moment it does — no reconciliation step."""
    owner, oauth = _user("owner@x.com")
    _plan("p1", owner)
    res = api.add_share("p1", api.ShareIn(email="later@x.com"), authorization=oauth)
    assert res["ok"] is True and res["registered"] is False
    # ...they sign up afterwards...
    _, lauth = _user("later@x.com")
    out = api.get_plans(authorization=lauth)
    assert [p["id"] for p in out["plans"]] == ["p1"], "the waiting invite never resolved"


def test_a_stranger_sees_nothing():
    owner, _ = _user("owner@x.com")
    _, sauth = _user("nobody@x.com")
    _plan("p1", owner)
    assert api.get_plans(authorization=sauth)["plans"] == []


def test_the_share_list_says_who_has_signed_up():
    """An invite to an address with no account is fine, but it must not LOOK broken."""
    owner, oauth = _user("owner@x.com")
    _user("mate@x.com")
    _plan("p1", owner)
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    api.add_share("p1", api.ShareIn(email="later@x.com"), authorization=oauth)
    got = {s["email"]: s["registered"] for s in api.get_shares("p1", authorization=oauth)["shares"]}
    assert got == {"mate@x.com": True, "later@x.com": False}


# ------------------------------------------------------------------ authorization


def test_a_stranger_cannot_overwrite_a_plan_by_guessing_its_id():
    """THE HOLE THIS CLOSES. `ON CONFLICT(id) DO UPDATE` never checked the owner."""
    owner, _ = _user("owner@x.com")
    _, sauth = _user("stranger@x.com")
    _plan("p1", owner, name="mine", data={"keep": 1})
    with pytest.raises(api.HTTPException) as e:
        api.put_plan(api.PlanIn(id="p1", name="stolen", data={"keep": 0}),
                     authorization=sauth)
    assert e.value.status_code == 403
    con = api._db()
    row = con.execute("SELECT name, data FROM plans WHERE id=?", ("p1",)).fetchone()
    con.close()
    assert row[0] == "mine" and json.loads(row[1]) == {"keep": 1}


def test_a_co_editor_may_write():
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner, data={"v": 1})
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    api.put_plan(api.PlanIn(id="p1", name="P", data={"v": 2}), authorization=mauth)
    con = api._db()
    row = con.execute("SELECT data FROM plans WHERE id=?", ("p1",)).fetchone()
    con.close()
    assert json.loads(row[0]) == {"v": 2}


def test_only_the_owner_can_share_it_on():
    """A co-editor re-sharing someone else's plan is a decision belonging to the person
    whose work it is."""
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner)
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    with pytest.raises(api.HTTPException) as e:
        api.add_share("p1", api.ShareIn(email="third@x.com"), authorization=mauth)
    assert e.value.status_code == 403


def test_delete_is_owner_only_even_though_editing_is_shared():
    """Co-editing a plan and being able to destroy it are different powers. Losing
    someone else's season of work is not a recoverable mistake."""
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner)
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    api.del_plan("p1", authorization=mauth)          # must be a no-op, not an error
    assert [p["id"] for p in api.get_plans(authorization=oauth)["plans"]] == ["p1"]
    api.del_plan("p1", authorization=oauth)
    assert api.get_plans(authorization=oauth)["plans"] == []


def test_anyone_may_remove_themselves_from_a_plan():
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner)
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    api.del_share("p1", email="mate@x.com", authorization=mauth)
    assert api.get_plans(authorization=mauth)["plans"] == []


# --------------------------------------------------------------- co-edit collisions


def test_a_stale_save_is_refused_instead_of_flattening_the_other_person():
    """Two editors on one blob is last-write-wins unless something notices. This is not
    a CRDT — it is an honest collision report, which is what a two-person hunting party
    actually needs."""
    owner, oauth = _user("owner@x.com")
    _, mauth = _user("mate@x.com")
    _plan("p1", owner, data={"v": 1})
    api.add_share("p1", api.ShareIn(email="mate@x.com"), authorization=oauth)
    # Both loaded at version 1. The mate saves first.
    r = api.put_plan(api.PlanIn(id="p1", data={"v": "mate"}, base_version=1),
                     authorization=mauth)
    assert r["version"] == 2
    # The owner, still holding version 1, must be told rather than silently winning.
    with pytest.raises(api.HTTPException) as e:
        api.put_plan(api.PlanIn(id="p1", data={"v": "owner"}, base_version=1),
                     authorization=oauth)
    assert e.value.status_code == 409
    con = api._db()
    row = con.execute("SELECT data FROM plans WHERE id=?", ("p1",)).fetchone()
    con.close()
    assert json.loads(row[0]) == {"v": "mate"}, "the stale save won anyway"


def test_a_client_that_does_not_track_versions_still_works():
    """Older clients send no base_version. They must keep saving rather than 409-ing on
    every write."""
    owner, oauth = _user("owner@x.com")
    _plan("p1", owner, data={"v": 1})
    api.put_plan(api.PlanIn(id="p1", data={"v": 2}), authorization=oauth)
    api.put_plan(api.PlanIn(id="p1", data={"v": 3}), authorization=oauth)
    con = api._db()
    row = con.execute("SELECT data, version FROM plans WHERE id=?", ("p1",)).fetchone()
    con.close()
    assert json.loads(row[0]) == {"v": 3} and row[1] == 3


def test_a_bad_email_is_refused():
    owner, oauth = _user("owner@x.com")
    _plan("p1", owner)
    for bad in ("", "nope", "a@b"):
        with pytest.raises(api.HTTPException):
            api.add_share("p1", api.ShareIn(email=bad), authorization=oauth)
