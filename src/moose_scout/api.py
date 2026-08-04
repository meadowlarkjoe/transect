"""HTTP API wrapping the scouting pipeline for the Transect app.

A real run pulls DEM/land-cover/imagery/roads and computes the model — minutes,
not seconds — so this is a job/poll API:

  POST /scout  {species, lat, lon, radius_km, ...}  -> {job_id}
  GET  /jobs/{id}                                    -> {status, stage, progress, scout?}
  GET  /health

`scout` in a finished job is the exact `window.SCOUT_DATA` object the app binds to
(areas/points/routes/grid/elev/wind/solar/infra), computed for the requested
species + location. CORS-open so the static Transect app can call it.
"""
from __future__ import annotations

import json
import shutil
import threading
import traceback
import uuid

import os

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Optional shared-key guard: if TRANSECT_API_KEY is set, /scout requires it. Keeps a
# public deployment from being abused into running expensive analyses for strangers.
API_KEY = os.environ.get("TRANSECT_API_KEY")


# Require a signed-in account (not just the shared key) to start an analysis.
# Off only if you deliberately set TRANSECT_OPEN=1 for a private/local deployment.
REQUIRE_ACCOUNT = os.environ.get("TRANSECT_OPEN", "") != "1"


def _require_key(x_api_key):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="invalid or missing API key")

from . import pipeline
from .config import (AOI, Context, HunterCfg, LatLon, SeasonCfg, cache_dir,
                     load_model, load_species, outputs_dir)

app = FastAPI(title="Transect Scout API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

JOBS: dict[str, dict] = {}
STAGES = ["acquire", "terrain", "habitat", "behavior", "access", "synth", "contract"]
SPECIES = {"moose", "whitetail_deer", "black_bear"}

# ---- accounts + cross-device saved plans (stdlib sqlite; no extra deps) ----
import hashlib
import hmac
import secrets
import sqlite3
import time
from pathlib import Path

DB_PATH = os.environ.get("TRANSECT_DB", "/app/data/transect.db")


def _db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, pw TEXT, created REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, uid INTEGER, created REAL)")
    con.execute("CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, uid INTEGER, name TEXT, data TEXT, updated REAL)")
    return con


def _hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def _verify_pw(pw, stored):
    try:
        salt, h = stored.split("$", 1)
        return hmac.compare_digest(hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex(), h)
    except Exception:
        return False


def _uid(authorization):
    if not authorization:
        return None
    tok = authorization.replace("Bearer ", "").strip()
    con = _db()
    r = con.execute("SELECT uid FROM sessions WHERE token=?", (tok,)).fetchone()
    con.close()
    return r[0] if r else None


class Auth(BaseModel):
    email: str
    password: str


class PlanIn(BaseModel):
    id: str
    name: str = ""
    data: dict = {}


class ScoutReq(BaseModel):
    species: str = "moose"
    lat: float
    lon: float
    radius_km: float = 35.0
    target_dates: list[str] | None = None
    residency: str = "quebec_resident"
    zone_hint: str | None = None
    # Setup constraints that shape the analysis (not just the display)
    watercraft: str = "none"          # none | canoe | motor
    hunt_style: str = "spike"         # spike | vehicle
    walk_access_km: float = 6.0
    walk_hunt_km: float = 3.0
    party_size: int = 2
    fixed_camp: list[float] | None = None   # [lat, lon] — hunt-from-camp mode
    hunt_radius_km: float | None = None


