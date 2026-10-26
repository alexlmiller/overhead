import test from 'node:test';
import assert from 'node:assert/strict';
import {IDS,PAGE_PATH,TV_FEED,TV_FINISHED,applyEntities,observation,mapGeometry,project,ReturnGate,readFeed,finishSession,savedAuth,accessToken,localClock,airspace,recentSightings,flightLabel,placeLabels}
  from '../web/core.mjs';

const NOW=1800000000000;
test('the clock uses HA timezone even when the browser timezone differs',()=>{
  const now=Date.parse('2026-09-24T18:00:00Z');
  assert.equal(localClock(now,'America/Denver').time,'12:00 PM');
  assert.equal(localClock(now,'America/Los_Angeles').time,'11:00 AM');
  assert.equal(localClock(now,null).time,'—');
  assert.equal(localClock(now,'invalid-zone').time,'—');
});
function states(){return {
  [IDS.current]:{state:'a12345',attributes:{feed_fresh:true,aircraft:{hex:'a12345',
    latitude:40,longitude:-100,altitude_ft:8000,distance_mi:2,position_timestamp:NOW/1000-2}}},
  [IDS.candidate]:{state:'none'},[IDS.feed]:{state:String(NOW/1000-1)},[IDS.session]:{state:'Automatic'},
  [IDS.alerts]:{state:'on'},[IDS.house]:{state:'Home'},[IDS.remote]:{state:'on'},
  [IDS.player]:{attributes:{app_id:'com.phlox.tvwebbrowser'}},
};}

test('snapshot, attribute deltas and removal do not retain a departed plane',()=>{
  let s=applyEntities({}, {a:{[IDS.current]:{s:'abc123',a:{aircraft:{hex:'abc123'},feed_fresh:true}},
    'sensor.unrelated':{s:'private',a:{}}}});
  assert.equal(s['sensor.unrelated'],undefined);
  s=applyEntities(s,{c:{[IDS.current]:{'+':{s:'none'},'-':{a:['aircraft']}}}});
  assert.deepEqual(s[IDS.current],{state:'none',attributes:{feed_fresh:true}});
  assert.deepEqual(applyEntities(s,{r:[IDS.current]}),{});
});

test('fresh observations render; stale/future/malformed positions never render as live',()=>{
  assert.ok(observation(states(),NOW,true).aircraft);
  assert.equal(observation(states(),NOW,false).aircraft,null);
  assert.equal(observation(states(),NOW+16000,true).aircraft,null);
  for(const patch of [{position_timestamp:NOW/1000+2},{latitude:NaN},{longitude:200},
    {altitude_ft:'ground'},{distance_mi:-1},{hex:'<script>'}]){
    const s=states();Object.assign(s[IDS.current].attributes.aircraft,patch);
    assert.equal(observation(s,NOW,true).aircraft,null);
  }
  const s=states();s[IDS.current].attributes.aircraft.position_timestamp=NOW/1000-21;
  assert.equal(observation(s,NOW,true).aircraft,null);
});

test('Mercator center is stable and full exit radius fits the short screen edge',()=>{
  const home={latitude:45.6,longitude:-110.7};
  for(const [width,height,radius] of [[1100,780,3],[700,400,10],[1920,1080,1]]){
    const g=mapGeometry(home,radius,width,height),p=project(home.latitude,home.longitude,g.zoom);
    assert.equal(p.x-g.left,width/2);assert.equal(p.y-g.top,height/2);
    assert.ok(g.outerPx<Math.min(width,height)/2);
    assert.ok(g.radiusPx>0&&g.radiusPx<g.outerPx);
  }
});

function gateArgs(){const s=states();s[IDS.current].state='none';return {
  now:NOW,states:s,connected:true,visible:true,path:PAGE_PATH,search:'?office_tv=1',demo:false,
};}

test('only the visible automatic TV page returns to art after 15 seconds',()=>{
  const gate=new ReturnGate(),a=gateArgs();
  assert.equal(gate.tick(a),false);
  assert.equal(gate.tick({...a,now:NOW+14999}),false);
  assert.equal(gate.tick({...a,now:NOW+15000}),true);
  assert.equal(gate.tick({...a,now:NOW+16000}),false);
  assert.equal(gate.tick({...a,now:NOW+20000}),true);
});

