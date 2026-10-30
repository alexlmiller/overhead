import {AIRPORT_CITIES} from './airport-cities.mjs?v=5204ef039b';
import {IDS,ENTITY_IDS,PAGE_PATH,number,coordinates,applyEntities,project,mapGeometry,ReturnGate,readFeed,finishSession,accessToken,localClock,airspace,recentSightings,flightLabel,flightNumber,placeLabels,typeName,iconIndex,aircraftIcon,airlineLogo} from './core.mjs?v=68b20f4b01';
import {RouteLookup,routeText,routeLabels} from './routes.mjs?v=50679358e7';
import {AIRCRAFT_TYPES,AIRCRAFT_ICONS} from './aircraft-types.mjs?v=90a7932222';
import {AIRLINE_LOGOS,AIRLINE_DESIGNATORS} from './airlines.mjs?v=754f3a5510';

const $=id=>document.getElementById(id);
const query=new URLSearchParams(location.search),demo=query.get('demo')==='1';
// The office TV polls its own feed and never reads a saved HA login.
const tv=!demo&&query.get('office_tv')==='1';
const scene=demo?query.get('scene'):null,gate=new ReturnGate();
const routes=new RouteLookup();
const routeStyle=['cities','codes','both'].includes(query.get('route_style'))?query.get('route_style'):'both';
const labels=r=>routeLabels(r,AIRPORT_CITIES,routeStyle);
let states={},connected=false,lastMessage=0,needsLogin=false,denied=false,polling=null,lastPoll=0;
let socket=null,retry=null,attempt=0,sequence=0,subscription=0,authRetry=false,connecting=false,connectAbort=null;
let configRequest=0,homeTimeZone=demo?Intl.DateTimeFormat().resolvedOptions().timeZone:null;
let geometry=null,mapKey='',visiblePlanes=[];
const tileNodes=new Map(),trails=new Map();
const labelMeasure=document.createElement('canvas').getContext?.('2d');
const aircraftType=a=>typeName(a.aircraft_type,AIRCRAFT_TYPES);
const icons=iconIndex(AIRCRAFT_ICONS),logos=new Set(AIRLINE_LOGOS);
const setText=(id,value)=>{const el=$(id);if(el.textContent!==value)el.textContent=value;};
const integer=v=>number(v)?Math.round(v).toLocaleString('en-US'):'—';
const element=(tag,cls,text)=>{const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;};
// Flight name with the operator's logo, when one is bundled for its callsign.
const nameNode=(a,cls)=>{
  const el=element('span',cls),logo=airlineLogo(a,logos);
  if(logo){const img=element('img','airline-logo');img.src=`logos/${logo}.png`;img.alt='';el.append(img);}
  el.append(flightName(a));return el;
};
const svg=(tag,attrs={},text)=>{const el=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v] of Object.entries(attrs))el.setAttribute(k,v);if(text!==undefined)el.textContent=text;return el;};
const flightName=a=>flightNumber(routes.get(a)?.flight||flightLabel(a),AIRLINE_DESIGNATORS);
const ago=(stamp,now)=>{const mins=Math.max(0,Math.floor((now/1000-stamp)/60));return mins<1?'just now':mins<60?`${mins}m ago`:mins<1440?`${Math.floor(mins/60)}h ago`:`${Math.floor(mins/1440)}d ago`;};

