"""Day 12 (Power) data prep: EMA household electricity by planning area, month and home type,
joined to URA's planning areas, plus the Tengeh floating solar farm from OpenStreetMap.

Requires: Python 3.10+, shapely 2, openpyxl  (pip install shapely openpyxl)
usage: python -I process.py <raw-dir> <out.json>      (run fetch.py first)

Inputs (see fetch.py):
  SES_tidy.xlsx      EMA Singapore Energy Statistics 2026, table T3.5: average monthly household
                     electricity consumption (kWh per account) by planning area and dwelling
                     type, monthly from Jan 2005. "s" marks suppressed figures.
  pa2019.geojson     URA MP2019 Planning Area Boundary (No Sea). EMA's 43 planning-area names
                     match its PLN_AREA_N case-insensitively; the other 12 areas have no figures.
  tengeh_osm.json    OSM power=plant on Tengeh Reservoir (the floating solar farm) and the
                     reservoir's water body.
  pub_floating.html  PUB's floating solar page: every Tengeh fact used is checked against it.

Output (compact JSON):
  m0, nm            first month ("2005-01") and number of months
  types             EMA dwelling types offered, [EMA name, label]
  dom               colour domain per type: [p1, p99] of every published monthly figure
                    (all areas, all months), so a month or an area is always compared on the
                    same scale for that home type
  caldom            per type, the lowest and highest national monthly figure (the heat
                    calendar's own colour stretch, so the seasons show)
  areas            [name, region, has-data] for the 55 MP2019 planning areas
  v[t][a]           kWh x 10 per month (int); -1 = no figure, -2 = suppressed ("s")
  nat[t]            national figure per month for the type (EMA's "Overall" row), kWh x 10
  geo[a]            polygons, rings delta-encoded as integer lon/lat at 1e-5 deg
  lab[a]            a point well inside each area (pole of inaccessibility), for markers
  season            seasonality check on the national all-homes series, full years only
  tengeh            OSM outline, reservoir outline, PUB facts, and the household equivalence
"""
import json
import math
import re
import sys
from collections import defaultdict

import openpyxl
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping, shape
from shapely.ops import linemerge, polygonize, polylabel, unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
TYPES = [  # EMA's own categories, in the order the switch shows them
    ('Overall', 'All homes'),
    ('1-room / 2-room', 'HDB 1–2 room'),
    ('3-room', 'HDB 3-room'),
    ('4-room', 'HDB 4-room'),
    ('5-room and Executive', 'HDB 5-room & Executive'),
    ('Private Apartments and Condominiums', 'Condos & private flats'),
    ('Landed Properties', 'Landed homes'),
]
SIMPLIFY = 0.00005   # degrees, about 5.5 m: invisible at the zooms the page uses


def rnd(x, n=1):
    return float(f'{x:.{n}f}')


# ---------- EMA T3.5 ----------
wb = openpyxl.load_workbook(f'{RAW}/SES_tidy.xlsx', read_only=True)
toc = [r[0] for r in wb['Table of Contents'].iter_rows(values_only=True) if r[0]]
edition = next(t for t in toc if str(t).startswith('Table of Contents for SES')).split('for ')[1]   # "SES 2026"
asof = re.search(r'accurate as of (\w+ \d{4})', ' '.join(map(str, toc))).group(1)
ws = wb['T3.5']
rows = list(ws.iter_rows(values_only=True))
head = [str(h).strip() if h else '' for h in rows[0]]
if head[:6] != ['Dwelling Type', 'Year', 'Month', 'Region', 'Description', 'Kwh Per Acc']:
    raise SystemExit(f'T3.5 layout changed: {head}')
note = next((r[0] for r in rows[1:] if r[0] and str(r[0]).startswith('Data for')), '')
cell = {}            # (type, place, year, month) -> value or 's'
for r in rows[1:]:
    t, y, m, reg, place, v = r[:6]
    if y is None or m == 'Annual' or t not in dict(TYPES):
        continue
    if reg != 'Overall' and place and place.endswith('Region'):
        continue       # regional subtotals
    cell[(t, place if reg != 'Overall' else '*', int(y), int(m))] = v
ym = sorted({(k[2], k[3]) for k in cell})
y0, m0 = ym[0]
y1, m1 = ym[-1]
months = [(y, m) for y in range(y0, y1 + 1) for m in range(1, 13) if (y0, m0) <= (y, m) <= (y1, m1)]
print(f'{edition} (as of {asof}); T3.5 {months[0]} .. {months[-1]} = {len(months)} months; note: {note!r}')

# ---------- planning areas ----------
pa = json.load(open(f'{RAW}/pa2019.geojson', encoding='utf-8'))['features']
ema_places = sorted({k[1] for k in cell if k[1] != '*'})
names = {f['properties']['PLN_AREA_N']: f for f in pa}
missing = [p for p in ema_places if p.upper() not in names]
if missing:
    raise SystemExit(f'EMA planning areas with no MP2019 match: {missing}')
