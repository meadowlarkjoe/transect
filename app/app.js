/* Transect on MapLibre — binds window.TRANSECT_DATA (engine transect.json). */
let DOC = window.TRANSECT_DATA;
let selectedDay = null;
// Live engine API (Setup → RUN ANALYSIS recomputes for a new species/area/radius).
// URL + key come from config.js (deployed, not in the repo); ?api= overrides for tests.
const API_URL = (new URLSearchParams(location.search).get('api')) ||
  (typeof window!=='undefined' && window.TRANSECT_API) ||
  'https://api.joejmeadows.com';
const API_KEY = (typeof window!=='undefined' && window.TRANSECT_API_KEY) || '';

/* ---------------- hunt setup state ---------------- */
let SETUP = { watercraft:'canoe', huntStyle:'spike' };   // watercraft: none|canoe|motor ; huntStyle: spike|vehicle

/* ---------------- units ---------------- */
let UNITS = 'metric';                       // 'metric' | 'imperial'
const KM_MI = 1.609344;
const km = (v) => UNITS === 'imperial' ? (v / KM_MI).toFixed(1) + ' mi' : v.toFixed(1) + ' km';
const metres = (m) => UNITS === 'imperial' ? Math.round(m * 1.09361) + ' yd' : Math.round(m) + ' m';
const unitBig = () => UNITS === 'imperial' ? 'mi' : 'km';
const unitSmall = () => UNITS === 'imperial' ? 'yd' : 'm';
const toU = (kmVal) => UNITS === 'imperial' ? kmVal / KM_MI : kmVal;   // km -> display-unit number
const fromU = (v) => UNITS === 'imperial' ? v * KM_MI : v;            // display-unit -> km

/* ---------------- palette / labels ---------------- */
const COLORS = {
  focus_area:'#111111', rut_calling:'#e2231a', thermal_refuge:'#ff3fb4',
  saline_blind:'#3d7bff', funnel:'#ff8c00', glassing:'#2fbf5b',
  validate_ground:'#c9d1d6', base_camp:'#b98a3e', parking:'#e0c06a',
  route_best:'#e2231a', route_midday_hot:'#ff3fb4'
};
const LABELS = {
  rut_calling:'Rut / calling (≥30 min)', thermal_refuge:'Thermal refuge',
  saline_blind:'Saline / feeding', funnel:'Funnel / pass', glassing:'Glassing knob',
  validate_ground:'Ground-truth', base_camp:'Base camp', parking:'Vehicle staging'
};
const SHAPE = {
  rut_calling:'circle', thermal_refuge:'ring', saline_blind:'square', funnel:'bowtie',
  glassing:'triangle', validate_ground:'diamond', base_camp:'tent', parking:'flag'
};
// Sites = POINT features. thermal_refuge + funnel are AREAS now (zones), not points.
const SITE_TYPES = ['rut_calling','saline_blind','glassing','validate_ground'];
const REFUGE_COL='#c94fa4', FUNNEL_COL='#e08a24';
const ZONE_WHY={
  refuge:'Thermal-refuge bedding — cool mature conifer / north aspect near water. Where a bull holds through a warm midday. Hunt the shade, approach from above/downwind.',
  funnel:'Terrain funnel / pass — a pinch point that concentrates travelling bulls between cover and feed. Sit downwind of the throat during movement windows.'};
// Huntability likelihood classes (defined zones, not heat) — red = best.
const HUNT_CLS = {high:{c:'#e2231a',label:'High likelihood'},medium:{c:'#ff8c00',label:'Medium likelihood'},low:{c:'#f2d02a',label:'Low likelihood'}};
const HUNT_WHY = {
  high:'Top of the model here — the browse/water/edge/terrain factors line up best. Prime ground to hunt.',
  medium:'Solid ground — a good mix of the factors, worth hunting especially near the high zones and edges.',
  low:'Marginal — some habitat value but the factors are weaker; travel/edge only, or skip for the better zones.'};
const BROWSE_COL = {'Shrub / regen browse':'#7ad151','Riparian / wetland browse':'#22a884',
  'Herbaceous opening':'#bddf26','Forest-edge browse':'#35b779'};
let showBrowse = false;

/* ---------------- basemap ---------------- */
const ESRI = k => `https://server.arcgisonline.com/ArcGIS/rest/services/${k}/MapServer/tile/{z}/{y}/{x}`;
function baseStyle(){
  return {
    version:8, glyphs:'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources:{
      satellite:{type:'raster',tiles:[ESRI('World_Imagery')],tileSize:256,attribution:'Esri'},
      topo:{type:'raster',tiles:[ESRI('World_Topo_Map')],tileSize:256,attribution:'Esri'},
      relief:{type:'raster',tiles:[ESRI('Elevation/World_Hillshade')],tileSize:256,attribution:'Esri — Hillshade'},
      trans:{type:'raster',tiles:[ESRI('Reference/World_Transportation')],tileSize:256},
      boundaries:{type:'raster',tiles:[ESRI('Reference/World_Boundaries_and_Places')],tileSize:256},
      dem:{type:'raster-dem',tiles:['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
           encoding:'terrarium',tileSize:256,maxzoom:14}
    },
    layers:[
      {id:'satellite',type:'raster',source:'satellite'},
      {id:'topo',type:'raster',source:'topo',layout:{visibility:'none'}},
      {id:'relief',type:'raster',source:'relief',layout:{visibility:'none'}},
      // map-level reference overlays (independent of the analysis): roads (dense when
      // zoomed in) + admin boundaries/places (dense when zoomed out). Owned by their
      // own layer toggles; default on.
      {id:'trans',type:'raster',source:'trans',layout:{visibility:'none'}},
      {id:'boundaries',type:'raster',source:'boundaries',layout:{visibility:'none'}}
    ],
    sky:{}
  };
}
const BASEMAPS=['satellite','topo','relief','hybrid'];
const BASE_LABEL={satellite:'Satellite',topo:'Topo',relief:'Relief',hybrid:'Hybrid'};
let curBase='satellite';
function switchBase(base){
  curBase=base;
  const vis=(id,on)=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',on?'visible':'none');
  vis('satellite', base==='satellite'||base==='hybrid');
  vis('topo', base==='topo');
  vis('relief', base==='relief');
  // NOTE: 'trans' (global roads overlay) is NOT tied to the basemap anymore — the
  // "Roads & rail" layer toggle owns it, so roads render on every basemap independent
  // of the engine analysis. Don't touch its visibility here.
  document.querySelectorAll('[data-base]').forEach(b=>b.classList.toggle('on',b.dataset.base===base));
}
const map = new maplibregl.Map({container:'map',style:baseStyle(),
  center:[DOC.meta.center.lon,DOC.meta.center.lat],zoom:9.4,pitch:0,maxPitch:80,
  attributionControl:{compact:true}});
map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'bottom-right');
map.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-right');

/* ---------------- turbo colormap + heat surface ---------------- */
function turbo(t){
  // clean 5-stop heat ramp: deep blue → teal → green → yellow → red
  t=Math.max(0,Math.min(1,t));
  const stops=[[46,26,110],[38,120,180],[46,180,120],[238,214,58],[214,48,28]];
  const x=t*(stops.length-1), i=Math.min(stops.length-2,Math.floor(x)), f=x-i;
  const a=stops[i], b=stops[i+1];
  return [Math.round(a[0]+(b[0]-a[0])*f),Math.round(a[1]+(b[1]-a[1])*f),Math.round(a[2]+(b[2]-a[2])*f)];
}
let HEAT = { thresh:0.42, source:'hunt', on:true, opacity:0.7 };
function gridFor(name){
  const g=DOC.grid||{};
  if(name==='browse') return g.browse;
  if(DOC.behavior && DOC.behavior.grids && DOC.behavior.grids[name]) return DOC.behavior.grids[name];
  return g.hunt;
}
function heatURL(){
  const g=DOC.grid||{}, gw=g.gw||260, gh=g.gh||175, arr=gridFor(HEAT.source)||g.hunt||[];
  const cv=document.createElement('canvas'); cv.width=gw; cv.height=gh;
  const cx=cv.getContext('2d'); const img=cx.createImageData(gw,gh);
  for(let i=0;i<gw*gh;i++){
    const v=arr[i];
    if(v==null||v<0||v<HEAT.thresh){ img.data[i*4+3]=0; continue; }
    const [r,gg,b]=turbo(v);
    img.data[i*4]=r; img.data[i*4+1]=gg; img.data[i*4+2]=b; img.data[i*4+3]=255;
  }
  cx.putImageData(img,0,0);
  return cv.toDataURL();
}
function heatCoords(){ const b=DOC.box; return [[b.w,b.n],[b.e,b.n],[b.e,b.s],[b.w,b.s]]; }
function updateHeat(){
  const src=map.getSource('heat'); if(!src)return;
  try{ src.updateImage({url:heatURL(),coordinates:heatCoords()}); }catch(e){/* image load race — ignore */}
  if(map.getLayer('heat')) map.setPaintProperty('heat','raster-opacity',HEAT.on?HEAT.opacity:0);
}

/* ---------------- distinct site icons (canvas -> addImage) ---------------- */
function iconData(shape,color){
  const S=36,cv=document.createElement('canvas');cv.width=cv.height=S;const c=cv.getContext('2d');
  c.translate(S/2,S/2); c.lineJoin='round';
  const R=11; c.lineWidth=3; c.strokeStyle='#0b0f0d';
  c.fillStyle=color;
  const path=()=>{
    c.beginPath();
    if(shape==='circle'){c.arc(0,0,R,0,7);}
    else if(shape==='ring'){c.arc(0,0,R,0,7);}
    else if(shape==='square'){c.rect(-R*0.85,-R*0.85,R*1.7,R*1.7);}
    else if(shape==='diamond'){c.moveTo(0,-R);c.lineTo(R,0);c.lineTo(0,R);c.lineTo(-R,0);c.closePath();}
    else if(shape==='triangle'){c.moveTo(0,-R*1.1);c.lineTo(R,R*0.8);c.lineTo(-R,R*0.8);c.closePath();}
    else if(shape==='bowtie'){c.moveTo(-R,-R);c.lineTo(-R*0.2,0);c.lineTo(-R,R);c.closePath();c.moveTo(R,-R);c.lineTo(R*0.2,0);c.lineTo(R,R);c.closePath();}
    else if(shape==='tent'){c.moveTo(-R,R*0.85);c.lineTo(0,-R);c.lineTo(R,R*0.85);c.closePath();}
    else if(shape==='flag'){c.moveTo(-R*0.7,R);c.lineTo(-R*0.7,-R);c.lineTo(R*0.8,-R*0.4);c.lineTo(-R*0.7,R*0.1);}
    else {c.arc(0,0,R,0,7);}
  };
  path();
  if(shape==='ring'){c.stroke();c.lineWidth=1.6;c.strokeStyle=color;c.stroke();}
  else if(shape==='flag'){c.stroke();c.fill();}
  else {c.stroke();c.fill();}
  if(shape==='tent'){c.beginPath();c.moveTo(0,-R);c.lineTo(0,R*0.85);c.lineWidth=1.4;c.strokeStyle='#0b0f0d';c.stroke();}
  const d=c.getImageData(0,0,S,S);
  return {width:S,height:S,data:d.data};
}
function addIcons(){
  Object.keys(SHAPE).forEach(t=>{ if(!map.hasImage(t)) map.addImage(t,iconData(SHAPE[t],COLORS[t]||'#ccc'),{pixelRatio:2}); });
}

/* ---------------- data → GeoJSON ---------------- */
const fc = (features) => ({type:'FeatureCollection',features});
function bbox(areas){let a=180,b=90,c=-180,d=-90;
  areas.forEach(x=>x.geometry.coordinates[0].forEach(([X,Y])=>{a=Math.min(a,X);b=Math.min(b,Y);c=Math.max(c,X);d=Math.max(d,Y);}));
  return [[a,b],[c,d]];}

