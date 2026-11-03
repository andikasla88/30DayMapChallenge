// Day 04 data prep, step 3 of 3: how tightly each trade huddles, where, and the compact file the page
// loads (window.DAY04).
//
// Unit: one business address. ACRA lists entities; a trade's addresses are the distinct
// (postal code, level, unit) among its live entities whose primary SSIC is that trade. Addresses that
// host 10 or more live entities of any kind are dropped first: those are registered-office
// services (corporate secretaries, accountants), not shopfronts.
//
// Huddle: lay a 150 m grid over the island and count, for a trade's addresses, the fewest cells
// that hold half of them (the "half area"). Draw the same number of addresses at random from all
// businesses and measure theirs the same way (mean of 40 draws). Huddle = random half area / the
// trade's half area: 10x means the trade packs into a tenth of the ground an ordinary mix of
// businesses of the same size would need.
//
// Hotspots: buildings (postal codes) taken greedily from the busiest, each absorbing every other
// address of the trade within 200 m; the four biggest of the first ten are kept. Named after the top building when it holds half the hotspot,
// else after its road. A building's name is the one its businesses most often give ACRA (OneMap
// lists every point of interest at a postal code, ATMs and consulates included).
//
// usage: node analyse.mjs <raw dir> <out.js>
//   reads <raw>/live.json (prep.mjs), <raw>/postal.json (geocode.mjs), <raw>/postal_xkjyeah.json
//   (road names), <raw>/ssic2025.json (SSIC 2025 titles, from SingStat's classification structure)
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [RAW, OUT] = process.argv.slice(2);
const read = f => JSON.parse(readFileSync(join(RAW, f), 'utf8'));

// The trades on the page: SSIC 2025 sub-class, what people call it, and a shelf.
const CATS = { shop: 'Shops', care: 'Looks & wellness', health: 'Doctors', money: 'Money', service: 'Services', night: 'Night out', motor: 'Cars & bikes', work: 'Workshops & offices' };
const TRADES = [
  ['47412', 'Computer shops', 'shop'], ['47411', 'Handphone shops', 'shop'], ['47752', 'Camera shops', 'shop'],
  ['47650', 'Music shops', 'shop'], ['47733', 'Watch shops', 'shop'], ['47731', 'Jewellers', 'shop'],
  ['47741', 'Art & antique dealers', 'shop'], ['47510', 'Fabric shops', 'shop'], ['47531', 'Furniture shops', 'shop'],
  ['47761', 'Joss paper shops', 'shop'], ['47745', 'Aquarium shops', 'shop'], ['47751', 'Opticians', 'shop'],
  ['47723', 'Chinese medicine halls', 'shop'], ['47770', 'Second-hand shops', 'shop'],
  ['96021', 'Hair salons', 'care'], ['96023', 'Nail salons', 'care'], ['96022', 'Beauty salons & spas', 'care'],
  ['96024', 'Massage & reflexology', 'care'], ['14103', 'Tailors', 'care'],
  ['86203', 'Specialist doctors', 'health'], ['86201', 'GP clinics', 'health'], ['86202', 'TCM clinics', 'health'], ['86204', 'Dentists', 'health'],
  ['66126', 'Money-changers', 'money'], ['64924', 'Moneylenders', 'money'], ['64925', 'Pawnshops', 'money'],
  ['64993', 'Remittance shops', 'money'], ['66309', 'Fund managers', 'money'],
  ['78103', 'Maid agencies', 'service'], ['96030', 'Funeral services', 'service'], ['79102', 'Travel agencies', 'service'], ['69101', 'Law firms', 'service'],
  ['93203', 'Karaoke & nightclubs', 'night'], ['56130', 'Pubs', 'night'], ['55101', 'Hotels', 'night'],
  ['95301', 'Car workshops', 'motor'], ['47311', 'Car dealers', 'motor'], ['47312', 'Motorcycle shops', 'motor'],
  ['47314', 'Car parts shops', 'motor'], ['95302', 'Car washes', 'motor'], ['77101', 'Car rental', 'motor'],
  ['46302', 'Fish & meat wholesalers', 'work'], ['46301', 'Fruit & veg wholesalers', 'work'], ['31001', 'Furniture makers', 'work'],
  ['43301', 'Renovation contractors', 'work'], ['50021', 'Shipping lines', 'work'], ['18112', 'Printers', 'work'], ['32901', 'Sign makers', 'work'],
];
const MASS = 10, CELL = 150, DRAWS = 40, HOT_R = 200;

