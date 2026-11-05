/* Day 08 (Utopia), Kalimantan print editions: build the data the two sheets draw.

usage: node build.js <raw-dir> <out-dir>      (out-dir: 2026/data/day08)
Needs GDAL's ogr2ogr, gdal_rasterize and gdal_translate on the PATH (2.3 is enough).
Writes <out-dir>/kalimantan.js (window.DAY08K) and <out-dir>/kalimantan-relief.js (window.DAY08K_RELIEF).

Fires: every NOAA-20 VIIRS detection of nominal or high confidence on Borneo, 1 Jan to the last
day fetched (low-confidence ones are left out, as FIRMS advises for counts). Each is looked up
in a 0.0025 degree (about 280 m) grid of the peat maps and of the provinces, then snapped to a
0.004 degree (about 445 m, a little over one VIIRS pixel) cell; the sheets draw cells.
Geometry is clipped, simplified by GDAL and stored as polylines at 1e-4 degree (about 11 m).
*/
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const { execFileSync } = require('child_process');

const [RAW, OUT] = process.argv.slice(2);
if (!RAW || !OUT) { console.error('usage: node build.js <raw-dir> <out-dir>'); process.exit(1); }
const TMP = path.join(RAW, 'tmp');
fs.mkdirSync(TMP, { recursive: true });
const BBOX = [108.3, -4.6, 119.6, 7.6];
const raw = f => path.join(RAW, f), tmp = f => path.join(TMP, f);
const run = (cmd, args) => execFileSync(cmd, args, { stdio: ['ignore', 'ignore', 'inherit'] });
const readJSON = f => JSON.parse(fs.readFileSync(f, 'utf8'));
const ogr = (out, src, ...args) => { if (fs.existsSync(out)) fs.unlinkSync(out); run('ogr2ogr', ['-f', 'GeoJSON', '-lco', 'COORDINATE_PRECISION=5', out, src, ...args]); return readJSON(out); };

/* ---------- polyline encoding (Google's, at 1e-4) ---------- */
const Q = 1e4;
function enc(coords) {
  let s = '', px = 0, py = 0;
  const put = v => { v = v < 0 ? ~(v << 1) : v << 1; while (v >= 0x20) { s += String.fromCharCode((0x20 | (v & 0x1f)) + 63); v >>= 5; } s += String.fromCharCode(v + 63); };
  let last = null;
  for (const [x, y] of coords) {
    const ix = Math.round(x * Q), iy = Math.round(y * Q);
    if (last && ix === last[0] && iy === last[1]) continue;
    put(iy - py); put(ix - px); py = iy; px = ix; last = [ix, iy];
  }
  return s;
}
const rings = g => !g ? [] : g.type === 'Polygon' ? g.coordinates : g.type === 'MultiPolygon' ? g.coordinates.flat() : [];
const lines = g => !g ? [] : g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
const polyRings = fc => fc.features.flatMap(f => rings(f.geometry)).filter(r => r.length > 3).map(enc);

/* ---------- Borneo: provinces and states ---------- */
const PROV = [   // id, name, country, source file, name in the source
  [1, 'West Kalimantan', 'IDN', 'adm-idn', 'West Kalimantan'], [2, 'Central Kalimantan', 'IDN', 'adm-idn', 'Central Kalimantan'],
  [3, 'South Kalimantan', 'IDN', 'adm-idn', 'South Kalimantan'], [4, 'East Kalimantan', 'IDN', 'adm-idn', 'East Kalimantan'],
  [5, 'North Kalimantan', 'IDN', 'adm-idn', 'North Kalimantan'], [6, 'Sarawak', 'MYS', 'adm-mys', 'Sarawak'],
  [7, 'Sabah', 'MYS', 'adm-mys', 'Sabah'], [8, 'Labuan', 'MYS', 'adm-mys', 'Labuan'], [9, 'Brunei', 'BRN', 'adm-brn', 'Brunei'],
];
const provFC = { type: 'FeatureCollection', features: [] };
for (const [id, name, country, file, src] of PROV) {
  const fc = ogr(tmp(`prov-${id}.geojson`), raw(`${file}.geojson`), '-where', `shapeName = '${src}'`, '-clipsrc', ...BBOX.map(String), '-simplify', '0.0015');
  for (const f of fc.features) provFC.features.push({ type: 'Feature', properties: { id, name, country }, geometry: f.geometry });
}
fs.writeFileSync(tmp('provinces.geojson'), JSON.stringify(provFC));
console.log('provinces', provFC.features.length);

