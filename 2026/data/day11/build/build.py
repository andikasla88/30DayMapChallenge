"""Day 11 · Sound: bake storm.json from the raw lightning days that fetch.py saved.

Steps
1. Read every raw day file. Each 2-minute record lists the strikes of the 2 minutes before
   it; a few strikes sit in two records, so readings are de-duplicated on
   (timestamp to the millisecond, latitude, longitude, type).
2. Each strike is filed under its own timestamp's date (Singapore time, UTC+8), so the
   00:00 record's strikes from 23:58-24:00 go back to the day before.
3. Days are ranked by unique reading ("strike") count. A day counts as complete if at most
   two of its 720 records are missing and the next day (for its 00:00 record) was fetched.
   Missing records are listed in stats.gaps: the feed itself skips the odd 2 minutes.
4. The stormiest day is written sorted by time and packed into one string (see 'encoding'
   in the output): per strike the milliseconds since the strike before with a
   cloud-to-ground flag ("G" in the feed; "C" is cloud-to-cloud), then the steps in
   x = round((lng - X0) * 1e4) and y = round((lat - Y0) * 1e4) (the feed gives 4 decimals).
   Lossless (checked below), so the page gets back exactly the feed's time, place and type.
   Alongside: the scan summary, the feed's coverage (the extent of every strike in the
   scan), where the replay starts, and the headline numbers the page shows.

Standard library only (no pip installs needed).
usage: python build.py <raw-dir> <out-json> [listener-lng listener-lat]
"""
import json, sys, math, pathlib, datetime as dt, collections

RAW = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2])
LIS = (float(sys.argv[3]), float(sys.argv[4])) if len(sys.argv) > 4 else (103.8485, 1.3510)   # near Bishan
SGT = dt.timezone(dt.timedelta(hours=8))
X0, Y0 = 103.0, 0.8
HEAR_KM = 20


def km(a, b):
    # Ground distance from a (the listener) to b, on the WGS84 ellipsoid's local scale at the
    # listener: 111.3195 km per degree of longitude times cos(latitude), 110.574 km per degree
    # of latitude. Within 20 km this is good to metres, and it is what the page computes.
    kx = 111.3195 * math.cos(math.radians(a[1]))
    return math.hypot((b[0] - a[0]) * kx, (b[1] - a[1]) * 110.574)


files = sorted(RAW.glob('lightning_*.json'))
if not files:
    sys.exit(f'no raw files in {RAW}; run fetch.py first')
strikes = {}                      # key -> (datetime, lng, lat, g)
records_by_date = collections.Counter()
fetched = set()
for f in files:
    doc = json.loads(f.read_text())
    fetched.add(doc['date'])
    for r in doc['records']:
        rt = dt.datetime.fromisoformat(r['datetime'])
        records_by_date[rt.date().isoformat()] += 1
        for x in r['item'].get('readings') or []:
            lat, lng, typ = x['location']['latitude'], x['location']['longitude'], x['type']
            key = (x['datetime'], lat, lng, typ)
            if key in strikes: continue
            strikes[key] = (dt.datetime.fromisoformat(x['datetime']).astimezone(SGT), float(lng), float(lat), typ)

types = collections.Counter((k[3]) for k in strikes)
by_day = collections.defaultdict(list)
for s in strikes.values():
    by_day[s[0].date().isoformat()].append(s)


def complete(d):   # every 2-minute record there, or at most two missing (the feed has the odd gap)
    nxt = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
    return records_by_date[d] >= 718 and nxt in fetched


def gaps(d):   # the 2-minute windows with no record: a record stamped T covers [T - 2 min, T)
    have = set()
    for f in (RAW / f'lightning_{d}.json',):
        have |= {dt.datetime.fromisoformat(r['datetime']) for r in json.loads(f.read_text())['records']}
    n = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
    for nxt in (RAW / f'lightning_{n}.json', RAW / f'lightning_{n}_midnight.json'):
        if nxt.exists():
            have |= {dt.datetime.fromisoformat(r['datetime']) for r in json.loads(nxt.read_text())['records']}
    m0 = dt.datetime.fromisoformat(d + 'T00:00:00+08:00')
    out = []
    for k in range(1, 721):
        stamp = m0 + dt.timedelta(minutes=2 * k)
        if stamp not in have:
            out.append([(k - 1) * 120000, k * 120000])
    return out


days = sorted(d for d in fetched)
scan = []
for d in days:
    ss = by_day.get(d, [])
    scan.append([d, len(ss), sum(1 for s in ss if s[3] == 'G'), int(complete(d))])
ranked = sorted((s for s in scan if s[3]), key=lambda s: -s[1])
if not ranked:
    sys.exit('no complete day yet')
best = ranked[0][0]
print('scan', days[0], '..', days[-1], len(days), 'days;', sum(1 for s in scan if s[3]), 'complete')
print('top days:', ranked[:6])
print('types over the scan:', dict(types))

S = sorted(by_day[best], key=lambda s: s[0])
midnight = dt.datetime.fromisoformat(best + 'T00:00:00+08:00')
lngs = [s[1] for s in strikes.values()]; lats = [s[2] for s in strikes.values()]
cover = [min(lngs), min(lats), max(lngs), max(lats)]
print('coverage of every strike in the scan:', cover)