const live = read('live.json'), pos = read('postal.json'), ssicT = read('ssic2025.json');
const C = Object.fromEntries(live.cols.map((k, i) => [k, i]));
const road = {};
for (const b of read('postal_xkjyeah.json')) if (!road[b.POSTAL] && b.ROAD_NAME && b.ROAD_NAME !== 'NIL') road[b.POSTAL] = b.ROAD_NAME;

// small metric frame around Singapore
const LAT0 = 1.35 * Math.PI / 180, KX = 111320 * Math.cos(LAT0), KY = 110574;
const xy = p => [p[0] * KX, p[1] * KY];
const cellOf = p => { const [x, y] = xy(p); return Math.floor(x / CELL) * 100000 + Math.floor(y / CELL); };

const addrN = new Map();
const akey = r => r[C.postal] + '|' + r[C.level] + '|' + r[C.unit];
for (const r of live.rows) addrN.set(akey(r), (addrN.get(akey(r)) || 0) + 1);

// every kept address once (the background, and the pool for random draws), and each trade's addresses
const allAddr = new Map(), byTrade = new Map(TRADES.map(t => [t[0], new Map()]));
const acraB = {}, acraS = {};   // postal -> { building, or street, as given to ACRA: count }
let massDrop = 0, unplaced = 0;
for (const r of live.rows) {
  const k = akey(r), pc = r[C.postal];
  if (addrN.get(k) >= MASS) { massDrop++; continue; }
  if (!pos[pc]) { unplaced++; continue; }
  allAddr.set(k, pc);
  if (byTrade.has(r[C.ssic])) byTrade.get(r[C.ssic]).set(k, pc);
  for (const [tab, w] of [[acraB, r[C.building]], [acraS, r[C.street]]]) {
    const v = w.replace(/\s+/g, ' ').trim();
    if (v) { const nm = (tab[pc] ||= {}); nm[v] = (nm[v] || 0) + 1; }
  }
}
const pool = [...allAddr.values()];
console.error(`entities ${live.rows.length}, dropped at mass addresses ${massDrop}, unplaced ${unplaced}, addresses kept ${pool.length}`);

