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
/* Cartes Xperts symbology — FROZEN. Québec moose hunters read these hexes fluently
   off the paper sheets; they are not ours to redesign. The chrome accent moved to
   brass precisely so it would stop colliding with --z-high red. */
const COLORS = {
  focus_area:'#CBD5DA', rut_calling:'#E2231A', thermal_refuge:'#FF00C8',
  saline_blind:'#0047FF', funnel:'#FF8C00', glassing:'#1F6F3F',
  validate_ground:'#CBD5DA', base_camp:'#C8963E', parking:'#DCA94D',
  route_best:'#E2231A', route_midday_hot:'#FF00C8', route_access:'#CBD5DA'
};
const FILL_ALPHA = 0.14;
/* browse stipple — texture survives overlapping the likelihood bands; a fifth flat
   fill in that stack is unreadable */
function stippleImage(){
  const S=16,cv=document.createElement('canvas');cv.width=cv.height=S;
  const c=cv.getContext('2d');
  c.clearRect(0,0,S,S); c.fillStyle='#8FB43A';
  [[3,3],[11,7],[7,11],[15,15]].forEach(([x,y])=>{c.beginPath();c.arc(x,y,1.6,0,7);c.fill();});
  const d=c.getImageData(0,0,S,S);
  return {width:S,height:S,data:new Uint8Array(d.data)};
}
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
const REFUGE_COL='#FF00C8', FUNNEL_COL='#FF8C00';
const ZONE_WHY={
  refuge:'Thermal-refuge bedding — cool mature conifer / north aspect near water. Where a bull holds through a warm midday. Hunt the shade, approach from above/downwind.',
  funnel:'Terrain funnel / pass — a pinch point that concentrates travelling bulls between cover and feed. Sit downwind of the throat during movement windows.'};
// Huntability likelihood classes (defined zones, not heat) — red = best.
const HUNT_CLS = {high:{c:'#E2231A',label:'High likelihood'},medium:{c:'#FF8C00',label:'Medium likelihood'},low:{c:'#FFD400',label:'Low likelihood'}};
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
  document.querySelectorAll('[data-base]').forEach(b=>{
    b.classList.toggle('on',b.dataset.base===base);
    if(b.closest('.seg')){ if(b.dataset.base===base) b.setAttribute('aria-pressed','true');
      else b.removeAttribute('aria-pressed'); }});
}
const map = new maplibregl.Map({container:'map',style:baseStyle(),
  center:[DOC.meta.center.lon,DOC.meta.center.lat],zoom:9.4,pitch:0,maxPitch:80,
  attributionControl:{compact:true}});
map.addControl(new maplibregl.NavigationControl({visualizePitch:true}),'bottom-right');
map.addControl(new maplibregl.ScaleControl({unit:'metric'}),'bottom-right');

/* The raster heat pipeline was removed with the switch to classified zones — the
   contract no longer ships behaviour grids, so it was ~60 lines targeting a source
   that is never added. Zones (huntZones/browse/refuge/funnel) carry that job now. */

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
  // the site feature carries the optimal bearing as `opt` (buildSources), NOT as a
  // nested optimal_wind object — reading the wrong key is why the promised wind ring
  // never rendered.
  const p=w.properties||{};
  const opt=(p.opt!=null)?p.opt:((p.optimal_wind||{}).from_deg);
  if(opt==null) return 0;
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
  // REAL engine routes (terrain/water cost-following). Typed so the map can style
  // access vs best vs midday-hot distinctly. A straight camp→centroid line is a
  // fiction, so we no longer draw one.
  const RT={route_access:'access',route_paddle:'access',route_best:'best',route_midday_hot:'hot'};
  const routes=fc((DOC.routes||[]).filter(r=>Array.isArray(r.coords)&&r.coords.length>1)
    .map(r=>({type:'Feature',geometry:{type:'LineString',coordinates:r.coords},
      properties:{t:RT[r.type]||'access',kind:r.type}})));
  const packin=[];
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
  return {areas,areaLabels,camps,staging,packin,routes,rivers,lakes,crossings,huntZones,browseZones,refugeZones,funnelZones,infra};
}

