"""Day 23 (Taste): build ../bib.js from the cached raw data. Run fetch.py first.

Requires python 3.10+ (standard library only).    usage: python -I process.py <raw-dir> <out-dir>

- Geocodes every eatery by its postal code with the cached OneMap answers and reports the match rate.
  A match is an OneMap result whose POSTAL equals the eatery's postal code exactly.
- Puts each eatery in a "venue": the NEA hawker centre it sits in (same postal code, or the NEA centre
  within 150 m of the geocode when NEA files the centre under a neighbouring block), else its own address.
- Joins the LLM dish tags from tags.json, and counts eateries per dish and per venue.
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
RAW, OUT = sys.argv[1], sys.argv[2]

src = json.load(open(os.path.join(HERE, 'stalls_source.json'), encoding='utf-8'))
tags = json.load(open(os.path.join(HERE, 'tags.json'), encoding='utf-8'))
T = {t['name']: t for t in tags['tags']}
CATS = [c[0] for c in tags['categories']]
assert set(T) == {s['name'] for s in src}, set(T) ^ {s['name'] for s in src}
assert all(t['dish'] in CATS for t in T.values())


def metres(a, b):
    kx = 111320 * math.cos(math.radians((a[1] + b[1]) / 2))
    return math.hypot((a[0] - b[0]) * kx, (a[1] - b[1]) * 110574)


# ---- NEA hawker centres ----
hc = json.load(open(os.path.join(RAW, 'hawker-centres.geojson'), encoding='utf-8'))
meta = json.load(open(os.path.join(RAW, 'hawker-centres.meta.json'), encoding='utf-8'))
NEA = []
for f in hc['features']:
    p = f['properties']
    name = p.get('NAME') or p.get('Name')
    pc = str(p.get('ADDRESSPOSTALCODE') or '').strip().zfill(6)
    lng, lat = f['geometry']['coordinates'][:2]
    NEA.append({'name': name, 'postal': pc, 'lnglat': (lng, lat), 'status': p.get('STATUS', '')})
print('NEA hawker centres:', len(NEA))

# ---- geocode ----
matched = 0
rows = []
for s in src:
    om = json.load(open(os.path.join(RAW, 'onemap', s['postal'] + '.json'), encoding='utf-8'))
    hits = [r for r in om.get('results', []) if r.get('POSTAL') == s['postal']]
    if not hits:
        print('NO MATCH', s['name'], s['postal'])
        rows.append((s, None))
        continue
    matched += 1
    words = set(re.findall(r'[a-z]+', (s['building'] or '').lower())) - {'market', 'food', 'centre', 'and', 'hawker', 'the'}
    hits.sort(key=lambda r: -len(words & set(re.findall(r'[a-z]+', r.get('BUILDING', '').lower()))))
    h = hits[0]
    road = h['ROAD_NAME'].lower()
    # sanity: OneMap's road for this postcode should appear in the address (allowing common abbreviations)
    addr = s['address'].lower().replace('lor ', 'lorong ').replace(' ave ', ' avenue ').replace(' st ', ' street ')
    ok = road.split()[0] in addr
    if not ok:
        print('CHECK road', s['name'], '|', s['address'], '| OneMap:', h['ADDRESS'])
    rows.append((s, h))
print(f'OneMap match rate: {matched}/{len(src)}')

# ---- venues ----
venues, vkey = [], {}
for s, h in rows:
    ll = (float(h['LONGITUDE']), float(h['LATITUDE']))
    nea = [n for n in NEA if n['postal'] == s['postal']]
    # Michelin names the market or food centre; NEA sometimes files it under the next block's postcode
    in_market = bool(re.search(r'market|food cent|hawker', (s['building'] or '').lower()))
    if not nea and in_market:
        near = sorted(NEA, key=lambda n: metres(n['lnglat'], ll))
        if near and metres(near[0]['lnglat'], ll) < 250:
            nea = [near[0]]
    if nea:
        raw = nea[0]['name']
        m = re.match(r'(.*?)\s*\((.*)\)$', raw)
        if m and not re.search(r'Blk ', m.group(1)):
            name = m.group(1)                     # 'Amoy Street Food Centre (Telok Ayer Food Centre)'
        elif m:
            name = m.group(2)                     # 'Upper Cross Street Blk 531A (Hong Lim Food Centre and Market)'
        else:
            name = raw if not re.search(r'Blk ', raw) else (s['building'] or raw)
        name = re.sub(r'^Blk \w+ ', '', name).replace(' and ', ' & ')
        key, kind = 'nea:' + raw, 'hawker'
    else:
        key = 'pc:' + s['postal']
        # the street address as Michelin gives it, without unit numbers and postcode
        parts = [re.sub(r'^#\S+\s*', '', p.strip()) for p in s['address'].split(',')]
        parts = [re.sub(r'^(Blk|Block) ', '', p) for p in parts if p and not re.match(r'#|Stall|Singapore\b|\d{6}$', p)
                 and p != s['building']]
        street = ''
        for j, p in enumerate(parts):   # '399', '401', '403 Balestier Road' -> '399, 401, 403 Balestier Road'; '416', 'Bedok North Avenue 2' -> '416 Bedok North Avenue 2'
            nxt = parts[j + 1] if j + 1 < len(parts) else ''
            street += p + (', ' if re.fullmatch(r'\d+\w?', p) and re.match(r'\d', nxt) else ' ')
        street = street.strip()
        b = s['building'] if s['building'] and not re.search(r'colonial|park$', s['building'].lower()) else None
        name, kind = b or street, 'other'
    if key not in vkey:
        vkey[key] = len(venues)
        venues.append({'name': name, 'kind': kind, 'lnglat': ll, 'stalls': [], 'postal': s['postal']})
    venues[vkey[key]]['stalls'].append(s['name'])

for v in venues:
    if v['kind'] == 'hawker' and len({rows_s['postal'] for rows_s, _ in rows if rows_s['name'] in v['stalls']}) > 1:
        print('venue spans postcodes:', v['name'], v['stalls'])

# ---- output ----
order = sorted(range(len(venues)), key=lambda i: (-len(venues[i]['stalls']), venues[i]['name']))
venues = [venues[i] for i in order]
vidx = {n: i for i, v in enumerate(venues) for n in v['stalls']}
stalls = []
for s, h in sorted(rows, key=lambda r: r[0]['name'].lower()):
    t = T[s['name']]
    stalls.append([s['name'], CATS.index(t['dish']), t['eat'], vidx[s['name']], int(s['new2026']), int(t['ambiguous']),
                   [CATS.index(a) for a in t.get('also', [])], t.get('cuisine', ''), s['address'],
                   s['michelin_url'].rsplit('/', 1)[1], t['reason']])
V = [[v['name'], v['kind'], round(v['lnglat'][0], 6), round(v['lnglat'][1], 6)] for v in venues]
dish_n = Counter(T[s['name']]['dish'] for s in src)
hawker_n = sum(len(v['stalls']) for v in venues if v['kind'] == 'hawker')
hot = [(v['name'], len(v['stalls'])) for v in venues if len(v['stalls']) > 1]
out = {
    'cats': tags['categories'], 'venues': V, 'stalls': stalls,
    'nea': [[n['name'], round(n['lnglat'][0], 6), round(n['lnglat'][1], 6)] for n in NEA],
    'stats': {'n': len(src), 'new': sum(s['new2026'] for s in src), 'matched': matched, 'venues': len(venues),
              'hawker': hawker_n, 'ambiguous': sum(t['ambiguous'] for t in T.values()), 'neaN': len(NEA),
              'neaUpdated': (meta.get('data') or meta).get('lastUpdatedAt', '')},
}
os.makedirs(OUT, exist_ok=True)
open(os.path.join(OUT, 'bib.js'), 'w', encoding='utf-8').write('window.DAY23 = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
print('dishes:', dict(dish_n))
print('venue names:', [v['name'] for v in venues])
print('venues:', len(venues), '| in NEA hawker centres:', hawker_n, '| hotspots (2+):', hot)
print('ambiguous names:', out['stats']['ambiguous'])
print('bytes:', os.path.getsize(os.path.join(OUT, 'bib.js')))
