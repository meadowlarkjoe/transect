/* Transect on MapLibre — binds window.TRANSECT_DATA (engine transect.json). */
const DOC = window.TRANSECT_DATA;
let selectedDay = null;

/* ---------------- hunt setup state ---------------- */
let SETUP = { watercraft:'canoe', huntStyle:'spike' };   // watercraft: none|canoe|motor ; huntStyle: spike|vehicle

/* ---------------- units ---------------- */
let UNITS = 'metric';                       // 'metric' | 'imperial'
const KM_MI = 1.609344;
const km = (v) => UNITS === 'imperial' ? (v / KM_MI).toFixed(1) + ' mi' : v.toFixed(1) + ' km';
const metres = (m) => UNITS === 'imperial' ? Math.round(m * 1.09361) + ' yd' : Math.round(m) + ' m';
const unitBig = () => UNITS === 'imperial' ? 'mi' : 'km';
const unitSmall = () => UNITS === 'imperial' ? 'yd' : 'm';

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
// Sites we render (base_camp/parking handled separately as camp + staging)
const SITE_TYPES = ['rut_calling','thermal_refuge','saline_blind','funnel','glassing','validate_ground'];

/* ---------------- basemap ---------------- */
const ESRI = k => `https://server.arcgisonline.com/ArcGIS/rest/services/${k}/MapServer/tile/{z}/{y}/{x}`;
function baseStyle(){
  return {
    version:8, glyphs:'https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf',
    sources:{
      satellite:{type:'raster',tiles:[ESRI('World_Imagery')],tileSize:256,attribution:'Esri'},
      topo:{type:'raster',tiles:[ESRI('World_Topo_Map')],tileSize:256,attribution:'Esri'},
      trans:{type:'raster',tiles:[ESRI('Reference/World_Transportation')],tileSize:256},
      dem:{type:'raster-dem',tiles:['https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'],
           encoding:'terrarium',tileSize:256,maxzoom:14}
    },
    layers:[
      {id:'satellite',type:'raster',source:'satellite'},
      {id:'topo',type:'raster',source:'topo',layout:{visibility:'none'}},
      {id:'trans',type:'raster',source:'trans',layout:{visibility:'none'}}
    ],
    sky:{}
  };
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
  return {areas,areaLabels,camps,staging,packin,rivers,lakes,crossings};
}

