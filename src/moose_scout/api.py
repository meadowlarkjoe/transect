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
            hunter=HunterCfg(residency=req.residency),
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
            JOBS[job_id].update(stage=stage, progress=round(i / len(STAGES), 2))
            pipeline.run_stage(stage, ctx)
        # return the app's data contract (transect.json), same shape the app binds to
        doc = json.loads((outputs_dir(name) / "transect.json").read_text())
        JOBS[job_id].update(status="done", stage="done", progress=1.0, scout=doc)
    except Exception as e:  # noqa: BLE001
        JOBS[job_id].update(status="error", error=str(e),
                            trace=traceback.format_exc()[-1200:])
    finally:
        shutil.rmtree(cache_dir(name), ignore_errors=True)
        shutil.rmtree(outputs_dir(name), ignore_errors=True)


@app.post("/scout")
def scout(req: ScoutReq, x_api_key: str = Header(default=None)):
    _require_key(x_api_key)
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"status": "running", "stage": "queued", "progress": 0.0}
    threading.Thread(target=_run, args=(jid, req), daemon=True).start()
    return {"job_id": jid}


@app.get("/jobs/{jid}")
def job(jid: str):
    return JOBS.get(jid, {"status": "unknown"})


@app.get("/health")
def health():
    return {"ok": True, "species": sorted(SPECIES)}


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