function init(){
  document.getElementById('subtitle').textContent =
    `${DOC.meta.species} · ${DOC.meta.target_dates.join(' – ')} · r${DOC.meta.radius_km} km · zone ${(DOC.legal||{}).zone||'?'}`;
  // Plans auto-name from the AOI — naming something before you know it's worth
  // keeping is friction at exactly the wrong moment.
  setPlanName(planTitle(), false);
  if(!document.getElementById('deepBadge')){const b=document.createElement('div');b.id='deepBadge';b.style.display='none';document.body.appendChild(b);}
  addIcons();
  const S=buildSources();
  window._aoi={huntZones:S.huntZones,browseZones:S.browseZones,rivers:S.rivers,lakes:S.lakes,
    refugeZones:S.refugeZones,funnelZones:S.funnelZones};

  // classified suitability zones (defined areas, not heat) — clickable for rationale
  map.addSource('huntZones',{type:'geojson',data:S.huntZones});
  map.addSource('browseZones',{type:'geojson',data:S.browseZones});
  const clsColor=['match',['get','cls'],'high',HUNT_CLS.high.c,'medium',HUNT_CLS.medium.c,'low',HUNT_CLS.low.c,'#888'];
  // Areal fills render at 14% with a full-saturation 1.5px stroke: solid fills were
  // muddying the satellite imagery, which is the layer that actually reveals the
  // logging roads and cutblocks the vector data misses. The stroke keeps identity.
  map.addLayer({id:'huntZones',type:'fill',source:'huntZones',
    paint:{'fill-color':clsColor,'fill-opacity':FILL_ALPHA}});
  map.addLayer({id:'huntZones-line',type:'line',source:'huntZones',
    paint:{'line-color':clsColor,'line-width':1.5,'line-opacity':1}});
  const brCol=['match',['get','type'],
    'Shrub / regen browse',BROWSE_COL['Shrub / regen browse'],
    'Riparian / wetland browse',BROWSE_COL['Riparian / wetland browse'],
    'Herbaceous opening',BROWSE_COL['Herbaceous opening'],
    'Forest-edge browse',BROWSE_COL['Forest-edge browse'],'#7ad151'];
  // Browse draws as a STIPPLE, not a fifth flat wash: it frequently sits *under*
  // the likelihood bands, and texture survives overlap where another fill can't.
  map.addImage('stipple', stippleImage(), {pixelRatio:2});
  map.addLayer({id:'browseZones',type:'fill',source:'browseZones',
    layout:{visibility:'none'},paint:{'fill-pattern':'stipple','fill-opacity':0.9}});
  map.addLayer({id:'browseZones-line',type:'line',source:'browseZones',
    layout:{visibility:'none'},paint:{'line-color':brCol,'line-width':1.5,'line-opacity':1,'line-dasharray':[2,1]}});
  // thermal refuge + funnel ZONES (areas, not points)
  map.addSource('refugeZones',{type:'geojson',data:S.refugeZones});
  map.addSource('funnelZones',{type:'geojson',data:S.funnelZones});
  map.addLayer({id:'refugeZones',type:'fill',source:'refugeZones',paint:{'fill-color':REFUGE_COL,'fill-opacity':FILL_ALPHA}});
  map.addLayer({id:'refugeZones-line',type:'line',source:'refugeZones',paint:{'line-color':REFUGE_COL,'line-width':1.5,'line-opacity':1,'line-dasharray':[4,2]}});
  map.addLayer({id:'funnelZones',type:'fill',source:'funnelZones',
    layout:{visibility:'none'},paint:{'fill-color':FUNNEL_COL,'fill-opacity':FILL_ALPHA}});
  map.addLayer({id:'funnelZones-line',type:'line',source:'funnelZones',
    layout:{visibility:'none'},paint:{'line-color':FUNNEL_COL,'line-width':1.5,'line-opacity':1}});

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
  // REAL routes from the engine (terrain/water-cost following, hundreds of points).
  // These were computed and exported but never drawn — the map used to show a
  // straight camp→centroid dash instead, which is exactly the wrong line to trust
  // when the crossings markers are anchored to the real one.
  map.addSource('routes',{type:'geojson',data:S.routes});
  map.addLayer({id:'route-access',type:'line',source:'routes',filter:['==',['get','t'],'access'],
    paint:{'line-color':COLORS.route_access,'line-width':2,'line-opacity':0.85,'line-dasharray':[3,2]}});
  map.addLayer({id:'route-hot',type:'line',source:'routes',filter:['==',['get','t'],'hot'],
    paint:{'line-color':COLORS.route_midday_hot,'line-width':2,'line-opacity':0.9,'line-dasharray':[4,2]}});
  map.addLayer({id:'route-best',type:'line',source:'routes',filter:['==',['get','t'],'best'],
    paint:{'line-color':COLORS.route_best,'line-width':2.4,'line-opacity':0.95}});
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
  // WIND-FIT RING — the legend has promised this since day one and no layer ever
  // read `windok`. Green = the chosen day's wind suits this setup, red = it doesn't.
  map.addLayer({id:'sites-wind',type:'circle',source:'sites',
    filter:['!=',['get','windok'],0],
    paint:{'circle-radius':['interpolate',['linear'],['zoom'],9,9,12,14,15,20],
      'circle-color':'rgba(0,0,0,0)','circle-stroke-width':2.4,
      'circle-stroke-color':['case',['==',['get','windok'],1],'#3FBF6E','#C9564A'],
      'circle-stroke-opacity':0.95}});
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
let _inited=false, _chromeUp=false;
function go(){ if(_inited)return; _inited=true; init();
  [0,200,600,1200].forEach(t=>setTimeout(()=>map.resize(),t)); }
/* If basemap tiles are slow or blocked (remote camp wifi, a dead CDN), the map
   'load' event may never fire — but the ledger, rail and brief don't need tiles.
   Build the chrome anyway so the plan is still readable. */
function chromeFallback(){
  if(_inited||_chromeUp) return; _chromeUp=true;
  try{ buildPanel(); }catch(e){}
  try{ buildTools(); }catch(e){}
  try{ buildWeather(); }catch(e){}
  try{ renderSetup(); renderBrief(); wireTabs(); initPlans(); initExport(); }catch(e){}
  try{ setPlanName(planTitle(),false);
    document.getElementById('subtitle').textContent=
      `${DOC.meta.species} · ${DOC.meta.target_dates.join(' – ')} · r${DOC.meta.radius_km} km`; }catch(e){}
}
map.on('load',go);
map.on('styledata',()=>{ if(map.isStyleLoaded()) go(); });
setTimeout(chromeFallback,4000);
window.addEventListener('resize',()=>map.resize());

/* ---------------- overview panel ---------------- */
/* Confidence as a five-bar gauge, not 11px grey text — the honesty machinery is a
   first-class UI element, not fine print. */
function confGauge(score){
  const n=Math.max(0,Math.min(5,Math.round((score||0)*5)));
  const lvl=n>=4?'high':(n<=2?'low':'mid');
  return `<span class="conf" data-level="${lvl}" title="Confidence is about DATA quality, not a guarantee animals are present">`+
    [0,1,2,3,4].map(i=>`<i ${i<n?'data-on':''}></i>`).join('')+`</span>`;
}
/* PACK-OUT REALITY — the decision that should veto an area for a foot hunter. A bull
   is ~200 kg of usable meat; a hard boned-out load is ~30 kg, so it is trips, not one
   carry. Walking loaded over boreal ground is ~2 km/h. */
function packout(a){
  const drKm=((a.stats||{}).dist_road_m||0)/1000;
  if(!drKm) return null;
  const loads=Math.max(3,Math.ceil(200/30));               // ≈7 loads for one bull
  const oneWay=drKm/2.0;                                   // hours, loaded
  const hrs=loads*oneWay*1.6;                              // out loaded + back empty
  const days=hrs/8;
  const boat=SETUP.watercraft!=='none';
  return {drKm,loads,hrs,days,
    text:`Kill here ⇒ ~${km(drKm)} to the nearest road ⇒ ~${loads} loads on foot ≈ `+
      (days>=1?`${days.toFixed(days<2?1:0)} hard day${days>=2?'s':''}`:`${Math.round(hrs)} h`)+
      (boat?' — or one trip if you can float it out.':'.')};
}
function buildPanel(){
  const g=DOC.legal, cf=DOC.confidence||null;
  document.getElementById('gate').innerHTML=
    `<div class="row" style="justify-content:space-between">
       <span class="t-micro" style="color:${g.diy_possible?'var(--good)':'var(--danger)'}">${g.diy_possible?'DIY POSSIBLE':'RESTRICTED'}</span>
       ${cf?`<span class="row" style="gap:7px"><span class="t-micro">CONF ${Math.round(cf.score*100)}%</span>${confGauge(cf.score)}</span>`:''}
     </div>
     <div class="t-data" style="margin-top:6px;color:var(--text-2)">ZONE ${g.zone} · ${g.north_of_52?'N':'S'} OF 52°N · ${(g.huntable_tenures||[]).join(', ')||'—'}</div>`
    + ((g.flags||[]).length?`<div class="callout" data-kind="warn"><span class="mark">!</span><div class="body"><b>${(g.flags||[]).length} thing${g.flags.length>1?'s':''} to confirm before you go</b>${(g.flags||[]).join('<br>')}</div></div>`:'')
    + (cf&&cf.caveats?`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${[].concat(cf.caveats).join(' ')}</div></div>`:'')
    + (DOC.strategy&&DOC.strategy.density_per_10km2?`<div class="s" style="margin-top:8px">Density ≈ <b class="mono">${DOC.strategy.density_per_10km2}</b> moose/10 km² (${DOC.strategy.density_is_estimate?'estimate':'survey'}) — expect long silences; coverage beats sitting.</div>`:'');
  const m=DOC.methodology;
  document.getElementById('method').innerHTML=
    `<details><summary class="t-micro" style="cursor:pointer">What I'm looking for</summary>
       <p class="s" style="margin:8px 0">${m.summary}</p>
       <div class="s"><b>Weighted:</b> ${(m.factors_weighted||[]).join('; ')}</div>
       ${(m.caveats||[]).map(c=>`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${c}</div></div>`).join('')}
     </details>`;
  let html='';
  DOC.camps.forEach(c=>{
    html+=`<div class="grouphead"><span class="g">Camp ${c.id}</span>
      <span class="g">${(c.member_areas||[]).length} areas · pack-in ≤ ${km(c.max_packin_km)}</span></div>`;
    DOC.areas.filter(a=>a.camp===c.id).sort((x,y)=>x.rank-y.rank).forEach(a=>{html+=areaCard(a);});
  });
  const list=document.getElementById('list'); list.innerHTML=html;
  list.querySelectorAll('.card').forEach(el=>el.onclick=()=>selectArea(+el.dataset.rank));
}
function areaCard(a){
  const dr=(a.stats||{}).dist_road_m||0;
  const boat=a.boat_required;
  const far=boat || (SETUP.huntStyle==='vehicle' && dr>reachKm()*1000);
  const po=packout(a);
  // Evidence lines: six saturated green pills read as one green block; a hairline row
  // with a single coloured operator scans far faster.
  const ev=[]
    .concat((a.pros||[]).slice(0,4).map(t=>({k:'pro',t})))
    .concat((a.cons||[]).slice(0,3).map(t=>({k:'con',t})))
    .map(e=>`<div class="ev" data-kind="${e.k}"><span class="op">${e.k==='pro'?'+':'!'}</span><span class="txt">${e.t}</span></div>`).join('');
  return `<div class="card ${far?'dim':''}" data-rank="${a.rank}">
    <div class="top"><div class="badge ${a.rank<=2?'top':''}">${a.rank}</div>
      <div class="ttl">Area ${a.rank}</div><div class="val">${a.area_km2} km²</div></div>
    <div class="metaline">${a.conf?confGauge(a.conf.score)+`<span>conf ${Math.round(a.conf.score*100)}%</span>`:''}
      <span>${km(dr/1000)} to road</span></div>
    ${a.habitat_score!=null?`<div class="axes">
      <div class="ax"><span class="k">habitat</span><span class="bar"><i style="width:${Math.round(a.habitat_score*100)}%"></i></span><span class="v">${a.habitat_score}</span></div>
      <div class="ax"><span class="k">pack-out</span><span class="bar"><i class="ret" style="width:${Math.round((a.retrieval_score||0)*100)}%"></i></span><span class="v">${a.retrieval_score}</span></div>
    </div>`:`<div class="metaline"><span>score ${a.huntability}</span></div>`}
    ${a.access_flag?`<div class="callout" data-kind="${boat?'danger':'warn'}"><span class="mark">${boat?'✕':'!'}</span><div class="body">${a.access_flag}</div></div>`:''}
    <div class="why">${(a.why||'').slice(0,190)}</div>
    ${ev}
    ${po?`<div class="ev" data-kind="con"><span class="op">⇈</span><span class="txt">${po.text}</span></div>`:''}
  </div>`;
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
  const po=packout(a);
  const stat=(lbl,val)=>`<div class="stat"><span class="k">${lbl}</span><span class="v">${val}</span></div>`;
  const evRow=(k,t)=>`<div class="ev" data-kind="${k}"><span class="op">${k==='pro'?'+':'!'}</span><span class="txt">${t}</span></div>`;
  d.innerHTML=`<div class="sec" style="padding-bottom:0">
    <button class="btn btn--ghost btn--sm back" style="padding-left:0">← all areas</button>
    <div class="top" style="display:flex;align-items:center;gap:10px;margin-top:6px">
      <div class="badge ${rank<=2?'top':''}">${rank}</div>
      <div class="ttl" style="font:600 18px/1.2 var(--sans)">Area ${rank}</div>
      <div class="val" style="margin-left:auto">${a.area_km2} km²</div></div>
    <div class="metaline">${a.conf?confGauge(a.conf.score):''}
      <span>score ${a.huntability}</span><span>camp ${a.camp}</span>
      <span>${a.centroid[1].toFixed(4)}, ${a.centroid[0].toFixed(4)}</span></div>
    ${a.access_flag?`<div class="callout" data-kind="${a.boat_required?'danger':'warn'}"><span class="mark">${a.boat_required?'✕':'!'}</span><div class="body">${a.access_flag}</div></div>`:''}
    <p class="why">${a.why||''}</p>
  </div>
  <div class="sec">
    <div class="t-micro" style="margin-bottom:9px">Why it scored</div>
    <div class="statgrid">
      ${st.dist_water_m!=null?stat('water',metres(st.dist_water_m)):''}
      ${st.dist_road_m!=null?stat('to road',km(st.dist_road_m/1000)):''}
      ${st.mean_slope_deg!=null?stat('slope',st.mean_slope_deg+'°'):''}
      ${a.conf?stat('confidence',Math.round(a.conf.score*100)+'% '+a.conf.band):''}
    </div>
    ${(a.pros||[]).map(p=>evRow('pro',p)).join('')}
    ${(a.cons||[]).map(p=>evRow('con',p)).join('')}
    ${po?evRow('con',po.text):''}
    ${a.conf&&a.conf.drivers?`<div class="callout" data-kind="info" style="margin-top:10px"><span class="mark">i</span><div class="body">${a.conf.drivers.join(' · ')}</div></div>`:''}
  </div>
  ${rutT?`<div class="sec">
    <div class="t-micro" style="margin-bottom:9px">Your dates &amp; the rut</div>
    <div class="rutdates">${(DOC.rut.targets||[]).map(t=>
      `<span class="pill">${t.date} · ${t.phase} · ${Math.round(t.responsiveness*100)}%</span>`).join('')}</div>
    <p class="s" style="margin-top:9px">${rutT.guidance||''}</p>
    ${rutT.weather_note?`<div class="callout" data-kind="warn"><span class="mark">!</span><div class="body">Weather: ${rutT.weather_note}</div></div>`:''}
    ${DOC.rut.phase_note?`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${DOC.rut.phase_note}</div></div>`:''}
  </div>`:''}
  <div class="sec">
    <div class="t-micro" style="margin-bottom:9px">Sites — ${wps.length}</div>
    ${wps.map(w=>{const ow=w.properties.optimal_wind||{};return `<div class="wp">
      <span class="dot" style="background:${COLORS[w.type]||'#ccc'}"></span>
      <div><div class="t">${LABELS[w.type]||w.type}</div>
      <div class="s">${w.properties.when||ow.note||('elev '+(w.properties.elev_m||'?')+' m')}</div></div></div>`;}).join('')}
  </div>`;
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
/* Moose activity is bimodal and light-triggered, but the afternoon peak sits ~1.5–2.5 h
   BEFORE dusk (GAMM on 622 GPS-collared moose), not at last light — so "be in position
   by early afternoon" is the actionable correction over the usual last-light advice. */
function updateHour(h){
  const lbl=document.getElementById('hourlbl');
  const em=(DOC.behavior&&DOC.behavior.expected_midday)||{};
  const warm=(em.refuge_weight||0)>=0.5;
  let period;
  if(h<6.0) period='pre-dawn — bedded';
  else if(h<9.0) period='first light — feeding peak';
  else if(h<13.0) period=warm?'late morning — moving to shade':'late morning — loafing';
  else if(h<16.5) period=(warm?'afternoon — thermal refuge; ':'')+'afternoon activity building (peak ~15:00–16:00)';
  else if(h<19.0) period='evening — feeding peak';
  else period='night — travel';
  if(lbl) lbl.textContent=`${Math.floor(h)}:${String(Math.round((h%1)*60)).padStart(2,'0')} · ${period}`;
  updateThermal(h);
  const tl=document.getElementById('thermLbl');
  if(tl) tl.textContent=thermalRising(h)?'· ↑ upslope':'· ↓ downslope';
}

function buildLegend(){ /* the separate legend is gone — colour meaning now lives in
  the layer rows themselves (each swatch previews how that layer actually draws), so
  panel and map cannot drift apart. See LAYERS below. */ }

/* ---------------- layer catalogue -------------------------------------------
   ONE array drives both the Layers card and the map. A row's swatch is a preview
   of how the layer really renders (hatched chip for zones, stipple for browse, the
   real dash for routes, the real glyph on its halo for point sites), which is why
   there is no longer a separate legend to hold in your head.
   `count` lets a row honestly report NO DATA instead of silently showing nothing. */
function setVis(ids,on){(ids||[]).forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',on?'visible':'none'));}
const LYR_MAP={areas:['areas-fill','areas-line','area-badges'],sites:['sites','sites-wind'],
  camps2:['camps','staging'],routes:['route-access','route-best','route-hot'],
  water:['lakes','lakes-line','rivers'],crossings:['crossings'],
  roads:['roads','roads-case','rail','trans'],
  boundaries:['boundaries'],
  shooters:['shooters','shooters-label','shooterLines'],thermal:['thermal'],
  huntZones:['huntZones','huntZones-line'],
  refuge:['refugeZones','refugeZones-line'],
  funnel:['funnelZones','funnelZones-line'],
  browse:['browseZones','browseZones-line']};

const LAYERS=[
 {group:'Model zones', rows:[
   {k:'hz-high', kind:'zone', c:'var(--z-high)', name:'High likelihood', note:'Model score in the top band',
    on:true, hz:'high', count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='high').length},
   {k:'hz-medium', kind:'zone', c:'var(--z-med)', name:'Medium', note:'Scored, second band',
    on:true, hz:'medium', count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='medium').length},
   {k:'hz-low', kind:'zone', c:'var(--z-low)', name:'Low', note:'Scored but not prioritised',
    on:true, hz:'low', count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='low').length},
   {k:'refuge', kind:'zone', c:'var(--thermal)', name:'Thermal refuge', note:'Cool midday bedding',
    on:true, lyr:'refuge', count:()=>(DOC.refuge_zones||[]).length},
   {k:'browse', kind:'stipple', c:'var(--browse)', name:'Browse / feeding',
    note:'Regen & riparian forage — the food itself', on:false, lyr:'browse',
    count:()=>(DOC.browse_zones||[]).length},
   {k:'funnel', kind:'zone', c:'var(--z-med)', name:'Funnels / passes',
    note:'Terrain pinch points — inferred from the DEM, weakly evidenced', on:false, lyr:'funnel',
    count:()=>(DOC.funnel_zones||[]).length},
 ]},
 {group:'Sites & features', rows:[
   {k:'sites', kind:'point', c:'var(--z-high)', glyph:'g-circle', name:'Hunt sites',
    note:'Calling, feeding, glassing, ground-truth', on:true, lyr:'sites',
    count:()=>(DOC.waypoints||[]).filter(w=>SITE_TYPES.includes(w.type)).length},
   {k:'camps2', kind:'point', c:'var(--accent)', glyph:'g-gable', name:'Camps & staging',
    note:'Where you sleep; where the truck sits', on:true, lyr:'camps2',
    count:()=>(DOC.camps||[]).length},
   {k:'shooters', kind:'point', c:'var(--z-low)', glyph:'g-diamond', name:'Caller / shooter',
    note:'Shooter ~70 m downwind of the caller', on:true, lyr:'shooters'},
   {k:'areas', kind:'outline', c:'var(--ref-outline)', name:'Focus-area outlines',
    note:'Plan extent', on:true, lyr:'areas', count:()=>(DOC.areas||[]).length},
   {k:'thermal', kind:'line', c:'var(--text-3)', dash:'dashed', name:'Thermal drift',
    note:'Modelled slope airflow — an inference, not a measurement', on:false, lyr:'thermal'},
 ]},
 {group:'Access & hydro', rows:[
   {k:'routes', kind:'line', c:'var(--z-high)', name:'Routes', note:'Access in, and the best line to hunt',
    on:true, lyr:'routes', count:()=>(DOC.routes||[]).length},
   {k:'roads', kind:'line', c:'var(--ref-outline)', name:'Roads & rail',
    note:'Reference geography, not a model output', on:true, lyr:'roads'},
   {k:'boundaries', kind:'outline', c:'var(--ref-outline)', name:'Borders & places',
    note:'Reference geography', on:true, lyr:'boundaries'},
   {k:'water', kind:'line', c:'var(--water-shore)', name:'Rivers & lakes',
    note:'Mapped hydrography (OSM)', on:true, lyr:'water',
    count:()=>((DOC.hydro||{}).rivers||[]).length},
   {k:'crossings', kind:'point', c:'var(--saline)', glyph:'g-triangle', name:'River crossings',
    note:'Red = needs a boat · amber = fordable', on:true, lyr:'crossings',
    count:()=>(DOC.crossings||[]).length},
 ]},
];