test('navigation, demo, hide, disconnect, manual and house/TV overrides cancel the timer',()=>{
  const overrides=[{demo:true},{visible:false},{connected:false},{path:'/other'}, {search:''}];
  for(const [id,value] of [[IDS.session,'Manual'],[IDS.alerts,'off'],[IDS.house,'Sleep'],[IDS.remote,'off'],[IDS.current,'abcdef']]){
    const s=gateArgs().states;s[id]={...s[id],state:value};overrides.push({states:s});
  }
  const s=gateArgs().states;s[IDS.player].attributes.app_id='com.vt.arttv.artmode';overrides.push({states:s});
  for(const override of overrides){
    const gate=new ReturnGate(),a=gateArgs();gate.tick(a);
    assert.equal(gate.tick({...a,...override,now:NOW+15000}),false);
    assert.equal(gate.tick({...a,now:NOW+16000}),false,'return must start a new grace period');
  }
});

const ORIGIN='https://ha.example.test';
function storage(token){let value=JSON.stringify(token);return {getItem:()=>value,setItem:(_key,v)=>{value=v;}};}
const token=()=>({hassUrl:ORIGIN,clientId:ORIGIN+'/',expires:NOW+60000,
  refresh_token:'synthetic-refresh',access_token:'synthetic-access',expires_in:60});

test('auth stays same-origin and an unexpired cached login needs no HTTP request',async()=>{
  const s=storage(token());
  assert.ok(savedAuth(s,ORIGIN));assert.equal(savedAuth(s,'https://other.example.test'),null);
  assert.equal(await accessToken(s,ORIGIN,()=>assert.fail('unexpected request'),NOW),'synthetic-access');
  await assert.rejects(accessToken(storage(null),ORIGIN,()=>assert.fail(),NOW),/sign-in/);
});

test('refresh posts only to the local token endpoint and preserves refresh credentials',async()=>{
  const s=storage({...token(),expires:0});let calls=0;
  const result=await accessToken(s,ORIGIN,async(url,options)=>{
    calls++;assert.equal(url,'/auth/token');assert.equal(options.method,'POST');
    assert.equal(options.body.get('refresh_token'),'synthetic-refresh');
    assert.equal(options.body.get('client_id'),ORIGIN+'/');
    return {ok:true,json:async()=>({access_token:'synthetic-new',expires_in:1800})};
  },NOW);
  assert.equal(calls,1);assert.equal(result,'synthetic-new');
  assert.equal(savedAuth(s,ORIGIN).refresh_token,'synthetic-refresh');
  assert.equal(savedAuth(s,ORIGIN).expires,NOW+1800000);
});

test('a concurrent logout is not undone by an in-flight refresh',async()=>{
  const s=storage({...token(),expires:0});
  await assert.rejects(accessToken(s,ORIGIN,async()=>{
    s.setItem('hassTokens','null');
    return {ok:true,json:async()=>({access_token:'synthetic-new',expires_in:1800})};
  },NOW),/sign-in/);
  assert.equal(savedAuth(s,ORIGIN),null);
});

test('denied refresh requires sign-in; a server outage does not erase saved auth',async()=>{
  for(const status of [400,403,500]){
    const s=storage({...token(),expires:0});
    await assert.rejects(accessToken(s,ORIGIN,async()=>({ok:false,status}),NOW),status===500?/connection/:/sign-in/);
    assert.ok(savedAuth(s,ORIGIN));
  }
});

// Execute a fresh copy of the real entry module with a small browser fixture.
// Opening a WebSocket fails the test and reading saved auth throws; `fetcher` is
// the page's only way out. Interval callbacks are returned, not scheduled.
let pageRuns=0;
async function runPage(search,fetcher){
  const elements=new Map();
  const element=id=>{
    if(!elements.has(id))elements.set(id,{textContent:'',innerHTML:'',style:{},hidden:false,children:[],
      setAttribute(){},getBoundingClientRect:()=>({width:1100,height:780}),
      append(...nodes){this.children.push(...nodes);},replaceChildren(...nodes){this.children=nodes;}});
    return elements.get(id);
  };
  globalThis.document={getElementById:element,createElement:()=>element(Symbol()),createElementNS:()=>element(Symbol()),visibilityState:'visible',addEventListener(){}};
  const listeners={};
  globalThis.window={addEventListener(type,listener){listeners[type]=listener;}};
  globalThis.location={search,pathname:PAGE_PATH};
  globalThis.ResizeObserver=class{observe(){}};
  globalThis.Image=class{style={};dataset={};addEventListener(){}remove(){}};
  const originalInterval=globalThis.setInterval,intervals=[];
  globalThis.setInterval=callback=>{intervals.push(callback);return 0;};
  const guard=()=>assert.fail('the page crossed the Home Assistant login boundary');
  globalThis.WebSocket=class{constructor(){guard();}};
  globalThis.fetch=fetcher;
  Object.defineProperty(globalThis,'localStorage',{get:guard,configurable:true});
  try{
    await import(`../web/display.mjs?run=${++pageRuns}`);
    await settle();
  }finally{globalThis.setInterval=originalInterval;}
  // close() is pagehide: it stops polls and login retries so a failure cannot hang the run.
  return {element,tick:intervals[0],close:()=>listeners.pagehide?.()};
}
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));

