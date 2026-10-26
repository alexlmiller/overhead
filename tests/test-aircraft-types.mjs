import test from 'node:test';
import assert from 'node:assert/strict';
import {readdirSync,readFileSync} from 'node:fs';
import {AIRCRAFT_TYPES,AIRCRAFT_ICONS} from '../web/aircraft-types.mjs';
import {AIRLINE_LOGOS,AIRLINE_DESIGNATORS} from '../web/airlines.mjs';
import {typeName,iconIndex,aircraftIcon,airlineLogo,flightNumber} from '../web/core.mjs';

test('common designators read as manufacturer and model',()=>{
  for(const [code,name] of [['C25B','Cessna Citation CJ3'],['B39M','Boeing 737 MAX 9'],['E75L','Embraer 175'],
    ['BE9L','Beechcraft King Air 90'],['H60','UH-60 Black Hawk'],['GB1','GameBird GB1'],['BALL','Balloon']])
    assert.equal(typeName(code,AIRCRAFT_TYPES),name);
});

test('unknown, padded, placeholder and hostile designators stay safe',()=>{
  assert.equal(typeName(' c25b ',AIRCRAFT_TYPES),'Cessna Citation CJ3');
  assert.equal(typeName('XY99',AIRCRAFT_TYPES),'XY99');
  assert.equal(typeName('ZZZZ',AIRCRAFT_TYPES),'');
  for(const code of ['',undefined,null,42])assert.equal(typeName(code,AIRCRAFT_TYPES),'');
  for(const code of ['constructor','__proto__','toString'])assert.equal(typeName(code,AIRCRAFT_TYPES),code.toUpperCase());
});

test('the generated table covers ICAO designators with map-tag length names',()=>{
  const entries=Object.entries(AIRCRAFT_TYPES);
  assert.ok(entries.length>2500);
  assert.equal(Object.getPrototypeOf(AIRCRAFT_TYPES),null);
  assert.ok(Object.isFrozen(AIRCRAFT_TYPES));
  for(const [code,name] of entries){
    assert.match(code,/^[A-Z0-9]{2,4}$/);
    assert.ok(name.length>0&&name.length<=28&&name.trim()===name,`${code}: ${name}`);
  }
});

test('every named type has a silhouette that the page defines',()=>{
  const index=iconIndex(AIRCRAFT_ICONS),page=readFileSync(new URL('../web/index.html',import.meta.url),'utf8');
  for(const code of Object.keys(AIRCRAFT_TYPES))assert.ok(index.has(code),code);
  for(const icon of new Set(index.values())){
    const [shape,wake]=icon.split('.');
    assert.match(page,new RegExp(`<symbol id="ac-${shape}"`),shape);
    assert.match(wake,/^(L|LM|M|H|J)$/);
  }
});

test('icons scale with wake category and fall back to the ADS-B emitter category',()=>{
  const index=iconIndex(AIRCRAFT_ICONS);
  assert.deepEqual(aircraftIcon({aircraft_type:'C25B'},index),{shape:'jet',size:.86});
  assert.deepEqual(aircraftIcon({aircraft_type:'B77W'},index),{shape:'widebody',size:1.22});
  assert.deepEqual(aircraftIcon({aircraft_type:'h60 '},index),{shape:'helicopter',size:1});
  assert.deepEqual(aircraftIcon({aircraft_type:'XY99',category:'A7'},index),{shape:'helicopter',size:.86});
  assert.deepEqual(aircraftIcon({aircraft_type:'',category:'Z9'},index),{shape:'airliner',size:1});
  assert.deepEqual(aircraftIcon({},index),{shape:'airliner',size:1});
});

test('airline logos come from airline-style callsigns with a bundled mark only',()=>{
  const logos=new Set(AIRLINE_LOGOS);
  assert.equal(airlineLogo({callsign:'UAL647'},logos),'UAL');
  assert.equal(airlineLogo({callsign:' skw3676 '},logos),'SKW');
  for(const callsign of ['N172SP','UAL','ZZZ123','SPTN630','',undefined])assert.equal(airlineLogo({callsign},logos),'');
});

test('the logo list matches the bundled files',()=>{
  const files=readdirSync(new URL('../web/logos/',import.meta.url)).filter(f=>f.endsWith('.png')).map(f=>f.slice(0,-4)).sort();
  assert.deepEqual([...AIRLINE_LOGOS],files);
  assert.ok(Object.isFrozen(AIRLINE_LOGOS));
});

test('airline callsigns read as published flight numbers; others stay as broadcast',()=>{
  for(const [callsign,expected] of [['UAL696','UA 696'],[' dal0012 ','DL 12'],['SKW3676','OO 3676'],['AAY1','G4 1'],
    ['N172SP','N172SP'],['EJA624','EJA624'],['CLX16V','CLX16V'],['UAL0','UAL0'],['ZZZ123','ZZZ123'],['','']])
    assert.equal(flightNumber(callsign,AIRLINE_DESIGNATORS),expected,callsign);
  assert.equal(Object.getPrototypeOf(AIRLINE_DESIGNATORS),null);
  assert.equal(flightNumber('CONSTRUCTOR1',AIRLINE_DESIGNATORS),'CONSTRUCTOR1');
});
