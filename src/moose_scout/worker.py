"""One analysis, in its own process (#17).

    python -m moose_scout.worker <job_id>

The run used to be a daemon thread inside uvicorn. That coupled two things that have no
business being coupled: the lifetime of the WEB SERVER and the lifetime of a ten-minute
computation. Restarting the API to ship a change — or the API dying for any reason at
all — took every in-flight analysis with it. And because the pipeline holds hundreds of
megabytes of raster, one oversized box could OOM the process and take the API down with
it, so a single user's request became everyone's outage.

As a separate process:

  * the API can be replaced under a running job — which is what makes a deploy safe;
  * an OOM kills the job that caused it, and the API stays up to report it;
  * the kernel, not our code, guarantees the memory is released when it ends;
  * progress is a file, so whoever asks next can answer without having been there.

The worker reads its request from the job store, so it needs nothing from the process
that spawned it. That independence is the entire point.
"""
from __future__ import annotations

import json
import sys
import time
import traceback

from . import jobstore, pipeline
from .config import (AOI, Context, HunterCfg, LatLon, SeasonCfg, load_model,
                     load_species, outputs_dir)

STAGES = ["acquire", "terrain", "habitat", "behavior", "access", "synth", "contract"]
SPECIES = {"moose", "whitetail_deer", "black_bear"}


def build_ctx(jid: str, req: dict):
    """Rebuild the analysis Context from the stored request. Mirrors what the API used
    to do inline; kept here so the worker depends on the STORE, not on the API."""
    import math

    species = req.get("species") if req.get("species") in SPECIES else "moose"
    lat, lon = float(req["lat"]), float(req["lon"])
    tr = req.get("transport") or {}
    sites = req.get("sites") or None
    aoi = AOI(
        name=f"job_{jid}", title=f"{lat:.3f}, {lon:.3f}", species=species,
        center=LatLon(lat=lat, lon=lon),
        bbox_halfwidth_km=max(3.0, min(120.0, float(req.get("radius_km", 35.0)))),
        zone_hint=req.get("zone_hint"),
        season=SeasonCfg(year=2026,
                         target_dates=req.get("target_dates") or ["2026-09-25", "2026-10-05"]),
        hunter=HunterCfg(
            residency=req.get("residency", "quebec_resident"),
            watercraft=req.get("watercraft") if req.get("watercraft") in ("none", "canoe", "motor") else "none",
            hunt_style=req.get("hunt_style") if req.get("hunt_style") in ("spike", "vehicle") else "spike",
            transport={k: bool(tr.get(k)) for k in ("canoe", "motor", "atv")},
            sites=[tuple(s) for s in sites] if sites else None,
            walk_access_km=max(0.5, min(30.0, float(req.get("walk_access_km", 6.0)))),
            walk_hunt_km=max(0.3, min(20.0, float(req.get("walk_hunt_km", 3.0)))),
            party_size=max(1, min(12, int(req.get("party_size", 2)))),
            fixed_camp=(tuple(req["fixed_camp"][:2]) if req.get("fixed_camp")
                        and len(req["fixed_camp"]) >= 2 else None),
            hunt_radius_km=(max(1.0, min(30.0, float(req["hunt_radius_km"])))
                            if req.get("hunt_radius_km") else None),
        ),
    )
    # Analysis resolution: scale with the box so a big area cannot blow past RAM, and
    # clamp any user override to the same ceiling. Memory grows with pixels SQUARED —
    # a 120 km radius at 40 m is 6000² = 36 M cells per raster.
    model = load_model()
    TARGET_PX = 2400
    auto_res = max(float(model.raster_resolution_m),
                   math.ceil(2 * aoi.bbox_halfwidth_km * 1000 / TARGET_PX))
    if req.get("resolution_m"):
        finest = max(20.0, math.ceil(2 * aoi.bbox_halfwidth_km * 1000 / 3200))
        res = max(finest, min(500.0, float(req["resolution_m"])))
    else:
        res = auto_res
    if res != model.raster_resolution_m:
        try:
            model = model.model_copy(update={"raster_resolution_m": res})
        except Exception:
            model.raster_resolution_m = res
    return Context(aoi=aoi, species=load_species(species), model=model), res


def run(jid: str) -> int:
    req = jobstore.read_req(jid)
    if req is None:
        print(f"[worker] no stored request for {jid}", file=sys.stderr)
        return 2

    name = f"job_{jid}"
    try:
        ctx, res = build_ctx(jid, req)
        jobstore.update(jid, res_m=res, pid=__import__("os").getpid())

        # RESUME. Stages write to the job's cache dir and each one skips work already on
        # disk, so a run cut short by a restart picks up where it stopped instead of
        # starting over. With the geography cache (#79) acquire is seconds on a box we
        # have seen before, which is what makes resuming worth doing rather than a
        # nice idea.
        done_stages = set(jobstore.read(jid).get("done_stages") or [])
        for i, stage in enumerate(STAGES):
            if jobstore.cancelled(jid):
                jobstore.update(jid, status="cancelled", stage="cancelled")
                return 0
            if stage in done_stages:
                continue
            jobstore.update(jid, stage=stage, progress=round(i / len(STAGES), 2))
            pipeline.run_stage(stage, ctx)
            done_stages.add(stage)
            jobstore.update(jid, done_stages=sorted(done_stages))

        # The contract itself stays on disk; state.json holds status, not megabytes.
        out = outputs_dir(name) / "transect.json"
        if not out.exists():
            raise RuntimeError("contract stage produced no transect.json")

        # /rescope re-plans against these already-acquired rasters, and it rebuilds the
        # request from job_meta.json. The old in-API runner wrote it; the worker owns
        # that now, or "Recalculate in my areas" 404s on every run this engine produces.
        from .config import cache_dir
        st = jobstore.read(jid) or {}
        try:
            (cache_dir(name) / "job_meta.json").write_text(json.dumps({
                "req": req, "uid": st.get("uid"), "res_m": res, "at": time.time()}))
        except Exception as e:  # noqa: BLE001 — a finished analysis is not worth failing
            print(f"[worker] job_meta not written ({e}) — rescope will refuse this job",
                  file=sys.stderr)

        jobstore.update(jid, status="done", stage="done", progress=1.0,
                        result=str(out), finished=time.time())
        print(f"[worker] {jid} done")
        return 0
    except Exception as e:  # noqa: BLE001
        jobstore.update(jid, status="error", error=str(e),
                        trace=traceback.format_exc()[-1200:], finished=time.time())
        print(f"[worker] {jid} FAILED: {e}", file=sys.stderr)
        # The cache is deliberately KEPT on failure now. It used to be deleted, which
        # threw away everything the run had already fetched and made a retry pay the
        # full download again; the stage-skip logic makes the leftovers useful.
        return 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m moose_scout.worker <job_id>", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(run(sys.argv[1]))