function drawMap(){
  if(document.visibilityState!=='visible')return;
  const home=states[IDS.home]?.attributes;
  if(!home||!coordinates(home.latitude,home.longitude))return;
  const radius=Math.max(1,Math.min(10,Number(states[IDS.radius]?.state)||3));
  const {width,height}=$('map').getBoundingClientRect();
  if(!width||!height)return;
  geometry={...mapGeometry(home,radius,width,height),width,height};
  const {zoom,left,top,cx,cy,radiusPx}=geometry;
  const key=[width,height,home.latitude,home.longitude,radius].join('/');
  if(mapKey===key)return;
  mapKey=key;
  const scale=Math.max(.8,width/570);
  $('map-overlay').setAttribute('viewBox',`0 0 ${width} ${height}`);
  $('map-geography').replaceChildren(svg('circle',{class:'ring',cx,cy,r:radiusPx}),
    svg('circle',{class:'home-dot',cx,cy,r:4*scale}),
    svg('text',{class:'home-label',x:cx,y:cy+18*scale,'text-anchor':'middle','font-size':9*scale},'HOME'));
  setText('radius-caption',`${radius} MI ALERT BOUNDARY`);
  const wanted=new Set();
  for(let y=Math.floor(top/256);y<=Math.floor((top+height)/256);y++)for(let x=Math.floor(left/256);x<=Math.floor((left+width)/256);x++){
    if(y<0||y>=2**zoom)continue;
    const wrapped=((x%2**zoom)+2**zoom)%2**zoom,tileKey=`${zoom}/${wrapped}/${y}`;
    wanted.add(tileKey);let img=tileNodes.get(tileKey);
    if(!img){
      img=new Image();img.alt='';img.decoding='async';
      img.addEventListener('load',()=>{img.dataset.loaded='true';tileStatus();});
      img.addEventListener('error',()=>{img.dataset.failed='true';tileStatus();});
      img.src=`https://tile.openstreetmap.org/${tileKey}.png`;
      tileNodes.set(tileKey,img);$('tiles').append(img);
    }
    img.style.left=`${x*256-left}px`;img.style.top=`${y*256-top}px`;
  }
  for(const [key,img] of tileNodes)if(!wanted.has(key)){img.remove();tileNodes.delete(key);}
  tileStatus();
}
function tileStatus(){ $('map-note').hidden=![...tileNodes.values()].some(img=>img.dataset.failed); }

function drawPlanes(all,now){
  visiblePlanes=[];
  if(!geometry)return;
  const {width,height}=geometry,scale=Math.max(.8,width/570);
  const point=a=>{const p=project(a.latitude,a.longitude,geometry.zoom);return {x:p.x-geometry.left,y:p.y-geometry.top};};
  const present=new Set(all.map(a=>a.hex));
  for(const h of trails.keys())if(!present.has(h))trails.delete(h);
  const trackNodes=[],planeNodes=[],labelNodes=[];
  const points=all.map(a=>({...a,...point(a)})).filter(p=>p.x>=0&&p.x<=width&&p.y>=0&&p.y<=height)
    .sort((a,b)=>Number(b.inside)-Number(a.inside)||a.distance_mi-b.distance_mi);
  visiblePlanes=points;
  for(const a of points){
    let trail=trails.get(a.hex)||[];
    if(!trail.length||a.position_timestamp>trail[trail.length-1].position_timestamp)trail.push(a);
    trail=trail.filter(p=>now/1000-p.position_timestamp<=120).slice(-30);trails.set(a.hex,trail);
    const d=trail.map((p,i)=>{const q=point(p);return `${i?'L':'M'}${q.x.toFixed(2)},${q.y.toFixed(2)}`;}).join(' ');
    trackNodes.push(svg('path',{class:`track${a.inside?'':' context'}`,d}));
    // Silhouette by aircraft class, sized by wake category (light singles to super-heavies).
    const {shape,size:wake}=aircraftIcon(a,icons),size=(a.inside?26:16)*scale*wake;
    const icon=svg('g',{class:`aircraft${a.inside?'':' context'}`,transform:`translate(${a.x} ${a.y}) rotate(${a.heading||0})`});
    icon.append(number(a.heading)?svg('use',{href:`#ac-${shape}`,x:-size/2,y:-size/2,width:size,height:size}):svg('circle',{r:4*scale}));
    planeNodes.push(icon);
  }
  const labelPoints=points.map(a=>{
    const route=routes.get(a),type=aircraftType(a)||'Type unavailable',logo=airlineLogo(a,logos);
    const lines=[flightName(a),type,routeText(route)].filter(Boolean);
    const widths=lines.map((line,i)=>{
      const indent=!i&&logo?14:0;
      if(!labelMeasure)return line.length*(i?4.7:6.2)+indent;
      labelMeasure.font=`${i?'400 9':'500 11'}px DM`;return labelMeasure.measureText(line).width+indent;
    });
    return {...a,route,type,logo,lines,labelWidth:Math.max(76,Math.max(...widths)+14),labelHeight:route?46:33};
  });
  for(const a of placeLabels(labelPoints,width,height,scale)){
    const b=a.box,cls=`map-tag${a.inside?'':' context'}`,{route,type,lines,logo}=a;
    const tag=svg('g',{class:cls,transform:`translate(${b.x} ${b.y})`});
    tag.append(svg('rect',{width:b.w,height:b.h,rx:2*scale}),
      svg('text',{x:(logo?20:7)*scale,y:13*scale,style:`font-size:${11*scale}px`},flightName(a)),
      svg('text',{x:7*scale,y:25*scale,class:'tag-type tag-route',style:`font-size:${9*scale}px`},type));
    if(logo)tag.append(svg('image',{href:`logos/${logo}.png`,x:6*scale,y:3.5*scale,width:11*scale,height:11*scale}));
    if(route)tag.append(svg('text',{x:7*scale,y:38*scale,class:'tag-route',style:`font-size:${9*scale}px`},routeText(route)));
    tag.append(svg('title',{},`${lines.join(' · ')}${route?' (reported route)':''}`));
    labelNodes.push(svg('line',{class:'leader',x1:a.x,y1:a.y,x2:Math.max(b.x,Math.min(b.x+b.w,a.x)),y2:Math.max(b.y,Math.min(b.y+b.h,a.y))}),tag);
  }
  $('map-tracks').replaceChildren(...trackNodes);
  $('map-planes').replaceChildren(...planeNodes);
  $('map-labels').replaceChildren(...labelNodes);
}

