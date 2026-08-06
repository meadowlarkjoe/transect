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
from .config import (AOI, Context, HunterCfg, LatLon, SeasonCfg, _walk, load_model,
                     load_species, outputs_dir)

STAGES = ["acquire", "terrain", "habitat", "behavior", "access", "synth", "contract"]
SPECIES = {"moose", "whitetail_deer", "black_bear"}


def sites_of(req: dict):
    """The centres this request wants analysed, as [(lat, lon), ...].

    Setup has always promised "up to 4 sites — each gets its own analysis, ranked
    against the others", and the engine has never read past the first one: `sites` was
    validated, threaded through config, echoed into the contract, and consumed by
    NOTHING. sites[0] doubled as the AOI centre and 2..4 were drawn as rings on the
    client and thrown away. A hunter comparing two camps 50 km apart got one of them
    analysed and no indication which — a confident wrong answer, which is the worst kind.
    """
    raw = req.get("sites") or []
    out = []
    for p in raw[:4]:
        try:
            lat, lon = float(p[0]), float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            out.append((lat, lon))
    if not out:
        out = [(float(req["lat"]), float(req["lon"]))]
    return out


def build_ctx(name: str, req: dict):
    """Rebuild the analysis Context from the stored request. Mirrors what the API used
    to do inline; kept here so the worker depends on the STORE, not on the API.

    `name` is the CACHE identity, not the job id: a multi-site run gives each site its
    own cache and outputs directory so their rasters cannot overwrite each other.
    """
    import math

    species = req.get("species") if req.get("species") in SPECIES else "moose"
    lat, lon = float(req["lat"]), float(req["lon"])
    tr = req.get("transport") or {}
    sites = req.get("sites") or None
    aoi = AOI(
        name=name, title=f"{lat:.3f}, {lon:.3f}", species=species,
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
            # .get(k, default) only covers a MISSING key — an explicit null still
            # reaches float() and raises. The worker sees the same payloads the API
            # does, so it needs the same coalescing, not a near-miss of it.
            walk_access_km=_walk(req.get("walk_access_km"), 6.0, 0.5, 30.0),
            walk_hunt_km=_walk(req.get("walk_hunt_km"), 3.0, 0.3, 20.0),
            party_size=max(1, min(12, int(req.get("party_size") or 2))),
            fixed_camp=(tuple(req["fixed_camp"][:2]) if req.get("fixed_camp")
                        and len(req["fixed_camp"]) >= 2 else None),
            hunt_radius_km=(max(1.0, min(30.0, float(req["hunt_radius_km"])))
                            if req.get("hunt_radius_km") is not None else None),
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


def _merge(docs, sites):
    """Fold per-site contracts into ONE plan the app can draw.

    Areas keep their own site's identity and are re-ranked ACROSS sites by expected
    encounter (area x mean huntability) — the same ordering a single-site run uses, so
    "rank 1" means the same thing whether the hunter compared one camp or four. Every
    feature carries `site`, because an area, a stand and a route belonging to different
    ground must never be readable as one plan.

    Site 1's contract supplies the shared scaffolding (legal gate, methodology, legend,
    region, coverage). It is the AOI centre and the one the request was built around;
    merging legal verdicts across sites would be inventing a claim nobody computed.
    """
    base = None
    for d in docs:
        if d is not None:
            base = json.loads(json.dumps(d))
            break
    if base is None:
        return None
    if len(docs) == 1:
        return base

    LIST_KEYS = ["areas", "waypoints", "routes", "camps", "hunt_zones", "browse_zones",
                 "refuge_zones", "funnel_zones", "feed_edge_zones", "burn_zones",
                 "cut_zones", "wetland_zones", "beaver_ponds", "tenure_zones",
                 "browse_cut_zones", "browse_burn_zones", "browse_stand_zones",
                 "browse_lc_zones"]
    for k in LIST_KEYS:
        base[k] = []

    ranked = []
    letters = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    for i, d in enumerate(docs, start=1):
        if d is None:
            continue
        # CAMP IDS COLLIDE ACROSS SITES. Each site's contract letters its own camps from
        # A, so two sites both produce a "Camp A" — and the app finds an area's camp by
        # matching that letter. Left alone, site 2's areas would attach to site 1's camp
        # and the brief would send a hunter to the wrong cabin. Re-letter globally and
        # carry the rename into the areas that reference it.
        remap = {}
        for c in (d.get("camps") or []):
            old = c.get("id")
            new = next(letters, old)
            remap[old] = new
            base["camps"].append(dict(c, id=new, site=i))
        for a in (d.get("areas") or []):
            a = dict(a, site=i, site_rank=a.get("rank"))
            if a.get("camp") in remap:
                a["camp"] = remap[a["camp"]]
            ranked.append(a)
        for k in LIST_KEYS:
            if k in ("areas", "camps"):
                continue
            for it in (d.get(k) or []):
                if isinstance(it, dict):
                    it = dict(it, site=i)
                base[k].append(it)

    # Rank across sites on the same measure a single site ranks on internally.
    ranked.sort(key=lambda a: (a.get("area_km2") or 0) * (a.get("habitat_score") or 0),
                reverse=True)
    for n, a in enumerate(ranked, start=1):
        a["rank"] = n
    base["areas"] = ranked

    # Per-site summary — what the hunter actually asked for when they entered four
    # coordinates: how these places compare, and on what.
    out_sites = []
    for i, (d, (lat, lon)) in enumerate(zip(docs, sites), start=1):
        if d is None:
            out_sites.append({"site": i, "lat": lat, "lon": lon, "ok": False,
                              "areas": 0, "note": "this site could not be analysed"})
            continue
        ar = d.get("areas") or []
        best = max((a.get("habitat_score") or 0) for a in ar) if ar else 0.0
        out_sites.append({
            "site": i, "lat": lat, "lon": lon, "ok": True,
            "areas": len(ar),
            "best_habitat": round(float(best), 3),
            "total_km2": round(sum((a.get("area_km2") or 0) for a in ar), 1),
            "best_rank_overall": min([a["rank"] for a in ranked if a.get("site") == i],
                                     default=None),
        })
    base["sites"] = out_sites
    base["meta"] = dict(base.get("meta") or {}, multi_site=True,
                        site_count=len([d for d in docs if d is not None]))
    return base


def run(jid: str) -> int:
    req = jobstore.read_req(jid)
    if req is None:
        print(f"[worker] no stored request for {jid}", file=sys.stderr)
        return 2

    import os
    from .config import cache_dir
    name = f"job_{jid}"
    sites = sites_of(req)
    multi = len(sites) > 1
    try:
        jobstore.update(jid, pid=os.getpid(), site_count=len(sites))
        done_stages = set(jobstore.read(jid).get("done_stages") or [])
        docs, res = [], None

        for si, (slat, slon) in enumerate(sites, start=1):
            # Each site is a SEPARATE analysis with its own cache: different geography,
            # different rasters. Sharing one cache directory would have site 2 overwrite
            # site 1's terrain and quietly report the wrong ground for both.
            sub_req = dict(req, lat=slat, lon=slon)
            sub_name = name if not multi else f"{name}_s{si}"
            ctx, res = build_ctx(sub_name, sub_req)
            if si == 1:
                jobstore.update(jid, res_m=res)

            for i, stage in enumerate(STAGES):
                if jobstore.cancelled(jid):
                    jobstore.update(jid, status="cancelled", stage="cancelled")
                    return 0
                key = stage if not multi else f"s{si}:{stage}"
                if key in done_stages:
                    continue
                # Progress spans all sites, so a 4-site run does not sit at 100% three
                # times over.
                frac = ((si - 1) * len(STAGES) + i) / (len(sites) * len(STAGES))
                jobstore.update(jid, stage=stage, progress=round(frac, 2),
                                site=si if multi else None)
                pipeline.run_stage(stage, ctx)
                done_stages.add(key)
                jobstore.update(jid, done_stages=sorted(done_stages))

            sub_out = outputs_dir(sub_name) / "transect.json"
            if not sub_out.exists():
                raise RuntimeError(f"contract stage produced no transect.json for site {si}")
            docs.append(json.loads(sub_out.read_text()))

        merged = _merge(docs, sites)
        out = outputs_dir(name) / "transect.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(merged))

        # /rescope re-plans against these already-acquired rasters, and it rebuilds the
        # request from job_meta.json. The old in-API runner wrote it; the worker owns
        # that now, or "Recalculate in my areas" 404s on every run this engine produces.
        st = jobstore.read(jid) or {}
        try:
            (cache_dir(name if not multi else f"{name}_s1") / "job_meta.json").write_text(
                json.dumps({"req": req, "uid": st.get("uid"), "res_m": res,
                            "at": time.time()}))
        except Exception as e:  # noqa: BLE001 — a finished analysis is not worth failing
            print(f"[worker] job_meta not written ({e}) — rescope will refuse this job",
                  file=sys.stderr)

        jobstore.update(jid, status="done", stage="done", progress=1.0,
                        result=str(out), finished=time.time())
        print(f"[worker] {jid} done ({len(sites)} site(s))")
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
