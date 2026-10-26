// Pure functions shared by the display and the regression tests.
export const IDS = Object.freeze({
  current:'sensor.office_aircraft_current', feed:'sensor.office_aircraft_feed',
  candidate:'sensor.office_aircraft_candidate', routes:'sensor.office_aircraft_routes',
  home:'zone.home', radius:'input_number.office_aircraft_radius',
  session:'input_select.office_aircraft_session', alerts:'input_boolean.office_aircraft_alerts',
  house:'input_select.house_mode', remote:'remote.overhead_tv',
  player:'media_player.overhead_tv',
});
export const ENTITY_IDS = Object.freeze(Object.values(IDS));
export const PAGE_PATH = '/local/aircraft-display/index.html';
export const number = v => typeof v === 'number' && Number.isFinite(v);
export const coordinates = (lat,lon) => number(lat) && number(lon) && Math.abs(lat)<=85 && Math.abs(lon)<=180;

export function localClock(now,timeZone) {
  if (timeZone) try {
    return {
      time:new Date(now).toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit',timeZone}),
      date:new Date(now).toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric',timeZone}).toUpperCase(),
    };
  } catch { /* Wait for a usable home timezone; never silently use the TV's. */ }
  return {time:'—',date:'LOCAL AIRSPACE'};
}

// HA subscribe_entities sends one initial snapshot then compact deltas.
export function applyEntities(states, update) {
  const next = {...states};
  for (const [id,s] of Object.entries(update.a || {})) {
    if (ENTITY_IDS.includes(id)) next[id] = {state:s.s,attributes:{...s.a}};
  }
  for (const id of update.r || []) delete next[id];
  for (const [id,diff] of Object.entries(update.c || {})) {
    if (!next[id]) continue;
    const add = diff['+'] || {};
    const attrs = {...next[id].attributes,...add.a};
    for (const key of diff['-']?.a || []) delete attrs[key];
    next[id] = {state:add.s === undefined ? next[id].state : add.s,attributes:attrs};
  }
  return next;
}

export function observation(states, now, connected) {
  const current = states[IDS.current];
  const stamp = Number(states[IDS.feed]?.state);
  const age = now / 1000 - stamp;
  const fresh = connected && stamp>0 && age>=-5 && age<=15 && current?.attributes?.feed_fresh === true;
  const a = current?.attributes?.aircraft;
  const posAge = now/1000 - a?.position_timestamp;
  const valid = fresh && a && current.state === a.hex && /^[a-f0-9]{6}$/i.test(a.hex) &&
    coordinates(a.latitude,a.longitude) && number(a.altitude_ft) &&
    number(a.distance_mi) && a.distance_mi>=0 && number(posAge) && posAge>=0 && posAge<=20;
  return {fresh, aircraft:valid ? a : null, age:posAge};
}

export function project(lat,lon,zoom) {
  const scale = 256 * 2**zoom;
  const sin = Math.sin(Math.max(-85,Math.min(85,lat))*Math.PI/180);
  return {x:(lon+180)/360*scale,y:(.5-Math.log((1+sin)/(1-sin))/(4*Math.PI))*scale};
}

export function mapGeometry(home,radius,width,height) {
  const metersPerPixel = ((radius+2)*2*1609.344)/(Math.min(width,height)*.78);
  const zoom = Math.max(3,Math.min(15,Math.floor(Math.log2(156543.03392*Math.cos(home.latitude*Math.PI/180)/metersPerPixel))));
  const center = project(home.latitude,home.longitude,zoom);
  const mpp = 156543.03392*Math.cos(home.latitude*Math.PI/180)/2**zoom;
  return {zoom,left:center.x-width/2,top:center.y-height/2,cx:width/2,cy:height/2,
    radiusPx:radius*1609.344/mpp,outerPx:(radius+2)*1609.344/mpp};
}

export class ReturnGate {
  missingSince=null;
  lastAttempt=-Infinity;
  tick({now,states,connected,visible,path,search,demo}) {
    const allowed = !demo && visible && connected && path===PAGE_PATH &&
      new URLSearchParams(search).get('office_tv')==='1' &&
      states[IDS.session]?.state==='Automatic' && states[IDS.alerts]?.state==='on' &&
      states[IDS.house]?.state==='Home' && states[IDS.remote]?.state==='on' &&
      states[IDS.player]?.attributes?.app_id==='com.phlox.tvwebbrowser' &&
      states[IDS.current]?.state==='none' && states[IDS.candidate]?.state==='none' &&
      airspace(states,now,connected).inside.length===0;
    if (!allowed) { this.missingSince=null; return false; }
    if (this.missingSince===null) this.missingSince=now;
    if (now-this.missingSince<15000 || now-this.lastAttempt<5000) return false;
    this.lastAttempt=now;
    return true;
  }
}

