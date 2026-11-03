// Day 04 data prep, step 1 of 3: read ACRA's 27 entity CSVs and keep the businesses that are live
// today and have a local address, one compact row each.
// usage: node prep.mjs <raw dir>          reads <raw>/acra/*.csv, writes <raw>/live.json
import { createReadStream, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const RAW = process.argv[2];
const LIVE = new Set(['Live', 'Live Company', 'Registered']);   // every other status is closed or closing

// RFC 4180 rows from a stream: quoted fields may hold commas, quotes ("") and newlines.
async function* rows(path) {
  let field = '', row = [], q = false, closed = false;   // closed: the last char closed a quote
  for await (const chunk of createReadStream(path, { encoding: 'utf8' })) {
    for (const ch of chunk) {
      if (q) {
        if (ch === '"') { q = false; closed = true; } else field += ch;
        continue;
      }
      if (ch === '"') { if (closed) field += '"'; q = true; }   // "" inside a quoted field
      else if (ch === ',') { row.push(field); field = ''; }
      else if (ch === '\n') { row.push(field.replace(/\r$/, '')); yield row; row = []; field = ''; }
      else field += ch;
      closed = false;
    }
  }
  if (field || row.length) { row.push(field); yield row; }
}

const out = [], seen = new Set(), stat = { rows: 0, live: 0, noPostal: 0, foreign: 0, dupe: 0 };
const files = readdirSync(join(RAW, 'acra')).filter(f => f.endsWith('.csv')).sort();
for (const f of files) {
  let H = null;
  for await (const r of rows(join(RAW, 'acra', f))) {
    if (!H) { H = Object.fromEntries(r.map((k, i) => [k, i])); continue; }
    if (r.length < 20) continue;
    stat.rows++;
    const g = k => { const v = (r[H[k]] || '').trim(); return v === 'na' ? '' : v; };
    if (!LIVE.has(g('entity_status_description'))) continue;
    stat.live++;
    if (g('address_type') !== 'LOCAL') { stat.foreign++; continue; }
    const pc = g('postal_code').padStart(6, '0');
    if (!/^\d{6}$/.test(pc) || pc === '000000') { stat.noPostal++; continue; }
    const uen = g('uen');
    if (seen.has(uen)) { stat.dupe++; continue; }
    seen.add(uen);
    out.push([uen, g('entity_name'), g('entity_type_description'), g('registration_incorporation_date'),
      g('primary_ssic_code'), g('primary_ssic_description'), g('primary_user_described_activity'), g('secondary_ssic_code'),
      pc, g('block'), g('street_name'), g('building_name'), g('level_no'), g('unit_no')]);
  }
  console.error(f, stat);
}
writeFileSync(join(RAW, 'live.json'), JSON.stringify({
  cols: ['uen', 'name', 'type', 'reg', 'ssic', 'ssicDesc', 'activity', 'ssic2', 'postal', 'block', 'street', 'building', 'level', 'unit'],
  rows: out,
}));
console.error('kept', out.length, stat);
