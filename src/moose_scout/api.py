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
import sys
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
from .config import (AOI, Context, HunterCfg, LatLon, SeasonCfg, _walk, cache_dir,
                     load_model, load_species, outputs_dir)

app = FastAPI(title="Transect Scout API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

import signal
import subprocess

from . import jobstore

# In-memory job state is GONE (#17): it lived and died with this process, so a deploy or
# a crash took every running analysis with it and left nothing to reconnect to. State is
# now a file the worker keeps writing, and the run is its own process.
MAX_CONCURRENT = int(os.environ.get("TRANSECT_MAX_CONCURRENT", "2"))


def _spawn_worker(jid: str) -> None:
    """Start the analysis as an independent process.

    start_new_session detaches it from this process group, so a signal aimed at uvicorn
    (a deploy, a container stop) does NOT cascade into the running analysis — which is
    the whole reason this exists."""
    # THE WORKER'S OUTPUT GOES TO A FILE, NOT TO /dev/null.
    #
    # It was discarded, and that made a whole class of failure undiagnosable: a worker
    # killed by the OOM killer, or dying before its own try/except is reached, writes no
    # status and leaves no trace — the job simply sits at "running" for ever with nothing
    # anywhere to say why. I hit exactly that today and had nothing to read.
    #
    # The log lives beside the job's state so it is findable from the job id alone, and
    # is small: stage lines plus a traceback at worst.
    log = None
    try:
        log = open(jobstore.dir_for(jid) / "worker.log", "ab", buffering=0)
    except OSError:
        pass
    proc = subprocess.Popen(
        [sys.executable, "-m", "moose_scout.worker", jid],
        stdout=(log or subprocess.DEVNULL), stderr=subprocess.STDOUT,
        start_new_session=True)
    jobstore.update(jid, pid=proc.pid)
# Set by POST /admin/drain during a deploy: refuse NEW analyses so the in-flight ones
# can finish before the container is replaced. Process-local by design (#17).
DRAINING = False
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
    watercraft: str = "none"          # none | canoe | motor (derived from transport; kept for back-compat)
    hunt_style: str = "spike"         # spike | vehicle
    # Multi-select transportation from Setup: {"canoe": bool, "motor": bool, "atv": bool}.
    # ATV/SxS is the one that changes the spatial model (tracks/trails become drivable).
    transport: dict | None = None
    # Known-sites mode: up to 4 [lat, lon] centres the hunter already has in mind,
    # compared against each other. sites[0] is the AOI centre.
    sites: list[list[float]] | None = None
    # Nullable on purpose. A pydantic default only fills a MISSING key — an explicit
    # null is a validation error, and the client legitimately holds "not stated yet"
    # for these two. Rejecting the whole run over an unset walk distance, when we have
    # a perfectly good default for it, is the engine being pedantic at the hunter's
    # expense. Coalesced below with `is None`, never `or`: a stated 0 is a real answer.
    walk_access_km: float | None = None
    walk_hunt_km: float | None = None
    party_size: int = 2
    fixed_camp: list[float] | None = None   # [lat, lon] — hunt-from-camp mode
    hunt_radius_km: float | None = None
    # Optional analysis-grid override (metres). None = auto (sized to the AOI so the
    # grid stays ~TARGET_PX per side). User-chosen values are clamped so a fine grid
    # on a big box can never OOM the droplet: never more than ~3200 px per side, and
    # never coarser than 500 m.
    resolution_m: float | None = None


def _clean_transport(t) -> dict:
    """Sanitize the transport multi-select to exactly three bools."""
    t = t if isinstance(t, dict) else {}
    return {k: bool(t.get(k)) for k in ("canoe", "motor", "atv")}


def _clean_sites(s):
    """Clamp known sites to <=4 valid (lat, lon) pairs, or None."""
    if not isinstance(s, list):
        return None
    out = []
    for p in s[:4]:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    return out or None


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
    if DRAINING:
        # 503 + Retry-After is the honest answer: the work is fine, this process is
        # about to be replaced and starting a run now would only get it killed.
        raise HTTPException(status_code=503, detail="engine-updating",
                            headers={"Retry-After": "120"})
    # A run holds hundreds of MB of raster. Two at once fits a 4 GB box; more is how you
    # OOM it. The thread model had no cap at all — it just got lucky with one user.
    if len(jobstore.active_ids()) >= MAX_CONCURRENT:
        raise HTTPException(status_code=503, detail="engine-busy",
                            headers={"Retry-After": "180"})
    jid = uuid.uuid4().hex[:12]
    jobstore.create(jid, req.model_dump(), uid)
    _spawn_worker(jid)
    return {"job_id": jid}


@app.get("/jobs/{jid}")
def job(jid: str, authorization: str = Header(default=None)):
    j = jobstore.read(jid)
    if not j:
        return {"status": "unknown"}
    # What the status ACTUALLY is: a worker killed outright never wrote a terminal
    # status, so the file still claims "running". Checking the pid turns that into
    # `interrupted` instead of a spinner that never stops.
    j = dict(j, status=jobstore.effective_status(j))
    # Every poll is a heartbeat. The front end polls a running job every 2.5 s, so
    # "nobody has asked in ORPHAN_S" means the tab is gone — closed, crashed or
    # navigated away — and the run is being computed for nobody. Using the existing
    # poll avoids a second mechanism, and it survives a reload: the new page
    # reconnects and resumes the heartbeat well inside the window.
    jobstore.update(jid, seen=time.time())
    # Don't hand one account's analysis to another; jobs are readable by their owner.
    if REQUIRE_ACCOUNT and j.get("uid") is not None:
        if _uid(authorization) != j.get("uid"):
            raise HTTPException(status_code=403, detail="not your job")
    # The finished contract lives on disk, not in the job state — state.json stays a few
    # hundred bytes instead of megabytes. Load it only when the client can use it.
    if j.get("status") == "done" and j.get("result"):
        try:
            j["scout"] = json.loads(Path(j["result"]).read_text())
        except Exception as e:  # noqa: BLE001
            j["status"] = "error"
            j["error"] = f"result unreadable: {e}"
    return j


@app.delete("/jobs/{jid}")
def cancel_job(jid: str, authorization: str = Header(default=None)):
    """Explicit abandon — sent by the page as it unloads, and usable from the UI."""
    j = jobstore.read(jid)
    if not j:
        return {"status": "unknown"}
    if REQUIRE_ACCOUNT and j.get("uid") is not None:
        if _uid(authorization) != j.get("uid"):
            raise HTTPException(status_code=403, detail="not your job")
    jobstore.set_cancel(jid)
    # The worker checks between stages, which can be minutes on `acquire`. SIGTERM makes
    # abandoning immediate; the cancel file is what stops a restart resuming it.
    pid = j.get("pid")
    if pid and jobstore.alive(pid):
        try:
            os.kill(int(pid), signal.SIGTERM)
        except OSError:
            pass
    jobstore.update(jid, status="cancelled", stage="cancelled")
    return {"status": "cancelling"}


ORPHAN_S = 90.0          # ~36 missed polls at the client's 2.5 s cadence


def _reap_orphans():
    """Cancel runs nobody is watching. A scout run pegs a core for minutes; one left
    behind by a closed tab is pure waste on a 2-vCPU box, and several of them are an
    outage. Started as a daemon so it dies with the process."""
    while True:
        time.sleep(30)
        now = time.time()
        try:
            for jid, j in list(jobstore.all_states()):
                if jobstore.effective_status(j) != "running" or jobstore.cancelled(jid):
                    continue
                seen = j.get("seen") or j.get("started") or now
                if now - seen > ORPHAN_S:
                    jobstore.set_cancel(jid)
                    jobstore.update(jid, orphaned=True)
                    pid = j.get("pid")
                    if pid and jobstore.alive(pid):
                        try:
                            os.kill(int(pid), signal.SIGTERM)
                        except OSError:
                            pass
            jobstore.prune()
        except Exception:  # noqa: BLE001 — a reaper must never take the API down
            pass


threading.Thread(target=_reap_orphans, daemon=True).start()


def _resume_interrupted():
    """Pick up runs whose worker died with the last container.

    HONEST LIMIT, measured rather than assumed: start_new_session detaches a worker from
    the API's process GROUP, not from the container. `docker rm -f` still kills it — I
    checked, and an earlier version of this claimed otherwise. So a deploy that replaces
    the container DOES kill the analysis running inside it.

    What makes that survivable is the pair of things #17 actually bought: the state is on
    disk, and stages skip work already done. So the new container looks for jobs that
    were running when the old one went away and starts them again — they resume at the
    stage they reached, and with the geography cache (#79) the acquire they already paid
    for costs seconds. The hunter sees the run continue instead of vanish.

    The drain is still the first line of defence; this is what happens when a drain was
    skipped, or the box died on its own."""
    try:
        for jid, st in list(jobstore.all_states()):
            if jobstore.effective_status(st) != "interrupted":
                continue
            if jobstore.cancelled(jid):
                continue          # abandoned on purpose; do not drag it back
            done = st.get("done_stages") or []
            print(f"[api] resuming interrupted job {jid} (had finished {len(done)} stages)")
            jobstore.update(jid, status="running", resumed=(st.get("resumed", 0) + 1))
            _spawn_worker(jid)
    except Exception as e:  # noqa: BLE001 — never let recovery stop the API booting
        print(f"[api] resume scan failed: {e}")


threading.Thread(target=_resume_interrupted, daemon=True).start()


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
                      transport=_clean_transport(r.transport),
                      sites=_clean_sites(r.sites),
                      walk_access_km=_walk(r.walk_access_km, 6.0, 0.5, 30.0),
                      walk_hunt_km=_walk(r.walk_hunt_km, 3.0, 0.3, 20.0),
                      party_size=max(1, min(12, int(r.party_size))),
                      fixed_camp=(tuple(r.fixed_camp[:2]) if r.fixed_camp and len(r.fixed_camp) >= 2 else None),
                      hunt_radius_km=(max(1.0, min(30.0, float(r.hunt_radius_km)))
                                      if r.hunt_radius_km is not None else None)))
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


