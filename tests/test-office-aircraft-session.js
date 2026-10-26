const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../home_assistant/legacy/aircraft-session.js'), 'utf8');

function fixture() {
  let clock = 100000, Class;
  const calls = [];
  const context = {
    HTMLElement: class { appendChild() {} },
    document: {visibilityState: 'visible', createElement: () => ({style: {}})},
    location: {pathname: '/dashboard-office-aircraft/sky', search: '?office_tv=1'},
    URLSearchParams, Date: {now: () => clock}, setInterval: () => 1, clearInterval() {},
    customElements: {get: () => undefined, define: (_, c) => { Class = c; }},
  };
  vm.runInNewContext(source, context);
  const card = new Class();
  card.isConnected = true;
  card.setConfig({});
  const hass = {
    connected: true,
    states: {'input_select.office_aircraft_session': {state: 'Automatic'},
      'sensor.office_aircraft_current': {state: 'none'}},
    callService: (...args) => { calls.push(args); return Promise.resolve(); },
  };
  card.hass = hass;
  const step = (seconds, update = true) => {
    for (let i = 0; i < seconds; i++) {
      clock += 1000;
      if (update) card.hass = hass;
      else card.tick();
    }
  };
  return {card, hass, context, calls, step};
}

{
  const f = fixture();
  f.step(14); assert.equal(f.calls.length, 0);
  f.step(1); assert.deepEqual(f.calls, [['script', 'office_tv_aircraft_finished']]);
}
for (const change of [
  f => { f.context.document.visibilityState = 'hidden'; },
  f => { f.context.location.pathname = '/different-dashboard'; },
  f => { f.context.location.search = ''; },
  f => { f.card.isConnected = false; },
  f => { f.hass.connected = false; },
  f => { f.hass.states['input_select.office_aircraft_session'].state = 'Manual'; },
  f => { f.hass.states['sensor.office_aircraft_current'].state = 'abc123'; },
]) {
  const f = fixture(); f.step(10); change(f); f.step(20);
  assert.equal(f.calls.length, 0, 'navigation, disconnect, manual view, or returning aircraft must suppress Art');
}
{
  const f = fixture(); f.step(20, false);
  assert.equal(f.calls.length, 0, 'stale HA connection must not return to Art');
}
console.log('Aircraft page visibility and return-to-Art tests passed');