no_data = sorted(n for n in names if n not in {p.upper() for p in ema_places})
print(f'{len(ema_places)} EMA areas joined; {len(no_data)} MP2019 areas without figures: {no_data}')
title = {p.upper(): p for p in ema_places}


def nice_name(n):   # EMA's spelling where it has one, else title case
    return title.get(n) or ' '.join(w.capitalize() if w not in ('OF',) else w.lower() for w in n.split(' ')).replace('North-eastern', 'North-Eastern')


def enc_ring(coords):
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * 1e5), round(y * 1e5)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def enc_geom(g):
    polys = [g] if isinstance(g, Polygon) else list(g.geoms)
    return [[enc_ring(p.exterior.coords)] + [enc_ring(i.coords) for i in p.interiors] for p in polys if not p.is_empty]


areas, geo, lab = [], [], []
order = sorted(names, key=lambda n: nice_name(n))
for n in order:
    f = names[n]
    g = shape(f['geometry'])
    if not g.is_valid:
        g = g.buffer(0)
    gs = g.simplify(SIMPLIFY, preserve_topology=True)
    big = max(gs.geoms, key=lambda p: p.area) if isinstance(gs, MultiPolygon) else gs
    pt = polylabel(big, tolerance=0.0003)
    region = f['properties']['REGION_N'].title().replace(' Region', '').replace('North East', 'North-East')
    areas.append([nice_name(n), region, 1 if n in title else 0])
    geo.append(enc_geom(gs))
    lab.append([rnd(pt.x, 5), rnd(pt.y, 5)])

# ---------- values ----------
def code(v):
    if v is None:
        return -1
    if v == 's':
        return -2
    return round(float(v) * 10)


v_out, nat, dom, caldom = [], [], [], []
for t, _ in TYPES:
    per = []
    pool = []
    for a in areas:
        place = a[0] if a[2] else None
        series = [code(cell.get((t, place, y, m))) if place else -1 for (y, m) in months]
        per.append(series if place and any(x >= 0 for x in series) else [])
        pool += [x / 10 for x in series if x >= 0]
    v_out.append(per)
    nat.append([code(cell.get((t, '*', y, m))) for (y, m) in months])
    pool.sort()
    q = lambda p: pool[int(p * (len(pool) - 1))]
    lo, hi = q(0.01), q(0.99)
    # round outwards to two significant figures
    sig = lambda x, up: (math.ceil if up else math.floor)(x / 10 ** (int(math.log10(x)) - 1)) * 10 ** (int(math.log10(x)) - 1)
    dom.append([sig(lo, False), sig(hi, True)])
    natv = [x / 10 for x in nat[-1] if x >= 0]
    caldom.append([min(natv), max(natv)])   # the heat calendar stretches the national series
    print(f'{t:38s} domain {dom[-1]}  national {caldom[-1]}  n={len(pool)}')

# ---------- seasonality (national, all homes, complete years only) ----------
ti = 0
full_years = [y for y in range(y0, y1 + 1) if all((y, m) in set(months) for m in range(1, 13))]
mi = {ym: i for i, ym in enumerate(months)}
peak, low = [], []
for y in full_years:
    vals = [nat[ti][mi[(y, m)]] for m in range(1, 13)]
    peak.append(vals.index(max(vals)) + 1)
    low.append(vals.index(min(vals)) + 1)
idx = []   # each calendar month as % of its year's mean, averaged over the full years
for m in range(1, 13):
    idx.append(rnd(100 * sum(nat[ti][mi[(y, m)]] / (sum(nat[ti][mi[(y, k)]] for k in range(1, 13)) / 12) for y in full_years) / len(full_years), 1))
season = {
    'years': [full_years[0], full_years[-1]],
    'peak': peak, 'low': low,
    'juneTop': sum(1 for p in peak if p == 6),
    'aprJulTop': sum(1 for p in peak if 4 <= p <= 7),
    'decMarLow': sum(1 for l in low if l in (12, 1, 2, 3)),
    'idx': idx,
}
rec = max(range(len(months)), key=lambda i: nat[ti][i])
season['record'] = [f'{months[rec][0]}-{months[rec][1]:02d}', nat[ti][rec] / 10]
print('season', season)

# ---------- Tengeh ----------
osm = json.load(open(f'{RAW}/tengeh_osm.json', encoding='utf-8'))
els = osm['elements']


def el_geom(e):
    if e['type'] == 'way':
        pts = [(p['lon'], p['lat']) for p in e['geometry']]
        return Polygon(pts) if len(pts) >= 4 and pts[0] == pts[-1] else None
    lines = [LineString([(p['lon'], p['lat']) for p in m['geometry']]) for m in e.get('members', []) if m.get('geometry') and m.get('role') in ('outer', '')]
    inner = [LineString([(p['lon'], p['lat']) for p in m['geometry']]) for m in e.get('members', []) if m.get('geometry') and m.get('role') == 'inner']
    outer = unary_union(list(polygonize(linemerge(lines)))) if lines else None
    holes = unary_union(list(polygonize(linemerge(inner)))) if inner else None
    return outer.difference(holes) if outer is not None and holes is not None else outer


