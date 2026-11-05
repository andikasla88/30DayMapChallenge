/* Day 08 (Utopia), Kalimantan print editions: fetch everything the two sheets are drawn from.

usage: node fetch.js <raw-dir> [last-day, default 2026-11-04]
Re-runnable: files already on disk are kept; delete one to fetch it again. Then run build.js.
No API keys and no npm packages: Node 18+ (fetch, zlib) only.

  fires/YYYY-MM-DD.json  every VIIRS fire detection on Borneo that day, from NASA GIBS: the FIRMS
                         NOAA-20 375 m layer as vector tiles. NOAA-20 is the one VIIRS satellite
                         with no gap in 2026 (Suomi NPP misses 11-15 July). At GIBS's 500m matrix
                         level 3 one tile (row 2, col 8: 108-144 E, 18 N-18 S) holds all of Borneo,
                         and it carries every detection (checked against levels 5 and 7).
  peat-idn.geojson       Indonesia Peat Lands (Ministry of Agriculture, 2011), and
  peat-mys.geojson       Malaysia Peat Lands (Wetlands International), from Global Forest Watch.
  ifl2016.geojson        Intact Forest Landscapes 2016 (Potapov et al.), from Global Forest Watch.
  adm-*.geojson          geoBoundaries: Indonesia and Malaysia provinces/states, Brunei.
  ne_10m_*.zip           Natural Earth land (the islands around Borneo) and populated places.
  HydroRIVERS_v10_au_shp.zip   HydroRIVERS (WWF HydroSHEDS), Australasia, which holds Borneo.
  terrain/z/x/y.png      AWS Terrain Tiles (Terrarium encoding) at zoom 8.
*/
'use strict';
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const RAW = process.argv[2];
const LAST = process.argv[3] || '2026-11-04';
if (!RAW) { console.error('usage: node fetch.js <raw-dir> [last-day]'); process.exit(1); }
const BBOX = [108.3, -4.6, 119.6, 7.6];   // Borneo with a little sea
fs.mkdirSync(path.join(RAW, 'fires'), { recursive: true });

const sleep = ms => new Promise(r => setTimeout(r, ms));
async function get(url, tries = 4) {
  for (let i = 1; ; i++) {
    try {
      const res = await fetch(url, { headers: { 'User-Agent': '30DayMapChallenge day08 build (personal, non-commercial)' } });
      if (res.status === 404) return null;
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return Buffer.from(await res.arrayBuffer());
    } catch (e) {
      if (i >= tries) throw new Error(`${url}: ${e.message}`);
      await sleep(1500 * i);
    }
  }
}
async function save(file, url) {
  const out = path.join(RAW, file);
  if (fs.existsSync(out)) return;
  const b = await get(url);
  if (!b) throw new Error(`not found: ${url}`);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, b);
  console.log(`${file}  ${(b.length / 1e6).toFixed(1)} MB`);
}
async function pool(items, n, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: n }, async () => { while (i < items.length) await fn(items[i++]); }));
}

/* ---------- a minimal Mapbox Vector Tile reader: feature properties only ---------- */
function mvtProps(buf) {
  let p = 0;
  const varint = () => { let r = 0, s = 1, b; do { b = buf[p++]; r += (b & 127) * s; s *= 128; } while (b >= 128); return r; };
  const skip = t => { if (t === 0) varint(); else if (t === 1) p += 8; else if (t === 2) { const n = varint(); p += n; } else if (t === 5) p += 4; else throw new Error(`wire type ${t}`); };
  const msg = (end, on) => { while (p < end) { const k = varint(); const f = Math.floor(k / 8), t = k & 7; if (!on(f, t)) skip(t); } };
  const value = end => {
    let v = null;
    msg(end, (f, t) => {
      if (f === 1) { const n = varint(); v = buf.toString('utf8', p, p + n); p += n; }
      else if (f === 2) { v = buf.readFloatLE(p); p += 4; }
      else if (f === 3) { v = buf.readDoubleLE(p); p += 8; }
      else if (f === 4 || f === 5) v = varint();
      else if (f === 6) { const n = varint(); v = n % 2 ? -(n + 1) / 2 : n / 2; }
      else if (f === 7) v = !!varint();
      else return false;
      return true;
    });
    return v;
  };
  const out = [];
  msg(buf.length, (f, t) => {
    if (f !== 3) return false;
    const len = varint(), end = p + len, keys = [], vals = [], feats = [];
    msg(end, (g, u) => {
      if (g === 3) { const n = varint(); keys.push(buf.toString('utf8', p, p + n)); p += n; }
      else if (g === 4) { const n = varint(), e = p + n; vals.push(value(e)); p = e; }
      else if (g === 2) {
        const n = varint(), fe = p + n, tags = [];
        msg(fe, (h, w) => { if (h !== 2) return false; const m = varint(), te = p + m; while (p < te) tags.push(varint()); return true; });
        feats.push(tags);
      } else return false;
      return true;
    });
    for (const tags of feats) { const o = {}; for (let i = 0; i < tags.length; i += 2) o[keys[tags[i]]] = vals[tags[i + 1]]; out.push(o); }
    return true;
  });
  return out;
}

