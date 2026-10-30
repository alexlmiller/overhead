// The HA server owns providers, credentials, caching, and the paid-request cap.
// The page only reads sanitized routes from HA: the TV feed or a signed-in WebSocket.
const code=v=>typeof v==='string'&&/^[A-Z0-9-]{2,10}$/.test(v)?v:'';
const call=a=>code((a?.callsign||a?.registration||'').trim().toUpperCase());
export const routeText=r=>r?`${r.origin} → ${r.destination}`:'';
// Unknown airports retain their exact identifier; never guess from code prefixes.
export function routeLabels(route, cities={}, mode='both') {
  if(!route)return {primary:'',secondary:''};
  const codes=routeText(route);
  const primary=mode==='codes'?codes:
    `${cities[route.origin]||route.origin} → ${cities[route.destination]||route.destination}`;
  return {primary,secondary:mode==='both'&&primary!==codes?codes:''};
}
export class RouteLookup {
  entries=[];demo=new Map();
  update(entries){this.entries=Array.isArray(entries)?entries:[];}
  get(a,now=Date.now()) {
    const observed=a?.position_timestamp??a?.last_seen;
    const recent=Number.isFinite(a?.last_seen)&&!Number.isFinite(a?.position_timestamp);
    const matches=r=>(!r.visit_id||r.visit_id===a?.visit_id)&&(!r.historical||recent)&&r.hex===a?.hex&&call(r)===call(a)&&
      r.registration===(a?.registration||'')&&Number.isFinite(observed)&&
      observed>=r.valid_from&&observed<=r.valid_until&&r.expires>now/1000&&
      code(r.origin)&&code(r.destination)&&code(r.flight);
    const r=(recent&&this.entries.find(r=>r.historical&&matches(r)))||this.entries.find(matches);
    return r||this.demo.get(call(a))||null;
  }
  seed(a,route){this.demo.set(call(a),route);}
}