function routeNode(a,cls){
  const route=routes.get(a),el=element('span',cls);
  if(route){
    const {primary,secondary}=labels(route);
    el.append(element('span','route-cities',primary));
    if(secondary)el.append(element('small','route-codes',secondary));
    el.title=`${primary} (${routeText(route)}). Reported route; actual origin and destination may differ.`;
  }
  else el.hidden=true;
  return el;
}
function drawLists(inside,recent,now,fresh){
  // Two flight summaries stay visible without shrinking the history. Busier
  // airspace pages every 8s; every aircraft remains on the map at all times.
  const pages=Math.ceil(inside.length/2),page=pages?Math.floor((now-demoStarted)/8000)%pages:0;
  const cards=inside.slice(page*2,page*2+2).map(a=>{
    const card=element('article','flight-card'),identity=element('div','flight-identity');
    const distance=element('span','flight-distance',a.distance_mi.toFixed(1));distance.append(element('small','','mi'));
    identity.append(nameNode(a,'flight-name'),distance);
    const route=routeNode(a,'flight-route');
    const meta=[aircraftType(a),a.registration].filter(Boolean).join(' · ')||'Aircraft details unavailable';
    const stats=element('div','flight-stats');
    for(const [value,unit] of [[integer(a.altitude_ft),'ft MSL'],[integer(a.speed_kt),'kt'],[number(a.heading)?`${Math.round(a.heading)%360}°`:'—','']]){
      const valueNode=element('span','',value);if(unit)valueNode.append(element('small','',unit));stats.append(valueNode);
    }
    stats.append(element('span','flight-age',`${Math.max(0,Math.floor(now/1000-a.position_timestamp))}s ago`));
    card.append(identity,route,element('div','flight-meta',meta),stats);return card;
  });
  $('nearby-list').replaceChildren(...cards);
  setText('nearby-count',String(inside.length));$('page-count').hidden=pages<=1;
  setText('page-count',`${page+1} / ${pages}`);$('nearby-empty').hidden=inside.length>0;
  setText('nearby-empty',fresh?'No aircraft above us right now.':needsLogin?'Sign in to see live aircraft.':
    denied?'This screen is not allowed to read live aircraft.':'Waiting for fresh positions…');
  $('recent-list').replaceChildren(...recent.map(a=>{
    const row=element('div','recent-row'),identity=element('div','recent-identity');
    const type=aircraftType(a);
    identity.append(nameNode(a,'recent-name'));
    if(type)identity.append(element('span','recent-type',type));
    row.append(identity,
      routeNode(a,'recent-route'),element('span','recent-time',ago(a.last_seen,now)));return row;
  }));
  $('recent-empty').hidden=recent.length>0;
  setText('recent-empty',Array.isArray(states[IDS.candidate]?.attributes?.history)?'No recent sightings.':'Waiting for sighting history…');
}