def _run(job_id: str, req: ScoutReq) -> None:
    name = f"job_{job_id}"
    try:
        species = req.species if req.species in SPECIES else "moose"
        aoi = AOI(
            name=name, title=f"{req.lat:.3f}, {req.lon:.3f}", species=species,
            center=LatLon(lat=req.lat, lon=req.lon),
            bbox_halfwidth_km=max(3.0, min(120.0, req.radius_km)),
            zone_hint=req.zone_hint,
            season=SeasonCfg(year=2026,
                             target_dates=req.target_dates or ["2026-09-25", "2026-10-05"]),
            hunter=HunterCfg(
                residency=req.residency,
                watercraft=req.watercraft if req.watercraft in ("none", "canoe", "motor") else "none",
                hunt_style=req.hunt_style if req.hunt_style in ("spike", "vehicle") else "spike",
                walk_access_km=max(0.5, min(30.0, float(req.walk_access_km))),
                walk_hunt_km=max(0.3, min(20.0, float(req.walk_hunt_km))),
                party_size=max(1, min(12, int(req.party_size))),
                fixed_camp=(tuple(req.fixed_camp[:2]) if req.fixed_camp
                            and len(req.fixed_camp) >= 2 else None),
                hunt_radius_km=(max(1.0, min(30.0, float(req.hunt_radius_km)))
                                if req.hunt_radius_km else None),
            ),
        )
        # Scale analysis resolution with AOI size so a big area doesn't blow past RAM.
        # The grid is (2*halfwidth*1000 / res) px per side, and memory grows with px² —
        # a 120 km-radius run at 40 m is 6000²=36M px/raster and OOMs. Cap the grid to
        # ~TARGET_PX per side (never finer than the configured resolution).
        import math
        model = load_model()
        TARGET_PX = 2400
        res = max(float(model.raster_resolution_m),
                  math.ceil(2 * aoi.bbox_halfwidth_km * 1000 / TARGET_PX))
        if res != model.raster_resolution_m:
            try:
                model = model.model_copy(update={"raster_resolution_m": res})
            except Exception:
                model.raster_resolution_m = res
            JOBS[job_id]["res_m"] = res
        ctx = Context(aoi=aoi, species=load_species(species), model=model)
        for i, stage in enumerate(STAGES):
            # Checked between stages rather than inside them: a stage is the smallest
            # unit we can abandon without leaving half-written rasters behind.
            if JOBS.get(job_id, {}).get("cancel"):
                JOBS[job_id].update(status="cancelled", stage="cancelled")
                return
            JOBS[job_id].update(stage=stage, progress=round(i / len(STAGES), 2))
            pipeline.run_stage(stage, ctx)
        # return the app's data contract (transect.json), same shape the app binds to
        doc = json.loads((outputs_dir(name) / "transect.json").read_text())
        JOBS[job_id].update(status="done", stage="done", progress=1.0, scout=doc)
        # Persist enough to rebuild this ctx later, and KEEP the cache so /rescope can
        # re-plan (manual areas, moved camp) against the already-acquired rasters
        # without a full minutes-long re-fetch. Pruned below to bound disk.
        try:
            (cache_dir(name) / "job_meta.json").write_text(json.dumps({
                "req": req.model_dump(), "uid": JOBS[job_id].get("uid"),
                "res_m": JOBS[job_id].get("res_m"), "at": time.time()}))
            _prune_caches()
        except Exception:
            pass
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(status="error", error=str(e),
                            trace=traceback.format_exc()[-1200:])
        shutil.rmtree(cache_dir(name), ignore_errors=True)   # a failed run keeps nothing
        shutil.rmtree(outputs_dir(name), ignore_errors=True)


@app.post("/scout")
def scout(req: ScoutReq, x_api_key: str = Header(default=None),
          authorization: str = Header(default=None)):
    # A run costs minutes of CPU on a small box, and the shared API key ships inside
    # the front end's config.js — i.e. it is public to anyone who views source. So the
    # key alone is not access control; require a real signed-in account as well.
    _require_key(x_api_key)
    uid = _uid(authorization)
    if REQUIRE_ACCOUNT and not uid:
        raise HTTPException(status_code=401, detail="sign in to run an analysis")
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"status": "running", "stage": "queued", "progress": 0.0, "uid": uid,
                 "started": time.time(), "seen": time.time()}
    threading.Thread(target=_run, args=(jid, req), daemon=True).start()
    return {"job_id": jid}


@app.get("/jobs/{jid}")
def job(jid: str, authorization: str = Header(default=None)):
    j = JOBS.get(jid)
    if not j:
        return {"status": "unknown"}
    # Every poll is a heartbeat. The front end polls a running job every 2.5 s, so
    # "nobody has asked in ORPHAN_S" means the tab is gone — closed, crashed or
    # navigated away — and the run is being computed for nobody. Using the existing
    # poll avoids a second mechanism, and it survives a reload: the new page
    # reconnects and resumes the heartbeat well inside the window.
    j["seen"] = time.time()
    # Don't hand one account's analysis to another; jobs are readable by their owner.
    if REQUIRE_ACCOUNT and j.get("uid") is not None:
        if _uid(authorization) != j.get("uid"):
            raise HTTPException(status_code=403, detail="not your job")
    return j