/* optimal wind fit for a waypoint on the selected day */
function angDiff(a,b){return Math.abs(((a-b+180)%360)-180);}
function windState(w){
  if(selectedDay==null) return 0;
  const opt=(w.properties.optimal_wind||{}).from_deg; if(opt==null) return 0;
  return angDiff(opt,selectedDay.wind_from_deg)<=45?1:-1;
}

let hideTypes = {};           // per-type show/hide

function buildSources(){
  const areas=fc(DOC.areas.map(a=>({type:'Feature',geometry:a.geometry,
    properties:{rank:a.rank,camp:a.camp,hunt:a.huntability,dr:(a.stats||{}).dist_road_m||0}})));
  const areaLabels=fc(DOC.areas.map(a=>({type:'Feature',geometry:{type:'Point',coordinates:a.centroid},
    properties:{rank:a.rank,top:a.rank<=2}})));
  // camps from contract (grouped, sited at access) → drawn as base camps
  const camps=fc(DOC.camps.map(c=>({type:'Feature',geometry:{type:'Point',coordinates:[c.site.lon,c.site.lat]},
    properties:{id:c.id,label:'Camp '+c.id}})));
  // vehicle staging = parking waypoints
  const staging=fc(DOC.waypoints.filter(w=>w.type==='parking').map(w=>({type:'Feature',
    geometry:{type:'Point',coordinates:[w.lon,w.lat]},properties:{}})));
  // sites = the hunt-site waypoints (distinct icons)
  window._sites=DOC.waypoints.filter(w=>SITE_TYPES.includes(w.type)).map(w=>({type:'Feature',
    geometry:{type:'Point',coordinates:[w.lon,w.lat]},
    properties:{type:w.type,area:w.properties.focus_area,
      windnote:(w.properties.optimal_wind||{}).note||'', opt:(w.properties.optimal_wind||{}).from_deg??null,
      when:w.properties.when||'', elev:w.properties.elev_m||null, windok:0}}));
  // camp → area pack-in routes
  const packin=[];
  DOC.camps.forEach(c=>{ (c.member_areas||[]).forEach(rk=>{
    const a=DOC.areas.find(x=>x.rank===rk); if(a) packin.push({type:'Feature',
      geometry:{type:'LineString',coordinates:[[c.site.lon,c.site.lat],a.centroid]},properties:{}});});});
  // exact vector hydrography (rivers carry a class: river=boat, stream=fordable)
  const h=DOC.hydro||{rivers:[],lakes:[]};
  const rivers=fc((h.rivers||[]).map(o=>{
    const ll=o.ll||o; return {type:'Feature',geometry:{type:'LineString',coordinates:ll},properties:{cls:o.cls||'stream'}};}));
  const lakes=fc((h.lakes||[]).map(r=>({type:'Feature',geometry:{type:'Polygon',coordinates:[r]},properties:{}})));
  const crossings=fc((DOC.crossings||[]).map(c=>({type:'Feature',geometry:{type:'Point',coordinates:c.ll},
    properties:{route:c.route,kind:c.kind||'stream'}})));
  // classified suitability zones (defined areas, not heat)
  const huntZones=fc((DOC.hunt_zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},
    properties:{cls:z.cls,area_km2:z.area_km2}})));
  const browseZones=fc((DOC.browse_zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},
    properties:{type:z.type,what:z.what,when:z.when,area_km2:z.area_km2}})));
  const zFC=(zones)=>fc((zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},properties:{area_km2:z.area_km2}})));
  const refugeZones=zFC(DOC.refuge_zones), funnelZones=zFC(DOC.funnel_zones);
  const infra=fc((DOC.infra||[]).map(o=>({type:'Feature',geometry:{type:'LineString',coordinates:o.ll},properties:{t:o.t}})));
  return {areas,areaLabels,camps,staging,packin,rivers,lakes,crossings,huntZones,browseZones,refugeZones,funnelZones,infra};
}

function init(){
  document.getElementById('subtitle').textContent =
    `${DOC.meta.title} · ${DOC.meta.species} · ${DOC.meta.target_dates.join(' – ')}`;
  if(!document.getElementById('deepBadge')){const b=document.createElement('div');b.id='deepBadge';b.style.display='none';document.body.appendChild(b);}
  addIcons();
  const S=buildSources();
  window._aoi={huntZones:S.huntZones,browseZones:S.browseZones,rivers:S.rivers,lakes:S.lakes,
    refugeZones:S.refugeZones,funnelZones:S.funnelZones};

  // classified suitability zones (defined areas, not heat) — clickable for rationale
  map.addSource('huntZones',{type:'geojson',data:S.huntZones});
  map.addSource('browseZones',{type:'geojson',data:S.browseZones});
  const clsColor=['match',['get','cls'],'high',HUNT_CLS.high.c,'medium',HUNT_CLS.medium.c,'low',HUNT_CLS.low.c,'#888'];
  map.addLayer({id:'huntZones',type:'fill',source:'huntZones',
    paint:{'fill-color':clsColor,'fill-opacity':['match',['get','cls'],'high',0.42,'medium',0.3,'low',0.18,0.2]}});
  map.addLayer({id:'huntZones-line',type:'line',source:'huntZones',
    paint:{'line-color':clsColor,'line-width':1.4,'line-opacity':0.85}});
  const brCol=['match',['get','type'],
    'Shrub / regen browse',BROWSE_COL['Shrub / regen browse'],
    'Riparian / wetland browse',BROWSE_COL['Riparian / wetland browse'],
    'Herbaceous opening',BROWSE_COL['Herbaceous opening'],
    'Forest-edge browse',BROWSE_COL['Forest-edge browse'],'#7ad151'];
  map.addLayer({id:'browseZones',type:'fill',source:'browseZones',
    layout:{visibility:'none'},paint:{'fill-color':brCol,'fill-opacity':0.4}});
  map.addLayer({id:'browseZones-line',type:'line',source:'browseZones',
    layout:{visibility:'none'},paint:{'line-color':brCol,'line-width':1.2,'line-opacity':0.9,'line-dasharray':[2,1]}});
  // thermal refuge + funnel ZONES (areas, not points)
  map.addSource('refugeZones',{type:'geojson',data:S.refugeZones});
  map.addSource('funnelZones',{type:'geojson',data:S.funnelZones});
  map.addLayer({id:'refugeZones',type:'fill',source:'refugeZones',paint:{'fill-color':REFUGE_COL,'fill-opacity':0.28}});
  map.addLayer({id:'refugeZones-line',type:'line',source:'refugeZones',paint:{'line-color':REFUGE_COL,'line-width':1.3,'line-opacity':0.9,'line-dasharray':[4,2]}});
  map.addLayer({id:'funnelZones',type:'fill',source:'funnelZones',paint:{'fill-color':FUNNEL_COL,'fill-opacity':0.3}});
  map.addLayer({id:'funnelZones-line',type:'line',source:'funnelZones',paint:{'line-color':FUNNEL_COL,'line-width':1.4,'line-opacity':0.95}});

  map.addSource('lakes',{type:'geojson',data:S.lakes});
  map.addSource('rivers',{type:'geojson',data:S.rivers});
  map.addSource('crossings',{type:'geojson',data:S.crossings});
  map.addSource('areas',{type:'geojson',data:S.areas});
  map.addSource('areaLabels',{type:'geojson',data:S.areaLabels});
  map.addSource('camps',{type:'geojson',data:S.camps});
  map.addSource('staging',{type:'geojson',data:S.staging});
  map.addSource('packin',{type:'geojson',data:fc(S.packin)});
  map.addSource('sites',{type:'geojson',data:fc(window._sites)});

  // exact hydrography (crisp vector — narrow rivers the raster missed)
  map.addLayer({id:'lakes',type:'fill',source:'lakes',paint:{'fill-color':'#265f7f','fill-opacity':0.5}});
  map.addLayer({id:'lakes-line',type:'line',source:'lakes',paint:{'line-color':'#7fc4e8','line-width':0.7,'line-opacity':0.8}});
  map.addLayer({id:'rivers',type:'line',source:'rivers',
    paint:{'line-color':['case',['==',['get','cls'],'river'],'#3f93c8','#6fc0e8'],'line-opacity':0.92,
      'line-width':['interpolate',['linear'],['zoom'],
        8,['case',['==',['get','cls'],'river'],1.0,0.35],
        11,['case',['==',['get','cls'],'river'],2.4,1.1],
        14,['case',['==',['get','cls'],'river'],4.5,2.2]]}});

  // roads + rail (OSM) — access is critical for a hunt map (pack-in, staging, pressure)
  map.addSource('infra',{type:'geojson',data:S.infra});
  map.addLayer({id:'roads-case',type:'line',source:'infra',filter:['==',['get','t'],'road'],
    paint:{'line-color':'#20160a','line-width':['interpolate',['linear'],['zoom'],8,1.6,12,3.4,15,5.5],'line-opacity':0.55}});
  map.addLayer({id:'roads',type:'line',source:'infra',filter:['==',['get','t'],'road'],
    paint:{'line-color':'#f0dfb0','line-width':['interpolate',['linear'],['zoom'],8,0.8,12,2,15,3.4],'line-opacity':0.95}});
  map.addLayer({id:'rail',type:'line',source:'infra',filter:['==',['get','t'],'rail'],
    paint:{'line-color':'#c7cdc3','line-width':1.5,'line-dasharray':[2,3],'line-opacity':0.9}});

  map.addLayer({id:'areas-fill',type:'fill',source:'areas',
    paint:{'fill-color':['case',['<=',['get','rank'],2],'#2fbf5b','#e2c044'],'fill-opacity':0.10}});
  map.addLayer({id:'areas-line',type:'line',source:'areas',
    paint:{'line-color':'#ffffff','line-width':2,'line-opacity':0.9,'line-dasharray':[3,2]}});
  map.addLayer({id:'packin',type:'line',source:'packin',
    paint:{'line-color':'#b98a3e','line-width':1.6,'line-dasharray':[2,2],'line-opacity':0.75}});
  // thermal-drift arrow field (off by default; toggle in tools)
  if(!map.hasImage('thermal-arrow')) map.addImage('thermal-arrow',arrowIcon(),{pixelRatio:2});
  map.addSource('thermal',{type:'geojson',data:fc([])});
  map.addLayer({id:'thermal',type:'symbol',source:'thermal',
    layout:{visibility:'none','icon-image':'thermal-arrow','icon-rotate':['get','brg'],
      'icon-size':['interpolate',['linear'],['zoom'],8,0.6,11,0.9,14,1.3],'icon-allow-overlap':true,'icon-rotation-alignment':'map'},
    paint:{'icon-opacity':0.9}});
  // caller/shooter pairs: the shooter sets up ~70 m downwind of each calling
  // station, because a bull circles downwind to scent-check before showing.
  map.addSource('shooterLines',{type:'geojson',data:fc([])});
  map.addSource('shooters',{type:'geojson',data:fc([])});
  map.addLayer({id:'shooterLines',type:'line',source:'shooterLines',
    paint:{'line-color':'#e6e9e3','line-width':1.2,'line-dasharray':[2,2],'line-opacity':0.85}});
  map.addLayer({id:'shooters',type:'circle',source:'shooters',
    paint:{'circle-radius':['interpolate',['linear'],['zoom'],9,4,12,7,15,10],'circle-color':'#0b0f0d','circle-stroke-color':'#e6e9e3','circle-stroke-width':2.2}});
  map.addLayer({id:'shooters-label',type:'symbol',source:'shooters',minzoom:10,
    layout:{'text-field':'SHOOTER','text-size':10,'text-offset':[0,-1.4],'text-font':['Open Sans Bold'],'text-allow-overlap':true},
    paint:{'text-color':'#e6e9e3','text-halo-color':'#0b0f0d','text-halo-width':1.5}});
  const SITE_SZ=['interpolate',['linear'],['zoom'],8,0.7,11,1.05,13,1.45,15,1.9];
  map.addLayer({id:'sites',type:'symbol',source:'sites',
    layout:{'icon-image':['get','type'],'icon-size':SITE_SZ,'icon-allow-overlap':true}});
  map.addLayer({id:'staging',type:'symbol',source:'staging',
    layout:{'icon-image':'parking','icon-size':['interpolate',['linear'],['zoom'],8,0.8,11,1.15,15,2],'icon-allow-overlap':true}});
  map.addLayer({id:'camps',type:'symbol',source:'camps',
    layout:{'icon-image':'base_camp','icon-size':['interpolate',['linear'],['zoom'],8,0.9,11,1.25,15,2],'icon-allow-overlap':true,
      'text-field':['get','id'],'text-offset':[0,1.4],'text-size':12,'text-font':['Open Sans Bold']},
    paint:{'text-color':'#e6c98a','text-halo-color':'#0b0f0d','text-halo-width':1.5}});
  map.addLayer({id:'area-badges',type:'symbol',source:'areaLabels',
    layout:{'text-field':['to-string',['get','rank']],'text-size':15,'text-font':['Open Sans Bold'],'text-allow-overlap':true},
    paint:{'text-color':'#fff','text-halo-color':['case',['get','top'],'#127a2e','#111'],'text-halo-width':2.5}});
  // river crossings on routes — red = river (needs a boat), amber = fordable stream
  map.addLayer({id:'crossings',type:'circle',source:'crossings',
    paint:{'circle-radius':6.5,
      'circle-color':['case',['==',['get','kind'],'river'],'#e2231a','#ffd24a'],
      'circle-stroke-color':'#0b0f0d','circle-stroke-width':2.5}});

  // interactions
  map.on('click','huntZones',e=>{ const p=e.features[0].properties; const cl=HUNT_CLS[p.cls]||{};
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(`<h4><span style="color:${cl.c}">●</span> ${cl.label||p.cls} · ${p.area_km2} km²</h4><div class="s">${HUNT_WHY[p.cls]||''}</div>`).addTo(map);});
  map.on('click','browseZones',e=>{ const p=e.features[0].properties;
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(`<h4>${p.type} · ${p.area_km2} km²</h4><div class="s">${p.what}</div><div class="s" style="margin-top:4px"><b>When:</b> ${p.when}</div>`).addTo(map);});
  map.on('click','refugeZones',e=>{ new maplibregl.Popup().setLngLat(e.lngLat)
    .setHTML(`<h4><span style="color:${REFUGE_COL}">▨</span> Thermal refuge · ${e.features[0].properties.area_km2} km²</h4><div class="s">${ZONE_WHY.refuge}</div>`).addTo(map);});
  map.on('click','funnelZones',e=>{ new maplibregl.Popup().setLngLat(e.lngLat)
    .setHTML(`<h4><span style="color:${FUNNEL_COL}">▨</span> Funnel / pass · ${e.features[0].properties.area_km2} km²</h4><div class="s">${ZONE_WHY.funnel}</div>`).addTo(map);});
  ['huntZones','browseZones','refugeZones','funnelZones'].forEach(l=>{map.on('mouseenter',l,()=>map.getCanvas().style.cursor='pointer');map.on('mouseleave',l,()=>map.getCanvas().style.cursor='');});
  map.on('click','crossings',e=>{ const p=e.features[0].properties;
    const river=p.kind==='river', noBoat=SETUP.watercraft==='none';
    const msg = river ? (noBoat
        ? '<b style="color:#f79">Impassable on foot.</b> This route crosses a river and you have no boat — reroute or add a boat in Setup.'
        : 'River crossing — take the '+(SETUP.watercraft==='motor'?'motorboat':'canoe')+' across here.')
      : 'Small stream — fordable on foot; watch footing.';
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML('<h4>'+(river?'River':'Stream')+' crossing</h4><div class="s">'+msg+'</div>').addTo(map);});
  map.on('click','areas-fill',e=>selectArea(e.features[0].properties.rank));
  map.on('click','sites',e=>{const p=e.features[0].properties;
    const scent = p.type==='saline_blind'
      ? '<div class="s" style="color:#e0a05a;margin-top:4px">⚠ Mineral/saline &amp; scents are regulated and may be prohibited in this zone — verify Zone '+((DOC.legal||{}).zone||'?')+' rules before using any attractant.</div>' : '';
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
      `<h4>${LABELS[p.type]||p.type}</h4>${p.when?('<div class="s">'+p.when+'</div>'):''}`+
      (p.windnote?('<div class="s">'+p.windnote+'</div>'):'')+scent).addTo(map);});
  ['areas-fill','sites','camps','staging'].forEach(l=>{
    map.on('mouseenter',l,()=>map.getCanvas().style.cursor='pointer');
    map.on('mouseleave',l,()=>map.getCanvas().style.cursor='');});

  buildShooters(); buildThermal();
  buildPanel(); buildWeather(); buildLegend(); buildTools();
  setVis(LYR_MAP.roads,true); setVis(LYR_MAP.boundaries,true);   // roads + borders on by default in every view
  renderSetup(); renderBrief(); wireTabs(); initPlans(); initExport(); setTab('overview');
  map.fitBounds(bbox(DOC.areas),{padding:{top:80,left:400,right:200,bottom:120}});
}

