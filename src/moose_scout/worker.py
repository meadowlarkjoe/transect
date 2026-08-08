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


def windows_of(req: dict):
    """The date windows this request wants analysed, as [[start, end], ...].

    A WINDOW IS A SEPARATE MODEL RUN, not a different label on one. The habitat surface
    is phase-weighted (habitat_phase.tif — cow-weighted at peak rut, feed-weighted after
    it), and behavior, synth and the contract all read the dates too. So mid-September
    bow season and late-October rifle produce genuinely different huntability, different
    site mixes and different stands on the same ground. Rendering one run's answer under
    two date headings would be a lie that looks like a feature.

    Unlike SITES, windows share their geography — so the geography cache (#79) makes the
    acquire stage of the second window nearly free, and the real cost is the compute
    stages only.
    """
    raw = req.get("windows") or []
    out = []
    for w in raw[:4]:
        try:
            a, b = str(w[0]), str(w[1])
        except (TypeError, ValueError, IndexError):
            continue
        if a and b:
            out.append([a, b])
    if not out:
        out = [list(req.get("target_dates") or ["2026-09-25", "2026-10-05"])]
    return out


def build_ctx(name: str, req: dict, method: str | None = None):
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
    # A DRAWN BOUNDARY (T10.8). [[lon, lat], ...] — the same winding the app's draw tool
    # produces. Rejected quietly rather than loudly if it is not a real ring: a malformed
    # shape must fall back to the radius, not fail the run.
    ring = None
    _r = req.get("ring")
    if isinstance(_r, list) and len(_r) >= 4:
        try:
            ring = [(float(x), float(y)) for x, y in (pt[:2] for pt in _r)]
        except Exception:
            ring = None
    aoi = AOI(
        name=name, title=f"{lat:.3f}, {lon:.3f}", species=species,
        center=LatLon(lat=lat, lon=lon),
        bbox_halfwidth_km=max(3.0, min(120.0, float(req.get("radius_km", 35.0)))),
        ring=ring,
        zone_hint=req.get("zone_hint"),
        season=SeasonCfg(year=2026,
                         target_dates=req.get("target_dates") or ["2026-09-25", "2026-10-05"]),
        hunter=HunterCfg(
            residency=req.get("residency", "quebec_resident"),
            watercraft=req.get("watercraft") if req.get("watercraft") in ("none", "canoe", "motor") else "none",
            hunt_style=req.get("hunt_style") if req.get("hunt_style") in ("spike", "vehicle") else "spike",
            method=method if method in METHODS else (
                req.get("method") if req.get("method") in METHODS else "rifle"),
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
    # `effective_halfwidth_km`, not `bbox_halfwidth_km`: a drawn AOI's extent comes from
    # its padded ring, and sizing the grid from a stored radius it is not using would put
    # a 35 km box's resolution on a 3 km parcel — or, worse, the reverse.
    _hw = aoi.effective_halfwidth_km()
    auto_res = max(float(model.raster_resolution_m),
                   math.ceil(2 * _hw * 1000 / TARGET_PX))
    if req.get("resolution_m"):
        finest = max(20.0, math.ceil(2 * _hw * 1000 / 3200))
        res = max(finest, min(500.0, float(req["resolution_m"])))
    else:
        res = auto_res
    if res != model.raster_resolution_m:
        try:
            model = model.model_copy(update={"raster_resolution_m": res})
        except Exception:
            model.raster_resolution_m = res
    return Context(aoi=aoi, species=load_species(species), model=model), res


# Sections of a contract that are a function of the DATES, and so differ between
# windows. Everything not named here is either geography (legal, coverage, region,
# methodology) or already merged as a list. Checked against a real contract's keys —
# adding a dated section later without adding it here is how this bug comes back.
WINDOW_SECTIONS = ("rut", "strategy", "recommendations", "field_plan", "weather",
                   "behavior", "scent", "wind", "camp_plan")


METHODS = ("rifle", "bow", "muzzleloader")


def methods_of(req: dict):
    """The method of take per window, aligned 1:1 with `windows_of(req)`.

    A window is usually a SEASON and a season is usually a weapon — which is how Joe
    framed it: "I gave it two hunting windows (rifle vs bow season)". So the method
    belongs to the window, not to the hunt.

    Carried as an optional THIRD element of each window so that every request that ever
    worked still works: `["2026-10-10", "2026-10-25"]` is a rifle window, exactly as it
    has always been treated.
    """
    raw = req.get("windows") or []
    default = req.get("method") if req.get("method") in METHODS else "rifle"
    out = []
    for w in raw[:4]:
        try:
            a, b = str(w[0]), str(w[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (a and b):
            continue
        m = None
        try:
            m = str(w[2]) if len(w) > 2 else None
        except (TypeError, IndexError):
            m = None
        out.append(m if m in METHODS else default)
    if not out:
        out = [default]
    return out


def _merge(docs, plans):
    """Fold per-PLAN contracts into ONE document the app can draw.

    A "plan" is one (site, window) pair — the unit that actually gets computed. Sites
    vary the ground; windows vary the dates, and because the habitat surface is
    phase-weighted a window is a genuinely different model run rather than a relabelling.

    Areas keep their plan's identity and are re-ranked ACROSS all of them by expected
    encounter (area x mean huntability) — the same ordering a single run uses internally,
    so "rank 1" means the same thing however many places and seasons were compared. Every
    feature carries `site` and `window`, because an area, a stand and a route belonging to
    different ground or different weeks must never be readable as one plan.

    Plan 1's contract supplies the shared scaffolding (legal gate, methodology, legend,
    region, coverage). Merging legal verdicts across places would invent a claim nobody
    computed.
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
    for d, pl in zip(docs, plans):
        if d is None:
            continue
        si, wi = pl["site"], pl["window"]
        # CAMP IDS COLLIDE ACROSS PLANS. Each contract letters its own camps from A, and
        # the app finds an area's camp by matching that letter. Left alone, a second
        # plan's areas attach to the first plan's camp and the brief sends a hunter to
        # the wrong cabin. Re-letter globally and carry the rename into the areas.
        remap = {}
        for c in (d.get("camps") or []):
            old = c.get("id")
            new_id = next(letters, old)
            remap[old] = new_id
            base["camps"].append(dict(c, id=new_id, site=si, window=wi))
        for a in (d.get("areas") or []):
            a = dict(a, site=si, window=wi, site_rank=a.get("rank"))
            if a.get("camp") in remap:
                a["camp"] = remap[a["camp"]]
            ranked.append(a)
        for k in LIST_KEYS:
            if k in ("areas", "camps"):
                continue
            for it in (d.get(k) or []):
                if isinstance(it, dict):
                    it = dict(it, site=si, window=wi)
                base[k].append(it)

    ranked.sort(key=lambda a: (a.get("area_km2") or 0) * (a.get("habitat_score") or 0),
                reverse=True)
    for n, a in enumerate(ranked, start=1):
        a["rank"] = n
    base["areas"] = ranked

    n_sites = len({p["site"] for p in plans})
    n_wins = len({p["window"] for p in plans})

    def _roll(sel):
        """Summarise the subset of plans matching `sel`."""
        idx = [i for i, p in enumerate(plans) if sel(p)]
        ars = [a for a in ranked
               if any(a.get("site") == plans[i]["site"] and a.get("window") == plans[i]["window"]
                      for i in idx)]
        ok = any(docs[i] is not None for i in idx)
        best = max((a.get("habitat_score") or 0) for a in ars) if ars else 0.0
        return {
            "ok": ok, "areas": len(ars),
            "best_habitat": round(float(best), 3),
            "total_km2": round(sum((a.get("area_km2") or 0) for a in ars), 1),
            "best_rank_overall": min([a["rank"] for a in ars], default=None),
        }

    if n_sites > 1:
        seen, out_sites = set(), []
        for pl in plans:
            if pl["site"] in seen:
                continue
            seen.add(pl["site"])
            r = _roll(lambda p, s=pl["site"]: p["site"] == s)
            out_sites.append(dict(r, site=pl["site"], lat=pl["lat"], lon=pl["lon"],
                                  note=None if r["ok"] else "this site could not be analysed"))
        base["sites"] = out_sites

    if n_wins > 1:
        # PER-WINDOW COMPARISON — the thing a hunter is asking when they enter bow season
        # AND rifle season: not "which dates are on the calendar" but "which of these
        # weeks is worth taking off work, and what changes between them".
        #
        # ...AND THE WHOLE BRIEF FOR EACH, WHICH IS THE HALF T9.2 MISSED (T10.1).
        # Everything above merges the LISTS — areas, waypoints, routes — and tags each
        # with its window. But `base` is plan 1's document, so every non-list section
        # stayed plan 1's: the rut read, the strategy, the recommendations, the weather,
        # the day plan. A two-window run therefore rendered rifle-window advice under a
        # bow-window area, with nothing anywhere saying which dates it was written for.
        # Reported from a real run: "the brief for both areas provides its analysis based
        # on the first date range".
        #
        # The engine already computed all of it correctly, once per window. It was only
        # ever a reporting failure — so carry the sections through rather than
        # recomputing anything.
        seen, out_wins = set(), []
        for i, pl in enumerate(plans):
            if pl["window"] in seen:
                continue
            seen.add(pl["window"])
            r = _roll(lambda p, w=pl["window"]: p["window"] == w)
            d = docs[i]
            rut = (d or {}).get("rut") or {}
            tg = rut.get("targets") or []
            entry = dict(
                r, window=pl["window"], start=pl["dates"][0], end=pl["dates"][1],
                dates=list(pl["dates"]), method=pl.get("method") or "rifle",
                phase=(tg[0].get("phase") if tg else None),
                rut_read=rut.get("hunt_read"),
                note=None if r["ok"] else "this window could not be analysed")
            if d:
                entry["brief"] = {k: d[k] for k in WINDOW_SECTIONS if k in d}
            out_wins.append(entry)
        base["windows"] = out_wins
        # The top level still carries window 1's sections, so an older client and a
        # saved plan keep rendering. Say so, loudly enough that nothing reads them as
        # belonging to the whole run.
        base["meta"] = dict(base.get("meta") or {}, top_level_window=plans[0]["window"])

    base["meta"] = dict(base.get("meta") or {},
                        multi_site=n_sites > 1, site_count=n_sites,
                        multi_window=n_wins > 1, window_count=n_wins,
                        plan_count=len([d for d in docs if d is not None]))
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
    windows = windows_of(req)
    methods = methods_of(req)
    # ONE RUN PER (SITE, WINDOW). Sites vary the ground and each needs its own acquire;
    # windows share geography, so the geography cache (#79) makes their acquire nearly
    # free and only the compute stages repeat.
    plans = [{"site": si, "lat": lat, "lon": lon, "window": wi, "dates": list(w),
              "method": methods[wi - 1] if wi - 1 < len(methods) else "rifle"}
             for si, (lat, lon) in enumerate(sites, start=1)
             for wi, w in enumerate(windows, start=1)]
    multi = len(plans) > 1
    try:
        jobstore.update(jid, pid=os.getpid(), site_count=len(sites),
                        window_count=len(windows), plan_count=len(plans))
        done_stages = set(jobstore.read(jid).get("done_stages") or [])
        docs, res = [], None

        for pi, pl in enumerate(plans, start=1):
            # Each plan is a SEPARATE analysis with its own cache. Different geography
            # means different rasters; different DATES mean a different phase-weighted
            # habitat surface. Sharing one cache directory would have the second plan
            # overwrite the first and quietly report one answer under two headings.
            sub_req = dict(req, lat=pl["lat"], lon=pl["lon"], target_dates=pl["dates"])
            sub_name = name if not multi else f"{name}_s{pl['site']}w{pl['window']}"
            ctx, res = build_ctx(sub_name, sub_req, method=pl.get("method"))
            if pi == 1:
                jobstore.update(jid, res_m=res)

            for i, stage in enumerate(STAGES):
                if jobstore.cancelled(jid):
                    jobstore.update(jid, status="cancelled", stage="cancelled")
                    return 0
                key = stage if not multi else f"p{pi}:{stage}"
                if key in done_stages:
                    continue
                # Progress spans every plan, so a 4-plan run does not sit at 100% three
                # times over.
                frac = ((pi - 1) * len(STAGES) + i) / (len(plans) * len(STAGES))
                jobstore.update(jid, stage=stage, progress=round(frac, 2),
                                site=pl["site"] if multi else None,
                                window=pl["window"] if len(windows) > 1 else None)
                pipeline.run_stage(stage, ctx)
                done_stages.add(key)
                jobstore.update(jid, done_stages=sorted(done_stages))

            sub_out = outputs_dir(sub_name) / "transect.json"
            if not sub_out.exists():
                raise RuntimeError(
                    f"contract stage produced no transect.json for site {pl['site']} "
                    f"window {pl['window']}")
            docs.append(json.loads(sub_out.read_text()))

        merged = _merge(docs, plans)
        out = outputs_dir(name) / "transect.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(merged))

        # /rescope re-plans against these already-acquired rasters, and it rebuilds the
        # request from job_meta.json. The old in-API runner wrote it; the worker owns
        # that now, or "Recalculate in my areas" 404s on every run this engine produces.
        st = jobstore.read(jid) or {}
        try:
            (cache_dir(name if not multi else f"{name}_s1w1") / "job_meta.json").write_text(
                json.dumps({"req": req, "uid": st.get("uid"), "res_m": res,
                            "at": time.time()}))
        except Exception as e:  # noqa: BLE001 — a finished analysis is not worth failing
            print(f"[worker] job_meta not written ({e}) — rescope will refuse this job",
                  file=sys.stderr)

        jobstore.update(jid, status="done", stage="done", progress=1.0,
                        result=str(out), finished=time.time())
        print(f"[worker] {jid} done ({len(sites)} site(s) x {len(windows)} window(s))")
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