/* ---------- lookup grids: provinces and peat, rasterised at 0.0025 degrees ---------- */
const RES = 0.0025, GW = Math.round((BBOX[2] - BBOX[0]) / RES), GH = Math.round((BBOX[3] - BBOX[1]) / RES);
function grid(name, src, burn) {
  const out = tmp(`${name}.bin`);
  for (const ext of ['.bin', '.hdr', '.bin.aux.xml']) if (fs.existsSync(tmp(name + ext))) fs.unlinkSync(tmp(name + ext));
  run('gdal_rasterize', [...burn, '-te', ...BBOX.map(String), '-ts', String(GW), String(GH), '-ot', 'Byte', '-init', '0', '-of', 'ENVI', src, out]);
  return fs.readFileSync(out);
}
const cellOf = (lng, lat) => {
  const x = Math.floor((lng - BBOX[0]) / RES), y = Math.floor((BBOX[3] - lat) / RES);
  return x >= 0 && y >= 0 && x < GW && y < GH ? y * GW + x : -1;
};
const provGrid = grid('provgrid', tmp('provinces.geojson'), ['-a', 'id']);

const peatAll = { type: 'FeatureCollection', features: [] };
for (const f of ['peat-idn', 'peat-mys']) for (const ft of readJSON(raw(`${f}.geojson`)).features) if (ft.geometry) peatAll.features.push({ type: 'Feature', properties: { src: f }, geometry: ft.geometry });
fs.writeFileSync(tmp('peat-all.geojson'), JSON.stringify(peatAll));
const peatGrid = grid('peatgrid', tmp('peat-all.geojson'), ['-burn', '1']);

// Peat area by province, from the grid (cell area shrinks with cos(latitude)).
const KM_PER_DEG = 111.32;
const peatKm2 = {}, landKm2 = {};
for (let y = 0; y < GH; y++) {
  const a = (RES * KM_PER_DEG) ** 2 * Math.cos((BBOX[3] - (y + 0.5) * RES) * Math.PI / 180);
  for (let x = 0; x < GW; x++) {
    const p = provGrid[y * GW + x];
    if (!p) continue;
    landKm2[p] = (landKm2[p] || 0) + a;
    if (peatGrid[y * GW + x]) peatKm2[p] = (peatKm2[p] || 0) + a;
  }
}

/* ---------- vectors for drawing ---------- */
const peatDraw = ogr(tmp('peat-draw.geojson'), tmp('peat-all.geojson'), '-simplify', '0.001');
const ifl = ogr(tmp('ifl.geojson'), raw('ifl2016.geojson'), '-simplify', '0.002');
const land = ogr(tmp('land.geojson'), `/vsizip/${raw('ne_10m_land.zip')}/ne_10m_land.shp`, '-clipsrc', '103', '-10', '125', '12', '-simplify', '0.003');
const rivers = ogr(tmp('rivers.geojson'), `/vsizip/${raw('HydroRIVERS_v10_au_shp.zip')}/HydroRIVERS_v10_au_shp/HydroRIVERS_v10_au.shp`,
  '-spat', ...BBOX.map(String), '-where', 'UPLAND_SKM >= 400', '-select', 'HYRIV_ID,NEXT_DOWN,UPLAND_SKM,DIS_AV_CMS,ORD_FLOW', '-simplify', '0.002');
// Keep rivers on Borneo (the box also takes in a corner of Sulawesi); join each reach to the
// next one downstream with the same width class, so long rivers draw as long smooth lines.
const riverClass = q => q >= 1500 ? 5 : q >= 500 ? 4 : q >= 150 ? 3 : q >= 50 ? 2 : 1;
const reaches = new Map();
for (const f of rivers.features) {
  const c = lines(f.geometry)[0];
  if (!c || !c.length) continue;
  const mid = c[Math.floor(c.length / 2)];
  const k = cellOf(mid[0], mid[1]);
  if (k < 0 || !provGrid[k]) continue;
  const p = f.properties;
  reaches.set(p.HYRIV_ID, { id: p.HYRIV_ID, down: p.NEXT_DOWN, cls: riverClass(p.DIS_AV_CMS), c });
}
const used = new Set(), riverLines = [];
// Start chains at reaches no same-class reach flows into; walk downstream while the class holds.
const feeds = new Map();
for (const r of reaches.values()) { const d = reaches.get(r.down); if (d && d.cls === r.cls) feeds.set(d.id, (feeds.get(d.id) || 0) + 1); }
for (const r of reaches.values()) {
  if (used.has(r.id) || feeds.get(r.id) === 1) continue;
  let cur = r, pts = [...r.c];
  used.add(r.id);
  for (;;) {
    const d = reaches.get(cur.down);
    if (!d || d.cls !== cur.cls || used.has(d.id) || feeds.get(d.id) !== 1) break;
    pts = pts.concat(d.c.slice(1)); used.add(d.id); cur = d;
  }
  riverLines.push([r.cls, enc(pts)]);
}
for (const r of reaches.values()) if (!used.has(r.id)) riverLines.push([r.cls, enc(r.c)]);   // loops, if any
riverLines.sort((a, b) => a[0] - b[0]);
console.log('rivers', reaches.size, 'reaches ->', riverLines.length, 'lines');

