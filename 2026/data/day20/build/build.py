"""Day 20: HDB resale $/psf binned to H3 hexagons, res 8 and res 9.
Requirements (own venv): pip install h3==4.5.0 requests
usage: python -X utf8 build.py <raw_dir> <day06 sheet.json> <out hex.json> [cache_dir]
Run fetch.py first (it writes <raw_dir>/resale_2017on.csv and resale_metadata.json).

Price per square foot = resale_price / (floor_area_sqm x 10.7639)   (1 m2 = 10.7639 sq ft)

Where each block is: its HDB building footprint centroid, read from day 06's sheet.json (HDB Existing
Building footprints joined to HDB Property Information on block + street). Blocks not found there are
geocoded with OneMap search ("<block> <street>", block number must match), cached in <cache_dir>.

Output (all integers unless noted):
  meta    rows, months, factor, threshold, geocode stats
  years   [2017 ... latest]; a selection's year index y: 0 = every year, 1.. = years[y-1]
  types   flat-type groups; t: 0 = every flat type
  places  [[street, town], ...]  label table: a hex is named after the street with the most resales in the selection
  towns   [[name, lng, lat], ...]  town label points (median of the town's resales)
  island  {"y|t": [median, sales, p25, p75]}           island-wide $/psf, every sale in the selection
  land, reservoirs   [[ring polyline, ...], ...]  day 06's Singapore land and reservoirs (OSM), for the paper island
  res     {"8"|"9": {area: mean cell km2, hex: [[polyline, h3 index, sales_all], ...],   boundary as a Google polyline (lng, lat at 1e5)
                       lattice: [polyline, ...]  land cells with no resale since 2017 (drawn as the empty honeycomb)
                       v: {"y|t": [i, median, sales, min, max, place, ...]}}}  every hex with >= 1 sale in the selection;
          medians and ranges in whole dollars per sq ft; the page leaves hexes under `threshold` sales hollow.
"""
import sys, os, csv, json, time, statistics, collections, math
import h3, requests

RAW, SHEET, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
CACHE = sys.argv[4] if len(sys.argv) > 4 else RAW
SQFT = 10.7639
THRESHOLD = 5          # fewer sales than this in a selection: the hex is drawn hollow, no median shown
RESOLUTIONS = (8, 9)
TYPES = [('All flats', None), ('1–2 room', {'1 ROOM', '2 ROOM'}), ('3 room', {'3 ROOM'}), ('4 room', {'4 ROOM'}),
         ('5 room', {'5 ROOM'}), ('Executive', {'EXECUTIVE', 'MULTI-GENERATION'})]
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}


# ---------- polyline helpers ----------
def decode(s):
    out, i, x, y = [], 0, 0, 0
    while i < len(s):
        vals = []
        for _ in range(2):
            shift = res = 0
            while True:
                b = ord(s[i]) - 63; i += 1
                res |= (b & 31) << shift; shift += 5
                if b < 32: break
            vals.append(~(res >> 1) if res & 1 else res >> 1)
        x += vals[0]; y += vals[1]
        out.append((x, y))
    return out


def encode(pts):
    """Google polyline of (lng, lat) at 1e5, lng first (as day 06 packs it)."""
    out, px, py = [], 0, 0
    for lng, lat in pts:
        x, y = round(lng * 1e5), round(lat * 1e5)
        for v in (x - px, y - py):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        px, py = x, y
    return ''.join(out)


# ---------- 1. block coordinates from day 06 ----------
sheet = json.load(open(SHEET, encoding='utf-8'))
O, K = sheet['o'], sheet['k']
norm = lambda b: b.strip().upper().lstrip('0')
acc = collections.defaultdict(lambda: [0.0, 0.0, 0.0])   # key -> [sum a*x, sum a*y, sum a]
for rec in sheet['b']:
    if rec[4] < 0: continue
    ring = [(O[0] + x / K, O[1] + y / K) for x, y in decode(rec[6])]
    a = cx = cy = 0.0
    for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
        c = x0 * y1 - x1 * y0
        a += c; cx += (x0 + x1) * c; cy += (y0 + y1) * c
    if abs(a) < 1e-14:
        cx, cy, a = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring), 1e-12
    else:
        cx, cy, a = cx / (3 * a), cy / (3 * a), abs(a / 2)
    k = (norm(rec[3]), sheet['streets'][rec[4]])
    acc[k][0] += a * cx; acc[k][1] += a * cy; acc[k][2] += a
coords = {k: (v[0] / v[2], v[1] / v[2]) for k, v in acc.items()}
print('day 06 blocks with coordinates:', len(coords))

# ---------- 2. resale transactions ----------
rows = list(csv.DictReader(open(os.path.join(RAW, 'resale_2017on.csv'), encoding='utf-8')))
months = sorted({r['month'] for r in rows})
years = sorted({int(m[:4]) for m in months})
print('rows', len(rows), 'months', months[0], '->', months[-1])