test('demo cannot create a Home Assistant connection even on an authenticated origin',async()=>{
  const {element}=await runPage('?demo=1&office_tv=1',()=>assert.fail('demo made an HTTP request'));
  assert.equal(element('nearby-count').textContent,'2');
  assert.equal(element('recent-list').children.length,5);
  assert.equal(element('nearby-list').children.length,2);
  assert.equal(element('nearby-empty').hidden,true);
  assert.equal(element('session-caption').textContent,'SIMULATED AIRCRAFT & ROUTES');
});

const reply=(calls,status,body)=>async(url,options)=>{
  calls.push([url,options]);return {ok:status>=200&&status<300,status,json:async()=>body};
};
test('the TV feed keeps only page entities and reports refusal separately',async()=>{
  const calls=[],request={headers:{'X-Office-TV':'1'},credentials:'omit',cache:'no-store'};
  const feed=await readFeed(reply(calls,200,{time_zone:'America/Denver',states:{
    [IDS.house]:{state:'Home',attributes:{}},[IDS.remote]:{state:7},'lock.front_door':{state:'unlocked'}}}));
  assert.deepEqual(feed,{states:{[IDS.house]:{state:'Home',attributes:{}}},timeZone:'America/Denver'});
  assert.deepEqual(calls,[[TV_FEED,request]]);
  assert.deepEqual(await readFeed(reply(calls,403,null)),{denied:true});
  for(const [status,body] of [[500,{}],[404,null],[200,null],[200,{states:'Home'}]])
    await assert.rejects(readFeed(reply(calls,status,body)),/connection/);
  await finishSession(reply(calls,202,{}));
  assert.deepEqual(calls.at(-1),[TV_FINISHED,{...request,method:'POST'}]);
});

test('the office TV shows live aircraft from its feed without a saved HA login',async t=>{
  const calls=[],now=Date.now()/1000;
  const plane=(hex,miles)=>({hex,flight:'UAL123',r:'N123UA',t:'B738',lat:40+miles/(3958.7613*Math.PI/180),lon:-100,alt_baro:10000,seen_pos:1,track:90});
  const {element,close}=await runPage('?office_tv=1&t=1800000000',reply(calls,200,{time_zone:'America/Denver',states:{
    [IDS.home]:{state:'0',attributes:{latitude:40,longitude:-100}},[IDS.radius]:{state:'3',attributes:{}},
    [IDS.feed]:{state:String(now-1),attributes:{ac:[plane('aaaaaa',1),plane('bbbbbb',2),plane('cccccc',4)]}},
    [IDS.current]:{state:'none',attributes:{}},[IDS.candidate]:{state:'none',attributes:{history:[]}}}}));
  t.after(close);
  assert.deepEqual(calls.map(([url,options])=>[url,options.method,options.headers,options.credentials]),
    [[TV_FEED,undefined,{'X-Office-TV':'1'},'omit']]);
  assert.equal(element('signal-text').textContent,'LIVE');
  assert.equal(element('nearby-count').textContent,'2');
  assert.equal(element('sign-in').hidden,true);
  assert.notEqual(element('clock').textContent,'—');
});

test('a refused office TV says so and never falls back to an HA login',async t=>{
  const {element,close}=await runPage('?office_tv=1',reply([],403,{message:'Forbidden'}));t.after(close);
  assert.equal(element('signal-text').textContent,'NO ACCESS');
  assert.equal(element('nearby-empty').textContent,'This screen is not allowed to read live aircraft.');
  assert.equal(element('sign-in').hidden,true);
});

test('the automatic office TV asks the feed endpoint, not a WebSocket, to return to Art',async t=>{
  const realNow=Date.now;let clock=realNow();Date.now=()=>clock;
  try{
    const calls=[];
    const {tick,close}=await runPage('?office_tv=1',async(url,options)=>{
      calls.push([url,options.method]);
      const s={...states(),[IDS.current]:{state:'none'},[IDS.feed]:{state:String(clock/1000-1)},
        [IDS.player]:{state:'on',attributes:{app_id:'com.phlox.tvwebbrowser'}}};
      return {ok:true,status:200,json:async()=>({time_zone:'America/Denver',states:s})};
    });
    t.after(close);
    for(let i=0;i<8;i++){clock+=2000;tick();await settle();}
    assert.deepEqual(calls.filter(([url])=>url!==TV_FEED),[[TV_FINISHED,'POST']]);
    assert.ok(calls.filter(([url])=>url===TV_FEED).length>=8,'the feed is polled every other second');
  }finally{Date.now=realNow;}
});