function lpHTML(r){
  const st=`--c:${r.c}`;
  if(r.kind==='zone')    return `<span class="lp lp--zone" style="${st}"><i></i></span>`;
  if(r.kind==='stipple') return `<span class="lp lp--stipple" style="${st}"><i></i></span>`;
  if(r.kind==='outline') return `<span class="lp lp--outline" style="${st}"></span>`;
  if(r.kind==='line')    return `<span class="lp lp--line" style="${st};--dash:${r.dash||'solid'}"><i></i></span>`;
  return `<span class="lp lp--point" style="${st}"><i class="${r.glyph||'g-circle'}"></i></span>`;
}
let showMeaning=true;
function buildLayersDock(){
  const d=document.getElementById('layersDock');
  let h=`<div class="dhead"><h4>Hunting layers</h4><button class="dclose" title="Close">✕</button></div>
    <div class="drow"><span class="t-micro">What each colour means</span>
      <label class="sw"><input type="checkbox" id="meaningOn" ${showMeaning?'checked':''}><i></i></label></div>
    <div class="dbody">`;
  LAYERS.forEach(g=>{
    const tot=g.rows.reduce((n,r)=>n+(r.count?(r.count()||0):0),0);
    h+=`<div class="grouplabel">${g.group}<span class="ct">${tot||''}</span></div>`;
    g.rows.forEach(r=>{
      const n=r.count?r.count():null;
      const nodata=(n===0);
      h+=`<label class="layer-row" data-k="${r.k}" data-state="${nodata?'nodata':(r.on?'on':'off')}">
        <input type="checkbox" ${r.on?'checked':''} ${nodata?'disabled':''}>
        ${lpHTML(r)}
        <span><span class="name">${r.name}</span>${showMeaning&&r.note?`<span class="note">${r.note}</span>`:''}</span>
        <span class="count">${nodata?'NO DATA':(n!=null?n:'')}</span></label>`;
    });
  });
  d.innerHTML=h+`</div>`;
  d.querySelector('.dclose').onclick=()=>closeDocks();
  d.querySelector('#meaningOn').onchange=e=>{showMeaning=e.target.checked;buildLayersDock();};
  d.querySelectorAll('.layer-row').forEach(row=>{
    const cb=row.querySelector('input'); if(cb.disabled) return;
    cb.onchange=()=>{
      const r=LAYERS.flatMap(g=>g.rows).find(x=>x.k===row.dataset.k); if(!r) return;
      r.on=cb.checked; row.dataset.state=r.on?'on':'off';
      if(r.hz) applyHuntZoneFilter();
      else if(r.lyr){ setVis(LYR_MAP[r.lyr],r.on);
        if(r.lyr==='browse') showBrowse=r.on;
        if(r.lyr==='thermal'&&r.on){const hr=document.getElementById('hour');updateThermal(hr?+hr.value:12);} }
    };
  });
}
function applyHuntZoneFilter(){
  const on=LAYERS[0].rows.filter(r=>r.hz&&r.on).map(r=>r.hz);
  ['huntZones','huntZones-line'].forEach(id=>map.getLayer(id)&&
    map.setFilter(id,['in',['get','cls'],['literal',on.length?on:['__none__']]]));
}
/* Each basemap states its actual SOURCE and resolution — you should be able to see
   what you're looking at without leaving the app. Options we don't have are shown
   as unavailable rather than hidden: same rule as the NO DATA layer row. */
