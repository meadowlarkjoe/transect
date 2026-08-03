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
        ctx = Context(aoi=aoi, species=load_species(species), model=load_model())
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
