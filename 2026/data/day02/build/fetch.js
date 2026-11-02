/* Day 02 (Lines), four-city print edition: fetch public transport routes from OpenStreetMap.

usage: node fetch.js <raw-dir>
Writes <raw-dir>/<city>.json, the Overpass answers for each city merged (re-runnable: files already
on disk are kept; delete one to fetch it again). Then run build.js.

For each city, inside a fixed frame and inside the city's own country (so Johor Bahru, Shenzhen
and Malmö stay dark):
  route relations: bus, trolleybus, minibus, tram, light_rail, subway, monorail, train
                   (tags + member lists; build.js decides which trains are urban rail)
  route masters:   tags and members, for line colours and names
  ways:            every member way, with geometry
  stop nodes:      the "stop" members of rail and tram routes, for station dots
*/
'use strict';
const fs = require('fs');
const path = require('path');
const CITIES = require('./cities.js');

const RAW = process.argv[2];
if (!RAW) { console.error('usage: node fetch.js <raw-dir>'); process.exit(1); }
fs.mkdirSync(RAW, { recursive: true });
const ENDPOINT = 'https://overpass-api.de/api/interpreter';
const UA = '30DayMapChallenge-day02/1.0 (static print map)';

// Overpass times out on Hong Kong when route geometry is asked for in one go, so each city is
// fetched in small steps, each cached in <raw-dir> so a failed run resumes where it stopped:
//   1. the route relations (with member lists) and their route masters
//   2. the member ways, CHUNK ids at a time, with geometry, kept only inside the country and frame
//   3. the "stop" member nodes of non-bus routes, the same way
const MODES = 'bus|trolleybus|minibus|tram|light_rail|subway|monorail|train';
const CHUNK = 2000;
const BUS = /^(bus|trolleybus|minibus)$/;

async function ask(label, q) {
  for (let attempt = 1; ; attempt++) {
    const t = Date.now();
    let msg;
    try {
      const r = await fetch(ENDPOINT, { method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': UA },
        body: 'data=' + encodeURIComponent(q) });
      if (r.ok) {
        const j = await r.json();
        if (!j.remark || !/runtime error|out of memory|timed out/i.test(j.remark)) {
          console.log(`${label}: ${j.elements.length} elements in ${((Date.now() - t) / 1000).toFixed(0)} s`);
          return j;
        }
        msg = `Overpass remark: ${j.remark}`;
      } else msg = `HTTP ${r.status}`;
    } catch (e) { msg = e.message; }
    console.warn(`${label}: ${msg}`);
    if (attempt >= 6) throw new Error(`gave up on ${label}`);
    await new Promise(res => setTimeout(res, 30000 * attempt));
  }
}
async function cached(file, label, q) {
  if (fs.existsSync(file)) return JSON.parse(fs.readFileSync(file, 'utf8'));
  const j = await ask(label, q);
  fs.writeFileSync(file, JSON.stringify(j));
  return j;
}

async function city(c) {
  const out = path.join(RAW, `${c.id}.json`);
  if (fs.existsSync(out)) { console.log(`${c.id}: kept`); return; }
  const [w, s, e, n] = CITIES.bbox(c, 3), bb = `${s},${w},${n},${e}`;
  const part = k => path.join(RAW, `${c.id}.${k}.json`), parts = [];
  const rels = await cached(part('rels'), `${c.id} routes`, `[out:json][timeout:600];
rel[type=route][route~"^(${MODES})$"](${bb});
out body;
rel(br)[type=route_master];
out body;`);
  parts.push(part('rels'));
  const wayIds = new Set(), nodeIds = new Set();
  for (const r of rels.elements) {
    if (r.type !== 'relation' || r.tags.type !== 'route') continue;
    for (const m of r.members || []) {
      if (m.type === 'way') wayIds.add(m.ref);
      else if (m.type === 'node' && m.role === 'stop' && !BUS.test(r.tags.route)) nodeIds.add(m.ref);
    }
  }
  const elements = [...rels.elements];
  for (const [kind, ids, outp] of [['way', [...wayIds], 'out geom;'], ['node', [...nodeIds], 'out;']]) {
    for (let i = 0, k = 0; i < ids.length; i += CHUNK, k++) {
      const j = await cached(part(`${kind}s-${k}`), `${c.id} ${kind}s ${i + 1}-${Math.min(i + CHUNK, ids.length)} of ${ids.length}`,
        `[out:json][timeout:600];
area${c.area}->.a;
${kind}(id:${ids.slice(i, i + CHUNK).join(',')})(area.a)(${bb});
${outp}`);
      parts.push(part(`${kind}s-${k}`));
      elements.push(...j.elements);
    }
  }
  fs.writeFileSync(out, JSON.stringify({ osm3s: rels.osm3s, elements }));
  for (const p of parts) fs.unlinkSync(p);
  console.log(`${c.id}: done, ${elements.length} elements`);
}

(async () => {
  const failed = [];
  for (const c of CITIES.list) {
    try { await city(c); } catch (e) { console.error(`${c.id}: ${e.message}`); failed.push(c.id); }
  }
  if (failed.length) { console.error(`failed: ${failed.join(', ')} (run again to resume)`); process.exit(1); }
})();
