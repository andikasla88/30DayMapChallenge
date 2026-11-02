"""Day 13 · Interactions: bake od.js from the raw LTA origin-destination file and sgraildata.

Steps
1. Stations: the station points of cheeaun/sgraildata (one per station; a duplicate
   Admiralty point is dropped). Each station's codes ("NS1-EW24") index it.
2. OD codes: LTA joins an interchange's codes with "/" ("EW24/NS1"). Every part of a code
   must point at the same sgraildata station, or the script stops. Stevens appears under
   two separate codes (DT10 and TE11); both become one station, and the few trips between
   the two (entered on one line's side, left on the other's) are kept as "same station".
3. Time bands, by the hour a trip started (TIME_PER_HOUR). Trains run from about 5:30 am
   to just past midnight, so the file has hours 5 to 23 and 0:
     am    morning peak  5 am - 10 am  (hours 5-9, from the first trains)
     mid   midday       10 am -  5 pm  (hours 10-16)
     pm    evening peak  5 pm -  8 pm  (hours 17-19)
     night night         8 pm -  1 am  (hours 20-23 and 0)
   Every hour in the file falls in exactly one band, so the bands add up to the day.
4. Day types stay apart: WEEKDAY and WEEKENDS/HOLIDAY. The number of days of each type in
   the month comes from the calendar and MOM's public-holiday list (holidays count as
   weekends in LTA's file), so the page can also say "about N a day".
   https://www.mom.gov.sg/employment-practices/public-holidays
5. Output (compact JSON):
     st:    [name, "codes", lng*1e5, lat*1e5] per station, sorted by name
     od:    per origin station, a flat list: [dest gap, wd am, wd mid, wd pm, wd night,
            we am, we mid, we pm, we night, dest gap, ...]; dest gap = dest index minus the
            previous dest index (the first is the index itself + 1). Pairs with no trips
            at all are left out.
     same:  {station index: [8 values]} trips that entered and left at the same station.
     hr:    per station [out wd x20, out we x20, in wd x20, in we x20]: trips starting
            (out) or ending (in) there, by hour from 5 am to midnight (hours 5..23, 0).
            "In" is counted by the hour the trip started, as in LTA's file.
     lines: rail lines for context, [name, [part, ...]], each part a flat list of
            delta-coded lng/lat*1e5 pairs. Lines are cut back to their open stations.
   The script checks that every total adds up (per day type, per band, per station)
   against the raw file before writing.

Requirements: Python 3.9+, standard library only.
usage: python process.py <raw-dir> <out-json>
"""
import collections
import csv
import datetime as dt
import io
import json
import math
import pathlib
import sys
import zipfile

RAW = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
YM = (RAW / 'od_train_month.txt').read_text().strip()

DAYS = ['WEEKDAY', 'WEEKENDS/HOLIDAY']
BANDS = [('am', 'Morning peak', [5, 6, 7, 8, 9]), ('mid', 'Midday', list(range(10, 17))),
         ('pm', 'Evening peak', [17, 18, 19]), ('night', 'Night', [20, 21, 22, 23, 0, 1, 2, 3, 4])]
BAND_OF = {h: b for b, (_, _, hs) in enumerate(BANDS) for h in hs}
HOURS = list(range(5, 24)) + [0]            # the strip: 5 am .. 11 pm, then the midnight hour
HOUR_IX = {h: i for i, h in enumerate(HOURS)}
assert sorted(BAND_OF) == list(range(24))

# Public holidays (gazetted, with the Monday in lieu when one falls on a Sunday), from MOM.
HOLIDAYS = {2026: ['2026-01-01', '2026-02-17', '2026-02-18', '2026-03-21', '2026-04-03', '2026-05-01', '2026-05-27',
                   '2026-05-31', '2026-06-01', '2026-08-09', '2026-08-10', '2026-11-08', '2026-11-09', '2026-12-25']}
y, m = int(YM[:4]), int(YM[4:])
if y not in HOLIDAYS:
    sys.exit(f'Add the {y} public holidays from MOM to HOLIDAYS first.')
hol = {dt.date.fromisoformat(d) for d in HOLIDAYS[y]}
first = dt.date(y, m, 1)
month_days = [first + dt.timedelta(k) for k in range(31) if (first + dt.timedelta(k)).month == m]
N_WD = sum(1 for d in month_days if d.weekday() < 5 and d not in hol)
N_WE = len(month_days) - N_WD
print(f'{YM}: {N_WD} weekdays, {N_WE} weekend days and public holidays')