function init(){
  document.getElementById('subtitle').textContent =
    `${DOC.meta.title} · ${DOC.meta.species} · ${DOC.meta.target_dates.join(' – ')}`;
  addIcons();
  const S=buildSources();

  // heat surface (image source over the AOI box)
  map.addSource('heat',{type:'image',url:heatURL(),coordinates:heatCoords()});
  map.addLayer({id:'heat',type:'raster',source:'heat',
    paint:{'raster-opacity':HEAT.opacity,'raster-resampling':'linear','raster-fade-duration':0}});

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

  map.addLayer({id:'areas-fill',type:'fill',source:'areas',
    paint:{'fill-color':['case',['<=',['get','rank'],2],'#2fbf5b','#e2c044'],'fill-opacity':0.10}});
  map.addLayer({id:'areas-line',type:'line',source:'areas',
    paint:{'line-color':'#ffffff','line-width':2,'line-opacity':0.9,'line-dasharray':[3,2]}});
  map.addLayer({id:'packin',type:'line',source:'packin',
    paint:{'line-color':'#b98a3e','line-width':1.6,'line-dasharray':[2,2],'line-opacity':0.75}});
  map.addLayer({id:'sites',type:'symbol',source:'sites',
    layout:{'icon-image':['get','type'],'icon-size':0.55,'icon-allow-overlap':true}});
  map.addLayer({id:'staging',type:'symbol',source:'staging',
    layout:{'icon-image':'parking','icon-size':0.62,'icon-allow-overlap':true}});
  map.addLayer({id:'camps',type:'symbol',source:'camps',
    layout:{'icon-image':'base_camp','icon-size':0.7,'icon-allow-overlap':true,
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
    new maplibregl.Popup().setLngLat(e.lngLat).setHTML(
      `<h4>${LABELS[p.type]||p.type}</h4>${p.when?('<div class="s">'+p.when+'</div>'):''}`+
      (p.windnote?('<div class="s">'+p.windnote+'</div>'):'')).addTo(map);});
  ['areas-fill','sites','camps','staging'].forEach(l=>{
    map.on('mouseenter',l,()=>map.getCanvas().style.cursor='pointer');
    map.on('mouseleave',l,()=>map.getCanvas().style.cursor='');});

  buildPanel(); buildWeather(); buildLegend(); buildTools();
  renderSetup(); renderBrief(); wireTabs(); setTab('overview');
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
  setTab('overview');
  document.getElementById('list').classList.add('hidden');
  document.getElementById('method').classList.add('hidden');
  const d=document.getElementById('detail'); d.classList.remove('hidden');
  const wps=DOC.waypoints.filter(w=>w.properties.focus_area===rank && SITE_TYPES.includes(w.type));
  const st=a.stats||{};
  const rutT=(DOC.rut&&DOC.rut.targets&&DOC.rut.targets[0])||null;
  d.innerHTML=`<div class="back">← all areas</div>
    <h2><span class="badge ${rank<=2?'top':''}" style="display:inline-grid">${rank}</span> Area ${rank} · ${a.area_km2} km²</h2>
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
    ${rutT?`<div class="dd" style="margin-top:8px"><b>Rut</b> — ${rutT.date}: <b style="color:#f2b98a">${rutT.phase}</b> (${Math.round(rutT.responsiveness*100)}% responsive). ${rutT.guidance}</div>`:''}
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
  html+=`<div class="note">Pick a day → sites turn <b style="color:#2fbf5b">green</b> when the wind fits their approach.`+
    (w.days[0].is_proxy?' (prior-year proxy — hunt is months out)':'')+'</div>';
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
}

/* ---------------- tools panel ---------------- */
function buildTools(){
  const t=document.getElementById('tools');
  // basemap + 3D + measure already in HTML; wire them + add heat controls
  t.querySelectorAll('[data-base]').forEach(b=>b.onclick=()=>{
    t.querySelectorAll('[data-base]').forEach(x=>x.classList.remove('on')); b.classList.add('on');
    const base=b.dataset.base;
    map.setLayoutProperty('satellite','visibility',base==='topo'?'none':'visible');
    map.setLayoutProperty('topo','visibility',base==='topo'?'visible':'none');
    map.setLayoutProperty('trans','visibility',base==='hybrid'?'visible':'none');});
  let on3d=false;
  document.getElementById('btn3d').onclick=e=>{on3d=!on3d;e.target.classList.toggle('on',on3d);
    if(on3d){map.setTerrain({source:'dem',exaggeration:1.4});map.easeTo({pitch:60});}
    else{map.setTerrain(null);map.easeTo({pitch:0});}};
  wireMeasure();
  // extra controls injected under Layers
  const extra=document.createElement('div'); extra.className='tgroup';
  extra.innerHTML=`
    <div class="tlabel">Huntability</div>
    <label style="display:flex;align-items:center;gap:6px"><input id="heatOn" type="checkbox" checked> Surface</label>
    <div class="srow"><span class="s">threshold</span><input id="thresh" type="range" min="0" max="0.95" step="0.01" value="${HEAT.thresh}"></div>
    <label style="display:flex;align-items:center;gap:6px;margin-top:4px"><input id="browseOn" type="checkbox"> Browse / feeding</label>`;
  t.appendChild(extra);
  document.getElementById('heatOn').onchange=e=>{HEAT.on=e.target.checked;updateHeat();};
  document.getElementById('thresh').oninput=e=>{HEAT.thresh=+e.target.value;updateHeat();};
  document.getElementById('browseOn').onchange=e=>{HEAT.source=e.target.checked?'browse':'hunt';updateHeat();};
  // per-layer visibility (areas/routes)
  const lay=document.createElement('div'); lay.className='tgroup';
  lay.innerHTML=`<div class="tlabel">Layers</div>
    <label><input type="checkbox" data-lyr="water" checked> Rivers &amp; lakes</label>
    <label><input type="checkbox" data-lyr="crossings" checked> River crossings</label>
    <label><input type="checkbox" data-lyr="areas" checked> Focus areas</label>
    <label><input type="checkbox" data-lyr="packin" checked> Pack-in routes</label>`;
  t.appendChild(lay);
  lay.querySelectorAll('[data-lyr]').forEach(cb=>cb.onchange=()=>{
    const vis=cb.checked?'visible':'none';
    ({areas:['areas-fill','areas-line','area-badges'],packin:['packin'],
      water:['lakes','lakes-line','rivers'],crossings:['crossings']})[cb.dataset.lyr]
      .forEach(id=>map.getLayer(id)&&map.setLayoutProperty(id,'visibility',vis));});
}
function wireMeasure(){
  const btn=document.getElementById('btnmeasure');let on=false,pts=[];
  map.addSource('measure',{type:'geojson',data:fc([])});
  map.addLayer({id:'measure-line',type:'line',source:'measure',paint:{'line-color':'#fff','line-width':2,'line-dasharray':[1,1]}});
  const label=new maplibregl.Popup({closeButton:false,closeOnClick:false});
  btn.onclick=()=>{on=!on;btn.classList.toggle('on',on);if(!on){pts=[];map.getSource('measure').setData(fc([]));label.remove();}};
  map.on('click',e=>{if(!on)return;pts.push([e.lngLat.lng,e.lngLat.lat]);
    map.getSource('measure').setData(fc([{type:'Feature',geometry:{type:'LineString',coordinates:pts}}]));
    let d=0;for(let i=1;i<pts.length;i++)d+=hav(pts[i-1],pts[i]);
    if(pts.length>1)label.setLngLat(e.lngLat).setHTML(`<b>${km(d)}</b>`).addTo(map);});
}
function hav(a,b){const R=6371,dLat=(b[1]-a[1])*Math.PI/180,dLon=(b[0]-a[0])*Math.PI/180,
  s=Math.sin(dLat/2)**2+Math.cos(a[1]*Math.PI/180)*Math.cos(b[1]*Math.PI/180)*Math.sin(dLon/2)**2;
  return 2*R*Math.asin(Math.sqrt(s));}

/* ---------------- Setup (redesigned) ---------------- */
let draft={center:[DOC.meta.center.lon,DOC.meta.center.lat],radius:DOC.meta.radius_km||50,
  walkAccess:2.0,walkHunt:4.0,leaving:'Baie-Comeau'};
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

    <div class="fld"><label>Species</label>
      <div class="radii"><button class="on" disabled>Moose</button></div></div>

    <div class="fld"><label>Search radius — <b id="radVal">${draft.radius} ${unitBig()}</b></label>
      <input id="radius" type="range" min="5" max="120" step="1" value="${draft.radius}"></div>

    <div class="fld"><label>How you'll hunt</label>
      <div class="radii wide"><button id="hsSpike" class="${SETUP.huntStyle==='spike'?'on':''}">Spike camp in the woods</button>
        <button id="hsVeh" class="${SETUP.huntStyle==='vehicle'?'on':''}">Return to vehicle nightly</button></div>
      <div class="s" id="hsNote"></div></div>

    <div class="fld"><label>Watercraft</label>
      <div class="radii"><button id="wcNone" class="${SETUP.watercraft==='none'?'on':''}">No boat</button>
        <button id="wcCanoe" class="${SETUP.watercraft==='canoe'?'on':''}">Canoe</button>
        <button id="wcMotor" class="${SETUP.watercraft==='motor'?'on':''}">Motorboat</button></div></div>

    <div class="fld"><label>Walk from access → base camp (max)</label>
      <div class="numrow"><input id="walkAccess" type="number" step="0.1" value="${draft.walkAccess}"><span id="uAccess">${unitBig()}</span></div></div>
    <div class="fld"><label>Walk from base camp → hunting (max)</label>
      <div class="numrow"><input id="walkHunt" type="number" step="0.1" value="${draft.walkHunt}"><span id="uHunt">${unitBig()}</span></div></div>

    <div class="fld"><label>Leaving from</label>
      <div class="searchrow"><input id="leaveSearch" placeholder="Search departure town…" value="${draft.leaving}">
        <button id="leaveBtn">Search</button></div>
      <div id="leaveRes" class="results"></div></div>

    <div class="fld"><label>Units</label>
      <div class="radii"><button id="uMetric" class="${UNITS==='metric'?'on':''}">Metric (km/m)</button>
        <button id="uImperial" class="${UNITS==='imperial'?'on':''}">Imperial (mi/yd)</button></div></div>

    <button id="runBtn" class="run">RUN ANALYSIS →</button>
    <div class="note">Live recompute for a new area/species/radius needs the engine API online
      (not yet wired). Controls are ready; results shown are the Fire Lake scout.</div>`;

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
  rad.oninput=()=>{draft.radius=+rad.value;document.getElementById('radVal').textContent=draft.radius+' '+unitBig();drawDraft();};
  document.getElementById('walkAccess').onchange=e=>draft.walkAccess=+e.target.value;
  document.getElementById('walkHunt').onchange=e=>draft.walkHunt=+e.target.value;
  document.getElementById('dragBox').onclick=()=>startBoxDraw();
  document.getElementById('uMetric').onclick=()=>setUnits('metric');
  document.getElementById('uImperial').onclick=()=>setUnits('imperial');
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
function reachKm(){ return (draft.walkAccess||2)*(UNITS==='imperial'?1.609344:1); }
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
function runAnalysis(){ // engine API not wired — just show current scout
  setTab('overview'); map.fitBounds(bbox(DOC.areas),{padding:{top:80,left:400,right:200,bottom:120}});
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

/* ---------------- brief ---------------- */
function renderBrief(){
  const g=DOC.legal,m=DOC.methodology;
  let h=`<h2>${DOC.meta.title}</h2><p class="why">${DOC.disclaimer}</p>
    <h3>Legal / access</h3>
    <p>Zone <b>${g.zone}</b> · ${g.diy_possible?'DIY possible':'restricted'} · ${(g.huntable_tenures||[]).join(', ')||'—'}</p>
    ${(g.flags||[]).map(f=>`<p class="s" style="color:#93a1a8">${f}</p>`).join('')}`;
  if(DOC.rut){const r=DOC.rut;h+=`<h3>Rut timing</h3><p>Peak ~<b>${r.peak_date}</b>. `+
    (r.targets||[]).map(t=>`${t.date}: <b>${t.phase}</b> (${Math.round(t.responsiveness*100)}%)`).join(' · ')+`</p>`;}
  if(DOC.strategy){h+=`<h3>Strategy</h3><p><b>${DOC.strategy.headline}</b> — ${DOC.strategy.approach}</p>`;}
  if(DOC.confidence){h+=`<h3>Confidence</h3><p><b>${DOC.confidence.band} (${Math.round(DOC.confidence.score*100)}%)</b> — ${(DOC.confidence.drivers||[]).join('; ')}</p>`;}
  h+=`<h3>What I'm looking for</h3><p>${m.summary}</p><p><b>Weighted:</b> ${(m.factors_weighted||[]).join('; ')}.</p>`;
  h+=`<h3>Focus areas</h3>`;
  DOC.areas.forEach(a=>{h+=`<h3>${a.rank}. ${a.area_km2} km² · huntability ${a.huntability} · camp ${a.camp}</h3>
    <p class="why">${a.why||''}</p><p><b>Pros:</b> ${(a.pros||[]).join('; ')}.</p>
    <p><b>Watch-outs:</b> ${(a.cons||[]).join('; ')}.</p>`;});
  h+=`<h3>Camps</h3>`+DOC.camps.map(c=>`<p>Camp ${c.id} — areas ${c.member_areas.join(', ')} · via ${c.access_type} · pack-in ≤ ${km(c.max_packin_km)}</p>`).join('');
  document.getElementById('brief').innerHTML=h;
}

/* ---------------- tabs ---------------- */
const TAB_SHOW={setup:{setup:1},overview:{panel:1,tools:1,weather:1,legend:1},
  field:{tools:1,weather:1,legend:1},brief:{brief:1}};
function setTab(name){
  const ids=['panel','setup','brief','tools','weather','legend'];
  const show=TAB_SHOW[name]||{};
  ids.forEach(id=>{const el=document.getElementById(id); if(el) el.classList.toggle('hidden',!show[id]);});
  document.querySelectorAll('#tabbar button').forEach(b=>b.classList.toggle('on',b.dataset.tab===name));
  setTimeout(()=>map.resize(),60);
}
function wireTabs(){ document.querySelectorAll('#tabbar button').forEach(b=>b.onclick=()=>setTab(b.dataset.tab)); }