/* wait for style, then init once */
let _inited=false;
function go(){ if(_inited)return; _inited=true; init();
  [0,200,600,1200].forEach(t=>setTimeout(()=>map.resize(),t)); }
map.on('load',go);
map.on('styledata',()=>{ if(map.isStyleLoaded()) go(); });
window.addEventListener('resize',()=>map.resize());

/* ---------------- overview panel ---------------- */
function buildPanel(){
  const g=DOC.legal;
  document.getElementById('gate').innerHTML=
    `<span class="diy ${g.diy_possible?'ok':'no'}">${g.diy_possible?'DIY POSSIBLE':'RESTRICTED'}</span>
     &nbsp;Zone ${g.zone} · ${g.north_of_52?'N':'S'} of 52°N · ${(g.huntable_tenures||[]).join(', ')||'—'}
     ${DOC.confidence?`<span class="pill" style="background:#20303a;color:#8fd0f2;float:right">confidence ${Math.round(DOC.confidence.score*100)}%</span>`:''}
     <div class="flag">${(g.flags||[]).slice(0,2).join('<br>')}</div>`;
  const m=DOC.methodology;
  document.getElementById('method').innerHTML=
    `<details><summary>What I'm looking for</summary><p>${m.summary}</p>
     <b>Weighted:</b> ${(m.factors_weighted||[]).join('; ')}</details>`;
  let html='';
  DOC.camps.forEach(c=>{
    html+=`<div class="camp">Camp ${c.id} · areas ${c.member_areas.join(', ')} · pack-in ≤ ${km(c.max_packin_km)}</div>`;
    DOC.areas.filter(a=>a.camp===c.id).sort((x,y)=>x.rank-y.rank).forEach(a=>{html+=areaCard(a);});
  });
  const list=document.getElementById('list'); list.innerHTML=html;
  list.querySelectorAll('.card').forEach(el=>el.onclick=()=>selectArea(+el.dataset.rank));
}
function areaCard(a){
  const pros=(a.pros||[]).slice(0,3).map(p=>`<span class="pill pro">${p}</span>`).join('');
  const cf=a.conf?`<span class="pill" style="background:#20303a;color:#8fd0f2">conf ${Math.round(a.conf.score*100)}%</span>`:'';
  const dr=(a.stats||{}).dist_road_m||0;
  const far=SETUP.huntStyle==='vehicle' && dr>reachKm()*1000;
  const farPill=far?`<span class="pill con">beyond day-return (${km(dr/1000)} to road)</span>`:'';
  return `<div class="card ${far?'dim':''}" data-rank="${a.rank}"><div class="top">
    <div class="badge ${a.rank<=2?'top':''}">${a.rank}</div>
    <div><div><b>Area ${a.rank}</b> · ${a.area_km2} km²</div>
    <div class="meta">huntability ${a.huntability} · camp ${a.camp}</div></div></div>
    <div class="why">${(a.why||'').slice(0,150)}</div><div>${pros}${cf}${farPill}</div></div>`;
}

/* ---------------- drilldown (area detail) ---------------- */
function selectArea(rank){
  const a=DOC.areas.find(x=>x.rank===rank); if(!a)return;
  lastSel=rank;
  if(curTab==='setup'||curTab==='brief') setTab('overview');   // stay on field/overview otherwise
  if(curTab==='field') enterDeep(rank);                        // switch the deep re-analysis too
  document.getElementById('list').classList.add('hidden');
  document.getElementById('method').classList.add('hidden');
  const d=document.getElementById('detail'); d.classList.remove('hidden');
  const wps=DOC.waypoints.filter(w=>w.properties.focus_area===rank && SITE_TYPES.includes(w.type));
  const st=a.stats||{};
  const rutT=(DOC.rut&&DOC.rut.targets&&DOC.rut.targets[0])||null;
  d.innerHTML=`<div class="back">← all areas</div>
    <h2><span class="badge ${rank<=2?'top':''}" style="display:inline-flex;vertical-align:middle">${rank}</span> Area ${rank} · ${a.area_km2} km²</h2>
    <div class="meta">huntability ${a.huntability} · camp ${a.camp} · ${a.centroid[1].toFixed(4)}, ${a.centroid[0].toFixed(4)}</div>
    <p class="why">${a.why||''}</p>
    <div class="dd"><b>Why it scored</b>
      <div class="ddgrid">
        ${st.dist_water_m!=null?`<div><span>water</span>${metres(st.dist_water_m)}</div>`:''}
        ${st.dist_road_m!=null?`<div><span>to road</span>${km(st.dist_road_m/1000)}</div>`:''}
        ${st.mean_slope_deg!=null?`<div><span>slope</span>${st.mean_slope_deg}°</div>`:''}
        ${a.conf?`<div><span>confidence</span>${Math.round(a.conf.score*100)}% ${a.conf.band}</div>`:''}
      </div>
      ${a.conf&&a.conf.drivers?`<div class="s" style="margin-top:4px">${a.conf.drivers.join(' · ')}</div>`:''}
    </div>
    <div><b>Pros</b><br>${(a.pros||[]).map(p=>`<span class="pill pro">${p}</span>`).join('')}</div>
    <div style="margin-top:6px"><b>Watch-outs</b><br>${(a.cons||[]).map(p=>`<span class="pill con">${p}</span>`).join('')}</div>
    ${rutT?`<div class="dd" style="margin-top:8px"><b>Rut</b> — ${rutT.date}: <b style="color:#f2b98a">${rutT.phase}</b> (${Math.round(rutT.responsiveness*100)}% responsive). ${rutT.guidance}${rutT.weather_note?` <span class="s">Weather: ${rutT.weather_note}.</span>`:''}<div class="s" style="margin-top:3px;color:#c99">Trigger-driven — a warm front kills the response, a hard frost fires it up.</div></div>`:''}
    <h3 style="margin:12px 0 2px">Sites (${wps.length})</h3>
    ${wps.map(w=>{const ow=w.properties.optimal_wind||{};return `<div class="wp">
      <span class="dot" style="background:${COLORS[w.type]||'#ccc'}"></span>
      <div><div class="t">${LABELS[w.type]||w.type}</div>
      <div class="s">${w.properties.when||ow.note||('elev '+(w.properties.elev_m||'?')+' m')}</div></div></div>`;}).join('')}`;
  d.querySelector('.back').onclick=()=>{
    d.classList.add('hidden');
    document.getElementById('list').classList.remove('hidden');
    document.getElementById('method').classList.remove('hidden');};
  map.flyTo({center:a.centroid,zoom:12.2,pitch:map.getPitch()});
}