def _active_jobs() -> int:
    """Runs still going. Since #17 these are separate processes that SURVIVE an API
    restart, so this is no longer "what a deploy would destroy" — but a deploy still
    waits for them, because the worker and the image it runs from should match."""
    return len(jobstore.active_ids())


@app.get("/health")
def health():
    from .version import ENGINE_REVISION, REVISIONS
    return {"ok": True, "species": sorted(SPECIES),
            "engine_revision": ENGINE_REVISION,
            "revision_notes": REVISIONS.get(ENGINE_REVISION, ""),
            # Deploy safety (see scripts/deploy_engine.sh). An analysis is minutes of
            # someone's evening; restarting the container under one throws it away with
            # no way to get it back. The deploy asks these two questions before it does
            # anything, instead of a human eyeballing CPU and guessing — which is exactly
            # how a live run got killed at 49% CPU.
            "active_jobs": _active_jobs(),
            "draining": DRAINING}


@app.post("/admin/drain")
def drain(on: bool = True, x_api_key: str = Header(default=None)):
    """Stop accepting NEW analyses so the running ones can finish.

    Without this a drain never converges: you wait for the last job while the app
    happily starts more. The flag is process-local on purpose — a fresh container comes
    up accepting work, which is the state you want after a deploy."""
    _require_key(x_api_key)
    global DRAINING
    DRAINING = bool(on)
    return {"draining": DRAINING, "active_jobs": _active_jobs()}


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
