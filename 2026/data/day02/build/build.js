/* Day 02 (Lines), four-city print edition: turn fetch.js's Overpass answers into the page's data.

usage: node build.js <raw-dir> <out-dir>
Writes <out-dir>/<city>.js, which sets window.DAY02[city] (a script, not JSON, so the poster also
works opened straight from disk, where browsers block fetch):
  stats:    bus services (distinct refs), km of road with a bus, urban rail lines, stations
  bus:      [[n, [polyline, ...]], ...]   road pieces used by n bus route relations. OSM maps
            each direction of a service as its own route, as LTA's patterns do on Day 02, so a
            two-way road with 10 services has n = 20 either way.
  rail:     [[name, mode, colour, [polyline, ...]], ...]   one entry per line, drawn in order
  stations: [[lng, lat, lines], ...]   rail stops (not tram stops) merged within 150 m
Polylines are Google-encoded (1e-5 deg), simplified to SIMPLIFY_M: the poster prints at about
30 m a pixel, so nothing finer would show.

Which trains count as urban rail: route=train only when it is a commuter/suburban service or
belongs to a city network (MTR, SL, S-tog). Regional and intercity trains are left out, and so
are ferries, funiculars and aerial lifts.
*/
'use strict';
const fs = require('fs');
const path = require('path');
const CITIES = require('./cities.js');