@app.delete("/jobs/{jid}")
def cancel_job(jid: str, authorization: str = Header(default=None)):
    """Explicit abandon — sent by the page as it unloads, and usable from the UI."""
    j = JOBS.get(jid)
    if not j:
        return {"status": "unknown"}
    if REQUIRE_ACCOUNT and j.get("uid") is not None:
        if _uid(authorization) != j.get("uid"):
            raise HTTPException(status_code=403, detail="not your job")
    j["cancel"] = True
    return {"status": "cancelling"}


ORPHAN_S = 90.0          # ~36 missed polls at the client's 2.5 s cadence


def _reap_orphans():
    """Cancel runs nobody is watching. A scout run pegs a core for minutes; one left
    behind by a closed tab is pure waste on a 2-vCPU box, and several of them are an
    outage. Started as a daemon so it dies with the process."""
    while True:
        time.sleep(30)
        now = time.time()
        for jid, j in list(JOBS.items()):
            if j.get("status") != "running" or j.get("cancel"):
                continue
            seen = j.get("seen") or j.get("started") or now
            if now - seen > ORPHAN_S:
                j["cancel"] = True
                j["orphaned"] = True


threading.Thread(target=_reap_orphans, daemon=True).start()


RESCOPE_KEEP = 25          # most-recent job caches retained for re-planning


def _prune_caches():
    """Keep the RESCOPE_KEEP newest job_* caches; delete the rest. Disk on the box is
    ample (a cache is ~40-160 MB, tens of GB free), so this is generous — it just
    stops unbounded growth."""
    import os
    root = Path(os.environ.get("MOOSE_SCOUT_CACHE", "cache"))
    try:
        jobs = sorted((p for p in root.glob("job_*") if p.is_dir()),
                      key=lambda p: p.stat().st_mtime, reverse=True)
        for old in jobs[RESCOPE_KEEP:]:
            shutil.rmtree(old, ignore_errors=True)
            shutil.rmtree(outputs_dir(old.name), ignore_errors=True)
    except Exception:
        pass


class RescopeReq(BaseModel):
    job_id: str
    manual_areas: list | None = None     # [[[lon,lat],...], ...] hand-drawn polygons
    fixed_camp: list[float] | None = None
    hunt_radius_km: float | None = None


@app.post("/rescope")
def rescope(rq: RescopeReq, x_api_key: str = Header(default=None),
            authorization: str = Header(default=None)):
    """Re-plan against an already-acquired AOI: reuse the cached rasters, apply the
    hunter's manual areas / moved camp, and re-run ONLY synth + contract. Seconds,
    not minutes — no re-fetch. This is the on-demand 'Recalculate' path."""
    _require_key(x_api_key)
    uid = _uid(authorization)
    name = f"job_{rq.job_id}"
    meta_p = cache_dir(name) / "job_meta.json"
    if not meta_p.exists():
        raise HTTPException(404, "that analysis is no longer cached — run a fresh one")
    meta = json.loads(meta_p.read_text())
    if REQUIRE_ACCOUNT and meta.get("uid") is not None and uid != meta.get("uid"):
        raise HTTPException(403, "not your analysis")
    r = ScoutReq(**meta["req"])
    # apply overrides from the rescope request (moved/added camp, new radius)
    if rq.fixed_camp is not None:
        r.fixed_camp = rq.fixed_camp
    if rq.hunt_radius_km is not None:
        r.hunt_radius_km = rq.hunt_radius_km
    try:
        species = r.species if r.species in SPECIES else "moose"
        model = load_model()
        if meta.get("res_m"):
            try:
                model = model.model_copy(update={"raster_resolution_m": meta["res_m"]})
            except Exception:
                model.raster_resolution_m = meta["res_m"]
        aoi = AOI(name=name, title=name, species=species,
                  center=LatLon(lat=r.lat, lon=r.lon),
                  bbox_halfwidth_km=max(3.0, min(120.0, r.radius_km)),
                  zone_hint=r.zone_hint,
                  season=SeasonCfg(year=2026, target_dates=r.target_dates or ["2026-09-25", "2026-10-05"]),
                  hunter=HunterCfg(
                      residency=r.residency,
                      watercraft=r.watercraft if r.watercraft in ("none", "canoe", "motor") else "none",
                      hunt_style=r.hunt_style if r.hunt_style in ("spike", "vehicle") else "spike",
                      walk_access_km=max(0.5, min(30.0, float(r.walk_access_km))),
                      walk_hunt_km=max(0.3, min(20.0, float(r.walk_hunt_km))),
                      party_size=max(1, min(12, int(r.party_size))),
                      fixed_camp=(tuple(r.fixed_camp[:2]) if r.fixed_camp and len(r.fixed_camp) >= 2 else None),
                      hunt_radius_km=(max(1.0, min(30.0, float(r.hunt_radius_km))) if r.hunt_radius_km else None)))
        ctx = Context(aoi=aoi, species=load_species(species), model=model)
        from . import synth as _synth, contract as _contract
        _synth.run(ctx, manual_areas=rq.manual_areas or None)
        _contract.build(ctx)
        doc = json.loads((outputs_dir(name) / "transect.json").read_text())
        # touch the cache so a rescoped plan isn't pruned out from under the user
        try:
            meta["at"] = time.time(); meta_p.write_text(json.dumps(meta))
        except Exception:
            pass
        return {"status": "done", "scout": doc}
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"rescope failed: {e}")