const BASE_SPEC={satellite:'ESRI WORLD IMAGERY · 0.5 M', hybrid:'IMAGERY + LABELS',
  topo:'CANVEC · 20 M CONTOURS', relief:'CDEM HILLSHADE'};
const BASE_SWATCH={satellite:'linear-gradient(135deg,#3d4a2c,#6b7a4a)',
  hybrid:'linear-gradient(135deg,#3d4a2c,#7f8fa0)', topo:'linear-gradient(135deg,#d8d2c4,#a8b09a)',
  relief:'linear-gradient(135deg,#4a4a4a,#9a9a9a)'};
const BASE_ADDS=[
  {name:'LiDAR (HD topo)', note:'NOT AVAILABLE FOR THIS AOI', ok:false},
  {name:'Leaf-off imagery', note:'NOT WIRED — WOULD SHOW STRUCTURE UNDER CANOPY', ok:false},
  {name:'Recent imagery', note:'NOT WIRED — LESS DETAIL · UPDATED OFTEN', ok:false},
];
let baseOpacity=1, terrOn=false, terrExag=1.4;
function buildBaseDock(){
  const d=document.getElementById('baseDock');
  let h=`<div class="dhead"><h4>Basemap</h4><button class="dclose" title="Close">✕</button></div><div class="dbody">`;
  h+=`<div class="grouplabel">Basemap</div>`;
  BASEMAPS.forEach(b=>{
    const on=curBase===b;
    h+=`<div class="baserow ${on?'on':''}" data-base="${b}">
      <span class="bthumb" style="background:${BASE_SWATCH[b]}"></span>
      <span class="bmeta"><span class="bname">${BASE_LABEL[b]}</span>
        <span class="bspec">${BASE_SPEC[b]||''}</span></span>
      ${on?'<span class="btag">ACTIVE</span>':''}</div>`;
  });
  h+=`<div class="drow"><span class="t-micro">Opacity</span>
        <input id="baseOpacity" type="range" min="20" max="100" step="5" value="${Math.round(baseOpacity*100)}" style="width:120px"></div>`;
  h+=`<div class="grouplabel">Terrain</div>
      <div class="drow"><span class="t-micro">3D terrain</span>
        <label class="sw"><input type="checkbox" id="terr3d" ${terrOn?'checked':''}><i></i></label></div>
      <div class="drow"><span class="t-micro">Exaggeration <b class="mono" id="exagVal">${terrExag.toFixed(1)}×</b></span>
        <input id="terrExag" type="range" min="1" max="3" step="0.1" value="${terrExag}" style="width:120px"></div>`;
  h+=`<div class="grouplabel">Additional imagery</div>`;
  BASE_ADDS.forEach(a=>{
    h+=`<div class="layer-row" data-state="${a.ok?'off':'nodata'}">
      <input type="checkbox" ${a.ok?'':'disabled'}>
      <span class="lp lp--outline" style="--c:var(--text-4)"></span>
      <span><span class="name">${a.name}</span><span class="note">${a.note}</span></span>
      <span class="count">${a.ok?'':'NO DATA'}</span></div>`;
  });
  d.innerHTML=h+`</div>`;
  d.querySelector('.dclose').onclick=()=>closeDocks();
  d.querySelectorAll('.baserow').forEach(r=>r.onclick=()=>{
    switchBase(r.dataset.base); buildBaseDock(); openDock('baseDock','railBase'); });
  d.querySelector('#baseOpacity').oninput=e=>{
    baseOpacity=+e.target.value/100;
    ['satellite','topo','relief','trans'].forEach(id=>map.getLayer(id)&&
      map.setPaintProperty(id,'raster-opacity',baseOpacity)); };
  d.querySelector('#terr3d').onchange=e=>{
    terrOn=e.target.checked;
    if(terrOn){ map.setTerrain({source:'dem',exaggeration:terrExag}); map.easeTo({pitch:60}); }
    else { map.setTerrain(null); map.easeTo({pitch:0}); } };
  d.querySelector('#terrExag').oninput=e=>{
    terrExag=+e.target.value; d.querySelector('#exagVal').textContent=terrExag.toFixed(1)+'×';
    if(terrOn) map.setTerrain({source:'dem',exaggeration:terrExag}); };
}
/* A card must appear where you clicked — anchor it to the rail button that opened it. */
function openDock(id,btnId){
  closeDocks(id);
  const d=document.getElementById(id), b=document.getElementById(btnId);
  if(!d||!b) return;
  const r=b.getBoundingClientRect();
  d.style.top=Math.max(62,r.top-6)+'px';
  d.style.right=(window.innerWidth-r.left+10)+'px';
  d.classList.remove('hidden'); b.classList.add('on');
}
function closeDocks(except){
  ['layersDock','baseDock'].forEach(id=>{ if(id===except) return;
    const d=document.getElementById(id); if(d) d.classList.add('hidden'); });
  ['railLayers','railBase'].forEach(id=>{const b=document.getElementById(id);
    if(b && !(except&&((except==='layersDock'&&id==='railLayers')||(except==='baseDock'&&id==='railBase')))) b.classList.remove('on');});
}
function toggleDock(id,btnId){
  const d=document.getElementById(id);
  if(d && !d.classList.contains('hidden')) closeDocks(); else { if(id==='layersDock') buildLayersDock(); else buildBaseDock(); openDock(id,btnId); }
}

