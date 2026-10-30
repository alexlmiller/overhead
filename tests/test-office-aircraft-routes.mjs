import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {RouteLookup,routeText} from '../web/routes.mjs';
const plane={hex:'aabbcc',callsign:'N207BC',registration:'N207BC',position_timestamp:1000};
const route={...plane,origin:'KDTO',destination:'BZN',flight:'N207BC',source:'FlightAware',valid_from:900,valid_until:1100,expires:2000};
test('server route matches aircraft identity and observed flight interval',()=>{
  const routes=new RouteLookup();routes.update([route]);
  assert.equal(routeText(routes.get(plane,1500000)),'KDTO → BZN');
  assert.equal(routes.get({...plane,hex:'ffffff'},1500000),null);
  assert.equal(routes.get({...plane,callsign:'UAL123'},1500000),null);
  assert.equal(routes.get({...plane,registration:'N12345'},1500000),null);
  assert.equal(routes.get({...plane,position_timestamp:1200},1500000),null);
  assert.equal(routes.get(plane,2000000),null);
  assert.equal(routes.get({...plane,position_timestamp:undefined},1500000),null);
});
test('recent sightings use the observation time, not the next flight by that tail',()=>{
  const routes=new RouteLookup();routes.update([route]);
  assert.equal(routeText(routes.get({...plane,position_timestamp:undefined,last_seen:1000},1500000)),'KDTO → BZN');
  routes.update([{...route,valid_from:1200,valid_until:1500}]);
  assert.equal(routes.get({...plane,position_timestamp:undefined,last_seen:1000},1500000),null);
});
test('missing or malformed routes remain unavailable; demo stays independent',()=>{
  const routes=new RouteLookup();routes.update(undefined);assert.equal(routeText(routes.get(plane)),'');
  routes.update([{...route,origin:'<img>'}]);assert.equal(routes.get(plane,1500000),null);
  routes.seed(plane,{origin:'KDTO',destination:'BZN'});assert.equal(routeText(routes.get(plane)),'KDTO → BZN');
});
test('archived sighting routes survive live rejection without leaking onto live aircraft',()=>{
  const routes=new RouteLookup();routes.update([{...route,historical:true}]);
  assert.equal(routes.get(plane,1500000),null);
  const recent={...plane,position_timestamp:undefined,last_seen:1000};
  assert.equal(routeText(routes.get(recent,1500000)),'KDTO → BZN');
  routes.update([{...route,origin:'BZN',destination:'SEA'},{...route,historical:true}]);
  assert.equal(routeText(routes.get(recent,1500000)),'KDTO → BZN');
  assert.equal(routeText(routes.get(plane,1500000)),'BZN → SEA');
});
test('frontend cannot query route providers or carry the provider key',()=>{
  const root=new URL('../web/',import.meta.url);
  const source=readFileSync(new URL('routes.mjs',root),'utf8');
  assert.doesNotMatch(source,/fetch\(|x-apikey|https:\/\//);
  const html=readFileSync(new URL('index.html',root),'utf8');
  assert.match(html,/connect-src 'self';/);assert.doesNotMatch(html,/api.adsbdb.com/);
});

// City labels are presentation only; provider identifiers remain untouched.
const {routeLabels}=await import('../web/routes.mjs');
test('city labels retain airport precision and unknown-code fallback',()=>{
  const cities={JFK:'New York',LGA:'New York',BZN:'Bozeman'};
  assert.deepEqual(routeLabels({origin:'JFK',destination:'LGA'},cities),{primary:'New York → New York',secondary:'JFK → LGA'});
  assert.deepEqual(routeLabels({origin:'ZZZZ',destination:'BZN'},cities,'cities'),{primary:'ZZZZ → Bozeman',secondary:''});
  assert.deepEqual(routeLabels({origin:'ZZZZ',destination:'XXXX'},cities),{primary:'ZZZZ → XXXX',secondary:''});
  assert.deepEqual(routeLabels(null,cities),{primary:'',secondary:''});
  assert.deepEqual(routeLabels({origin:'JFK',destination:'BZN'},cities,'codes'),{primary:'JFK → BZN',secondary:''});
});
const {AIRPORT_CITIES}=await import('../web/airport-cities.mjs');
test('bundled city catalog covers IATA and ICAO without conflating airport codes',()=>{
  assert.equal(AIRPORT_CITIES.BZN,'Bozeman');
  assert.equal(AIRPORT_CITIES.KBZN,'Bozeman');
  assert.equal(AIRPORT_CITIES.JFK,'New York');
  assert.equal(AIRPORT_CITIES.LGA,'New York');
  assert.equal(AIRPORT_CITIES.FCA,'Kalispell');
  assert.ok(Object.keys(AIRPORT_CITIES).length>10000);
  assert.equal(AIRPORT_CITIES.ZZZZZ,undefined);
});
test('a saved route belongs only to its own visit',()=>{
  const lookup=new RouteLookup();
  lookup.update([{...route,visit_id:'first',historical:true}]);
  const sighting={...plane,last_seen:1000,position_timestamp:undefined,visit_id:'second'};
  assert.equal(lookup.get(sighting,1500000),null);
  assert.equal(lookup.get({...sighting,visit_id:'first'},1500000)?.origin,'KDTO');
});