async function fires() {
  const days = [];
  for (let d = new Date('2026-01-01T00:00:00Z'); d <= new Date(`${LAST}T00:00:00Z`); d.setUTCDate(d.getUTCDate() + 1)) days.push(d.toISOString().slice(0, 10));
  let done = 0;
  await pool(days, 6, async day => {
    const out = path.join(RAW, 'fires', `${day}.json`);
    if (fs.existsSync(out)) return;
    let b = await get(`https://gibs.earthdata.nasa.gov/wmts/epsg4326/best/VIIRS_NOAA20_Thermal_Anomalies_375m_All/default/${day}/500m/3/2/8.mvt`);
    if (!b) { console.warn(`no tile for ${day}`); return; }
    if (b[0] === 0x1f) b = zlib.gunzipSync(b);
    const seen = new Set(), rows = [];
    for (const f of mvtProps(b)) {
      const lng = f.LONGITUDE, lat = f.LATITUDE;
      if (!(lng >= BBOX[0] && lng <= BBOX[2] && lat >= BBOX[1] && lat <= BBOX[3])) continue;
      const k = `${lat},${lng},${f.ACQ_TIME}`;
      if (seen.has(k)) continue;
      seen.add(k);
      rows.push([lng, lat, f.ACQ_DATE, f.ACQ_TIME, f.FRP, f.CONFIDENCE, f.DAYNIGHT]);
    }
    fs.writeFileSync(out, JSON.stringify(rows));
    if (++done % 25 === 0) console.log(`fires: ${done} days`);
  });
}

// ArcGIS REST query -> GeoJSON, generalised to ~200 m, paged.
async function arcgis(file, layerUrl, offset = 0.002) {
  const out = path.join(RAW, file);
  if (fs.existsSync(out)) return;
  const feats = [];
  for (let start = 0; ; start += 500) {
    const q = new URLSearchParams({ where: '1=1', geometry: BBOX.join(','), geometryType: 'esriGeometryEnvelope', inSR: '4326', spatialRel: 'esriSpatialRelIntersects',
      outFields: '*', outSR: '4326', maxAllowableOffset: String(offset), geometryPrecision: '5', resultOffset: String(start), resultRecordCount: '500', f: 'geojson' });
    const j = JSON.parse((await get(`${layerUrl}/query?${q}`, 6)).toString());
    feats.push(...j.features);
    if (j.features.length < 500) break;
  }
  fs.writeFileSync(out, JSON.stringify({ type: 'FeatureCollection', features: feats }));
  console.log(`${file}: ${feats.length} features`);
}

async function geoBoundaries(file, iso, adm) {
  if (fs.existsSync(path.join(RAW, file))) return;
  const meta = JSON.parse((await get(`https://www.geoboundaries.org/api/current/gbOpen/${iso}/${adm}/`)).toString());
  await save(file, meta.gjDownloadURL);
}

// Terrarium tiles at zoom 8 covering the box.
async function terrain() {
  const z = 8, n = 2 ** z;
  const tx = lng => Math.floor((lng + 180) / 360 * n);
  const ty = lat => Math.floor((1 - Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)) / Math.PI) / 2 * n);
  const jobs = [];
  for (let x = tx(BBOX[0]); x <= tx(BBOX[2]); x++) for (let y = ty(BBOX[3]); y <= ty(BBOX[1]); y++) jobs.push([x, y]);
  await pool(jobs, 6, ([x, y]) => save(`terrain/${z}/${x}/${y}.png`, `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/${z}/${x}/${y}.png`));
  console.log(`terrain: ${jobs.length} tiles`);
}

(async () => {
  const GFW = 'https://gis-gfw.wri.org/arcgis/rest/services';
  await arcgis('peat-idn.geojson', `${GFW}/country_data/asia/MapServer/10`);
  await arcgis('peat-mys.geojson', `${GFW}/country_data/asia/MapServer/9`);
  await arcgis('ifl2016.geojson', `${GFW}/forest_cover/MapServer/19`, 0.003);
  await geoBoundaries('adm-idn.geojson', 'IDN', 'ADM1');
  await geoBoundaries('adm-mys.geojson', 'MYS', 'ADM1');
  await geoBoundaries('adm-brn.geojson', 'BRN', 'ADM0');
  await save('ne_10m_land.zip', 'https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip');
  await save('ne_10m_populated_places_simple.zip', 'https://naciscdn.org/naturalearth/10m/cultural/ne_10m_populated_places_simple.zip');
  await save('HydroRIVERS_v10_au_shp.zip', 'https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_au_shp.zip');
  await terrain();
  await fires();
  console.log('done');
})().catch(e => { console.error(e); process.exit(1); });