/* ---------------- right rail: persistent tools, transient cards ------------- */
function buildTools(){
  const rail=document.getElementById('rail');
  rail.innerHTML=`
    <button id="railLayers" data-tip="Hunting layers">▤</button>
    <button id="railBase" data-tip="Basemap">◱</button>
    <div class="sep"></div>
    <button data-tool="dist" data-tip="Measure distance">↔</button>
    <button data-tool="area" data-tip="Measure area">▱</button>
    <button data-tool="line" data-tip="Draw line">✎</button>
    <button data-tool="route" data-tip="Build route">➤</button>
    <button data-tool="waypoint" data-tip="Drop waypoint">◉</button>
    <button id="drawClear" data-tip="Clear drawings">✕</button>`;
  document.getElementById('railLayers').onclick=()=>toggleDock('layersDock','railLayers');
  document.getElementById('railBase').onclick=()=>toggleDock('baseDock','railBase');
  rail.querySelectorAll('button[data-tool]').forEach(b=>b.onclick=()=>setDrawTool(b.dataset.tool));
  document.getElementById('drawClear').onclick=()=>{clearDraw();setDrawTool(null);};

  const mc=document.getElementById('mapctl');
  mc.innerHTML=`<button id="mcN" data-tip="North up">N</button>
    <button id="mcIn">+</button><button id="mcOut">−</button>
    <button id="mcSat">SAT</button>`;
  document.getElementById('mcN').onclick=()=>map.easeTo({bearing:0,pitch:0});
  document.getElementById('mcIn').onclick=()=>map.zoomIn();
  document.getElementById('mcOut').onclick=()=>map.zoomOut();
  document.getElementById('mcSat').onclick=()=>toggleDock('baseDock','railBase');

  setupDraw();
  // Layers is the card you actually keep open while reading a plan — open it by
  // default (Basemap stays transient).
  buildLayersDock(); openDock('layersDock','railLayers');
}
/* the draw/measure strip is now part of the persistent right rail (buildTools) */
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
  document.querySelectorAll('#rail button[data-tool]').forEach(b=>b.classList.toggle('on',b.dataset.tool===drawTool));
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
    <div class="sec">
      <h2 class="t-h1" style="margin:0 0 6px">Scout setup</h2>
      <p class="lede">Define the box and the hunter. Both filter every recommendation downstream.</p>
    </div>

    <div class="sec">
      <div class="sechead"><span class="num">01</span><h3>Where &amp; when</h3></div>
      <label class="fld">Search a place</label>
      <div class="row"><input id="placeSearch" placeholder="Search a place, lake, mine…">
        <button id="searchBtn" class="btn btn--secondary btn--sm">Search</button></div>
      <div id="searchRes" class="results"></div>
      <button id="dragBox" class="btn btn--secondary btn--block" style="margin-top:8px">▛ Drag a box on the map</button>
      <label class="fld">Or paste coordinates</label>
      <input id="coord" placeholder="lat, lon" value="${draft.center[1].toFixed(4)}, ${draft.center[0].toFixed(4)}">
      <label class="fld">Hunt dates</label>
      <div class="numrow"><input id="dateStart" type="date" value="${draft.dates[0]}">
        <span>→</span><input id="dateEnd" type="date" value="${draft.dates[1]}"></div>
      <div class="s" style="margin-top:6px">Drives rut timing, weather and behaviour. Peak breeding ≈ Oct 2 at this latitude — but bulls are most <i>callable</i> in the two weeks before it.</div>
    </div>

    <div class="sec">
      <div class="sechead"><span class="num">02</span><h3>Quarry &amp; extent</h3></div>
      <label class="fld">Species</label>
      <div class="seg"><button aria-pressed="true">Moose</button></div>
      <label class="fld">Search radius — <b class="mono" id="radVal">${Math.round(toU(draft.radius))} ${unitBig()}</b></label>
      <input id="radius" type="range" min="${UNITS==='imperial'?3:5}" max="${UNITS==='imperial'?75:120}" step="1" value="${Math.round(toU(draft.radius))}">
      <div class="t-micro" style="display:flex;justify-content:space-between;margin-top:4px">
        <span>${UNITS==='imperial'?3:5}</span><span>~20 km+ resolves focus areas</span></div>
    </div>

    <div class="sec">
      <div class="sechead"><span class="num">03</span><h3>Hunter profile</h3></div>
      <label class="fld">How you'll hunt</label>
      <div class="seg"><button id="hsSpike" ${SETUP.huntStyle==='spike'?'aria-pressed="true"':''}>Spike camp</button>
        <button id="hsVeh" ${SETUP.huntStyle==='vehicle'?'aria-pressed="true"':''}>Return to vehicle</button></div>
      <div class="s" id="hsNote" style="margin-top:6px"></div>

      <label class="fld">Watercraft</label>
      <div class="seg"><button id="wcNone" ${SETUP.watercraft==='none'?'aria-pressed="true"':''}>No boat</button>
        <button id="wcCanoe" ${SETUP.watercraft==='canoe'?'aria-pressed="true"':''}>Canoe</button>
        <button id="wcMotor" ${SETUP.watercraft==='motor'?'aria-pressed="true"':''}>Motorboat</button></div>
      <div class="s" style="margin-top:6px">With no boat, rivers become foot barriers — ground across one from the road drops out of the ranking.</div>

      <label class="fld">Walk: access → base camp (max)</label>
      <div class="numrow"><input id="walkAccess" type="number" step="0.1" value="${toU(draft.walkAccess).toFixed(1)}"><span id="uAccess">${unitBig()}</span></div>
      <label class="fld">Walk: base camp → hunting (max)</label>
      <div class="numrow"><input id="walkHunt" type="number" step="0.1" value="${toU(draft.walkHunt).toFixed(1)}"><span id="uHunt">${unitBig()}</span></div>

      <label class="fld">Leaving from</label>
      <div class="row"><input id="leaveSearch" placeholder="Search departure town…" value="${draft.leaving}">
        <button id="leaveBtn" class="btn btn--secondary btn--sm">Search</button></div>
      <div id="leaveRes" class="results"></div>

      <label class="fld">Units</label>
      <div class="seg"><button id="uMetric" ${UNITS==='metric'?'aria-pressed="true"':''}>Metric</button>
        <button id="uImperial" ${UNITS==='imperial'?'aria-pressed="true"':''}>Imperial</button></div>

      <label class="fld">Basemap</label>
      <div class="seg">${BASEMAPS.map(b=>`<button data-base="${b}" ${curBase===b?'aria-pressed="true"':''}>${BASE_LABEL[b]}</button>`).join('')}</div>
    </div>

    <div class="sec">
      <button id="runBtn" class="btn btn--primary btn--lg btn--block">RUN ANALYSIS →</button>
      <div class="callout" data-kind="info" style="margin-top:10px"><span class="mark">i</span><div class="body">
        <b>Live recompute — 3–5 minutes</b>
        Downloads terrain, imagery, land-cover, burn history and hydrography for the box, then
        re-runs the model. Progress sits at 0% through the download stage; that's normal.</div></div>
    </div>`;

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
    segPick({none:'wcNone',canoe:'wcCanoe',motor:'wcMotor'}[w]); applyHunt();};
  document.getElementById('wcNone').onclick=()=>setWC('none');
  document.getElementById('wcCanoe').onclick=()=>setWC('canoe');
  document.getElementById('wcMotor').onclick=()=>setWC('motor');
  const setHS=(h)=>{SETUP.huntStyle=h;
    segPick(h==='spike'?'hsSpike':'hsVeh'); updateHsNote(); applyHunt();};
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
  setD('routes',S.routes);
  setVis(LYR_MAP.roads,true); setVis(LYR_MAP.boundaries,true);   // keep roads + borders visible after a recompute too
  window._aoi={huntZones:S.huntZones,browseZones:S.browseZones,rivers:S.rivers,lakes:S.lakes,
    refugeZones:S.refugeZones,funnelZones:S.funnelZones};
  Object.keys(AREA_DETAIL).forEach(k=>delete AREA_DETAIL[k]);   // deep detail is stale for a new AOI
  deepActive=null;
  try{buildThermal();}catch(e){} buildShooters();
  buildPanel(); buildWeather(); buildLayersDock(); lastSel=1;
  document.getElementById('subtitle').textContent=`${DOC.meta.title} · ${DOC.meta.species} · ${(DOC.meta.target_dates||[]).join(' – ')}`;
  const b=newDoc.box; if(b) map.fitBounds([[b.w,b.s],[b.e,b.n]],{padding:60});
}
function runAnalysis(){
  const btn=document.getElementById('runBtn');
  const setBtn=(t,dis)=>{if(btn){btn.textContent=t;btn.disabled=!!dis;}};
  const req={species:'moose',lat:draft.center[1],lon:draft.center[0],
    radius_km:Math.max(3,Math.min(120,draft.radius)),
    target_dates:(draft.dates&&draft.dates.length===2)?draft.dates:['2026-09-25','2026-10-05'],
    residency:'quebec_resident',
    // Setup constraints now shape the analysis (no-boat river barriers, walk range, rut-phase weighting)
    watercraft:SETUP.watercraft, hunt_style:SETUP.huntStyle,
    walk_access_km:draft.walkAccess, walk_hunt_km:draft.walkHunt};
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
  const dates=(DOC.meta&&DOC.meta.target_dates)||(draft.dates||[]);
  const styleTxt=SETUP.huntStyle==='vehicle'?'back to the truck nightly':'spike camp';
  const wcTxt={none:'no boat (foot access)',canoe:'canoe',motor:'motorboat'}[SETUP.watercraft]||SETUP.watercraft;
  const g2=DOC.legal||{};
  let h=`<div class="seg" style="margin-bottom:14px">`+
    DOC.areas.map(x=>`<button class="briefpick" data-rank="${x.rank}" ${x.rank===a.rank?'aria-pressed="true"':''}>Area ${x.rank}</button>`).join('')+`</div>`;
  // ---- the plan this brief is written for ----
  h+=`<div class="kicker">Field brief · Zone ${g2.zone||'?'} · ${(g2.huntable_tenures||['—'])[0]} · ${g2.diy_possible?'DIY':'restricted'}</div>
    <h2>Your hunt — Area ${a.rank}</h2>
    <div class="dataline">${a.area_km2} KM² · CAMP ${a.camp} · ${a.centroid[1].toFixed(4)}, ${a.centroid[0].toFixed(4)}`
    +`${a.conf?` · CONF ${Math.round(a.conf.score*100)}%`:''}</div>
    ${a.habitat_score!=null?`<div class="axes" style="margin:0 0 14px">
      <div class="ax"><span class="k">habitat</span><span class="bar"><i style="width:${Math.round(a.habitat_score*100)}%"></i></span><span class="v">${a.habitat_score}</span></div>
      <div class="ax"><span class="k">pack-out</span><span class="bar"><i class="ret" style="width:${Math.round((a.retrieval_score||0)*100)}%"></i></span><span class="v">${a.retrieval_score}</span></div>
    </div>`:''}
    <div class="callout" data-kind="info"><span class="mark">i</span><div class="body">
      <i style="font-family:var(--serif)">À valider sur le terrain.</i> Every mark below is a hypothesis
      to ground-truth on foot — the model reads habitat, not animals.</div></div>
    <p class="planline">If you hunt <b>Area ${a.rank}</b> (${a.area_km2} km²)${dates.length?`, <b>${dates.join(' – ')}</b>`:''}, running a <b>${styleTxt}</b> with <b>${wcTxt}</b> — here's how to make the most of it.</p>`;
  // ---- where your dates land + how that shapes the hunt ----
  if(DOC.rut&&(DOC.rut.hunt_read||rutT.length)){ h+=`<h3>Your dates &amp; the rut</h3>`;
    if(DOC.rut.hunt_read) h+=`<p class="huntread">${DOC.rut.hunt_read}</p>`;
    if(rutT.length) h+=`<div class="rutdates">`+rutT.map(t=>
      `<span class="pill" style="background:#2a2117;color:#f2b98a">${t.date} · ${t.phase} · ${Math.round(t.responsiveness*100)}%</span>`).join('')+`</div>`;
    if(DOC.rut.trigger_note) h+=`<p class="s" style="color:#e0b985;margin-top:6px">${DOC.rut.trigger_note}</p>`; }
  // ---- how to hunt this ground ----
  h+=`<h3>How to hunt it</h3>`;
  if(DOC.strategy){ h+=`<p><b>${DOC.strategy.headline}</b> ${DOC.strategy.approach||''} ${DOC.strategy.calling||''}`
    +`${DOC.strategy.movement?` <span class="s">${DOC.strategy.movement}</span>`:''}</p>`;
    if(DOC.strategy.scent_warning) h+=`<div class="warn">${DOC.strategy.scent_warning}</div>`; }
  h+=`<p class="why">${a.why||''}</p>
    <p class="s"><b>Working for you:</b> ${(a.pros||[]).join('; ')||'—'}.</p>
    <p class="s"><b>Watch-outs:</b> ${(a.cons||[]).join('; ')||'—'}.</p>`;
  // ---- getting in & out for your kit ----
  h+=`<h3>Getting in &amp; out</h3>`;
  if(a.access_flag) h+=`<div class="warn">${a.access_flag}</div>`;
  if(camp) h+=`<p>Base at <b>Camp ${a.camp}</b> — in via ${camp.access_type}, pack-in ≤ ${km(camp.max_packin_km)} to the hunt. Running ${styleTxt} with ${wcTxt}.</p>`;
  else h+=`<p>Running ${styleTxt} with ${wcTxt}.</p>`;
  if(st.dist_water_m!=null) h+=`<p class="s">water ${metres(st.dist_water_m)} · to road ${km((st.dist_road_m||0)/1000)} · slope ${st.mean_slope_deg}°</p>`;
  h+=`<p class="s">Legal: Zone <b>${g.zone}</b> · ${g.diy_possible?'DIY possible':'restricted'} · ${(g.huntable_tenures||[]).join(', ')||'—'}. ${(g.verify||[]).length?'Verify current season/rules before you go.':''}</p>`;
  // ---- day plan ----
  h+=`<h3>Your day plan — ${wps.length} site${wps.length!==1?'s':''}</h3>`+
    wps.map(w=>`<p><b style="color:${COLORS[w.type]||'#ccc'}">●</b> <b>${LABELS[w.type]||w.type}</b> — ${w.properties.when||(w.properties.optimal_wind||{}).note||''}</p>`).join('');
  // ---- what the score was built from ----
  const fw=((DOC.methodology||{}).factors_weighted)||[];
  if(fw.length){
    h+=`<h3>Weighted factors</h3>`;
    fw.forEach(f=>{
      const m=f.match(/\((\d+)%\)\s*$/);
      const pct=m?+m[1]:null, label=f.replace(/\s*\(\d+%\)\s*$/,'');
      h+=`<div class="wf"><span>${label}</span>
        <span class="wfbar"><i style="width:${pct?Math.min(100,pct*2.2):40}%"></i></span></div>`;
    });
  }
  // ---- how to do better (the leverage) ----
  const recs=(DOC.recommendations||[]);
  if(recs.length){ h+=`<h3>How to do better</h3><div class="recs">`+
    recs.map(r=>`<div class="rec rec-${r.impact||'low'}"><span class="recicon">${r.icon||'•'}</span><span>${r.text}</span></div>`).join('')+`</div>`; }
  h+=`<p class="s" style="margin-top:12px">${DOC.disclaimer||''}</p>`;
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
// The rail is persistent (you reach for tools constantly); only the ledger and the
// weather strip swap by step.
const TAB_SHOW={setup:{setup:1},overview:{panel:1,weather:1},
  field:{panel:1,weather:1},brief:{brief:1}};