function trafficState(){
  const s=states();s[IDS.home]={attributes:{latitude:40,longitude:-100}};s[IDS.radius]={state:'3'};
  const plane=(hex,miles)=>({hex,flight:'UAL123',r:'N123UA',lat:40+miles/(3958.7613*Math.PI/180),lon:-100,alt_baro:10000,seen_pos:1,track:90});
  s[IDS.feed].attributes={ac:[plane('aaaaaa',1),plane('bbbbbb',2),plane('cccccc',4)]};return s;
}
test('all nearby aircraft render together, while background stays outside the boundary',()=>{
  const s=trafficState(),a=airspace(s,NOW,true);
  assert.equal(a.all.length,3);assert.deepEqual(a.inside.map(a=>a.hex),['aaaaaa','bbbbbb']);
  assert.equal(a.all[2].inside,false);assert.equal(a.fresh,true);
  assert.equal(airspace(s,NOW,false).all.length,0);assert.equal(airspace(s,NOW+21000,true).all.length,0);
  s[IDS.feed].attributes.ac.push({...s[IDS.feed].attributes.ac[0],seen_pos:8});
  assert.equal(airspace(s,NOW,true).all.length,3);
});
test('missing, stale, malformed and future feed positions are excluded individually',()=>{
  for(const patch of [{lat:91},{alt_baro:'ground'},{seen_pos:60},{seen_pos:-1},{hex:'<html>'}]){
    const s=trafficState();s[IDS.feed].attributes.ac=[{...s[IDS.feed].attributes.ac[0],...patch}];
    assert.equal(airspace(s,NOW,true).all.length,0);
  }
  const s=trafficState();s[IDS.feed].state=String(NOW/1000+10);assert.equal(airspace(s,NOW,true).all.length,0);
  s[IDS.feed].attributes.ac='invalid';assert.equal(airspace(s,NOW,true).all.length,0);
  assert.equal(flightLabel({callsign:'',registration:'N12345',hex:'abcdef'}),'N12345');
});
test('recent list has five unique visitors, excludes current traffic and orders by last seen',()=>{
  const s=trafficState(),active=airspace(s,NOW,true).inside;
  s[IDS.candidate]={attributes:{history:[...active.map(a=>({...a,last_seen:NOW/1000})),
    ...Array.from({length:8},(_,i)=>({hex:`a0000${i}`,last_seen:NOW/1000-60*(i+1),callsign:`UAL${i}`})),
    {hex:'a00000',last_seen:NOW/1000-500},{hex:'aaaaaa',last_seen:NOW/1000+100}]}};
  const recent=recentSightings(s,active,NOW);
  assert.equal(recent.length,5);assert.equal(recent[0].hex,'a00000');assert.equal(recent[4].hex,'a00004');
});
test('second aircraft prevents automatic return; background alone does not',()=>{
  const args=gateArgs(),s=trafficState();s[IDS.current].state='none';args.states=s;
  const gate=new ReturnGate();assert.equal(gate.tick(args),false);
  s[IDS.feed].state=String(NOW/1000+14);
  assert.equal(gate.tick({...args,now:NOW+15000}),false);
  s[IDS.feed].attributes.ac=s[IDS.feed].attributes.ac.slice(2);
  assert.equal(gate.tick({...args,now:NOW+16000}),false);
  s[IDS.feed].state=String(NOW/1000+30);
  assert.equal(gate.tick({...args,now:NOW+31000}),true);
  const candidate=gateArgs();candidate.states[IDS.candidate].state='aaaaaa';
  assert.equal(new ReturnGate().tick(candidate),false);
});
test('clustered map labels are kept inside viewport and avoid each other',()=>{
  const labels=placeLabels([{x:100,y:100,inside:true},{x:103,y:100,inside:true},{x:565,y:410}],570,430);
  for(const {box:b} of labels){assert.ok(b.x>=0&&b.y>=0&&b.x+b.w<=570&&b.y+b.h<=430);}
  const [a,b]=labels.map(p=>p.box);
  assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
});

test('a close pair can use opposite sides without long leader lines',()=>{
  const labels=placeLabels([{x:240,y:120,labelWidth:100,labelHeight:46},
    {x:243,y:120,labelWidth:80,labelHeight:33}],570,430);
  for(const p of labels){
    const b=p.box;
    const leader=Math.hypot(Math.max(b.x-p.x,0,p.x-b.x-b.w),Math.max(b.y-p.y,0,p.y-b.y-b.h));
    assert.ok(leader<=20,`leader length ${leader}`);
  }
  const [a,b]=labels.map(p=>p.box);
  assert.ok(a.x+a.w<=b.x||b.x+b.w<=a.x||a.y+a.h<=b.y||b.y+b.h<=a.y);
  assert.equal(b.h,33);
});