/* ---------------- weather / wind calendar + hour scrubber ---------------- */
function buildWeather(){
  const w=DOC.weather, el=document.getElementById('weather');
  if(!w||!w.days||!w.days.length){el.style.display='none';return;}
  let html='<div class="days">';
  w.days.forEach((d,i)=>{html+=`<div class="day" data-i="${i}"><div class="d">${d.date.slice(5)}</div>
    <div class="w">${d.wind_from_compass||'—'} ${d.wind_kmh?Math.round(d.wind_kmh):''}</div>
    <div class="w">${d.t_max_c!=null?Math.round(d.t_max_c)+'°':''}</div></div>`;});
  html+='</div>';
  // hour scrubber → behavioural heat
  if(DOC.behavior){
    html+=`<div class="hourrow"><input id="hour" type="range" min="4" max="21" step="0.5" value="6.5">
      <span id="hourlbl" class="s"></span></div>`;
  }
  html+=`<div class="note">Pick a day → sites turn <b style="color:#2fbf5b">green</b> when the forecast wind fits their approach`+
    (w.days[0].is_proxy?' — but this is a <b>prior-year proxy</b> (hunt is months out), treat as rough':' (forecast — verify on the ground)')+
    `. At <b>first &amp; last light the thermal drift usually wins</b>, not the forecast wind — use the Thermal-drift layer for those windows.</div>`;
  el.innerHTML=html;
  el.querySelectorAll('.day').forEach(del=>del.onclick=()=>{
    el.querySelectorAll('.day').forEach(x=>x.classList.remove('sel')); del.classList.add('sel');
    selectedDay=w.days[+del.dataset.i]; applyWind();});
  const hr=document.getElementById('hour');
  if(hr) hr.oninput=()=>updateHour(+hr.value);
  if(hr) updateHour(6.5);
}
function applyWind(){
  window._sites.forEach(f=>f.properties.windok=windState(f));
  // recolour site halos via a data-driven approach: use a circle underlay
  const src=map.getSource('sites'); if(src) src.setData(fc(window._sites));
  buildShooters();   // shooter sits downwind of the chosen day's wind
}
function updateHour(h){
  const lbl=document.getElementById('hourlbl');
  const sr=(DOC.grid&&6.3), ss=18.5;
  let period='dawn', src='feed';
  const em=(DOC.behavior&&DOC.behavior.expected_midday)||{};
  const warm=(em.refuge_weight||0)>=0.5;
  if(h<6.0){period='pre-dawn';src='feed';}
  else if(h<9.0){period='first light — feeding';src='feed';}
  else if(h<16.0){period=warm?'midday — thermal refuge':'midday — still feeding';src=warm?'midday_warm':'midday_cool';}
  else if(h<20.5){period='last light — feeding';src='feed';}
  else {period='night';src='feed';}
  if(lbl) lbl.textContent=`${Math.floor(h)}:${String(Math.round((h%1)*60)).padStart(2,'0')} · ${period}`;
  if(HEAT.source!==src){ HEAT.source=src; updateHeat(); }
  updateThermal(h);
  const tl=document.getElementById('thermLbl');
  if(tl) tl.textContent=thermalRising(h)?'· ↑ upslope':'· ↓ downslope';
}

/* ---------------- legend (per-type show/hide) ---------------- */
function buildLegend(){
  const el=document.getElementById('legend');
  let h='<b>Sites</b> <span class="s">(click to hide)</span>';
  SITE_TYPES.forEach(t=>h+=`<div class="row tog" data-t="${t}"><i style="background:${COLORS[t]}"></i>${LABELS[t]}</div>`);
  h+=`<div class="row tog" data-t="base_camp"><i style="background:${COLORS.base_camp}"></i>Base camp</div>`;
  h+=`<div class="row tog" data-t="parking"><i style="background:${COLORS.parking}"></i>Vehicle staging</div>`;
  h+='<div class="row s" style="color:#9fb;margin-top:4px">green ring = wind-right for the chosen day</div>';
  el.innerHTML=h;
  el.querySelectorAll('.tog').forEach(r=>r.onclick=()=>toggleType(r.dataset.t,r));
}
function toggleType(t,row){
  hideTypes[t]=!hideTypes[t]; row.style.opacity=hideTypes[t]?0.4:1;
  const vis=hideTypes[t]?'none':'visible';
  if(t==='base_camp'){ ['camps'].forEach(l=>map.getLayer(l)&&map.setLayoutProperty(l,'visibility',vis)); return; }
  if(t==='parking'){ map.getLayer('staging')&&map.setLayoutProperty('staging','visibility',vis); return; }
  // site type: filter the sites layer
  const active=SITE_TYPES.filter(x=>!hideTypes[x]);
  map.setFilter('sites',['in',['get','type'],['literal',active]]);
  if(t==='rut_calling') buildShooters();   // show/hide the paired shooters too
}

