// Day 04 data prep, step 2 of 3: a location for every postal code in live.json.
// Seeds from a 2023 scrape of OneMap's postal codes (github.com/xkjyeah/singapore-postal-codes,
// buildings.json, saved as <raw>/postal_xkjyeah.json), then asks OneMap's search API for the rest.
// Without a token OneMap answers 429 to anything brisker than about a call a second, so codes are
// asked busiest first (by live entities), and [max asks] can skip the long tail of one-business
// codes. Answers are cached in <raw>/postal_onemap.json, so the script can be stopped and rerun.
// usage: node geocode.mjs <raw dir> [max asks]       writes <raw>/postal.json  { "018906": [lng, lat], ... }
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const RAW = process.argv[2];
const live = JSON.parse(readFileSync(join(RAW, 'live.json'), 'utf8'));
const iP = live.cols.indexOf('postal');
const per = {};
for (const r of live.rows) per[r[iP]] = (per[r[iP]] || 0) + 1;
const want = new Set(Object.keys(per));

const pos = {};
for (const b of JSON.parse(readFileSync(join(RAW, 'postal_xkjyeah.json'), 'utf8'))) {
  if (!pos[b.POSTAL]) pos[b.POSTAL] = [+b.LONGITUDE, +b.LATITUDE];
}
const cacheFn = join(RAW, 'postal_onemap.json');
const cache = existsSync(cacheFn) ? JSON.parse(readFileSync(cacheFn, 'utf8')) : {};   // postal -> [lng, lat] or null

const todo = [...want].filter(p => !pos[p] && !(p in cache) && +p.slice(0, 2) >= 1 && +p.slice(0, 2) <= 83)   // 01-83: real postal sectors
  .sort((a, b) => per[b] - per[a]).slice(0, +(process.argv[3] || Infinity));
console.error(`postal codes ${want.size}: ${want.size - todo.length - [...want].filter(p => !pos[p] && cache[p] === null).length} placed, ${todo.length} to ask OneMap`);
const sleep = ms => new Promise(r => setTimeout(r, ms));
let n = 0;
for (const p of todo) {
  for (let t = 0; t < 4; t++) {
    try {
      const r = await fetch(`https://www.onemap.gov.sg/api/common/elastic/search?searchVal=${p}&returnGeom=Y&getAddrDetails=Y&pageNum=1`, { signal: AbortSignal.timeout(15000) });
      if (r.status === 429) { await sleep(30000); continue; }
      const j = await r.json();
      const hit = (j.results || []).find(x => x.POSTAL === p);
      cache[p] = hit ? [+(+hit.LONGITUDE).toFixed(6), +(+hit.LATITUDE).toFixed(6)] : null;
      break;
    } catch (e) { console.error(p, 'retry', t + 1, e.name); await sleep(5000); }
  }
  if (++n % 50 === 0) { writeFileSync(cacheFn, JSON.stringify(cache)); console.error(n, '/', todo.length); }
  await sleep(1500);
}
writeFileSync(cacheFn, JSON.stringify(cache));

const out = {};
let miss = 0;
for (const p of want) { const c = pos[p] || cache[p]; if (c) out[p] = c; else miss++; }
writeFileSync(join(RAW, 'postal.json'), JSON.stringify(out));
console.error('placed', Object.keys(out).length, 'unplaced', miss);
