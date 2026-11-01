// Day 03 data prep, step 3 of 3: pack the simplified patches (TopoJSON) and the island
// outline into one compact JSON the page decodes itself (see decodeQuilt in the page).
//   arcs:  TopoJSON's quantized, delta-coded arcs, each written as a polyline-style
//          varint string (zigzag, 5-bit chunks + 63), so ~3 bytes a vertex.
//   f:     one row per patch: [fabric, landUse, gprIndex, planningArea, areaM2, ...rings]
//          each ring a varint string of delta-coded arc references (~i = reversed arc).
//   island: outline rings as varint strings of delta-coded 1e5 lng/lat.
// usage: node encode.mjs <patches.topo.json> <island.geojson> <stats.json> <out.json>
import { readFileSync, writeFileSync } from 'node:fs';

const [topoPath, islandPath, statsPath, outPath] = process.argv.slice(2);
const topo = JSON.parse(readFileSync(topoPath, 'utf8'));
const island = JSON.parse(readFileSync(islandPath, 'utf8'));
const stats = JSON.parse(readFileSync(statsPath, 'utf8'));

const enc = ints => {
  let s = '';
  for (const n of ints) {
    let v = n < 0 ? ~(n << 1) : n << 1;
    while (v >= 32) { s += String.fromCharCode((32 | (v & 31)) + 63); v >>>= 5; }
    s += String.fromCharCode(v + 63);
  }
  return s;
};
const deltas = list => list.map((v, i) => (i ? v - list[i - 1] : v));

const obj = Object.values(topo.objects)[0];
const arcs = topo.arcs.map(a => enc(a.flat()));
const G = [];
const gIdx = g => { g = g == null ? '' : String(g); let i = G.indexOf(g); if (i < 0) { G.push(g); i = G.length - 1; } return i; };
gIdx('');
const f = [];
let dropped = 0;
for (const g of obj.geometries) {
  const p = g.properties;
  const polys = g.type === 'Polygon' ? [g.arcs] : g.type === 'MultiPolygon' ? g.arcs : null;
  if (!polys) { dropped++; continue; }
  for (const rings of polys) {   // multipolygons (rare after -explode) become one row per part
    f.push([p.c, p.u, gIdx(p.g), p.p, p.a, ...rings.map(r => enc(deltas(r)))]);
  }
}

const isl = [];
for (const feat of island.features) {
  const gm = feat.geometry;
  const polys = gm.type === 'Polygon' ? [gm.coordinates] : gm.coordinates;
  for (const rings of polys) {
    isl.push(rings.map(r => {
      const q = r.map(([x, y]) => [Math.round(x * 1e5), Math.round(y * 1e5)]);
      return enc(q.flatMap((pt, i) => (i ? [pt[0] - q[i - 1][0], pt[1] - q[i - 1][1]] : pt)));
    }));
  }
}

const out = {
  v: 1,
  source: 'URA Master Plan 2019 Land Use layer (data.gov.sg d_90d86daa5bfaa371668b84fa5f01424f), planning areas d_4765db0e87b9c86336792efe8a1f7a66',
  built: new Date().toISOString().slice(0, 10),
  transform: topo.transform,
  fabrics: stats.fabric_keys,
  lu: stats.lu.map(s => s.toLowerCase()),
  pa: stats.pa,
  gpr: G,
  stats: { total: stats.total_km2, road: stats.road_km2, km2: stats.fabric_keys.map(k => stats.fabrics[k].km2) },
  arcs,
  f,
  island: isl,
};
writeFileSync(outPath, JSON.stringify(out));
console.log(`patches ${f.length} (dropped ${dropped} empty), arcs ${arcs.length}, island parts ${isl.length}, gpr values ${G.length}`);