/* ---------- places ---------- */
const PLACES = {   // Natural Earth name -> label on the sheets
  Pontianak: 'Pontianak', 'Palangkaraya': 'Palangka Raya', Bandjarmasin: 'Banjarmasin', Kualakapuas: 'Kuala Kapuas', Samarinda: 'Samarinda', Balikpapan: 'Balikpapan',
  Tarakan: 'Tarakan', Kuching: 'Kuching', 'Kota Kinabalu': 'Kota Kinabalu', 'Bandar Seri Begawan': 'Bandar Seri Begawan',
  Sampit: 'Sampit', Sandakan: 'Sandakan', Sibu: 'Sibu', Miri: 'Miri', Bintulu: 'Bintulu', Singkawang: 'Singkawang', Tawau: 'Tawau',
};
const pp = ogr(tmp('places.geojson'), `/vsizip/${raw('ne_10m_populated_places_simple.zip')}/ne_10m_populated_places_simple.shp`, '-spat', ...BBOX.map(String));
const places = [];
for (const f of pp.features) {
  const n = f.properties.name, label = PLACES[n] || PLACES[f.properties.nameascii];
  if (!label || places.some(p => p[0] === label)) continue;
  const [lng, lat] = f.geometry.coordinates;
  places.push([label, +lng.toFixed(4), +lat.toFixed(4), f.properties.adm0_a3, +(f.properties.pop_max || 0)]);
}
// Two towns at the edge of this year's worst burning that Natural Earth leaves out.
places.push(['Pangkalan Bun', 111.6200, -2.6800, 'IDN', 0], ['Ketapang', 109.9720, -1.8530, 'IDN', 0]);
// Nusantara, the new capital being built in East Kalimantan (the zero point at the core
// government area, Sepaku, Penajam Paser Utara), is not in Natural Earth.
places.push(['Nusantara (IKN)', 116.7022, -0.9741, 'IDN', 0]);
console.log('places', places.map(p => p[0]).join(', '));

/* ---------- fires ---------- */
const files = fs.readdirSync(raw('fires')).filter(f => f.endsWith('.json')).sort();
const CELL = 0.004;
const cells = new Map();
const MONTHS = 12;
const byProv = {}, monthly = Array.from({ length: MONTHS }, () => [0, 0]), monthlyAll = Array.from({ length: MONTHS }, () => [0, 0]);
const daily = [];
let total = 0, onPeat = 0, kal = 0, kalPeat = 0, low = 0;
for (const f of files) {
  const day = f.slice(0, 10), rows = readJSON(raw(`fires/${f}`));
  let dk = 0;
  for (const [lng, lat, , , frp, conf] of rows) {
    if (conf === 'low') { low++; continue; }
    const k = cellOf(lng, lat);
    if (k < 0) continue;
    const prov = provGrid[k];
    if (!prov) continue;   // at sea or off Borneo
    const peat = peatGrid[k] ? 1 : 0, m = +day.slice(5, 7) - 1, isKal = prov <= 5;
    total++; onPeat += peat;
    monthlyAll[m][peat]++;
    if (isKal) { kal++; kalPeat += peat; monthly[m][peat]++; dk++; }
    const b = byProv[prov] || (byProv[prov] = { n: 0, peat: 0 });
    b.n++; b.peat += peat;
    const cx = Math.floor((lng - BBOX[0]) / CELL), cy = Math.floor((BBOX[3] - lat) / CELL), ck = cy * 100000 + cx;
    const c = cells.get(ck) || { cx, cy, n: 0, peat: 0, frp: 0, prov, first: day };
    c.n++; c.peat += peat; c.frp += frp || 0;
    cells.set(ck, c);
  }
  daily.push([day, dk]);
}
const peak = daily.reduce((a, b) => (b[1] > a[1] ? b : a));
// Cells, sorted north to south then west to east, as flat rows: dx from the previous cell in the
// row (or absolute x on a new row), row y, detections, detections on peat, fire power (MW, rounded).
const list = [...cells.values()].sort((a, b) => a.cy - b.cy || a.cx - b.cx);
const flat = [];
let py = -1, px = 0;
for (const c of list) {
  const dx = c.cy === py ? c.cx - px : c.cx;
  flat.push(dx, c.cy - Math.max(py, 0), c.n, c.peat, Math.round(c.frp));
  py = c.cy; px = c.cx;
}
const kalCells = list.filter(c => c.prov <= 5);
console.log(`detections ${total} (low left out ${low}); on peat ${onPeat}; Kalimantan ${kal}, on peat ${kalPeat}; cells ${list.length} (Kalimantan ${kalCells.length}); peak ${peak}`);

