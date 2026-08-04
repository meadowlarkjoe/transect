import time, osmnx as ox
from moose_scout.acquire import _pick_overpass
m=_pick_overpass(); print('mirror:',m)
ox.settings.timeout=90; ox.settings.max_query_area_size=5_000_000_000
ox.settings.overpass_url=m
from moose_scout.config import load_species, load_model, Context, AOI, LatLon, SeasonCfg, HunterCfg
from moose_scout.acquire import roads
aoi=AOI(name='tem',title='tem',species='moose',center=LatLon(lat=47.165,lon=-78.019),
        bbox_halfwidth_km=35,season=SeasonCfg(year=2026,target_dates=['2026-09-25']),hunter=HunterCfg())
ctx=Context(aoi=aoi,species=load_species('moose'),model=load_model())
t=time.time(); g=roads._osm(ctx, roads.DRIVE_TAGS)
print(f'ROADS: rows={len(g)} in {time.time()-t:.0f}s   (was 8043s on the slow mirror)')