const [RAW, OUT] = process.argv.slice(2);
if (!OUT) { console.error('usage: node build.js <raw-dir> <out-dir>'); process.exit(1); }
const SIMPLIFY_M = 8, STATION_MERGE_M = 150;
const BUS = new Set(['bus', 'trolleybus', 'minibus']);
const RAIL = ['train', 'subway', 'monorail', 'light_rail', 'tram'];   // draw order, bottom to top
const URBAN_TRAIN = /\b(MTR|SL|S-tog|S-train|Storstockholms Lokaltrafik|Roslagsbanan|Saltsj[öo]banan|Pendelt[åa]g)\b/i;
const NOT_URBAN = /intercity|through train|KTM|Shuttle Tebrau|Øresund|(?:^|\s)SJ(?:\s|$)|Mälartåg|regional|Skytrain|High Speed|高速|People Mover|\bAPM\b/i;   // Skytrain, APM: airport people movers
// Routes still being built or planned are mapped in OSM with these tags; they are not running yet.
const notRunning = t => !!(t.construction || t.proposed || t.disused || t.abandoned || /^(construction|proposed|planned|disused)$/.test(t.state || ''));
const FALLBACK = { train: '#9AA7B8', subway: '#E8E8E8', monorail: '#C9B6FF', light_rail: '#B6E3A0', tram: '#7FD6C2' };
// Some lines are coloured by name rather than hex (Stockholm's tunnelbana: "green", "red", "blue");
// these are SL's shades. Anything else unreadable or near-black falls back to FALLBACK.
const NAMED = { green: '#4BA946', red: '#E3242B', blue: '#0089CA', orange: '#F28C28', purple: '#8E44AD', yellow: '#F2D600', brown: '#9D5B25', pink: '#F166A7', grey: '#9AA7B8', gray: '#9AA7B8' };
function lineColour(L) {
  const v = (L.colour || '').trim().toLowerCase(), hex = /^#?([0-9a-f]{6}|[0-9a-f]{3})$/.test(v) ? (v[0] === '#' ? v : `#${v}`) : NAMED[v];
  if (!hex) return FALLBACK[L.mode];
  const rgb = hex.length === 4 ? [1, 2, 3].map(i => parseInt(hex[i] + hex[i], 16)) : [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
  return rgb[0] * 0.299 + rgb[1] * 0.587 + rgb[2] * 0.114 > 30 ? hex : FALLBACK[L.mode];   // near-black would vanish on the night map
}

const metres = (a, b) => {
  const k = Math.PI / 180, x = (b[0] - a[0]) * k * Math.cos((a[1] + b[1]) * k / 2), y = (b[1] - a[1]) * k;
  return 6371008.8 * Math.hypot(x, y);
};
function simplify(pts, tol) {   // Douglas-Peucker in local metres
  if (pts.length < 3) return pts;
  const k = Math.cos(pts[0][1] * Math.PI / 180) * 111320, xy = pts.map(([x, y]) => [x * k, y * 110574]);
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    const [ax, ay] = xy[a], dx = xy[b][0] - ax, dy = xy[b][1] - ay, L = Math.hypot(dx, dy) || 1e-9;
    let best = -1, bd = tol;
    for (let i = a + 1; i < b; i++) { const d = Math.abs(dx * (ay - xy[i][1]) - dy * (ax - xy[i][0])) / L; if (d > bd) { bd = d; best = i; } }
    if (best > 0) { keep[best] = 1; stack.push([a, best], [best, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}
function encode(pts) {
  let out = '', plat = 0, plng = 0;
  const enc = v => { v = v < 0 ? ~(v << 1) : v << 1; let s = ''; while (v >= 0x20) { s += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; } return s + String.fromCharCode(v + 63); };
  for (const [lng, lat] of pts) { const a = Math.round(lat * 1e5), o = Math.round(lng * 1e5); out += enc(a - plat) + enc(o - plng); plat = a; plng = o; }
  return out;
}
const isStopRole = r => /platform|stop|station|entry|exit/.test(r || '');

fs.mkdirSync(OUT, { recursive: true });
for (const c of CITIES.list) {
  const raw = JSON.parse(fs.readFileSync(path.join(RAW, `${c.id}.json`), 'utf8'));
  const [W, S, E, N] = CITIES.bbox(c, 1);
  const routes = [], masters = new Map(), ways = new Map(), nodes = new Map();
  for (const e of raw.elements) {
    if (e.type === 'relation') (e.tags.type === 'route_master' ? masters.set(e.id, e) : routes.push(e));
    else if (e.type === 'way' && e.geometry) ways.set(e.id, e.geometry.map(g => [g.lon, g.lat]));
    else if (e.type === 'node') nodes.set(e.id, [e.lon, e.lat]);
  }
  const masterOf = new Map();
  for (const m of masters.values()) for (const mem of m.members || []) if (mem.type === 'relation') masterOf.set(mem.ref, m);
  const inFrame = g => g.some(([x, y]) => x >= W && x <= E && y >= S && y <= N);

  // ---- buses: count route relations per way ----
  const count = new Map(), refs = new Set();
  for (const r of routes) {
    if (!BUS.has(r.tags.route) || notRunning(r.tags)) continue;
    const seen = new Set();
    for (const m of r.members || []) if (m.type === 'way' && !isStopRole(m.role) && ways.has(m.ref) && !seen.has(m.ref)) {
      seen.add(m.ref); count.set(m.ref, (count.get(m.ref) || 0) + 1);
    }
    if (seen.size) refs.add(`${r.tags.network || r.tags.operator || ''}|${r.tags.ref || r.tags.name || r.id}`);
  }
  const buckets = new Map();
  let busKm = 0;
  for (const [id, n] of count) {
    const g = ways.get(id);
    if (!inFrame(g)) continue;
    for (let i = 1; i < g.length; i++) busKm += metres(g[i - 1], g[i]) / 1000;
    if (!buckets.has(n)) buckets.set(n, []);
    buckets.get(n).push(encode(simplify(g, SIMPLIFY_M)));
  }

  // ---- urban rail: one entry per line (route master, else ref/name) ----
  const lines = new Map(), stops = [];
  for (const r of routes) {
    const t = r.tags, mode = t.route;
    if (BUS.has(mode) || !RAIL.includes(mode) || notRunning(t)) continue;
    const m = masterOf.get(r.id), mt = m ? m.tags : {};
    const label = [t.network, t.operator, t.service, t.name, mt.network, mt.name].filter(Boolean).join(' ');
    if (mode === 'train' && !(/^(commuter|suburban|urban)$/.test(t.service || '') || URBAN_TRAIN.test(label))) continue;
    if (NOT_URBAN.test(label)) continue;
    const key = m ? `m${m.id}` : `${mode}|${t.ref || t.name}`;
    if (!lines.has(key)) lines.set(key, { name: mt.name || t.name || t.ref || '', ref: mt.ref || t.ref || '', mode, colour: mt.colour || t.colour || '', ways: new Set() });
    const L = lines.get(key);
    if (!L.colour && t.colour) L.colour = t.colour;
    for (const mem of r.members || []) {
      if (mem.type === 'way' && !isStopRole(mem.role) && ways.has(mem.ref)) L.ways.add(mem.ref);
      if (mem.type === 'node' && mem.role === 'stop' && mode !== 'tram' && nodes.has(mem.ref)) stops.push([...nodes.get(mem.ref), key]);
    }
  }
  const rail = [...lines.values()].filter(L => L.ways.size && [...L.ways].some(id => inFrame(ways.get(id))))
    .sort((a, b) => RAIL.indexOf(a.mode) - RAIL.indexOf(b.mode))
    .map(L => [L.name, L.mode, lineColour(L),
      [...L.ways].map(id => encode(simplify(ways.get(id), SIMPLIFY_M)))]);

  // ---- stations: merge stops of the kept lines within STATION_MERGE_M ----
  const stations = [];
  for (const [lng, lat, key] of stops) {
    if (!lines.has(key)) continue;
    const s = stations.find(s => metres(s, [lng, lat]) < STATION_MERGE_M);
    if (s) s[2].add(key); else stations.push([lng, lat, new Set([key])]);
  }
  const st = stations.filter(([x, y]) => x >= W && x <= E && y >= S && y <= N).map(([x, y, k]) => [Math.round(x * 1e5) / 1e5, Math.round(y * 1e5) / 1e5, k.size]);

  const out = {
    id: c.id, name: c.name, centre: c.centre, frameKm: CITIES.FRAME_KM, osm: raw.osm3s && raw.osm3s.timestamp_osm_base,
    stats: { busServices: refs.size, busKm: Math.round(busKm), railLines: rail.length, stations: st.length },
    bus: [...buckets].sort((a, b) => a[0] - b[0]),
    rail, stations: st,
  };
  const file = path.join(OUT, `${c.id}.js`);
  fs.writeFileSync(file, `(window.DAY02 = window.DAY02 || {})[${JSON.stringify(c.id)}] = ${JSON.stringify(out)};
`);
  const ns = [...count.values()].sort((a, b) => a - b);
  console.log(`\n${c.name}: ${(fs.statSync(file).size / 1e6).toFixed(2)} MB  ${JSON.stringify(out.stats)}  busiest way n=${ns[ns.length - 1]}, median ${ns[ns.length >> 1]}`);
  for (const [name, mode, colour, w] of rail) console.log(`   ${mode.padEnd(10)} ${colour.padEnd(8)} ${name} (${w.length} ways)`);
}