// The office TV (?office_tv=1) reads the integration's feed instead of a saved
// login. HA answers only the TV's own connection; the header also keeps other
// origins from sending these requests without a CORS preflight.
export const TV_FEED='/api/office_tv/aircraft', TV_FINISHED='/api/office_tv/aircraft/finished';
const TV_REQUEST=Object.freeze({headers:{'X-Office-TV':'1'},credentials:'omit',cache:'no-store'});

export async function readFeed(fetcher) {
  const response=await fetcher(TV_FEED,TV_REQUEST);
  if (response.status===403) return {denied:true};
  if (!response.ok) throw new Error('connection');
  const body=await response.json();
  if (!body?.states || typeof body.states!=='object') throw new Error('connection');
  const states={};
  for (const id of ENTITY_IDS) {
    const s=body.states[id];
    if (s && typeof s.state==='string') states[id]={state:s.state,attributes:{...s.attributes}};
  }
  return {states,timeZone:typeof body.time_zone==='string'?body.time_zone:null};
}

export const finishSession=fetcher=>fetcher(TV_FINISHED,{...TV_REQUEST,method:'POST'});

export function savedAuth(storage,origin) {
  try {
    const t=JSON.parse(storage.getItem('hassTokens'));
    // Never follow a stored token to another host or carry credentials in a URL.
    if (!t || new URL(t.hassUrl).origin!==origin || !t.refresh_token) return null;
    return t;
  } catch { return null; }
}

export async function accessToken(storage,origin,fetcher,now,force=false) {
  let auth=savedAuth(storage,origin);
  if (!auth) throw new Error('sign-in');
  if (!force && auth.access_token && number(auth.expires) && auth.expires>now+30000) return auth.access_token;
  const form=new URLSearchParams({grant_type:'refresh_token',refresh_token:auth.refresh_token});
  if (auth.clientId) form.set('client_id',auth.clientId);
  const response=await fetcher('/auth/token',{method:'POST',body:form,credentials:'same-origin'});
  if (!response.ok) throw new Error([400,401,403].includes(response.status)?'sign-in':'connection');
  const fresh=await response.json();
  if (!fresh.access_token || !number(fresh.expires_in)) throw new Error('connection');
  // Do not resurrect a login that was revoked/changed while refreshing.
  if (savedAuth(storage,origin)?.refresh_token!==auth.refresh_token) throw new Error('sign-in');
  auth={...auth,access_token:fresh.access_token,expires_in:fresh.expires_in,expires:now+fresh.expires_in*1000};
  storage.setItem('hassTokens',JSON.stringify(auth));
  return auth.access_token;
}


const clean = v => typeof v==='string' ? v.trim().slice(0,24) : '';
export const flightLabel = a => clean(a.callsign)||clean(a.registration)||clean(a.hex).toUpperCase();
// Airline callsigns read as published flight numbers ("UAL0696" -> "UA 696");
// registrations, charter and military callsigns stay as broadcast.
export function flightNumber(callsign,designators) {
  const call=clean(callsign).toUpperCase(),match=/^([A-Z]{3})0*([1-9][0-9]{0,3})$/.exec(call);
  return match&&designators[match[1]]?`${designators[match[1]]} ${match[2]}`:call;
}
// Designator to display name; unknown codes stay visible and ZZZZ means "no designator".
export const typeName = (code,types) => {
  const value=clean(code).toUpperCase();
  return value==='ZZZZ' ? '' : types[value]||value;
};
// Map icon shape and size: the designator's icon, else the ADS-B emitter category.
const WAKE_SIZE={L:.86,LM:.93,M:1,H:1.22,J:1.36};
const CATEGORY_ICONS={A1:'single.L',A2:'jet.L',A3:'airliner.M',A4:'airliner.M',A5:'widebody.H',A6:'fighter.M',
  A7:'helicopter.L',B1:'glider.L',B2:'balloon.L',B4:'single.L',B6:'helicopter.L'};
export function iconIndex(groups) {
  const index=new Map();
  for(const [icon,codes] of Object.entries(groups))for(const code of codes.split(' '))index.set(code,icon);
  return index;
}
export function aircraftIcon(a,index) {
  const icon=index.get(clean(a.aircraft_type).toUpperCase())||CATEGORY_ICONS[clean(a.category).toUpperCase()]||'airliner.M';
  const [shape,wake]=icon.split('.');
  return {shape,size:WAKE_SIZE[wake]||1};
}
// Operator logo from an airline-style callsign (three letters, then a digit).
export function airlineLogo(a,logos) {
  const call=clean(a.callsign).toUpperCase(),code=call.slice(0,3);
  return /^[A-Z]{3}[0-9]/.test(call)&&logos.has(code)?code:'';
}
export function distanceMiles(home,a) {
  const r=Math.PI/180;
  const x=(a.longitude-home.longitude)*r*Math.cos((home.latitude+a.latitude)/2*r);
  const y=(a.latitude-home.latitude)*r;
  return Math.hypot(x,y)*3958.7613;
}