/* ---------------- tools panel ---------------- */
function setVis(ids,on){(ids||[]).forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',on?'visible':'none'));}
const LYR_MAP={areas:['areas-fill','areas-line','area-badges'],sites:['sites'],camps2:['camps','staging'],
  packin:['packin'],water:['lakes','lakes-line','rivers'],crossings:['crossings'],
  roads:['roads','roads-case','rail','trans'],   // 'trans' = global roads overlay, always available regardless of analysis
  boundaries:['boundaries'],   // provincial/state/national boundaries + places (map level, independent of analysis)
  shooters:['shooters','shooters-label','shooterLines'],thermal:['thermal']};
function buildTools(){
  const t=document.getElementById('tools');       // Map / basemap only
  const hp=document.getElementById('hunting');     // Hunting layers (zones + sites)
  const grp=(title,html)=>`<div class="tgroup"><div class="tlabel">${title}</div><div class="tbody">${html}</div></div>`;
  t.innerHTML =
      `<div class="phead"><span class="ptitle">Basemap</span><button class="panelMin" title="Collapse">–</button></div>`
    + `<div class="pbody">`
    + grp('Map',
      `<div class="chips">${BASEMAPS.map(b=>`<button data-base="${b}" class="${curBase===b?'on':''}">${BASE_LABEL[b]}</button>`).join('')}</div>
       <button id="btn3d" class="wbtn">3D terrain</button>`)
    + `</div>`;
  hp.innerHTML =
      `<div class="hhead"><span class="ptitle">Hunting layers</span><button class="panelMin" title="Collapse">–</button></div>`
    + `<div class="pbody">`
    + grp('Model zones',
      `<label><input type="checkbox" data-hz="high" checked> <b style="color:${HUNT_CLS.high.c}">■</b> High likelihood</label>
       <label><input type="checkbox" data-hz="medium" checked> <b style="color:${HUNT_CLS.medium.c}">■</b> Medium</label>
       <label><input type="checkbox" data-hz="low" checked> <b style="color:${HUNT_CLS.low.c}">■</b> Low</label>
       <label><input id="refugeOn" type="checkbox" checked> <b style="color:${REFUGE_COL}">▨</b> Thermal refuge</label>
       <label><input id="funnelOn" type="checkbox" checked> <b style="color:${FUNNEL_COL}">▨</b> Funnels / passes</label>
       <label><input id="browseOn" type="checkbox"> <b style="color:#22a884">▨</b> Browse / feeding</label>`)
    + grp('Sites &amp; features',
      `<label><input type="checkbox" data-lyr="sites" checked> Hunt sites (calling/glassing…)</label>
       <label><input type="checkbox" data-lyr="camps2" checked> Camps &amp; staging</label>
       <label><input type="checkbox" data-lyr="packin" checked> Pack-in routes</label>
       <label><input type="checkbox" data-lyr="shooters" checked> Caller / shooter</label>
       <label><input type="checkbox" data-lyr="areas" checked> Focus-area outlines</label>
       <label><input type="checkbox" data-lyr="thermal"> Thermal drift <span class="s" id="thermLbl"></span></label>`)
    + grp('Access &amp; hydro',
      `<label><input type="checkbox" data-lyr="roads" checked> Roads &amp; rail</label>
       <label><input type="checkbox" data-lyr="boundaries" checked> Borders &amp; places</label>
       <label><input type="checkbox" data-lyr="water" checked> Rivers &amp; lakes</label>
       <label><input type="checkbox" data-lyr="crossings" checked> River crossings</label>`)
    + `</div>`;

  // collapse each panel down to a small square (click the – / ☰ button)
  [t,hp].forEach(pnl=>{const b=pnl.querySelector('.panelMin'); if(b) b.onclick=()=>{
    const m=pnl.classList.toggle('mini'); b.textContent=m?'☰':'–'; b.title=m?'Expand':'Collapse';};});
  t.querySelectorAll('[data-base]').forEach(b=>b.onclick=()=>switchBase(b.dataset.base));
  let on3d=false;
  document.getElementById('btn3d').onclick=e=>{on3d=!on3d;e.target.classList.toggle('on',on3d);
    if(on3d){map.setTerrain({source:'dem',exaggeration:1.4});map.easeTo({pitch:60});}
    else{map.setTerrain(null);map.easeTo({pitch:0});}};
  const applyHZ=()=>{const on=[...hp.querySelectorAll('[data-hz]')].filter(c=>c.checked).map(c=>c.dataset.hz);
    map.setFilter('huntZones',['in',['get','cls'],['literal',on.length?on:['__none__']]]);
    map.setFilter('huntZones-line',['in',['get','cls'],['literal',on.length?on:['__none__']]]);};
  hp.querySelectorAll('[data-hz]').forEach(cb=>cb.onchange=applyHZ);
  document.getElementById('refugeOn').onchange=e=>setVis(['refugeZones','refugeZones-line'],e.target.checked);
  document.getElementById('funnelOn').onchange=e=>setVis(['funnelZones','funnelZones-line'],e.target.checked);
  document.getElementById('browseOn').onchange=e=>{showBrowse=e.target.checked;setVis(['browseZones','browseZones-line'],showBrowse);};
  hp.querySelectorAll('[data-lyr]').forEach(cb=>cb.onchange=()=>{
    setVis(LYR_MAP[cb.dataset.lyr],cb.checked);
    if(cb.dataset.lyr==='thermal'&&cb.checked){const hr=document.getElementById('hour');updateThermal(hr?+hr.value:12);}});
  [t,hp].forEach(pnl=>pnl.querySelectorAll('.tgroup .tlabel').forEach(lbl=>lbl.onclick=()=>lbl.parentElement.classList.toggle('collapsed')));

  setupDraw();          // annotation source/layers + map handlers (once)
  buildDrawToolbar();   // the separate floating draw/measure strip
}
function buildDrawToolbar(){
  const d=document.getElementById('drawtools'); if(!d) return;
  d.innerHTML=`<div class="dt-title">TOOLS</div>
    <button data-tool="dist" title="Measure distance">📏</button>
    <button data-tool="area" title="Measure area">▱</button>
    <button data-tool="line" title="Draw line">✎</button>
    <button data-tool="route" title="Build route">➤</button>
    <button data-tool="waypoint" title="Drop waypoint">📍</button>
    <button id="drawClear" title="Clear drawings">✕</button>
    <div class="dt-hint" id="drawhint"></div>`;
  d.querySelectorAll('button[data-tool]').forEach(b=>b.onclick=()=>setDrawTool(b.dataset.tool));
  document.getElementById('drawClear').onclick=()=>{clearDraw();setDrawTool(null);};
}
/* ---- OnX-style field tools: distance / line / area / route / waypoint ---- */
let drawTool=null, drawPts=[], drawWpts=[], drawSaved=[];
function polyKm(pts){let d=0;for(let i=1;i<pts.length;i++)d+=hav(pts[i-1],pts[i]);return d;}
function ringKm2(ring){ // spherical polygon area
  if(ring.length<3)return 0; const R=6371,d2r=Math.PI/180; let s=0;
  for(let i=0;i<ring.length;i++){const p=ring[i],q=ring[(i+1)%ring.length];
    s+=(q[0]-p[0])*d2r*(2+Math.sin(p[1]*d2r)+Math.sin(q[1]*d2r));}
  return Math.abs(s*R*R/2);
}
function areaFmt(km2){ return UNITS==='imperial'?(km2*0.386102).toFixed(2)+' mi²':km2.toFixed(2)+' km²'; }
function setupDraw(){
  map.addSource('annot',{type:'geojson',data:fc([])});
  map.addLayer({id:'annot-fill',type:'fill',source:'annot',filter:['==','$type','Polygon'],
    paint:{'fill-color':'#f0c069','fill-opacity':0.18}});
  map.addLayer({id:'annot-line',type:'line',source:'annot',filter:['!=','$type','Point'],
    paint:{'line-color':'#fff','line-width':2.2,'line-dasharray':[2,1.5]}});
  map.addLayer({id:'annot-pt',type:'circle',source:'annot',filter:['==','$type','Point'],
    paint:{'circle-radius':5,'circle-color':'#f0c069','circle-stroke-color':'#0b0f0d','circle-stroke-width':2}});
  map.addLayer({id:'annot-label',type:'symbol',source:'annot',filter:['has','label'],
    layout:{'text-field':['get','label'],'text-size':12,'text-offset':[0,-1.2],'text-font':['Open Sans Bold'],'text-allow-overlap':true},
    paint:{'text-color':'#ffe6a8','text-halo-color':'#0b0f0d','text-halo-width':2}});
  map.on('click',onDrawClick);
  map.on('dblclick',e=>{ if(drawTool&&drawTool!=='waypoint'){ e.preventDefault(); finishDraw(); } });
}
function onDrawClick(e){
  if(!drawTool) return;
  const ll=[e.lngLat.lng,e.lngLat.lat];
  if(drawTool==='waypoint'){ drawSaved.push({type:'Feature',geometry:{type:'Point',coordinates:ll},
      properties:{label:'WP'+(drawSaved.filter(f=>f.geometry.type==='Point').length+1)}}); renderAnnot(); return; }
  drawPts.push(ll); renderAnnot();
}
function finishDraw(){
  if(drawPts.length>=2){
    if(drawTool==='area'){ const ring=drawPts.concat([drawPts[0]]);
      drawSaved.push({type:'Feature',geometry:{type:'Polygon',coordinates:[ring]},properties:{label:areaFmt(ringKm2(drawPts))}});}
    else { drawSaved.push({type:'Feature',geometry:{type:'LineString',coordinates:drawPts.slice()},
      properties:{label:(drawTool==='route'?'Route ':'')+km(polyKm(drawPts))}});}
  }
  drawPts=[]; renderAnnot();
}
function renderAnnot(){
  const feats=drawSaved.slice();
  if(drawPts.length){
    const isArea=drawTool==='area';
    const geom=isArea&&drawPts.length>=3?{type:'Polygon',coordinates:[drawPts.concat([drawPts[0]])]}
      :{type:'LineString',coordinates:drawPts};
    const lab=isArea?(drawPts.length>=3?areaFmt(ringKm2(drawPts)):'')
      :(drawPts.length>=2?km(polyKm(drawPts)):'');
    feats.push({type:'Feature',geometry:geom,properties:lab?{label:lab}:{}});
    drawPts.forEach(p=>feats.push({type:'Feature',geometry:{type:'Point',coordinates:p},properties:{}}));
  }
  map.getSource('annot').setData(fc(feats));
}
function setDrawTool(t){
  finishDraw();                         // commit any in-progress geometry
  drawTool=(drawTool===t)?null:t; drawPts=[];
  document.querySelectorAll('#drawtools button[data-tool]').forEach(b=>b.classList.toggle('on',b.dataset.tool===drawTool));
  const dtb=document.getElementById('drawtools'); if(dtb) dtb.classList.toggle('active',!!drawTool);
  map.getCanvas().style.cursor=drawTool?'crosshair':'';
  map.doubleClickZoom[drawTool?'disable':'enable']();
  const hint=document.getElementById('drawhint');
  if(hint) hint.textContent=drawTool?({dist:'Click points; double-click to finish. Shows distance.',
    line:'Click points; double-click to finish a line.',route:'Click waypoints; double-click to finish the route.',
    area:'Click a boundary; double-click to close. Shows area.',waypoint:'Click to drop waypoints.'})[drawTool]:'';
  renderAnnot();
}
function clearDraw(){ drawSaved=[]; drawPts=[]; if(map.getSource('annot')) map.getSource('annot').setData(fc([])); }
function destPoint(lon,lat,brgDeg,km){const R=6371,d2r=Math.PI/180,br=brgDeg*d2r,la1=lat*d2r,lo1=lon*d2r;
  const la2=Math.asin(Math.sin(la1)*Math.cos(km/R)+Math.cos(la1)*Math.sin(km/R)*Math.cos(br));
  const lo2=lo1+Math.atan2(Math.sin(br)*Math.sin(km/R)*Math.cos(la1),Math.cos(km/R)-Math.sin(la1)*Math.sin(la2));
  return [lo2/d2r,la2/d2r];}
function buildShooters(){
  if(!map.getSource('shooters'))return;
  const wdir=(selectedDay&&selectedDay.wind_from_deg!=null)?selectedDay.wind_from_deg:270;
  const down=(wdir+180)%360;   // shooter sits downwind of the caller
  const pts=[],lines=[];
  (window._sites||[]).filter(f=>f.properties.type==='rut_calling'&&!hideTypes.rut_calling).forEach(f=>{
    const c=f.geometry.coordinates, s=destPoint(c[0],c[1],down,0.07);
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:s},properties:{}});
    lines.push({type:'Feature',geometry:{type:'LineString',coordinates:[c,s]},properties:{}});});
  map.getSource('shooters').setData(fc(pts));
  map.getSource('shooterLines').setData(fc(lines));
}
/* thermal drift: air drains DOWNSLOPE at night/evening (katabatic) and rises
   UPSLOPE through a warming day (anabatic). Arrow field from the elevation grid. */
function arrowIcon(){const S=30,cv=document.createElement('canvas');cv.width=cv.height=S;const c=cv.getContext('2d');
  c.translate(S/2,S/2);c.strokeStyle='#ffd9a0';c.fillStyle='#ffd9a0';c.lineWidth=2.5;c.lineCap='round';c.lineJoin='round';
  c.beginPath();c.moveTo(0,10);c.lineTo(0,-7);c.stroke();
  c.beginPath();c.moveTo(0,-12);c.lineTo(-5,-4);c.lineTo(5,-4);c.closePath();c.fill();
  return {width:S,height:S,data:c.getImageData(0,0,S,S).data};}
function elevAt(gi,gj){const e=DOC.elev;gi=Math.max(0,Math.min(e.gw-1,gi));gj=Math.max(0,Math.min(e.gh-1,gj));return e.v[gj*e.gw+gi];}
function buildThermal(){
  const e=DOC.elev,b=DOC.box; if(!e||!map.getSource('thermal'))return;
  const step=6,pts=[];
  for(let gj=step;gj<e.gh-step;gj+=step)for(let gi=step;gi<e.gw-step;gi+=step){
    const lon=b.w+(gi+0.5)/e.gw*(b.e-b.w), lat=b.n-(gj+0.5)/e.gh*(b.n-b.s);
    const gx=elevAt(gi+1,gj)-elevAt(gi-1,gj);      // east-west uphill component
    const gyN=elevAt(gi,gj-1)-elevAt(gi,gj+1);     // north-south uphill component (row 0 = north)
    if(Math.hypot(gx,gyN)<1.2) continue;           // skip flats
    const upAz=(Math.atan2(gx,gyN)*180/Math.PI+360)%360;
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:[lon,lat]},properties:{brg:Math.round((upAz+180)%360)}}); // downslope (drainage)
  }
  map.getSource('thermal').setData(fc(pts));
}
function thermalRising(h){ return h>=8 && h<=17; }   // warming day = upslope; else drainage
function updateThermal(h){
  if(!map.getLayer('thermal'))return;
  const off=thermalRising(h)?180:0;   // brg is drainage; +180 = upslope by day
  map.setLayoutProperty('thermal','icon-rotate',['+',['get','brg'],off]);
}
function hav(a,b){const R=6371,dLat=(b[1]-a[1])*Math.PI/180,dLon=(b[0]-a[0])*Math.PI/180,
  s=Math.sin(dLat/2)**2+Math.cos(a[1]*Math.PI/180)*Math.cos(b[1]*Math.PI/180)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(s));}

/* ---------------- Setup (redesigned) ---------------- */
let draft={center:[DOC.meta.center.lon,DOC.meta.center.lat],radius:DOC.meta.radius_km||50,
  walkAccess:2.0,walkHunt:4.0,leaving:'Baie-Comeau',
  dates:((DOC.meta&&DOC.meta.target_dates)||['2026-09-25','2026-10-05']).slice()};