function halfCells(postals) {
  const m = new Map();
  for (const pc of postals) { const c = cellOf(pos[pc]); m.set(c, (m.get(c) || 0) + 1); }
  const v = [...m.values()].sort((a, b) => b - a);
  let acc = 0, i = 0;
  while (acc * 2 < postals.length) acc += v[i++];
  return i;
}
let seed = 20261104;
const rand = () => ((seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32);
function expectedHalf(n) {
  let s = 0;
  for (let d = 0; d < DRAWS; d++) { const smp = []; for (let i = 0; i < n; i++) smp.push(pool[Math.floor(rand() * pool.length)]); s += halfCells(smp); }
  return s / DRAWS;
}

const SMALL = new Set(['of', 'the', 'and', 'at', 'on', 'by', 'de', 'la']);
const KEEP = new Set(['AMK', 'KB', 'HDB', 'JTC', 'NTUC', 'UOB', 'OCBC', 'SGX', 'II', 'III', 'IV', 'SAFRA', 'CT', 'PSA', 'MRT', 'ITE', 'UE', 'WCEGA', 'YS', 'CPF', 'DBS', 'OUE', 'ICA']);
const title = s => s.toLowerCase().replace(/[a-z0-9'’]+/g, (w, i) => {
  const U = w.toUpperCase();
  if (KEEP.has(U)) return U;
  if (i > 0 && SMALL.has(w)) return w;
  return w[0].toUpperCase() + w.slice(1);
}).replace(/\bSingapore$/, '').replace(/\s+/g, ' ').trim();
const modal = m => { const a = Object.entries(m || {}).sort((x, y) => y[1] - x[1])[0]; return a ? a[0] : ''; };
// names as people know them, where ACRA's most common spelling is a hotel brand or a long form
const ALIAS = { 'Peninsula Excelsior Singapore,A Wyndham Hotel': 'Peninsula Shopping Centre', 'Wyndham Singapore, Peninsula Shopping Complex': 'Peninsula Shopping Centre',
  'Peninsula Shopping Complex': 'Peninsula Shopping Centre', 'Zhujiao Centre (Tekka Market)': 'Tekka Centre', 'Queensway Shopping Centre/Queensway Tower': 'Queensway Shopping Centre',
  'Wholesale Centre': 'Pasir Panjang Wholesale Centre', 'Square 2': 'Novena Square 2' };
const placeName = pc => { const t = title(modal(acraB[pc])); return ALIAS[t] || t; };
const roadOf = pc => { const t = title(road[pc] || modal(acraS[pc])); return ALIAS[t] || t; };

// the island's postal codes, each with its count of kept addresses: the background, and the index trades refer to
const pcCount = new Map();
for (const pc of pool) pcCount.set(pc, (pcCount.get(pc) || 0) + 1);
const PCS = [...pcCount.keys()].sort((a, b) => pos[a][0] - pos[b][0] || pos[a][1] - pos[b][1]);
const pcIdx = new Map(PCS.map((pc, i) => [pc, i]));

const trades = [];
for (const [ssic, name, cat] of TRADES) {
  const postals = [...byTrade.get(ssic).values()], n = postals.length;
  const half = halfCells(postals), exp = expectedHalf(n);
  // per building
  const per = new Map();
  for (const pc of postals) per.set(pc, (per.get(pc) || 0) + 1);
  const bl = [...per.entries()].sort((a, b) => b[1] - a[1]);
  // hotspots
  const used = new Set();
  let hot = [];
  for (const [pc] of bl) {
    if (used.has(pc) || hot.length >= 10) continue;
    const [x0, y0] = xy(pos[pc]);
    let cnt = 0, sx = 0, sy = 0; const members = [];
    for (const [q, c] of bl) {
      if (used.has(q)) continue;
      const [x, y] = xy(pos[q]);
      if (Math.hypot(x - x0, y - y0) <= HOT_R) { used.add(q); cnt += c; sx += pos[q][0] * c; sy += pos[q][1] * c; members.push([q, c]); }
    }
    if (cnt < 5) continue;
    const top = members[0];
    const label = top[1] * 2 >= cnt && placeName(top[0]) ? placeName(top[0]) : roadOf(top[0]);
    hot.push([label, +(sx / cnt).toFixed(5), +(sy / cnt).toFixed(5), cnt, top[1]]);
  }
  hot = hot.sort((a, b) => b[3] - a[3]).slice(0, 4);   // the four biggest of the first ten found
  const p = [];
  for (const [pc, c] of bl.sort((a, b) => pcIdx.get(a[0]) - pcIdx.get(b[0]))) p.push(pcIdx.get(pc), c);
  trades.push({ ssic, name, cat, title: ssicT[ssic], n, half: +(half * CELL * CELL / 1e6).toFixed(3), exp: +(exp * CELL * CELL / 1e6).toFixed(3),
    x: +(exp / half).toFixed(1), hot, p });
  console.error(`${(exp / half).toFixed(1).padStart(5)}x ${String(n).padStart(5)} ${name.padEnd(30)} ${hot.map(h => `${h[0]} ${h[3]}`).join(' | ')}`);
}
trades.sort((a, b) => b.x - a.x);

// postal table: lng, lat as integers of 1e-5 degree, delta-coded in sorted order; count of addresses
const pxy = [], pn = [];
let lx = 0, ly = 0;
for (const pc of PCS) {
  const X = Math.round(pos[pc][0] * 1e5), Y = Math.round(pos[pc][1] * 1e5);
  pxy.push(X - lx, Y - ly); lx = X; ly = Y;
  pn.push(pcCount.get(pc));
}
const out = {
  v: 1, built: new Date().toISOString().slice(0, 10),
  source: 'ACRA Information on Corporate Entities (data.gov.sg collection 2), live entities; SSIC 2025 (SingStat); postal code locations from OneMap',
  method: { mass: MASS, cell: CELL, draws: DRAWS, hotR: HOT_R },
  stats: { entities: live.rows.length, massDrop, addresses: pool.length, half: +(halfCells(pool) * CELL * CELL / 1e6).toFixed(1) },
  cats: CATS, pxy, pn, trades,
};
writeFileSync(OUT, `window.DAY04 = ${JSON.stringify(out)};\n`);
console.error('wrote', OUT, Math.round(JSON.stringify(out).length / 1024), 'kB; postal codes', PCS.length);