t_ms = [round((s[0] - midnight).total_seconds() * 1000) for s in S]
dts = [t_ms[0]] + [t_ms[i] - t_ms[i - 1] for i in range(1, len(t_ms))]
xs = [round((s[1] - X0) * 1e4) for s in S]
ys = [round((s[2] - Y0) * 1e4) for s in S]
g = ''.join('1' if s[3] == 'G' else '0' for s in S)
assert all(x >= 0 for x in xs + ys) and all(d >= 0 for d in dts)


# Pack every strike into one string, Google-polyline style (5 bits a character, chr(v + 63)):
#   (dt << 1 | cloud-to-ground), then the zig-zagged steps in x and in y from the strike before.
# Lossless: the page decodes exactly the integers above.
def put(v, out):
    while v >= 0x20:
        out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
    out.append(chr(v + 63))


zz = lambda v: v << 1 if v >= 0 else ~(v << 1)
packed, px, py = [], 0, 0
for k in range(len(S)):
    put(dts[k] << 1 | (g[k] == '1'), packed)
    put(zz(xs[k] - px), packed); put(zz(ys[k] - py), packed)
    px, py = xs[k], ys[k]
packed = ''.join(packed)


def unpack(s):   # the same decoder the page runs, to prove the packing is lossless
    i, out, vals = 0, [], []
    while i < len(s):
        v, sh = 0, 0
        while True:
            b = ord(s[i]) - 63; i += 1
            v |= (b & 0x1f) << sh; sh += 5
            if b < 0x20: break
        vals.append(v)
    t = x = y = 0
    for k in range(0, len(vals), 3):
        a, bx, by = vals[k:k + 3]
        t += a >> 1; x += ~(bx >> 1) if bx & 1 else bx >> 1; y += ~(by >> 1) if by & 1 else by >> 1
        out.append((t, x, y, a & 1))
    return out


assert unpack(packed) == [(t_ms[k], xs[k], ys[k], int(g[k] == '1')) for k in range(len(S))]

# headline numbers (the page recomputes the listener-dependent ones itself)
near = [s for s in S if km(LIS, (s[1], s[2])) <= HEAR_KM]
dist = sorted(km(LIS, (s[1], s[2])) for s in S)
minute = collections.Counter(int(t // 60000) for t in t_ms)
peak_min, peak_n = max(minute.items(), key=lambda kv: kv[1])
hours = collections.Counter(int(t // 3600000) for t in t_ms)
first, last = S[0][0], S[-1][0]
stats = {
    'strikes': len(S), 'cg': g.count('1'), 'ic': g.count('0'),
    'nearDefault': len(near), 'nearestDefaultKm': round(dist[0], 2),
    'peakMinute': f'{peak_min // 60:02d}:{peak_min % 60:02d}', 'peakMinuteStrikes': peak_n,
    'first': first.strftime('%H:%M:%S'), 'last': last.strftime('%H:%M:%S'),
    'busiestHour': max(hours.items(), key=lambda kv: kv[1]),
    'runnerUp': ranked[1][:3] if len(ranked) > 1 else None,
}
# Where the replay starts: the first minute with at least one reading a second within earshot
# of the default listener, so thunder comes at once and the storm is heard building.
near1 = collections.Counter(int(t_ms[i] // 60000) for i, s in enumerate(S) if km(LIS, (s[1], s[2])) <= HEAR_KM)
busy = [m for m, v in near1.items() if v >= 60]
start_ms = min(busy) * 60000 if busy else max(0, t_ms[0] - 60000)
stats['start'] = f'{start_ms // 3600000:02d}:{start_ms // 60000 % 60:02d}'
# the box the sensors report from, in km (east-west at its middle latitude)
mid = math.radians((cover[1] + cover[3]) / 2)
stats['coverageKm'] = [round((cover[2] - cover[0]) * 111.3195 * math.cos(mid), 1), round((cover[3] - cover[1]) * 110.574, 1)]
# how often the feed logs several readings at the very same millisecond (parts of one flash)
ms_count = collections.Counter(t_ms)
stats['sameMsShare'] = round(sum(c for c in ms_count.values() if c > 1) / len(t_ms), 3)
stats['gaps'] = gaps(best)
print('stats', stats)
out = {
    'start': start_ms,
    'date': best, 'utcOffset': '+08:00', 't0': int(midnight.timestamp() * 1000),
    'x0': X0, 'y0': Y0, 'scale': 1e4,
    'source': 'https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning&date=' + best,
    'coverage': cover, 'listener': LIS, 'hearKm': HEAR_KM,
    'scan': {'from': min(s[0] for s in scan if s[3]), 'to': max(s[0] for s in scan if s[3]), 'days': [s[:3] for s in scan if s[3]]},
    'stats': stats,
    'n': len(S),
    'encoding': 'polyline-style varints, per strike: (ms since previous strike << 1 | cloud-to-ground), '
                'zigzag step in round((lng - x0) * 1e4), zigzag step in round((lat - y0) * 1e4)',
    's': packed,
}
OUT.write_text(json.dumps(out, separators=(',', ':')))
print('wrote', OUT, OUT.stat().st_size, 'bytes,', len(S), 'strikes on', best)