/* ---------- write ---------- */
const round = v => Math.round(v);
const data = {
  meta: {
    bbox: BBOX, cell: CELL, q: Q, from: files[0].slice(0, 10), to: files[files.length - 1].slice(0, 10),
    cellsNote: 'cells: flat rows of [dx, dy, detections, on peat, FRP MW]; dx from the previous cell in the row, or absolute x on a new row; dy rows down from the previous cell. x, y count CELL degrees from (bbox west, bbox north).',
  },
  stats: {
    total, onPeat, kal, kalPeat, cells: list.length, kalCells: kalCells.length, kalCellsPeat: kalCells.filter(c => c.peat).length,
    peak: { day: peak[0], n: peak[1] }, monthly, monthlyAll,
    provinces: PROV.map(([id, name, country]) => ({ id, name, country, fires: byProv[id] ? byProv[id].n : 0, firesPeat: byProv[id] ? byProv[id].peat : 0,
      landKm2: round(landKm2[id] || 0), peatKm2: round(peatKm2[id] || 0) })),
  },
  provinces: provFC.features.map(f => [f.properties.id, rings(f.geometry).filter(r => r.length > 3).map(enc)]),
  land: polyRings(land),
  peat: polyRings(peatDraw),
  ifl: polyRings(ifl),
  rivers: riverLines,
  places,
  cells: flat,
};
fs.writeFileSync(path.join(OUT, 'kalimantan.js'), `window.DAY08K = ${JSON.stringify(data)};\n`);
console.log('kalimantan.js', (fs.statSync(path.join(OUT, 'kalimantan.js')).size / 1e6).toFixed(2), 'MB');