function setTab(name){
  const ids=['panel','setup','brief','weather'];
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
/* plan identity in the top bar: auto-named, renamable inline, with a saved state */
let PLAN_NAME='', PLAN_SAVED=false;
/* mark exactly one button in a .seg as pressed (the control means "one of these") */
function segPick(id){
  const b=document.getElementById(id); if(!b) return;
  const seg=b.closest('.seg'); if(!seg){ b.setAttribute('aria-pressed','true'); return; }
  seg.querySelectorAll('button').forEach(x=>x.removeAttribute('aria-pressed'));
  b.setAttribute('aria-pressed','true');
}
function planTitle(){
  const t=(DOC.meta.title||'').trim(), sp=(DOC.meta.species||'').trim();
  return (sp && !t.toLowerCase().includes(sp.toLowerCase())) ? `${t} — ${sp}` : t;
}
function setPlanName(n,saved){
  PLAN_NAME=n; if(saved!=null) PLAN_SAVED=saved;
  const el=document.getElementById('planName'), d=document.getElementById('saveDot');
  if(el){ el.textContent=PLAN_NAME; el.title='Click to rename'; el.style.cursor='text';
    el.onclick=()=>{ const v=prompt('Rename this plan',PLAN_NAME); if(v&&v.trim()) setPlanName(v.trim(),false); }; }
  if(d){ d.dataset.s=PLAN_SAVED?'saved':'unsaved'; d.textContent=PLAN_SAVED?'SAVED':'UNSAVED'; }
}

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