@app.get("/health")
def health():
    from .version import ENGINE_REVISION, REVISIONS
    return {"ok": True, "species": sorted(SPECIES),
            "engine_revision": ENGINE_REVISION,
            "revision_notes": REVISIONS.get(ENGINE_REVISION, "")}


# ---- auth ----
def _new_session(uid):
    tok = secrets.token_hex(24)
    con = _db()
    con.execute("INSERT INTO sessions(token, uid, created) VALUES(?,?,?)", (tok, uid, time.time()))
    con.commit()
    con.close()
    return tok


@app.post("/auth/signup")
def signup(a: Auth):
    email = a.email.strip().lower()
    if "@" not in email or len(a.password) < 6:
        raise HTTPException(400, "enter a valid email and a password of 6+ characters")
    con = _db()
    try:
        con.execute("INSERT INTO users(email, pw, created) VALUES(?,?,?)",
                    (email, _hash_pw(a.password), time.time()))
        con.commit()
    except sqlite3.IntegrityError:
        con.close()
        raise HTTPException(409, "that email is already registered — sign in instead")
    uid = con.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
    con.close()
    return {"token": _new_session(uid), "email": email}


@app.post("/auth/login")
def login(a: Auth):
    email = a.email.strip().lower()
    con = _db()
    r = con.execute("SELECT id, pw FROM users WHERE email=?", (email,)).fetchone()
    con.close()
    if not r or not _verify_pw(a.password, r[1]):
        raise HTTPException(401, "wrong email or password")
    return {"token": _new_session(r[0]), "email": email}


@app.post("/auth/logout")
def logout(authorization: str = Header(default=None)):
    if authorization:
        tok = authorization.replace("Bearer ", "").strip()
        con = _db(); con.execute("DELETE FROM sessions WHERE token=?", (tok,)); con.commit(); con.close()
    return {"ok": True}


@app.get("/auth/me")
def me(authorization: str = Header(default=None)):
    uid = _uid(authorization)
    if not uid:
        return {"signed_in": False}
    con = _db(); r = con.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone(); con.close()
    return {"signed_in": True, "email": r[0] if r else None}


# ---- cross-device saved plans ----
@app.get("/plans")
def get_plans(authorization: str = Header(default=None)):
    uid = _uid(authorization)
    if not uid:
        raise HTTPException(401, "sign in to sync plans")
    con = _db()
    rows = con.execute("SELECT id, name, data, updated FROM plans WHERE uid=? ORDER BY updated DESC", (uid,)).fetchall()
    con.close()
    return {"plans": [{"id": r[0], "name": r[1], "data": json.loads(r[2]), "updated": r[3]} for r in rows]}


@app.put("/plans")
def put_plan(p: PlanIn, authorization: str = Header(default=None)):
    uid = _uid(authorization)
    if not uid:
        raise HTTPException(401, "sign in to sync plans")
    con = _db()
    con.execute("INSERT INTO plans(id, uid, name, data, updated) VALUES(?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, data=excluded.data, updated=excluded.updated",
                (p.id, uid, p.name, json.dumps(p.data), time.time()))
    con.commit()
    con.close()
    return {"ok": True}


@app.delete("/plans/{pid}")
def del_plan(pid: str, authorization: str = Header(default=None)):
    uid = _uid(authorization)
    if not uid:
        raise HTTPException(401, "sign in to sync plans")
    con = _db(); con.execute("DELETE FROM plans WHERE id=? AND uid=?", (pid, uid)); con.commit(); con.close()
    return {"ok": True}
