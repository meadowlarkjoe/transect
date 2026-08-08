/* Transect on MapLibre — binds window.TRANSECT_DATA (engine transect.json). */

/* A fresh session must NOT open on somebody else's analysis. data.js ships a baked
   Fire Lake run as an EXAMPLE, and loading it by default presented a stranger's plan
   as if it were yours — the exact thing this product claims not to do. So we start
   BLANK (same document shape, empty arrays) and only load the example when it's asked
   for explicitly: ?example=1, or the button in the empty state. */
const EXAMPLE = window.TRANSECT_DATA;
/* Where the map opens before an area is chosen. Montréal: recognisable, central to
   the zones this build knows, and obviously not a hunt area — so nobody mistakes
   the starting view for a suggestion. It is a CAMERA POSITION, never a default AOI:
   draft.center stays null until you search, paste, or drag a box. */
const DEFAULT_VIEW = {lat:45.5019, lon:-73.5674};
function blankDoc(){
  const m = (EXAMPLE && EXAMPLE.meta) || {};
  return {
    schema: 'transect/1', blank: true,
    // A fresh plan must not inherit the EXAMPLE's centre — that seeded every new
    // user onto Fire Lake, someone else's hunt area, pre-filled as if they had
    // chosen it. Start on a neutral view and make them pick.
    meta: {aoi:'', title:'No area yet', species:'moose',
           center: DEFAULT_VIEW,
           radius_km: 35, target_dates: (m.target_dates||['2026-09-25','2026-10-05']),
           residency:'quebec_resident', extraction_modes:[]},
    legal: {zone:null, north_of_52:false, diy_possible:false, huntable_tenures:[],
            flags:[], verify:[], season_summary:''},
    methodology: {summary:'', factors_weighted:[], then:'', caveats:[]},
    camps: [], areas: [], waypoints: [], routes: [],
    weather: {source:'none', days:[]},
    hydro: {rivers:[], lakes:[]}, crossings: [], infra: [],
    hunt_zones: [], browse_zones: [], refuge_zones: [], funnel_zones: [],
    burn_zones: [], burn_meta: {}, cut_zones: [], cut_meta: {}, tenure_zones: [],
    rut: null, confidence: null, strategy: null, recommendations: [],
    disclaimer: (EXAMPLE && EXAMPLE.disclaimer) || ''
  };
}
const _q0 = new URLSearchParams(location.search);
const USING_EXAMPLE = _q0.get('example') === '1';
let DOC = USING_EXAMPLE ? EXAMPLE : blankDoc();
let selectedDay = null;
let selectedHour = 6.5;   // #27 — the scrubbed hour drives the per-position wind read
// Live engine API (Setup → RUN ANALYSIS recomputes for a new species/area/radius).
// URL + key come from config.js (deployed, not in the repo); ?api= overrides for tests.
const API_URL = (new URLSearchParams(location.search).get('api')) ||
  (typeof window!=='undefined' && window.TRANSECT_API) ||
  'https://api.joejmeadows.com';
const API_KEY = (typeof window!=='undefined' && window.TRANSECT_API_KEY) || '';

/* ---------------- hunt setup state ---------------- */
let SETUP = { watercraft:'none', huntStyle:'spike',
  transport:{canoe:false,motor:false,atv:false} };   // multi-select; watercraft stays derived (motor>canoe>none) for engine back-compat

/* ---------------- units ---------------- */
let UNITS = 'metric';                       // 'metric' | 'imperial'
const KM_MI = 1.609344;
/* A FORMATTER MUST NEVER TAKE DOWN THE PAGE. km(null) threw `null is not an object
   (evaluating 'v.toFixed')`, and because the whole result is rendered in one pass that
   killed the ENTIRE analysis view — from one missing number. The value that did it was
   camp.max_packin_km, which the contract emits as null, correctly, when a camp has no
   member areas; two of the six call sites passed it straight in.
   The engine is right to say "unknown" with a null. The display's job is to show that,
   not to explode — an unknown distance is a dash, not a blank screen. */
const _n = (v) => (typeof v === 'number' && isFinite(v));
const km = (v) => !_n(v) ? '—'
  : (UNITS === 'imperial' ? (v / KM_MI).toFixed(1) + ' mi' : v.toFixed(1) + ' km');
const metres = (m) => !_n(m) ? '—'
  : (UNITS === 'imperial' ? Math.round(m * 1.09361) + ' yd' : Math.round(m) + ' m');
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
/* diagonal hatch — the universal "closed / no-go" convention on a hunting map */
function hatchImage(hex,back){
  const S=12,cv=document.createElement('canvas');cv.width=cv.height=S;
  const c=cv.getContext('2d');
  c.clearRect(0,0,S,S);
  c.strokeStyle=hex; c.lineWidth=2; c.globalAlpha=0.55;
  if(back){                       // "\" — distinct from the red no-go "/" hatch
    c.beginPath(); c.moveTo(-2,-2); c.lineTo(S+2,S+2); c.stroke();
    c.beginPath(); c.moveTo(-2,S/2-2); c.lineTo(S/2+2,S+2); c.stroke();
  } else {
    c.beginPath(); c.moveTo(-2,S+2); c.lineTo(S+2,-2); c.stroke();
    c.beginPath(); c.moveTo(S/2-2,S+2); c.lineTo(S+2,S/2-2); c.stroke();
  }
  const d=c.getImageData(0,0,S,S);
  return {width:S,height:S,data:new Uint8Array(d.data)};
}
/* Map fill patterns are generated at runtime from the layer hex, by the same data
   that drives the panel swatch — never authored separately, or panel and map drift.
   Line weight stays 1.1–1.5px at every zoom: scaling texture with zoom turns it
   into a solid at distance. */
function patternTile(kind,hex){
  const S=16,cv=document.createElement('canvas');cv.width=cv.height=S;
  const c=cv.getContext('2d');c.clearRect(0,0,S,S);
  const rgb=(h)=>{const n=parseInt(h.slice(1),16);return [(n>>16)&255,(n>>8)&255,n&255];};
  const [R,G,B]=rgb(hex);
  const col=(a)=>`rgba(${R},${G},${B},${a})`;
  if(kind==='stipple'){
    // Denser and stronger than it was: at r=1.4 / a=.67 the browse stipple all but
    // vanished over a satellite basemap, which is the one layer a hunter most wants to
    // read against the ground it describes.
    c.fillStyle=col(.85);
    [[3.5,3.5],[10.5,3.5],[3.5,10.5],[10.5,10.5],[7,7]].forEach(([x,y])=>{c.beginPath();c.arc(x,y,1.9,0,7);c.fill();});
  } else if(kind==='cross'){
    c.strokeStyle=col(.53);c.lineWidth=1.4;
    for(let o=-S;o<S*2;o+=6){c.beginPath();c.moveTo(o,0);c.lineTo(o+S,S);c.stroke();
                             c.beginPath();c.moveTo(o+S,0);c.lineTo(o,S);c.stroke();}
  } else if(kind==='hatch'){
    c.strokeStyle=col(.67);c.lineWidth=1.4;
    for(let o=-S;o<S*2;o+=7){c.beginPath();c.moveTo(o,S);c.lineTo(o+S,0);c.stroke();}
  } else if(kind==='exclude'){
    c.strokeStyle=col(.87);c.lineWidth=1.5;
    for(let o=-S;o<S*2;o+=6){c.beginPath();c.moveTo(o,0);c.lineTo(o+S,S);c.stroke();}
  } else if(kind==='soft'){
    // FEATHERED, NOT INVISIBLE. This peaked at 0.30 alpha and fell to 0.10 — and the
    // fill is then multiplied by the group opacity (0.9 x 0.55), so its effective peak
    // over satellite imagery was about 0.15. Funnels are the only 'soft' layer and they
    // are SMALL (a neck is <=300 m), so they were technically drawn and practically
    // unfindable: the only way to see them was to dim the basemap.
    //
    // The feathered edge is the point — a funnel is inferred from the DEM and must not
    // get a crisp outline, which would turn a soft inference into a surveyed boundary
    // (the 'never outline a guess' rule). So keep the gradient to zero at the tile edge
    // and raise the CORE instead: still edgeless, now actually visible.
    const g=c.createRadialGradient(S/2,S/2,0,S/2,S/2,S/2);
    g.addColorStop(0,col(.78));g.addColorStop(.55,col(.34));g.addColorStop(1,col(0));
    c.fillStyle=g;c.fillRect(0,0,S,S);
  }
  const d=c.getImageData(0,0,S,S);
  return {width:S,height:S,data:new Uint8Array(d.data)};
}
/* `tgt` so the PDF's offscreen map can register the SAME icons and patterns as the one
   on screen (T10.6). A symbol or fill-pattern layer whose image is missing draws
   nothing — silently — which is most of why the exported plates came out as basemap. */
function registerPatterns(tgt){
  const M=tgt||map;
  LAYERS.forEach(r=>{
    if(!['stipple','cross','hatch','exclude','soft'].includes(r.kind)) return;
    const id='pat-'+r.k;
    if(!M.hasImage(id)) M.addImage(id, patternTile(r.kind,r.hex), {pixelRatio:2});
  });
}
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
  saline_blind:'Feeding edge', funnel:'Funnel / pass', glassing:'Glassing knob',
  validate_ground:'Ground-truth', base_camp:'Base camp', parking:'Vehicle staging'
};
const SHAPE = {
  rut_calling:'circle', thermal_refuge:'ring', saline_blind:'square', funnel:'bowtie',
  glassing:'triangle', validate_ground:'diamond', base_camp:'tent', parking:'flag'
};
// Sites = POINT features. thermal_refuge + funnel are AREAS now (zones), not points.
// 'validate_ground' is deliberately absent: the ground-truth pin was one marker per
// area on the highest-scoring cell — i.e. on top of a stand the plan already drew —
// so it said "go look at the place we just told you to hunt". The advice survives as
// the ground-truth checklist in the brief, which covers every stand, not one point.
const SITE_TYPES = ['rut_calling','saline_blind','glassing'];
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
/* ---------------------------------------------------------------------------
   IMAGERY RESOLUTION LIMIT — keep the sharpest tile we have, never a blank.

   Esri does not 404 past its coverage; it serves a grey "Map data not yet
   available" placeholder. So zooming in over remote ground made the map appear
   to LOSE its imagery, which reads as "there is nothing here" when it means "we
   have run out of resolution". Over Fire Lake, real imagery stops at z16, topo
   at z17 and hillshade at z14 — but those limits are REGIONAL (southern Québec
   goes to z19), so hardcoding them would blur every other area.

   A source that declares its true maxzoom makes MapLibre OVERZOOM: it keeps
   stretching the deepest real tile instead of fetching the placeholder. So probe
   the actual AOI once, then declare what we found.
--------------------------------------------------------------------------- */
const BASE_MAXZ={satellite:19,topo:19,relief:16,trans:19,boundaries:19};
// Only the IMAGERY sources get probed. trans/boundaries are line overlays whose
// tiles are legitimately near-empty over wilderness — an empty roads tile there is
// correct, not missing data, and probing them by content would cap them at z10.
const ESRI_SVC={satellite:'World_Imagery',topo:'World_Topo_Map'};
// Hillshade is NOT probed by contrast, because shaded relief over flat boreal
// ground is legitimately low-contrast at every zoom (measured sd 1.7–5.2 over Fire
// Lake, versus 29.1 for real imagery). A variance test capped it at z10 and would
// have blurred terrain that was rendering fine. Its ceiling instead comes from the
// data underneath it: the terrarium DEM this app already declares maxes at z14, so
// hillshade cannot carry honest detail past that either.
const RELIEF_MAXZ=14;
function tileXY(lon,lat,z){
  const n=2**z, x=Math.floor((lon+180)/360*n);
  const r=lat*Math.PI/180;
  const y=Math.floor((1-Math.log(Math.tan(r)+1/Math.cos(r))/Math.PI)/2*n);
  return [x,y];
}
/* Esri's "Map data not yet available" tile is a flat grey card. Real imagery is
   never flat. Byte size was the obvious test and the wrong one — a genuinely
   uniform tile (snowfield, open water) is small too, and a sparse overlay tile is
   tiny by design. Luminance variance separates "no data" from "not much to see". */
async function tileVariance(url){
  const r=await fetch(url,{cache:'force-cache'});
  if(!r.ok) return null;
  const bmp=await createImageBitmap(await r.blob());
  const N=24, cv=document.createElement('canvas'); cv.width=cv.height=N;
  const c=cv.getContext('2d',{willReadFrequently:true});
  c.drawImage(bmp,0,0,N,N); bmp.close&&bmp.close();
  const d=c.getImageData(0,0,N,N).data;
  let s=0,s2=0,n=0;
  for(let i=0;i<d.length;i+=4){
    const L=0.299*d[i]+0.587*d[i+1]+0.114*d[i+2];
    s+=L; s2+=L*L; n++;
  }
  const mean=s/n;
  return Math.sqrt(Math.max(0,s2/n-mean*mean));
}
const FLAT_SD=7;                 // below this the tile carries no detail at all
async function probeMaxZoom(svc,lon,lat,hi,lo){
  for(let z=hi; z>=lo; z--){
    const [x,y]=tileXY(lon,lat,z);
    try{
      const sd=await tileVariance(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/${z}/${y}/${x}`);
      if(sd!=null && sd>FLAT_SD) return z;   // real detail at this level
    }catch(e){ /* CORS or network: fall through and try shallower */ }
  }
  return lo;
}
/* Re-declare a base source with its measured limit. MapLibre fixes maxzoom at
   add time, so the source and its layer are rebuilt and re-inserted underneath
   whatever is currently on top of them. */
function setBaseMaxZoom(id,mz){
  if(!map.getSource(id) || BASE_MAXZ[id]===mz) return;
  BASE_MAXZ[id]=mz;
  const layers=map.getStyle().layers, i=layers.findIndex(l=>l.id===id);
  if(i<0) return;
  const before=layers[i+1] ? layers[i+1].id : undefined;
  const vis=map.getLayoutProperty(id,'visibility')||'visible';
  const src=map.getStyle().sources[id];
  map.removeLayer(id); map.removeSource(id);
  map.addSource(id,{...src,maxzoom:mz});
  map.addLayer({id,type:'raster',source:id,layout:{visibility:vis}},before);
}
let imageryLimit=null;
async function calibrateImagery(){
  const c=DOC.meta&&DOC.meta.center; if(!c) return;
  setBaseMaxZoom('relief',RELIEF_MAXZ);
  const jobs=Object.keys(ESRI_SVC).map(async k=>{
    const z=await probeMaxZoom(ESRI_SVC[k],c.lon,c.lat,17,10);
    setBaseMaxZoom(k,z);
    return [k,z];
  });
  const got=await Promise.all(jobs);
  imageryLimit=Object.fromEntries(got);
  // the Basemap card states the limit, so "blurry" is never mistaken for "broken"
  const d=document.getElementById('baseDock');
  if(d && !d.classList.contains('hidden')) buildBaseDock();
}
function imageryNote(){
  if(!imageryLimit) return '';
  const z=imageryLimit[curBase]; if(z==null) return '';
  return map.getZoom()>z+0.2
    ? t('base.overzoom','Past the sharpest imagery published here — the last real tile is being stretched, not lost.')
    : '';
}

function baseStyle(){
  return {
    version:8, glyphs:'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources:{
      // maxzoom = the deepest zoom the PROVIDER actually publishes here. Declaring it
      // makes MapLibre OVERZOOM — keep stretching the last real tile — instead of
      // requesting a tile that doesn't exist and painting nothing. Zooming past the
      // data used to blank the map, which reads as "there's nothing here" when it
      // means "we've run out of resolution". Northern Québec imagery thins out well
      // before z19, so this bites early on exactly the ground this tool is for.
      satellite:{type:'raster',tiles:[ESRI('World_Imagery')],tileSize:256,maxzoom:BASE_MAXZ.satellite,attribution:'Esri'},
      topo:{type:'raster',tiles:[ESRI('World_Topo_Map')],tileSize:256,maxzoom:BASE_MAXZ.topo,attribution:'Esri'},
      relief:{type:'raster',tiles:[ESRI('Elevation/World_Hillshade')],tileSize:256,maxzoom:BASE_MAXZ.relief,attribution:'Esri — Hillshade'},
      trans:{type:'raster',tiles:[ESRI('Reference/World_Transportation')],tileSize:256,maxzoom:BASE_MAXZ.trans},
      boundaries:{type:'raster',tiles:[ESRI('Reference/World_Boundaries_and_Places')],tileSize:256,maxzoom:BASE_MAXZ.boundaries},
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
// What the map-control chip says. It is a STATUS READOUT, so it has to be derived from
// the live state every time — it used to be the literal string `<b>SAT</b><i>2D</i>`,
// written once and wired to nothing, so it claimed satellite while you were on Relief
// and 2D while you were pitched to 60 degrees (T10.10).
const BASE_CHIP={satellite:'SAT',topo:'TOPO',relief:'RELIEF',hybrid:'HYB'};
function syncBaseChip(){
  const el=document.getElementById('mcSat');
  if(!el) return;
  el.innerHTML=`<b>${BASE_CHIP[curBase]||'MAP'}</b><i>${terrOn?'3D':'2D'}</i>`;
}
let curBase='satellite';
function switchBase(base){
  curBase=base;
  syncBaseChip();
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
/* Zoom is clamped 3–17: past 17 the map would be drawn finer than the model's own
   inputs (10–30 m rasters), which invites reading precision that isn't there. */
const map = new maplibregl.Map({container:'map',style:baseStyle(),
  center:[DOC.meta.center.lon,DOC.meta.center.lat],zoom:9.4,pitch:0,maxPitch:80,
  minZoom:3,maxZoom:17,
  attributionControl:{compact:true}});
// NavigationControl is replaced by the #mapctl stack (§4 anchoring table) — two
// zoom stacks in the same corner is exactly the "floats without a parent" problem.
map.addControl(new maplibregl.ScaleControl({unit:UNITS==='imperial'?'imperial':'metric'}),'bottom-left');

/* The raster heat pipeline was removed with the switch to classified zones — the
   contract no longer ships behaviour grids, so it was ~60 lines targeting a source
   that is never added. Zones (huntZones/browse/refuge/funnel) carry that job now. */

/* --------------- waypoint icon badges (SYMBOLOGY §2, canvas -> addImage) ------
   The map marker and the panel swatch are the same object drawn twice: a rounded
   square in the layer's own colour, a dark halo so it survives satellite imagery,
   and a Lucide glyph whose stroke colour is COMPUTED from the badge luminance so
   it never has to be hand-maintained. Abstract shapes (circle / diamond / bowtie)
   were legible only against the legend; a glyph is legible on its own. */
const ICON_FOR = {
  rut_calling:'megaphone', thermal_refuge:'trees', saline_blind:'droplets',
  funnel:'fork', glassing:'binoculars', validate_ground:'eye',
  base_camp:'tent', parking:'truck', focus_area:'milestone',
  // these used to be bare circles, so the map disagreed with its own legend
  shooter:'target',
  // A crossing is a crossing: ONE glyph so the mark always reads "water in the way",
  // and a corner chip for WHICH KIND. Two different glyphs (sailboat vs footprints)
  // meant the legend could only ever show one of them, which is the same
  // map-disagrees-with-legend bug in a quieter form.
  crossing_boat:'waves', crossing_ford:'waves', crossing_bridge:'waves'
};
// blue is water, and only water — the badge body says "hydro", the chip says "how"
const CROSS_BODY='#7FC4E8';
// three states now, because "river => needs a boat" was asserting something we had
// no evidence for. A mapped road bridge is MEASURED; the rest is INFERRED from the
// OSM waterway class alone, and the card says which.
const CROSS_CHIP={bridge:'#3FBF6E', ford:'#E0A62E', boat:'#C9564A'};
const CROSS_LABEL={bridge:'Bridged — not an obstacle', ford:'Fordable on foot',
                   boat:'Assume you need a boat'};
function iconData(type,color,chip){
  const S=44, cv=document.createElement('canvas');
  cv.width=cv.height=S; const c=cv.getContext('2d');
  c.translate(S/2,S/2);
  const half=13;                                   // badge is 26x26 inside a 44 canvas
  const round=(x,y,w,h,r)=>{c.beginPath();
    c.moveTo(x+r,y); c.arcTo(x+w,y,x+w,y+h,r); c.arcTo(x+w,y+h,x,y+h,r);
    c.arcTo(x,y+h,x,y,r); c.arcTo(x,y,x+w,y,r); c.closePath();};
  round(-half,-half,half*2,half*2,7);
  c.lineWidth=3; c.strokeStyle='#0B0F0D'; c.stroke();   // halo first, badge over it
  c.fillStyle=color; c.fill();
  const d=(window.TRANSECT_ICONS||{})[ICON_FOR[type]];
  if(d && window.Path2D){
    const g=15/24;                                  // 24px viewBox -> 15px glyph
    c.save(); c.translate(-12*g,-12*g); c.scale(g,g);
    c.lineWidth=2.4/g; c.lineCap='round'; c.lineJoin='round';
    c.strokeStyle=glyphOn(color); c.stroke(new Path2D(d));
    c.restore();
  }
  // state chip, top-right: small enough to stay subordinate to the glyph, ringed in
  // the same halo colour so it reads as attached rather than as a second marker
  if(chip){
    c.beginPath(); c.arc(half-1, -half+1, 6, 0, 7);
    c.fillStyle='#0B0F0D'; c.fill();
    c.beginPath(); c.arc(half-1, -half+1, 4.2, 0, 7);
    c.fillStyle=chip; c.fill();
  }
  return {width:S,height:S,data:c.getImageData(0,0,S,S).data};
}
function addIcons(tgt){
  const M=tgt||map;
  Object.keys(SHAPE).forEach(t=>{ if(!M.hasImage(t)) M.addImage(t,iconData(t,COLORS[t]||'#ccc'),{pixelRatio:2}); });
  if(!M.hasImage('shooter')) M.addImage('shooter',iconData('shooter','#FFD400'),{pixelRatio:2});
  // same glyph and same body for both crossings; only the corner chip differs
  ['bridge','ford','boat'].forEach(k=>{
    const id='crossing_'+k;
    if(!M.hasImage(id)) M.addImage(id,iconData(id,CROSS_BODY,CROSS_CHIP[k]),{pixelRatio:2});
  });
  if(!M.hasImage('thermal-arrow')) M.addImage('thermal-arrow',arrowIcon(),{pixelRatio:2});
}

/* ---------------- data → GeoJSON ---------------- */
const fc = (features) => ({type:'FeatureCollection',features});
function bbox(areas){let a=180,b=90,c=-180,d=-90;
  areas.forEach(x=>x.geometry.coordinates[0].forEach(([X,Y])=>{a=Math.min(a,X);b=Math.min(b,Y);c=Math.max(c,X);d=Math.max(d,Y);}));
  return [[a,b],[c,d]];}

/* optimal wind fit for a waypoint on the selected day */
function angDiff(a,b){return Math.abs(((a-b+180)%360)-180);}
// #27 — the wind read is PER-POSITION and TIME-SCRUBBED, not one map-wide daily arrow.
// At the first/last-light windows the katabatic THERMAL DRIFT (cold air draining downhill)
// dominates the synoptic forecast wind, so the forecast verdict is unreliable then and the
// site flips to a "drift governs" state — read the Thermal-drift layer and approach from
// below. Midday, the forecast wind governs and the green/red fit verdict applies.
function isThermalWindow(h){ return h!=null && (h < 8.0 || h > 16.5); }   // dawn / dusk drainage
function windState(w){
  if(selectedDay==null) return 0;
  if(isThermalWindow(selectedHour)) return 2;   // thermal drift rules this hour, not forecast
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
  // WHICH WINDOW EVERY FEATURE BELONGS TO (T10.3). The merge already stamps `window` on
  // every list item, but nothing carried it onto the map, so two overlapping areas from a
  // rifle window and a bow window drew as one indistinguishable pile — reported as "They
  // overlap. Im guessing these are different for each season, but thats not clear."
  // -1 rather than null: MapLibre filters cannot compare against null, and an old plan
  // with no windows must stay visible under every filter state.
  const win=o=>(o&&o.window!=null)?o.window:-1;
  const areas=fc(DOC.areas.map(a=>({type:'Feature',geometry:a.geometry,
    properties:{rank:a.rank,camp:a.camp,hunt:a.huntability,dr:(a.stats||{}).dist_road_m||0,
      win:win(a),
      // EXCLUDED areas (capability gate) draw red — good ground this hunter's kit
      // can't reach. Shown, not hidden, with the reason on hover/click.
      excl:(a.status==='excluded')?1:0, why_out:a.excluded_reason||''}})));
  const areaLabels=fc(DOC.areas.map(a=>({type:'Feature',geometry:{type:'Point',coordinates:a.centroid},
    properties:{rank:a.rank,top:a.rank<=2,win:win(a)}})));
  // camps from contract (grouped, sited at access) → drawn as base camps
  // A fixed camp is the hunter's own, so it is labelled as theirs rather than offered
  // as "Camp A" — and the Setup draft pin for it is suppressed once a result exists
  // (see setTab), so there is exactly ONE camp marker instead of the two the map used
  // to show. The doc is the one drawn, not the draft, because a reopened plan always
  // has DOC.camps while the Setup draft state may not have survived the round trip.
  const camps=fc(DOC.camps.map(c=>({type:'Feature',geometry:{type:'Point',coordinates:[c.site.lon,c.site.lat]},
    properties:{id:c.id,fixed:!!c.fixed,win:win(c),label:c.fixed?'Camp':('Camp '+c.id)}})));
  // vehicle staging = parking waypoints
  const staging=fc(DOC.waypoints.filter(w=>w.type==='parking').map(w=>({type:'Feature',
    geometry:{type:'Point',coordinates:[w.lon,w.lat]},properties:{win:win(w)}})));
  // sites = the hunt-site waypoints (distinct icons)
  window._sites=DOC.waypoints.filter(w=>SITE_TYPES.includes(w.type)).map(w=>({type:'Feature',
    geometry:{type:'Point',coordinates:[w.lon,w.lat]},
    properties:{type:w.type,area:w.properties.focus_area,win:win(w),
      windnote:(w.properties.optimal_wind||{}).note||'', opt:(w.properties.optimal_wind||{}).from_deg??null,
      when:w.properties.when||'', elev:w.properties.elev_m||null, windok:0}}));
  // REAL engine routes (terrain/water cost-following). Typed so the map can style
  // access vs best vs midday-hot distinctly. A straight camp→centroid line is a
  // fiction, so we no longer draw one.
  const RT={route_access:'access',route_paddle:'access',route_best:'best',route_midday_hot:'hot'};
  // With an ATV the engine splits each route into RIDE and WALK legs (#69). Draw the
  // legs when they're there — the part you ride is not the part that costs you a
  // pack-out — and fall back to the whole line when they aren't.
  const routes=fc((DOC.routes||[]).filter(r=>Array.isArray(r.coords)&&r.coords.length>1)
    .flatMap(r=>{
      const base={t:RT[r.type]||'access',kind:r.type,win:win(r),
        ride_km:r.ride_km!=null?r.ride_km:null, walk_km:r.walk_km!=null?r.walk_km:null};
      if(Array.isArray(r.legs)&&r.legs.length)
        return r.legs.filter(lg=>Array.isArray(lg.coords)&&lg.coords.length>1)
          .map(lg=>({type:'Feature',geometry:{type:'LineString',coordinates:lg.coords},
            properties:Object.assign({},base,{mode:lg.mode,leg_km:lg.km!=null?lg.km:null})}));
      return [{type:'Feature',geometry:{type:'LineString',coordinates:r.coords},
        properties:Object.assign({},base,{mode:'foot'})}];
    }));
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
    properties:{type:z.type,what:z.what,when:z.when,area_km2:z.area_km2,score:z.score,
      // #96 provenance — which source decided this ground and how well the rest agreed.
      // Absent on plans computed before rev 21, so every reader has to tolerate null.
      src:(z.why&&z.why.source)||null, srcShare:(z.why&&z.why.share)||null, agree:(z.agree!=null?z.agree:null)}})));
  // BROWSE SUB-LAYERS (#96). browse.tif is a composite of four kinds of evidence; these
  // are the same polygonizer run over each contributor on its own, so the hunter can
  // switch off the satellite guess and see only ground backed by a dated, surveyed cut.
  const browseSub={};
  (DOC.browse_sublayers||[]).forEach(sl=>{
    browseSub[sl.key]=fc((DOC[sl.key]||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},
      properties:{area_km2:z.area_km2,score:z.score,name:sl.name,note:sl.note}})));
  });
  const zFC=(zones)=>fc((zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},properties:{area_km2:z.area_km2}})));
  const refugeZones=zFC(DOC.refuge_zones), funnelZones=zFC(DOC.funnel_zones);
  // #70: the feeding EDGE is a band, not a dot — draw its real extent alongside the
  // point markers that say where to actually sit.
  const feedEdgeZones=zFC(DOC.feed_edge_zones);
  const burnZones=fc((DOC.burn_zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},
    properties:{cls:z.cls,area_km2:z.area_km2}})));
  const cutZones=fc((DOC.cut_zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},
    // The BAND is a 15-year bucket; the years are the thing a hunter actually wants —
    // a 1998 cut and a 2012 cut are both "prime regen" and are not the same walk.
    properties:{cls:z.cls,area_km2:z.area_km2,
      yrFirst:(z.years&&z.years.first)||null, yrLast:(z.years&&z.years.last)||null,
      yrMed:(z.years&&z.years.median)||null, ageMed:(z.years&&z.years.age_median)||null}})));
  const tenureZones=fc((DOC.tenure_zones||[]).map(t=>({type:'Feature',geometry:t.geometry,
    properties:{tenure:t.tenure,name:t.name,access:t.access,huntable:!!t.huntable}})));
  // `unpaved` is carried SEPARATELY from `cls` on purpose: class is the road's role
  // (artery / road / track) and both data sources now agree on that, while surface is
  // its own fact. Folding surface into the class is what made the same gravel logging
  // road draw solid where MRNF mapped it and dashed where OSM did.
  const infra=fc((DOC.infra||[]).map(o=>({type:'Feature',geometry:{type:'LineString',coordinates:o.ll},
    properties:{t:o.t,cls:o.cls||o.t,name:o.name||'',unpaved:!!o.unpaved}})));
  const wetlandZones=zFC(DOC.wetland_zones);
  const beaverPonds=fc((DOC.beaver_ponds||[]).map(p=>({type:'Feature',geometry:{type:'Point',coordinates:p.ll},properties:{}})));
  // Leased shelters (T9.8). Squares, not circles, and a built-structure brown — these
  // are BUILDINGS somebody else uses, and must not read as one of your own sites.
  const leases=fc((((DOC.leases||{}).points)||[]).map(p=>({type:'Feature',
    geometry:{type:'Point',coordinates:[p.lon,p.lat]},
    properties:{kind:p.kind||'', label:p.label||'Leased shelter'}})));
  return {browseSub,areas,areaLabels,camps,staging,packin,routes,rivers,lakes,crossings,huntZones,browseZones,refugeZones,funnelZones,feedEdgeZones,burnZones,cutZones,wetlandZones,beaverPonds,leases,tenureZones,infra};
}

function init(){
  document.getElementById('subtitle').textContent =
    `${speciesName(DOC.meta.species)} · ${DOC.meta.target_dates.join(' – ')} · r${DOC.meta.radius_km} km · ${t('sub.zone')} ${(DOC.legal||{}).zone||'?'}`;
  // Plans auto-name from the AOI — naming something before you know it's worth
  // keeping is friction at exactly the wrong moment.
  setPlanName(planTitle(), false);
  if(!document.getElementById('deepBadge')){const b=document.createElement('div');b.id='deepBadge';b.style.display='none';document.body.appendChild(b);}
  addIcons();
  registerPatterns();
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
    paint:{'fill-color':clsColor,'fill-opacity':surfFillOpacity()}});
  // edge:'none' — a continuous field has no real boundary, so it gets NO stroke.
  // Outlining it would convert a fuzzy probability into a surveyed line.
  const brCol=['match',['get','type'],
    'Shrub / regen browse',BROWSE_COL['Shrub / regen browse'],
    'Riparian / wetland browse',BROWSE_COL['Riparian / wetland browse'],
    'Herbaceous opening',BROWSE_COL['Herbaceous opening'],
    'Forest-edge browse',BROWSE_COL['Forest-edge browse'],'#7ad151'];
  // Browse draws as a STIPPLE, not a fifth flat wash: it frequently sits *under*
  // the likelihood bands, and texture survives overlap where another fill can't.
  map.addLayer({id:'browseZones',type:'fill',source:'browseZones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-browse','fill-opacity':0.9}});
  // One layer per browse contributor (#96). Outlined rather than filled: these sit ON
  // TOP of the composite, so a solid wash would just hide the thing it is explaining.
  // Colour runs hard-evidence -> guess, matching the precedence the engine uses.
  // Written out one by one rather than built in a loop ON PURPOSE: the static gate
  // test_toggled_layer_ids_exist scans for literal addLayer ids to prove no toggle is a
  // no-op, and a computed id makes that check blind. A little repetition is cheaper than
  // a gate that cannot see the thing it guards.
  const _bsub=(k)=>({type:'geojson',data:(S.browseSub&&S.browseSub[k])||fc([])});
  map.addSource('browse_cut_zones',_bsub('browse_cut_zones'));
  map.addLayer({id:'browse_cut_zones',type:'fill',source:'browse_cut_zones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-browseCut','fill-opacity':0.95}});
  map.addLayer({id:'browse_cut_zones-line',type:'line',source:'browse_cut_zones',
    layout:{visibility:'none'},paint:{'line-color':'#8FE04A','line-width':1.4,'line-opacity':0.9}});
  map.addSource('browse_burn_zones',_bsub('browse_burn_zones'));
  map.addLayer({id:'browse_burn_zones',type:'fill',source:'browse_burn_zones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-browseBurn','fill-opacity':0.95}});
  map.addLayer({id:'browse_burn_zones-line',type:'line',source:'browse_burn_zones',
    layout:{visibility:'none'},paint:{'line-color':'#5FBF57','line-width':1.4,'line-opacity':0.9}});
  map.addSource('browse_stand_zones',_bsub('browse_stand_zones'));
  map.addLayer({id:'browse_stand_zones',type:'fill',source:'browse_stand_zones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-browseStand','fill-opacity':0.95}});
  map.addLayer({id:'browse_stand_zones-line',type:'line',source:'browse_stand_zones',
    layout:{visibility:'none'},paint:{'line-color':'#3E9A63','line-width':1.4,'line-opacity':0.9}});
  map.addSource('browse_lc_zones',_bsub('browse_lc_zones'));
  map.addLayer({id:'browse_lc_zones',type:'fill',source:'browse_lc_zones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-browseLc','fill-opacity':0.95}});
  map.addLayer({id:'browse_lc_zones-line',type:'line',source:'browse_lc_zones',
    layout:{visibility:'none'},paint:{'line-color':'#9CA86B','line-width':1.4,'line-opacity':0.9}});
  // edge:'none' — stipple carries the identity; satellite-derived browse has no surveyed edge
  // TENURE — closed ground gets a hatched red wash + hard outline; bookable ground a
  // dashed amber outline only. This is the legal gate made visible.
  map.addSource('feedEdgeZones',{type:'geojson',data:S.feedEdgeZones});
  map.addLayer({id:'feedEdgeZones',type:'fill',source:'feedEdgeZones',
    layout:{visibility:'none'},paint:{'fill-color':'#4FB0E5','fill-opacity':0.18}});
  map.addLayer({id:'feedEdgeZones-line',type:'line',source:'feedEdgeZones',
    layout:{visibility:'none'},paint:{'line-color':'#4FB0E5','line-width':1.2,'line-opacity':0.75}});
  map.addSource('tenureZones',{type:'geojson',data:S.tenureZones});
  // edge:'solid' 2px — a legal exclusion is the heaviest mark on the map, and it
  // also feeds the ranking mask: if it draws as excluded it IS excluded.
  map.addLayer({id:'tenureBlocked',type:'fill',source:'tenureZones',
    filter:['==',['get','huntable'],false],
    paint:{'fill-pattern':'pat-tenure','fill-opacity':0.9}});
  // line-dasharray is one of the few paint properties MapLibre will NOT evaluate as a
  // data expression, so the solid/dashed split has to be two layers with filters
  // rather than one ['case',…]. Closed ground: solid 2px red. Bookable: dashed amber.
  map.addLayer({id:'tenureZones-line',type:'line',source:'tenureZones',
    filter:['==',['get','huntable'],false],
    paint:{'line-color':'#C9564A','line-width':2,'line-opacity':0.95}});
  map.addLayer({id:'tenureZones-line-ok',type:'line',source:'tenureZones',
    filter:['!=',['get','huntable'],false],
    paint:{'line-color':'#E0A62E','line-width':1.5,'line-opacity':0.95,
      'line-dasharray':[4,2]}});

  // burn regeneration — prime (15–22 yr) reads hotter than the wider regen band
  // Burns also sat in the orange family and read as a third copy of MEDIUM. They get
  // a charcoal-ember hatch (backslash, so it can't be confused with the red no-go
  // hatch either) plus a dark umber outline — clearly "burnt ground", not a score band.
  map.addSource('burnZones',{type:'geojson',data:S.burnZones});
  // edge:'solid' — a fire perimeter IS surveyed, so it earns a stroke
  map.addLayer({id:'burnZones',type:'fill',source:'burnZones',
    layout:{visibility:'none'},paint:{'fill-pattern':'pat-burns',
      'fill-opacity':['case',['==',['get','cls'],'prime'],0.95,0.5]}});
  map.addLayer({id:'burnZones-line',type:'line',source:'burnZones',
    layout:{visibility:'none'},paint:{'line-color':'#C97A2B','line-width':1.5,'line-opacity':1}});
  // Recent LOGGING CUTS (écoforestière), coloured by age — a surveyed cutblock edge, so
  // it earns a stroke. Green family (it's about browse), distinct from the ember burns:
  // fresh = pale (open, browse not up yet), regen = bright (prime), closing = dark.
  map.addSource('cutZones',{type:'geojson',data:S.cutZones});
  const cutCol=['match',['get','cls'],'fresh','#C7C267','regen','#6FA83A','closing','#3F6B34','#6FA83A'];
  // Cuts already draw ABOVE browse (added later, and MapLibre paints in insertion order),
  // but they did not READ as above it: browse is a dense stipple at 0.9 while the cut fill
  // was 0.32, so the layer underneath won the contrast fight and the cuts looked buried.
  // Cuts are the one browse input with a hard surveyed edge and a real date on it, so it
  // gets the stronger mark of the two.
  map.addLayer({id:'cutZones',type:'fill',source:'cutZones',
    layout:{visibility:'none'},paint:{'fill-color':cutCol,'fill-opacity':0.5}});
  map.addLayer({id:'cutZones-line',type:'line',source:'cutZones',
    layout:{visibility:'none'},paint:{'line-color':cutCol,'line-width':1.8,'line-opacity':1}});
  // GRHQ WETLANDS (milieu humide) — the marsh/bog barrier that shapes funnels + travel (#62).
  // Teal, hatched-feel via a soft fill; off by default. Beaver PONDS ride on top as small dots
  // (a rut hub worth a stand).
  map.addSource('wetlandZones',{type:'geojson',data:S.wetlandZones});
  map.addLayer({id:'wetlandZones',type:'fill',source:'wetlandZones',
    layout:{visibility:'none'},paint:{'fill-color':'#3E8E7E','fill-opacity':0.22}});
  map.addLayer({id:'wetlandZones-line',type:'line',source:'wetlandZones',
    layout:{visibility:'none'},paint:{'line-color':'#3E8E7E','line-width':1.0,'line-opacity':0.8}});
  map.addSource('beaverPonds',{type:'geojson',data:S.beaverPonds});
  map.addLayer({id:'beaverPonds',type:'circle',source:'beaverPonds',
    layout:{visibility:'none'},paint:{'circle-radius':['interpolate',['linear'],['zoom'],8,2.2,13,5],
      'circle-color':'#2FB5C4','circle-stroke-color':'#0b3b40','circle-stroke-width':1,'circle-opacity':0.9}});
  map.addSource('leases',{type:'geojson',data:S.leases});
  map.addLayer({id:'leases',type:'circle',source:'leases',
    layout:{visibility:'none'},paint:{
      'circle-radius':['interpolate',['linear'],['zoom'],8,2.0,13,4.5],
      // An abri sommaire is the hunting signal; a cottage is mostly a summer thing.
      // Same layer, different weight, so the map shows the difference the model uses.
      'circle-color':['match',['get','kind'],
        'abri_sommaire','#B8734A','pourvoirie_camp','#A85C3A','#9C8B6E'],
      'circle-stroke-color':'#2b1d12','circle-stroke-width':1,'circle-opacity':0.9}});
  // thermal refuge + funnel ZONES (areas, not points)
  map.addSource('refugeZones',{type:'geojson',data:S.refugeZones});
  map.addSource('funnelZones',{type:'geojson',data:S.funnelZones});
  map.addLayer({id:'refugeZones',type:'fill',source:'refugeZones',
    paint:{'fill-pattern':'pat-refuge','fill-opacity':0.9}});
  // edge:'none' — no stroke (cross-hatch pattern carries the identity instead)
  // Funnels share --z-med (#FF8C00) with MEDIUM huntability in the frozen Cartes
  // Funnels share #FF8C00 with MEDIUM in the frozen Cartes Xperts palette, so they
  // separate by TEXTURE not hue — a soft radial field, the weakest evidence in the
  // system. edge:'none': no stroke, because outlining a DEM-inferred pinch point
  // would sell a guess as a surveyed line.
  map.addLayer({id:'funnelZones',type:'fill',source:'funnelZones',
    layout:{visibility:'none'},
    paint:{'fill-pattern':'pat-funnel','fill-opacity':0.85}});

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

  // roads + rail + trails (OSM) — access is critical for a hunt map (pack-in, staging,
  // pressure). Roads are DIFFERENTIATED by drivability class (#32): paved arteries read
  // brightest and widest, resource/logging tracks read as thin dashed gravel, and foot
  // TRAILS are a separate dotted layer you can't drive. A hunter reads the access the way
  // they would on OnX — which spur is a highway and which is a two-track you might not get
  // a truck down. `_PAVED`/`_TRACK` filters split them; width scales off one base by class.
  const _PAVED=['all',['==',['get','t'],'road'],['match',['get','cls'],['artery','road'],true,false]];
  const _TRACK=['all',['==',['get','t'],'road'],['==',['get','cls'],'track']];
  // Width must be a TOP-LEVEL zoom interpolate — MapLibre forbids nesting a zoom expression
  // inside ['*',…] (that threw on every frame and broke rendering). So bake the per-class
  // factor into the interpolate STOP OUTPUTS via `match`, exactly like the rivers layer above.
  const _cw=(a,r)=>['interpolate',['linear'],['zoom'],
    8, ['match',['get','cls'],'artery',0.9*a,0.9*r],
    12,['match',['get','cls'],'artery',2.1*a,2.1*r],
    15,['match',['get','cls'],'artery',3.6*a,3.6*r]];
  const _tw=k=>['interpolate',['linear'],['zoom'],8,0.9*k,12,2.1*k,15,3.6*k];
  map.addSource('infra',{type:'geojson',data:S.infra});
  map.addLayer({id:'roads-case',type:'line',source:'infra',filter:_PAVED,
    paint:{'line-color':'#20160a','line-width':_cw(2.0,1.5),'line-opacity':0.5}});
  map.addLayer({id:'roads',type:'line',source:'infra',filter:_PAVED,
    paint:{'line-color':['match',['get','cls'],'artery','#f6e7bd','#e4cf94'],
      'line-width':_cw(1.4,1.0),'line-opacity':0.95}});
  map.addLayer({id:'roads-track',type:'line',source:'infra',filter:_TRACK,
    paint:{'line-color':'#c39a5e','line-width':_tw(0.75),'line-dasharray':[3,2.2],'line-opacity':0.9}});
  map.addLayer({id:'trails',type:'line',source:'infra',filter:['==',['get','t'],'trail'],
    layout:{visibility:'none'},
    paint:{'line-color':'#9db36a','line-width':_tw(0.7),'line-dasharray':[1,2.2],'line-opacity':0.9}});
  map.addLayer({id:'rail',type:'line',source:'infra',filter:['==',['get','t'],'rail'],
    paint:{'line-color':'#c7cdc3','line-width':1.5,'line-dasharray':[2,3],'line-opacity':0.9}});

  // edge:'dashed', NEVER filled — this hull is our own drawing, and says so
  map.addLayer({id:'areas-fill',type:'fill',source:'areas',
    paint:{'fill-color':['case',['==',['get','excl'],1],'#C9564A','#CBD5DA'],'fill-opacity':0}});
  // White = a formal recommendation. RED = excluded by the capability gate: real ground,
  // but not reachable with the kit you told us about (the reason rides on the feature).
  map.addLayer({id:'areas-line',type:'line',source:'areas',
    paint:{'line-color':['case',['==',['get','excl'],1],'#C9564A','#CBD5DA'],
      'line-width':1.5,'line-opacity':.9,'line-dasharray':[3,2]}});
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
  // HOW EACH STRETCH IS TRAVELLED (T10.20). This used to be one 30%-opacity casing on
  // 'atv' legs, which is why "I can't see any difference between routes to be travelled
  // on ATV vs things to be walked" — it was technically drawn and practically invisible.
  // Each mode now gets its own casing, and they read differently at a glance:
  //   ridden  → solid amber, heavy (you are on a machine)
  //   boat    → solid blue, heavy (you are on water)
  //   trail   → thin dashed (walking, but on a cut line)
  //   bushwhack → dotted (walking, and paying for it)
  map.addLayer({id:'route-ride-atv',type:'line',source:'routes',
    filter:['==',['get','mode'],'atv'],layout:{'line-cap':'round'},
    paint:{'line-color':'#E2A03F','line-width':7,'line-opacity':0.75}},'route-access');
  map.addLayer({id:'route-ride-boat',type:'line',source:'routes',
    filter:['in',['get','mode'],['literal',['canoe','motor']]],layout:{'line-cap':'round'},
    paint:{'line-color':'#2F86C4','line-width':7,'line-opacity':0.75}},'route-access');
  map.addLayer({id:'route-foot-trail',type:'line',source:'routes',
    filter:['in',['get','mode'],['literal',['foot_trail','foot']]],layout:{'line-cap':'round'},
    paint:{'line-color':'#CFE0A8','line-width':4,'line-opacity':0.55,
      'line-dasharray':[2,1.4]}},'route-access');
  map.addLayer({id:'route-foot-bush',type:'line',source:'routes',
    filter:['==',['get','mode'],'foot_bush'],layout:{'line-cap':'round'},
    paint:{'line-color':'#C98F6A','line-width':4,'line-opacity':0.6,
      'line-dasharray':[0.6,1.6]}},'route-access');
  // PORTAGE (T10.21) — a foot leg between you and the water. Drawn heavier than a
  // bushwhack because it is the worst ground on the route: going in you carry a canoe,
  // coming out you carry the canoe and the meat, several trips over the same yards.
  map.addLayer({id:'route-portage',type:'line',source:'routes',
    filter:['==',['get','mode'],'portage'],layout:{'line-cap':'round'},
    paint:{'line-color':'#D2691E','line-width':5,'line-opacity':0.8,
      'line-dasharray':[1,1]}},'route-access');
  // thermal-drift arrow field (off by default; toggle in tools)
  if(!map.hasImage('thermal-arrow')) map.addImage('thermal-arrow',arrowIcon(),{pixelRatio:2});
  map.addSource('thermal',{type:'geojson',data:fc([])});
  // Thermal drift is a FINE-SCALE, per-stand signal — meaningless zoomed out over a
  // whole AOI. Gate it to close zoom (minzoom) so it appears only when you're reading
  // individual draws and aspects, and ramp size + opacity with zoom so it fades in
  // rather than popping. It's also Field-tab only (see setTab).
  map.addLayer({id:'thermal',type:'symbol',source:'thermal',minzoom:11.5,
    layout:{visibility:'none','icon-image':'thermal-arrow','icon-rotate':['get','brg'],
      'icon-size':['interpolate',['linear'],['zoom'],11.5,0.5,13,0.9,15,1.4],
      'icon-allow-overlap':true,'icon-rotation-alignment':'map'},
    paint:{'icon-opacity':['interpolate',['linear'],['zoom'],11.5,0,12.5,0.85]}});
  // caller/shooter pairs: the shooter sets up ~70 m downwind of each calling
  // station, because a bull circles downwind to scent-check before showing.
  map.addSource('shooterLines',{type:'geojson',data:fc([])});
  map.addSource('shooters',{type:'geojson',data:fc([])});
  map.addLayer({id:'shooterLines',type:'line',source:'shooterLines',
    paint:{'line-color':'#e6e9e3','line-width':1.2,'line-dasharray':[2,2],'line-opacity':0.85}});
  map.addLayer({id:'shooters',type:'symbol',source:'shooters',
    layout:{'icon-image':'shooter','icon-allow-overlap':true,
      // match the other site icons (SITE_SZ) — these were visibly smaller than every
      // other marker on the map for no reason (user-reported).
      'icon-size':['interpolate',['linear'],['zoom'],8,0.7,11,1.05,13,1.45,15,1.9]},
    paint:{'icon-opacity':0.95}});
  map.addLayer({id:'shooters-label',type:'symbol',source:'shooters',minzoom:10,
    layout:{'text-field':'SHOOTER','text-size':11,'text-offset':[0,-1.4],'text-font':['Open Sans Semibold'],'text-allow-overlap':true},
    paint:{'text-color':'#e6e9e3','text-halo-color':'#0b0f0d','text-halo-width':1.5}});
  // SCENT WICKS (#73) — three points across the downwind arc, short of the shooter.
  // Wind-dependent like the shooter, so they are derived here, not shipped as geometry.
  map.addSource('scent',{type:'geojson',data:fc([])});
  map.addSource('scentArc',{type:'geojson',data:fc([])});
  map.addLayer({id:'scentArc',type:'line',source:'scentArc',minzoom:11,
    paint:{'line-color':'#9BD1C4','line-width':1.1,'line-dasharray':[1,2],'line-opacity':0.7}});
  // SIZED TO BE FINDABLE. At 2.4-5.5 px these sat under site badges of 19-34 px and
  // disappeared entirely beneath the shooter — which is the ONE icon they are always
  // placed near, 25 m short of it by construction. Bigger, with a heavier halo so they
  // read against a badge rather than dissolving into it.
  map.addLayer({id:'scent',type:'circle',source:'scent',minzoom:11,
    paint:{'circle-radius':['interpolate',['linear'],['zoom'],11,4.5,15,9],
      'circle-color':'#9BD1C4','circle-stroke-color':'#0b0f0d','circle-stroke-width':2,
      'circle-opacity':0.98}});
  map.addLayer({id:'scent-label',type:'symbol',source:'scent',minzoom:13.2,
    filter:['==',['get','mid'],1],
    layout:{'text-field':'SCENT','text-size':10,'text-offset':[0,1.5],'text-font':['Open Sans Semibold'],'text-allow-overlap':true},
    paint:{'text-color':'#9BD1C4','text-halo-color':'#0b0f0d','text-halo-width':1.5}});
  const SITE_SZ=['interpolate',['linear'],['zoom'],8,0.7,11,1.05,13,1.45,15,1.9];
  // WIND-FIT RING — per-position + time-scrubbed (#27). Green = the chosen day's forecast
  // wind suits this setup · red = it doesn't · magenta = a first/last-light window where the
  // local THERMAL DRIFT governs, not the forecast (read the Thermal-drift layer, come from below).
  map.addLayer({id:'sites-wind',type:'circle',source:'sites',
    filter:['!=',['get','windok'],0],
    paint:{'circle-radius':['interpolate',['linear'],['zoom'],9,9,12,14,15,20],
      'circle-color':'rgba(0,0,0,0)','circle-stroke-width':2.4,
      'circle-stroke-color':['case',['==',['get','windok'],1],'#3FBF6E',['==',['get','windok'],2],'#FF00C8','#C9564A'],
      'circle-stroke-opacity':0.95}});
  map.addLayer({id:'sites',type:'symbol',source:'sites',
    layout:{'icon-image':['get','type'],'icon-size':SITE_SZ,'icon-allow-overlap':true}});
  // ...and lifted ABOVE the site badges. Occlusion had to break one way or the other:
  // a 9 px dot over a 30 px badge leaves the badge perfectly readable, while the badge
  // over the dot erased it. The wick positions are the whole point of the scent layer —
  // where the bull cuts cow scent BEFORE he reaches the shooter — so they win the overlap.
  ['scentArc','scent','scent-label'].forEach(id=>{ if(map.getLayer(id)) map.moveLayer(id); });
  map.addLayer({id:'staging',type:'symbol',source:'staging',
    layout:{'icon-image':'parking','icon-size':['interpolate',['linear'],['zoom'],8,0.8,11,1.15,15,2],'icon-allow-overlap':true}});
  // `text-optional` IS THE WHOLE TICKET. A MapLibre symbol carrying both an icon and a
  // label is placed as a UNIT: with neither part optional, a label that cannot be placed
  // takes the icon down with it. `icon-allow-overlap` exempts the icon from collision
  // testing but not the pair. So the camp's own "A" losing a collision — to the numbered
  // draft dot above, which sets text-allow-overlap and therefore always wins — deleted
  // the cabin. The hunter saw a number in a circle where their camp should be.
  map.addLayer({id:'camps',type:'symbol',source:'camps',
    layout:{'icon-image':'base_camp','icon-size':['interpolate',['linear'],['zoom'],8,0.9,11,1.25,15,2],'icon-allow-overlap':true,
      'text-optional':true,
      'text-field':['get','id'],'text-offset':[0,1.4],'text-size':12,'text-font':['Open Sans Semibold']},
    paint:{'text-color':'#e6c98a','text-halo-color':'#0b0f0d','text-halo-width':1.5}});
  map.addLayer({id:'area-badges',type:'symbol',source:'areaLabels',
    layout:{'text-field':['to-string',['get','rank']],'text-size':15,'text-font':['Open Sans Semibold'],'text-allow-overlap':true},
    paint:{'text-color':'#fff','text-halo-color':['case',['get','top'],'#127a2e','#111'],'text-halo-width':2.5}});
  // river crossings on routes — red = river (needs a boat), amber = fordable stream
  // A crossing is a decision point, so it gets the same badge treatment as every
  // other waypoint — and the same glyph the legend shows. As anonymous red/amber
  // dots these read as "sites", and 173 of them strung along an access route read
  // as a mystery linear feature.
  map.addLayer({id:'crossings',type:'symbol',source:'crossings',
    layout:{'icon-image':['match',['get','kind'],
        'bridge','crossing_bridge','ford','crossing_ford','crossing_boat'],
      'icon-size':['interpolate',['linear'],['zoom'],8,0.5,11,0.75,14,1],
      'icon-allow-overlap':true},
    paint:{'icon-opacity':0.95}});

  // interactions
  // When a draw/measure tool is armed it OWNS the click — feature popups and
  // selectArea must not fire, or they steal the click (this is why 'drop pin did
  // nothing': the click selected the focus area instead). onFeat wraps every
  // feature handler with that guard in one place.
  const onFeat=(layer,fn)=>map.on('click',layer,e=>{ if(drawTool) return; fn(e); });
  onFeat('huntZones',e=>{ const p=e.features[0].properties; const cl=HUNT_CLS[p.cls]||{};
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(`<h4><span style="color:${cl.c}">●</span> ${cl.label||p.cls} · ${p.area_km2} km²</h4><div class="s">${HUNT_WHY[p.cls]||''}</div>`).addTo(map);});
  onFeat('browseZones',e=>{ const p=e.features[0].properties;
    // #96 — browse is a composite, so the card says which source decided this ground and
    // whether the others backed it up. A number with no history is what made this layer
    // hard to trust. Older plans carry no provenance; the block simply does not render.
    let prov='';
    if(p.src){
      const sh=p.srcShare!=null?` (${Math.round(p.srcShare*100)}% of it)`:'';
      const ag=p.agree==null?'' : (p.agree>=0.8?'the other sources agree'
              : p.agree>=0.5?'the other sources partly agree'
              : '<b>the other sources disagree here</b>');
      prov=`<div class="s" style="margin-top:6px"><b>Why:</b> mostly the ${p.src}${sh}${ag?' — '+ag:''}.</div>`;
    }
    const sc=(p.score!=null)?`<div class="s" style="margin-top:4px"><b>Score:</b> ${p.score}</div>`:'';
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML(`<h4>${p.type} · ${p.area_km2} km²</h4><div class="s">${p.what}</div><div class="s" style="margin-top:4px"><b>When:</b> ${p.when}</div>${sc}${prov}`).addTo(map);});
  ['browse_cut_zones','browse_burn_zones','browse_stand_zones','browse_lc_zones'].forEach(k=>{
    onFeat(k,e=>{ const p=e.features[0].properties;
      new maplibregl.Popup().setLngLat(e.lngLat)
        .setHTML(`<h4>${p.name} · ${p.area_km2} km²</h4><div class="s">${p.note}</div>`+
                 `<div class="s" style="margin-top:4px"><b>Score from this source alone:</b> ${p.score}</div>`).addTo(map);});
  });
  onFeat('refugeZones',e=>{ new maplibregl.Popup().setLngLat(e.lngLat)
    .setHTML(`<h4><span style="color:${REFUGE_COL}">▨</span> Thermal refuge · ${e.features[0].properties.area_km2} km²</h4><div class="s">${ZONE_WHY.refuge}</div>`).addTo(map);});
  ['tenureZones-line','tenureZones-line-ok'].forEach(id=>
    onFeat(id,e=>{ const p=e.features[0].properties; tenurePopup(e.lngLat,p); }));
  onFeat('tenureBlocked',e=>{ const p=e.features[0].properties; tenurePopup(e.lngLat,p); });
  onFeat('burnZones',e=>{ const p=e.features[0].properties;
    const prime=p.cls==='prime';
    const bm=DOC.burn_meta||{};
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
      `<h4><span style="color:${prime?'#E07B39':'#8A5A2B'}">▨</span> Burn regeneration · ${prime?'prime':'regen'} · ${p.area_km2} km²</h4>`+
      `<div class="s">${prime
        ? 'Peak browse window (~15–22 yr post-fire): willow, birch and aspen at reachable height with cover alongside. In this black-spruce country the unburned matrix is close to a food desert, so burns of this age are where the animals concentrate.'
        : 'Regenerating burn, either side of the peak. Under ~8 yr the browse is below reachable height with no security cover; past ~30 yr the canopy closes and it grows out of reach.'}</div>`+
      (bm.first_year?`<div class="s" style="margin-top:4px;opacity:.75">Mapped fires ${bm.first_year}–${bm.last_year} (NBAC) · ${bm.pct_of_aoi}% of this area burned.</div>`:'')).addTo(map);});
  onFeat('funnelZones',e=>{ new maplibregl.Popup().setLngLat(e.lngLat)
    .setHTML(`<h4><span style="color:${FUNNEL_COL}">▨</span> Funnel / pass · ${e.features[0].properties.area_km2} km²</h4><div class="s">${ZONE_WHY.funnel}</div>`).addTo(map);});
  ['huntZones','browseZones','refugeZones','funnelZones','burnZones'].forEach(l=>{map.on('mouseenter',l,()=>map.getCanvas().style.cursor='pointer');map.on('mouseleave',l,()=>map.getCanvas().style.cursor='');});
  onFeat('crossings',e=>{ const p=e.features[0].properties;
    const noBoat=SETUP.watercraft==='none';
    const msg = p.kind==='bridge'
      ? 'A road bridge is mapped here, so this is not an obstacle — you drive or walk over it.'
      : p.kind==='ford'
        ? 'Mapped as a stream rather than a river — fordable on foot, but watch your footing and the water level.'
        : (noBoat
           ? '<b style="color:#f79">Treat as impassable on foot.</b> This is a mapped river, you have no boat, and nothing here tells us how wide it is — reroute or add a boat in Setup.'
           : 'Take the '+(SETUP.watercraft==='motor'?'motorboat':'canoe')+' across here.');
    // never let the popup imply more certainty than the data carries
    const basis = p.basis==='measured'
      ? '<div class="s" style="margin-top:6px;opacity:.8">Measured: a bridge is mapped at this point.</div>'
      : '<div class="s" style="margin-top:6px;opacity:.8">Inferred from the OSM waterway class alone — no width, ford or riverbank data ships for this area. Verify on the ground.</div>';
    new maplibregl.Popup().setLngLat(e.lngLat)
      .setHTML('<h4>'+(CROSS_LABEL[p.kind]||CROSS_LABEL.boat)+'</h4><div class="s">'+msg+'</div>'+basis).addTo(map);});
  onFeat('areas-fill',e=>selectArea(e.features[0].properties.rank));
  onFeat('sites',e=>{const p=e.features[0].properties;
    const scent = p.type==='saline_blind'
      ? '<div class="s" style="color:#e0a05a;margin-top:4px">⚠ Mineral/saline &amp; scents are regulated and may be prohibited in this zone — verify Zone '+((DOC.legal||{}).zone||'?')+' rules before using any attractant.</div>' : '';
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
      `<h4>${LABELS[p.type]||p.type}</h4>${p.when?('<div class="s">'+p.when+'</div>'):''}`+
      (p.windnote?('<div class="s">'+p.windnote+'</div>'):'')+scent).addTo(map);});
  ['areas-fill','sites','camps','staging'].forEach(l=>{
    map.on('mouseenter',l,()=>map.getCanvas().style.cursor='pointer');
    map.on('mouseleave',l,()=>map.getCanvas().style.cursor='');});

  buildShooters(); buildThermal();
  applyLegend();
  buildPanel(); buildWeather(); buildLegend(); buildTools();
  toggleWeather(false);   // the wind calendar is a rail tool now — off until asked for
  setVis(LYR_MAP.roads,true); setVis(LYR_MAP.boundaries,true);   // roads + borders on by default in every view
  applySiteFilter();
  // Each of these is independent chrome. Binding the tabs is the one thing that must
  // never be skipped, so a failure in an earlier renderer cannot cascade into
  // an app with dead navigation.
  [renderSetup,renderBrief,wireTabs,initAccount,initLang,initExport].forEach(fn=>{
    try{ fn(); }catch(e){ console.error('init step failed:',fn.name,e); }
  });
  setTab(startTab());
  if(window.I18N) I18N.apply(document);
  // Deep link from the plans dashboard: /transect/app?plan=<id> restores that plan
  // (and its cached analysis, when it has one) instead of opening blank.
  const _pid=new URLSearchParams(location.search).get('plan');
  // Claim the id SYNCHRONOUSLY: openPlanById() fetches, so waiting for it would
  // leave CUR_PLAN_ID null when resumeJob() checks ownership, and a legitimate
  // reconnect would be thrown away as "belongs to another plan".
  if(_pid){ CUR_PLAN_ID=_pid; openPlanById(_pid); }
  resumeJob();          // rejoin an analysis that outlived the page — this plan's only
  abandonJobOnUnload();
  if(DOC.blank || !(DOC.areas||[]).length){
    // neutral starting camera; zoomed out enough to read as "pick somewhere"
    map.jumpTo({center:[DEFAULT_VIEW.lon,DEFAULT_VIEW.lat],zoom:5.5});
  } else {
    map.fitBounds(bbox(DOC.areas),{padding:{top:80,left:400,right:200,bottom:120}});
  }
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
  try{ renderSetup(); renderBrief(); wireTabs(); initAccount(); initLang(); initExport(); setTab(startTab());
  if(window.I18N) I18N.apply(document); }catch(e){}
  try{ setPlanName(planTitle(),false);
    document.getElementById('subtitle').textContent=
      `${speciesName(DOC.meta.species)} · ${DOC.meta.target_dates.join(' – ')} · r${DOC.meta.radius_km} km`; }catch(e){}
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
/* WHAT COMING OUT ACTUALLY COSTS (T10.21).
   This used straight-line distance to the nearest road, which was the only number
   available before routes knew their modes. It is the wrong number in both directions:
   it charges you for ground a boat or a quad carries the load over for free, and it
   says nothing about a PORTAGE — where you carry a canoe in and the canoe plus a
   quartered bull out, several trips over the same yards.
   The route now reports `carry_km`: the distance walked UNDER LOAD, with water and
   ridden legs costed at one trip and portages at the loads plus the boat. Prefer it,
   and fall back to the old estimate for routes computed before this existed. */
function packout(a){
  const rts=(DOC.routes||[]).filter(r=>r.focus_area===a.rank&&r.carry_km!=null);
  const loads=Math.max(3,Math.ceil(200/30));               // ≈7 loads for one bull
  if(rts.length){
    const r=rts.reduce((x,y)=>((y.carry_km||0)<(x.carry_km||0)?y:x));
    const m=r.km_by_mode||{};
    const hrs=(r.carry_km||0)/2.0;                          // km walked under load, at 2 km/h
    const days=hrs/8;
    const floated=(m.canoe||0)+(m.motor||0), ridden=m.atv||0;
    const bits=[];
    if(r.walk_km!=null) bits.push(`~${km(r.walk_km)} on foot each way`);
    if(floated) bits.push(`${km(floated)} floated`);
    if(ridden) bits.push(`${km(ridden)} ridden`);
    return {drKm:r.walk_km,loads,hrs,days,carry:r.carry_km,portage:m.portage||0,
      text:`Coming out: ${bits.join(' · ')} ⇒ ~${loads} loads ≈ `+
        (days>=1?`${days.toFixed(days<2?1:0)} hard day${days>=2?'s':''}`:`${Math.round(hrs)} h`)+
        ` of walking under load (${km(r.carry_km)} total).`+
        (m.portage?` Includes a ${km(m.portage)} PORTAGE — in with a canoe, out with the canoe and the meat. A route you can portage in on is not necessarily one you can pack a bull out on.`:'')};
  }
  const drKm=((a.stats||{}).dist_road_m||0)/1000;
  if(!drKm) return null;
  const oneWay=drKm/2.0;                                   // hours, loaded
  const hrs=loads*oneWay*1.6;                              // out loaded + back empty
  const days=hrs/8;
  const boat=SETUP.watercraft!=='none';
  return {drKm,loads,hrs,days,
    text:`Kill here ⇒ ~${km(drKm)} to the nearest road ⇒ ~${loads} loads on foot ≈ `+
      (days>=1?`${days.toFixed(days<2?1:0)} hard day${days>=2?'s':''}`:`${Math.round(hrs)} h`)+
      (boat?' — or one trip if you can float it out.':'.')};
}
// E2: the honest "what covered your box" readout. The engine emits a coverage
// manifest (contract.build → DOC.coverage_manifest) — per declared data source, is
// THIS AOI in the source's coverage, and did the source actually land a product.
// 'fallback' = outside the source's envelope, using a coarser substitute (expected,
// info); 'missing' = declared in-coverage but nothing landed this run (degraded, warn).
// A collapsed summary by default; the caveats expand. Empty (older contract) → nothing.
/* SITE COMPARISON (T9.1). When a hunter enters more than one known site they are asking
   one question — which of these places is worth my week — and until now the engine
   answered it for the first one only and said nothing about the rest. This is the answer
   made visible: every site, whether it produced anything, and where its best ground
   ranks against the others. A site that returned NOTHING is shown, not omitted; that is
   a finding about the ground, and hiding it is what the old bug did by accident. */
function siteCompareBlock(){
  const S=DOC.sites||[];
  if(S.length<2) return '';
  const rows=S.map(s=>{
    const ll=`${s.lat.toFixed(4)}, ${s.lon.toFixed(4)}`;
    if(!s.ok) return `<div class="row" style="justify-content:space-between;padding:5px 0">
        <span class="mono t-micro">${s.site} · ${ll}</span>
        <span class="t-micro" style="color:var(--danger)">could not be analysed</span></div>`;
    if(!s.areas) return `<div class="row" style="justify-content:space-between;padding:5px 0">
        <span class="mono t-micro">${s.site} · ${ll}</span>
        <span class="t-micro" style="color:var(--text-3)">no ground cleared the bar</span></div>`;
    return `<div class="row" style="justify-content:space-between;padding:5px 0">
        <span class="mono t-micro">${s.site} · ${ll}</span>
        <span class="t-micro">${s.areas} area${s.areas>1?'s':''} · ${s.total_km2} km² · habitat ${s.best_habitat}${s.best_rank_overall?` · best is #${s.best_rank_overall} overall`:''}</span></div>`;
  }).join('');
  return `<div class="sec"><div class="t-micro" style="margin-bottom:6px">SITES COMPARED</div>
    ${rows}
    <div class="s" style="margin-top:6px">Each site was analysed on its own ground and the
    areas below are ranked across all of them.</div></div>`;
}
function coverageBlock(){
  const m=DOC.coverage_manifest||[];
  if(!m.length) return '';
  const COL={ok:'var(--good)',in:'var(--good)',partial:'var(--z-medium,#FF8C00)',fallback:'var(--text-2)',missing:'var(--danger)'};
  const full=m.filter(e=>e.status==='ok'||e.status==='in');
  const deg =m.filter(e=>e.status==='missing');
  const fb  =m.filter(e=>e.status==='fallback'||e.status==='partial');
  const chips=m.map(e=>`<span class="t-micro" style="color:${COL[e.status]||'var(--text-2)'}" title="${(e.note||e.status).replace(/"/g,'&quot;')}">${e.label||e.id}</span>`).join(' · ');
  let h=`<details style="margin-top:8px"><summary class="t-micro" style="cursor:pointer">`
    +`Data coverage — ${full.length}/${m.length} full`
    +(deg.length?`, ${deg.length} degraded`:'')+(fb.length?`, ${fb.length} fallback`:'')
    +`</summary><div class="s" style="margin:6px 0">${chips}</div>`;
  deg.concat(fb).forEach(e=>{ if(e.note) h+=`<div class="callout" data-kind="${e.status==='missing'?'warn':'info'}"><span class="mark">${e.status==='missing'?'!':'i'}</span><div class="body"><b>${e.label||e.id}</b> — ${e.note}</div></div>`; });
  return h+`</details>`;
}
function buildPanel(){
  // Nothing analysed yet — say so, and offer the example explicitly rather than
  // silently pretending someone else's run is yours.
  if(DOC.blank){
    // A RUN IN FLIGHT IS NOT AN EMPTY APP. Re-analysing an existing plan clears the map
    // first, and this panel then told the owner of a five-minute-old plan that there was
    // "nothing on the map" and invited them to set up a hunt — while their hunt was
    // already computing. Say what is actually happening instead.
    if(RUN_ACTIVE){
      document.getElementById('gate').innerHTML=
        `<div class="t-micro" style="margin-bottom:10px">${t('run.analysing','Analysing')}</div>
         <h2 class="t-h1" style="margin:0 0 8px;font-size:19px">${escHtml(PLAN_NAME||t('run.thisPlan','This plan'))}</h2>
         <p class="s" style="margin:0 0 14px">${t('run.inflight','Your analysis is running. The previous result was cleared so it cannot be mistaken for the new one — the map fills in as soon as the run finishes.')}</p>
         <button class="btn btn--secondary btn--block" id="goSetup">${t('run.watch','Watch progress in Setup')}</button>`;
      document.getElementById('method').innerHTML='';
      document.getElementById('list').innerHTML='';
      const g2=document.getElementById('goSetup'); if(g2) g2.onclick=()=>setTab('setup');
      return;
    }
    document.getElementById('gate').innerHTML=
      `<div class="t-micro" style="margin-bottom:10px">No analysis yet</div>
       <h2 class="t-h1" style="margin:0 0 8px;font-size:19px">Nothing on the map yet</h2>
       <p class="s" style="margin:0 0 14px">Draw a box in <b>Setup</b>, set your hunt dates and
          who's hunting, then run the analysis. It takes a few minutes and everything you see
          afterwards is computed for that box — not a sample.</p>
       <button class="btn btn--primary btn--block" id="goSetup">Set up a hunt →</button>
       <button class="btn btn--ghost btn--block" id="loadEx" style="margin-top:8px">
         Or load the Fire Lake example</button>`;
    document.getElementById('method').innerHTML='';
    document.getElementById('list').innerHTML='';
    const gs=document.getElementById('goSetup'); if(gs) gs.onclick=()=>setTab('setup');
    const lx=document.getElementById('loadEx');
    if(lx) lx.onclick=()=>{ const u=new URL(location.href); u.searchParams.set('example','1'); location.href=u.toString(); };
    return;
  }
  const g=DOC.legal, cf=DOC.confidence||null;
  document.getElementById('gate').innerHTML=
    `<div class="row" style="justify-content:space-between">
       <span class="t-micro" style="color:${g.diy_possible?'var(--good)':'var(--danger)'}">${g.diy_possible?t('ov.diy'):t('ov.restricted')}</span>
       ${cf?`<span class="row" style="gap:7px"><span class="t-micro">CONF ${Math.round(cf.score*100)}%</span>${confGauge(cf.score)}</span>`:''}
     </div>
     <div class="t-data" style="margin-top:6px;color:var(--text-2)">${g.zone?('ZONE '+g.zone):'ZONE NOT RESOLVED'} · ${g.north_of_52?'N':'S'} OF 52°N · ${(g.huntable_tenures||[]).join(', ')||'—'}</div>`
    + (DOC.access_unknown?`<div class="callout" data-kind="danger"><span class="mark">✕</span><div class="body">
        <b>No road network for this box — access not modelled</b>
        The road download timed out (large or road-dense area), so pack-out, hunter pressure
        and camp siting could not be computed, and no focus areas were ranked. This is a DATA
        gap, not a judgement about the ground. Try a smaller radius (≤40 km) and re-run.</div></div>`:'')
    + ((DOC.areas||[]).length===0&&!DOC.access_unknown?`<div class="callout" data-kind="warn"><span class="mark">!</span><div class="body">
        <b>No focus areas met the bar here</b>
        The model found no ground clearing its absolute thresholds in this box. That is a real
        answer, not an error — try a different area, a larger radius, or different dates.</div></div>`:'')
    + ((g.flags||[]).length?`<div class="callout" data-kind="warn"><span class="mark">!</span><div class="body"><b>${(g.flags||[]).length} thing${g.flags.length>1?'s':''} to confirm before you go</b>${(g.flags||[]).join('<br>')}</div></div>`:'')
    + (cf&&cf.caveats?`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${[].concat(cf.caveats).join(' ')}</div></div>`:'')
    + (DOC.strategy&&DOC.strategy.density_per_10km2?`<div class="s" style="margin-top:8px">Density ≈ <b class="mono">${DOC.strategy.density_per_10km2}</b> moose/10 km² (${DOC.strategy.density_is_estimate?'estimate':'survey'}) — expect long silences; coverage beats sitting.</div>`:'')
    + siteCompareBlock()
    + coverageBlock();
  const m=DOC.methodology;
  document.getElementById('method').innerHTML=
    `<details><summary class="t-micro" style="cursor:pointer">What I'm looking for</summary>
       <p class="s" style="margin:8px 0">${m.summary}</p>
       <div class="s"><b>Weighted:</b> ${(m.factors_weighted||[]).join('; ')}</div>
       ${(m.caveats||[]).map(c=>`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${c}</div></div>`).join('')}
     </details>`;
  let html='';
  // The season filter is a MAP control that the list has to honour too (T10.3) — a
  // sidebar still listing eight areas while the map shows four is the same "which of
  // these am I looking at" confusion the filter exists to end. A camp with nothing left
  // in it drops its heading rather than standing empty.
  DOC.camps.filter(inWindow).forEach(c=>{
    const mine=DOC.areas.filter(a=>a.camp===c.id&&inWindow(a)).sort((x,y)=>x.rank-y.rank);
    if(!mine.length) return;
    html+=`<div class="grouphead"><span class="g">Camp ${c.id}</span>
      <span class="g">${mine.length} areas · pack-in ≤ ${km(c.max_packin_km)}</span></div>`;
    mine.forEach(a=>{html+=areaCard(a);});
  });
  const list=document.getElementById('list'); list.innerHTML=html;
  list.querySelectorAll('.card').forEach(el=>el.onclick=()=>selectArea(+el.dataset.rank));
}
function areaCard(a){
  const dr=(a.stats||{}).dist_road_m||0;
  const boat=a.boat_required;
  const excl=a.status==='excluded';
  const far=boat || (SETUP.huntStyle==='vehicle' && dr>reachKm()*1000);
  const po=packout(a);
  // An EXCLUDED area is not a recommendation: it leads with WHY IT'S OUT instead of
  // why it scored, and carries no sites/routes (the engine didn't compute any). The
  // habitat evidence stays visible so the hunter can judge whether different kit is
  // worth bringing, and can still run a field analysis on it on demand.
  if(excl) return `<div class="card excluded" data-rank="${a.rank}"
      style="border-color:#5a2b26;background:linear-gradient(0deg,rgba(201,86,74,.05),rgba(201,86,74,.05))">
    <div class="top"><div class="badge" style="background:#3a1c19;color:#e29a92;border-color:#5a2b26">${a.rank}</div>
      <div class="ttl">Area ${a.rank}${windowTag(a)?` <span class="t-micro" style="opacity:.8">· ${escHtml(windowTag(a))}</span>`:''}</div><div class="val">${a.area_km2} km²</div></div>
    <div class="metaline"><span style="color:#e29a92;letter-spacing:.04em;font-size:11px">${t('ov.excluded','EXCLUDED')}</span>
      <span>${km(dr/1000)} to road</span>${a.conf?`<span>conf ${Math.round(a.conf.score*100)}%</span>`:''}</div>
    <div class="callout" data-kind="danger"><span class="mark">✕</span><div class="body">${a.excluded_reason||t('ov.exclDefault','Out of reach with the equipment you listed.')}</div></div>
    <div class="why">${(a.why||'').slice(0,160)}</div>
    ${(a.pros||[]).slice(0,2).map(p=>`<div class="ev" data-kind="pro"><span class="op">+</span><span class="txt">${p}</span></div>`).join('')}
    <div class="t-micro" style="margin-top:6px;opacity:.75">${t('ov.exclHint','No stands or routes computed here. Open it to run a field analysis anyway.')}</div>
  </div>`;
  // Evidence lines: six saturated green pills read as one green block; a hairline row
  // with a single coloured operator scans far faster.
  const ev=[]
    .concat((a.pros||[]).slice(0,4).map(t=>({k:'pro',t})))
    .concat((a.cons||[]).slice(0,3).map(t=>({k:'con',t})))
    .map(e=>`<div class="ev" data-kind="${e.k}"><span class="op">${e.k==='pro'?'+':'!'}</span><span class="txt">${e.t}</span></div>`).join('');
  return `<div class="card ${far?'dim':''}" data-rank="${a.rank}">
    <div class="top"><div class="badge ${a.rank<=2?'top':''}">${a.rank}</div>
      <div class="ttl">Area ${a.rank}${a.site&&(DOC.sites||[]).length>1?` <span class="t-micro" style="opacity:.8">· site ${a.site}</span>`:''}${
        windowTag(a)?` <span class="t-micro" style="opacity:.8">· ${escHtml(windowTag(a))}</span>`:''}</div>
      <div class="val">${a.area_km2} km²</div></div>
    <div class="metaline">${a.conf?confGauge(a.conf.score)+`<span>conf ${Math.round(a.conf.score*100)}%</span>`:''}
      <span>${km(dr/1000)} to road</span></div>
    ${a.habitat_score!=null?`<div class="axes">
      <div class="ax"><span class="k">${t('ov.habitat')}</span><span class="bar"><i style="width:${Math.round(a.habitat_score*100)}%"></i></span><span class="v">${a.habitat_score}</span></div>
      <div class="ax"><span class="k">${t('ov.packout')}</span><span class="bar"><i class="ret" style="width:${Math.round((a.retrieval_score||0)*100)}%"></i></span><span class="v">${a.retrieval_score}</span></div>
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
  // Area-scoped, so the rut read must be THIS area's window (T10.1) — not the
  // top-level one, which is window 1's on a multi-window run.
  const RUT=wsec(a,'rut')||{};
  const rutT=(RUT.targets&&RUT.targets[0])||null;
  const po=packout(a);
  const stat=(lbl,val)=>`<div class="stat"><span class="k">${lbl}</span><span class="v">${val}</span></div>`;
  const evRow=(k,t)=>`<div class="ev" data-kind="${k}"><span class="op">${k==='pro'?'+':'!'}</span><span class="txt">${t}</span></div>`;
  d.innerHTML=`<div class="sec" style="padding-bottom:0">
    <button class="btn btn--ghost btn--sm back" style="padding-left:0">${t('ov.allareas')}</button>
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
    <div class="t-micro" style="margin-bottom:9px">${t('ov.why')}</div>
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
    <div class="t-micro" style="margin-bottom:9px">Your dates &amp; the rut${windowLabel(a)}</div>
    <div class="rutdates">${(RUT.targets||[]).map(t=>
      `<span class="pill">${t.date} · ${t.phase} · ${Math.round(t.responsiveness*100)}%</span>`).join('')}</div>
    <p class="s" style="margin-top:9px">${rutT.guidance||''}</p>
    ${rutT.weather_note?`<div class="callout" data-kind="warn"><span class="mark">!</span><div class="body">Weather: ${rutT.weather_note}</div></div>`:''}
    ${RUT.phase_note?`<div class="callout" data-kind="info"><span class="mark">i</span><div class="body">${RUT.phase_note}</div></div>`:''}
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
  html+=`<div class="note">Pick a day, then <b>scrub the hour</b>: each site rings <b style="color:#2fbf5b">green</b> when that day's forecast wind fits its approach, <b style="color:#C9564A">red</b> when it fights you`+
    (w.days[0].is_proxy?' — but this is a <b>prior-year proxy</b> (hunt is months out), treat as rough':' (forecast — verify on the ground)')+
    `. Scrub into <b>first or last light</b> and the rings turn <b style="color:#FF00C8">magenta</b>: the <b>thermal drift wins</b> those windows, not the forecast — read the Thermal-drift layer and come in from below.</div>`;
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
  selectedHour=h;
  // #27 — scrubbing time re-evaluates every site: into the dawn/dusk drift windows the
  // rings flip to "thermal governs", midday they read the forecast-wind fit.
  if(selectedDay!=null && window._sites) applyWind();
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

const TENURE_WHY={
  pourvoirie_exclusive:'Pourvoirie à droits exclusifs — an outfitter holds exclusive hunting rights here. You cannot hunt it DIY; you would be hunting as their client or not at all.',
  pourvoirie:'Pourvoirie (without exclusive rights) — outfitter operates here but the land may still be open. Confirm before counting it in.',
  zec:'ZEC — open to you, but you must register and pay at the gate on the way in and out.',
  reserve_faunique:'Réserve faunique (SEPAQ) — open only by draw or reservation; you cannot simply drive in and hunt.',
  crown:'Terres du domaine de l\'État — general crown land, open to a Québec resident DIY.'};
function tenurePopup(lngLat,p){
  const closed=!(p.huntable===true||p.huntable==='true');
  new maplibregl.Popup().setLngLat(lngLat).setHTML(
    `<h4><span style="color:${closed?'#C9564A':'#E0A62E'}">${closed?'⃠':'▨'}</span> ${p.name||p.tenure}</h4>`+
    `<div class="s"><b style="color:${closed?'#E58077':'#E0A62E'}">${closed?'CLOSED to you — masked out of the ranking':'Open with conditions'}</b></div>`+
    `<div class="s" style="margin-top:4px">${TENURE_WHY[p.tenure]||p.tenure}</div>`+
    `<div class="s" style="margin-top:4px;opacity:.7">Tenure boundaries are from the MRNF layer and can lag reality — verify before you hunt.</div>`).addTo(map);
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
const LYR_MAP={feedEdge:['feedEdgeZones','feedEdgeZones-line'],areas:['areas-fill','areas-line','area-badges'],sites:['sites','sites-wind'],
  camps2:['camps'],staging:['staging'],routes:['route-best','route-hot'],access:['route-access'],
  water:['lakes','lakes-line','rivers'],crossings:['crossings'],
  roads:['roads','roads-case','roads-track','rail','trans'],
  trails:['trails'],
  boundaries:['boundaries'],
  shooters:['shooters','shooters-label','shooterLines'],
  scent:['scent','scent-label','scentArc'],
  thermal:['thermal'],
  huntZones:['huntZones'],
  refuge:['refugeZones'],
  funnel:['funnelZones'],
  browse:['browseZones'],
  browseCut:['browse_cut_zones','browse_cut_zones-line'],
  browseBurn:['browse_burn_zones','browse_burn_zones-line'],
  browseStand:['browse_stand_zones','browse_stand_zones-line'],
  browseLc:['browse_lc_zones','browse_lc_zones-line'],
  burns:['burnZones','burnZones-line'],
  cuts:['cutZones','cutZones-line'],
  wetland:['wetlandZones','wetlandZones-line'],beaver:['beaverPonds'],
  tenure:['tenureBlocked','tenureZones-line'],tenureOk:['tenureZones-line-ok'],
  leases:['leases'],
  modeRide:['route-ride-atv'],modeBoat:['route-ride-boat'],
  modeTrail:['route-foot-trail'],modeBush:['route-foot-bush'],
  modePortage:['route-portage']};

/* ============================================================================
   ONE ARRAY drives the panel row, the map paint and the legend meaning, so they
   cannot drift apart. Adding a layer is one entry; there is no second place.

   Two independent axes (SYMBOLOGY §1):
     kind — the TEXTURE: what kind of thing this is
     edge — the HONESTY axis: how much we know about where it stops
              none   → continuous field, NO STROKE AT ALL, soft feather only
              solid  → somebody surveyed that line (burn perimeters, tenure)
              dashed → we drew the edge ourselves and say so (hulls, borders)
   Never outline a guess: a crisp line around a DEM-inferred funnel converts a fuzzy
   probability into a surveyed boundary, and a hunter plans a stalk against it.
   ========================================================================== */
const LAYERS=[
 {k:'hz-high', group:'MODEL ZONES', panel:false, kind:'solid', edge:'none', name:'High likelihood',
  note:'Model score in the top band', hex:'#E2231A', icon:'target', on:true, hz:'high',
  count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='high').length},
 {k:'hz-medium', group:'MODEL ZONES', panel:false, kind:'solid', edge:'none', name:'Medium',
  note:'Scored, second band', hex:'#FF8C00', icon:'target', on:true, hz:'medium',
  count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='medium').length},
 {k:'hz-low', group:'MODEL ZONES', panel:false, kind:'solid', edge:'none', name:'Low',
  note:'Scored but not prioritised', hex:'#FFD400', icon:'target', on:true, hz:'low',
  count:()=>(DOC.hunt_zones||[]).filter(z=>z.cls==='low').length},
 {k:'refuge', group:'MODEL ZONES', kind:'cross', edge:'none', name:'Thermal refuge',
  note:'Cool midday bedding', hex:'#FF00C8', icon:'trees', on:true, lyr:'refuge',
  count:()=>(DOC.refuge_zones||[]).length},
 {k:'browse', group:'MODEL ZONES', kind:'stipple', edge:'none', name:'Browse / feeding',
  note:'Regen & riparian forage — the food itself', hex:'#8FB43A', icon:'leaf', on:false, lyr:'browse',
  count:()=>(DOC.browse_zones||[]).length},
 // #96 — the parts browse is made of, indented under it. Each is the SAME polygonizer
 // over one contributor's own raster, so switching off "satellite land cover" leaves
 // only ground backed by a surveyed, dated disturbance. A contributor with no data for
 // this AOI shows a count of 0 rather than disappearing: absent evidence is a fact.
 // GREEN RAMP, HARDEST EVIDENCE TO GUESS. They share the parent's stipple so they read
 // as the same KIND of thing, differing only in shade — bright saturated green where a
 // dated survey backs the ground, dull olive where it is a satellite's opinion. `sub`
 // indents them under Browse / feeding: they are parts of it, not siblings of it.
 {k:'browseCut', group:'MODEL ZONES', sub:'browse', kind:'stipple', edge:'none',
  name:'from dated cuts', note:'Logging polygons with a cut year, aged through the browse curve — the hardest browse evidence there is.',
  hex:'#8FE04A', on:false, lyr:'browseCut', count:()=>(DOC.browse_cut_zones||[]).length},
 {k:'browseBurn', group:'MODEL ZONES', sub:'browse', kind:'stipple', edge:'none',
  name:'from dated burns', note:'Mapped fire perimeters with a year. Peaks later than a cut — fire regenerates more slowly.',
  hex:'#5FBF57', on:false, lyr:'browseBurn', count:()=>(DOC.browse_burn_zones||[]).length},
 {k:'browseStand', group:'MODEL ZONES', sub:'browse', kind:'stipple', edge:'none',
  name:'from the stand map', note:'Surveyed stand species and canopy closure, but no date. Beats the satellite, loses to a dated disturbance.',
  hex:'#3E9A63', on:false, lyr:'browseStand', count:()=>(DOC.browse_stand_zones||[]).length},
 {k:'browseLc', group:'MODEL ZONES', sub:'browse', kind:'stipple', edge:'none',
  name:'from satellite land cover', note:'10 m land cover refined by greenness. Covers everywhere — and it is a guess everywhere it is used.',
  hex:'#9CA86B', on:false, lyr:'browseLc', count:()=>(DOC.browse_lc_zones||[]).length},
 {k:'burns', group:'MODEL ZONES', kind:'hatch', edge:'solid', name:'Burn regeneration',
  note:'Fire perimeters by age — browse peaks 15–22 yr after a burn. Strongest single predictor here.',
  hex:'#C97A2B', icon:'flame', on:false, lyr:'burns', count:()=>(DOC.burn_zones||[]).length},
 {k:'cuts', group:'MODEL ZONES', kind:'stipple', edge:'solid', name:'Recent cuts',
  note:'Logging cutblocks by age (écoforestière) — pale = fresh, bright green = 10–25 yr prime browse, dark = closing in. South of ~52°N.',
  hex:'#6FA83A', icon:'leaf', on:false, lyr:'cuts', count:()=>(DOC.cut_zones||[]).length},
 {k:'funnel', group:'MODEL ZONES', kind:'soft', edge:'none', name:'Funnels / passes',
  note:'A neck that travel is FORCED through — it must separate two real pieces of ground (a peninsula is narrow but leads nowhere) and join two places worth moving between, ideally feed on one side and cover on the other.',
  hex:'#FF8C00', icon:'fork', on:false, lyr:'funnel', count:()=>(DOC.funnel_zones||[]).length},

 // These were one "Hunt sites" row drawing four different icons — so the map showed
 // four symbols the legend never named, and you could not turn one off. They are four
 // different jobs at four different times of day; they get four rows.
 {k:'st-rut', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Calling positions',
  note:'Where you set up and call — stands of 30 min or more. Calling works through the seeking phase too, not just the peak.', hex:'#E2231A', icon:'megaphone',
  on:true, site:'rut_calling', count:()=>siteCount('rut_calling')},
 {k:'st-saline', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Feeding edge', lyr:'feedEdge',
  note:'Browse edge / riparian willow at first and last light. Not a detected salt lick — salines are regulated; check the zone.',
  hex:'#0047FF', icon:'droplets', on:true, site:'saline_blind', count:()=>siteCount('saline_blind')},
 {k:'st-glass', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Glassing knobs',
  note:'Computed viewshed — high ground worth sitting behind glass', hex:'#1F6F3F',
  icon:'binoculars', on:true, site:'glassing', count:()=>siteCount('glassing')},
 // Camp and staging were one row, so a vehicle hunter — who has no camp at all —
 // could not see or toggle the only pin that matters to them: where the truck goes.
 {k:'camps2', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Base camp',
  note:'Where you sleep. Spike hunts only — a vehicle hunt has no camp.',
  hex:'#C8963E', icon:'tent', on:true, lyr:'camps2',
  count:()=>(DOC.waypoints||[]).filter(w=>w.type==='base_camp').length||(DOC.camps||[]).length},
 {k:'staging', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Staging / parking',
  note:'Where you leave the truck — one per focus area, at its nearest road',
  hex:'#DCA94D', icon:'truck', on:true, lyr:'staging',
  count:()=>(DOC.waypoints||[]).filter(w=>w.type==='parking').length},
 {k:'shooters', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Shooter positions',
  note:'Where the SHOOTER sets up, downwind of its calling position, because a bull circles downwind to scent-check. The distance follows your method of take — a bow setup is much tighter than a rifle one.', hex:'#FFD400', icon:'target', on:true, lyr:'shooters',
  count:()=>'—'},
 {k:'scent', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Scent wicks',
  note:'Where to hang cow scent — across the arc a bull swings downwind to scent-check, short of the shooter so he stops in range. Moves with the wind.',
  hex:'#9BD1C4', icon:'target', on:false, lyr:'scent',
  count:()=>{const n=(window._sites||[]).filter(f=>f.properties.type==='rut_calling').length;
    return n?n*3:'—';}},
 {k:'areas', group:'SITES & FEATURES', kind:'dashed', edge:'dashed', name:'Focus-area outlines',
  note:'Plan extent — a hull we drew, not a surveyed edge', hex:'#CBD5DA', on:true, lyr:'areas',
  count:()=>(DOC.areas||[]).length},
 {k:'thermal', group:'SITES & FEATURES', kind:'line', edge:'dashed', name:'Thermal drift',
  note:'Modelled slope airflow — Field tab, zoom in to read it', hex:'#CBD5DA', dash:'dashed', on:false, lyr:'thermal', count:()=>'—'},

 // One "Routes" row used to cover three visually different lines, so the white
 // dashed access leg had no legend entry at all — you could see it and not name it.
 {k:'routes', group:'ACCESS & HYDRO', kind:'line', edge:'solid', name:'Hunt lines',
  note:'The best line to walk in on, from camp to the stand', hex:'#E2231A', icon:'route',
  on:true, lyr:'routes',
  count:()=>(DOC.routes||[]).filter(r=>(r.type||r.t)!=='route_access').length},
 {k:'access', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Access from staging',
  note:'Truck to the area — one short leg per focus area, from its own staging point',
  hex:'#CBD5DA', dash:'dashed', icon:'truck', on:false, lyr:'access',
  count:()=>(DOC.routes||[]).filter(r=>(r.type||r.t)==='route_access').length},
 {k:'roads', group:'ACCESS & HYDRO', kind:'line', edge:'solid', name:'Roads & rail',
  note:'Reference geography, not a model output', hex:'#CBD5DA', on:true, lyr:'roads',
  count:()=>(DOC.infra||[]).filter(o=>o.t!=='trail').length},
 {k:'trails', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Trails & sentiers',
  note:'Foot paths (OSM) plus official quad/snowmobile sentiers (AQréseau+). Not truck-drivable — but an ATV rides them, they beat bushwhacking, and moose travel them.', hex:'#9db36a',
  dash:'dashed', on:false, lyr:'trails', count:()=>(DOC.infra||[]).filter(o=>o.t==='trail').length},
 // These were one row describing only the red hatch, so the amber dashed boundary —
 // ZEC / réserve faunique, ground you CAN hunt but must register or book first —
 // drew on the map with no legend entry and no tooltip, and vanished when you
 // toggled "outfitter". Two different legal outcomes, two rows.
 {k:'tenure', group:'ACCESS & HYDRO', kind:'exclude', edge:'solid', name:'Closed to you',
  note:'Exclusive outfitter tenure — hatched red is masked out of the ranking entirely',
  hex:'#C9564A', icon:'ban', on:true, lyr:'tenure',
  count:()=>(DOC.tenure_zones||[]).filter(z=>z.huntable===false).length},
 {k:'tenure-ok', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Bookable ground',
  note:'ZEC or réserve faunique — you may hunt here, but register or reserve first',
  hex:'#E0A62E', dash:'dashed', icon:'milestone', on:true, lyr:'tenureOk',
  count:()=>(DOC.tenure_zones||[]).filter(z=>z.huntable!==false).length},
 // Leased shelters (T9.8). Deliberately in ACCESS & HYDRO next to the tenure rows and
 // deliberately NOT styled like them: tenure answers "may you hunt here", this answers
 // "who else is". A lease covers the building, not the country — the note says so,
 // because a red pin beside a "Closed to you" row would read as a closure.
 {k:'leases', group:'ACCESS & HYDRO', kind:'point', edge:'none', name:'Leased shelters',
  note:'Abris sommaires, chalets de villégiature and outfitter camps leased on crown land. Somebody hunts this ground every season — and thought it worth building on. Does NOT restrict where you may hunt.',
  hex:'#B8734A', icon:'home', on:false, lyr:'leases',
  count:()=>((DOC.leases||{}).points||[]).length},
 // TRAVEL MODE (T10.20). Reported: "I indicated on setup i had an ATV/SXS. On the
 // analysis, i can't see any difference between routes to be travelled on ATV vs things
 // to be walked." The engine now routes mode-aware and these name what it drew.
 {k:'mode-ride', group:'ACCESS & HYDRO', kind:'line', edge:'solid', name:'Ridden (ATV/SxS)',
  note:'Road and motorised sentier you ride. The machine starts where you do and stays where you step off it — you come back to it.',
  hex:'#E2A03F', on:true, lyr:'modeRide',
  count:()=>(DOC.routes||[]).filter(r=>(r.km_by_mode||{}).atv).length},
 {k:'mode-boat', group:'ACCESS & HYDRO', kind:'line', edge:'solid', name:'On the water',
  note:'Paddled or run under power. A motorboat launches only where a drivable road meets water; a canoe can be portaged in.',
  hex:'#2F86C4', on:true, lyr:'modeBoat',
  count:()=>(DOC.routes||[]).filter(r=>{const m=r.km_by_mode||{};return m.canoe||m.motor;}).length},
 {k:'mode-trail', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Walked — trail',
  note:'On foot along a road or cut line. Quiet, fast, and where moose travel too.',
  hex:'#CFE0A8', on:true, lyr:'modeTrail',
  count:()=>(DOC.routes||[]).filter(r=>(r.km_by_mode||{}).foot_trail).length},
 {k:'mode-bush', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Walked — bushwhack',
  note:'On foot off any line. This is the part you repeat carrying meat, so it is the number that matters on a pack-out.',
  hex:'#C98F6A', on:true, lyr:'modeBush',
  count:()=>(DOC.routes||[]).filter(r=>(r.km_by_mode||{}).foot_bush).length},
 {k:'mode-portage', group:'ACCESS & HYDRO', kind:'line', edge:'dashed', name:'Portage',
  note:'Carrying between road and water. The worst ground on any route — in with a canoe, out with the canoe AND the meat, several trips over the same yards. A route you can portage in on is not necessarily one you can pack a bull out on.',
  hex:'#D2691E', on:true, lyr:'modePortage',
  count:()=>(DOC.routes||[]).filter(r=>(r.km_by_mode||{}).portage).length},
 {k:'boundaries', group:'ACCESS & HYDRO', kind:'outline', edge:'dashed', name:'Borders & places',
  note:'Reference geography', hex:'#CBD5DA', on:true, lyr:'boundaries', count:()=>'—'},
 {k:'water', group:'ACCESS & HYDRO', kind:'line', edge:'solid', name:'Rivers & lakes',
  note:'Mapped hydrography (OSM)', hex:'#7FC4E8', icon:'waves', on:true, lyr:'water',
  count:()=>'—'},
 {k:'wetland', group:'ACCESS & HYDRO', kind:'stipple', edge:'solid', name:'Wetlands',
  note:'GRHQ marsh / bog / fen — a travel barrier that shapes funnels; slow on foot.',
  hex:'#3E8E7E', icon:'waves', on:false, lyr:'wetland', count:()=>(DOC.wetland_zones||[]).length},
 {k:'beaver', group:'SITES & FEATURES', kind:'point', edge:'none', name:'Beaver ponds',
  note:'GRHQ flowages — a rut hub: bulls scent-mark the wet edge, cows follow. Worth a stand.',
  hex:'#2FB5C4', icon:'droplets', on:false, lyr:'beaver', count:()=>(DOC.beaver_ponds||[]).length},
 {k:'crossings', group:'ACCESS & HYDRO', kind:'point', edge:'none', name:'River crossings',
  note:'On the access legs. Green = a mapped bridge · amber = fordable · red = assume a boat',
  hex:CROSS_BODY, icon:'waves',
  chips:[CROSS_CHIP.bridge,CROSS_CHIP.ford,CROSS_CHIP.boat],
  on:false, lyr:'crossings',
  count:()=>(DOC.crossings||[]).length},
];
const LAYER_GROUPS=['MODEL ZONES','SITES & FEATURES','ACCESS & HYDRO'];
let groupOpacity={'MODEL ZONES':0.55,'SITES & FEATURES':1,'ACCESS & HYDRO':1};

// E1: the PROSE for each layer — its name, its one-line note, its group — now travels in
// the contract as DOC.legend (contract.build → config/species/*.yaml), so the ENGINE, not
// this file, decides what a layer is called and how it's described. applyLegend() merges
// that prose onto LAYERS by key. The hardcoded strings above stay as a fallback for a blank
// doc or an older contract with no legend, so the app never renders nameless rows. Visual
// symbology (colour / icon / texture / edge) is NOT species-specific and stays here.
const _LEGEND_DEFAULTS=LAYERS.map(r=>({name:r.name,note:r.note,group:r.group}));
/* Row key → i18n key: 'st-rut' → 'lay.stRut'. Kept as a transform rather than a table
   so adding a layer cannot forget to add a mapping — it either has a translation or it
   falls through to the engine's English, never to nothing. */
const _layKey=k=>'lay.'+String(k).replace(/-([a-z])/g,(m,c)=>c.toUpperCase());
/* WHO OWNS THIS PROSE. The engine does, in English: config/species/*.yaml decides what
   a layer is called, so a new species relabels the whole UI with no app change. But the
   yaml is English-only, so a French reader was getting an English panel — the most
   visible part of the app, in the wrong language, for the user this is actually built
   for. So: English takes the engine's words; French takes ours where we have them, and
   falls back to the engine's rather than showing a bare key. */
function _legendText(key,fallback){
  // I18N.lang is a GETTER, not a method — calling it would throw, get swallowed, and
  // silently hand French text to English readers.
  try{ if(I18N && I18N.lang === 'en') return fallback; }catch(e){}
  const s=t(key,'__none__');
  return s==='__none__' ? fallback : s;
}
function applyLegend(){
  let rows=[]; try{ if(Array.isArray(DOC.legend)) rows=DOC.legend; }catch(e){}
  const byKey={}; rows.forEach(e=>{ if(e&&e.key) byKey[e.key]=e; });
  LAYERS.forEach((r,i)=>{
    const d=_LEGEND_DEFAULTS[i], e=byKey[r.k], lk=_layKey(r.k);
    r.name =_legendText(lk,      (e&&e.name)      ? e.name : d.name);
    r.note =_legendText(lk+'.n', (e&&e.note!=null) ? e.note : d.note);
    r.group=(e&&e.group) ? e.group : d.group;
  });
}

/* The panel swatch and the map tile come from ONE generator, so a hunter can never
   trust a swatch that doesn't match what's drawn. */
function layerCSS(kind,hex,dash){
  const a=(h,p)=>h+p;                                  // #RRGGBB + alpha hex
  switch(kind){
    case 'solid':   return `background:${hex};opacity:.34;box-shadow:inset 0 0 5px 2px ${a(hex,'1F')}`;
    case 'stipple': return `background-color:${a(hex,'18')};background-image:radial-gradient(${a(hex,'AA')} 1.4px,transparent 1.5px);background-size:7px 7px`;
    case 'cross':   return `background-image:repeating-linear-gradient(45deg,${a(hex,'88')} 0 1.5px,transparent 1.5px 6px),repeating-linear-gradient(-45deg,${a(hex,'88')} 0 1.5px,transparent 1.5px 6px)`;
    case 'soft':    return `background-image:radial-gradient(120% 100% at 50% 50%,${a(hex,'4D')} 0%,${a(hex,'1A')} 55%,transparent 100%)`;
    case 'hatch':   return `background-color:${a(hex,'18')};background-image:repeating-linear-gradient(45deg,${a(hex,'AA')} 0 2px,transparent 2px 7px);border:1.5px solid ${hex}`;
    case 'exclude': return `background-color:${a(hex,'22')};background-image:repeating-linear-gradient(135deg,${a(hex,'DD')} 0 3px,transparent 3px 6px);border:2px solid ${hex}`;
    case 'dashed':  return `border:1.5px dashed ${hex};background:none`;
    case 'outline': return `border:1.5px dashed ${a(hex,'66')};background:none`;
    default:        return '';
  }
}
function lpHTML(r){
  if(r.kind==='line')
    return `<span class="lp lp--line"><i style="border-top:2px ${r.dash||'solid'} ${r.hex}"></i></span>`;
  // BRACES. `if(r.kind==='point')` guarded only the `if(r.chips)` line, so the
  // point-badge return below it ran for EVERY row and the fill branch was unreachable
  // dead code. Every zone row — the browse stipple, the burn hatch, the tenure exclude
  // wash — was drawn in the panel as an icon badge, which is precisely what the comment
  // above layerCSS says must never happen: "a hunter can never trust a swatch that
  // doesn't match what's drawn". It was an invariant asserted in prose and not in code.
  if(r.kind==='point'){
    if(r.chips)
      return `<span class="lp lp--point lp--pair">${r.chips.map(c=>
        iconBadge(r.icon,r.hex,16,c)).join('')}</span>`;
    return `<span class="lp lp--point">${iconBadge(r.icon,r.hex,18)}</span>`;
  }
  return `<span class="lp lp--fill" style="${layerCSS(r.kind,r.hex,r.dash)}"></span>`;
}
/* Rounded-square badge, layer colour, halo, glyph colour COMPUTED from luminance
   so it never has to be hand-maintained (SYMBOLOGY §2). */
function glyphOn(hex){
  const n=parseInt(hex.slice(1),16);
  const L=(0.299*((n>>16)&255)+0.587*((n>>8)&255)+0.114*(n&255))/255;
  return L>0.55?'#0B0F0D':'#F2F5F6';
}
function iconBadge(name,hex,size,chip){
  const d=(window.TRANSECT_ICONS||{})[name];
  const s=size||24;
  const glyph=d?`<svg viewBox="0 0 24 24" width="${Math.round(s*0.58)}" height="${Math.round(s*0.58)}"
      fill="none" stroke="${glyphOn(hex)}" stroke-width="2.4" stroke-linecap="round"
      stroke-linejoin="round"><path d="${d}"/></svg>`:'';
  const dot=chip?`<i class="wpchip" style="background:${chip}"></i>`:'';
  return `<span class="wpb" style="width:${s}px;height:${s}px;background:${hex}">${glyph}${dot}</span>`;
}

let showMeaning=true;
let layersDismissed=false;   // set when YOU close it, so auto-open doesn't override you

/* COUNT RULE (SYMBOLOGY §0). NO DATA is load-bearing — it is the visible proof of
   "never render data you don't have", so it must mean exactly one thing: this source
   shipped ZERO geometry for this AOI. It must NOT be used for "nothing analysed yet",
   which is a different claim and was making all 18 rows read NO DATA on a blank start. */
function layerCount(r){
  if(DOC.blank) return {v:'—', state:'pending'};        // no analysis yet ≠ no data
  const n=r.count?r.count():null;
  if(n==='—'||n==null) return {v:'—', state:r.on?'on':'off'};   // continuous/uncountable
  if(n===0) return {v:t('lay.nodata','NO DATA'), state:'nodata'};
  return {v:String(n), state:r.on?'on':'off'};
}
function buildLayersDock(){
  const d=document.getElementById('layersDock');
  const rows=LAYERS.filter(r=>r.panel!==false).map(r=>({r,c:layerCount(r)}));
  const onCount=rows.filter(x=>x.r.on&&x.c.state!=='nodata').length;
  let h=`<div class="dhead"><h4>${t('lay.title')}</h4>
      <span class="t-micro" id="layOn">${onCount} ON</span>
      <button class="dclose" title="Close">✕</button></div>
    <div class="drow"><span class="t-micro">${t('lay.meaning')}</span>
      <label class="sw"><input type="checkbox" id="meaningOn" ${showMeaning?'checked':''}><i></i></label></div>
    <div class="dbody">`;
  LAYER_GROUPS.forEach(g=>{
    const gr=rows.filter(x=>x.r.group===g);
    const live=gr.filter(x=>x.c.state!=='nodata');
    const on=live.filter(x=>x.r.on).length;
    const tri = on===0?'none':(on===live.length?'all':'partial');
    h+=`<div class="grouphead2" data-g="${g}">
        <button class="master" data-tri="${tri}" title="Toggle all">${tri==='all'?'✓':(tri==='partial'?'–':'')}</button>
        <span class="glabel">${g}</span><span class="gcount">${on} / ${live.length}</span>
        <input class="gop" type="range" min="10" max="100" value="${Math.round(groupOpacity[g]*100)}" data-g="${g}" title="Group opacity"></div>`;
    gr.forEach(({r,c})=>{
      const dis = c.state==='nodata' || c.state==='pending';
      h+=`<label class="layer-row" data-k="${r.k}" data-state="${c.state}" data-edge="${r.edge}"${r.sub?` data-sub="${r.sub}"`:''}>
        <input type="checkbox" ${r.on&&!dis?'checked':''} ${dis?'disabled':''}>
        ${lpHTML(r)}
        <span class="lmeta"><span class="name">${r.name}</span>${showMeaning&&r.note?`<span class="note">${r.note}</span>`:''}</span>
        <span class="count">${c.v}</span></label>`;
    });
  });
  d.innerHTML=h+`</div>`;
  d.querySelector('.dclose').onclick=()=>{layersDismissed=true;closeDocks();};
  d.querySelector('#meaningOn').onchange=e=>{showMeaning=e.target.checked;buildLayersDock();openDock('layersDock','railLayers');};
  // group master: tri-state toggle
  d.querySelectorAll('.master').forEach(b=>b.onclick=e=>{
    e.preventDefault(); e.stopPropagation();
    const g=b.closest('.grouphead2').dataset.g;
    const gr=LAYERS.filter(r=>r.group===g && r.panel!==false && layerCount(r).state!=='nodata' && layerCount(r).state!=='pending');
    const allOn=gr.every(r=>r.on);
    gr.forEach(r=>{ r.on=!allOn; applyLayer(r); });
    buildLayersDock(); openDock('layersDock','railLayers');
  });
  d.querySelectorAll('.gop').forEach(sl=>sl.oninput=e=>{
    const g=e.target.dataset.g; groupOpacity[g]=+e.target.value/100;
    LAYERS.filter(r=>r.group===g).forEach(applyLayer);
  });
  // THE PANEL IS THE TRUTH. applyLayer() only ever ran from a click, so nothing
  // reconciled what the map is drawing with what the checkboxes say — and every
  // applyDoc() rebuilds this panel. Any drift between the two then persisted: a row
  // reading OFF over a layer still painting (reported for Trails & sentiers), or the
  // reverse. Worse, a row whose count is 0 renders DISABLED and gets no handler at all,
  // so clicking it silently does nothing forever.
  //
  // Reconciling on every build makes the panel authoritative by construction, whatever
  // caused the drift. A disabled row is forced hidden: there is nothing to show, and
  // leaving it painted is how a layer becomes unturn-off-able.
  d.querySelectorAll('.layer-row').forEach(row=>{
    const r0=LAYERS.find(x=>x.k===row.dataset.k);
    if(r0 && r0.lyr){
      const dis0=row.querySelector('input').disabled;
      setVis(LYR_MAP[r0.lyr], !!r0.on && !dis0);
    }
  });
  d.querySelectorAll('.layer-row').forEach(row=>{
    const cb=row.querySelector('input'); if(cb.disabled) return;
    cb.onchange=()=>{
      const r=LAYERS.find(x=>x.k===row.dataset.k); if(!r) return;
      r.on=cb.checked; row.dataset.state=r.on?'on':'off';
      applyLayer(r); refreshLayerHeader();
    };
    // hovering a row emphasises that layer on the map, and vice versa
    row.onmouseenter=()=>emphasiseLayer(row.dataset.k,true);
    row.onmouseleave=()=>emphasiseLayer(row.dataset.k,false);
  });
}
/* The sites layer is one MapLibre layer drawing several icons, so per-type rows
   drive a filter rather than a visibility flag. */
function siteCount(t){ return (DOC.waypoints||[]).filter(w=>w.type===t).length; }
function applySiteFilter(){
  if(!map.getLayer('sites')) return;
  const on=LAYERS.filter(r=>r.site&&r.on).map(r=>r.site);
  if(!on.length){ setVis(['sites','sites-wind'],false); return; }
  setVis(['sites','sites-wind'],true);
  const f=['in',['get','type'],['literal',on]];
  map.setFilter('sites',f);
  if(map.getLayer('sites-wind')) map.setFilter('sites-wind',f);
}
function refreshLayerHeader(){
  const el=document.getElementById('layOn'); if(!el) return;
  el.textContent=LAYERS.filter(r=>r.panel!==false&&r.on&&layerCount(r).state!=='nodata').length+' ON';
}
function applyLayer(r){
  if(r.hz){ applyHuntZoneFilter(); return; }
  if(r.site){ applySiteFilter(); return; }
  if(!r.lyr) return;
  setVis(LYR_MAP[r.lyr], r.on);
  if(r.lyr==='browse') showBrowse=r.on;
  if(r.lyr==='thermal'&&r.on){const hr=document.getElementById('hour');updateThermal(hr?+hr.value:12);}
  // group opacity applies to the fill of model zones
  const op=groupOpacity[r.group]!=null?groupOpacity[r.group]:1;
  (LYR_MAP[r.lyr]||[]).forEach(id=>{
    if(!map.getLayer(id)) return;
    const ty=map.getLayer(id).type;
    try{
      if(ty==='fill') map.setPaintProperty(id,'fill-opacity',(r.kind==='solid'?FILL_ALPHA:0.9)*op);
    }catch(e){}
  });
}
function emphasiseLayer(k,on){
  const r=LAYERS.find(x=>x.k===k); if(!r||!r.lyr) return;
  (LYR_MAP[r.lyr]||[]).forEach(id=>{
    if(!map.getLayer(id)) return;
    try{
      if(map.getLayer(id).type==='symbol')
        map.setLayoutProperty(id,'icon-size',on?1.25:['interpolate',['linear'],['zoom'],8,0.7,11,1.05,13,1.45,15,1.9]);
    }catch(e){}
  });
}
function applyHuntZoneFilter(){
  const on=LAYERS.filter(r=>r.hz&&r.on).map(r=>r.hz);
  ['huntZones'].forEach(id=>map.getLayer(id)&&
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
/* TERRAIN IS DERIVED FROM PITCH — one state, not two (T10.11).
   Two independent things used to wear the name "3D": the camera, which right-drag
   tilts because the map is built with maxPitch:80, and the terrain mesh, which only
   `setTerrain` turns on and which only the #terr3d checkbox ever called. So tilting
   gave you a pitched FLAT map with a dead exaggeration slider — 3D that isn't 3D.
   Now pitch is the ONLY input: past the threshold the mesh is on, at 0 it is released,
   and the checkbox is just a shortcut that tilts the camera for you. */
const TERRAIN_PITCH=12;
let _terrExagApplied=null;                 // what setTerrain was last given, or null
function applyTerrain(){
  const want=map.getPitch()>TERRAIN_PITCH;
  // The camera is the truth and the chip follows it immediately, even if the mesh has
  // to wait a frame — what the hunter sees tilt is what the chip should say.
  terrOn=want;
  syncBaseChip();
  const cb=document.getElementById('terr3d'); if(cb) cb.checked=want;
  try{
    // Only touch the mesh when something actually changed: `pitch` fires every frame of
    // an easeTo, and setTerrain per frame is a rebuild per frame.
    if(want && _terrExagApplied!==terrExag){
      map.setTerrain({source:'dem',exaggeration:terrExag}); _terrExagApplied=terrExag;
    } else if(!want && _terrExagApplied!==null){
      map.setTerrain(null); _terrExagApplied=null;
    }
  }catch(e){
    // setTerrain THROWS "Style is not done loading" rather than queueing, and a pitch
    // event can absolutely arrive during a window where it does — on open, or while the
    // 30-odd plan sources are still settling after a run. An exception thrown inside a
    // map listener is not a contained failure.
    //
    // Retry on `idle`, NOT on `load`. `load` fires once, but isStyleLoaded() drops back
    // to false on every ordinary source update, so a `load` guard would silently drop
    // terrain for anyone who tilts just after a plan opens — the same "3D that isn't 3D"
    // this ticket is about, wearing a different hat. `idle` fires every time the map
    // settles, so the retry is always available and can never busy-loop.
    map.once('idle',applyTerrain);
  }
}
function buildBaseDock(){
  const d=document.getElementById('baseDock');
  let h=`<div class="dhead"><h4>${t('base.title')}</h4><button class="dclose" title="Close">✕</button></div><div class="dbody">`;
  h+=`<div class="grouplabel">${t('base.title')}</div>`;
  BASEMAPS.forEach(b=>{
    const on=curBase===b;
    h+=`<div class="baserow ${on?'on':''}" data-base="${b}">
      <span class="bthumb" style="background:${BASE_SWATCH[b]}"></span>
      <span class="bmeta"><span class="bname">${BASE_LABEL[b]}</span>
        <span class="bspec">${BASE_SPEC[b]||''}</span></span>
      ${on?'<span class="btag">ACTIVE</span>':''}</div>`;
  });
  h+=`<div class="drow"><span class="t-micro">${t('base.opacity')}</span>
        <input id="baseOpacity" type="range" min="20" max="100" step="5" value="${Math.round(baseOpacity*100)}" style="width:120px"></div>`;
  h+=`<div class="grouplabel">${t('base.terrain')}</div>
      <div class="drow"><span class="t-micro">${t('base.3d')}</span>
        <label class="sw"><input type="checkbox" id="terr3d" ${terrOn?'checked':''}><i></i></label></div>
      <div class="drow"><span class="t-micro">Exaggeration <b class="mono" id="exagVal">${terrExag.toFixed(1)}×</b></span>
        <input id="terrExag" type="range" min="1" max="3" step="0.1" value="${terrExag}" style="width:120px"></div>`;
  h+=`<div class="grouplabel">${t('base.more')}</div>`;
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
  // The checkbox no longer OWNS terrain — it tilts the camera, and the pitch handler
  // turns the mesh on. That is what makes the checkbox and a right-drag the same act.
  d.querySelector('#terr3d').onchange=e=>{ map.easeTo({pitch:e.target.checked?60:0}); };
  d.querySelector('#terrExag').oninput=e=>{
    terrExag=+e.target.value; d.querySelector('#exagVal').textContent=terrExag.toFixed(1)+'×';
    applyTerrain(); };
}
/* ---------------------------------------------------------------------------
   SYMBOLOGY §4 — TOOLBARS.
   One principle: persistent controls live in a narrow icon rail; everything
   transient is a card anchored to the control that opened it. Nothing floats
   without a parent.

   Entry points, and they are NOT interchangeable:
     • Hunting layers  → its own pill at left:420 top:88, beside the sidebar.
     • Model surface   → view rail, mountain glyph. Shows/hides huntability.
     • Area statistics → view rail, crosshair. Follows the cursor.
     • Basemap         → the SAT/2D chip in the bottom-right map controls.
   An earlier revision hung Layers and Basemap off the tool rail, which put
   three unrelated things behind two buttons and left the surface unreachable.
--------------------------------------------------------------------------- */
const ANCHOR={
  layersDock:()=>({left:420,top:142}),                       // under the Layers pill
  baseDock:  ()=>({right:70,bottom:12}),                     // beside the SAT chip
  surfDock:  ()=>({right:70,top:railTop('surface')})         // aligned to its own rail button
};
/* the tooltip/readout slot: top = 22px TOOLS cap + index × 40px row.
   A tooltip that appears in a fixed spot regardless of which button you
   hovered is worse than no tooltip — this was a real defect in rev 2. */
const TOOL_DEFS=[
  {k:'dist',    icon:'ruler2',   name:'Measure',        hint:'Click points on the map for a running distance. Double-click to finish.'},
  {k:'area',    icon:'pentagon', name:'Area',           hint:'Draw a polygon — reports hectares and km².'},
  {k:'line',    icon:'linedraw', name:'Draw line',      hint:'Freehand line for a boundary or a note to yourself. Shows its length.'},
  {k:'route',   icon:'route',    name:'Build route',    hint:'Multi-point access route at 2.5 km/h bushwhack. Exports its own GPX.'},
  {k:'waypoint',icon:'pin',      name:'Drop pin',       hint:'Log fresh sign or a wallow. Feeds the re-ranking loop.'},
  {k:'wind',    icon:'wind',     name:'Wind calendar',  hint:'Per-day forecast wind against each stand’s optimal approach.'}
];
const VIEW_DEFS=[
  {k:'surface', icon:'mountain', name:'Model surface',   hint:'Show or hide the huntability surface. Predicted moose ground — not terrain.'},
  {k:'stats',   icon:'crosshair',name:'Area statistics', hint:'Score breakdown, land-cover mix and confidence for whatever is under the cursor.'}
];
/* Below the divider: the drawings-list toggle. Clear-all lives INSIDE the panel —
   a destructive one-click button on the rail was a misfire waiting to happen. */
const EXTRA_DEFS=[
  {k:'drawings', icon:'listdraw', name:'My drawings', hint:'Show or hide your drawings list — rename, restyle, hide or delete each drawing there. Clear all lives in the panel.'}
];
const TOOLS_CARD_H=22+TOOL_DEFS.length*40+2;
/* "top = 22 + index x 40" in the spec is just "aligned to that button's own
   row". Reading the button's real rect says the same thing and cannot drift when
   the rail gains or loses a button — which is exactly how the first attempt at
   this broke (the view rail landed 74px on top of the tool rail). */
function railTop(k){
  const b=document.querySelector(`#railStack button[data-k="${k}"]`);
  if(b) return Math.round(b.getBoundingClientRect().top);
  const ti=TOOL_DEFS.findIndex(t=>t.k===k);
  return ti>=0 ? 76+22+ti*40 : 76;
}
function railIcon(name,size){
  const d=(window.TRANSECT_ICONS||{})[name]||'';
  return `<svg viewBox="0 0 24 24" width="${size||18}" height="${size||18}" fill="none"
    stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
}

/* A card must appear where you clicked, so every dock declares its anchor. */
function openDock(id,btnId){
  closeDocks(id);
  const d=document.getElementById(id); if(!d) return;
  const a=(ANCHOR[id]||(()=>({right:70,top:142})))();
  d.style.left  = a.left  !=null ? a.left+'px'  : 'auto';
  d.style.right = a.right !=null ? a.right+'px' : 'auto';
  d.style.top   = a.top   !=null ? a.top+'px'   : 'auto';
  d.style.bottom= a.bottom!=null ? a.bottom+'px': 'auto';
  d.classList.remove('hidden');
  const b=btnId&&document.getElementById(btnId); if(b) b.classList.add('on');
  refreshLayersPill();
}
const DOCK_BTN={layersDock:'layersPill',baseDock:'mcSat',surfDock:'viewSurface'};
function closeDocks(except){
  Object.keys(DOCK_BTN).forEach(id=>{
    if(id===except) return;
    const d=document.getElementById(id); if(d) d.classList.add('hidden');
    const b=document.getElementById(DOCK_BTN[id]); if(b) b.classList.remove('on');
  });
  refreshLayersPill();
}
function toggleDock(id,btnId){
  const d=document.getElementById(id); if(!d) return;
  if(!d.classList.contains('hidden')){
    if(id==='layersDock') layersDismissed=true;
    closeDocks();
  } else {
    if(id==='layersDock'){ layersDismissed=false; buildLayersDock(); }
    else if(id==='baseDock') buildBaseDock();
    else if(id==='surfDock') buildSurfDock();
    openDock(id,btnId||DOCK_BTN[id]);
  }
}

/* ---------------- rails: persistent tools, transient cards ------------- */
function buildTools(){
  /* Layers pill — the only door to the hunting layers, parked beside the
     sidebar rather than in the right rail, because it belongs to the analysis
     you are reading on the left, not to the map instruments on the right. */
  const pill=document.getElementById('layersPill');
  pill.innerHTML=`<span class="bars"><i></i><i></i><i></i></span>
    <span class="pmeta"><span class="pcap">${t('pill.cap','HUNT MAP')}</span>
      <span class="pname">${t('pill.name','Layers')}</span></span>
    <span class="pcount" id="pillCount">—</span>`;
  pill.onclick=()=>toggleDock('layersDock','layersPill');

  /* TOOL RAIL — right:12 top:76, 46px, mono cap + 40px hairline-divided rows */
  const rail=document.getElementById('rail');
  rail.innerHTML=`<div class="railcap">${t('rail.tools','TOOLS')}</div>`+
    TOOL_DEFS.map(x=>`<button data-tool="${x.k}" data-k="${x.k}">${railIcon(x.icon)}</button>`).join('')+
    `<div class="sep"></div>
     <button id="drawListBtn" data-k="drawings">${railIcon('listdraw')}</button>`;

  /* VIEW RAIL — directly beneath, same 46px card, two buttons */
  const vr=document.getElementById('viewRail');
  vr.innerHTML=VIEW_DEFS.map(v=>`<button id="view${v.k[0].toUpperCase()+v.k.slice(1)}" data-k="${v.k}">${railIcon(v.icon)}</button>`).join('');

  /* hover tooltip / live readout, aligned to the hovered button's own row */
  [...rail.querySelectorAll('button'),...vr.querySelectorAll('button')].forEach(b=>{
    b.onmouseenter=()=>showRailTip(b.dataset.k);
    b.onmouseleave=()=>hideRailTip();
  });
  rail.querySelectorAll('button[data-tool]').forEach(b=>b.onclick=()=>{
    if(b.dataset.tool==='wind'){ toggleWeather(); return; }
    setDrawTool(drawTool===b.dataset.tool?null:b.dataset.tool);
    showRailTip(b.dataset.k);
  });
  document.getElementById('drawListBtn').onclick=()=>{
    window.drawMgrHidden=!window.drawMgrHidden;
    document.getElementById('drawListBtn').classList.toggle('on',!window.drawMgrHidden);
    renderDrawManager();
  };
  document.getElementById('viewSurface').onclick=()=>toggleDock('surfDock','viewSurface');
  document.getElementById('viewStats').onclick=()=>{
    statsOn=!statsOn;
    document.getElementById('viewStats').classList.toggle('on',statsOn);
    if(!statsOn) hideStats();
  };

  /* MAP CONTROLS — right:12 bottom:12. Compass only once rotated; zoom clamped
     3–17 (past 17 the model is finer than its own inputs); SAT chip is both a
     status readout and the door to Basemap; locate centres the AOI, not you. */
  const mc=document.getElementById('mapctl');
  mc.innerHTML=`<button id="mcN" class="round" title="${t('ctl.north','North up')}">N</button>
    <div class="zoomcard"><button id="mcIn" title="${t('ctl.in','Zoom in')}">+</button>
    <button id="mcOut" title="${t('ctl.out','Zoom out')}">−</button></div>
    <button id="mcSat" class="satchip" title="${t('ctl.base','Basemap')}"></button>
    <button id="mcLoc" title="${t('ctl.locate','Centre the area')}">${railIcon('crosshair',15)}</button>`;
  document.getElementById('mcN').onclick=()=>map.easeTo({bearing:0,pitch:0});
  document.getElementById('mcIn').onclick=()=>map.zoomIn();
  document.getElementById('mcOut').onclick=()=>map.zoomOut();
  document.getElementById('mcSat').onclick=()=>toggleDock('baseDock','mcSat');
  document.getElementById('mcLoc').onclick=()=>fitAOI();
  const rb=document.getElementById('rescopeBtn'); if(rb) rb.onclick=()=>rescopeWithDrawnAreas();
  const syncCompass=()=>{
    const b=map.getBearing(), p=map.getPitch();
    document.getElementById('mcN').style.display=(Math.abs(b)>0.5||p>0.5)?'grid':'none';
    document.getElementById('mcN').style.transform=`rotate(${-b}deg)`;
  };
  map.on('rotate',syncCompass); map.on('pitch',syncCompass); syncCompass();
  // Same listener the compass uses, because it is the same fact: how the camera is
  // sitting. Terrain follows it, and the chip reports it.
  map.on('pitch',applyTerrain); applyTerrain();
  const syncZoom=()=>{
    const z=map.getZoom();
    document.getElementById('mcIn').disabled = z>=map.getMaxZoom()-0.01;
    document.getElementById('mcOut').disabled= z<=map.getMinZoom()+0.01;
  };
  map.on('zoom',syncZoom); syncZoom();

  setupDraw();
  buildStatsCard();
  calibrateImagery();
  buildIdentify();
  toggleWeather(false);
  buildLayersDock();          // built, but shown/hidden per tab (see syncDocks)
  refreshLayersPill();
}
function refreshLayersPill(){
  const p=document.getElementById('layersPill'); if(!p) return;
  const open=!document.getElementById('layersDock')?.classList.contains('hidden');
  p.classList.toggle('on',open);
  const c=document.getElementById('pillCount');
  if(c) c.textContent=LAYERS.filter(r=>r.panel!==false&&r.on&&layerCount(r).state==='on').length+' '+t('lay.on','ON');
}
function showRailTip(k){
  const def=TOOL_DEFS.concat(EXTRA_DEFS,VIEW_DEFS).find(x=>x.k===k);
  const tip=document.getElementById('railTip'); if(!tip) return;
  if(!def){ tip.classList.add('hidden'); return; }
  // A tool with a running value replaces its tooltip with a live readout,
  // and a measurement always states its assumption.
  const live=(k===drawTool)&&drawReadout&&drawReadout();
  tip.style.top=railTop(k)+'px';
  tip.innerHTML= live
    ? `<div class="tipcap">${t('tip.measuring','MEASURING')}<span>${t('tip.esc','ESC TO EXIT')}</span></div>
       <div class="tiptiles">${live.tiles.map(v=>`<span>${v}</span>`).join('')}</div>
       <div class="tipnote">${live.note}</div>`
    : `<div class="tipname">${def.name}</div><div class="tipnote">${def.hint}</div>`
      + (k==='waypoint'
        ? `<div class="tipcoord"><input id="wpCoord" placeholder="or type lat, lon" />
             <button id="wpCoordGo">Drop</button></div>` : '');
  tip.classList.remove('hidden');
  // Type a coordinate instead of clicking — for a point off a GPS or a report.
  const ci=document.getElementById('wpCoord');
  if(ci){
    tip.style.pointerEvents='auto';           // the tip is normally click-through
    const go=()=>{
      const m=ci.value.split(/[, ]+/).map(Number).filter(n=>!isNaN(n));
      if(m.length!==2){ ci.style.borderColor='var(--danger)'; return; }
      const [lat,lon]=m;
      // Add the pin DIRECTLY. Routing through onDrawClick no-ops unless the waypoint tool
      // is armed (`if(!drawTool) return`) — but this coord tip can be open on hover without
      // arming it, so the map recentred and NO marker appeared (user-reported). Ensure the
      // annot source/layers exist, drop the point, render it.
      if(typeof setupDraw==='function') setupDraw();
      drawSaved.push({type:'Feature',geometry:{type:'Point',coordinates:[lon,lat]},
        properties:{label:'WP'+(drawSaved.filter(f=>f.geometry.type==='Point').length+1)}});
      renderAnnot();
      map.flyTo({center:[lon,lat],zoom:Math.max(map.getZoom(),11)});
      ci.value='';
    };
    document.getElementById('wpCoordGo').onclick=go;
    ci.onkeydown=e=>{ if(e.key==='Enter'){ e.preventDefault(); go(); } };
    ci.onclick=e=>e.stopPropagation();
  } else {
    tip.style.pointerEvents='';
  }
}
function hideRailTip(){
  const tip=document.getElementById('railTip'); if(!tip) return;
  if(drawTool){ showRailTip(drawTool); return; }   // keep a live readout up
  tip.classList.add('hidden');
}
/* The wind calendar is a tool now, so its strip is a tool surface: off until you
   ask for it. It also used to sit on top of the mandatory scale bar. */
let weatherWanted=false;
function toggleWeather(force){
  const w=document.getElementById('weather'); if(!w) return;
  const show = force!=null ? force : w.classList.contains('hidden');
  if(force==null) weatherWanted=show;      // an explicit click is a preference; a tab switch is not
  w.classList.toggle('hidden',!show);
  document.body.classList.toggle('weather-on',show);
  if(show) document.documentElement.style.setProperty('--weather-h',
    Math.round(w.getBoundingClientRect().height)+'px');
  document.querySelector('#rail button[data-tool="wind"]')?.classList.toggle('on',show);
}
/* Layers belongs with the analysis, not with the location picker: hidden on Setup and
   Brief, open on Overview and Field — unless you closed it yourself. */
function syncDocks(tab){
  const onMap = (tab==='overview' || tab==='field');
  const rail=document.getElementById('rail'), vr=document.getElementById('viewRail'),
        pill=document.getElementById('layersPill'), mc=document.getElementById('mapctl');
  [rail,vr,mc].forEach(e=>{ if(e) e.style.display=''; });   // tools are always visible
  if(pill) pill.classList.toggle('hidden',!onMap);
  if(!onMap){ closeDocks(); return; }
  if(layersDismissed) return;
  const d=document.getElementById('layersDock');
  if(d && d.classList.contains('hidden')){ buildLayersDock(); openDock('layersDock','layersPill'); }
}
/* the draw/measure strip is now part of the persistent right rail (buildTools) */
/* ---- OnX-style field tools: distance / line / area / route / waypoint ---- */
let drawTool=null, drawPts=[], drawWpts=[], drawSaved=[];
let drawEditId=null;                       // id of the drawing whose vertices are being dragged
const hiddenDrawTypes=new Set();           // drawing TYPES hidden from the legend (area/line/…)
function _styledLine(coords,src){ return {type:'Feature',geometry:{type:'LineString',coordinates:coords},
  properties:{id:src.id,stroke:src.stroke,lo:src.lo!=null?src.lo:1,lw:src.lw!=null?src.lw:3.4,style:src.style||'solid',label:src.label||''}}; }
function _vertFeat(ll,src,grab){ return {type:'Feature',geometry:{type:'Point',coordinates:ll},
  properties:{vertex:1,grab:grab?1:0,id:src.id,stroke:src.stroke||'#5fe6ff'}}; }
function _vertsOf(f){ const g=f.geometry;
  if(g.type==='Point') return [g.coordinates];
  if(g.type==='LineString') return g.coordinates.slice();
  if(g.type==='Polygon') return (g.coordinates[0]||[]).slice(0,-1);   // drop the closing dup
  return []; }
function _drawById(id){ return drawSaved.find(f=>f.properties&&f.properties.id===id); }
function polyKm(pts){let d=0;for(let i=1;i<pts.length;i++)d+=hav(pts[i-1],pts[i]);return d;}
function ringKm2(ring){ // spherical polygon area
  if(ring.length<3)return 0; const R=6371,d2r=Math.PI/180; let s=0;
  for(let i=0;i<ring.length;i++){const p=ring[i],q=ring[(i+1)%ring.length];
    s+=(q[0]-p[0])*d2r*(2+Math.sin(p[1]*d2r)+Math.sin(q[1]*d2r));}
  return Math.abs(s*R*R/2);
}
function areaFmt(km2){ return UNITS==='imperial'?(km2*0.386102).toFixed(2)+' mi²':km2.toFixed(2)+' km²'; }
// ONE `annot` source, legacy $type filters, plain setData — the exact rendering that worked at
// commit 7421749. Per-object colour/weight/opacity ride on data-driven PAINT (safe: the fill
// proved data-driven paint renders). A `line` layer does not paint polygon RINGS, so renderAnnot
// emits an explicit boundary LineString for every polygon — that is the real cure for the
// "area outline vanishes at the 3rd point" report. No source-splitting, no recreate/prime, no
// per-style layer split (all of which caused regressions and could not be verified reliably).
// The draw FILL lives in its OWN source (`annotFill`), separate from the lines/points (`annot`).
// A POLYGON sharing the geojson source with the line/point features BLANKS the whole drawing the
// instant it appears — that is the "everything vanishes at the 3rd point when it becomes a polygon"
// bug. It was originally fixed in e8148c7 and regressed when the sources were merged. Keep apart.
const _ANNOT_LAYERS=['annot-line-case','annot-line','annot-line-dash','annot-line-dot','annot-pt','annot-label'];
const _ANNOTFILL_LAYERS=['annot-fill'];
function _addAnnotFillLayers(){
  // Insert the fill BELOW the outline casing so the outline/vertices always sit on top of it.
  const before=map.getLayer('annot-line-case')?'annot-line-case':undefined;
  map.addLayer({id:'annot-fill',type:'fill',source:'annotFill',filter:['==','$type','Polygon'],
    paint:{'fill-color':['coalesce',['get','fill'],'#4de1ff'],'fill-opacity':['coalesce',['get','fo'],0.28]}}, before);
}
function _addAnnotLayers(){
  const LW=['coalesce',['get','lw'],3.4], SC=['coalesce',['get','stroke'],'#5fe6ff'], LO=['coalesce',['get','lo'],1];
  // A dark casing under the bright outline so the drawing reads on any background. Both line layers
  // match ONLY LineStrings — every polygon emits its own boundary LineString into `annot`.
  map.addLayer({id:'annot-line-case',type:'line',source:'annot',filter:['==','$type','LineString'],
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':'#08131a','line-width':['+',LW,2.6],'line-opacity':['*',0.6,LO]}});
  // One line layer per outline STYLE (line-dasharray is a constant, not data-driven). Filters are
  // PURE expression syntax — never mix legacy '$type' with ['get',…] in one filter (silent fail).
  const isLine=['==',['geometry-type'],'LineString'];
  const styleIs=v=>['all',isLine,['==',['coalesce',['get','style'],'solid'],v]];
  map.addLayer({id:'annot-line',type:'line',source:'annot',filter:styleIs('solid'),
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':SC,'line-width':LW,'line-opacity':LO}});
  map.addLayer({id:'annot-line-dash',type:'line',source:'annot',filter:styleIs('dashed'),
    layout:{'line-join':'round'},
    paint:{'line-color':SC,'line-width':LW,'line-opacity':LO,'line-dasharray':[2,1.4]}});
  map.addLayer({id:'annot-line-dot',type:'line',source:'annot',filter:styleIs('dotted'),
    layout:{'line-cap':'round','line-join':'round'},
    paint:{'line-color':SC,'line-width':LW,'line-opacity':LO,'line-dasharray':[0.1,1.8]}});
  map.addLayer({id:'annot-pt',type:'circle',source:'annot',filter:['==','$type','Point'],
    paint:{'circle-radius':['case',['==',['get','grab'],1],7,['==',['get','vertex'],1],5,6],
      'circle-color':['case',['==',['get','grab'],1],'#ffffff',SC],
      'circle-stroke-color':'#08131a','circle-stroke-width':2.2}});
  map.addLayer({id:'annot-label',type:'symbol',source:'annot',filter:['has','label'],
    layout:{'text-field':['get','label'],'text-size':12,'text-offset':[0,-1.2],'text-font':['Open Sans Semibold'],'text-allow-overlap':true},
    paint:{'text-color':'#ffe6a8','text-halo-color':'#0b0f0d','text-halo-width':2}});
}
// THE render fix, GPU-pixel-verified (queryRenderedFeatures and screenshots both lied here; only
// reading canvas pixels told the truth). A geojson source created EMPTY at map load never builds
// its tile buckets, so NOTHING set on it later with setData paints. The one operation that always
// paints is RECREATING the source carrying the real data SYNCHRONOUSLY. It must be synchronous:
// deferring into requestAnimationFrame collides with MapLibre's render loop and the tiles never
// load. Both sources are recreated every write; setData is never used.
function _recreateAnnotFill(data){
  _ANNOTFILL_LAYERS.forEach(l=>{ if(map.getLayer(l)) map.removeLayer(l); });
  if(map.getSource('annotFill')) map.removeSource('annotFill');
  map.addSource('annotFill',{type:'geojson',data});
  _addAnnotFillLayers();
}
function _recreateAnnot(data){
  _ANNOT_LAYERS.forEach(l=>{ if(map.getLayer(l)) map.removeLayer(l); });
  if(map.getSource('annot')) map.removeSource('annot');
  map.addSource('annot',{type:'geojson',data});
  _addAnnotLayers();
}
// Recreate the LINES/POINTS first, THEN the fill. A polygon in a source recreated in the same
// tick starves whatever source is recreated after it (fill stayed, outline/vertices vanished at
// the 3rd point). Doing the lines first means they never sit behind the polygon's tiling; the
// fill is recreated last and inserted BELOW the outline via beforeId so z-order still holds.
function _annotWrite(lineData, fillData){ try{ _recreateAnnot(lineData); _recreateAnnotFill(fillData); }catch(e){} }
function setupDraw(){
  if(map.getSource('annot')) return;                 // idempotent
  map.addSource('annot',{type:'geojson',data:fc([])});
  _addAnnotLayers();
  map.addSource('annotFill',{type:'geojson',data:fc([])});
  _addAnnotFillLayers();
  if(!window._annotWired){
    window._annotWired=true;
    map.on('click',onDrawClick);
    map.on('dblclick',e=>{ if(drawTool&&drawTool!=='waypoint'){ e.preventDefault(); finishDraw(); } });
    // Click a finished drawing (no tool armed) to open its editor; fills, outlines and vertices
    // all carry the parent id, so a click anywhere on the drawing resolves to it.
    ['annot-fill','annot-line','annot-line-dash','annot-line-dot','annot-pt'].forEach(l=>{
      map.on('click',l,e=>{ if(drawTool||drawEditId) return;
        const id=e.features&&e.features[0]&&e.features[0].properties.id;
        if(id!=null&&id!==''){ if(e.originalEvent)e.originalEvent.stopPropagation(); openDrawEditor(+id); } });
      map.on('mouseenter',l,()=>{ if(!drawTool&&!drawEditId) map.getCanvas().style.cursor='pointer'; });
      map.on('mousemove',l,e=>{ if(drawTool||drawEditId) return; _drawHover(e); });
      map.on('mouseleave',l,()=>{ if(!drawTool&&!drawEditId) map.getCanvas().style.cursor=''; _drawHover(null); });
    });
    // ENTER saves the in-progress drawing (commit + disarm, same as double-click);
    // ESC cancels it (drops the points, commits nothing). In vertex-edit, either exits.
    window.addEventListener('keydown',e=>{
      if(e.key!=='Enter'&&e.key!=='Escape') return;
      if(e.target&&/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;   // don't eat form keys
      if(drawEditId){ exitDrawEdit(); const de=document.getElementById('drawEdit'); if(de)de.remove(); return; }
      if(!drawTool) return;
      if(e.key==='Escape') drawPts=[];      // cancel: nothing to commit
      setDrawTool(drawTool);                // toggles OFF; commits any remaining drawPts via finishDraw()
    });
  }
}
// Hover tooltip for finished drawings: name (bold) + notes + the measurement.
function _drawHover(e){
  let tip=document.getElementById('drawTip');
  if(!e){ if(tip) tip.remove(); return; }
  const id=e.features&&e.features[0]&&e.features[0].properties.id;
  const f=(id!=null&&id!=='')?_drawById(+id):null;
  if(!f){ if(tip) tip.remove(); return; }
  const p=f.properties, esc=s=>String(s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
  if(!p.name && !p.note){ if(tip) tip.remove(); return; }   // nothing to say — no empty bubble
  if(!tip){ tip=document.createElement('div'); tip.id='drawTip';
    tip.style.cssText='position:fixed;z-index:70;pointer-events:none;max-width:220px;background:#12171a;'
      +'border:1px solid #2a343a;border-radius:8px;padding:6px 9px;font:11px/1.4 system-ui,sans-serif;'
      +'color:#c7d0d4;box-shadow:0 6px 18px rgba(0,0,0,.45)';
    document.body.appendChild(tip); }
  tip.innerHTML=(p.name?`<b style="color:#dfe6e9">${esc(p.name)}</b>`:'')
    +(p.note?`<div>${esc(p.note)}</div>`:'')
    +(p.label?`<div style="color:#7c8b93;margin-top:2px">${esc(p.label)}</div>`:'');
  const r=map.getCanvas().getBoundingClientRect();
  tip.style.left=Math.round(r.left+e.point.x+14)+'px';
  tip.style.top =Math.round(r.top +e.point.y+14)+'px';
}
// Per-drawing editable style. Every committed drawing carries its own id, type, colours
// and opacities so the click-to-edit panel can recolour just that one, and so a type can
// be hidden wholesale from the legend. Defaults per tool; the user overrides them.
const DRAW_STYLE={
  area :{stroke:'#5fe6ff',fill:'#4de1ff',fo:0.28,lo:1},
  line :{stroke:'#ffd24d',fill:'#ffd24d',fo:0,   lo:1},
  route:{stroke:'#7bd47b',fill:'#7bd47b',fo:0,   lo:1},
  dist :{stroke:'#ffd24d',fill:'#ffd24d',fo:0,   lo:1},
  pin  :{stroke:'#ff5da2',fill:'#ff5da2',fo:0,   lo:1},
};
let _drawId=1;
function _drawFeat(geom,dtype,label){
  const s=DRAW_STYLE[dtype]||DRAW_STYLE.area;
  // AUTHOR (T9.6). A shared plan is co-edited, so a drawing has to say who put it there
  // — otherwise the party has a map with four people's marks on it and no way to ask
  // anyone what they meant. Stamped at creation; existing drawings are backfilled to the
  // plan's owner on load, which is the only honest guess available for them.
  let by=null; try{ by=localStorage.getItem('transect_email')||null; }catch(e){}
  return {type:'Feature',geometry:geom,properties:{id:_drawId++,dtype,label:label||'',
    by:by, at:Date.now(),
    stroke:s.stroke,fill:s.fill,fo:s.fo,lo:s.lo,lw:3.4,style:'solid',hidden:false}};
}
function onDrawClick(e){
  if(!drawTool || drawEditId) return;      // in vertex-edit mode, clicks drag, not add
  const ll=[e.lngLat.lng,e.lngLat.lat];
  if(drawTool==='waypoint'){
    drawSaved.push(_drawFeat({type:'Point',coordinates:ll},'pin','WP'+(drawSaved.filter(f=>f.geometry.type==='Point').length+1)));
    renderAnnot(); return; }
  drawPts.push(ll); renderAnnot();
}
function finishDraw(){
  if(drawPts.length>=2){
    if(drawTool==='area'){ const ring=drawPts.concat([drawPts[0]]);
      drawSaved.push(_drawFeat({type:'Polygon',coordinates:[ring]},'area',areaFmt(ringKm2(drawPts))));}
    else { const dt=drawTool==='route'?'route':(drawTool==='dist'?'dist':'line');
      drawSaved.push(_drawFeat({type:'LineString',coordinates:drawPts.slice()},dt,(dt==='route'?'Route ':'')+km(polyKm(drawPts))));}
  }
  drawPts=[]; renderAnnot();
}
function renderAnnot(){
  // GUARANTEE the annotation source/layers exist before we draw into them. If the map-init
  // path that calls setupDraw() ever aborts early, `annot` is missing and every draw tool
  // silently no-ops (the tip readout still updates from drawPts, so the panel looked alive
  // while the map stayed blank) — the measure/line/route/area bug. Idempotent.
  if(!map.getSource('annot')){ try{ setupDraw(); }catch(e){} }
  if(!map.getSource('annot')) return;
  // No moveLayer raise here: _annotWrite recreates the source and RE-ADDS the annot layers on top
  // every render, so they always sit above the satellite + model layers by construction.
  // Offer "Recalculate" once the hunter has drawn a focus area to re-plan inside.
  const rb=document.getElementById('rescopeBtn');
  if(rb){ const hasPoly=(drawSaved||[]).some(f=>f.geometry&&f.geometry.type==='Polygon');
    rb.classList.toggle('hidden', !(hasPoly && hasResult() && LAST_JOB_ID)); }
  // The measurement was being computed correctly and never shown: the readout only refreshed on
  // hovering the rail button, so clicking points produced a running total nobody could see.
  if(drawTool) showRailTip(drawTool);
  // Split the render set: polygons go to `annotFill` (fill only), everything else — the lines,
  // the explicit polygon-boundary LineStrings, the vertices — goes to `annot`. Keeping polygons
  // OUT of the line/point source is what stops a polygon from blanking the whole drawing. Every
  // polygon still emits an explicit closed-ring LineString for its outline, because a line layer
  // does not paint polygon rings. Hidden objects (per-object or per-TYPE) are dropped.
  const feats=[];   // lines + points + boundary lines  -> `annot`
  const fills=[];   // polygons                           -> `annotFill`
  const vis=f=>!(f.properties&&(f.properties.hidden||hiddenDrawTypes.has(f.properties.dtype)));
  drawSaved.filter(vis).forEach(f=>{
    if(f.geometry.type==='Polygon'){
      fills.push(f);
      (f.geometry.coordinates||[]).forEach(ring=>feats.push(_styledLine(ring,f.properties)));
    } else {
      feats.push(f);                                            // committed line / pin
    }
    if(drawEditId && f.properties.id===drawEditId) _vertsOf(f).forEach(v=>feats.push(_vertFeat(v,f.properties,true)));
  });
  if(drawPts.length){
    const st=DRAW_STYLE[drawTool]||DRAW_STYLE.area;
    if(drawTool==='area' && drawPts.length>=2){
      const ring=drawPts.concat([drawPts[0]]);                 // ALWAYS closed while drawing
      if(drawPts.length>=3) fills.push({type:'Feature',geometry:{type:'Polygon',coordinates:[ring]},properties:{fill:st.fill,fo:st.fo}});
      feats.push(_styledLine(ring,{stroke:st.stroke,lo:st.lo,style:'solid',label:drawPts.length>=3?areaFmt(ringKm2(drawPts)):''}));
    } else {
      feats.push(_styledLine(drawPts.slice(),{stroke:st.stroke,lo:st.lo,style:'solid',label:drawPts.length>=2?km(polyKm(drawPts)):''}));
    }
    drawPts.forEach(p=>feats.push(_vertFeat(p,st)));
  }
  _annotWrite(fc(feats), fc(fills));
  renderDrawManager();
}
function setDrawTool(t){
  if(drawEditId){ exitDrawEdit(); const de=document.getElementById('drawEdit'); if(de)de.remove(); }
  finishDraw();                         // commit any in-progress geometry
  drawTool=(drawTool===t)?null:t; drawPts=[];
  document.querySelectorAll('#rail button[data-tool]').forEach(b=>b.classList.toggle('on',b.dataset.tool===drawTool));
  // crosshair for point-placing tools, but a distinct cursor for the ones that
  // are about to consume your click differently
  map.getCanvas().style.cursor = drawTool
    ? (drawTool==='waypoint' ? 'copy' : 'crosshair')
    : '';
  document.body.classList.toggle('tool-armed', !!drawTool);
  document.body.setAttribute('data-tool', drawTool||'');
  map.doubleClickZoom[drawTool?'disable':'enable']();
  const hint=document.getElementById('drawhint');
  if(hint) hint.textContent=drawTool?({dist:'Click points; double-click to finish. Shows distance.',
    line:'Click points; double-click to finish a line.',route:'Click waypoints; double-click to finish the route.',
    area:'Click a boundary; double-click to close. Shows area.',waypoint:'Click to drop waypoints.'})[drawTool]:'';
  renderAnnot();
}
function clearDraw(){ drawSaved=[]; drawPts=[]; if(map.getSource('annot')) _annotWrite(fc([]),fc([])); renderDrawManager(); }
// #25 — a manager for what you've drawn: one row per object with its measurement, a per-
// object delete, and clear-all. Self-styled floating card, shown only when drawings exist,
// so you can drop a pin or measure a line and then prune the ones you don't want to keep.
// #25 — the drawings legend: a per-TYPE show/hide (eye), and per-object rows you can click
// to open the editor, or delete. Grouped by type (area/line/route/pin), which is the
// "drawing types in the legend, shown/hidden by type" the hunter asked for.
const _DT_ORDER=['area','line','route','dist','pin'];
const _DT_NAME={area:'Areas',line:'Lines',route:'Routes',dist:'Measures',pin:'Pins'};
function renderDrawManager(){
  let el=document.getElementById('drawMgr');
  const items=(drawSaved||[]).filter(f=>f&&f.geometry);
  // The rail's My-drawings button toggles the panel; empty list removes it outright.
  if(!items.length || window.drawMgrHidden){ if(el) el.remove(); return; }
  if(!el){
    el=document.createElement('div'); el.id='drawMgr';
    el.style.cssText='position:fixed;right:64px;bottom:16px;z-index:45;width:224px;max-height:52vh;overflow:auto;'
      +'background:#12171a;border:1px solid #2a343a;border-radius:10px;padding:8px 10px;'
      +'font:12px/1.4 system-ui,sans-serif;color:#dfe6e9;box-shadow:0 6px 20px rgba(0,0,0,.4)';
    document.body.appendChild(el);
  }
  const esc=s=>String(s||'').replace(/[<>&]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
  const eye=on=>railIcon(on?'eye':'eyeoff',13);   // vector eyes, matching the app's icon set
  const byType={}; items.forEach(f=>{ (byType[f.properties.dtype]=byType[f.properties.dtype]||[]).push(f); });
  let h=`<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">`
    +`<b style="letter-spacing:.04em;font-size:11px;color:#9fb0b8">MY DRAWINGS</b>`
    +`<span style="color:#7c8b93">${items.length}</span></div>`;
  _DT_ORDER.filter(t=>byType[t]).forEach(t=>{
    const off=hiddenDrawTypes.has(t);
    h+=`<div style="display:flex;align-items:center;gap:6px;margin:5px 0 2px"><button data-ty="${t}" title="show/hide all"`
      +` style="background:none;border:none;cursor:pointer;display:flex;align-items:center;color:${off?'#5c6a70':'#e2c044'}">${eye(!off)}</button>`
      +`<b style="flex:1;font-size:11px;color:#9fb0b8">${_DT_NAME[t]} · ${byType[t].length}</b></div>`;
    byType[t].forEach(f=>{ const p=f.properties;
      h+=`<div style="display:flex;align-items:center;gap:6px;padding:1px 0 1px 16px">`
        +`<span data-open="${p.id}" title="${esc((p.note||'')+(p.by?`\n${p.byAssumed?'assumed ':''}by ${p.by}`:''))}" style="flex:1;color:${p.hidden?'#66727a':'#c7d0d4'};cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(p.name)||esc(p.label)||_DT_NAME[t]}`
        // WHO DREW IT. On a shared plan a map carries several people's marks, and a mark
        // you cannot attribute is a mark you cannot ask about. Only shown when the plan
        // actually has more than one author — solo hunters do not need to be told.
        +`${(p.by&&_drawAuthors().size>1)?`<span style="opacity:.55;font-size:10px"> · ${esc(String(p.by).split('@')[0])}${p.byAssumed?'?':''}</span>`:''}</span>`
        +`<button data-del="${p.id}" style="background:none;border:none;color:#C9564A;cursor:pointer;font-size:14px;padding:0 2px">×</button></div>`;
    });
  });
  h+=`<button id="dmClear" style="margin-top:8px;width:100%;background:#1c2429;border:1px solid #2a343a;color:#9fb0b8;border-radius:6px;padding:4px;cursor:pointer;font-size:11px">Clear all</button>`;
  el.innerHTML=h;
  el.querySelectorAll('button[data-ty]').forEach(b=>b.onclick=()=>{ const t=b.dataset.ty; hiddenDrawTypes.has(t)?hiddenDrawTypes.delete(t):hiddenDrawTypes.add(t); renderAnnot(); });
  el.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>openDrawEditor(+b.dataset.open));
  el.querySelectorAll('button[data-del]').forEach(b=>b.onclick=()=>{ const id=+b.dataset.del; drawSaved=drawSaved.filter(x=>x.properties.id!==id); if(drawEditId===id)exitDrawEdit(); renderAnnot(); });
  const ca=document.getElementById('dmClear'); if(ca) ca.onclick=()=>{ const de=document.getElementById('drawEdit'); if(de)de.remove(); clearDraw(); };
}
/* Distinct authors among the current drawings — the panel only names people when there
   is more than one, because a solo hunter does not need to be told they drew their own
   line. */
function _drawAuthors(){
  return new Set((drawSaved||[]).map(f=>(f.properties||{}).by).filter(Boolean));
}
// Elevation sampler (inverse of the thermal grid mapping) + per-drawing stats.
function _elevAtLL(lon,lat){ const e=DOC.elev,b=DOC.box; if(!e||!b||!e.v)return null;
  const gi=Math.round((lon-b.w)/(b.e-b.w)*e.gw-0.5), gj=Math.round((b.n-lat)/(b.n-b.s)*e.gh-0.5);
  const v=elevAt(gi,gj); return (v==null||isNaN(v))?null:v; }
function _drawStats(f){ const g=f.geometry,out={};
  if(g.type==='LineString'){ out.dist=polyKm(g.coordinates);
    const es=g.coordinates.map(c=>_elevAtLL(c[0],c[1])).filter(v=>v!=null);
    if(es.length>=2){ let up=0,dn=0; for(let i=1;i<es.length;i++){const d=es[i]-es[i-1]; if(d>0)up+=d;else dn-=d;}
      out.up=up; out.dn=dn; } }
  else if(g.type==='Polygon'){ const ring=g.coordinates[0]||[]; out.area=ringKm2(ring.slice(0,-1));
    const es=ring.map(c=>_elevAtLL(c[0],c[1])).filter(v=>v!=null);
    if(es.length){ out.emin=Math.min(...es); out.emax=Math.max(...es); } }
  else if(g.type==='Point'){ out.elev=_elevAtLL(g.coordinates[0],g.coordinates[1]); }
  return out; }
// Click-to-open editor: stats + outline/fill colour + opacities + hide + edit-points + delete.
function openDrawEditor(id){
  const f=_drawById(id); if(!f) return; const p=f.properties, s=_drawStats(f);
  let el=document.getElementById('drawEdit');
  if(!el){ el=document.createElement('div'); el.id='drawEdit'; document.body.appendChild(el); }
  el.style.cssText='position:fixed;right:296px;bottom:16px;z-index:60;width:236px;background:#12171a;'
    +'border:1px solid #2a343a;border-radius:10px;padding:10px 12px;font:12px/1.45 system-ui,sans-serif;'
    +'color:#dfe6e9;box-shadow:0 8px 26px rgba(0,0,0,.5)';
  const TN={area:'Area',line:'Line',route:'Route',dist:'Measure',pin:'Pin'}[p.dtype]||'Drawing';
  const mval=v=>UNITS==='imperial'?Math.round(v*3.28084)+' ft':Math.round(v)+' m';
  let stats='';
  if(s.dist!=null) stats+=`<div>Distance <b>${km(s.dist)}</b></div>`;
  if(s.area!=null) stats+=`<div>Area <b>${areaFmt(s.area)}</b></div>`;
  if(s.up!=null) stats+=`<div>Climb <b>+${mval(s.up)}</b> · drop <b>−${mval(s.dn)}</b></div>`;
  if(s.emin!=null) stats+=`<div>Elevation <b>${mval(s.emin)}–${mval(s.emax)}</b></div>`;
  if(s.elev!=null) stats+=`<div>Elevation <b>${mval(s.elev)}</b></div>`;
  const isArea=p.dtype==='area';
  el.innerHTML=`<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">`
    +`<b style="font-size:11px;letter-spacing:.04em;color:#9fb0b8">${TN.toUpperCase()}</b>`
    +`<button id="deClose" style="background:none;border:none;color:#7c8b93;cursor:pointer;font-size:15px">×</button></div>`
    +(stats?`<div style="margin-bottom:8px;color:#c7d0d4">${stats}</div>`:'')
    +`<input id="deName" type="text" placeholder="Name" value="${(p.name||'').replace(/"/g,'&quot;')}" maxlength="60"
       style="width:100%;box-sizing:border-box;background:#1c2429;border:1px solid #2a343a;color:#dfe6e9;border-radius:5px;padding:4px 6px;margin:2px 0 4px;font:12px system-ui,sans-serif">`
    +`<textarea id="deNote" placeholder="Notes — shown on hover" maxlength="240" rows="2"
       style="width:100%;box-sizing:border-box;background:#1c2429;border:1px solid #2a343a;color:#c7d0d4;border-radius:5px;padding:4px 6px;margin:0 0 6px;font:11px system-ui,sans-serif;resize:vertical">${(p.note||'').replace(/</g,'&lt;')}</textarea>`
    +`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Outline</span><input id="deStroke" type="color" value="${p.stroke||'#5fe6ff'}" style="width:30px;height:22px;border:none;background:none;padding:0"></div>`
    +`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Line opacity</span><input id="deLo" type="range" min="0" max="1" step="0.05" value="${p.lo!=null?p.lo:1}" style="width:100px"></div>`
    +`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Weight</span><input id="deLw" type="range" min="1" max="8" step="0.5" value="${p.lw!=null?p.lw:3.4}" style="width:100px"></div>`
    +`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Style</span>`
      +`<select id="deStyle" style="background:#1c2429;border:1px solid #2a343a;color:#cde;border-radius:5px;padding:2px 6px;cursor:pointer">`
      +['solid','dashed','dotted'].map(v=>`<option value="${v}" ${(p.style||'solid')===v?'selected':''}>${v[0].toUpperCase()+v.slice(1)}</option>`).join('')
      +`</select></div>`
    +(isArea?`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Fill</span><input id="deFill" type="color" value="${p.fill||'#4de1ff'}" style="width:30px;height:22px;border:none;background:none;padding:0"></div>`
      +`<div style="display:flex;align-items:center;gap:8px;margin:4px 0"><span style="flex:1">Fill opacity</span><input id="deFo" type="range" min="0" max="0.7" step="0.02" value="${p.fo!=null?p.fo:0.28}" style="width:100px"></div>`:'')
    +`<label style="display:flex;align-items:center;gap:8px;margin:7px 0;cursor:pointer"><input id="deHide" type="checkbox" ${p.hidden?'checked':''}> Hide on map</label>`
    +`<div style="display:flex;gap:6px;margin-top:6px">`
    +`<button id="deEdit" style="flex:1;background:${drawEditId===id?'#2a4d1c':'#1c2429'};border:1px solid #2a343a;color:#cde;border-radius:6px;padding:5px;cursor:pointer">${drawEditId===id?'Done editing':'Edit points'}</button>`
    +`<button id="deDel" style="background:#2a1416;border:1px solid #4a2226;color:#e58;border-radius:6px;padding:5px 9px;cursor:pointer">Delete</button></div>`
    +(drawEditId===id?`<div style="margin-top:6px;color:#8fae6a;font-size:11px">Drag the points to reshape · click Done when finished.</div>`:'');
  const set=(k,v)=>{ p[k]=v; renderAnnot(); };
  el.querySelector('#deClose').onclick=()=>{ el.remove(); if(drawEditId===id) exitDrawEdit(); };
  // Name/notes only touch the list + hover tip — no map re-render per keystroke.
  el.querySelector('#deName').oninput=e=>{ p.name=e.target.value; renderDrawManager(); };
  el.querySelector('#deNote').oninput=e=>{ p.note=e.target.value; renderDrawManager(); };
  el.querySelector('#deStroke').oninput=e=>set('stroke',e.target.value);
  el.querySelector('#deLo').oninput=e=>set('lo',+e.target.value);
  el.querySelector('#deLw').oninput=e=>set('lw',+e.target.value);
  el.querySelector('#deStyle').onchange=e=>set('style',e.target.value);
  if(isArea){ el.querySelector('#deFill').oninput=e=>set('fill',e.target.value); el.querySelector('#deFo').oninput=e=>set('fo',+e.target.value); }
  el.querySelector('#deHide').onchange=e=>{ set('hidden',e.target.checked); renderDrawManager(); };
  el.querySelector('#deDel').onclick=()=>{ drawSaved=drawSaved.filter(x=>x.properties.id!==id); if(drawEditId===id)exitDrawEdit(); el.remove(); renderAnnot(); };
  el.querySelector('#deEdit').onclick=()=>{ if(drawEditId===id) exitDrawEdit(); else enterDrawEdit(id); openDrawEditor(id); };
}
// Vertex-drag editing of the selected drawing.
let _dragVert=null;
function enterDrawEdit(id){ drawEditId=id; map.getCanvas().style.cursor='grab'; renderAnnot(); map.on('mousedown','annot-pt',_vertDown); }
function exitDrawEdit(){ drawEditId=null; _dragVert=null; map.getCanvas().style.cursor=''; try{map.off('mousedown','annot-pt',_vertDown);}catch(e){} renderAnnot(); }
function _vertDown(e){ if(!drawEditId)return; const f=_drawById(drawEditId); if(!f)return;
  const cl=e.lngLat, verts=_vertsOf(f); let bi=-1,bd=1e9;
  verts.forEach((v,i)=>{const d=(v[0]-cl.lng)**2+(v[1]-cl.lat)**2; if(d<bd){bd=d;bi=i;}});
  if(bi<0)return; _dragVert=bi; e.preventDefault(); map.dragPan.disable();
  map.on('mousemove',_vertMove); map.once('mouseup',_vertUp); }
function _vertMove(e){ if(_dragVert==null)return; const f=_drawById(drawEditId); if(!f)return; const g=f.geometry, ll=[e.lngLat.lng,e.lngLat.lat];
  if(g.type==='Point') g.coordinates=ll;
  else if(g.type==='LineString') g.coordinates[_dragVert]=ll;
  else if(g.type==='Polygon'){ const r=g.coordinates[0]; r[_dragVert]=ll; if(_dragVert===0) r[r.length-1]=ll; }
  _relabel(f); renderAnnot(); }
function _vertUp(){ _dragVert=null; map.off('mousemove',_vertMove); map.dragPan.enable(); const de=document.getElementById('drawEdit'); if(de&&drawEditId!=null) openDrawEditor(drawEditId); }
function _relabel(f){ const g=f.geometry;
  if(g.type==='Polygon') f.properties.label=areaFmt(ringKm2((g.coordinates[0]||[]).slice(0,-1)));
  else if(g.type==='LineString') f.properties.label=(f.properties.dtype==='route'?'Route ':'')+km(polyKm(g.coordinates)); }
function destPoint(lon,lat,brgDeg,km){const R=6371,d2r=Math.PI/180,br=brgDeg*d2r,la1=lat*d2r,lo1=lon*d2r;
  const la2=Math.asin(Math.sin(la1)*Math.cos(km/R)+Math.cos(la1)*Math.sin(km/R)*Math.cos(br));
  const lo2=lo1+Math.atan2(Math.sin(br)*Math.sin(km/R)*Math.cos(la1),Math.cos(km/R)-Math.sin(la1)*Math.sin(la2));
  return [lo2/d2r,la2/d2r];}
function buildShooters(){
  if(!map.getSource('shooters'))return;
  const wdir=(selectedDay&&selectedDay.wind_from_deg!=null)?selectedDay.wind_from_deg:270;
  const down=(wdir+180)%360;   // shooter sits downwind of the caller
  // HOW FAR DOWNWIND DEPENDS ON WHAT YOU ARE CARRYING (T10.2). This was a literal
  // 0.07 km — a rifle setup — drawn identically for a bow hunter whose whole problem is
  // that 70 m is twice his effective range. The engine picks it per window; the client
  // only supplies the wind.
  const _sg=(DOC.scent&&DOC.scent.geometry)||{};
  const shooterKm=(_sg.shooter_m||70)/1000;
  const pts=[],lines=[];
  (window._sites||[]).filter(f=>f.properties.type==='rut_calling'&&!hideTypes.rut_calling
      && (winSel==null||f.properties.win===winSel||f.properties.win===-1)).forEach(f=>{
    const c=f.geometry.coordinates, s=destPoint(c[0],c[1],down,shooterKm);
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:s},properties:{}});
    lines.push({type:'Feature',geometry:{type:'LineString',coordinates:[c,s]},properties:{}});});
  map.getSource('shooters').setData(fc(pts));
  map.getSource('shooterLines').setData(fc(lines));
  buildScent(wdir,down);
}
/* SCENT WICKS (#73). A bull that answers a call swings DOWNWIND to scent-check the
   cow he heard before he shows himself — that arc is the most predictable thing he
   does, and it is where the hunt is usually lost, because what he finds there is
   human scent. Three wicks go across that arc at 45 m (25 m short of the shooter,
   so he stops in range rather than walking on into the shooter's own scent cone),
   with two flankers 25 m out either side because a single wick is a thread he can
   walk past. Geometry comes from the engine (DOC.scent.geometry) so the brief, the
   map and the tests all quote one source; only the wind is local. */
function buildScent(wdir,down){
  if(!map.getSource('scent')) return;
  const g=(DOC.scent&&DOC.scent.geometry)||{};
  const wickM=(g.wick_m||45)/1000, flankM=(g.flank_m||25)/1000;
  const pts=[],arcs=[];
  (window._sites||[]).filter(f=>f.properties.type==='rut_calling'&&!hideTypes.rut_calling).forEach(f=>{
    const c=f.geometry.coordinates;
    const mid=destPoint(c[0],c[1],down,wickM);
    const a=destPoint(mid[0],mid[1],(down+90)%360,flankM);
    const b=destPoint(mid[0],mid[1],(down+270)%360,flankM);
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:mid},properties:{mid:1}});
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:a},properties:{mid:0}});
    pts.push({type:'Feature',geometry:{type:'Point',coordinates:b},properties:{mid:0}});
    arcs.push({type:'Feature',geometry:{type:'LineString',coordinates:[a,mid,b]},properties:{}});
  });
  map.getSource('scent').setData(fc(pts));
  map.getSource('scentArc').setData(fc(arcs));
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
  const step=4,pts=[];   // denser: only shown zoomed-in, so it can be busy
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
// Sunrise/sunset (local decimal hours) for the AOI centre and hunt date — the thermal
// switch is SUN-driven, so an 08:00/17:00 clock was up to ~1.5 h wrong at the dawn window
// where thermals matter most (audit #59). Compact solar formula; QC moose season is EDT.
function sunTimes(){
  const b=DOC.box; if(!b) return {rise:7, set:18};
  const lat=(b.n+b.s)/2, lon=(b.w+b.e)/2;
  const ds=(DOC.meta&&DOC.meta.target_dates&&DOC.meta.target_dates[0])||'2026-09-25';
  const d=new Date(ds+'T12:00:00Z');
  const doy=Math.floor((d-new Date(Date.UTC(d.getUTCFullYear(),0,0)))/86400000);
  const latr=lat*Math.PI/180, decl=0.4093*Math.sin(2*Math.PI/365*(doy-81));
  let cosH=Math.max(-1,Math.min(1,-Math.tan(latr)*Math.tan(decl)));
  const H=Math.acos(cosH)*180/Math.PI/15;        // half-day length, hours
  const tz=-4, noon=12-(lon/15-tz);              // local clock hour of solar noon (EDT)
  return {rise:noon-H, set:noon+H};
}
// Upslope (anabatic) once the sun has warmed the slopes (~45 min after sunrise) until it
// stops (~30 min before sunset); overnight/early it drains downslope (katabatic).
function thermalRising(h){ const s=sunTimes(); return h>=s.rise+0.75 && h<=s.set-0.5; }
function updateThermal(h){
  if(!map.getLayer('thermal'))return;
  const off=thermalRising(h)?180:0;   // brg is drainage; +180 = upslope by day
  map.setLayoutProperty('thermal','icon-rotate',['+',['get','brg'],off]);
}
function hav(a,b){const R=6371,dLat=(b[1]-a[1])*Math.PI/180,dLon=(b[0]-a[0])*Math.PI/180,
  s=Math.sin(dLat/2)**2+Math.cos(a[1]*Math.PI/180)*Math.cos(b[1]*Math.PI/180)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(s));}

/* ---------------- Setup (redesigned) ---------------- */
let draft={center: DOC.blank ? null : [DOC.meta.center.lon,DOC.meta.center.lat],
  radius:DOC.meta.radius_km||50,
  walkAccess:null, walkHunt:null, party:2, fixedCampMode:false, huntRadius:null,
  windows:[],                      // EXTRA date windows beyond draft.dates (T9.2)
  method:'rifle',                  // method of take for the PRIMARY window (T10.2)
  siteMode:'find',                 // 'find' = model finds sites in a box · 'known' = hunter names up to 4 sites
  resM:null,                       // analysis-grid override (m); null = auto (sized to the area)
  sites:[],                        // known-site centres [[lon,lat],...] (max 4); sites[0] mirrors draft.center
  dates: (USING_EXAMPLE && DOC.meta && DOC.meta.target_dates) ? DOC.meta.target_dates.slice() : []};
/* The hunt style is one 3-way choice: a HUNTING CAMP (cabin — a fixed camp you drive to),
   BASECAMP @ VEHICLE (you sleep at the truck), or SPIKE CAMP (pack in and sleep out).
   Internally: camp => fixedCampMode + spike semantics (as before), the other two map to
   the engine's spike|vehicle hunt_style. */
function hstyleOf(){ return draft.fixedCampMode ? 'camp' : SETUP.huntStyle; }
/* THE BOX IS AN INPUT TO A RUNNING COMPUTATION. While one is in flight the Setup that
   defines it has to hold still: the engine already has the box, the dates and the kit it
   was given, and nothing the hunter changes here can reach it. Leaving the controls live
   invites moving the box mid-run and then reading the result as if it were for the new
   one — a silent, confident wrong answer, which is the worst kind.

   Disabling the whole pane rather than each control means a new control cannot be added
   later and quietly escape the lock. */
function lockSetupWhileRunning(){
  const el=document.getElementById('setup'); if(!el) return;
  const lock=!!RUN_ACTIVE;
  el.querySelectorAll('input,select,button,textarea').forEach(n=>{
    if(n.id==='runBtn') return;                 // the run button owns its own state
    if(lock) n.setAttribute('disabled','');
    else n.removeAttribute('disabled');
  });
  el.classList.toggle('locked', lock);
  const old=el.querySelector('.runlock'); if(old) old.remove();
  if(!lock) return;
  const note=document.createElement('div');
  note.className='callout runlock'; note.dataset.kind='info';
  note.innerHTML=`<span class="mark">◷</span><div class="body"><b>${t('lock.title')}</b>${t('lock.body')}</div>`;
  el.insertBefore(note, el.firstChild);
}
function renderSetup(){
  const el=document.getElementById('setup');
  const hs=hstyleOf();
  // A camp hunt IS a known-site hunt with exactly one site: the camp. Forcing it here
  // rather than only hiding the toggle means a hunter who picked "find sites" first and
  // then switched to a camp hunt cannot leave a contradictory pair behind — the same
  // shape of bug as huntStyle-vs-fixedCampMode.
  const camping=(hs==='camp');
  if(camping){
    draft.siteMode='known';
    if(draft.sites.length>1) draft.sites=draft.sites.slice(0,1);
    if(!draft.sites.length && draft.center) draft.sites=[{ll:draft.center.slice(),label:''}];
  }
  const known=draft.siteMode==='known';
  const siteChip=(s,i)=>`<div class="row" style="align-items:center;margin-top:6px">
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
        <b class="mono" style="color:#e2c044">${i+1}</b>&nbsp; ${s.label?s.label:(s.ll[1].toFixed(4)+', '+s.ll[0].toFixed(4))}</span>
      <button data-delsite="${i}" class="btn btn--secondary btn--sm" title="${t('setup.removeSite','Remove site')}">×</button></div>`;
  el.innerHTML=`
    <div class="sec">
      <h2 class="t-h1" style="margin:0 0 6px">${t('setup.title')}</h2>
      <p class="lede">${t('setup.lede')}</p>
    </div>

    <!-- 01 SPECIES + DATES — the hunt itself comes first. -->
    <div class="sec">
      <div class="sechead"><span class="num">01</span><h3>${t('setup.sSpecies','Species & dates')}</h3></div>
      <label class="fld">${t('setup.species','Species')}</label>
      <div class="seg"><button aria-pressed="true">${t('setup.moose','Moose')}</button></div>
      <label class="fld">${t('setup.dates')}</label>
      <div class="numrow" style="border:1px solid var(--line,#2a343a);border-radius:8px;padding:4px 8px">
        <input id="dateStart" type="date" required value="${draft.dates[0]||''}" style="border:none;background:none">
        <span>→</span>
        <input id="dateEnd" type="date" required value="${draft.dates[1]||''}" style="border:none;background:none"></div>
      <div class="s" style="margin-top:6px">${t('setup.datesnote','Drives rut timing, weather and behaviour. Peak breeding ≈ Oct 2 at this latitude — but bulls are most callable in the two weeks before it.')}</div>
      <!-- METHOD OF TAKE (T10.2). It decides how close the animal has to come, so it
           moves the shooter, the wicks and how much a glassing knob is worth. -->
      <div class="numrow" style="margin-top:8px"><span class="t-micro">Method of take</span>
        <select id="methodPrimary" class="btn btn--secondary btn--sm" style="margin-left:auto;padding:2px 6px">
          ${['rifle','bow','muzzleloader'].map(m=>`<option value="${m}" ${draft.method===m?'selected':''}>${m}</option>`).join('')}
        </select></div>
      <div class="s" style="margin-top:4px">${t('setup.methodnote','A bow needs the bull inside ~35 m, so the shooter sits closer to the caller, the scent wicks come in with him, and a glassing knob is worth much less than a neck he already walks through.')}</div>
      <!-- EXTRA SEASONS (T9.2). Each one is a FULL analysis, so the cost is stated up
           front rather than discovered on the progress bar. -->
      ${draft.windows.map((w,i)=>`<div class="numrow" style="border:1px solid var(--line,#2a343a);border-radius:8px;padding:4px 8px;margin-top:8px">
        <input data-win="${i}" data-end="0" type="date" value="${w[0]||''}" style="border:none;background:none">
        <span>→</span>
        <input data-win="${i}" data-end="1" type="date" value="${w[1]||''}" style="border:none;background:none">
        <select data-winm="${i}" class="btn btn--secondary btn--sm" style="padding:2px 6px">${['rifle','bow','muzzleloader'].map(m=>`<option value="${m}" ${(w[2]||'rifle')===m?'selected':''}>${m==='muzzleloader'?'muzzle':m}</option>`).join('')}</select>
        <button data-delwin="${i}" class="btn btn--secondary btn--sm" title="${t('setup.removeWindow','Remove this season')}">×</button></div>`).join('')}
      ${draft.windows.length<3?`<button id="winAdd" class="btn btn--secondary btn--block" style="margin-top:8px">${t('setup.winAdd','+ Compare another season (bow, muzzleloader…)')}</button>`:''}
      ${draft.windows.length?`<div class="s" style="margin-top:6px">${t('setup.winNote','Each season is analysed separately — the model weights habitat differently before, during and after the rut, so the same ground scores differently. Expect the run to take about this many times longer.')}</div>`:''}
    </div>

    <!-- 02 HUNT STYLE — three cards with icons; distances follow from the choice. -->
    <div class="sec">
      <div class="sechead"><span class="num">02</span><h3>${t('setup.sStyle','Hunt style')}</h3></div>
      <div class="seg" id="hstyleSeg" style="display:flex">
        <button id="hsCamp"  style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${hs==='camp'?'aria-pressed="true"':''}>${railIcon('cabin',20)}<span>${t('setup.styleCamp','Hunting camp')}</span></button>
        <button id="hsVeh"   style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${hs==='vehicle'?'aria-pressed="true"':''}>${railIcon('pickup',20)}<span>${t('setup.styleVeh','Basecamp @ vehicle')}</span></button>
        <button id="hsSpike" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${hs==='spike'?'aria-pressed="true"':''}>${railIcon('tent',20)}<span>${t('setup.styleSpike','Spike camp')}</span></button>
      </div>
      <div class="s" id="hsNote" style="margin-top:6px"></div>
      <div id="stageCampRow" class="${hs==='spike'?'':'hidden'}">
        <label class="fld">${t('setup.stageCamp','Vehicle staging → base camp (max)')}</label>
        <div class="numrow"><input id="stageCamp" type="number" step="0.1" min="0.3" placeholder="e.g. 2"
          value="${draft.walkAccess!=null?toU(draft.walkAccess).toFixed(1):''}"><span>${unitBig()}</span></div>
      </div>
      <label class="fld">${t('setup.campHunt','Camp → hunting (max)')}</label>
      <div class="numrow"><input id="campHunt" type="number" step="0.1" min="0.3" placeholder="e.g. 4"
        value="${draft.walkHunt!=null?toU(draft.walkHunt).toFixed(1):''}"><span>${unitBig()}</span></div>
      <label class="fld">${t('setup.party','Hunters in the party')}</label>
      <div class="numrow"><input id="partySize" type="number" min="1" max="12" step="1"
        value="${draft.party||2}"><span>${t('setup.partyU','hunters')}</span></div>
      <div class="s" style="margin-top:6px">${t('setup.partyNote',
        'Party size changes the analysis, not just the wording: focus areas are sized to hold the crew, and each area gets a calling stand per hunter plus glassing positions to pair up on.')}</div>
    </div>

    <!-- 03 TRANSPORTATION — multi-select; each one changes what the model can reach. -->
    <div class="sec">
      <div class="sechead"><span class="num">03</span><h3>${t('setup.sTransport','Available transportation')}</h3></div>
      <div class="seg" id="transportSeg" style="display:flex">
        <button id="trCanoe" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${SETUP.transport.canoe?'aria-pressed="true"':''}>${railIcon('canoe',20)}<span>${t('setup.trCanoe','Canoe')}</span></button>
        <button id="trMotor" style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${SETUP.transport.motor?'aria-pressed="true"':''}>${railIcon('motorboat',20)}<span>${t('setup.trMotor','Motorboat')}</span></button>
        <button id="trAtv"   style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px" ${SETUP.transport.atv?'aria-pressed="true"':''}>${railIcon('atv',20)}<span>${t('setup.trAtv','ATV / SxS')}</span></button>
      </div>
      <div class="s" style="margin-top:6px">${t('setup.transportNote',
        'Pick everything you\'ll have. No boat: rivers become foot barriers. ATV/SxS: tracks and trails become drivable, so camp can sit further in and routes split into ride vs walk legs.')}</div>
    </div>

    <!-- 04 HUNT LOCATION — known sites (up to 4, compared) or find sites in an area.
         A CAMP HUNT HAS NEITHER OF THOSE CHOICES. The camp is a place the hunter
         already owns or rents; there is nothing to go and find, and there is exactly
         one of it. Offering "Find sites" there invites a run whose whole premise
         (the analysis is centred on your camp) contradicts the mode that was picked. -->
    <div class="sec">
      <div class="sechead"><span class="num">04</span><h3>${camping?t('setup.sCampWhere','Camp location'):t('setup.sWhere','Hunt location')}</h3></div>
      ${camping?'':`<div class="seg"><button id="lmFind" ${!known?'aria-pressed="true"':''}>${t('setup.findSites','Find sites')}</button>
        <button id="lmKnown" ${known?'aria-pressed="true"':''}>${t('setup.knownSites','Known sites')}</button></div>`}

      <div id="locKnown" class="${known?'':'hidden'}">
        <div id="siteList">${draft.sites.map(siteChip).join('')}</div>
        <div class="row" id="siteEntryRow" style="margin-top:8px;${(camping?draft.sites.length>=1:draft.sites.length>=4)?'display:none':''}">
          <input id="siteEntry" placeholder="${camping?t('setup.campPh','Search a place or paste your camp\'s lat, lon'):t('setup.sitePh','Search a place or paste lat, lon')}">
          <button id="siteDrop" class="btn btn--secondary btn--sm" title="${t('setup.siteDrop','Drop a waypoint on the map')}">${railIcon('pin',15)}</button>
        </div>
        <div id="siteRes" class="results"></div>
        ${!camping&&draft.sites.length>0&&draft.sites.length<4?`<button id="siteAdd" class="btn btn--secondary btn--block" style="margin-top:8px">${t('setup.siteAdd','+ Add another site to compare')}</button>`:''}
        <div class="s" style="margin-top:6px">${camping?t('setup.campNote','Where you sleep. Everything is measured from here — the analysis covers what you can reach and hunt from this one point.'):t('setup.knownNote','Up to 4 sites — each gets its own analysis, ranked against the others.')}</div>
      </div>

      <div id="locFind" class="${known?'hidden':''}">
        <div class="row">
          <input id="locEntry" placeholder="${t('setup.sitePh','Search a place or paste lat, lon')}"
            value="${draft.center?draft.center[1].toFixed(4)+', '+draft.center[0].toFixed(4):''}">
          <button id="dragBox" class="btn btn--secondary btn--sm" title="${t('setup.boxSel','Select an area on the map')}">${railIcon('boxselect',15)}</button>
        </div>
        <div id="locRes" class="results"></div>
      </div>

      <label class="fld">${t('setup.radius','Radius')} — <b class="mono" id="radVal">${Math.round(toU(draft.radius))} ${unitBig()}</b></label>
      <input id="radius" type="range" min="${UNITS==='imperial'?3:5}" max="${UNITS==='imperial'?75:120}" step="1" value="${Math.round(toU(draft.radius))}">
      <div class="t-micro" style="display:flex;justify-content:space-between;margin-top:4px">
        <span>${UNITS==='imperial'?3:5}</span><span>${t('setup.radiushint','~20 km+ resolves focus areas')}</span></div>
    </div>

    <!-- 05 PROCESSING DETAIL — the analysis grid. Auto-sized to the area; the hunter can
         trade detail for speed. Finer grid = more data, slower run. -->
    <div class="sec">
      <div class="sechead"><span class="num">05</span><h3>${t('setup.sRes','Processing detail')}</h3></div>
      <label class="fld">${t('setup.resLbl','Grid resolution')} — <b class="mono" id="resVal"></b></label>
      <input id="resSlider" type="range" step="1">
      <div class="t-micro" style="display:flex;justify-content:space-between;margin-top:4px">
        <span>${t('setup.resCoarse','coarser · faster')}</span><span>${t('setup.resFine','finer · more detail · slower')}</span></div>
      <div class="s" id="resNote" style="margin-top:6px"></div>
    </div>

    <div class="sec">
      <label class="fld">${t('setup.units')}</label>
      <div class="seg"><button id="uMetric" ${UNITS==='metric'?'aria-pressed="true"':''}>${t('setup.metric')}</button>
        <button id="uImperial" ${UNITS==='imperial'?'aria-pressed="true"':''}>${t('setup.imperial')}</button></div>
    </div>

    <div class="sec">
      <div id="setupErr"></div>
      <button id="runBtn" class="btn btn--primary btn--lg btn--block">${hasResult()?t('setup.runnew'):t('setup.run')}</button>
      ${hasResult()?`<div class="callout" data-kind="warn" style="margin-top:10px"><span class="mark">!</span><div class="body">
        <b>This replaces your current analysis</b>
        The areas, zones and brief on screen now are for a different box. Running again
        discards them — save the current plan first if you want to keep it.</div></div>`:''}
      <div class="callout" data-kind="info" style="margin-top:10px"><span class="mark">i</span><div class="body">
        <b>Live recompute — a few minutes (longer for large southern boxes)</b>
        Downloads terrain, imagery, land-cover, burn history, hydrography and — south of ~52°N —
        detailed forest-stand data (species, canopy closure, dated cuts), then re-runs the model.
        Big boxes with full stand data can take 8–10 min; progress sits at 0% through the
        download stage, which is normal.</div></div>
    </div>`;

  // ---- wiring ----
  const clearErr=()=>{const b=document.getElementById('setupErr'); if(b){b.className='';b.innerHTML='';}};
  document.getElementById('dateStart').onchange=e=>{if(e.target.value)draft.dates[0]=e.target.value;clearErr();};
  document.getElementById('dateEnd').onchange=e=>{if(e.target.value)draft.dates[1]=e.target.value;clearErr();};
  const _wa=document.getElementById('winAdd');
  if(_wa) _wa.onclick=()=>{ draft.windows.push(['','','rifle']); renderSetup(); };
  el.querySelectorAll('input[data-win]').forEach(inp=>inp.onchange=e=>{
    const i=+e.target.dataset.win, j=+e.target.dataset.end;
    if(draft.windows[i]) draft.windows[i][j]=e.target.value; markDirtySoft(); });
  document.querySelectorAll('[data-winm]').forEach(s=>s.onchange=e=>{
    const i=+e.target.dataset.winm;
    if(draft.windows[i]){ draft.windows[i][2]=e.target.value; markDirtySoft(); } });
  const _mp=document.getElementById('methodPrimary');
  if(_mp) _mp.onchange=e=>{ draft.method=e.target.value; markDirtySoft(); };
  el.querySelectorAll('button[data-delwin]').forEach(b=>b.onclick=e=>{
    e.preventDefault(); draft.windows.splice(+b.dataset.delwin,1); renderSetup(); });

  // hunt style (3-way)
  const setHstyle=(h)=>{
    draft.fixedCampMode=(h==='camp');
    if(h!=='camp') SETUP.huntStyle=h;          // camp keeps spike semantics engine-side
    else SETUP.huntStyle='spike';
    renderSetup(); applyHunt(); markDirtySoft();
  };
  document.getElementById('hsCamp').onclick=()=>setHstyle('camp');
  document.getElementById('hsVeh').onclick=()=>setHstyle('vehicle');
  document.getElementById('hsSpike').onclick=()=>setHstyle('spike');
  const note=document.getElementById('hsNote');
  note.textContent = hs==='camp' ? t('setup.noteCamp','Your first hunt-location point IS the camp — the analysis narrows to what you can hunt from it.')
    : hs==='vehicle' ? t('setup.noteVeh','You sleep at the truck. Areas beyond your reach of a road are dimmed.')
    : t('setup.noteSpike','Pack-in camps allowed — remote areas stay in play.');

  const sc=document.getElementById('stageCamp');
  if(sc) sc.onchange=e=>{draft.walkAccess=fromU(+e.target.value);applyHunt();};
  document.getElementById('campHunt').onchange=e=>{
    draft.walkHunt=fromU(+e.target.value);
    if(draft.fixedCampMode) draft.huntRadius=draft.walkHunt;   // one number, both meanings
    applyHunt();};
  document.getElementById('partySize').onchange=e=>{
    draft.party=Math.max(1,Math.min(12,Math.round(+e.target.value||2)));
    e.target.value=draft.party; setPlanName(PLAN_NAME,false);};

  // transportation multi-select
  const syncTr=()=>{
    SETUP.watercraft = SETUP.transport.motor?'motor':(SETUP.transport.canoe?'canoe':'none');
    ['trCanoe','trMotor','trAtv'].forEach((id,i)=>{
      const k=['canoe','motor','atv'][i];
      const b=document.getElementById(id);
      if(SETUP.transport[k]) b.setAttribute('aria-pressed','true'); else b.removeAttribute('aria-pressed');
    });
    applyHunt(); markDirtySoft();
  };
  document.getElementById('trCanoe').onclick=()=>{SETUP.transport.canoe=!SETUP.transport.canoe;syncTr();};
  document.getElementById('trMotor').onclick=()=>{SETUP.transport.motor=!SETUP.transport.motor;syncTr();};
  document.getElementById('trAtv').onclick=()=>{SETUP.transport.atv=!SETUP.transport.atv;syncTr();};

  // location: one entry field per mode — coords parse first, else geocode
  const parseLL=v=>{const m=String(v||'').split(',').map(s=>parseFloat(s.trim()));
    return (m.length===2&&!isNaN(m[0])&&!isNaN(m[1])&&Math.abs(m[0])<=90)?[m[1],m[0]]:null;};
  const wireEntry=(inputId,resId,commit)=>{
    const inp=document.getElementById(inputId), res=document.getElementById(resId);
    if(!inp) return;
    const go=()=>{
      const ll=parseLL(inp.value);
      if(ll){ commit(ll,null); return; }
      geocode(inp.value).then(list=>{
        res.innerHTML=list.slice(0,5).map((r,i)=>`<div class="rres" data-i="${i}">${r.display_name}</div>`).join('');
        res.querySelectorAll('.rres').forEach(d=>d.onclick=()=>{const r=list[+d.dataset.i];res.innerHTML='';
          commit([+r.lon,+r.lat], r.display_name.split(',')[0]);});});
    };
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();go();}});
    inp.onchange=()=>{ const ll=parseLL(inp.value); if(ll) commit(ll,null); };
  };
  // The Find/Known toggle is not rendered for a camp hunt (there is one camp and
  // nothing to go find), so these must be looked up defensively rather than assumed.
  const _lmF=document.getElementById('lmFind'), _lmK=document.getElementById('lmKnown');
  if(_lmF) _lmF.onclick=()=>{draft.siteMode='find';renderSetup();};
  if(_lmK) _lmK.onclick=()=>{draft.siteMode='known';
    // carry an existing centre in as site 1 so switching modes doesn't lose it
    if(!draft.sites.length&&draft.center) draft.sites=[{ll:draft.center.slice(),label:''}];
    renderSetup();};
  if(known){
    wireEntry('siteEntry','siteRes',(ll,label)=>addSite(ll,label));
    const drop=document.getElementById('siteDrop');
    if(drop) drop.onclick=()=>{ window._siteDropArm=true; drop.classList.add('on');
      map.getCanvas().style.cursor='crosshair'; };
    const add=document.getElementById('siteAdd');
    if(add) add.onclick=()=>{ const r=document.getElementById('siteEntryRow'); if(r){r.style.display='';
      document.getElementById('siteEntry').focus(); add.remove(); } };
    // fresh KNOWN mode with sites: the entry row hides until "+ Add" (spec) — show it only when empty
    if(draft.sites.length>0&&draft.sites.length<(camping?1:4)){ const r=document.getElementById('siteEntryRow'); if(r) r.style.display='none'; }
    el.querySelectorAll('button[data-delsite]').forEach(b=>b.onclick=()=>{
      draft.sites.splice(+b.dataset.delsite,1);
      draft.center=draft.sites.length?draft.sites[0].ll.slice():null;
      renderSetup(); drawDraft(true); });
  } else {
    wireEntry('locEntry','locRes',(ll,label)=>{
      draft.center=ll; document.getElementById('locEntry').value=ll[1].toFixed(4)+', '+ll[0].toFixed(4);
      map.flyTo({center:ll,zoom:10}); drawDraft(); clearErr(); });
    document.getElementById('dragBox').onclick=(e)=>{
      const b=e.currentTarget;
      if(b.classList.contains('on')){ cancelBoxDraw(); return; }
      b.classList.add('on'); startBoxDraw();
    };
  }
  // one-shot map click to drop a known site (wired once, checked per click)
  if(!window._siteClickWired){ window._siteClickWired=true;
    map.on('click',e=>{ if(!window._siteDropArm) return;
      window._siteDropArm=false; map.getCanvas().style.cursor='';
      addSite([e.lngLat.lng,e.lngLat.lat],null); }); }

  const rad=document.getElementById('radius');
  rad.oninput=()=>{draft.radius=fromU(+rad.value);document.getElementById('radVal').textContent=(+rad.value)+' '+unitBig();
    // Area changed: a manually-chosen resolution is KEPT (clamped into the new bounds);
    // only auto mode re-derives. The res slider's bounds follow the new area.
    if(draft.resM!=null){ const b=resBounds(draft.radius);
      draft.resM=Math.max(b.fine,Math.min(b.coarse,draft.resM)); }
    _syncResUI();
    drawDraft();};
  // processing-detail slider — RIGHT = more detail (finer grid). The slider carries an
  // inverted value so the metre number falls as the thumb moves right.
  const rsl=document.getElementById('resSlider');
  rsl.oninput=()=>{ const b=resBounds(draft.radius), a=autoResM(draft.radius);
    const res=b.fine+b.coarse-(+rsl.value);
    draft.resM=(Math.abs(res-a)<=2)?null:res;    // snap back to auto near the default
    _syncResUI(); _syncRadiusBounds(); };
  _syncResUI(); _syncRadiusBounds();
  document.getElementById('uMetric').onclick=()=>setUnits('metric');
  document.getElementById('uImperial').onclick=()=>setUnits('imperial');
  document.getElementById('runBtn').onclick=()=>runAnalysis();
  drawDraft(); applyHunt();
  lockSetupWhileRunning();
}
/* Keep the resolution slider honest against the current area: bounds, default marker,
   live time estimate, and a WARNING when the grid is pushing the engine's memory
   ceiling (the server clamps at ~3200 px/side regardless — that's the hard limit). */
function _syncResUI(){
  const sl=document.getElementById('resSlider'); if(!sl) return;
  const b=resBounds(draft.radius), auto=autoResM(draft.radius);
  sl.min=b.fine; sl.max=b.coarse;
  const res=Math.max(b.fine,Math.min(b.coarse,draft.resM||auto));
  sl.value=b.fine+b.coarse-res;              // inverted: thumb RIGHT = finer grid = more detail
  const pxSide=Math.round(2*Math.max(3,draft.radius)*1000/res);
  const vEl=document.getElementById('resVal');
  if(vEl) vEl.textContent=res+' m'+(draft.resM==null?' · '+t('setup.resAuto','auto'):'');
  const est=estimateMinutes(draft.radius,res);
  const note=document.getElementById('resNote');
  if(note){
    let html=t('setup.resEst','Estimated processing')+` <b>~${est.lo}–${est.hi} min</b> · ${pxSide}×${pxSide} px`;
    if(pxSide>2600) html+=`<div class="callout" data-kind="warn" style="margin-top:6px"><span class="mark">!</span><div class="body">`
      +(res<=b.fine? t('setup.resHard','This is the ceiling for an area this size — the engine refuses finer grids so a run can\'t exhaust its memory. Shrink the area to go finer.')
                   : t('setup.resWarn','You\'re pushing the engine — expect a slow, memory-heavy run. There\'s a hard ceiling just past this.'))
      +`</div></div>`;
    note.innerHTML=html;
  }
}
/* Two-way coupling: a manually-chosen FINE grid caps how big the area can be (the
   ~3200 px/side memory ceiling => radius <= res * 1.6 km). Shrink the radius slider's
   max to match, and pull the current radius down if it now exceeds it — WITHOUT
   touching the user's chosen resolution. Auto mode leaves the full radius range. */
function _syncRadiusBounds(){
  const rad=document.getElementById('radius'); if(!rad) return;
  const maxKm = draft.resM!=null ? Math.max(5, Math.min(120, Math.floor(draft.resM*1.6))) : 120;
  rad.max=Math.round(toU(maxKm));
  if(draft.radius>maxKm){
    draft.radius=maxKm;
    rad.value=Math.round(toU(maxKm));
    const rv=document.getElementById('radVal'); if(rv) rv.textContent=Math.round(toU(maxKm))+' '+unitBig();
    drawDraft();
  }
}
function addSite(ll,label){
  // A camp hunt has ONE site — the camp. Entering another REPLACES it rather than
  // adding a second, because "compare these four" is a different mode and silently
  // making a camp hunt into one would move the analysis off the camp.
  if(hstyleOf()==='camp'){
    draft.sites=[{ll:ll.slice(),label:label||''}];
    draft.center=ll.slice();
    renderSetup(); drawDraft(true);
    return;
  }
  if(draft.sites.length>=4) return;
  draft.sites.push({ll:ll.slice(),label:label||''});
  draft.center=draft.sites[0].ll.slice();          // engine centre = first site
  renderSetup(); drawDraft(true);                  // true => refit the map to all sites
}
/* How far off a road an area may sit and still count as reachable. With no camp
   there is only one walk — truck to hunting ground — so the hidden access field
   must not be the one that governs. Hiding it without this made a vehicle hunt fall
   back to the neutral 6 km, silently ignoring what the hunter actually said. */
function reachKm(){
  const veh=SETUP.huntStyle==='vehicle';
  const v = veh ? draft.walkHunt : draft.walkAccess;
  return (v!=null ? v : 6);   // 6 km = neutral fallback when unset
}
function applyHunt(){
  if(!map.getLayer('areas-fill'))return;
  const veh=SETUP.huntStyle==='vehicle', rk=reachKm()*1000;
  map.setPaintProperty('areas-fill','fill-opacity',
    veh?['case',['>',['coalesce',['get','dr'],0],rk],0.03,['case',['<=',['get','rank'],2],0.16,0.12]]:0.10);
  map.setPaintProperty('areas-line','line-opacity',
    veh?['case',['>',['coalesce',['get','dr'],0],rk],0.2,0.9]:0.9);
  // Crossings emphasis when you have no boat — they are hard blocks on a foot route.
  // This used to set circle-radius, but crossings became a SYMBOL layer when it got
  // its icon badges. setPaintProperty then threw, renderSetup() aborted, and since
  // wireTabs() is the very next call, EVERY tab button lost its handler: the whole
  // navigation died from one stale property name. Symbol layers scale via icon-size.
  if(map.getLayer('crossings') && map.getLayer('crossings').type==='symbol')
    map.setLayoutProperty('crossings','icon-size',
      (SETUP.watercraft==='none')
        ? ['case',['==',['get','kind'],'boat'],1.15,0.8]
        : ['interpolate',['linear'],['zoom'],8,0.5,11,0.75,14,1]);
  if(document.getElementById('list')) buildPanel();
}
function setUnits(u){ if(u===UNITS)return; UNITS=u; renderSetup(); buildPanel(); if(!document.getElementById('detail').classList.contains('hidden')){} }
function applyDoc(newDoc){        // re-bind the whole map + panels to fresh engine data
  // honour the incoming document's own flag: engine results have none (falsy),
  // blankDoc() sets it true — so resetting to blank doesn't need a correction after.
  DOC=newDoc; DOC.blank=!!newDoc.blank; window.TRANSECT_DATA=newDoc;
  applyLegend();   // rebind layer prose to THIS document's contract legend (falls back if absent)
  if(typeof paintTabLocks==='function') paintTabLocks();
  const S=buildSources();
  const setD=(id,data)=>{const s=map.getSource(id); if(s&&data) s.setData(data);};
  setD('huntZones',S.huntZones); setD('browseZones',S.browseZones);
  ['browse_cut_zones','browse_burn_zones','browse_stand_zones','browse_lc_zones']
    .forEach(k=>setD(k,(S.browseSub&&S.browseSub[k])||fc([])));
  setD('refugeZones',S.refugeZones); setD('funnelZones',S.funnelZones); setD('burnZones',S.burnZones); setD('cutZones',S.cutZones); setD('tenureZones',S.tenureZones);
  setD('wetlandZones',S.wetlandZones); setD('beaverPonds',S.beaverPonds); setD('leases',S.leases);
  setD('rivers',S.rivers); setD('lakes',S.lakes); setD('crossings',S.crossings); setD('infra',S.infra);
  setD('areas',S.areas); setD('areaLabels',S.areaLabels); setD('camps',S.camps);
  setD('staging',S.staging); setD('packin',fc(S.packin)); setD('sites',fc(window._sites));
  setD('routes',S.routes);
  buildWindowPill(); applyWindowFilter();      // T10.3 — reassert the filter on new data
  setVis(LYR_MAP.roads,true); setVis(LYR_MAP.boundaries,true);   // keep roads + borders visible after a recompute too
  window._aoi={huntZones:S.huntZones,browseZones:S.browseZones,rivers:S.rivers,lakes:S.lakes,
    refugeZones:S.refugeZones,funnelZones:S.funnelZones};
  Object.keys(AREA_DETAIL).forEach(k=>delete AREA_DETAIL[k]);   // deep detail is stale for a new AOI
  deepActive=null;
  try{buildThermal();}catch(e){} buildShooters();
  buildPanel(); buildWeather(); buildLayersDock(); lastSel=1;
  document.getElementById('subtitle').textContent=`${DOC.blank?t('plan.noarea'):DOC.meta.title} · ${speciesName(DOC.meta.species)} · ${(DOC.meta.target_dates||[]).join(' – ')}`;
  setPlanName(planTitle(),false);   // a recompute is a NEW area — don't keep the old plan's name
  const b=newDoc.box; if(b) map.fitBounds([[b.w,b.s],[b.e,b.n]],{padding:60});
}
/* Runtime estimate from the actual box size. Two components, because they scale
   differently: a roughly FIXED cost (several sequential Overpass queries against a
   slow public mirror, plus STAC lookups) and an AREA-SCALED cost (DEM, land-cover,
   Sentinel-2 and burn tiles for the box). The raster stages don't blow up with area
   because the API caps the grid at ~2400 px/side by coarsening resolution.
   Calibrated against measured runs: r=16 km ≈ 3.5 min, r=18 km ≈ 4.2 min. */
/* The engine's own auto grid: never finer than the model's 40 m, coarsened so the
   grid stays ~2400 px/side on big boxes. Mirrored here so the Setup slider can show
   the default and the bounds without a round-trip. */
function autoResM(radiusKm){ return Math.max(40, Math.ceil(2*Math.max(3,radiusKm)*1000/2400)); }
function resBounds(radiusKm){
  return { fine: Math.max(20, Math.ceil(2*Math.max(3,radiusKm)*1000/3200)),   // OOM guard px cap
           coarse: Math.min(500, Math.max(120, autoResM(radiusKm)*4)) };
}
function estimateMinutes(radiusKm, resM){
  const sideKm = 2 * Math.max(3, radiusKm);
  const areaKm2 = sideKm * sideKm;
  // Calibrated against measured runs — and the headline is that runtime is much FLATTER
  // in area than you'd expect: r=16 km took 3.5 min, r=18 km 4.2 min, r=67 km 4.4 min.
  // Most of the cost is a fixed pipeline of sequential Overpass/STAC queries, and the
  // raster stages can't blow up because the API caps the grid at ~2400 px/side by
  // coarsening resolution. So: big constant, gentle area term. A finer user-chosen
  // grid scales the raster term by pixels — (auto/chosen)² — the fixed download cost
  // doesn't change.
  const auto=autoResM(radiusKm), res=resM||auto;
  const factor=(auto/res)*(auto/res);
  const mins = 3.2 + (areaKm2 / 18000) * factor;
  const lo = Math.max(2, Math.round(mins * 0.85));
  const hi = Math.max(lo + 1, Math.round(mins * 1.6));
  return {lo, hi, mins};
}
function fmtElapsed(ms){
  const s = Math.floor(ms / 1000);
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}
function missingSetup(){
  const miss=[];
  // Without this an unset centre would quietly become whatever the map happened to
  // be looking at — which is how a new user ended up with someone else's hunt area
  // pre-filled and could have run an analysis on it.
  if(draft.siteMode==='known'){
    if(!draft.sites.length) miss.push('a hunt site — search, paste coordinates, or drop a waypoint');
  } else if(!draft.center) miss.push('an area — search a place, paste coordinates, or select an area');
  if(!(draft.dates && draft.dates.length===2 && draft.dates[0] && draft.dates[1]))
    miss.push('hunt dates');
  else if(new Date(draft.dates[1]) < new Date(draft.dates[0]))
    miss.push('an end date after the start date');
  return miss;
}
/* A completed analysis cost 3–5 minutes; don't let it evaporate on a stray click.
   The confirmation is a dialog, so this half is async — everything after the guard
   lives in _runAnalysis and is unchanged. */
async function runAnalysis(){
  if(hasResult()){
    const est=estimateMinutes(draft.radius,draft.resM);
    const a=await askModal({kind:'warn', title:t('dlg.rerunTitle'),
      body:`The areas, zones, sites and brief on screen now will be cleared and recomputed
        for the box you have set. About ${est.lo}–${est.hi} min.
        ${PLAN_SAVED
          ? `<span class="note">${t('dlg.rerunSaved')}</span>`
          : `<span class="note">${t('dlg.rerunUnsaved')}</span>`}`,
      actions:PLAN_SAVED
        ? [{id:'no',label:t('dlg.cancel')},{id:'go',label:t('dlg.rerunGo'),primary:true}]
        : [{id:'no',label:t('dlg.cancel')},{id:'save',label:t('dlg.rerunSave')},{id:'go',label:t('dlg.rerunAnyway'),danger:true}]});
    if(a==='save'){ await savePlanNow(true); }
    else if(a!=='go') return;
  }
  return _runAnalysis();
}
function _runAnalysis(){
  const miss=missingSetup();
  if(miss.length){
    const box=document.getElementById('setupErr');
    if(box){ box.className='callout'; box.dataset.kind='warn';
      box.innerHTML=`<span class="mark">!</span><div class="body"><b>Set your ${miss[0]} first</b>
        Hunt dates drive rut phase, weather and which behaviour the model weights — without them
        the result would be for dates you never chose.</div>`; }
    setTab('setup');
    const d=document.getElementById('dateStart'); if(d) d.focus();
    return;
  }
  const btn=document.getElementById('runBtn');
  const setBtn=(t,dis)=>{if(btn){btn.textContent=t;btn.disabled=!!dis;}};
  const est=estimateMinutes(draft.radius,draft.resM), t0=Date.now();
  const line=(head)=>`${head}\n${fmtElapsed(Date.now()-t0)} elapsed · ~${est.lo}–${est.hi} min for this ${Math.round(draft.radius)} km box`;
  // THE HUNT STYLE HAS ONE SOURCE OF TRUTH, AND IT IS hstyleOf().
  // It used to be read off two independent fields — draft.fixedCampMode for the camp
  // pin and SETUP.huntStyle for everything else — which can and did disagree: a stored
  // plan carried huntStyle:'vehicle' WITH fixedCampMode:true, so the engine was handed a
  // fixed camp and told to run a back-to-the-truck hunt around it. It did exactly that,
  // and the brief honestly reported the hunt it was given, not the one the hunter picked.
  // Deriving both from hstyleOf() makes the contradictory pair unrepresentable.
  const hs=hstyleOf();                       // 'camp' | 'vehicle' | 'spike'
  const camping=(hs==='camp');
  const req={species:'moose',lat:draft.center[1],lon:draft.center[0],
    radius_km:Math.max(3,Math.min(120,draft.radius)),
    target_dates:(draft.dates&&draft.dates.length===2)?draft.dates:['2026-09-25','2026-10-05'],
    // EXTRA SEASONS (T9.2). Each window is a full model run — the habitat surface is
    // phase-weighted, so bow in September and rifle in October are different answers on
    // the same ground, not the same answer relabelled. Sent only when the hunter added
    // one, so an ordinary hunt is byte-for-byte the request it always was.
    windows:(draft.windows&&draft.windows.length)
      ? [ ((draft.dates&&draft.dates.length===2)?draft.dates:['2026-09-25','2026-10-05'])
            .slice(0,2).concat([draft.method||'rifle']) ]
        .concat(draft.windows.filter(w=>w&&w[0]&&w[1])
                  .map(w=>[w[0],w[1],w[2]||'rifle']))
      : null,
    method:draft.method||'rifle',
    residency:'quebec_resident',
    // Setup constraints now shape the analysis (no-boat river barriers, walk range, rut-phase weighting)
    // A cabin hunt runs on spike semantics engine-side — you sleep out, just in a building.
    watercraft:SETUP.watercraft, hunt_style:(camping?'spike':hs),
    // Multi-select transportation (ATV/SxS extends reach + splits routes into ride/walk legs).
    transport:{canoe:!!SETUP.transport.canoe,motor:!!SETUP.transport.motor,atv:!!SETUP.transport.atv},
    // Known-sites mode: up to 4 named centres compared; the first one is the AOI centre.
    sites:(draft.siteMode==='known'&&draft.sites.length)?draft.sites.map(s=>[s.ll[1],s.ll[0]]):null,
    // For a vehicle hunt the staging point IS the camp (see synth.py), so the
    // access-to-camp leg is zero and the only real limit is the walk from the truck.
    // ?? not || — a hunter who states 0 means 0, and `or` would silently overwrite it
    // with the default. These must never go out as null: the engine declares them
    // non-nullable floats, and a default only fills a MISSING key, so an explicit null
    // is a 422 the app then reported as "the engine isn't answering".
    walk_access_km:((hs==='vehicle'?draft.walkHunt:draft.walkAccess) ?? 6),
    // Fixed camp: the hunt radius IS how far you go from camp — one number, not two.
    walk_hunt_km:(camping?(draft.huntRadius??draft.walkHunt??5):(draft.walkHunt??3)),
    party_size:draft.party||2,
    // Hunt-from-camp: the AOI centre IS the camp; the analysis narrows to hunt radius.
    fixed_camp:(camping && draft.center)?[draft.center[1],draft.center[0]]:null,
    hunt_radius_km:(camping?(draft.huntRadius??draft.walkHunt??5):null),
    // Analysis-grid override from the processing-detail slider; null = engine auto.
    resolution_m:draft.resM||null};
  // In fixed-camp mode the box only needs to cover the hunt radius + a data margin,
  // so a tight radius doesn't force a huge (slow) acquire.
  if(req.fixed_camp) req.radius_km=Math.max(6,Math.min(120,(req.hunt_radius_km||5)+4));
  // wipe the previous result up front: leaving it on the map while a new box computes
  // invites reading old areas as if they belonged to the new one.
  //
  // But the plan's IDENTITY is not part of the result. Blanking used to rename the plan
  // to "No area yet — moose" and mark it UNSAVED, so re-analysing a saved plan looked
  // like it had been thrown away and replaced by a blank one.
  RUN_ACTIVE = true;
  lockSetupWhileRunning();
  const _keepName = PLAN_NAME, _keepSaved = PLAN_SAVED;
  if(hasResult()){ applyDoc(blankDoc()); paintTabLocks(); setPlanName(_keepName, _keepSaved); }
  // Send them where the progress actually is. Left on Overview they got the empty-state
  // panel — "Nothing on the map yet · Set up a hunt →" — while their own re-run was
  // already computing, which reads as "my plan is gone", not "my plan is working".
  setTab('setup'); syncDocks('setup');
  setBtn(line('ANALYSING… starting'),true);
  // tick the elapsed clock even between polls so it never looks frozen
  let lastHead='ANALYSING… starting', tick=setInterval(()=>setBtn(line(lastHead),true),1000);
  const stop=()=>{ clearInterval(tick); };
  const _ah={'Content-Type':'application/json','X-API-Key':API_KEY};
  if(authTok()) _ah['Authorization']='Bearer '+authTok();
  fetch(API_URL+'/scout',{method:'POST',headers:_ah,body:JSON.stringify(req)})
    .then(async r=>{
      if(r.status===503){
        // The engine is draining for a deploy (scripts/deploy_engine.sh). Nothing is
        // wrong and nothing was lost — say that, rather than the generic "not
        // answering", which reads like the run failed.
        stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); setBtn('RUN ANALYSIS →',false);
        tellModal(t('dlg.updatingTitle'), t('dlg.updatingBody'), 'warn');
        throw new Error('auth');   // reuse the already-handled sentinel
      }
      if(r.status===401){ stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); setBtn('RUN ANALYSIS →',false);
        askModal({title:t('dlg.signinTitle'),
          body:t('dlg.signinBody'),
          actions:[{id:'no',label:t('dlg.notnow')},{id:'go',label:t('dlg.signinGo'),primary:true}]})
          .then(a=>{ if(a==='go') location.href='signin?next=app'; });
        throw new Error('auth'); }
      // ANY other non-OK is the engine ANSWERING with a refusal, which is a different
      // fact from the engine being unreachable — and the hunter is the one who has to
      // act on the difference. A 422 (the app sent something the engine won't accept)
      // used to fall through here, parse as perfectly good JSON, fail the job_id check
      // below and surface as "the engine isn't answering" while the button kept
      // counting elapsed time on a run that had never started.
      if(!r.ok){
        stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); setBtn('RUN ANALYSIS →',false);
        let why='';
        try{ const b=await r.json();
          const d=b&&b.detail;
          why = typeof d==='string' ? d
              : Array.isArray(d) ? d.map(x=>`${(x.loc||[]).slice(1).join('.')}: ${x.msg}`).join(' · ')
              : (b&&b.message)||''; }catch(_){}
        tellModal(t('dlg.rejectTitle','The engine turned this run down'),
          escHtml(`HTTP ${r.status}${why?' — '+why:''}`)+
          `<br><br>${escHtml(t('dlg.rejectBody','Nothing was lost and nothing is running — the request never started. This is a fault in the app, not in your setup; the details above identify it.'))}`,
          'danger');
        throw new Error('auth');   // reuse the already-handled sentinel
      }
      return r.json();
    }).then(j=>{
      if(!j.job_id) throw new Error('no job');
      const STAGE={acquire:'fetching terrain, imagery, burns & hydro',terrain:'terrain analysis',
        habitat:'habitat model',behavior:'behavioural surfaces',access:'access & pack-out',
        synth:'placing areas & sites',contract:'building your plan'};
      const _jh=authTok()?{'Authorization':'Bearer '+authTok()}:{};
      // Remember the job so a reload — or a give-up — can pick the run back up.
      // Losing a ten-minute analysis to a browser refresh is not acceptable.
      rememberJob(j.job_id);
      pollJob(j.job_id,_jh,STAGE,stop,setBtn,line,h=>{lastHead=h;});
    })
    .catch(e=>{ stop();            // the clock must die with the run, or the button
                                   // reports minutes of progress on nothing at all
      RUN_ACTIVE=false; lockSetupWhileRunning(); if(e && e.message==='auth') return;   // already handled above
      setBtn('RUN ANALYSIS →',false);
      tellModal(t('dlg.offlineTitle'),
        t('dlg.offlineBody'),'warn');
      setTab('overview'); });
}

/* draft AOI box preview on the map (radius → box) */
function draftBox(){
  if(!draft.center) return null;
  const [lon,lat]=draft.center, r=draft.radius;
  const dLat=r/111, dLon=r/(111*Math.cos(lat*Math.PI/180));
  return [[lon-dLon,lat+dLat],[lon+dLon,lat+dLat],[lon+dLon,lat-dLat],[lon-dLon,lat-dLat],[lon-dLon,lat+dLat]];
}
/* radius circle around a point, as a 64-seg ring (for the live known-site preview) */
function _radiusRing(ll,rkm){
  const [lon,lat]=ll, ring=[];
  for(let i=0;i<=64;i++){ const a=i/64*2*Math.PI;
    ring.push([lon+rkm/(111*Math.cos(lat*Math.PI/180))*Math.cos(a), lat+rkm/111*Math.sin(a)]); }
  return ring;
}
function drawDraft(fit){
  _wireDraftBoxEdit();                    // idempotent — box move/resize handlers
  const feats=[];
  if(draft.siteMode==='known' && draft.sites.length){
    // KNOWN SITES: a dot per site + a live radius circle that tracks the slider.
    // NOT in fixed-camp mode. There is exactly one entry there and it is the CAMP —
    // numbering it "1" says nothing, and the numbered dot is drawn at the identical
    // coordinate as the camp badge, where its label suppressed the camp icon outright
    // (T10.5). A camp is not a site index.
    draft.sites.forEach((s,i)=>{
      if(!draft.fixedCampMode)
        feats.push({type:'Feature',geometry:{type:'Point',coordinates:s.ll.slice()},properties:{site:1,n:String(i+1)}});
      feats.push({type:'Feature',geometry:{type:'Polygon',coordinates:[_radiusRing(s.ll,draft.radius)]},properties:{}});
    });
    if(draft.fixedCampMode)
      feats.push({type:'Feature',geometry:{type:'Point',coordinates:draft.sites[0].ll.slice()},properties:{camp:1}});
  } else {
    const box=draftBox();
    if(box) feats.push({type:'Feature',geometry:{type:'Polygon',coordinates:[box]},properties:{}});
    // Fixed camp: mark WHERE the camp sits (the analysis centre) the moment it's set.
    if(draft.fixedCampMode && draft.center)
      feats.push({type:'Feature',geometry:{type:'Point',coordinates:draft.center.slice()},properties:{camp:1}});
  }
  const data=fc(feats);
  if(map.getSource('draft')) map.getSource('draft').setData(data);
  else { map.addSource('draft',{type:'geojson',data});
    map.addLayer({id:'draft-fill',type:'fill',source:'draft',filter:['==','$type','Polygon'],paint:{'fill-color':'#e2c044','fill-opacity':0.06}});
    map.addLayer({id:'draft-line',type:'line',source:'draft',filter:['==','$type','Polygon'],
      paint:{'line-color':'#e2c044','line-width':2,'line-dasharray':[3,2]}});
    map.addLayer({id:'draft-site',type:'circle',source:'draft',filter:['==',['get','site'],1],
      paint:{'circle-radius':7,'circle-color':'#e2c044','circle-stroke-color':'#0b0f0d','circle-stroke-width':2}});
    map.addLayer({id:'draft-site-n',type:'symbol',source:'draft',filter:['==',['get','site'],1],
      layout:{'text-field':['get','n'],'text-size':10,'text-font':['Open Sans Semibold'],'text-allow-overlap':true},
      paint:{'text-color':'#0b0f0d'}});
    map.addLayer({id:'draft-camp',type:'symbol',source:'draft',filter:['==',['get','camp'],1],
      layout:{'icon-image':'base_camp','icon-size':['interpolate',['linear'],['zoom'],8,0.9,11,1.25,15,2],'icon-allow-overlap':true,
        'text-optional':true,
        'text-field':'CAMP','text-offset':[0,1.4],'text-size':11,'text-font':['Open Sans Semibold']},
      paint:{'text-color':'#e6c98a','text-halo-color':'#0b0f0d','text-halo-width':1.5}}); }
  // Refit so every added site (plus its radius) is on screen.
  if(fit && draft.siteMode==='known' && draft.sites.length){
    let w=1e9,s=1e9,e=-1e9,n=-1e9;
    draft.sites.forEach(st=>_radiusRing(st.ll,draft.radius).forEach(c=>{w=Math.min(w,c[0]);e=Math.max(e,c[0]);s=Math.min(s,c[1]);n=Math.max(n,c[1]);}));
    map.fitBounds([[w,s],[e,n]],{padding:80,duration:600});
  }
}
let _boxCleanup=null;
function cancelBoxDraw(){ if(_boxCleanup) _boxCleanup(); }
function startBoxDraw(){
  // Box-draw takes over the drag gesture, so the cursor has to say so: crosshair
  // while you are aiming, grabbing while you are actually dragging the corner out.
  // Without it the mode is invisible and the map just stops panning.
  map.getCanvas().style.cursor='crosshair';
  document.body.classList.add('boxdraw');
  map.dragPan.disable();
  let start=null;
  const onDown=(e)=>{ start=e.lngLat; document.body.classList.add('boxdraw-active'); };
  const onMove=(e)=>{ if(!start)return;
    const b=[[start.lng,start.lat],[e.lngLat.lng,start.lat],[e.lngLat.lng,e.lngLat.lat],[start.lng,e.lngLat.lat],[start.lng,start.lat]];
    map.getSource('draft').setData(fc([{type:'Feature',geometry:{type:'Polygon',coordinates:[b]},properties:{}}]));};
  // RELEASING the mouse commits the box (the intuitive gesture); ESC still bails out.
  // NOTE: every element touched here must exist in the CURRENT setup markup — an id that
  // went away in a redesign made this throw mid-commit, which left the mode armed and
  // "release does nothing, next click starts a new box" (user-reported).
  const onUp=(e)=>{ if(!start)return;
    const clon=(start.lng+e.lngLat.lng)/2, clat=(start.lat+e.lngLat.lat)/2;
    const halfW=hav([start.lng,clat],[e.lngLat.lng,clat])/2, halfH=hav([clon,start.lat],[clon,e.lngLat.lat])/2;
    draft.center=[clon,clat]; draft.radius=Math.max(2,Math.round(Math.max(halfW,halfH)));
    const rs=document.getElementById('radius'); if(rs) rs.value=Math.min(120,Math.round(toU(draft.radius)));
    const rv=document.getElementById('radVal'); if(rv) rv.textContent=Math.round(toU(draft.radius))+' '+unitBig();
    const le=document.getElementById('locEntry'); if(le) le.value=clat.toFixed(4)+', '+clon.toFixed(4);
    cleanup(); drawDraft();};
  const onKey=(ev)=>{ if(ev.key==='Escape') cleanup(); };
  function cleanup(){
    map.getCanvas().style.cursor=''; map.dragPan.enable();
    document.body.classList.remove('boxdraw','boxdraw-active');
    const b=document.getElementById('dragBox');
    if(b){ b.classList.remove('on'); b.innerHTML=railIcon('boxselect',15); }   // restore the icon, don't clobber it
    map.off('mousedown',onDown); map.off('mousemove',onMove); map.off('mouseup',onUp);
    window.removeEventListener('keydown',onKey);
    _boxCleanup=null;
  }
  _boxCleanup=cleanup;
  window.addEventListener('keydown',onKey);
  map.on('mousedown',onDown); map.on('mousemove',onMove); map.on('mouseup',onUp);
}
/* Once drawn, the search box is a live object: hover an EDGE to resize (cursor shows
   which way), hover the MIDDLE to move (move cursor), drag to do it. Radius + slider
   track the resize in real time. Active only on the Setup tab, find-sites mode, with
   no other tool armed. */
function _wireDraftBoxEdit(){
  if(window._draftEditWired) return; window._draftEditWired=true;
  const EDGE=8;                                   // px tolerance for grabbing an edge
  let drag=null;                                  // {mode:'move'|'resize', startLL, c0, r0}
  const zone=(e)=>{
    // A run is computing THIS box. Letting it be dragged mid-run leaves the map showing
    // one area while the engine analyses another, and the result lands looking wrong.
    if(RUN_ACTIVE) return null;
    if(curTab!=='setup'||draft.siteMode!=='find'||!draft.center||drawTool||drawEditId||_boxCleanup) return null;
    const box=draftBox(); if(!box) return null;
    const nw=map.project({lng:box[0][0],lat:box[0][1]}), se=map.project({lng:box[2][0],lat:box[2][1]});
    const x=e.point.x,y=e.point.y;
    const inX=x>nw.x-EDGE&&x<se.x+EDGE, inY=y>nw.y-EDGE&&y<se.y+EDGE;
    if(!inX||!inY) return null;
    const nL=Math.abs(x-nw.x)<EDGE, nR=Math.abs(x-se.x)<EDGE, nT=Math.abs(y-nw.y)<EDGE, nB=Math.abs(y-se.y)<EDGE;
    if((nL||nR)&&(nT||nB)) return {mode:'resize',cursor:'nwse-resize'};
    if(nL||nR) return {mode:'resize',cursor:'ew-resize'};
    if(nT||nB) return {mode:'resize',cursor:'ns-resize'};
    if(x>nw.x&&x<se.x&&y>nw.y&&y<se.y) return {mode:'move',cursor:'move'};
    return null;
  };
  map.on('mousemove',e=>{
    if(drag){
      if(drag.mode==='move'){
        draft.center=[drag.c0[0]+(e.lngLat.lng-drag.startLL.lng), drag.c0[1]+(e.lngLat.lat-drag.startLL.lat)];
      } else {
        const dxKm=hav([draft.center[0],draft.center[1]],[e.lngLat.lng,draft.center[1]]);
        const dyKm=hav([draft.center[0],draft.center[1]],[draft.center[0],e.lngLat.lat]);
        draft.radius=Math.max(2,Math.min(120,Math.round(Math.max(dxKm,dyKm))));
        const rs=document.getElementById('radius'); if(rs) rs.value=Math.min(120,Math.round(toU(draft.radius)));
        const rv=document.getElementById('radVal'); if(rv) rv.textContent=Math.round(toU(draft.radius))+' '+unitBig();
      }
      drawDraft(); return;
    }
    const z=zone(e);
    // Only own the cursor while we're actually over the box (and release it after),
    // so the drawings' pointer cursor and the tools' crosshair are never fought over.
    if(z){ map.getCanvas().style.cursor=z.cursor; window._boxCur=true; }
    else if(window._boxCur){ map.getCanvas().style.cursor=drawTool?'crosshair':''; window._boxCur=false; }
  });
  map.on('mousedown',e=>{
    const z=zone(e); if(!z) return;
    e.preventDefault(); map.dragPan.disable();
    drag={mode:z.mode,startLL:e.lngLat,c0:draft.center.slice(),r0:draft.radius};
  });
  map.on('mouseup',()=>{ if(!drag) return; drag=null; map.dragPan.enable();
    const le=document.getElementById('locEntry');
    if(le&&draft.center) le.value=draft.center[1].toFixed(4)+', '+draft.center[0].toFixed(4); });
}

/* Nominatim geocode (no key) */
function geocode(q){
  if(!q||q.length<3) return Promise.resolve([]);
  return fetch('https://nominatim.openstreetmap.org/search?format=json&limit=5&q='+encodeURIComponent(q),
    {headers:{'Accept':'application/json'}}).then(r=>r.json()).catch(()=>[]);
}

// #67: render a structured field-plan section (DOC.field_plan.*) — calling sequence,
// day plan, ground-truth checklist — that the engine emits as data. Converts the
// **bold**/*italic* the engine writes into HTML. Empty/absent section → nothing.
function briefMD(s){ return (s||'').replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/\*(.+?)\*/g,'<i>$1</i>'); }
function briefSection(sec, numbered){
  if(!sec||!(sec.items||[]).length) return '';
  let h=`<h3>${sec.title}</h3>`;
  if(sec.intro) h+=`<p class="s">${briefMD(sec.intro)}</p>`;
  if(sec.headline) h+=`<p><b>${briefMD(sec.headline)}</b></p>`;
  const tag=numbered?'ol':'ul';
  h+=`<${tag} class="s" style="margin:6px 0 8px 18px;padding:0">`
    +sec.items.map(it=>`<li style="margin:3px 0">${briefMD(it)}</li>`).join('')+`</${tag}>`;
  if(sec.note) h+=`<p class="s" style="opacity:.82"><i>${briefMD(sec.note)}</i></p>`;
  return h;
}
/* SEASON COMPARISON (T9.2). Each window was a full model run — the habitat surface is
   phase-weighted, so the same ground genuinely scores differently in September and
   October. This is the pros/cons the hunter asked for, and the honest framing is that
   they are different HUNTS, not one hunt on two dates. */
function windowCompareBlock(){
  const W=DOC.windows||[]; if(W.length<2) return '';
  const best=W.reduce((a,b)=>((b.best_habitat||0)>(a.best_habitat||0)?b:a), W[0]);
  const rows=W.map(w=>{
    if(!w.ok) return `<div style="padding:8px 0;border-top:1px solid var(--line,rgba(255,255,255,.08))">
      <div class="row" style="justify-content:space-between">
        <span class="mono t-micro">${escHtml(w.start)} → ${escHtml(w.end)}</span>
        <span class="t-micro" style="color:var(--danger)">could not be analysed</span></div></div>`;
    const win = w.window===best.window && W.filter(x=>x.ok).length>1;
    return `<div style="padding:8px 0;border-top:1px solid var(--line,rgba(255,255,255,.08))">
      <div class="row" style="justify-content:space-between">
        <span class="mono t-micro">${escHtml(w.start)} → ${escHtml(w.end)}${w.method?' · '+escHtml(w.method):''}${w.phase?' · '+escHtml(w.phase):''}</span>
        <span class="t-micro"${win?' style="color:var(--good)"':''}>${w.areas} area${w.areas===1?'':'s'} · ${w.total_km2} km² · habitat ${w.best_habitat}${win?' · best':''}</span></div>
      ${w.rut_read?`<div class="s" style="margin-top:4px">${w.rut_read}</div>`:''}
      ${!w.areas?`<div class="s" style="margin-top:4px;color:var(--text-3)">No ground cleared the bar in this window — the phase weighting moves the model off this cover.</div>`:''}
    </div>`;
  }).join('');
  return `<div class="sec">
    <div class="kicker">Seasons compared</div>
    <h2 style="margin:2px 0 8px">Which window is worth taking?</h2>
    <p class="s">Each of these was analysed on its own. The model weights habitat
    differently before, during and after the rut, so the same ground is not the same
    hunt in September and October — the areas below are ranked across all of them.
    Pick an area and the whole brief under it — rut read, strategy, day plan, weather —
    is written for <b>that area's window</b>, not for the first one.</p>
    ${rows}
  </div>`;
}

/* THE CAMP VERDICT + THE ROTATION (T9.3).
   Rendered from doc.camp_plan, which the engine only emits for a fixed camp — so this
   returns nothing for every other hunt style and no caller has to special-case it. */
function campPlanBlock(){
  const cp=DOC.camp_plan; if(!cp||cp.kind!=='camp') return '';
  const v=cp.verdict||{};
  if(!v.areas) return `<div class="sec"><div class="kicker">This camp</div>
    <p class="s">${escHtml(v.line||'')}</p></div>`;
  const rob=cp.robust||{};
  const robRows=Object.keys(rob).sort((x,y)=>rob[y].octants-rob[x].octants).map(fa=>{
    const r=rob[fa];
    return `<div class="row" style="justify-content:space-between;padding:3px 0">
      <span class="t-micro">Area ${fa}</span>
      <span class="t-micro" style="color:${r.octants>=4?'var(--good)':r.octants>=2?'var(--text-2)':'var(--danger)'}">
        works on ${r.octants}/8 winds · ${r.winds.join(' ')}</span></div>`;
  }).join('');
  const rot=(cp.rotation||[]).slice(0,14).map(d=>{
    const pick = d.areas&&d.areas.length ? `Area ${d.areas.join(' or ')}`
               : (d.second&&d.second.length ? `Area ${d.second[0]} (closest)` : '—');
    return `<div class="row" style="justify-content:space-between;padding:4px 0;border-top:1px solid var(--line,rgba(255,255,255,.08))">
      <span class="mono t-micro">${escHtml(d.date||'')} · ${escHtml(d.wind_from||'?')}${d.wind_kmh!=null?' '+Math.round(d.wind_kmh)+'k':''}${d.t_max_c!=null?' · '+Math.round(d.t_max_c)+'°':''}</span>
      <span class="t-micro" style="text-align:right">${escHtml(pick)}${d.hot?' <span style="color:var(--warn,#e2c044)">· hot</span>':''}</span></div>`;
  }).join('');
  return `<div class="sec">
    <div class="kicker">This camp</div>
    <h2 style="margin:2px 0 8px">How good is hunting here?</h2>
    <p class="s">${escHtml(v.line||'')}</p>
    <div class="axes" style="margin:8px 0 10px">
      <div class="ax"><span class="k">HABITAT</span><span class="bar"><i style="width:${Math.round((v.habitat||0)*100)}%"></i></span><span class="v">${v.habitat}</span></div>
    </div>
    ${v.packin_max_km!=null?`<div class="s">Pack-out from ${v.packin_min_km}–${v.packin_max_km} km, camp to area.</div>`:''}
    ${(v.caveats||[]).map(c=>`<div class="ev" data-kind="con"><span class="op">!</span><span class="txt">${escHtml(c)}</span></div>`).join('')}
    ${cp.rut_read?`<div class="callout" data-kind="info" style="margin-top:10px"><span class="mark">i</span><div class="body">${cp.rut_read}</div></div>`:''}
    <div class="t-micro" style="margin-top:14px">WHICH AREA, WHICH DAY</div>
    <p class="s">${escHtml(cp.how||'')}</p>
    ${rot?`<div style="margin-top:6px">${rot}</div>`:'<p class="s">No forecast for these dates yet.</p>'}
    ${robRows?`<div class="t-micro" style="margin-top:14px">WIND ROBUSTNESS</div>
      <p class="s">How many of the eight wind directions each area can be hunted on — the
      number that matters for a stand you build once and use for years.</p>
      <div style="margin-top:4px">${robRows}</div>`:''}
  </div>`;
}

/* THE BRIEF IS WRITTEN FOR ONE AREA, AND AN AREA BELONGS TO ONE WINDOW (T10.1).
   Every dated section — the rut read, the strategy, the day plan, the weather — is a
   function of the DATES, so on a two-window run there are two of each and reading them
   off the top-level DOC gives you window 1's answer for every area. That is what
   happened: a bow-season area briefed with rifle-season advice, with nothing saying so.

   `wsec(area, key)` returns the section belonging to THAT area's window, falling back
   to the top level for single-window runs and for plans saved before this existed.
   Nothing else in the brief should reach for DOC.<dated section> directly. */
/* WINDOW FILTER (T10.3) — all windows, or one.
   Reported: "They overlap. Im guessing these are different for each season, but thats
   not clear on the map." Two windows share their geography, so a rifle-season area and a
   bow-season area land on top of each other and read as one contradictory pile. The
   engine has always known which is which (`window` on every merged feature); the map
   just never asked.

   This is a DISPLAY control. It filters — it never recomputes, never reorders and never
   changes a score, so what you see under "All windows" is exactly what the brief says. */
let winSel=null;                 // null = all windows
const WIN_SOURCES=['areas','areaLabels','sites','camps','staging','routes'];
let _winBaseFilter=null;         // each layer's own filter, captured once
function applyWindowFilter(){
  // `getStyle()` returns UNDEFINED before the style is loaded — not an empty style — and
  // this runs from the source refresh, which can land first. Guarding on the method
  // existing is not enough; it is the RETURN that is missing. An exception here would
  // abort the rest of the refresh, so it is worth more than a silent skip: retry on
  // `idle` (never `load`, which fires once — see applyTerrain) so the filter is actually
  // applied rather than quietly dropped.
  const st=(map&&map.getStyle)?map.getStyle():null;
  if(!st||!st.layers){ if(map&&map.once) map.once('idle',applyWindowFilter); return; }
  if(!_winBaseFilter){
    _winBaseFilter={};
    st.layers.forEach(l=>{
      if(WIN_SOURCES.includes(l.source)) _winBaseFilter[l.id]=map.getFilter(l.id)||null;
    });
  }
  Object.keys(_winBaseFilter).forEach(id=>{
    if(!map.getLayer(id)) return;
    const base=_winBaseFilter[id];
    if(winSel==null){ map.setFilter(id, base); return; }
    // -1 is "this feature predates windows" — a single-window or legacy plan. It stays
    // visible under every selection, because hiding it would be claiming it belongs to
    // some OTHER window, which is a stronger claim than the data supports.
    const cond=['any',['==',['get','win'],winSel],['==',['get','win'],-1]];
    map.setFilter(id, base?['all',base,cond]:cond);
  });
  buildShooters();               // derived from window._sites, so it filters separately
  if(document.getElementById('list')&&!DOC.blank) buildPanel();
}
function inWindow(o){ return winSel==null || o==null || o.window==null || o.window===winSel; }
function buildWindowPill(){
  const el=document.getElementById('winPill');
  if(!el) return;
  const W=DOC.windows||[];
  // One window is not a choice. Offering the control anyway would be a filter that
  // filters nothing, which reads as a broken control rather than an absent one.
  if(W.length<2){ el.classList.add('hidden'); el.innerHTML=''; winSel=null; return; }
  el.classList.remove('hidden');
  const chip=(sel,label,sub)=>`<button class="wchip${winSel===sel?' on':''}" data-win="${sel==null?'':sel}">
    <span class="wname">${escHtml(label)}</span>${sub?`<span class="wsub">${escHtml(sub)}</span>`:''}</button>`;
  // Name the method on EVERY chip when the windows differ by weapon, not just the
  // non-rifle one. Suppressing "rifle" as the default left one chip reading "bow" and
  // the other reading nothing, which asks the hunter to know what the blank means — and
  // the method is the thing they asked to see. When both windows use the same weapon it
  // distinguishes nothing, so it goes.
  const methods=new Set(W.map(w=>w.method||'rifle'));
  el.innerHTML=`<span class="pcap">${t('win.cap','SEASON')}</span>`
    + chip(null,t('win.all','All'),W.length+' windows')
    + W.map(w=>chip(w.window, `${w.start} → ${w.end}`,
        methods.size>1?(w.method||'rifle'):'')).join('');
  el.querySelectorAll('.wchip').forEach(b=>b.onclick=()=>{
    const v=b.dataset.win;
    winSel=(v==='')?null:+v;
    buildWindowPill(); applyWindowFilter();
  });
}
/* A SHORT identifier for the window a thing belongs to (T10.3) — for card titles and
   badges, where `windowLabel`'s full date range does not fit. Empty on a single-window
   run, because there "season 1" is noise pretending to be rigour.

   Prefers the METHOD, because that is what the hunter asked to see and what actually
   changes the advice ("shooting locations for a bow are going to be different"). Falls
   back to the start date when both windows use the same weapon. */
function windowTag(a){
  const W=DOC.windows||[]; if(W.length<2) return '';
  const w=windowOf(a); if(!w) return '';
  const methods=new Set(W.map(x=>x.method||'rifle'));
  if(methods.size>1 && w.method) return w.method;
  return String(w.start||'').slice(5);      // MM-DD — the year is the same for all of them
}
function windowOf(a){
  const W=DOC.windows||[];
  if(!W.length || !a || a.window==null) return null;
  return W.find(w=>w.window===a.window)||null;
}
function wsec(a, key){
  const w=windowOf(a);
  if(w && w.brief && w.brief[key]!=null) return w.brief[key];
  return DOC[key];
}
/* Names the window a section belongs to, but only when there is more than one — on a
   single-window run saying "window 1" everywhere would be noise pretending to be rigour. */
function windowLabel(a){
  const W=DOC.windows||[]; if(W.length<2) return '';
  const w=windowOf(a); if(!w) return '';
  const m=w.method&&w.method!=='rifle'?` · ${escHtml(w.method)}`:'';
  return ` <span class="mono" style="color:var(--text-3);font-weight:400"> · ${escHtml(w.start)} → ${escHtml(w.end)}${m}</span>`;
}
/* The dates a DOCUMENT covers, which on a multi-window run is not one range (T10.1).
   The exported PDF read `dates 2026-10-10 → 2026-10-25` on a two-window run — window 1
   only — which is how the whole problem was spotted. A document covering two windows
   has to say two windows. */
function headerDates(){
  const W=DOC.windows||[];
  if(W.length>1) return 'windows ' + W.map(w=>`${w.start} → ${w.end}`).join('  ·  ');
  return 'dates ' + (((DOC.meta||{}).target_dates)||[]).join(' → ');
}
function windowDates(a){
  const w=windowOf(a);
  if(w && w.dates && w.dates.length) return w.dates;
  if(w && w.start) return [w.start, w.end];
  return (DOC.meta&&DOC.meta.target_dates)||(draft.dates||[]);
}

/* ---------------- brief — scoped to the CHOSEN area ---------------- */
function renderBrief(){
  const a=(DOC.areas||[]).find(x=>x.rank===lastSel)||(DOC.areas||[])[0];
  if(!a){ document.getElementById('brief').innerHTML=
    `<div class="sec"><div class="t-micro" style="margin-bottom:10px">No brief yet</div>
      <p class="s">A brief is written for a specific area, so there's nothing to write until
      you've run an analysis. Set up a hunt and the brief fills itself in.</p>
      <button class="btn btn--primary btn--block" onclick="setTab('setup')">Set up a hunt →</button></div>`;
    return; }
  const g=DOC.legal, st=a.stats||{};
  // every dated section below comes from THIS AREA'S window — see wsec()
  const RUT=wsec(a,'rut')||{}, STRAT=wsec(a,'strategy'), FP=wsec(a,'field_plan'),
        RECS=wsec(a,'recommendations')||[], rutT=(RUT.targets)||[];
  const camp=DOC.camps.find(c=>(c.member_areas||[]).includes(a.rank));
  const wps=DOC.waypoints.filter(w=>w.properties.focus_area===a.rank && SITE_TYPES.includes(w.type));
  const dates=windowDates(a);
  // THE BRIEF DESCRIBES THE PLAN, NOT THE PANEL. These used to read SETUP.huntStyle and
  // SETUP.watercraft — live setup state that has already moved on by the time a saved
  // plan is reopened, and that carries no notion of a cabin hunt at all. The result was
  // a brief for a hunt out of a fixed camp opening with "back to the truck nightly".
  // DOC.meta is what the engine was actually given, so it is the only honest source.
  const _m=DOC.meta||{};
  const styleTxt = _m.fixed_camp ? 'hunting out of your camp'
    : (_m.hunt_style||SETUP.huntStyle)==='vehicle' ? 'back to the truck nightly' : 'spike camp';
  const _wc=_m.watercraft||SETUP.watercraft;
  const wcTxt={none:'no boat (foot access)',canoe:'canoe',motor:'motorboat'}[_wc]||_wc;
  const g2=DOC.legal||{};
  let h=`<div class="seg" style="margin-bottom:14px">`+
    DOC.areas.map(x=>`<button class="briefpick" data-rank="${x.rank}" ${x.rank===a.rank?'aria-pressed="true"':''}>Area ${x.rank}</button>`).join('')+`</div>`;
  // T9.3 — A CAMP HUNT IS ASKED A DIFFERENT QUESTION. The area tabs above still let a
  // hunter drill into any one piece of ground, but for a fixed camp the brief LEADS with
  // the camp, because the areas around it are complements they will hunt across a week,
  // not candidates competing for it.
  h+=windowCompareBlock();
  h+=campPlanBlock();
  // ---- the plan this brief is written for ----
  h+=`<div class="kicker">Field brief · Zone ${g2.zone||'?'} · ${(g2.huntable_tenures||['—'])[0]} · ${g2.diy_possible?'DIY':'restricted'}</div>
    <h2>Your hunt — Area ${a.rank}</h2>
    <div class="dataline">${a.area_km2} KM² · CAMP ${a.camp} · ${a.centroid[1].toFixed(4)}, ${a.centroid[0].toFixed(4)}`
    +`${a.conf?` · CONF ${Math.round(a.conf.score*100)}%`:''}</div>
    ${a.habitat_score!=null?`<div class="axes" style="margin:0 0 14px">
      <div class="ax"><span class="k">${t('ov.habitat')}</span><span class="bar"><i style="width:${Math.round(a.habitat_score*100)}%"></i></span><span class="v">${a.habitat_score}</span></div>
      <div class="ax"><span class="k">${t('ov.packout')}</span><span class="bar"><i class="ret" style="width:${Math.round((a.retrieval_score||0)*100)}%"></i></span><span class="v">${a.retrieval_score}</span></div>
    </div>`:''}
    <div class="callout" data-kind="info"><span class="mark">i</span><div class="body">
      <i style="font-family:var(--serif)">À valider sur le terrain.</i> Every mark below is a hypothesis
      to ground-truth on foot — the model reads habitat, not animals.</div></div>
    <p class="planline">If you hunt <b>Area ${a.rank}</b> (${a.area_km2} km²)${dates.length?`, <b>${dates.join(' – ')}</b>`:''}, running a <b>${styleTxt}</b> with <b>${wcTxt}</b> — here's how to make the most of it.</p>`;
  // ---- where your dates land + how that shapes the hunt ----
  if(RUT&&(RUT.hunt_read||rutT.length)){ h+=`<h3>${t('br.dates')}${windowLabel(a)}</h3>`;
    if(RUT.hunt_read) h+=`<p class="huntread">${RUT.hunt_read}</p>`;
    if(rutT.length) h+=`<div class="rutdates">`+rutT.map(t=>
      `<span class="pill" style="background:#2a2117;color:#f2b98a">${t.date} · ${t.phase} · ${Math.round(t.responsiveness*100)}%</span>`).join('')+`</div>`;
    if(RUT.trigger_note) h+=`<p class="s" style="color:#e0b985;margin-top:6px">${RUT.trigger_note}</p>`; }
  // ---- how to hunt this ground ----
  h+=`<h3>${t('br.how')}</h3>`;
  if(STRAT){ h+=`<p><b>${STRAT.headline}</b> ${STRAT.approach||''} ${STRAT.calling||''}`
    +`${STRAT.movement?` <span class="s">${STRAT.movement}</span>`:''}</p>`;
    if(STRAT.scent_warning) h+=`<div class="warn">${STRAT.scent_warning}</div>`; }
  // #67: the concrete phase-keyed calling script, right where you decide how to hunt.
  if(FP) h+=briefSection(FP.calling_sequence, true);
  h+=`<p class="why">${a.why||''}</p>
    <p class="s"><b>Working for you:</b> ${(a.pros||[]).join('; ')||'—'}.</p>
    <p class="s"><b>Watch-outs:</b> ${(a.cons||[]).join('; ')||'—'}.</p>`;
  // ---- getting in & out for your kit ----
  h+=`<h3>${t('br.inout')}</h3>`;
  if(a.access_flag) h+=`<div class="warn">${a.access_flag}</div>`;
  if(camp) h+=`<p>Base at <b>Camp ${a.camp}</b> — in via ${camp.access_type}, pack-in ≤ ${km(camp.max_packin_km)} to the hunt. Running ${styleTxt} with ${wcTxt}.</p>`;
  else h+=`<p>Running ${styleTxt} with ${wcTxt}.</p>`;
  if(st.dist_water_m!=null) h+=`<p class="s">water ${metres(st.dist_water_m)} · to road ${km((st.dist_road_m||0)/1000)} · slope ${st.mean_slope_deg}°</p>`;
  h+=`<p class="s">Legal: Zone <b>${g.zone}</b> · ${g.diy_possible?'DIY possible':'restricted'} · ${(g.huntable_tenures||[]).join(', ')||'—'}. ${(g.verify||[]).length?'Verify current season/rules before you go.':''}</p>`;
  // ---- day plan ----
  h+=`<h3>Your day plan — ${wps.length} site${wps.length!==1?'s':''}</h3>`+
    wps.map(w=>{
      const ow=w.properties.optimal_wind||{};
      const when=w.properties.when||'';
      // The approach/wind note was computed per site but dropped here — a hunter needs
      // to know WHICH WAY to walk in, not just when to sit (audit #51). At first/last
      // light thermal drainage usually beats the forecast wind (see the Field tab).
      const app=ow.note?` <span class="s" style="opacity:.85">— ${ow.note}</span>`:'';
      return `<p><b style="color:${COLORS[w.type]||'#ccc'}">●</b> <b>${LABELS[w.type]||w.type}</b>${when?' — '+when:''}${app}</p>`;
    }).join('');
  // ---- what the score was built from ----
  const fw=((DOC.methodology||{}).factors_weighted)||[];
  if(fw.length){
    h+=`<h3>${t('br.factors')}</h3>`;
    fw.forEach(f=>{
      const m=f.match(/\((\d+)%\)\s*$/);
      const pct=m?+m[1]:null, label=f.replace(/\s*\(\d+%\)\s*$/,'');
      h+=`<div class="wf"><span>${label}</span>
        <span class="wfbar"><i style="width:${pct?Math.min(100,pct*2.2):40}%"></i></span></div>`;
    });
  }
  // ---- how to do better (the leverage) ----
  const recs=RECS;
  if(recs.length){ h+=`<h3>${t('br.better')}</h3><div class="recs">`+
    recs.map(r=>`<div class="rec rec-${r.impact||'low'}"><span class="recicon">${r.icon||'•'}</span><span>${r.text}</span></div>`).join('')+`</div>`; }
  // #67: the trip-level close — ordered day-by-day plan + boots-on-ground checklist.
  if(FP){ h+=briefSection(FP.day_plan, false)
    +briefSection(FP.ground_truth, false); }
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
  {const _fe=map.getSource('feedEdgeZones'); if(_fe) _fe.setData(fc((d.feed_edge_zones||[]).map(z=>({type:'Feature',geometry:{type:'Polygon',coordinates:[z.ll]},properties:{area_km2:z.area_km2}}))));}
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
/* The wind calendar is a rail tool now, so the tab no longer decides whether its
   strip is up — you do. The tab only decides whether it is ALLOWED up (it means
   nothing on Setup or Brief), and it was covering the mandatory scale bar. */
const TAB_SHOW={setup:{setup:1},overview:{panel:1,weather:1},
  field:{panel:1,weather:1},brief:{brief:1}};
function setTab(name){
  const ids=['panel','setup','brief'];
  const show=TAB_SHOW[name]||{};
  ids.forEach(id=>{const el=document.getElementById(id); if(el) el.classList.toggle('hidden',!show[id]);});
  toggleWeather(!!show.weather && weatherWanted);
  document.querySelectorAll('#tabbar button').forEach(b=>b.classList.toggle('on',b.dataset.tab===name));
  // the draft AOI box is a Setup-only preview — hide it elsewhere so it doesn't
  // cover the map or intercept zone clicks.
  // ...and so are the numbered site dots, which used to survive onto Overview/Field/
  // Brief and sit on top of the analysis's own markers (T10.5).
  const dv=(name==='setup')?'visible':'none';
  ['draft-fill','draft-line','draft-site','draft-site-n']
    .forEach(id=>map.getLayer&&map.getLayer(id)&&map.setLayoutProperty(id,'visibility',dv));
  // The draft CAMP pin is the same camp the analysis already draws. Showing both put
  // two camp icons on the map — and when the engine was inventing its own camp site,
  // two icons in two DIFFERENT places, which reads as "here is your camp, and here is
  // the one we recommend". Once a result exists the analysis owns the marker.
  const cv=(name==='setup'||!hasResult())?'visible':'none';
  if(map.getLayer&&map.getLayer('draft-camp')) map.setLayoutProperty('draft-camp','visibility',cv);
  curTab=name;
  // Field = the per-area field plan + DEEP re-analysis of the chosen area.
  if(name==='field'){
    if(document.getElementById('detail').classList.contains('hidden')) selectArea(lastSel);
    enterDeep(lastSel);
  } else {
    exitDeep();
  }
  // Thermal drift belongs to the Field tab — where you're planning a specific
  // approach — not to Overview/Setup/Brief. Force it off when you leave.
  if(name!=='field'){
    const tr=LAYERS.find(r=>r.k==='thermal');
    if(tr&&tr.on){ tr.on=false; setVis(LYR_MAP.thermal,false); }
  }
  if(name==='brief') renderBrief();   // scope the brief to the currently chosen area
  syncDocks(name);
  try{ localStorage.setItem('transect_tab',name); }catch(e){}
  setTimeout(()=>map.resize(),60);
}
/* Where to land. The steps are numbered 1→4 for a reason: on a first visit you have
   not defined a box yet, so dropping you on someone else's Overview is confusing.
   Land on Setup the first time, then remember where you were, and honour ?tab= . */
function startTab(){
  const q=new URLSearchParams(location.search).get('tab');
  if(q && TAB_SHOW[q] && !(RESULT_TABS.includes(q) && !hasResult())) return q;
  try{
    const last=localStorage.getItem('transect_tab');
    if(last && TAB_SHOW[last] && !(RESULT_TABS.includes(last) && !hasResult())) return last;
    if(!localStorage.getItem('transect_seen')){ localStorage.setItem('transect_seen','1'); return 'setup'; }
  }catch(e){}
  try{
    if(DOC && DOC.blank) return 'setup';   // nothing to look at on Overview yet
  }catch(e){}
  return 'overview';
}
const RESULT_TABS=['overview','field','brief'];
function hasResult(){ return !!(DOC && !DOC.blank && (DOC.areas||[]).length); }
/* Overview / Field / Brief describe an analysis. With nothing computed they'd show
   empty scaffolding, which reads as broken — so they stay locked until a run lands. */
function paintTabLocks(){
  const locked=!hasResult();
  document.querySelectorAll('#tabbar button[data-tab]').forEach(b=>{
    const isResult=RESULT_TABS.includes(b.dataset.tab);
    const off=isResult&&locked;
    b.classList.toggle('locked',off);
    b.disabled=off;
    b.title=off?'Run an analysis first — there is nothing to show yet':'';
  });
}
function wireTabs(){
  document.querySelectorAll('#tabbar button[data-tab]').forEach(b=>b.onclick=()=>{
    if(RESULT_TABS.includes(b.dataset.tab) && !hasResult()){
      setTab('setup');
      const box=document.getElementById('setupErr');
      if(box){ box.className='callout'; box.dataset.kind='info';
        box.innerHTML='<span class="mark">i</span><div class="body"><b>Nothing to show yet</b>'
          +'Overview, Field and Brief all describe a computed analysis. Set your area and dates, '
          +'then run it — they unlock as soon as it finishes.</div>'; }
      return;
    }
    setTab(b.dataset.tab);
  });
  paintTabLocks();
}
/* plan identity in the top bar: auto-named, renamable inline, with a saved state */
let PLAN_NAME='', PLAN_SAVED=false;
/* Is an analysis in flight? The Overview panel needs to tell "no plan yet" apart from
   "your plan is recomputing right now" — they look identical on a blanked DOC. */
let RUN_ACTIVE=false; lockSetupWhileRunning();
/* mark exactly one button in a .seg as pressed (the control means "one of these") */
function segPick(id){
  const b=document.getElementById(id); if(!b) return;
  const seg=b.closest('.seg'); if(!seg){ b.setAttribute('aria-pressed','true'); return; }
  seg.querySelectorAll('button').forEach(x=>x.removeAttribute('aria-pressed'));
  b.setAttribute('aria-pressed','true');
}
/* Species as a word a hunter reads, not the contract's identifier. Written as an
   explicit map rather than a computed key so the keys are real literals the gate can
   see — a computed key looks like an orphan to the checker and like English through t()
   to the shape gate. Three species is a small fixed set; when it stops being small,
   generate it the way applyLegend does and teach the checker about it. */
const SPECIES_NAME={
  moose:          ()=>t('sp.moose'),
  whitetail_deer: ()=>t('sp.whitetail_deer'),
  black_bear:     ()=>t('sp.black_bear'),
};
function speciesName(sp){
  const k=String(sp||'').trim();
  return SPECIES_NAME[k] ? SPECIES_NAME[k]() : k;
}
function planTitle(){
  // A real AOI title is a PLACE NAME written by the engine — never translate that.
  // The blank-state stub is ours, and it was the last English in the top bar with FR
  // selected.
  const raw=(DOC.meta.title||'').trim();
  const ttl=DOC.blank ? t('plan.noarea') : raw;
  const sp=speciesName(DOC.meta.species);
  return (sp && !ttl.toLowerCase().includes(sp.toLowerCase())) ? `${ttl} — ${sp}` : ttl;
}
function setPlanName(n,saved){
  PLAN_NAME=n; if(saved!=null) PLAN_SAVED=saved;
  const el=document.getElementById('planName'), d=document.getElementById('saveDot');
  if(el){ el.textContent=PLAN_NAME; el.title='Click to rename'; el.style.cursor='text';
    // rename in place — a native prompt() for a one-word edit was the loudest possible
    // way to ask the smallest possible question
    el.onclick=()=>{
      if(el.querySelector('input')) return;
      const old=PLAN_NAME;
      el.innerHTML='<input class="planedit" maxlength="90">';
      const i=el.querySelector('input'); i.value=old; i.focus(); i.select();
      let done=false;
      const fin=commit=>{ if(done) return; done=true;
        const v=(i.value||'').trim();
        setPlanName(commit&&v?v:old, commit&&v&&v!==old ? false : PLAN_SAVED); };
      i.onkeydown=e=>{ e.stopPropagation();
        if(e.key==='Enter'){e.preventDefault();fin(true);} if(e.key==='Escape'){e.preventDefault();fin(false);} };
      i.onblur=()=>fin(true);
    }; }
  if(d){ d.dataset.s=PLAN_SAVED?'saved':'unsaved'; d.textContent=PLAN_SAVED?'SAVED':'UNSAVED';
    // UNSAVED is now a button, not just a verdict: click it and the plan is saved,
    // analysis or not.
    d.style.cursor=PLAN_SAVED?'default':'pointer';
    d.title=PLAN_SAVED?'This plan is saved':'Click to save this plan now';
    d.onclick=PLAN_SAVED?null:()=>{ d.textContent='SAVING…'; savePlanNow(true)
      .then(()=>{ if(!PLAN_SAVED) setPlanName(PLAN_NAME,false); }); }; }
}

/* ---------------- saved hunt plans (UUID + local storage) ----------------
   A plan captures your Setup, chosen area, and map drawings — saved under a UUID
   in this browser. (Cross-device accounts come with the durable server.) */
function uuid(){ return (crypto&&crypto.randomUUID)?crypto.randomUUID():'p-'+Date.now()+'-'+Math.random().toString(16).slice(2); }
/* PLAN SUMMARY (#74). The dashboard used to ask the plan itself whether it had areas —
   but the analysis lives at plan.doc, and signed-out plans have no doc at all, so every
   card read NOT RUN whether or not it had ever been computed. A run now stamps a small
   summary onto the plan: it is a couple of KB, so it survives localStorage, and it is
   the honest record of "this was analysed" separate from "the result is cached here".
   The thumbnail is SVG path data in a unit box — no tiles, no map, no network. */
function _thumbPaths(rings, box, maxRings, maxPts){
  const W=100, H=62, out=[];
  const dx=(box.e-box.w)||1, dy=(box.n-box.s)||1;
  for(const r of (rings||[]).slice(0,maxRings)){
    if(!r || r.length<3) continue;
    const step=Math.max(1,Math.ceil(r.length/maxPts));
    let d='';
    for(let i=0;i<r.length;i+=step){
      const x=((r[i][0]-box.w)/dx)*W, y=((box.n-r[i][1])/dy)*H;
      if(!isFinite(x)||!isFinite(y)) continue;
      d+=(d?'L':'M')+x.toFixed(1)+' '+y.toFixed(1);
    }
    if(d) out.push(d+'Z');
  }
  return out;
}
function planSummary(doc){
  if(!doc || doc.blank) return null;
  const areas=doc.areas||[], box=doc.box;
  const s={ranAt:doc._ranAt||Date.now(), areas:areas.length,
    species:(doc.meta&&doc.meta.species)||'', zone:(doc.legal&&doc.legal.zone)||'',
    title:(doc.meta&&doc.meta.title)||'', rev:(doc.meta&&doc.meta.engine_revision)||null,
    excluded:areas.filter(a=>a.status==='excluded').length,
    waypoints:(doc.waypoints||[]).length};
  if(box && areas.length){
    const ring=a=>{ const g=a.geometry||{};
      return g.type==='Polygon'?g.coordinates[0]
           : g.type==='MultiPolygon'?(g.coordinates[0]||[])[0] : null; };
    // budgeted deliberately: a 118px-tall card needs no more detail than this, and the
    // whole summary has to fit in localStorage alongside every other plan (~5 KB worst case).
    s.thumb={
      ok:_thumbPaths(areas.filter(a=>a.status!=='excluded').map(ring).filter(Boolean), box, 6, 32),
      ex:_thumbPaths(areas.filter(a=>a.status==='excluded').map(ring).filter(Boolean), box, 4, 24),
      water:_thumbPaths(((doc.hydro&&doc.hydro.lakes)||[]), box, 20, 14)
    };
    // REAL COORDINATES, not just the card thumbnail (T9.5). The thumb paths are
    // normalised to THIS plan's own box, which makes them useless for drawing several
    // plans together — every plan would land on top of every other. Keeping a budgeted
    // ring in lon/lat is what lets the dashboard put them all on one map.
    const geo=(rings,maxR,maxP)=>{ const out=[];
      for(const r of rings.slice(0,maxR)){
        if(!r||r.length<3) continue;
        const st=Math.max(1,Math.ceil(r.length/maxP)), q=[];
        for(let i=0;i<r.length;i+=st) q.push([+r[i][0].toFixed(4),+r[i][1].toFixed(4)]);
        if(q.length>=3) out.push(q); }
      return out; };
    s.box=box;
    s.geo={ ok:geo(areas.filter(a=>a.status!=='excluded').map(ring).filter(Boolean),6,20),
            ex:geo(areas.filter(a=>a.status==='excluded').map(ring).filter(Boolean),4,14) };
  }
  return s;
}
function loadPlans(){ try{return JSON.parse(localStorage.getItem('transect_plans')||'[]');}catch(e){return [];} }
function savePlans(a){ try{localStorage.setItem('transect_plans',JSON.stringify(a));}
  catch(e){ tellModal(t('dlg.storageTitle'),
    t('dlg.storageBody'),'warn'); } }
/* The plan currently on screen, if it came from (or was saved to) the store. Keeps
   a re-run updating that plan instead of spawning a duplicate every time. */
let PLAN_OWNER=null;     // email of the plan's owner, for drawing backfill
let PLAN_VERSION=null;   // the plan version this client loaded (T9.6 co-edit)
let CUR_PLAN_ID=null;
let LAST_JOB_ID=null;   // the AOI whose rasters the server retains for /rescope
function markDirtySoft(){ try{ setPlanName(PLAN_NAME,false); }catch(e){} }

/* Re-plan inside hand-drawn focus areas WITHOUT a full re-run: the server reuses the
   already-acquired rasters and only re-places sites/routes. Seconds, not minutes. */
async function rescopeWithDrawnAreas(){
  const polys=(drawSaved||[]).filter(f=>f.geometry&&f.geometry.type==='Polygon')
    .map(f=>f.geometry.coordinates[0]);
  if(!polys.length){ tellModal('Nothing to recalculate in',
    `Recalculate re-plans your analysis <b>inside areas you draw</b>. Draw one or more with
     the area tool (▱), then press it again — it reuses the rasters already on the engine,
     so it takes seconds rather than minutes.`); return; }
  if(!LAST_JOB_ID){ tellModal('Run an analysis first',
    `Recalculate re-plans an existing analysis inside your drawn areas — there is nothing to
     re-plan yet.`); return; }
  const btn=document.getElementById('rescopeBtn'); if(btn){ btn.disabled=true; btn.textContent='Recalculating…'; }
  try{
    const r=await fetch(API_URL+'/rescope',{method:'POST',
      headers:Object.assign({'Content-Type':'application/json','X-API-Key':API_KEY},
        authTok()?{'Authorization':'Bearer '+authTok()}:{}),
      body:JSON.stringify({job_id:LAST_JOB_ID, manual_areas:polys})});
    if(!r.ok){ const d=await r.json().catch(()=>({})); throw new Error(d.detail||('rescope '+r.status)); }
    const d=await r.json();
    // the drawn polygons are now the focus areas — clear them as annotations so they
    // don't double up with the rendered focus-area outlines.
    drawSaved=(drawSaved||[]).filter(f=>!(f.geometry&&f.geometry.type==='Polygon')); renderAnnot();
    applyDoc(d.scout); layersDismissed=false; setTab('overview'); syncDocks('overview'); autosavePlan();
  }catch(e){
    const gone=/no longer cached/.test(e.message);
    if(gone) askModal({kind:'warn', title:'The engine no longer holds this analysis',
      body:`Recalculate reuses rasters the engine keeps for a while after a run, and this
        one has aged out. A full run rebuilds them — your drawn areas stay put and the new
        analysis will use them.`,
      actions:[{id:'no',label:'Not now'},{id:'run',label:'Run a full analysis',primary:true}]
    }).then(a=>{ if(a==='run') runAnalysis(); });
    else tellModal('Could not recalculate', escHtml(e.message), 'danger');
  }finally{ const b=document.getElementById('rescopeBtn'); if(b){ b.disabled=false; b.textContent='↻ Recalculate in my areas'; } }
}
function currentPlan(name, withDoc){
  const p={id:uuid(), name:name||PLAN_NAME||('Plan '+new Date().toLocaleDateString()), savedAt:Date.now(),
    aoi:(DOC.meta&&DOC.meta.title)||'', units:UNITS,
    setup:{center:draft.center?draft.center.slice():null,radius:draft.radius,walkAccess:draft.walkAccess,walkHunt:draft.walkHunt,party:draft.party,
      leaving:draft.leaving,watercraft:SETUP.watercraft,huntStyle:SETUP.huntStyle,dates:draft.dates.slice(),
      fixedCampMode:draft.fixedCampMode,huntRadius:draft.huntRadius},
    area:lastSel, annot:JSON.parse(JSON.stringify(drawSaved||[]))};
  // The computed analysis is the expensive part (3–5 min). Store it with the plan so
  // reopening is instant — but only server-side, where there's room for it.
  if(withDoc && DOC && !DOC.blank) p.doc = DOC;
  p.cached = !!p.doc;
  // …and the small summary rides along either way, so the dashboard can tell a plan
  // that was analysed from one that never has, and can draw a preview of it.
  p.sum = planSummary(DOC);
  return p;
}
/* AUTOSAVE ON COMPLETION.
   A run costs 3–5 minutes of engine time, and nothing saved it. The result was
   applied to the map and held only in memory: reload, or open "My hunt plans", and
   it was gone — which is exactly what it looks like when the feature is broken.
   Saving is not a decision worth asking someone to make after waiting five minutes.

   Signed in, the whole computed analysis goes with it so reopening is instant and
   costs no engine time. Signed out, we keep the setup locally (there is no room in
   localStorage for a full contract) and say so. */
async function autosavePlan(){ return savePlanNow(false); }
/* force=true saves whatever is on screen — including a Setup you have not run yet.
   A plan that only exists once it has cost five minutes of engine time is a plan you
   lose every time you close the tab mid-setup. */
async function savePlanNow(force){
  try{
    if(!force && (!DOC || DOC.blank || !(DOC.areas||[]).length)) return;
    if(force && !draft.center) return;
    const authed=isAuthed();
    const p=currentPlan(PLAN_NAME||'', authed);
    if(CUR_PLAN_ID) p.id=CUR_PLAN_ID;          // re-running replaces, never piles up
    if(authed){
      // CO-EDIT (T9.6). Send the version this client started from so the server can
      // refuse a save that would flatten a co-editor's work rather than silently
      // winning. A 409 is not an error to swallow — it means somebody else saved.
      const r=await apiF('/plans',{method:'PUT',body:JSON.stringify(
        {id:p.id,name:p.name,data:p,base_version:(PLAN_VERSION!=null?PLAN_VERSION:null)})});
      if(r && r.status===409){
        const who=(await r.json().catch(()=>({})))||{};
        askModal({kind:'warn', title:t('dlg.conflictTitle','Somebody else saved this plan'),
          body:t('dlg.conflictBody','This plan is shared, and another editor saved changes after you opened it. Saving now would replace their work. Reload to pick up their version — anything you drew since is still on screen until you do.'),
          actions:[{id:'stay',label:t('dlg.conflictStay','Keep mine on screen')},
                   {id:'reload',label:t('dlg.conflictReload','Reload theirs'),primary:true}]
        }).then(a=>{ if(a==='reload') location.reload(); });
        return;
      }
      if(r && r.ok){ try{ const j=await r.json(); if(j&&j.version!=null) PLAN_VERSION=j.version; }catch(e){} }
    }else{
      const arr=loadPlans().filter(x=>x.id!==p.id); arr.unshift(p); savePlans(arr);
    }
    CUR_PLAN_ID=p.id;
    setPlanName(p.name,true);                   // the dot says SAVED, and means it
  }catch(e){
    // never let a save failure eat the analysis the user just waited for
    console.error('autosave failed',e);
    setPlanName(PLAN_NAME,false);
  }
}
function applyPlan(p){
  if(!p) return;
  CUR_PLAN_ID=p.id||null;
  setTimeout(()=>{ if(!DOC._revisionDismissed) checkEngineRevision(); },800);
  const s=p.setup||{};
  draft.center=(s.center||draft.center||null); if(draft.center) draft.center=draft.center.slice();
  draft.radius=s.radius||draft.radius;
  draft.walkAccess=s.walkAccess??draft.walkAccess; draft.walkHunt=s.walkHunt??draft.walkHunt;
  draft.party=s.party??draft.party;
  draft.fixedCampMode=s.fixedCampMode??draft.fixedCampMode; draft.huntRadius=s.huntRadius??draft.huntRadius;
  draft.leaving=s.leaving||draft.leaving;
  if(s.dates&&s.dates.length===2) draft.dates=s.dates.slice();
  SETUP.watercraft=s.watercraft||SETUP.watercraft; SETUP.huntStyle=s.huntStyle||SETUP.huntStyle;
  // A plan saved before the 3-way hunt-style control can hold a contradictory pair —
  // fixedCampMode with huntStyle 'vehicle'. hstyleOf() would read 'camp' while every
  // other reader of SETUP.huntStyle read 'vehicle'. Collapse it on the way in, once,
  // rather than teaching each reader to distrust the field.
  if(draft.fixedCampMode) SETUP.huntStyle='spike';
  UNITS=p.units||UNITS;
  drawSaved=JSON.parse(JSON.stringify(p.annot||[]));
  // Older plans stored drawings without id/dtype/style — backfill so the editor + legend
  // work on them — and bump the id counter past what we restored so new drawings don't clash.
  drawSaved.forEach(f=>{ const q=f.properties=f.properties||{};
    if(q.id==null) q.id=_drawId++;
    // Drawings made before authorship existed belong to whoever owned the plan — the
    // only honest attribution available. Marked so the panel can say "assumed".
    if(q.by==null){ q.by=(PLAN_OWNER||null); q.byAssumed=true; }
    if(!q.dtype) q.dtype=f.geometry.type==='Polygon'?'area':f.geometry.type==='LineString'?'line':'pin';
    const s=DRAW_STYLE[q.dtype]||DRAW_STYLE.area;
    if(q.stroke==null)q.stroke=s.stroke; if(q.fill==null)q.fill=s.fill;
    if(q.fo==null)q.fo=s.fo; if(q.lo==null)q.lo=s.lo; if(q.lw==null)q.lw=2.6; if(!q.style)q.style='solid'; });
  _drawId=Math.max(_drawId,...drawSaved.map(f=>(f.properties&&f.properties.id||0)+1),1);
  if(map.getSource('annot')) renderAnnot();
  lastSel=p.area||1;
  renderSetup();
  if(p.doc){                                   // cached analysis → no recompute needed
    // keep the ORIGINAL run time — re-saving a reopened plan must not pretend it
    // was just analysed.
    p.doc._ranAt = (p.sum && p.sum.ranAt) || p.savedAt || Date.now();
    applyDoc(p.doc);
    setPlanName(p.name||planTitle(), true);
    setTab('overview');
  } else {
    // NO CACHED ANALYSIS. The Setup is already restored and on screen behind this —
    // so the dialog is an offer to run it, not a notice that something is missing.
    map.flyTo({center:draft.center,zoom:9.5}); drawDraft();
    setPlanName(p.name||planTitle(), true);
    setTab('setup');
    const est=estimateMinutes(draft.radius,draft.resM);
    askModal({title:tf('dlg.readyTitle',{name:escHtml(p.name||'This plan')}),
      body:`${t('dlg.readyBody')}
        <ul><li><b>${t('dlg.readyRun')}</b> — ~${est.lo}–${est.hi} min · ${Math.round(draft.radius)} km</li>
        <li><b>${t('dlg.readySetup')}</b></li></ul>
        <span class="note">${isAuthed()?t('dlg.readyCached'):t('dlg.readyLocal')}</span>`,
      actions:[{id:'setup',label:t('dlg.readySetup')},{id:'run',label:t('dlg.readyRun'),primary:true}]
    }).then(a=>{ if(a==='run') runAnalysis(); });
  }
}
/* accounts — token in localStorage; plans sync to the server when signed in */
// accept either key: the sign-in page writes 'transect_tok', older builds wrote
// 'transect_token'. Reading both means an existing session keeps working.
const authTok=()=>{try{return localStorage.getItem('transect_tok')||localStorage.getItem('transect_token')||'';}catch(e){return '';}};
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
  localStorage.setItem('transect_tok',d.token); localStorage.setItem('transect_token',d.token);
  localStorage.setItem('transect_email',d.email); localStorage.setItem('transect_seen','1'); return d;
}
function signOut(){ apiF('/auth/logout',{method:'POST'}).catch(()=>{});
  ['transect_token','transect_tok','transect_email'].forEach(k=>{try{localStorage.removeItem(k);}catch(e){}});
  if(window._acctPaint) window._acctPaint(); }
async function openPlanById(id){
  if(!id) return false;
  try{
    let src=[];
    if(isAuthed()){ const r=await apiF('/plans'); if(r.ok){ const d=await r.json();
      src=(d.plans||[]).map(p=>Object.assign({},p.data,{id:p.id,name:p.name,savedAt:(p.updated||0)*1000})); } }
    if(!src.length) src=loadPlans();
    const p=src.find(x=>String(x.id)===String(id));
    if(p){ applyPlan(p); return true; }
  }catch(e){}
  return false;
}
function initLang(){
  const seg=document.getElementById('langSeg'); if(!seg||!window.I18N) return;
  const paint=()=>seg.querySelectorAll('button').forEach(b=>{
    if(b.dataset.lang===I18N.lang) b.setAttribute('aria-pressed','true'); else b.removeAttribute('aria-pressed');});
  paint();
  seg.querySelectorAll('button').forEach(b=>b.onclick=()=>{ I18N.set(b.dataset.lang); paint(); });
  // Switching language re-renders every panel rather than reloading, so you keep your
  // place, your analysis and your map position.
  I18N.onChange(()=>{
    try{ I18N.apply(document);
      buildPanel(); buildWeather(); renderSetup(); renderBrief();
      buildLayersDock(); paintTabLocks();
      if(window._acctPaint) window._acctPaint();
      const d=document.getElementById('layersDock');
      if(d && !d.classList.contains('hidden')) openDock('layersDock','railLayers');
    }catch(e){}
  });
}
function initAccount(){
  const btn=document.getElementById('acctBtn'), menu=document.getElementById('acctMenu');
  if(!btn||!menu) return;
  const paint=()=>{
    const on=isAuthed();
    btn.textContent = on ? (authEmail()||'Account').split('@')[0] : 'Sign in';
    menu.innerHTML = on
      ? `<div class="s" style="margin-bottom:8px">Signed in as<br><b>${authEmail()}</b></div>
         <a class="btn btn--secondary btn--block btn--sm" href="plans" style="margin-bottom:6px">Your hunt plans</a>
         <button class="btn btn--danger btn--block btn--sm" id="acctOut">Sign out</button>`
      : `<div class="s" style="margin-bottom:8px">You're not signed in. Plans stay in this browser and
           you can't run an analysis.</div>
         <a class="btn btn--primary btn--block btn--sm" href="signin">Sign in</a>`;
    const o=document.getElementById('acctOut');
    if(o) o.onclick=()=>{ signOut(); menu.classList.add('hidden'); paint(); };
  };
  paint();
  btn.onclick=e=>{ e.stopPropagation(); paint(); menu.classList.toggle('hidden'); };
  document.addEventListener('click',e=>{ if(!menu.contains(e.target)&&e.target!==btn) menu.classList.add('hidden'); });
  window._acctPaint=paint;
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
  // A bridged crossing is not a waypoint worth carrying into the field; the other
  // two are, and each says how confident the call is.
  (DOC.crossings||[]).filter(c=>c.kind!=='bridge').forEach(c=>w.push({lon:c.ll[0],lat:c.ll[1],
    name:(c.kind==='ford'?'Ford':'Water crossing'),
    desc:(c.kind==='ford'?'fordable on foot':'assume you need a boat')
         +(c.basis==='inferred'?' (inferred — verify on the ground)':'')}));
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
/* ===========================================================================
   BRIEF PDF (T9.7) — the written brief plus one map plate per theme.

   WHY AN OFFSCREEN MAP AND NOT THE ONE ON SCREEN. getCanvas().toDataURL() returns a
   BLANK image unless the map was created with preserveDrawingBuffer, and turning that
   on permanently taxes every frame for every user to serve an export used occasionally.
   A second map, created only while exporting, costs nothing the rest of the time — and
   it can be sized for print and framed on the AOI rather than on wherever the hunter
   happens to be looking.

   WHY PRINT-TO-PDF AND NOT A PDF LIBRARY. The browser already has an excellent one, the
   text stays selectable and searchable, and it avoids vendoring another megabyte into a
   bundle that has to work offline. The page is written into a hidden iframe so no popup
   blocker can eat it.

   This is the artifact that goes in a pack where there is no cell service, so every
   plate carries a scale bar, a north arrow and the datum. A map you cannot navigate
   from is a picture.
   =========================================================================== */
const PLATES=[
  {key:'overview', name:'Overview', rows:['huntZones','camps2','staging','routes','access'],
   sites:true,
   note:'Ranked focus areas with the huntability bands beneath them, your camp or staging '+
        'point, and the approach lines between them. Bands are model output with no surveyed '+
        'edge — treat the boundary as a gradient, not a fence.'},
  {key:'browse', name:'Browse & feeding', rows:['browse','cuts','burns'],
   note:'Where the food is. Browse is a composite: dated logging cuts and burns are surveyed '+
        'polygons with a year on them, the rest is a satellite classification. The cut layer '+
        'is drawn over it so you can see which of the green is actually backed by a dated cut.'},
  {key:'refuge', name:'Thermal refuge & water', rows:['refuge','water','wetland','beaver'],
   note:'Cool, closed cover for the middle of a warm day, plus the hydrography that shapes '+
        'both travel and the funnels. Wetland is passable to a moose — it slows a hunter far '+
        'more than it slows them.'},
  {key:'travel', name:'Funnels & access', rows:['funnel','roads','trails','crossings'],
   note:'Pinch points where travelling animals are forced together, and how you get in. '+
        'Every funnel here has a measured neck width; road class is the road\'s ROLE, and '+
        'the surface is stated separately in the app.'},
  {key:'sites', name:'Stands', rows:['st-rut','st-saline','st-glass','refuge','routes'],
   sites:true,
   note:'Where to sit and how to come in. Every one is a hypothesis to ground-truth on '+
        'foot — the model reads habitat, not animals.'},
];

async function _plateMap(){
  const host=document.createElement('div');
  host.style.cssText='position:fixed;left:-10000px;top:0;width:1400px;height:900px';
  document.body.appendChild(host);
  // THE LIVE STYLE, NOT A BARE BASEMAP (T10.6). This built the plate map from
  // `baseStyle()` — imagery and nothing else — and then called setLayoutProperty on
  // layer ids that did not exist on it. Every one of those calls was guarded by
  // `if(m.getLayer(id))`, so every one silently did nothing, and all five plates came
  // out as pictures of the ground with no plan on them. Reported: "None of the analysis
  // / polygons / waypoints / etc. render on the PDF."
  //
  // map.getStyle() serialises the sources WITH their GeoJSON data, so the offscreen map
  // gets the same features. Images are NOT part of a style, which is why they are
  // re-registered below — a symbol layer whose icon is missing also draws nothing.
  const m=new maplibregl.Map({container:host,style:map.getStyle(),
    center:map.getCenter(),zoom:map.getZoom(),
    preserveDrawingBuffer:true,   // the whole reason this second map exists
    attributionControl:false,interactive:false});
  await new Promise(r=>m.on('load',r));
  try{ addIcons(m); registerPatterns(m); }catch(e){ console.warn('plate icons',e); }
  // A plate is a PLAN VIEW OF THE PLAN. Flat, because a pitched hillshade is a picture
  // rather than something you navigate from; and framed on the areas rather than on
  // wherever the hunter happened to be looking when they pressed export — a plate that
  // misses the focus areas is as useless as a blank one.
  try{ m.setTerrain(null); }catch(e){}
  try{
    if(!DOC.blank && (DOC.areas||[]).length)
      m.fitBounds(bbox(DOC.areas),{padding:70,duration:0});
    else if(DOC.box)
      m.fitBounds([[DOC.box.w,DOC.box.s],[DOC.box.e,DOC.box.n]],{padding:70,duration:0});
  }catch(e){ console.warn('plate framing',e); }
  return {m,host};
}

async function _plateShot(m,rows){
  // Only the rows this plate is about. Everything else is hidden so a plate makes ONE
  // point — a plate showing all 25 layers is the screenshot the hunter already has.
  // Match on the row key OR its layer group: the huntability bands are three rows
  // (hz-high/medium/low) that all share the `huntZones` layer, so a plate naming the
  // group would otherwise show no bands at all — a silently empty plate, which is the
  // failure this whole codebase keeps producing when a name is matched in one namespace
  // and defined in another.
  const shown=[];
  LAYERS.forEach(r=>{
    const on = rows.includes(r.k) || rows.includes(r.lyr);
    (LYR_MAP[r.lyr||r.k]||[]).forEach(id=>{
      if(!m.getLayer(id)) return;
      m.setLayoutProperty(id,'visibility', on?'visible':'none');
      if(on) shown.push(id);
    });
  });
  // A PLATE WITH NOTHING ON IT MUST BE LOUD. T9.7 shipped on the strength of the plates
  // existing; nobody checked what was on them, and all five were basemap for weeks —
  // because `if(m.getLayer(id))` above turned every missing layer into a silent skip.
  // Saying so beats printing a picture of the ground and calling it a brief.
  if(!shown.length) console.warn('[pdf] plate has no plan layers on it:', rows);
  await new Promise(r=>{ const done=()=>{m.off('idle',done);r();}; m.on('idle',done);
                         setTimeout(done,2500); });   // never hang the export on a slow tile
  return m.getCanvas().toDataURL('image/png');
}

function _briefPlainText(){
  /* The written brief, taken from the DOM the hunter has already read, so the PDF can
     never disagree with the screen. */
  const el=document.getElementById('brief');
  return el?el.innerHTML:'';
}

async function exportBriefPDF(btn){
  const label=btn?btn.textContent:null;
  if(btn){ btn.disabled=true; btn.textContent='Rendering plates…'; }
  let ctxm=null;
  try{
    ctxm=await _plateMap();
    if(!DOC.blank && (DOC.areas||[]).length)
      ctxm.m.fitBounds(bbox(DOC.areas),{padding:60,duration:0});
    else if(DOC.box)
      ctxm.m.fitBounds([[DOC.box.w,DOC.box.s],[DOC.box.e,DOC.box.n]],{padding:60,duration:0});
    const shots=[];
    for(const pl of PLATES){
      if(btn) btn.textContent=`Rendering ${pl.name}…`;
      shots.push({...pl,img:await _plateShot(ctxm.m,pl.rows)});
    }
    const m=DOC.meta||{}, g=DOC.legal||{};
    const scale=`Datum WGS 84 · centre ${(m.center||{}).lat?.toFixed?.(4)}, ${(m.center||{}).lon?.toFixed?.(4)} · box ${m.radius_km} km`;
    const doc=`<!doctype html><meta charset="utf-8">
      <title>Transect — ${escHtml(m.title||m.aoi||'hunt brief')}</title>
      <style>
        @page{size:A4;margin:14mm}
        body{font:11pt/1.5 -apple-system,system-ui,sans-serif;color:#111}
        h1{font-size:19pt;margin:0 0 2mm} h2{font-size:13pt;margin:8mm 0 2mm}
        .meta{font:9pt/1.4 ui-monospace,monospace;color:#555;margin-bottom:6mm}
        .plate{page-break-inside:avoid;margin:0 0 8mm}
        .plate img{width:100%;border:1px solid #bbb}
        .cap{font:9.5pt/1.45 sans-serif;color:#333;margin-top:2mm}
        .foot{font:8.5pt/1.4 ui-monospace,monospace;color:#666;margin-top:1mm}
        .warn{border:1px solid #b00;background:#fff5f5;padding:3mm;margin:4mm 0;font-size:10pt}
        .brief :is(button,input,.seg,.briefpick){display:none!important}
        .brief{font-size:10.5pt}
        .north{float:right;font:9pt/1 sans-serif;color:#333}
      </style>
      <h1>${escHtml(m.title||m.aoi||'Hunt brief')}</h1>
      <div class="meta">${escHtml(scale)}<br>
        Zone ${escHtml(String(g.zone||'?'))} · ${escHtml((g.huntable_tenures||['—'])[0])} ·
        ${g.diy_possible?'DIY':'restricted'} · engine rev ${escHtml(String(DOC.engine_revision||'?'))} ·
        ${escHtml(headerDates())}</div>
      <div class="warn"><b>À valider sur le terrain.</b> Every mark in this document is a
        modelled hypothesis to ground-truth on foot — the model reads habitat, not animals.
        Hunting regulations, zone boundaries and access change: verify before you go.</div>
      ${shots.map(s=>`<div class="plate">
        <h2>${escHtml(s.name)}<span class="north">N ↑</span></h2>
        <img src="${s.img}">
        <div class="cap">${escHtml(s.note)}</div>
        <div class="foot">${escHtml(scale)}</div>
      </div>`).join('')}
      <h2 style="page-break-before:always">The written brief</h2>
      <div class="brief">${_briefPlainText()}</div>`;
    const fr=document.createElement('iframe');
    fr.style.cssText='position:fixed;right:0;bottom:0;width:0;height:0;border:0';
    document.body.appendChild(fr);
    fr.contentDocument.open(); fr.contentDocument.write(doc); fr.contentDocument.close();
    // Give the images a moment to decode, or the print dialog captures empty boxes.
    await new Promise(r=>setTimeout(r,600));
    fr.contentWindow.focus(); fr.contentWindow.print();
    setTimeout(()=>fr.remove(),60000);
  }catch(err){
    console.error('brief PDF failed',err);
    tellModal(t('dlg.pdfTitle','Could not build the PDF'),
      escHtml(String((err&&err.message)||err))+
      `<br><br>${escHtml(t('dlg.pdfBody','Nothing was lost — this only affects the export. The map and the brief on screen are unchanged.'))}`,
      'danger');
  }finally{
    if(ctxm){ try{ctxm.m.remove();}catch(e){} ctxm.host.remove(); }
    if(btn){ btn.disabled=false; btn.textContent=label; }
  }
}

function initExport(){
  const btn=document.getElementById('exportBtn'), menu=document.getElementById('exportMenu'); if(!btn) return;
  btn.onclick=()=>menu.classList.toggle('hidden');
  const slug=((DOC.meta||{}).aoi||'transect').replace(/[^a-z0-9]+/gi,'_');
  menu.querySelectorAll('button[data-fmt]').forEach(b=>b.onclick=()=>{
    const wz=document.getElementById('exZones').checked;
    if(b.dataset.fmt==='pdf'){ menu.classList.add('hidden'); exportBriefPDF(b); return; }
    if(b.dataset.fmt==='gpx') _download(slug+'.gpx',buildGPX(wz),'application/gpx+xml');
    else _download(slug+'.kml',buildKML(wz),'application/vnd.google-earth.kml+xml');
    menu.classList.add('hidden');
  });
  document.addEventListener('click',e=>{ if(!menu.contains(e.target)&&e.target!==btn) menu.classList.add('hidden'); });
}

/* ---------------------------------------------------------------------------
   §4 — VIEW RAIL SURFACES: model surface card, area statistics, tool readouts.
--------------------------------------------------------------------------- */
function fitAOI(){
  if(!DOC.blank && (DOC.areas||[]).length)
    map.fitBounds(bbox(DOC.areas),{padding:{top:80,left:400,right:200,bottom:120},duration:600});
  else if(DOC.box) map.fitBounds([[DOC.box.w,DOC.box.s],[DOC.box.e,DOC.box.n]],{padding:70,duration:600});
}

/* --- Model surface card -----------------------------------------------------
   The value ramp legend lives IN this card, not floating on the map, because it
   is only meaningful while the surface is on. And the card has to say out loud
   that holes are EXCLUDED, not low-scoring: a hole is an admission of
   ignorance, and excluded ground must never look like low-scoring ground. */
let surfMode='banded', surfMin=0, surfOpacity=0.55;
const RAMP=[['#FFD400','Low','.30'],['#FF8C00','Medium','.55'],['#E2231A','High','.75']];
// The Model-surface opacity controls the HUNTABILITY bands ONLY (huntZones). It must
// not touch refuge/browse/burns/funnel — those are separate layers with their own rows.
// Slider 10–100% maps to a light-wash range so the imagery beneath (the layer that
// reveals unmapped roads/cutblocks) is never fully buried.
function surfFillOpacity(){ return +(0.55*surfOpacity).toFixed(3); }
function applySurfaceOpacity(){
  if(map.getLayer('huntZones'))
    try{ map.setPaintProperty('huntZones','fill-opacity',surfFillOpacity()); }catch(e){}
}
function buildSurfDock(){
  const d=document.getElementById('surfDock');
  const on=LAYERS.filter(r=>r.hz).some(r=>r.on);
  d.innerHTML=`<div class="dhead"><h4>${t('surf.title','Model surface')}</h4>
      <button class="dclose" title="Close">✕</button></div>
    <div class="dbody">
      <label class="drow drow--sw"><span>${t('surf.show','Show huntability')}</span>
        <input type="checkbox" id="surfOn" ${on?'checked':''}></label>
      <div class="grouplabel">${t('surf.ramp','VALUE RAMP')}</div>
      <div class="ramp">${RAMP.map(([hex,lab,v])=>
        `<div class="ramprow"><i style="background:${hex}"></i><span>${lab}</span><b>${v}</b></div>`).join('')}</div>
      <div class="seg" id="surfSeg">
        <button data-m="banded" class="${surfMode==='banded'?'on':''}">${t('surf.banded','Banded')}</button>
        <button data-m="cont" class="${surfMode==='cont'?'on':''}">${t('surf.cont','Continuous')}</button>
      </div>
      <label class="drow"><span>${t('surf.hide','Hide below')}</span>
        <input type="range" id="surfMin" min="0" max="90" value="${surfMin}">
        <b id="surfMinV">${surfMin?('.'+String(surfMin).padStart(2,'0')):t('surf.none','none')}</b></label>
      <label class="drow"><span>${t('surf.op','Opacity')}</span>
        <input type="range" id="surfOp" min="10" max="100" value="${Math.round(surfOpacity*100)}">
        <b>${Math.round(surfOpacity*100)}%</b></label>
      <p class="dnote">${t('surf.holes',
        'Holes in the surface are <b>excluded</b> ground — deep water, road corridors, outfitter tenure — not low scores. Excluded is not the same as bad, and the model refuses to guess there.')}</p>
    </div>`;
  d.querySelector('.dclose').onclick=()=>closeDocks();
  d.querySelector('#surfOn').onchange=e=>{
    LAYERS.filter(r=>r.hz).forEach(r=>{r.on=e.target.checked;});
    applyHuntZoneFilter(); buildLayersDock(); refreshLayerHeader(); refreshLayersPill();
  };
  d.querySelectorAll('#surfSeg button').forEach(b=>b.onclick=()=>{
    surfMode=b.dataset.m; buildSurfDock(); openDock('surfDock','viewSurface'); applyHuntZoneFilter();
  });
  d.querySelector('#surfMin').oninput=e=>{
    surfMin=+e.target.value;
    d.querySelector('#surfMinV').textContent=surfMin?('.'+String(surfMin).padStart(2,'0')):t('surf.none','none');
    applyHuntZoneFilter();
  };
  d.querySelector('#surfOp').oninput=e=>{
    surfOpacity=+e.target.value/100; applySurfaceOpacity();
    e.target.nextElementSibling.textContent=e.target.value+'%';
  };
}

/* --- Area statistics --------------------------------------------------------
   Follows the cursor at a 16px offset and flips at the viewport edges. The
   confidence gauge travels WITH the number, always — a score shown without its
   confidence is the most misleading thing this interface could put on screen. */
let statsOn=false;
function buildStatsCard(){
  if(document.getElementById('statsCard')) return;
  const el=document.createElement('div');
  el.id='statsCard'; el.className='hidden';
  document.body.appendChild(el);
  map.on('mousemove',e=>{ if(statsOn) moveStats(e); });
  map.on('mouseout',()=>hideStats());
}
function hideStats(){ document.getElementById('statsCard')?.classList.add('hidden'); }
function moveStats(e){
  const el=document.getElementById('statsCard'); if(!el) return;
  // Respond anywhere inside the AOI, not only where a huntZones polygon happens to be
  // rendered: gating on queryRenderedFeatures meant the card vanished the moment you
  // turned the huntability surface off (hidden layers return no features), so the tool
  // looked dead. Over a ranked area → full breakdown; elsewhere in the box → the
  // "outside a ranked area" note. Outside the box → nothing.
  const ll=e.lngLat, b=DOC.box;
  if(b && (ll.lng<b.w||ll.lng>b.e||ll.lat<b.s||ll.lat>b.n)){ el.classList.add('hidden'); return; }
  const a=areaUnderPoint(ll);
  el.innerHTML=statsHTML(a);
  el.classList.remove('hidden');
  const r=el.getBoundingClientRect(), pad=16;
  let x=e.originalEvent.clientX+pad, y=e.originalEvent.clientY+pad;
  if(x+r.width  > innerWidth -8) x=e.originalEvent.clientX-r.width -pad;
  if(y+r.height > innerHeight-8) y=e.originalEvent.clientY-r.height-pad;
  el.style.left=Math.max(8,x)+'px'; el.style.top=Math.max(8,y)+'px';
}
function areaUnderPoint(ll){
  let best=null;
  (DOC.areas||[]).forEach(a=>{ if(a.geometry && ptInPoly([ll.lng,ll.lat],a.geometry)) best=a; });
  return best;
}
function ptInPoly(p,geom){
  const rings=geom.type==='Polygon'?geom.coordinates:(geom.coordinates||[]).flat(1);
  let inside=false;
  (rings[0]?[rings[0]]:[]).concat(geom.type==='MultiPolygon'?geom.coordinates.map(c=>c[0]):[]).forEach(ring=>{
    for(let i=0,j=ring.length-1;i<ring.length;j=i++){
      const xi=ring[i][0],yi=ring[i][1],xj=ring[j][0],yj=ring[j][1];
      if(((yi>p[1])!==(yj>p[1])) && (p[0]<(xj-xi)*(p[1]-yi)/(yj-yi)+xi)) inside=!inside;
    }
  });
  return inside;
}
/* the five weighted factors, straight off the engine's own methodology so the
   card can never drift from what the model actually did */
const FACTOR_W=[['Browse / burn regen',0.35],['Water & wetland',0.25],
                ['Security & thermal cover',0.20],['Terrain',0.10],['Cover↔opening edge',0.10]];
function statsHTML(a){
  if(!a) return `<div class="scap">${t('stats.cap','AREA STATISTICS')}</div>
    <div class="snone">${t('stats.none','Outside a ranked area — the model scores the raster here but did not cluster it into a focus area.')}</div>`;
  const c=a.conf||{}, pct=Math.round((c.score||0)*100);
  return `<div class="scap">${t('stats.cap','AREA STATISTICS')}<span>#${a.rank} · ${a.area_km2} km²</span></div>
    <div class="sscore"><b>${(a.huntability||0).toFixed(3).replace(/^0/,'')}</b>
      <span class="sbar"><i style="width:${Math.round((a.huntability||0)*100)}%"></i></span></div>
    <div class="sfact">${FACTOR_W.map(([n,w])=>
      `<div><span>${n}</span><i style="width:${w*100*2.4}px"></i><b>${Math.round(w*100)}%</b></div>`).join('')}</div>
    <div class="sconf"><span>${t('stats.conf','CONFIDENCE')}</span>
      <span class="sgauge"><i style="width:${pct}%"></i></span><b>${pct}% ${c.band||''}</b></div>
    <div class="snote">${(c.drivers||[])[0]||''}</div>`;
}

/* --- Tool readout -----------------------------------------------------------
   A measurement always states its assumption. A bare "1:56" invites trust the
   model cannot promise. */
function drawReadout(){
  if(!drawPts.length) return null;
  if(drawTool==='dist'||drawTool==='line'||drawTool==='route'){
    const km=polyKm(drawPts);
    const h=km/2.5, hh=Math.floor(h), mm=Math.round((h-hh)*60);
    return {tiles:[UNITS==='imperial'?(km*0.621371).toFixed(2)+' mi':km.toFixed(2)+' km',
                   `${hh}:${String(mm).padStart(2,'0')} h`],
            note:t('tip.assume','Estimated at 2.5 km/h bushwhack. A loaded pack-out is roughly half that.')};
  }
  if(drawTool==='area'&&drawPts.length>2)
    return {tiles:[areaFmt(ringKm2(drawPts))],note:t('tip.areaAssume','Spherical area of the ring as drawn.')};
  return null;
}

/* ---------------------------------------------------------------------------
   JOB POLLING — resilient by default.

   What went wrong on 2026-08-04: the engine pegs a core for the length of a run,
   and while it did, one poll came back as a Caddy 502 ("EOF" on a reused
   keep-alive connection). A proxy-generated 502 carries no CORS headers, so the
   browser rejects it outright and `fetch` rejects — which the old single-`.catch`
   poller treated as fatal. It threw away a run that was still computing fine on
   the server, and said "Lost connection to the engine."

   A poll failure is almost never the end of a run. So: retry with backoff, only
   give up after a sustained outage, and keep the job id so the run can be
   rejoined after a give-up or a page reload.
--------------------------------------------------------------------------- */
const JOB_KEY='transect_job';
const POLL_MS=2500, POLL_GIVEUP_MS=180000;   // 3 min of consecutive failures
function rememberJob(id){
  try{localStorage.setItem(JOB_KEY,JSON.stringify({id,at:Date.now(),plan:CUR_PLAN_ID||null}));}catch(e){}
}
function forgetJob(){ try{localStorage.removeItem(JOB_KEY);}catch(e){} }
function storedJob(){
  try{
    const j=JSON.parse(localStorage.getItem(JOB_KEY)||'null');
    // a job older than two hours is not worth rejoining; the engine drops it on restart
    if(j&&j.id&&Date.now()-j.at<7200000) return j;
  }catch(e){}
  return null;
}
function pollJob(jid,headers,STAGE,stop,setBtn,line,onHead){
  let failedSince=0;
  const tick=()=>{
    fetch(API_URL+'/jobs/'+jid,{headers,cache:'no-store'})
      .then(r=>{
        // 5xx from the proxy means the engine was too busy to answer, not that the
        // run died. Treat it as a retry, exactly like a dropped connection.
        if(r.status>=500) throw new Error('upstream '+r.status);
        return r.json();
      })
      .then(s=>{
        failedSince=0;
        if(s.status==='done'){
          stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); LAST_JOB_ID=jid; forgetJob(); setBtn('RUN ANALYSIS →',false);
          // THE RENDER RUNS IN ITS OWN try/catch, and this is not defensive padding.
          // The .catch() at the bottom of this chain was written for NETWORK failures,
          // but it sits on the whole promise chain — so an exception thrown in HERE,
          // while drawing a finished result, came out as "ANALYSING… reconnecting" and
          // retried for ever. The hunter watched a completed analysis report itself as a
          // connection problem. A run that finished and then failed to DRAW is a
          // different fact from a run we cannot reach, and it has to say so.
          try{
            applyDoc(s.scout);
            // a finished run should present its result: Overview, with the layers card
            // showing what was drawn — even if it was dismissed earlier during Setup.
            layersDismissed=false; setTab('overview'); syncDocks('overview');
            autosavePlan();
          }catch(err){
            console.error('render of finished analysis failed', err);
            tellModal(t('dlg.renderTitle','The analysis finished but could not be drawn'),
              escHtml(String((err&&err.message)||err))+
              `<br><br>${escHtml(t('dlg.renderBody','The run itself completed and nothing was lost — this is a fault in the app drawing the result. The message above identifies it.'))}`,
              'danger');
          }
          return;
        } else if(s.status==='error'){
          stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); forgetJob(); setBtn('RUN ANALYSIS →',false);
          tellModal(t('dlg.failTitle'),
            `The engine reported: <b>${escHtml(s.error||'unknown error')}</b><br>
             Your setup is untouched — nothing to re-enter before trying again.`,'danger');
        } else if(s.status==='cancelled'){
          stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); forgetJob(); setBtn('RUN ANALYSIS →',false);
          if(s.orphaned) tellModal(t('dlg.stoppedTitle'),
            t('dlg.stoppedBody'),'warn');
        } else if(s.status==='unknown'){
          stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); forgetJob(); setBtn('RUN ANALYSIS →',false);
          tellModal(t('dlg.restartTitle'),
            t('dlg.restartBody'),'warn');
        } else {
          const st=s.stage||'', nm=STAGE[st]||st;
          // acquire has no sub-progress to report, so say what it's doing, not 0%
          const head=(st==='acquire') ? `ANALYSING… ${nm}`
            : `ANALYSING… ${nm} · ${Math.round((s.progress||0)*100)}%`;
          onHead(head); setBtn(line(head),true); setTimeout(tick,POLL_MS);
        }
      })
      .catch(()=>{
        const now=Date.now();
        if(!failedSince) failedSince=now;
        const out=now-failedSince;
        if(out>POLL_GIVEUP_MS){
          stop(); RUN_ACTIVE=false; lockSetupWhileRunning(); setBtn('RUN ANALYSIS →',false);
          askModal({kind:'warn', title:t('dlg.lostTitle'),
            body:t('dlg.lostBody'),
            actions:[{id:'stay',label:t('dlg.lostStay')},{id:'reload',label:t('dlg.lostReload'),primary:true}]
          }).then(a=>{ if(a==='reload') location.reload(); });
          return;
        }
        // say so on the button rather than silently stalling, and back off
        const head=`ANALYSING… reconnecting (${Math.round(out/1000)}s)`;
        onHead(head); setBtn(line(head),true);
        setTimeout(tick,Math.min(POLL_MS*Math.ceil(out/10000+1),10000));
      });
  };
  tick();
}
/* ---------------------------------------------------------------------------
   ONE DIALOG (#75).
   Opening a saved plan used to fire a chain of native popups — an alert about the
   missing cache, then a confirm about the engine revision, then maybe another about
   a job still running — each one an OS box in a typeface the app never uses, each
   one blocking, and none of them able to say what the choice actually costs.

   askModal is a single styled dialog: a title, a short body that explains the
   trade-off, and named buttons instead of OK/Cancel. It resolves to the id of the
   button pressed, or null if dismissed, so callers read as a decision and not as a
   pile of nested ifs. Only one is ever on screen; a second call replaces the first.
--------------------------------------------------------------------------- */
const escHtml=s=>String(s==null?'':s).replace(/[<>&"]/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c]));
let _modalClose=null;
function askModal(o){
  if(_modalClose) _modalClose(null);
  return new Promise(resolve=>{
    const wrap=document.createElement('div');
    wrap.className='modalwrap'; wrap.setAttribute('role','dialog'); wrap.setAttribute('aria-modal','true');
    const acts=(o.actions||[{id:'ok',label:'OK',primary:true}]);
    wrap.innerHTML=`<div class="modal" data-kind="${o.kind||'info'}">
      <div class="mtitle">${o.title||''}</div>
      <div class="mbody">${o.body||''}</div>
      <div class="macts">${acts.map(a=>
        `<button data-id="${a.id}" class="${a.primary?'primary':(a.danger?'danger':'ghost')}">${a.label}</button>`
      ).join('')}</div></div>`;
    const done=v=>{ if(!_modalClose) return; _modalClose=null;
      document.removeEventListener('keydown',key); wrap.remove(); resolve(v); };
    const key=e=>{ if(e.key==='Escape'){ e.preventDefault(); done(null); } };
    _modalClose=done;
    wrap.onclick=e=>{ if(e.target===wrap && o.dismissable!==false) done(null); };
    wrap.querySelectorAll('button[data-id]').forEach(b=>b.onclick=()=>done(b.dataset.id));
    document.addEventListener('keydown',key);
    document.body.appendChild(wrap);
    const p=wrap.querySelector('button.primary')||wrap.querySelector('button'); if(p) p.focus();
  });
}
/* a plain replacement for alert(): one dialog, one button, still non-blocking */
function tellModal(title,body,kind){
  return askModal({title,body,kind:kind||'info',actions:[{id:'ok',label:t('dlg.ok'),primary:true}]});
}

/* ENGINE REVISION — a saved plan is never broken by an engine update, but it must
   not quietly pretend to be current either. On opening a plan we compare the
   revision it was computed under against the live engine and OFFER a re-run,
   showing what actually changed so the choice is informed. Declining keeps the
   plan exactly as it is, notes and all. */
let LIVE_REVISION=null;
async function checkEngineRevision(){
  try{
    if(!DOC || DOC.blank) return;
    const was=DOC.engine_revision;
    if(was==null) return;                     // pre-revision plan: nothing to compare
    if(LIVE_REVISION==null){
      const h=await (await fetch(API_URL+'/health',{cache:'no-store'})).json();
      LIVE_REVISION=h.engine_revision??null;
    }
    if(LIVE_REVISION==null || LIVE_REVISION<=was) return;
    const note=(await (await fetch(API_URL+'/health',{cache:'no-store'})).json()).revision_notes||'';
    const lines=String(note).split('\n').map(s=>s.replace(/^[-•*]\s*/,'').trim()).filter(Boolean);
    const est=estimateMinutes(draft.radius,draft.resM);
    const a=await askModal({kind:'warn',
      title:t('dlg.revTitle'),
      body:`${t('dlg.revBody')}
        <b>rev ${was}</b> → <b>rev ${LIVE_REVISION}</b>.
        ${lines.length?'<ul>'+lines.slice(0,6).map(l=>'<li>'+escHtml(l)+'</li>').join('')+'</ul>':''}
        <span class="note">Re-analysing takes about ${est.lo}–${est.hi} min and replaces the current
        areas, sites and brief. Your drawings and notes are kept either way.</span>`,
      actions:[{id:'keep',label:t('dlg.revKeep')},{id:'run',label:t('dlg.revRun'),primary:true}]});
    if(a==='run') runAnalysis();
    else DOC._revisionDismissed=true;         // don't nag on every tab switch
  }catch(e){ /* never let a version check break opening a plan */ }
}

/* Tell the engine when we leave, so a run is never computed for nobody.
   `pagehide` fires on close, navigation and mobile backgrounding; `keepalive` is what
   lets a request outlive the document. The server also reaps unheard-from jobs on its
   own, because this beacon is best-effort — a crash or a lost network sends nothing. */
function abandonJobOnUnload(){
  window.addEventListener('pagehide',()=>{
    const j=storedJob(); if(!j) return;
    // A reload is not an abandonment: resumeJob() will reconnect and the heartbeat
    // resumes well inside the server's window, so only fire when the run is live.
    try{
      fetch(API_URL+'/jobs/'+j.id,{method:'DELETE',keepalive:true,
        headers:authTok()?{'Authorization':'Bearer '+authTok()}:{}});
    }catch(e){}
  });
}
/* On load, rejoin a run that was still going when the page went away. */
/* Rejoin a run that outlived the page — but ONLY for the plan that started it.
   Reattaching unconditionally meant opening "+ New hunt plan" adopted whatever job
   was last running and showed a blank plan locked at "ANALYSING… 71%", with no way
   out of a run that had nothing to do with it. */
function resumeJob(){
  const q=new URLSearchParams(location.search);
  const j=storedJob(); if(!j) return;
  // explicit "new plan" intent: ?tab=setup with no ?plan= — that job is not ours
  if(q.get('tab')==='setup' && !q.get('plan')){ forgetJob(); return; }
  // a job belongs to one plan; opening a different one must not inherit it
  if(j.plan && CUR_PLAN_ID && j.plan!==CUR_PLAN_ID){ return; }
  if(j.plan && !CUR_PLAN_ID){ forgetJob(); return; }
  const jid=j.id;
  const hdr=authTok()?{'Authorization':'Bearer '+authTok()}:{};
  fetch(API_URL+'/jobs/'+jid,{headers:hdr,cache:'no-store'}).then(r=>r.json()).then(s=>{
    if(!s||s.status==='unknown'||s.status==='error'||s.status==='cancelled'){ forgetJob(); return; }
    if(s.status==='done'){
      RUN_ACTIVE=false; lockSetupWhileRunning(); LAST_JOB_ID=jid; forgetJob(); applyDoc(s.scout); layersDismissed=false; setTab('overview'); syncDocks('overview');
      autosavePlan();
      return;
    }
    setTab('setup');
    askModal({title:t('dlg.jobTitle'),
      body:`An analysis you started for this plan is still working on the engine
        ${s.pct!=null?`(<b>${Math.round(s.pct)}%</b> done)`:''}. Reconnect and it finishes where it is;
        abandon it and that engine time is spent for nothing.`,
      actions:[{id:'drop',label:t('dlg.jobDrop')},{id:'watch',label:t('dlg.jobWatch'),primary:true}]
    }).then(a=>{
      if(a!=='watch'){ forgetJob(); return; }
      RUN_ACTIVE=true; _watchJob(jid,hdr);
    });
  }).catch(()=>{});
}
function _watchJob(jid,hdr){
  const setBtn=(t,d)=>{const b=document.getElementById('runBtn'); if(b){b.textContent=t;b.disabled=!!d;}};
  const line=t=>t;
  const STAGE={acquire:'fetching terrain, imagery, burns & hydro',terrain:'terrain analysis',
    habitat:'habitat model',behavior:'behavioural surfaces',access:'access & pack-out',
    synth:'placing areas & sites',contract:'building your plan'};
  pollJob(jid,hdr,STAGE,()=>{},setBtn,line,()=>{});
}

/* ---------------------------------------------------------------------------
   HOVER IDENTIFY — "what am I looking at?"
   Every drawn thing on this map is a claim, and a claim you can't name is worse
   than one you can't see. Hovering any feature names it, says which legend row
   it belongs to, and gives the one fact that matters for that kind. The feature
   under the cursor also lifts, so the label and the geometry can't be mismatched.
--------------------------------------------------------------------------- */
const IDENTIFY = [
  // ORDER IS PRIORITY, and it is the inverse of GENERALITY — most specific first, so the
  // thing you are pointing AT wins over the thing it sits inside. The huntability band
  // used to sit 7th and therefore beat refuge, browse, burns, cuts, funnels, wetlands,
  // beaver ponds, tenure, roads, trails and water: it covers most of the map, so hovering
  // any real feature inside it just reported the band and there was no way to drill down.
  // It is a broad model surface and belongs LAST — the answer when nothing better is
  // under the cursor. (Paint order already had it at the bottom; this is the same idea
  // applied to the cursor.)
  // order matters: points first, so a site beats the polygon under it
  {lyr:'sites',        row:p=>SITE_ROW[p.type], title:p=>SITE_LABEL[p.type]||p.type||'Hunt site',
                       sub:p=>p.when||''},
  {lyr:'camps',        row:'camps2',
                       title:p=>p.fixed?'Your camp':'Base camp',
                       sub:p=>p.fixed?'you placed this — the plan is built around it'
                                     :(p.anchor?`${p.anchor} access`:'')},
  {lyr:'staging',      row:'staging',  title:p=>p.is_camp?'Staging — and your camp':'Staging / parking',
                       sub:p=>p.walk_km!=null?`leave the truck here — ~${p.walk_km} km walk to the area`
                                             :'where you leave the truck'},
  {lyr:'shooters',     row:'shooters', title:()=>'Shooter position',
                       sub:()=>`~${((DOC.scent&&DOC.scent.geometry)||{}).shooter_m||70} m downwind of the caller`},
  // A wick is useless without its refresh interval, and the interval depends on the
  // day you have scrubbed to — so the hover says both.
  {lyr:'scent',        row:'scent', title:p=>p.mid?t('scent.mid'):t('scent.flank'),
                       sub:()=>{
                         const g=(DOC.scent&&DOC.scent.geometry)||{};
                         const cad=((DOC.scent&&DOC.scent.cadence)||[])
                           .find(c=>selectedDay&&c.date===selectedDay.date);
                         const h=g.height_m||[1,1.5];
                         const geo=tf('scent.geo',{m:g.wick_m||45,a:h[0],b:h[1]});
                         return cad ? `${geo} · ${tf('scent.refresh',{h:cad.refresh_hours})}`
                           + (cad.rain_reset?' · '+t('scent.rain'):'') : geo;
                       }},
  {lyr:'crossings',    row:'crossings',
                       title:p=>CROSS_LABEL[p.kind]||CROSS_LABEL.boat,
                       chip:p=>CROSS_CHIP[p.kind]||CROSS_CHIP.boat,
                       // basis is the whole point: say whether we checked or guessed
                       sub:p=>[(p.why||''),
                               p.basis==='measured'?'Measured from mapped road data.'
                                                   :'Inferred from the waterway class alone — no width or ford data ships here.',
                               p.route?`On the ${p.route.replace('route_','')} leg.`:''
                              ].filter(Boolean).join(' ')},
  {lyr:'refugeZones',  row:'refuge',   title:()=>'Thermal refuge',   sub:p=>`${p.area_km2} km²`},
  // SPECIFIC BEFORE BLANKET. IDENTIFY takes the FIRST match under the cursor, so with
  // browse listed first every hover on a cut reported "Browse / feeding, 140 km²" — the
  // least informative true statement available. Browse is a composite covering most of
  // the map; the layers that say WHY a piece of it scores have to be asked first.
  {lyr:'cutZones',     row:'cuts',     title:p=>({fresh:'Recent cut · fresh (<10 yr)',regen:'Recent cut · prime regen (10–25 yr)',closing:'Recent cut · closing in (26–40 yr)'}[p.cls]||'Logging cut'),
                       sub:p=>{
                         const yr = (p.yrFirst&&p.yrLast)
                           ? (p.yrFirst===p.yrLast ? `cut ${p.yrFirst}` : `cut ${p.yrFirst}–${p.yrLast}`)
                           : '';
                         const age = p.ageMed!=null ? `~${p.ageMed} yr old` : '';
                         return [yr, age, `${p.area_km2} km²`].filter(Boolean).join(' · ');
                       }},
  {lyr:'burnZones',    row:'burns',    title:p=>`Burn regeneration · ${p.cls||''}`, sub:p=>`${p.area_km2} km²`},
  {lyr:'browse_cut_zones',   row:'browseCut',   title:()=>'Browse — from dated cuts',
                       sub:p=>`${p.area_km2} km² · scores ${p.score} on this source alone`},
  {lyr:'browse_burn_zones',  row:'browseBurn',  title:()=>'Browse — from dated burns',
                       sub:p=>`${p.area_km2} km² · scores ${p.score} on this source alone`},
  {lyr:'browse_stand_zones', row:'browseStand', title:()=>'Browse — from the stand map',
                       sub:p=>`${p.area_km2} km² · scores ${p.score} on this source alone`},
  {lyr:'browse_lc_zones',    row:'browseLc',    title:()=>'Browse — from satellite land cover',
                       sub:p=>`${p.area_km2} km² · scores ${p.score} on this source alone`},
  // LAST of the browse family: the composite, which is what you get when nothing more
  // specific is under the cursor. It leads with WHERE ITS ANSWER CAME FROM.
  {lyr:'browseZones',  row:'browse',   title:()=>'Browse / feeding',
                       sub:p=>{
                         const bits=[];
                         if(p.src) bits.push(`mostly the ${p.src}${p.srcShare!=null?` (${Math.round(p.srcShare*100)}%)`:''}`);
                         if(p.agree!=null) bits.push(p.agree>=0.8?'sources agree'
                                                    :p.agree>=0.5?'sources partly agree'
                                                                 :'sources disagree here');
                         if(p.score!=null) bits.push(`score ${p.score}`);
                         bits.push(`${p.area_km2} km²`);
                         return bits.join(' · ');
                       }},
  {lyr:'funnelZones',  row:'funnel',   title:()=>'Funnel / pass',
                       // The NECK WIDTH is the claim this feature is making; area is not.
                       // "0.1 km²" is unfalsifiable — "a 180 m neck" is something you can
                       // check against the contours in front of you, and it is what makes a
                       // funnel drawn through a bog obviously wrong.
                       sub:p=>{
                         const w=p.neck_m!=null?`~${p.neck_m} m neck`:'width not measured';
                         const meta=DOC.funnel_meta||{};
                         const thin=meta.grhq_present===false;
                         return `${w} · ${p.area_km2} km²`+(thin?' · bog data missing here — treat with suspicion':'');
                       }},
  {lyr:'wetlandZones', row:'wetland',  title:()=>'Wetland',          sub:p=>`${p.area_km2} km² · marsh/bog — barrier + slow going`},
  {lyr:'beaverPonds',  row:'beaver',   title:()=>'Beaver pond',      sub:()=>'GRHQ flowage — a rut hub; hunt the wet edge beside cover'},
  {lyr:'tenureBlocked',row:'tenure',   title:()=>'Closed to you',    sub:p=>p.name||'outfitter / reserve tenure'},
  {lyr:'tenureZones-line-ok', row:'tenure-ok', title:()=>'Bookable — register first',
                       sub:p=>(p.name?p.name+' — ':'')+'you may hunt here, but it is a ZEC or réserve faunique: daily registration or a reservation is required.'},
  {lyr:'areas-fill',   row:'areas',    title:p=>`Focus area ${p.rank}`,
                       sub:p=>`${p.area_km2} km² · score ${p.mean_huntability}`},
  {lyr:'route-best',   row:'routes',   title:()=>'Hunt line',        sub:()=>'camp → stand, least-cost on foot'},
  {lyr:'route-hot',    row:'routes',   title:()=>'Midday line',      sub:()=>'camp → thermal refuge'},
  {lyr:'route-access', row:'access',   title:()=>'Access leg',       sub:()=>'staging point → this focus area'},
  {lyr:'roads',        row:'roads',    title:p=>p.name||({artery:'Through road',road:'Local / forest road'}[p.cls]||'Road'),
                       // Surface is reported rather than encoded in the line style — the
                       // style says what the road is FOR, this says what it is made of.
                       sub:p=>[({artery:'Through road',road:'Drivable road'}[p.cls]||'Road'),
                               p.unpaved?'gravel / unpaved — scout the last spur on foot':'paved'
                              ].filter(Boolean).join(' · ')},
  {lyr:'roads-track',  row:'roads',    title:p=>p.name||'Resource / logging track',
                       sub:()=>'Gravel two-track — may be rough or seasonal; scout before you trust it'},
  {lyr:'trails',       row:'trails',   title:p=>p.name||'Foot trail',
                       sub:()=>'OSM path — walk-in only, not drivable'},
  {lyr:'rivers',       row:'water',    title:p=>p.name||'Watercourse',sub:()=>'mapped hydrography (OSM)'},
  {lyr:'lakes',        row:'water',    title:p=>p.name||'Waterbody', sub:()=>'mapped hydrography (OSM)'},
  // LAST ON PURPOSE — see the note above.
  {lyr:'huntZones',    row:null,       title:p=>(HUNT_CLS[p.cls]||{}).label||'Likelihood band',
                       sub:p=>`${p.area_km2} km² · model band, no surveyed edge`},
];
// No validate_ground entry: the st-ground legend row is gone, and pointing at a row
// that no longer exists is how a panel reconcile ends up with a dangling toggle.
const SITE_ROW={rut_calling:'st-rut',saline_blind:'st-saline',glassing:'st-glass'};
const SITE_LABEL={rut_calling:'Calling position',thermal_refuge:'Thermal refuge',
  saline_blind:'Feeding edge',funnel:'Funnel / pass',glassing:'Glassing knob',
  validate_ground:'Ground-truth check',base_camp:'Base camp',parking:'Staging / parking'};
let idHover=null;
/* ONE CARD PER FEATURE UNDER THE CURSOR (T9.4).
   It used to show only the FIRST match, so reading a spot where several layers overlap
   — which is most interesting ground, since that is what "interesting" means here —
   meant toggling layers off and on to interrogate them one at a time. Reported as
   exactly that. Now every hit renders its own card, in IDENTIFY order (specific before
   blanket), capped so a busy pixel does not fill the screen. */
const ID_MAX_CARDS = 4;

function idCardHTML(def, f){
  const p=f.properties||{};
  const rk=typeof def.row==='function'?def.row(p):def.row;
  const row=rk?LAYERS.find(r=>r.k===rk):null;
  const sub=(def.sub&&def.sub(p))||'';
  // #71 — say WHY this is here and how sure we are. Modelled features carry a
  // confidence + plain-language reasons from the engine; layers that come straight
  // from an official dataset name the SOURCE instead of inventing a rationale, so a
  // hunter can tell "we measured this" from "we inferred this".
  let why=[]; try{ why=typeof p.why==='string'?JSON.parse(p.why):(p.why||[]); }catch(e){ why=[]; }
  // browse zones carry `why` as an OBJECT ({source, share}), not a list of reasons —
  // rendering an object here printed "[object Object]" at the hunter.
  if(why && !Array.isArray(why)) why = why.source ? ['mostly the '+why.source] : [];
  const conf=p.conf!=null?(typeof p.conf==='object'?p.conf.score:p.conf):null;
  const prov=(DOC.layer_provenance||{})[rk]||null;
  const pct=v=>Math.round(v*100)+'%';
  // Which site / season this belongs to, when a run compared several (T9.1/T9.2). Two
  // features from different ground or different weeks must never read as one place.
  const tag=[(p.site!=null && (DOC.sites||[]).length>1)?('site '+p.site):'',
             (p.window!=null && (DOC.windows||[]).length>1)?('season '+p.window):'']
            .filter(Boolean).join(' · ');
  return `<div class="iditem">
    <div class="idhead">${row?iconBadge(row.icon,row.hex,18,def.chip&&def.chip(p)):''}
      <span>${def.title(p)}</span></div>`+
    (tag?`<div class="idsub" style="opacity:.7">${tag}</div>`:'')+
    (sub?`<div class="idsub">${sub}</div>`:'')+
    (conf!=null?`<div class="idsub" style="color:#e2c044">Confidence ${pct(conf)}${p.band?' · '+p.band:''}</div>`:'')+
    ((why&&why.length)?`<div class="idsub" style="opacity:.9">${
       why.map(w=>'· '+String(w)).join('<br>')}</div>`:'')+
    (prov?`<div class="idsub" style="opacity:.75">Source: ${prov.source} · ${pct(prov.conf)}</div>`:'')+
    (row?`<div class="idrow">${row.name}</div>`:'')+
  `</div>`;
}

function buildIdentify(){
  if(document.getElementById('idCard')) return;
  const el=document.createElement('div');
  el.id='idCard'; el.className='hidden';
  document.body.appendChild(el);
  map.on('mousemove',e=>{
    // A tool owns the cursor. Identifying features while someone is placing
    // measurement points fights them for the pointer and buries the readout.
    if(drawTool){ clearIdentify(); return; }
    const live=IDENTIFY.filter(d=>map.getLayer(d.lyr) &&
      map.getLayoutProperty(d.lyr,'visibility')!=='none');
    const hits=map.queryRenderedFeatures(
      [[e.point.x-4,e.point.y-4],[e.point.x+4,e.point.y+4]],
      {layers:live.map(d=>d.lyr)});
    if(!hits.length){ clearIdentify(); return; }
    // Walk IDENTIFY order (points before polygons, specific before blanket) and take
    // each layer's nearest hit. One card per LAYER rather than per feature: two
    // adjacent polygons of the same kind under one pixel are the same answer twice.
    const picked=[];
    for(const def of live){
      const f=hits.find(h=>h.layer.id===def.lyr);
      if(f) picked.push({def,f});
    }
    if(!picked.length){ clearIdentify(); return; }
    const shown=picked.slice(0,ID_MAX_CARDS);
    const more=picked.length-shown.length;
    el.innerHTML=shown.map(x=>idCardHTML(x.def,x.f)).join('')+
      (more>0?`<div class="idmore">+${more} more layer${more>1?'s':''} here — hide one to see it</div>`:'');
    el.classList.remove('hidden');
    const r=el.getBoundingClientRect(), pad=14, cx=e.originalEvent.clientX, cy=e.originalEvent.clientY;
    let x=cx+pad, y=cy+pad;
    if(x+r.width  > innerWidth -8) x=cx-r.width -pad;
    if(y+r.height > innerHeight-8) y=cy-r.height-pad;
    el.style.left=Math.max(8,x)+'px'; el.style.top=Math.max(8,y)+'px';
    map.getCanvas().style.cursor='pointer';
    // Emphasis still follows the TOP card only — lighting up four layers at once is
    // the flashing this codebase has already been told off for.
    const top=shown[0].def.lyr;
    if(idHover!==top){ if(idHover) emphasiseMapLayer(idHover,false);
      emphasiseMapLayer(top,true); idHover=top; }
  });
  map.on('mouseout',clearIdentify);
}
function clearIdentify(){
  const el=document.getElementById('idCard'); if(el) el.classList.add('hidden');
  if(idHover){ emphasiseMapLayer(idHover,false); idHover=null; }
  if(!drawTool) map.getCanvas().style.cursor='';
}
/* Reference/basemap layers are context, not findings — hovering a road must not
   fatten the whole road network, and water is everywhere. The identify card still
   NAMES them; we just don't light them up. Only model output (zones, sites, our
   routes) earns a highlight. */
// huntZones is the huntability SURFACE — its opacity is owned by the Model-surface
// slider, so a hover must not touch it (it was jumping to 100% on hover and settling at
// 0.9, never back to the slider value). Identify still NAMES it; it just isn't lit up.
// EMPHASIS IS LAYER-WIDE, NOT PER-FEATURE. setPaintProperty changes the whole layer, so
// hovering one line "highlights" every line in it. On a handful of routes that reads as
// emphasis; on a dense network it is the entire map flashing at you — which is what
// happened with the forest tracks: crossing a single logging road thickened every logging
// road in the AOI. roads/roads-case/rail were already exempt for this reason and
// roads-track/trails were simply missed, being newer (AQréseau+, #81).
// The identify tooltip still works on all of them; only the flash is gone.
const NO_EMPHASIS=new Set(['roads','roads-case','roads-track','trails','rail','trans',
  'rivers','lakes','lakes-line','boundaries','huntZones']);
/* lift the hovered layer so the label and the geometry can't disagree */
function emphasiseMapLayer(id,on){
  if(NO_EMPHASIS.has(id)) return;
  if(!map.getLayer(id)) return;
  const t=map.getLayer(id).type;
  try{
    if(t==='fill') map.setPaintProperty(id,'fill-opacity',on?1:(id==='areas-fill'?0.10:0.9));
    else if(t==='line') map.setPaintProperty(id,'line-width',
      on?(id==='roads'?3.4:4):(id==='route-best'?2.4:2));
    else if(t==='symbol') map.setPaintProperty(id,'icon-opacity',on?1:0.95);
    else if(t==='circle') map.setPaintProperty(id,'circle-opacity',on?1:0.9);
  }catch(e){}
}