# ---------- 3. geocode the blocks day 06 does not have (OneMap search, cached) ----------
cache_p = os.path.join(CACHE, 'onemap_cache.json')
cache = json.load(open(cache_p, encoding='utf-8')) if os.path.exists(cache_p) else {}
ABBR = {'RD': 'ROAD', 'ST': 'STREET', 'AVE': 'AVENUE', 'STH': 'SOUTH', 'NTH': 'NORTH', 'BT': 'BUKIT', 'JLN': 'JALAN',
        'LOR': 'LORONG', 'KG': 'KAMPONG', 'TG': 'TANJONG', 'UPP': 'UPPER', 'CRES': 'CRESCENT', 'CL': 'CLOSE', 'DR': 'DRIVE',
        'PK': 'PARK', 'CTRL': 'CENTRAL', "C'WEALTH": 'COMMONWEALTH', 'PL': 'PLACE', 'HTS': 'HEIGHTS', 'TER': 'TERRACE',
        'GDNS': 'GARDENS', 'MKT': 'MARKET', 'CTR': 'CENTRE', 'SQ': 'SQUARE', 'MT': 'MOUNT', 'CT': 'COURT'}
expand = lambda s: ' '.join(ABBR.get(w, w) for w in s.split())


def search(q):
    if q in cache: return cache[q]
    for attempt in range(6):
        try:
            r = requests.get('https://www.onemap.gov.sg/api/common/elastic/search',
                             params={'searchVal': q, 'returnGeom': 'Y', 'getAddrDetails': 'Y', 'pageNum': 1}, headers=UA, timeout=30)
            if r.status_code == 200:
                cache[q] = r.json().get('results', []); time.sleep(0.6); return cache[q]
            if r.status_code == 429: time.sleep(10 * (attempt + 1)); continue
        except requests.RequestException as e:
            print('onemap error', e)
        time.sleep(3)
    return []


pairs = collections.Counter((norm(r['block']), r['street_name'].strip().upper()) for r in rows)
geo = {'pairs': len(pairs), 'day06': 0, 'onemap': 0, 'unplaced': 0, 'rowsUnplaced': 0, 'onemapList': [], 'unplacedList': []}
for k, n in sorted(pairs.items()):
    if k in coords: geo['day06'] += 1; continue
    hit = None
    for q in (f'{k[0]} {expand(k[1])}', f'{k[0]} {k[1]}'):
        res = [x for x in search(q) if x.get('BLK_NO', '').upper().lstrip('0') == k[0]]
        if res: hit = res[0]; break
    if hit:
        coords[k] = (float(hit['LONGITUDE']), float(hit['LATITUDE']))
        geo['onemap'] += 1; geo['onemapList'].append(f'{k[0]} {k[1]} ({n} sales) -> {hit["ADDRESS"]}')
    else:
        geo['unplaced'] += 1; geo['rowsUnplaced'] += n; geo['unplacedList'].append(f'{k[0]} {k[1]} ({n} sales)')
json.dump(cache, open(cache_p, 'w', encoding='utf-8'))
print('geocode:', {k: v for k, v in geo.items()})

# ---------- 4. one record per sale ----------
YI = {y: i + 1 for i, y in enumerate(years)}
TI = {}
for t, (_, s) in enumerate(TYPES):
    for ft in (s or ()): TI[ft] = t
sales = []   # (lng, lat, y index, t index, psf, street, town)
for r in rows:
    k = (norm(r['block']), r['street_name'].strip().upper())
    if k not in coords: continue
    psf = float(r['resale_price']) / (float(r['floor_area_sqm']) * SQFT)
    sales.append((*coords[k], YI[int(r['month'][:4])], TI[r['flat_type']], psf, r['street_name'].strip().upper(), r['town'].strip().upper()))
print('sales placed', len(sales), 'of', len(rows))


def q(vals, p):   # linear-interpolated quantile of sorted vals
    if len(vals) == 1: return vals[0]
    h = (len(vals) - 1) * p; lo = math.floor(h)
    return vals[lo] + (vals[min(lo + 1, len(vals) - 1)] - vals[lo]) * (h - lo)


def combos(y, t):   # every (y, t) selection key a sale belongs to
    return [(yy, tt) for yy in (0, y) for tt in (0, t)]


# island-wide
island = collections.defaultdict(list)
for s in sales:
    for yy, tt in combos(s[2], s[3]): island[(yy, tt)].append(s[4])
island_out = {}
for k, v in island.items():
    v.sort()
    island_out[f'{k[0]}|{k[1]}'] = [round(statistics.median(v)), len(v), round(q(v, .25)), round(q(v, .75))]

# labels
TITLE = {'BT': 'Bukit', 'JLN': 'Jalan', 'LOR': 'Lorong', 'KG': 'Kampong', 'TG': 'Tanjong', "C'WEALTH": 'Commonwealth',
         'UPP': 'Upper', 'NTH': 'North', 'STH': 'South', 'CTRL': 'Central', 'PK': 'Park', 'MKT': 'Market', 'HTS': 'Heights'}
def nice(s):
    return ' '.join(TITLE.get(w, w if any(c.isdigit() for c in w) else w.capitalize()) for w in s.replace('/', ' / ').split()).replace(' / ', '/')