function renderSetup(){
  const el=document.getElementById('setup');
  el.innerHTML=`
    <h2>Scout setup</h2>

    <div class="fld">
      <label>Where to hunt</label>
      <div class="searchrow"><input id="placeSearch" placeholder="Search a place, lake, mine…">
        <button id="searchBtn">Search</button></div>
      <div id="searchRes" class="results"></div>
      <button id="dragBox" class="big">▛ Drag a box on the map</button>
      <div class="coordline"><span class="s">or paste coordinates</span>
        <input id="coord" placeholder="lat, lon" value="${draft.center[1].toFixed(4)}, ${draft.center[0].toFixed(4)}"></div>
    </div>

    <div class="fld"><label>Hunt dates <span class="s">— drives rut timing, weather &amp; behaviour</span></label>
      <div class="numrow"><input id="dateStart" type="date" value="${draft.dates[0]}">
        <span>→</span><input id="dateEnd" type="date" value="${draft.dates[1]}"></div></div>

    <div class="fld"><label>Species</label>
      <div class="radii"><button class="on" disabled>Moose</button></div></div>

    <div class="fld"><label>Search radius — <b id="radVal">${Math.round(toU(draft.radius))} ${unitBig()}</b></label>
      <input id="radius" type="range" min="${UNITS==='imperial'?3:5}" max="${UNITS==='imperial'?75:120}" step="1" value="${Math.round(toU(draft.radius))}"></div>

    <div class="fld"><label>How you'll hunt</label>
      <div class="radii wide"><button id="hsSpike" class="${SETUP.huntStyle==='spike'?'on':''}">Spike camp in the woods</button>
        <button id="hsVeh" class="${SETUP.huntStyle==='vehicle'?'on':''}">Return to vehicle nightly</button></div>
      <div class="s" id="hsNote"></div></div>

    <div class="fld"><label>Watercraft</label>
      <div class="radii"><button id="wcNone" class="${SETUP.watercraft==='none'?'on':''}">No boat</button>
        <button id="wcCanoe" class="${SETUP.watercraft==='canoe'?'on':''}">Canoe</button>
        <button id="wcMotor" class="${SETUP.watercraft==='motor'?'on':''}">Motorboat</button></div></div>

    <div class="fld"><label>Walk from access → base camp (max)</label>
      <div class="numrow"><input id="walkAccess" type="number" step="0.1" value="${toU(draft.walkAccess).toFixed(1)}"><span id="uAccess">${unitBig()}</span></div></div>
    <div class="fld"><label>Walk from base camp → hunting (max)</label>
      <div class="numrow"><input id="walkHunt" type="number" step="0.1" value="${toU(draft.walkHunt).toFixed(1)}"><span id="uHunt">${unitBig()}</span></div></div>

    <div class="fld"><label>Leaving from</label>
      <div class="searchrow"><input id="leaveSearch" placeholder="Search departure town…" value="${draft.leaving}">
        <button id="leaveBtn">Search</button></div>
      <div id="leaveRes" class="results"></div></div>

    <div class="fld"><label>Units</label>
      <div class="radii"><button id="uMetric" class="${UNITS==='metric'?'on':''}">Metric (km/m)</button>
        <button id="uImperial" class="${UNITS==='imperial'?'on':''}">Imperial (mi/yd)</button></div></div>

    <div class="fld"><label>Basemap</label>
      <div class="radii">${BASEMAPS.map(b=>`<button data-base="${b}" class="${curBase===b?'on':''}">${BASE_LABEL[b]}</button>`).join('')}</div></div>

    <button id="runBtn" class="run">RUN ANALYSIS →</button>
    <div class="note">Recomputes live via the engine for the area/radius you set — takes
      ~3–5 min (it downloads terrain, imagery, land-cover &amp; hydrography for the box).
      Pick a radius of ~20 km+ so it resolves focus areas.</div>`;

  // wiring
  const doSearch=(inputId,resId,cb)=>{
    const inp=document.getElementById(inputId), res=document.getElementById(resId);
    const run=()=>geocode(inp.value).then(list=>{
      res.innerHTML=list.slice(0,5).map((r,i)=>`<div class="rres" data-i="${i}">${r.display_name}</div>`).join('');
      res.querySelectorAll('.rres').forEach(d=>d.onclick=()=>{const r=list[+d.dataset.i];res.innerHTML='';cb(r);});});
    return run;
  };
  document.getElementById('searchBtn').onclick=doSearch('placeSearch','searchRes',r=>{
    draft.center=[+r.lon,+r.lat];
    document.getElementById('coord').value=(+r.lat).toFixed(4)+', '+(+r.lon).toFixed(4);
    map.flyTo({center:draft.center,zoom:10}); drawDraft();});
  document.getElementById('leaveBtn').onclick=doSearch('leaveSearch','leaveRes',r=>{
    draft.leaving=r.display_name.split(',')[0]; document.getElementById('leaveSearch').value=draft.leaving;});
  document.getElementById('placeSearch').addEventListener('keydown',e=>{if(e.key==='Enter')document.getElementById('searchBtn').onclick();});
  document.getElementById('coord').onchange=e=>{const m=e.target.value.split(',').map(s=>parseFloat(s.trim()));
    if(m.length===2&&!isNaN(m[0])&&!isNaN(m[1])){draft.center=[m[1],m[0]];map.flyTo({center:draft.center,zoom:10});drawDraft();}};
  const rad=document.getElementById('radius');
  rad.oninput=()=>{draft.radius=fromU(+rad.value);document.getElementById('radVal').textContent=(+rad.value)+' '+unitBig();drawDraft();};
  document.getElementById('walkAccess').onchange=e=>{draft.walkAccess=fromU(+e.target.value);applyHunt();};
  document.getElementById('walkHunt').onchange=e=>draft.walkHunt=fromU(+e.target.value);
  document.getElementById('dateStart').onchange=e=>{if(e.target.value)draft.dates[0]=e.target.value;};
  document.getElementById('dateEnd').onchange=e=>{if(e.target.value)draft.dates[1]=e.target.value;};
  document.getElementById('dragBox').onclick=()=>startBoxDraw();
  document.getElementById('uMetric').onclick=()=>setUnits('metric');
  document.getElementById('uImperial').onclick=()=>setUnits('imperial');
  document.querySelectorAll('#setup [data-base]').forEach(b=>b.onclick=()=>switchBase(b.dataset.base));
  const setWC=(w)=>{SETUP.watercraft=w;
    ['wcNone','wcCanoe','wcMotor'].forEach(id=>document.getElementById(id)&&document.getElementById(id).classList.remove('on'));
    const b=document.getElementById({none:'wcNone',canoe:'wcCanoe',motor:'wcMotor'}[w]); if(b)b.classList.add('on'); applyHunt();};
  document.getElementById('wcNone').onclick=()=>setWC('none');
  document.getElementById('wcCanoe').onclick=()=>setWC('canoe');
  document.getElementById('wcMotor').onclick=()=>setWC('motor');
  const setHS=(h)=>{SETUP.huntStyle=h;
    document.getElementById('hsSpike').classList.toggle('on',h==='spike');
    document.getElementById('hsVeh').classList.toggle('on',h==='vehicle'); updateHsNote(); applyHunt();};
  document.getElementById('hsSpike').onclick=()=>setHS('spike');
  document.getElementById('hsVeh').onclick=()=>setHS('vehicle');
  document.getElementById('runBtn').onclick=()=>runAnalysis();
  updateHsNote(); drawDraft(); applyHunt();
}
function updateHsNote(){ const n=document.getElementById('hsNote'); if(!n)return;
  n.textContent=SETUP.huntStyle==='vehicle'
    ? 'Analysis favours areas within your access-walk of a road — backcountry spots are dimmed.'
    : 'Backcountry spike camps allowed — remote areas stay in play.'; }
