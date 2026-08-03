import time, osmnx as ox
ox.settings.timeout=90
try: ox.settings.requests_timeout=90
except: pass
ox.settings.max_query_area_size=5_000_000_000
ox.settings.overpass_url="https://maps.mail.ru/osm/tools/overpass/api"
from moose_scout.config import load_species, load_model, Context, AOI, LatLon, SeasonCfg, HunterCfg
from moose_scout.acquire import roads
aoi=AOI(name='tem',title='tem',species='moose',center=LatLon(lat=47.165,lon=-78.019),
        bbox_halfwidth_km=35,season=SeasonCfg(year=2026,target_dates=['2026-09-25']),hunter=HunterCfg())
ctx=Context(aoi=aoi,species=load_species('moose'),model=load_model())
print('bbox:',[round(v,3) for v in aoi.bbox_wgs84()])
t=time.time()
g=roads._osm(ctx, roads.DRIVE_TAGS)
print(f'CHUNKED roads: rows={len(g)} in {time.time()-t:.0f}s')
if len(g): print('geom:',g.geometry.type.value_counts().to_dict())