place_keys = sorted({(s[5], s[6]) for s in sales})
PI = {k: i for i, k in enumerate(place_keys)}
town_names = sorted({s[6] for s in sales})
tpts = collections.defaultdict(list)
for s in sales: tpts[s[6]].append((s[0], s[1]))
towns_out = []
for name in town_names:
    xs = sorted(p[0] for p in tpts[name]); ys = sorted(p[1] for p in tpts[name])
    towns_out.append([nice(name), round(xs[len(xs) // 2], 4), round(ys[len(ys) // 2], 4)])

# Singapore's land (day 06, from the OSM coastline) for the empty honeycomb
land_polys = []
for poly in sheet['ctx']['land']['c']:
    rings = [[(lat, lng) for lng, lat in ((x / 1e5, y / 1e5) for x, y in decode(r))] for r in poly]
    land_polys.append(h3.LatLngPoly(rings[0], *rings[1:]))


def boundary(cell):
    b = [(lng, lat) for lat, lng in h3.cell_to_boundary(cell)]
    return encode(b)


res_out, stats = {}, {}
for R in RESOLUTIONS:
    cell_sales = collections.defaultdict(list)
    for s in sales: cell_sales[h3.latlng_to_cell(s[1], s[0], R)].append(s)
    # order cells west to east, then north to south, so the file is stable between runs
    cells = sorted(cell_sales, key=lambda c: (round(-h3.cell_to_latlng(c)[0], 3), h3.cell_to_latlng(c)[1]))
    ci = {c: i for i, c in enumerate(cells)}
    hex_out = [[boundary(c), c, len(cell_sales[c])] for c in cells]
    area = sum(h3.cell_area(c, 'km^2') for c in cells) / len(cells)
    groups = collections.defaultdict(list)
    for c, ss in cell_sales.items():
        for s in ss:
            for yy, tt in combos(s[2], s[3]): groups[(yy, tt, ci[c])].append((s[4], PI[(s[5], s[6])]))
    v = collections.defaultdict(list)
    shown = collections.Counter(); shown_sales = collections.Counter(); all_sales = collections.Counter()
    for (yy, tt, i), recs in sorted(groups.items()):
        vals = sorted(r[0] for r in recs)
        n = len(vals)
        place = collections.Counter(r[1] for r in recs).most_common(1)[0][0]   # ties: the first seen (stable)
        all_sales[(yy, tt)] += n
        if n >= THRESHOLD:
            v[f'{yy}|{tt}'] += [i, round(statistics.median(vals)), n, round(vals[0]), round(vals[-1]), place]
            shown[(yy, tt)] += 1; shown_sales[(yy, tt)] += n
        else:
            v[f'{yy}|{tt}'] += [i, 0, n, 0, 0, place]
    land = set()
    for p in land_polys: land |= set(h3.polygon_to_cells(p, R))
    lattice = sorted(land - set(cells))
    res_out[str(R)] = {'area': round(area, 4), 'hex': hex_out, 'lattice': [boundary(c) for c in lattice], 'v': dict(v)}
    stats[R] = {'area': round(area, 4), 'hexes': len(cells), 'lattice': len(lattice),
                'shownAll': shown[(0, 0)], 'hidden2026all': sum(1 for i in range(len(cells)) if 0 < len(groups.get((len(years), 0, i), [])) < THRESHOLD),
                'salesInHollow_byYearAll': {years[y - 1]: all_sales[(y, 0)] - shown_sales[(y, 0)] for y in range(1, len(years) + 1)},
                'salesInHollow_allCombos': sum(all_sales.values()) - sum(shown_sales.values()), 'salesAllCombos': sum(all_sales.values())}
    print('res', R, stats[R])

meta = json.load(open(os.path.join(RAW, 'resale_metadata.json'), encoding='utf-8')).get('data', {})
out = {
    'meta': {'rows': len(rows), 'placed': len(sales), 'from': months[0], 'to': months[-1], 'factor': SQFT, 'threshold': THRESHOLD,
             'updated': meta.get('lastUpdatedAt', ''), 'geo': {k: v for k, v in geo.items() if not k.endswith('List')},
             'perType': {TYPES[t][0]: island_out[f'0|{t}'][1] for t in range(len(TYPES))}},
    'years': years, 'types': [t[0] for t in TYPES],
    'places': [[nice(st), nice(tw)] for st, tw in place_keys], 'towns': towns_out,
    'island': island_out, 'res': res_out,
    # Singapore's land and reservoirs, as day 06 drew them from the OSM coastline (polylines, lng/lat at 1e5)
    'land': sheet['ctx']['land']['c'], 'reservoirs': sheet['ctx']['reservoirs']['c'],
}
s = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
open(OUT, 'w', encoding='utf-8').write(s)
print('wrote', OUT, len(s.encode('utf-8')), 'bytes')
print('island all years, all flats:', island_out['0|0'], '| latest year:', island_out[f'{len(years)}|0'], '| 2017:', island_out['1|0'])
for line in geo['onemapList'] + geo['unplacedList']: print('  ', line)