function reachKm(){ return draft.walkAccess||2; }   // draft.walkAccess is canonical km
function applyHunt(){
  if(!map.getLayer('areas-fill'))return;
  const veh=SETUP.huntStyle==='vehicle', rk=reachKm()*1000;
  map.setPaintProperty('areas-fill','fill-opacity',
    veh?['case',['>',['coalesce',['get','dr'],0],rk],0.03,['case',['<=',['get','rank'],2],0.16,0.12]]:0.10);
  map.setPaintProperty('areas-line','line-opacity',
    veh?['case',['>',['coalesce',['get','dr'],0],rk],0.2,0.9]:0.9);
  // river crossings emphasis when no boat (they block foot routes)
  if(map.getLayer('crossings'))
    map.setPaintProperty('crossings','circle-radius',
      (SETUP.watercraft==='none')?['case',['==',['get','kind'],'river'],9,6.5]:6.5);
  if(document.getElementById('list')) buildPanel();
}
function setUnits(u){ if(u===UNITS)return; UNITS=u; renderSetup(); buildPanel(); if(!document.getElementById('detail').classList.contains('hidden')){} }
function applyDoc(newDoc){        // re-bind the whole map + panels to fresh engine data
  DOC=newDoc; window.TRANSECT_DATA=newDoc;
  const S=buildSources();
  const setD=(id,data)=>{const s=map.getSource(id); if(s&&data) s.setData(data);};
  setD('huntZones',S.huntZones); setD('browseZones',S.browseZones);
  setD('refugeZones',S.refugeZones); setD('funnelZones',S.funnelZones);
  setD('rivers',S.rivers); setD('lakes',S.lakes); setD('crossings',S.crossings); setD('infra',S.infra);
  setD('areas',S.areas); setD('areaLabels',S.areaLabels); setD('camps',S.camps);
  setD('staging',S.staging); setD('packin',fc(S.packin)); setD('sites',fc(window._sites));
  setVis(LYR_MAP.roads,true); setVis(LYR_MAP.boundaries,true);   // keep roads + borders visible after a recompute too
  window._aoi={huntZones:S.huntZones,browseZones:S.browseZones,rivers:S.rivers,lakes:S.lakes,
    refugeZones:S.refugeZones,funnelZones:S.funnelZones};
  Object.keys(AREA_DETAIL).forEach(k=>delete AREA_DETAIL[k]);   // deep detail is stale for a new AOI
  deepActive=null;
  try{buildThermal();}catch(e){} buildShooters();
  buildPanel(); buildWeather(); buildLegend(); lastSel=1;
  document.getElementById('subtitle').textContent=`${DOC.meta.title} · ${DOC.meta.species} · ${(DOC.meta.target_dates||[]).join(' – ')}`;
  const b=newDoc.box; if(b) map.fitBounds([[b.w,b.s],[b.e,b.n]],{padding:60});
}
function runAnalysis(){
  const btn=document.getElementById('runBtn');
  const setBtn=(t,dis)=>{if(btn){btn.textContent=t;btn.disabled=!!dis;}};
  const req={species:'moose',lat:draft.center[1],lon:draft.center[0],
    radius_km:Math.max(3,Math.min(120,draft.radius)),
    target_dates:(draft.dates&&draft.dates.length===2)?draft.dates:['2026-09-25','2026-10-05'],
    residency:'quebec_resident'};
  setBtn('ANALYSING… 0%',true);
  fetch(API_URL+'/scout',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':API_KEY},body:JSON.stringify(req)})
    .then(r=>r.json()).then(j=>{
      if(!j.job_id) throw new Error('no job');
      const poll=()=>fetch(API_URL+'/jobs/'+j.job_id).then(r=>r.json()).then(s=>{
        if(s.status==='done'){ setBtn('RUN ANALYSIS →',false); applyDoc(s.scout); setTab('overview'); }
        else if(s.status==='error'){ setBtn('RUN ANALYSIS →',false); alert('Analysis failed: '+(s.error||'unknown')); }
        else if(s.status==='unknown'){ setBtn('RUN ANALYSIS →',false); alert('The engine restarted — please run again.'); }
        else {
          const msg = s.stage==='acquire'
            ? 'ANALYSING… fetching terrain + imagery (2–4 min)'
            : 'ANALYSING… '+Math.round((s.progress||0)*100)+'% · '+(s.stage||'');
          setBtn(msg,true); setTimeout(poll,2500);
        }
      }).catch(()=>{ setBtn('RUN ANALYSIS →',false); alert('Lost connection to the engine.'); });
      poll();
    })
    .catch(()=>{ setBtn('RUN ANALYSIS →',false);
      alert('Engine API not reachable — showing the current scout. (RUN ANALYSIS needs the engine online.)');
      setTab('overview'); });
}

/* draft AOI box preview on the map (radius → box) */
function draftBox(){
  const [lon,lat]=draft.center, r=draft.radius;
  const dLat=r/111, dLon=r/(111*Math.cos(lat*Math.PI/180));
  return [[lon-dLon,lat+dLat],[lon+dLon,lat+dLat],[lon+dLon,lat-dLat],[lon-dLon,lat-dLat],[lon-dLon,lat+dLat]];
}
function drawDraft(){
  const data=fc([{type:'Feature',geometry:{type:'Polygon',coordinates:[draftBox()]},properties:{}}]);
  if(map.getSource('draft')) map.getSource('draft').setData(data);
  else { map.addSource('draft',{type:'geojson',data});
    map.addLayer({id:'draft-line',type:'line',source:'draft',
      paint:{'line-color':'#e2c044','line-width':2,'line-dasharray':[3,2]}});
    map.addLayer({id:'draft-fill',type:'fill',source:'draft',paint:{'fill-color':'#e2c044','fill-opacity':0.06}}); }
}
function startBoxDraw(){
  map.getCanvas().style.cursor='crosshair'; map.dragPan.disable();
  let start=null;
  const onDown=(e)=>{start=e.lngLat; };
  const onMove=(e)=>{ if(!start)return;
    const b=[[start.lng,start.lat],[e.lngLat.lng,start.lat],[e.lngLat.lng,e.lngLat.lat],[start.lng,e.lngLat.lat],[start.lng,start.lat]];
    map.getSource('draft').setData(fc([{type:'Feature',geometry:{type:'Polygon',coordinates:[b]},properties:{}}]));};
  const onUp=(e)=>{ if(!start)return;
    const clon=(start.lng+e.lngLat.lng)/2, clat=(start.lat+e.lngLat.lat)/2;
    const halfW=hav([start.lng,clat],[e.lngLat.lng,clat])/2, halfH=hav([clon,start.lat],[clon,e.lngLat.lat])/2;
    draft.center=[clon,clat]; draft.radius=Math.max(2,Math.round(Math.max(halfW,halfH)));
    document.getElementById('radius').value=Math.min(120,draft.radius);
    document.getElementById('radVal').textContent=draft.radius+' '+unitBig();
    document.getElementById('coord').value=clat.toFixed(4)+', '+clon.toFixed(4);
    cleanup(); drawDraft();};
  function cleanup(){ map.getCanvas().style.cursor=''; map.dragPan.enable();
    map.off('mousedown',onDown);map.off('mousemove',onMove);map.off('mouseup',onUp);}
  map.on('mousedown',onDown);map.on('mousemove',onMove);map.on('mouseup',onUp);
}

/* Nominatim geocode (no key) */
function geocode(q){
  if(!q||q.length<3) return Promise.resolve([]);
  return fetch('https://nominatim.openstreetmap.org/search?format=json&limit=5&q='+encodeURIComponent(q),
    {headers:{'Accept':'application/json'}}).then(r=>r.json()).catch(()=>[]);
}

/* ---------------- brief — scoped to the CHOSEN area ---------------- */
function renderBrief(){
  const a=DOC.areas.find(x=>x.rank===lastSel)||DOC.areas[0]; if(!a){document.getElementById('brief').innerHTML='';return;}
  const g=DOC.legal, st=a.stats||{}, rutT=(DOC.rut&&DOC.rut.targets)||[];
  const camp=DOC.camps.find(c=>(c.member_areas||[]).includes(a.rank));
  const wps=DOC.waypoints.filter(w=>w.properties.focus_area===a.rank && SITE_TYPES.includes(w.type));
  let h=`<div class="radii" style="margin-bottom:10px">`+
    DOC.areas.map(x=>`<button class="briefpick ${x.rank===a.rank?'on':''}" data-rank="${x.rank}">Area ${x.rank}</button>`).join('')+`</div>`;
  h+=`<h2>Field brief — Area ${a.rank} · ${a.area_km2} km²</h2>
    <div class="meta" style="color:#93a1a8;font-size:12px">huntability ${a.huntability} · camp ${a.camp} · ${a.centroid[1].toFixed(4)}, ${a.centroid[0].toFixed(4)}`
    +`${a.conf?` · confidence ${Math.round(a.conf.score*100)}% (${a.conf.band})`:''}</div>
    <p class="why">${a.why||''}</p>
    <h3>Legal / access</h3>
    <p>Zone <b>${g.zone}</b> · ${g.diy_possible?'DIY possible':'restricted'} · ${(g.huntable_tenures||[]).join(', ')||'—'}</p>
    <h3>Why this ground</h3>
    <p><b>Pros:</b> ${(a.pros||[]).join('; ')}.</p>
    <p><b>Watch-outs:</b> ${(a.cons||[]).join('; ')}.</p>`;
  if(st.dist_water_m!=null) h+=`<p class="s">water ${metres(st.dist_water_m)} · to road ${km((st.dist_road_m||0)/1000)} · slope ${st.mean_slope_deg}°</p>`;
  if(rutT.length){ h+=`<h3>Rut &amp; calling strategy</h3>`+
    rutT.map(t=>`<p>${t.date}: <b style="color:#f2b98a">${t.phase}</b> (${Math.round(t.responsiveness*100)}% responsive). ${t.guidance}`
      +(t.weather_note?` <span class="s">Weather: ${t.weather_note}.</span>`:'')+`</p>`).join('');
    if(DOC.rut.trigger_note) h+=`<p class="s" style="color:#e0b985">${DOC.rut.trigger_note}</p>`; }
  if(DOC.strategy){ h+=`<p><b>${DOC.strategy.headline}</b> — ${DOC.strategy.approach} ${DOC.strategy.calling||''}</p>`;
    if(DOC.strategy.scent_warning) h+=`<div class="warn">${DOC.strategy.scent_warning}</div>`; }
  h+=`<h3>Camp &amp; access</h3>`;
  if(camp) h+=`<p>Camp ${camp.id} · via ${camp.access_type} · pack-in ≤ ${km(camp.max_packin_km)}.</p>`;
  h+=`<p><b>Watercraft:</b> ${SETUP.watercraft} · <b>style:</b> ${SETUP.huntStyle==='vehicle'?'return to vehicle nightly':'spike camp'}.</p>`;
  h+=`<h3>Sites &amp; day plan (${wps.length})</h3>`+
    wps.map(w=>`<p><b style="color:${COLORS[w.type]||'#ccc'}">●</b> <b>${LABELS[w.type]||w.type}</b> — ${w.properties.when||(w.properties.optimal_wind||{}).note||''}</p>`).join('');
  h+=`<p class="s" style="margin-top:10px">${DOC.disclaimer}</p>`;
  const el=document.getElementById('brief'); el.innerHTML=h;
  el.querySelectorAll('.briefpick').forEach(b=>b.onclick=()=>{lastSel=+b.dataset.rank; renderBrief();
    map.flyTo({center:(DOC.areas.find(x=>x.rank===lastSel)||{}).centroid,zoom:12.2});});
}

/* ---------------- deep per-area analysis (finer re-run) ---------------- */
const AREA_DETAIL = (typeof window!=='undefined' && window.AREA_DETAIL) || {};
let deepActive=null;
function _hzFC(zones){return fc((zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},properties:{cls:z.cls,area_km2:z.area_km2}})));}
function _bzFC(zones){return fc((zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},properties:{type:z.type,what:z.what,when:z.when,area_km2:z.area_km2}})));}
function _rvFC(rivers){return fc((rivers||[]).map(o=>({type:'Feature',geometry:{type:'LineString',coordinates:o.ll||o},properties:{cls:o.cls||'stream'}})));}
function _lkFC(lakes){return fc((lakes||[]).map(r=>({type:'Feature',geometry:{type:'Polygon',coordinates:[r]},properties:{}})));}
function enterDeep(rank){
  const d=AREA_DETAIL[String(rank)];
  const badge=document.getElementById('deepBadge');
  if(!d){ if(badge){badge.style.display='none';} return false; }
  map.getSource('huntZones').setData(_hzFC(d.hunt_zones));
  map.getSource('browseZones').setData(_bzFC(d.browse_zones));
  if(d.refuge_zones) map.getSource('refugeZones').setData(_hzFC(d.refuge_zones));
  if(d.funnel_zones) map.getSource('funnelZones').setData(_hzFC(d.funnel_zones));
  if(d.hydro){ map.getSource('rivers').setData(_rvFC(d.hydro.rivers)); map.getSource('lakes').setData(_lkFC(d.hydro.lakes)); }
  // deep sites if the finer run produced them, else keep the parent's sites
  if(d.sites&&d.sites.length){
    window._sites=d.sites.map(s=>({type:'Feature',geometry:{type:'Point',coordinates:s.ll},
      properties:{type:s.t,when:s.when,windok:0}}));
    map.getSource('sites').setData(fc(window._sites)); buildShooters();
  }
  if(d.box) map.fitBounds([[d.box.w,d.box.s],[d.box.e,d.box.n]],{padding:70,duration:600});
  deepActive=rank;
  if(badge){ badge.style.display='block'; badge.textContent=`◉ ${d.res_m||20} m deep analysis · Area ${rank}`; }
  return true;
}
function exitDeep(){
  if(deepActive===null) return;
  const A=window._aoi||{};
  if(A.huntZones) map.getSource('huntZones').setData(A.huntZones);
  if(A.browseZones) map.getSource('browseZones').setData(A.browseZones);
  if(A.rivers) map.getSource('rivers').setData(A.rivers);
  if(A.lakes) map.getSource('lakes').setData(A.lakes);
  if(A.refugeZones) map.getSource('refugeZones').setData(A.refugeZones);
  if(A.funnelZones) map.getSource('funnelZones').setData(A.funnelZones);
  // restore AOI-wide sites
  window._sites=DOC.waypoints.filter(w=>SITE_TYPES.includes(w.type)).map(w=>({type:'Feature',
    geometry:{type:'Point',coordinates:[w.lon,w.lat]},
    properties:{type:w.type,area:w.properties.focus_area,when:w.properties.when||'',
      opt:(w.properties.optimal_wind||{}).from_deg??null,windnote:(w.properties.optimal_wind||{}).note||'',windok:0}}));
  map.getSource('sites').setData(fc(window._sites)); buildShooters();
  deepActive=null;
  const badge=document.getElementById('deepBadge'); if(badge) badge.style.display='none';
}

/* ---------------- tabs ---------------- */
let curTab='overview', lastSel=1;
// #tools (basemap info) is always visible; #hunting only where the map layers matter (overview/field)
const TAB_SHOW={setup:{setup:1,tools:1},overview:{panel:1,tools:1,hunting:1,weather:1,legend:1},
  field:{panel:1,tools:1,hunting:1,weather:1,legend:1},brief:{brief:1,tools:1}};
function setTab(name){
  const ids=['panel','setup','brief','tools','hunting','weather','legend'];
  const show=TAB_SHOW[name]||{};
  ids.forEach(id=>{const el=document.getElementById(id); if(el) el.classList.toggle('hidden',!show[id]);});
  document.querySelectorAll('#tabbar button').forEach(b=>b.classList.toggle('on',b.dataset.tab===name));
  // the draft AOI box is a Setup-only preview — hide it elsewhere so it doesn't
  // cover the map or intercept zone clicks.
  const dv=(name==='setup')?'visible':'none';
  ['draft-fill','draft-line'].forEach(id=>map.getLayer&&map.getLayer(id)&&map.setLayoutProperty(id,'visibility',dv));
  curTab=name;
  // Field = the per-area field plan + DEEP re-analysis of the chosen area.
  if(name==='field'){
    if(document.getElementById('detail').classList.contains('hidden')) selectArea(lastSel);
    enterDeep(lastSel);
  } else {
    exitDeep();
  }
  if(name==='brief') renderBrief();   // scope the brief to the currently chosen area
  setTimeout(()=>map.resize(),60);
}
function wireTabs(){ document.querySelectorAll('#tabbar button[data-tab]').forEach(b=>b.onclick=()=>setTab(b.dataset.tab)); }

/* ---------------- saved hunt plans (UUID + local storage) ----------------
   A plan captures your Setup, chosen area, and map drawings — saved under a UUID
   in this browser. (Cross-device accounts come with the durable server.) */
