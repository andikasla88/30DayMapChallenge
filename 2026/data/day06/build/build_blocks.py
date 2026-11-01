"""Join HDB Property Information (year completed, floors, flats) to HDB Existing Building footprints.
Join key: (block number, street code). Street names -> ST_COD come from geocode_streets.py
(OneMap search -> postal code -> footprint). Rows still unmatched are geocoded individually
(OneMap, cached) and joined on postal code. usage: python -X utf8 build_blocks.py <raw_dir> <out_json>
Output: {"o":[lng0,lat0],"k":scale,"streets":[...],"towns":{...},"b":[[year,floors,units,blk,street,flags,ring,ring...],...]}
flags: 1 residential, 2 commercial, 4 carpark, 8 hawker/market. ring = Google-polyline string of (x, y) in 1/K degree from origin o."""
import sys, os, json, csv, collections, time, requests
import warnings; warnings.filterwarnings('ignore')
from shapely.geometry import shape
from shapely.ops import transform
from pyproj import Transformer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from geocode_streets import expand, search, save_cache   # noqa: E402  (shared OneMap helpers)

RAW, OUT = sys.argv[1], sys.argv[2]
fw = Transformer.from_crs(4326, 3414, always_xy=True).transform
bw = Transformer.from_crs(3414, 4326, always_xy=True).transform
foot = json.load(open(os.path.join(RAW, 'hdb_buildings.geojson'), encoding='utf-8'))['features']
rows = list(csv.DictReader(open(os.path.join(RAW, 'hdb_property.csv'), encoding='utf-8')))
st2c = json.load(open(os.path.join(RAW, 'street_to_stcod.json')))
norm = lambda b: b.strip().upper().lstrip('0')
fkey = collections.defaultdict(list)
by_postal = collections.defaultdict(list)
for i, f in enumerate(foot):
    p = f['properties']
    fkey[(norm(p['BLK_NO']), p['ST_COD'])].append(i)
    by_postal[p['POSTAL_COD']].append(i)

match = {}   # footprint index -> property row
how = collections.Counter()
unmatched = []
for r in rows:
    b, c = norm(r['blk_no']), st2c.get(r['street'])
    idx = fkey.get((b, c)) if c else None
    if idx:
        for i in idx: match.setdefault(i, r)
        how['blk + street code'] += 1
    else:
        unmatched.append(r)
print('geocoding', len(unmatched), 'leftover rows')
for r in ([] if os.environ.get('NO_GEOCODE') else unmatched):
    b = r['blk_no'].strip().upper()
    hit = None
    for q in (f"{b} {expand(r['street'])}", f"{b} {r['street']}"):
        res = [x for x in search(q) if x['BLK_NO'].upper() == b and x['POSTAL'] in by_postal]
        if res: hit = res[0]; break
    if hit:
        for i in by_postal[hit['POSTAL']]: match.setdefault(i, r)
        how['OneMap postal fallback'] += 1
    else:
        how['no footprint'] += 1
save_cache()
print('property rows', len(rows), dict(how))
print('footprints', len(foot), 'with a property record', len(match))

streets = sorted({r['street'] for r in rows})
sidx = {s: i for i, s in enumerate(streets)}
O = (103.6, 1.15); K = 100000   # 1 unit = 1/100000 degree, about 1.1 m


def polyline(pts):
    """Google polyline encoding of integer (x, y) pairs: first pair as is, then deltas."""
    out, px, py = [], 0, 0
    for x, y in pts:
        for v in (x - px, y - py):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        px, py = x, y
    return ''.join(out)

   # 1 unit = 1/200000 degree, about 0.56 m
out_b = []
years = collections.Counter()
for i, f in enumerate(foot):
    g = transform(bw, transform(fw, shape(f['geometry'])).simplify(1.0, preserve_topology=True))
    r = match.get(i)
    if r:
        flags = (r['residential'] == 'Y') * 1 + (r['commercial'] == 'Y') * 2 + (r['multistorey_carpark'] == 'Y') * 4 + (r['market_hawker'] == 'Y') * 8
        rec = [int(r['year_completed']), int(r['max_floor_lvl']), int(r['total_dwelling_units']), r['blk_no'].strip(), sidx[r['street']], flags]
        years[int(r['year_completed'])] += 1
    else:
        rec = [0, 0, 0, f['properties']['BLK_NO'].strip(), -1, 0]
    polys = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    first = True
    for poly in polys:
        enc = []
        for ring in [poly.exterior] + list(poly.interiors):
            pts = list(ring.coords)[:-1]
            if len(pts) < 3: continue
            q = [(round((x - O[0]) * K), round((y - O[1]) * K)) for x, y in pts]
            q = [a for j, a in enumerate(q) if j == 0 or a != q[j - 1]]
            enc.append(polyline(q))
        if enc:
            # flats/units are counted once per block: extra parts of a MultiPolygon carry units 0
            out_b.append((rec if first else rec[:2] + [0] + rec[3:]) + enc)
            first = False

TOWN = {'AMK': 'Ang Mo Kio', 'BB': 'Bukit Batok', 'BD': 'Bedok', 'BH': 'Bishan', 'BM': 'Bukit Merah', 'BP': 'Bukit Panjang',
        'BT': 'Bukit Timah', 'CCK': 'Choa Chu Kang', 'CL': 'Clementi', 'CT': 'Central Area', 'GL': 'Geylang', 'HG': 'Hougang',
        'JE': 'Jurong East', 'JW': 'Jurong West', 'KWN': 'Kallang/Whampoa', 'MP': 'Marine Parade', 'PG': 'Punggol',
        'PRC': 'Pasir Ris', 'QT': 'Queenstown', 'SB': 'Sembawang', 'SGN': 'Serangoon', 'SK': 'Sengkang', 'TAP': 'Tampines',
        'TG': 'Tengah', 'TP': 'Toa Payoh', 'WL': 'Woodlands', 'YS': 'Yishun'}
# Town label anchors: median of the town's block centroids, and the year its first tenth was done.
tpts = collections.defaultdict(list)
for i, r in match.items():
    c = shape(foot[i]['geometry']).centroid
    tpts[r['bldg_contract_town']].append((c.x, c.y, int(r['year_completed'])))
towns = {}
for code, pts in tpts.items():
    xs = sorted(p[0] for p in pts); ys = sorted(p[1] for p in pts); yrs = sorted(p[2] for p in pts)
    towns[code] = [TOWN.get(code, code), round(xs[len(xs) // 2], 4), round(ys[len(ys) // 2], 4), yrs[len(yrs) // 10], len(pts)]
# Per-year totals straight from the property list (every row, footprint or not):
# year -> [residential blocks, flats, all buildings]
yearly = collections.defaultdict(lambda: [0, 0, 0])
for r in rows:
    y = yearly[int(r['year_completed'])]
    y[2] += 1
    if r['residential'] == 'Y': y[0] += 1; y[1] += int(r['total_dwelling_units'])
data = {'o': O, 'k': K, 'streets': streets, 'towns': towns, 'yearly': {str(k): v for k, v in sorted(yearly.items())}, 'b': out_b,
        'stats': {'rows': len(rows), 'footprints': len(foot), 'matchedFootprints': len(match), 'how': dict(how)}}
s = json.dumps(data, separators=(',', ':'))
open(OUT, 'w', encoding='utf-8').write(s)
print('blocks bytes', len(s), 'features', len(out_b), 'year range', min(years), max(years))