/* ---------- relief: Terrarium tiles -> hillshade -> JPEG ---------- */
function png(buf) {   // 8-bit RGB or RGBA, not interlaced: all the Terrarium tiles are
  let p = 8, w, h, ct, idat = [];
  while (p < buf.length) {
    const len = buf.readUInt32BE(p), type = buf.toString('ascii', p + 4, p + 8), d = buf.subarray(p + 8, p + 8 + len);
    if (type === 'IHDR') { w = d.readUInt32BE(0); h = d.readUInt32BE(4); ct = d[9]; if (d[8] !== 8 || d[12]) throw new Error('unsupported PNG'); }
    else if (type === 'IDAT') idat.push(d);
    p += 12 + len;
  }
  const bpp = ct === 6 ? 4 : ct === 2 ? 3 : (() => { throw new Error(`PNG colour type ${ct}`); })();
  const z = zlib.inflateSync(Buffer.concat(idat)), stride = w * bpp, out = Buffer.alloc(h * stride);
  for (let y = 0; y < h; y++) {
    const f = z[y * (stride + 1)], row = z.subarray(y * (stride + 1) + 1, (y + 1) * (stride + 1));
    for (let i = 0; i < stride; i++) {
      const a = i >= bpp ? out[y * stride + i - bpp] : 0, b = y ? out[(y - 1) * stride + i] : 0, c = i >= bpp && y ? out[(y - 1) * stride + i - bpp] : 0;
      let v = row[i];
      if (f === 1) v += a; else if (f === 2) v += b; else if (f === 3) v += (a + b) >> 1;
      else if (f === 4) { const pa = Math.abs(b - c), pb = Math.abs(a - c), pc = Math.abs(a + b - 2 * c); v += pa <= pb && pa <= pc ? a : pb <= pc ? b : c; }
      out[y * stride + i] = v & 255;
    }
  }
  return { w, h, bpp, px: out };
}
const Z = 8, TDIR = raw(`terrain/${Z}`);
const xs = fs.readdirSync(TDIR).map(Number).sort((a, b) => a - b);
const ys = fs.readdirSync(path.join(TDIR, String(xs[0]))).map(f => parseInt(f)).sort((a, b) => a - b);
const W = xs.length * 256, H = ys.length * 256, elev = new Float32Array(W * H);
for (const [i, x] of xs.entries()) for (const [j, y] of ys.entries()) {
  const t = png(fs.readFileSync(path.join(TDIR, String(x), `${y}.png`)));
  for (let r = 0; r < 256; r++) for (let c = 0; c < 256; c++) {
    const o = (r * 256 + c) * t.bpp;
    elev[(j * 256 + r) * W + i * 256 + c] = t.px[o] * 256 + t.px[o + 1] + t.px[o + 2] / 256 - 32768;
  }
}
// Hillshade, land only: three lights (NW strongest), 4x vertical exaggeration; flat land = 128,
// so the sheets can lay it on with an "overlay" blend that both lightens and darkens.
const n = 2 ** Z, lat = yy => Math.atan(Math.sinh(Math.PI * (1 - 2 * yy / (256 * n)))) * 180 / Math.PI;
const shade = Buffer.alloc(W * H, 128), EX = 4;
const LIGHTS = [[315, 45, 0.6], [270, 45, 0.2], [0, 45, 0.2]].map(([az, alt, w]) => [az * Math.PI / 180, alt * Math.PI / 180, w]);
for (let y = 1; y < H - 1; y++) {
  const cell = 2 * Math.PI * 6378137 * Math.cos(lat(ys[0] * 256 + y + 0.5) * Math.PI / 180) / (256 * n);
  for (let x = 1; x < W - 1; x++) {
    const e = i => Math.max(0, elev[i]), k = y * W + x;
    if (elev[k] <= 0) continue;
    const dzdx = ((e(k - W + 1) + 2 * e(k + 1) + e(k + W + 1)) - (e(k - W - 1) + 2 * e(k - 1) + e(k + W - 1))) / (8 * cell) * EX;
    const dzdy = ((e(k + W - 1) + 2 * e(k + W) + e(k + W + 1)) - (e(k - W - 1) + 2 * e(k - W) + e(k - W + 1))) / (8 * cell) * EX;
    const slope = Math.atan(Math.hypot(dzdx, dzdy)), aspect = Math.atan2(dzdy, -dzdx);
    let v = 0;
    for (const [az, alt, w] of LIGHTS) {
      const a = Math.PI / 2 - az;   // to maths angle
      v += w * (Math.cos(Math.PI / 2 - alt) * Math.cos(slope) + Math.sin(Math.PI / 2 - alt) * Math.sin(slope) * Math.cos(a - aspect));
    }
    shade[k] = Math.max(0, Math.min(255, Math.round(128 + (v - Math.cos(Math.PI / 4)) * 260)));
  }
}
fs.writeFileSync(tmp('relief.bin'), shade);
fs.writeFileSync(tmp('relief.hdr'), `ENVI\nsamples = ${W}\nlines = ${H}\nbands = 1\nheader offset = 0\nfile type = ENVI Standard\ndata type = 1\ninterleave = bsq\nbyte order = 0\n`);
if (fs.existsSync(tmp('relief.jpg'))) fs.unlinkSync(tmp('relief.jpg'));
run('gdal_translate', ['-of', 'JPEG', '-co', 'QUALITY=88', tmp('relief.bin'), tmp('relief.jpg')]);
const lng = xx => xx / (256 * n) * 360 - 180;
const relief = { z: Z, bounds: [lng(xs[0] * 256), lat((ys[ys.length - 1] + 1) * 256), lng((xs[xs.length - 1] + 1) * 256), lat(ys[0] * 256)],
  img: `data:image/jpeg;base64,${fs.readFileSync(tmp('relief.jpg')).toString('base64')}` };
fs.writeFileSync(path.join(OUT, 'kalimantan-relief.js'), `window.DAY08K_RELIEF = ${JSON.stringify(relief)};\n`);
console.log('kalimantan-relief.js', W, 'x', H, (fs.statSync(path.join(OUT, 'kalimantan-relief.js')).size / 1e6).toFixed(2), 'MB');