function render(){
  const now=Date.now(),healthy=connected&&now-lastMessage<15000;
  const {fresh,all,inside}=airspace(states,now,healthy),recent=recentSightings(states,inside,now);
  const clock=localClock(now,homeTimeZone);setText('clock',clock.time);setText('dateline',clock.date);
  $('edition').hidden=!demo;
  $('signal').className=`signal ${demo?'demo':fresh?'live':''}`;
  setText('signal-text',demo?'PREVIEW':fresh?'LIVE':needsLogin?'SIGN IN':denied?'NO ACCESS':'OFFLINE');
  $('sign-in').hidden=!needsLogin;
  if(!demo)routes.update(states[IDS.routes]?.attributes?.routes);
  drawMap();drawPlanes(all,now);drawLists(inside,recent,now,fresh);
  setText('session-caption',demo?'SIMULATED AIRCRAFT & ROUTES':!fresh?'POSITIONS UNAVAILABLE':`${inside.length} NEARBY · ${visiblePlanes.filter(a=>!a.inside).length} SURROUNDING`);
  if(gate.tick({now,states,connected:healthy,visible:document.visibilityState==='visible',path:location.pathname,search:location.search,demo})){
    if(tv)finishSession(fetch).catch(()=>{});
    else send({type:'call_service',domain:'script',service:'office_tv_aircraft_finished'});
  }
}
function send(message){
  if(!socket||socket.readyState!==WebSocket.OPEN)return 0;
  const id=++sequence;socket.send(JSON.stringify({id,...message}));return id;
}

// Office TV: one feed request at a time, every other tick of the 1s clock. A
// failed poll keeps the last frame, which shows OFFLINE after 15s.
async function poll(){
  if(polling||document.visibilityState!=='visible')return;
  const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),8000);
  polling=controller;lastPoll=Date.now();
  try{
    const feed=await readFeed((url,options)=>fetch(url,{...options,signal:controller.signal}));
    if(polling===controller){
      denied=!!feed.denied;connected=!denied;
      if(denied)states={};else{states=feed.states;homeTimeZone=feed.timeZone;lastMessage=Date.now();}
    }
  }catch{/* Retried on the next tick. */}
  finally{clearTimeout(timeout);}
  if(polling!==controller)return;
  polling=null;render();
}