# ---------- 1. stations ----------
g = json.loads((RAW / 'sg-rail.geojson').read_text(encoding='utf-8'))
stations, by_code, seen = [], {}, set()
for f in g['features']:
    p = f['properties']
    if f['geometry']['type'] != 'Point' or p.get('stop_type') != 'station':
        continue
    name = p['name'].strip()
    if name in seen:
        continue
    seen.add(name)
    codes = p['station_codes'].split('-')
    s = {'name': name, 'codes': codes, 'xy': f['geometry']['coordinates']}
    stations.append(s)
    for c in codes:
        assert c not in by_code, c
        by_code[c] = s
print(len(stations), 'sgraildata stations')

# ---------- 2. OD file ----------
z = zipfile.ZipFile(RAW / f'od_train_{YM}.zip')
rows = list(csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8-sig')))
head, rows = rows[0], rows[1:]
H = {k: i for i, k in enumerate(head)}
assert {r[H['YEAR_MONTH']] for r in rows} == {f'{YM[:4]}-{YM[4:]}'}
assert {r[H['PT_TYPE']] for r in rows} == {'TRAIN'}

od_codes = sorted({r[H['ORIGIN_PT_CODE']] for r in rows} | {r[H['DESTINATION_PT_CODE']] for r in rows})
code_station, unmatched = {}, []
for oc in od_codes:
    hits = {id(by_code[c]): by_code[c] for c in oc.split('/') if c in by_code}
    missing = [c for c in oc.split('/') if c not in by_code]
    if len(hits) != 1 or missing:
        unmatched.append((oc, missing, [h['name'] for h in hits.values()]))
        continue
    code_station[oc] = next(iter(hits.values()))
if unmatched:
    for u in unmatched:
        print('UNMATCHED', u)
    sys.exit('Some OD codes could not be matched to exactly one station.')

used = {id(s): s for s in code_station.values()}
st = sorted(used.values(), key=lambda s: s['name'].lower())
IX = {id(s): i for i, s in enumerate(st)}
shared = collections.defaultdict(list)
for oc, s in code_station.items():
    shared[s['name']].append(oc)
for name, ocs in shared.items():
    if len(ocs) > 1:
        print('merged', ocs, '->', name)
print(len(od_codes), 'OD codes ->', len(st), 'stations')
print('sgraildata stations not in the OD file:', sorted(s['name'] for s in stations if id(s) not in used))

# The codes to show for a station: the OD file's codes, in sgraildata's order.
def show_codes(s):
    have = {c for oc in shared[s['name']] for c in oc.split('/')}
    return ' '.join(c for c in s['codes'] if c in have)

# ---------- 3. aggregate ----------
N = len(st)
pair = collections.defaultdict(lambda: [0] * 8)
same = collections.defaultdict(lambda: [0] * 8)
hr = [[0] * 80 for _ in range(N)]
raw_tot = collections.Counter()
raw_band = collections.Counter()
for r in rows:
    d = DAYS.index(r[H['DAY_TYPE']])
    h = int(r[H['TIME_PER_HOUR']])
    t = int(r[H['TOTAL_TRIPS']])
    o = IX[id(code_station[r[H['ORIGIN_PT_CODE']]])]
    e = IX[id(code_station[r[H['DESTINATION_PT_CODE']]])]
    k = d * 4 + BAND_OF[h]
    (same[o] if o == e else pair[(o, e)])[k] += t
    hr[o][d * 20 + HOUR_IX[h]] += t
    hr[e][40 + d * 20 + HOUR_IX[h]] += t
    raw_tot[d] += t
    raw_band[k] += t

# ---------- 4. checks: everything adds up ----------
for d in range(2):
    agg = sum(v[d * 4 + b] for v in list(pair.values()) + list(same.values()) for b in range(4))
    assert agg == raw_tot[d], (d, agg, raw_tot[d])
    assert sum(hr[i][d * 20 + j] for i in range(N) for j in range(20)) == raw_tot[d]
    assert sum(hr[i][40 + d * 20 + j] for i in range(N) for j in range(20)) == raw_tot[d]
    for b in range(4):
        k = d * 4 + b
        assert sum(v[k] for v in list(pair.values()) + list(same.values())) == raw_band[k]
        hsum = sum(hr[i][d * 20 + HOUR_IX[h]] for i in range(N) for h in BANDS[b][2] if h in HOUR_IX)
        assert hsum == raw_band[k], (k, hsum, raw_band[k])
for i in range(N):   # per station: pairs out + same == its hourly departures; pairs in + same == arrivals
    for d in range(2):
        own = sum(same.get(i, [0] * 8)[d * 4:d * 4 + 4])
        out_ = sum(v[d * 4 + b] for (o, e), v in pair.items() if o == i for b in range(4)) + own
        in_ = sum(v[d * 4 + b] for (o, e), v in pair.items() if e == i for b in range(4)) + own
        assert out_ == sum(hr[i][d * 20:d * 20 + 20]), (st[i]['name'], d)
        assert in_ == sum(hr[i][40 + d * 20:40 + d * 20 + 20]), (st[i]['name'], d)
print('checks passed: totals per day type, per band, per hour and per station all match the raw file')
print('weekday trips', raw_tot[0], 'weekend/holiday trips', raw_tot[1])
print('same-station trips', {st[i]['name']: v for i, v in same.items()})

# ---------- 5. rail lines for context, cut back to open stations ----------
PREFIX = {'North South Line': ['NS'], 'East West Line': ['EW', 'CG'], 'North East Line': ['NE'], 'Circle Line': ['CC'],
          'Downtown Line': ['DT'], 'Thomson-East Coast Line': ['TE'], 'Bukit Panjang LRT': ['BP'],
          'Sengkang LRT (East Loop)': ['SE', 'STC'], 'Sengkang LRT (West Loop)': ['SW', 'STC'],
          'Punggol LRT (East Loop)': ['PE', 'PTC'], 'Punggol LRT (West Loop)': ['PW', 'PTC']}
open_codes = {c for oc in od_codes for c in oc.split('/')}
KX, KY = 111320 * math.cos(math.radians(1.35)), 110574


def dist(a, b):
    return math.hypot((a[0] - b[0]) * KX, (a[1] - b[1]) * KY)


def strip_prefix(c):
    return ''.join(ch for ch in c if ch.isalpha())


lines = []
for f in g['features']:
    gm = f['geometry']
    if gm['type'] not in ('LineString', 'MultiLineString'):
        continue
    name = f['properties']['name']
    pre = PREFIX[name]
    on_line = [s for s in st if any(strip_prefix(c) in pre for c in s['codes'] if c in open_codes or strip_prefix(c) in ('STC', 'PTC'))]
    parts = [gm['coordinates']] if gm['type'] == 'LineString' else gm['coordinates']
    out_parts = []
    for part in parts:
        near = [min(range(len(part)), key=lambda k: dist(part[k], s['xy'])) for s in on_line]
        near = [k for k, s in zip(near, on_line) if dist(part[k], s['xy']) < 400]
        if not near:
            continue
        a, b = min(near), max(near)
        loop = 'Loop' in name
        seg = part if loop else part[a:b + 1]
        if not loop and (a > 0 or b < len(part) - 1):
            cut = sum(dist(part[k], part[k + 1]) for k in list(range(0, a)) + list(range(b, len(part) - 1)))
            if cut > 150:
                print(f'cut {name}: {cut:.0f} m of track beyond its last open station')
        flat, px, py = [], 0, 0
        for x, y in seg:
            X, Y = round(x * 1e5), round(y * 1e5)
            if (X, Y) == (px, py) and flat:
                continue
            flat += [X - px, Y - py]
            px, py = X, Y
        out_parts.append(flat)
    lines.append([name, out_parts])

# ---------- 6. write ----------
od = []
for o in range(N):
    flat, prev = [], -1
    for e in range(N):
        v = pair.get((o, e))
        if v and any(v):
            flat += [e - prev] + v
            prev = e
    od.append(flat)
hr_out = [row for row in hr]
data = {
    'month': f'{YM[:4]}-{YM[4:]}',
    'bands': [[k, label, hs] for k, label, hs in BANDS],
    'hours': HOURS,
    'st': [[s['name'], show_codes(s), round(s['xy'][0] * 1e5), round(s['xy'][1] * 1e5)] for s in st],
    'od': od,
    'same': {str(i): v for i, v in same.items()},
    'hr': hr_out,
    'total': [raw_tot[0], raw_tot[1]],
    'days': [N_WD, N_WE],
    'lines': lines,
}
OUT.write_text('window.DAY13 = ' + json.dumps(data, separators=(',', ':')) + ';\n')
print('wrote', OUT, OUT.stat().st_size, 'bytes;', sum(len(x) // 9 for x in od), 'station pairs')

# ---------- 7. headline facts (for the report; the page computes its own from the file) ----------
dep = [sum(hr[i][0:20]) for i in range(N)]
top = sorted(range(N), key=lambda i: -dep[i])[:5]
print('busiest weekday origins:', [(st[i]['name'], dep[i]) for i in top])
best = max(pair.items(), key=lambda kv: sum(kv[1][0:4]))
print('busiest weekday pair:', st[best[0][0]]['name'], '->', st[best[0][1]]['name'], sum(best[1][0:4]))