function uuid(){ return (crypto&&crypto.randomUUID)?crypto.randomUUID():'p-'+Date.now()+'-'+Math.random().toString(16).slice(2); }
function loadPlans(){ try{return JSON.parse(localStorage.getItem('transect_plans')||'[]');}catch(e){return [];} }
function savePlans(a){ try{localStorage.setItem('transect_plans',JSON.stringify(a));}catch(e){alert('Could not save (storage full).');} }
function currentPlan(name){
  return {id:uuid(), name:name||('Plan '+new Date().toLocaleDateString()), savedAt:Date.now(),
    aoi:(DOC.meta&&DOC.meta.title)||'', units:UNITS,
    setup:{center:draft.center.slice(),radius:draft.radius,walkAccess:draft.walkAccess,walkHunt:draft.walkHunt,
      leaving:draft.leaving,watercraft:SETUP.watercraft,huntStyle:SETUP.huntStyle,dates:draft.dates.slice()},
    area:lastSel, annot:JSON.parse(JSON.stringify(drawSaved||[]))};
}
function applyPlan(p){
  if(!p) return;
  const s=p.setup||{};
  draft.center=(s.center||draft.center).slice(); draft.radius=s.radius||draft.radius;
  draft.walkAccess=s.walkAccess??draft.walkAccess; draft.walkHunt=s.walkHunt??draft.walkHunt;
  draft.leaving=s.leaving||draft.leaving;
  if(s.dates&&s.dates.length===2) draft.dates=s.dates.slice();
  SETUP.watercraft=s.watercraft||SETUP.watercraft; SETUP.huntStyle=s.huntStyle||SETUP.huntStyle;
  UNITS=p.units||UNITS;
  drawSaved=JSON.parse(JSON.stringify(p.annot||[])); if(map.getSource('annot')) renderAnnot();
  lastSel=p.area||1;
  renderSetup();
  map.flyTo({center:draft.center,zoom:9.5}); drawDraft();
  document.getElementById('plans').classList.add('hidden');
  alert('Loaded "'+p.name+'". Its Setup + drawings are restored — hit RUN ANALYSIS to recompute this area, or browse the current scout.');
}
/* accounts — token in localStorage; plans sync to the server when signed in */
const authTok=()=>localStorage.getItem('transect_token')||'';
const authEmail=()=>localStorage.getItem('transect_email')||'';
const isAuthed=()=>!!authTok();
function apiF(path,opts){ opts=opts||{}; opts.headers=Object.assign(
  {'Content-Type':'application/json','X-API-Key':API_KEY,'Authorization':'Bearer '+authTok()},opts.headers||{});
  return fetch(API_URL+path,opts); }
async function doAuth(kind,email,pw){
  const r=await fetch(API_URL+'/auth/'+kind,{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':API_KEY},
    body:JSON.stringify({email,password:pw})});
  const d=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(d.detail||'failed');
  localStorage.setItem('transect_token',d.token); localStorage.setItem('transect_email',d.email); return d;
}
function signOut(){ apiF('/auth/logout',{method:'POST'}).catch(()=>{});
  localStorage.removeItem('transect_token'); localStorage.removeItem('transect_email'); renderPlans(); }
async function serverPlans(){
  try{ const r=await apiF('/plans'); if(!r.ok) return null;
    return (await r.json()).plans.map(p=>Object.assign({},p.data,{id:p.id,name:p.name,savedAt:(p.updated||0)*1000})); }
  catch(e){ return null; } }

async function renderPlans(){
  const el=document.getElementById('plans'); const authed=isAuthed();
  const auth = authed
    ? `<div class="authbar">Signed in as <b>${authEmail()}</b> <button id="signOut" class="ghost">Sign out</button></div>`
    : `<div class="authbox"><div class="prow"><input id="aEmail" type="email" placeholder="email"><input id="aPw" type="password" placeholder="password"></div>
       <div class="prow"><button id="aLogin">Sign in</button><button id="aSignup" class="ghost">Create account</button></div>
       <div class="s" id="aErr" style="color:#f79"></div></div>`;
  let plans = authed ? await serverPlans() : loadPlans();
  if(plans===null) plans=loadPlans();
  el.innerHTML=`<div class="phead"><b>Hunt plans</b><button id="plansClose" class="ghost">✕</button></div>
    ${auth}
    <div class="prow" style="margin-top:8px"><input id="planName" placeholder="Name this plan…"><button id="planSave">Save current</button></div>
    <div class="s" style="margin:2px 0 8px">${authed?'Synced to your account — available on any device.':'Saved in this browser. Sign in to sync across devices.'}</div>
    ${plans.length?plans.map(p=>`<div class="plan" data-id="${p.id}">
        <div><b>${p.name||'Plan'}</b><div class="s">${p.savedAt?new Date(p.savedAt).toLocaleString():''} · ${p.aoi||''} · r=${p.setup?p.setup.radius:'?'}km</div></div>
        <div class="pacts"><button data-act="load" data-id="${p.id}">Load</button><button data-act="del" data-id="${p.id}" class="ghost">Delete</button></div>
      </div>`).join(''):'<div class="s">No saved plans yet.</div>'}`;
  document.getElementById('plansClose').onclick=()=>el.classList.add('hidden');
  if(authed){
    document.getElementById('signOut').onclick=signOut;
  } else {
    const err=document.getElementById('aErr');
    const go=(kind)=>()=>{const e=document.getElementById('aEmail').value.trim(),p=document.getElementById('aPw').value;
      doAuth(kind,e,p).then(()=>renderPlans()).catch(x=>{err.textContent=x.message;});};
    document.getElementById('aLogin').onclick=go('login');
    document.getElementById('aSignup').onclick=go('signup');
  }
  document.getElementById('planSave').onclick=async ()=>{
    const p=currentPlan(document.getElementById('planName').value.trim());
    if(isAuthed()){ await apiF('/plans',{method:'PUT',body:JSON.stringify({id:p.id,name:p.name,data:p})}); }
    else { const arr=loadPlans(); arr.unshift(p); savePlans(arr); }
    renderPlans();
  };
  el.querySelectorAll('button[data-act]').forEach(b=>b.onclick=async ()=>{
    const id=b.dataset.id;
    if(b.dataset.act==='del'){
      if(isAuthed()) await apiF('/plans/'+id,{method:'DELETE'}); else savePlans(loadPlans().filter(x=>x.id!==id));
      renderPlans();
    } else {
      const src = isAuthed()? (await serverPlans()||[]) : loadPlans();
      applyPlan(src.find(x=>x.id===id));
    }
  });
}
function initPlans(){
  const btn=document.getElementById('plansBtn'); if(!btn) return;
  btn.onclick=()=>{ const el=document.getElementById('plans');
    if(el.classList.contains('hidden')){ renderPlans(); el.classList.remove('hidden'); } else el.classList.add('hidden'); };
}

/* ---------------- GPX / KML export (OnX / Garmin / Google Earth) ---------------- */
const _xesc=s=>String(s==null?'':s).replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
function exportWaypoints(){
  const w=[];
  // pull sites from the data (robust regardless of map-render state)
  (DOC.waypoints||[]).filter(x=>SITE_TYPES.includes(x.type)).forEach(x=>w.push(
    {lon:x.lon,lat:x.lat,name:LABELS[x.type]||x.type,desc:(x.properties&&x.properties.when)||''}));
  (DOC.camps||[]).forEach(c=>w.push({lon:c.site.lon,lat:c.site.lat,name:'Camp '+c.id,desc:'base camp'}));
  (DOC.waypoints||[]).filter(x=>x.type==='parking').forEach(x=>w.push({lon:x.lon,lat:x.lat,name:'Vehicle staging',desc:'leave the truck here'}));
  (DOC.crossings||[]).forEach(c=>w.push({lon:c.ll[0],lat:c.ll[1],
    name:(c.kind==='river'?'River':'Stream')+' crossing',desc:c.kind==='river'?'needs a boat':'fordable on foot'}));
  (drawSaved||[]).filter(f=>f.geometry.type==='Point').forEach((f,i)=>w.push(
    {lon:f.geometry.coordinates[0],lat:f.geometry.coordinates[1],name:f.properties.label||('Waypoint '+(i+1)),desc:'my mark'}));
  return w;
}
function exportTracks(withZones){
  const t=[];
  (DOC.areas||[]).forEach(a=>{ if(a.geometry&&a.geometry.coordinates) t.push({name:'Focus Area '+a.rank,pts:a.geometry.coordinates[0],poly:true}); });
  (DOC.routes||[]).forEach(r=>{ if(r.coords&&r.coords.length>1) t.push({name:(r.type||'route').replace('route_','').replace('_',' '),pts:r.coords,poly:false}); });
  (DOC.camps||[]).forEach(c=>(c.member_areas||[]).forEach(rk=>{const a=(DOC.areas||[]).find(x=>x.rank===rk);
    if(a) t.push({name:'Pack-in Camp '+c.id+' → Area '+rk,pts:[[c.site.lon,c.site.lat],a.centroid],poly:false});}));
  if(withZones){
    (DOC.hunt_zones||[]).forEach(z=>t.push({name:z.cls+' likelihood',pts:z.ll,poly:true}));
    (DOC.refuge_zones||[]).forEach(z=>t.push({name:'Thermal refuge',pts:z.ll,poly:true}));
    (DOC.funnel_zones||[]).forEach(z=>t.push({name:'Funnel / pass',pts:z.ll,poly:true}));
    (DOC.browse_zones||[]).forEach(z=>t.push({name:z.type,pts:z.ll,poly:true}));
  }
  (drawSaved||[]).filter(f=>f.geometry.type==='LineString').forEach((f,i)=>t.push({name:f.properties.label||('My line '+(i+1)),pts:f.geometry.coordinates,poly:false}));
  (drawSaved||[]).filter(f=>f.geometry.type==='Polygon').forEach((f,i)=>t.push({name:f.properties.label||('My area '+(i+1)),pts:f.geometry.coordinates[0],poly:true}));
  return t;
}
function buildGPX(withZones){
  let x='<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="Transect" xmlns="http://www.topografix.com/GPX/1/1">\n';
  exportWaypoints().forEach(w=>{x+=`<wpt lat="${w.lat}" lon="${w.lon}"><name>${_xesc(w.name)}</name><desc>${_xesc(w.desc)}</desc></wpt>\n`;});
  exportTracks(withZones).forEach(t=>{x+=`<trk><name>${_xesc(t.name)}</name><trkseg>`
    +t.pts.map(p=>`<trkpt lat="${p[1]}" lon="${p[0]}"/>`).join('')+`</trkseg></trk>\n`;});
  return x+'</gpx>';
}
function buildKML(withZones){
  let x='<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document><name>Transect — '+_xesc((DOC.meta||{}).title)+'</name>\n';
  exportWaypoints().forEach(w=>{x+=`<Placemark><name>${_xesc(w.name)}</name><description>${_xesc(w.desc)}</description><Point><coordinates>${w.lon},${w.lat},0</coordinates></Point></Placemark>\n`;});
  exportTracks(withZones).forEach(t=>{const c=t.pts.map(p=>p[0]+','+p[1]+',0').join(' ');
    x+= t.poly
      ? `<Placemark><name>${_xesc(t.name)}</name><Polygon><outerBoundaryIs><LinearRing><coordinates>${c}</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>\n`
      : `<Placemark><name>${_xesc(t.name)}</name><LineString><coordinates>${c}</coordinates></LineString></Placemark>\n`;});
  return x+'</Document></kml>';
}
function _download(name,text,mime){
  const b=new Blob([text],{type:mime}); const u=URL.createObjectURL(b);
  const a=document.createElement('a'); a.href=u; a.download=name; document.body.appendChild(a); a.click();
  setTimeout(()=>{URL.revokeObjectURL(u);a.remove();},2000);
}
function initExport(){
  const btn=document.getElementById('exportBtn'), menu=document.getElementById('exportMenu'); if(!btn) return;
  btn.onclick=()=>menu.classList.toggle('hidden');
  const slug=((DOC.meta||{}).aoi||'transect').replace(/[^a-z0-9]+/gi,'_');
  menu.querySelectorAll('button[data-fmt]').forEach(b=>b.onclick=()=>{
    const wz=document.getElementById('exZones').checked;
    if(b.dataset.fmt==='gpx') _download(slug+'.gpx',buildGPX(wz),'application/gpx+xml');
    else _download(slug+'.kml',buildKML(wz),'application/vnd.google-earth.kml+xml');
    menu.classList.add('hidden');
  });
  document.addEventListener('click',e=>{ if(!menu.contains(e.target)&&e.target!==btn) menu.classList.add('hidden'); });
}