async function connect(force=false){
  if(tv){poll();return;}
  if(demo||connecting||socket||document.visibilityState!=='visible')return;
  connecting=true;needsLogin=false;connectAbort=new AbortController();
  const controller=connectAbort;
  const refreshTimeout=setTimeout(()=>controller.abort(),10000);
  try{
    const fetcher=(url,options)=>fetch(url,{...options,signal:controller.signal});
    const token=await accessToken(localStorage,location.origin,fetcher,Date.now(),force);
    clearTimeout(refreshTimeout);
    if(controller.signal.aborted||document.visibilityState!=='visible')return;
    states={};connected=false;lastMessage=0;
    const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/websocket`);
    socket=ws;sequence=0;subscription=0;
    const handshake=setTimeout(()=>ws.close(),10000);
    ws.onmessage=event=>{
      if(socket!==ws)return;
      let msg;try{msg=JSON.parse(event.data);}catch{ws.close();return;}
      lastMessage=Date.now();
      if(msg.type==='auth_required')ws.send(JSON.stringify({type:'auth',access_token:token}));
      else if(msg.type==='auth_ok'){
        clearTimeout(handshake);connected=true;attempt=0;authRetry=false;
        subscription=send({type:'subscribe_entities',entity_ids:ENTITY_IDS});
        configRequest=send({type:'get_config'});
      }else if(msg.type==='auth_invalid'){
        clearTimeout(handshake);
        if(authRetry)needsLogin=true;else authRetry=true;
        ws.close();
      }else if(msg.type==='event'&&msg.id===subscription){states=applyEntities(states,msg.event);}
      else if(msg.type==='result'&&msg.id===configRequest&&msg.success){homeTimeZone=msg.result?.time_zone||null;}
      else if(msg.type==='result'&&msg.id===subscription&&!msg.success){ws.close();}
      render();
    };
    ws.onclose=()=>{
      clearTimeout(handshake);if(socket!==ws)return;
      socket=null;connected=false;render();schedule();
    };
    ws.onerror=()=>ws.close();
  }catch(error){
    if(connectAbort===controller&&document.visibilityState==='visible'){
      needsLogin=error.message==='sign-in';connected=false;render();schedule();
    }
  }finally{clearTimeout(refreshTimeout);if(connectAbort===controller){connecting=false;connectAbort=null;}}
}

function schedule(){
  clearTimeout(retry);
  if(needsLogin||demo||document.visibilityState!=='visible')return;
  retry=setTimeout(()=>connect(authRetry),Math.min(15000,1000*2**Math.min(attempt++,4)));
}

function disconnect(){
  clearTimeout(retry);connectAbort?.abort();polling?.abort();polling=null;connected=false;connecting=false;
  if(socket){const ws=socket;socket=null;ws.close();}
  gate.missingSince=null;
}

// Synthetic flights and routes, centered on a public city location. Never read
// auth/storage or request flight data in preview mode, even on the HA origin.
const demoStarted=Date.now();
function demoFrame(){
  if(!demo)return;
  const now=Date.now(),elapsed=(now-demoStarted)/1000;
  const home={latitude:45.679,longitude:-111.042};
  const make=(hex,flight,r,t,north,east,alt,gs,track)=>({hex,flight,r,t,
    lat:home.latitude+north/69,lon:home.longitude+east/48.2,alt_baro:alt,gs,track,seen_pos:2});
  const ac=[make('a12345','UAL647','N37267','B738',1.3,1.1+(elapsed%120)*.001,8100,204,310),
    make('a23456','N172SP','N172SP','C172',-1.5,-1.6,6500,109,75),
    make('a34567','DAL1198','N171DZ','B763',4.6,-3.2,34000,448,112),
    make('a45678','ASA905','N917AK','E75L',-3.5,4.8,21000,384,280),
    make('a56789','N80MM','N80MM','CL35',-5.2,-4.7,18000,245,15),
    make('a67890','N407LF','N407LF','B407',3.1,3.4,6200,118,205)];
  if(scene==='busy')for(let i=0;i<5;i++)ac.push(make(`b0000${i}`,`SKW${4200+i}`,'N123SK','E75L',.5+i*.25,-.1-i*.3,9000,240,180));
  if(scene==='cluster'){ac[1].lat=ac[0].lat+.001;ac[1].lon=ac[0].lon+.001;}
  if(scene==='sparse'){ac[0].flight='';ac[0].r='';ac[0].t='';ac[0].gs=null;ac[0].track=null;}
  const visible=scene==='quiet'?ac.slice(2):scene==='stale'?[]:ac;
  const history=[['a60001','ASA221','N551AS','SEA','BZN','B39M'],['a60002','DAL1723','N351DN','SLC','BZN','A321'],
    ['a60003','N734AR','N734AR',null,null,'C25B'],['a60004','UAL2171','N873UA','BZN','DEN','A319'],
    ['a60005','SWA2844','N881WN','BZN','LAS','B738']].map(([hex,callsign,registration,origin,destination,aircraft_type],i)=>{
      const a={hex,callsign,registration,aircraft_type:scene==='sparse'&&i===2?'':aircraft_type,last_seen:now/1000-(i*11+4)*60};
      if(origin)routes.seed(a,{origin,destination});return a;
    });
  routes.seed({callsign:'UAL647'},{origin:'DEN',destination:'BZN'});
  routes.seed({callsign:'DAL1198'},{origin:'MSP',destination:'SEA'});
  routes.seed({callsign:'ASA905'},{origin:'SEA',destination:'DEN'});
  if(scene==='long-routes'){
    routes.seed({callsign:'UAL647'},{origin:'DFW',destination:'SFO'});
    routes.seed({callsign:'ASA221'},{origin:'JFK',destination:'DFW'});
    routes.seed({callsign:'DAL1723'},{origin:'MSP',destination:'SFO'});
  }
  if(scene==='routes')routes.seed({callsign:'N172SP'},{origin:'BZN',destination:'BTM'});
  states={[IDS.home]:{attributes:home},[IDS.radius]:{state:'3'},[IDS.feed]:{state:String(now/1000-(scene==='stale'?90:1)),attributes:{ac:visible}},
    [IDS.current]:{state:'none'},[IDS.candidate]:{state:'none',attributes:{history}},[IDS.session]:{state:'Manual'}};
  connected=true;lastMessage=now;render();
}
new ResizeObserver(()=>render()).observe($('map'));
document.addEventListener('visibilitychange',()=>{
  if(document.visibilityState!=='visible'){disconnect();}else if(demo)demoFrame();else connect();
  render();
});
window.addEventListener('pagehide',()=>{disconnect();});
window.addEventListener('pageshow',()=>{if(!demo)connect();});
window.addEventListener('storage',event=>{if(!demo&&!tv&&event.key==='hassTokens'){disconnect();connect();}});
window.addEventListener('online',()=>{if(!demo){clearTimeout(retry);connect();}});
setInterval(()=>{
  if(document.visibilityState!=='visible')return;
  if(demo){demoFrame();return;}
  if(tv){if(Date.now()-lastPoll>=1500)poll();}
  else if(connected&&Date.now()-lastMessage>15000){disconnect();connect();}
  render();
},1000);
setInterval(()=>{if(connected&&!demo)send({type:'ping'});},5000);
if(demo)demoFrame();else{render();connect();}