// Map context comes from the existing 15-NM feed, never from the alert selector.
export function airspace(states,now,connected) {
  const stamp=Number(states[IDS.feed]?.state),age=now/1000-stamp;
  const home=states[IDS.home]?.attributes;
  const radius=Math.max(1,Math.min(10,Number(states[IDS.radius]?.state)||3));
  const fresh=connected&&stamp>0&&age>=-5&&age<=15&&!!home&&coordinates(home.latitude,home.longitude);
  const raw=states[IDS.feed]?.attributes?.ac;
  const byHex=new Map();
  for(const a of fresh&&Array.isArray(raw)?raw:[]) {
    if(!a||typeof a.hex!=='string'||!(/^[a-f0-9]{6}$/i.test(a.hex))||
      !coordinates(a.lat,a.lon)||!number(a.alt_baro)||!number(a.seen_pos)||a.seen_pos<0||
      age+a.seen_pos<0||age+a.seen_pos>20)continue;
    const record={hex:a.hex.toLowerCase(),callsign:clean(a.flight),registration:clean(a.r),
      aircraft_type:clean(a.t),category:clean(a.category),latitude:a.lat,longitude:a.lon,altitude_ft:a.alt_baro,
      speed_kt:number(a.gs)&&a.gs>=0?a.gs:null,heading:number(a.track)?((a.track%360)+360)%360:null,
      position_timestamp:stamp-a.seen_pos};
    record.distance_mi=distanceMiles(home,record);
    record.inside=record.distance_mi<=radius;
    if(!byHex.has(record.hex)||byHex.get(record.hex).position_timestamp<record.position_timestamp)byHex.set(record.hex,record);
  }
  const all=[...byHex.values()].sort((a,b)=>a.distance_mi-b.distance_mi||a.hex.localeCompare(b.hex));
  return {fresh,radius,all,inside:all.filter(a=>a.inside)};
}

export function recentSightings(states,inside,now) {
  const raw=states[IDS.candidate]?.attributes?.history;
  const current=new Set(inside.map(a=>a.hex));
  const unique=new Map();
  for(const a of Array.isArray(raw)?raw:[]) {
    if(!a||typeof a.hex!=='string'||!(/^[a-f0-9]{6}$/i.test(a.hex))||current.has(a.hex.toLowerCase())||
      !number(a.last_seen)||a.last_seen<=0||a.last_seen>now/1000+5)continue;
    const h=a.hex.toLowerCase();
    if(!unique.has(h)||unique.get(h).last_seen<a.last_seen)unique.set(h,{...a,hex:h,
      callsign:clean(a.callsign),registration:clean(a.registration)});
  }
  return [...unique.values()].sort((a,b)=>b.last_seen-a.last_seen||a.hex.localeCompare(b.hex)).slice(0,5);
}

// Nearby planes get first choice; use the actual card size and distance to its
// nearest edge. Search all sides so a left/above card is not penalized by width.
export function placeLabels(points,width,height,scale=1) {
  const boxes=[{x:width/2-24*scale,y:height/2-6*scale,w:48*scale,h:30*scale}],
    icons=points.map(p=>({x:p.x-12*scale,y:p.y-12*scale,w:24*scale,h:24*scale}));
  const overlap=(a,b)=>Math.max(0,Math.min(a.x+a.w,b.x+b.w)-Math.max(a.x,b.x))*
    Math.max(0,Math.min(a.y+a.h,b.y+b.h)-Math.max(a.y,b.y));
  return points.map(p=>{
    const w=Math.min((p.labelWidth||128)*scale,width-8*scale),
      h=(p.labelHeight||46)*scale,gap=14*scale;
    let best=null;
    const candidates=[];
    // Fine offsets let cards stack closely; cardinal and corner placements
    // provide space above/below a cluster as well as to either side.
    for(let step=0;step<=14;step++){
      const shift=step*12*scale;
      for(const sign of step?[1,-1]:[1]){
        candidates.push([gap,-h/2+sign*shift],[-w-gap,-h/2+sign*shift],
          [-w/2+sign*shift,-h-gap],[-w/2+sign*shift,gap]);
      }
      for(const side of [1,-1])for(const vertical of [1,-1])
        candidates.push([side>0?gap+shift:-w-gap-shift,vertical>0?gap:-h-gap]);
    }
    for(const [dx,dy] of candidates) {
      const box={x:Math.max(4*scale,Math.min(width-w-4*scale,p.x+dx)),
        y:Math.max(25*scale,Math.min(height-h-24*scale,p.y+dy)),w,h};
      const padded={x:box.x-2*scale,y:box.y-2*scale,w:w+4*scale,h:h+4*scale};
      const collision=[...boxes,...icons].reduce((sum,b)=>sum+overlap(padded,b),0);
      const edgeDistance=Math.hypot(Math.max(box.x-p.x,0,p.x-box.x-w),Math.max(box.y-p.y,0,p.y-box.y-h));
      const centerDistance=Math.hypot(box.x+w/2-p.x,box.y+h/2-p.y);
      const score=collision*100+edgeDistance+centerDistance*.05;
      if(!best||score<best.score)best={...box,score};
    }
    boxes.push(best);
    return {...p,box:best};
  });
}