water = [e for e in els if e.get('tags', {}).get('natural') == 'water' and 'Tengeh' in e['tags'].get('name', '')]
wg = unary_union([g for g in (el_geom(e) for e in water) if g is not None]) if water else None
floating = [e for e in els if e.get('tags', {}).get('power') == 'plant' and e['tags'].get('floating') == 'yes']
# The farm is the plant OSM names "Tengeh Floating Solar Farm"; the 1 MW SERIS testbed of 2016
# floats on the same reservoir and is left out.
solar = [e for e in floating if 'Tengeh Floating Solar' in e['tags'].get('name', '')]
if not solar and wg is not None:   # fallback: the largest floating plant on the reservoir
    on = [e for e in floating if el_geom(e) is not None and el_geom(e).intersects(wg)]
    solar = sorted(on, key=lambda e: el_geom(e).area)[-1:]
if not solar:
    raise SystemExit('no Tengeh floating solar plant found in tengeh_osm.json')
sg = unary_union([g for g in (el_geom(e) for e in solar) if g is not None])


def ha(g):   # local equirectangular area: fine for a 1 km object near the equator
    lat0 = g.centroid.y
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110574
    from shapely.affinity import scale
    return scale(g, xfact=kx, yfact=ky, origin=(0, 0)).area / 1e4


pub = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', open(f'{RAW}/pub_floating.html', encoding='utf-8', errors='replace').read()))
FACTS = {   # each quote must appear on PUB's page, or the build stops
    'mwp': ('At 60 MWp', 60),
    'ha': ('It occupies 45 hectares, or one-third of the reservoir', 45),
    'panels': ('over 122,000 solar panels', 122000),
    'islands': ('10 floating solar panel islands', 10),
    'flats4': ('powering about 16,000 four-room HDB flats', 16000),
    'launched': ('officially launched in July 2021', '2021-07'),
}
for k, (quote, _) in FACTS.items():
    if quote not in pub:
        raise SystemExit(f'PUB page no longer says: {quote!r}')
last12 = [i for i in range(len(months))][-12:]


def avg12(t_i):
    vals = [nat[t_i][i] / 10 for i in last12 if nat[t_i][i] >= 0]
    return sum(vals) / len(vals)


four = [k for k, _ in TYPES].index('4-room')
a4 = avg12(four)
implied_kwh = FACTS['flats4'][1] * a4 * 12          # PUB's equivalence, in this data's 4-room kWh
homes = [int(round(FACTS['flats4'][1] * a4 / avg12(i), -2)) for i in range(len(TYPES))]
# households' share: EMA T3.3 household electricity accounts, latest full year
acc = None
for r in list(wb['T3.3'].iter_rows(values_only=True))[1:]:
    if r[0] and r[1] == 'Households' and r[2] in ('Households', None):
        acc = (int(r[0]), int(r[3])) if acc is None or int(r[0]) > acc[0] else acc
tengeh = {
    'outline': enc_geom(sg),
    'ha_osm': rnd(ha(sg), 1),
    'osm': [f"{e['type']}/{e['id']}" for e in solar],
    'water': enc_geom(wg) if wg is not None and not wg.is_empty else [],
    'center': [rnd(sg.centroid.x, 5), rnd(sg.centroid.y, 5)],
    'facts': {k: v for k, (_, v) in FACTS.items()},
    'window': [f'{months[last12[0]][0]}-{months[last12[0]][1]:02d}', f'{months[last12[-1]][0]}-{months[last12[-1]][1]:02d}'],
    'avg12': [rnd(avg12(i), 1) for i in range(len(TYPES))],
    'gwh': rnd(implied_kwh / 1e6, 1),
    'homes': homes,
    'accounts': acc,
    # T3.3's latest year is a part year (to the same month as T3.5), so label it with that month
    'accAsOf': (f'{["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][m1 - 1]} {y1}' if acc and acc[0] == y1 and m1 < 12 else str(acc[0]) if acc else None),
    # all-homes equivalent as a share of every household electricity account, and "1 in N"
    'pct': rnd(100 * homes[0] / acc[1], 2) if acc else None,
    'oneIn': round(acc[1] / homes[0]) if acc else None,
    'osmTags': {k: v for k, v in solar[0]['tags'].items() if k in ('name', 'operator', 'owner', 'start_date', 'plant:output:electricity')},
}
print('tengeh', {k: v for k, v in tengeh.items() if k not in ('outline', 'water')})

out = {
    'src': {'edition': edition, 'asof': asof, 'note': note},
    'm0': f'{months[0][0]}-{months[0][1]:02d}', 'nm': len(months),
    'types': [list(t) for t in TYPES], 'dom': dom, 'caldom': caldom,
    'areas': areas, 'v': v_out, 'nat': nat, 'geo': geo, 'lab': lab,
    'season': season, 'tengeh': tengeh,
}
s = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
open(OUT, 'w', encoding='utf-8').write('window.DAY12 = ' + s + ';\n')
print(f'wrote {OUT}: {len(s):,} bytes')
