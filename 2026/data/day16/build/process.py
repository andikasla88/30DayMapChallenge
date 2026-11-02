"""Day 16 (Collaborative map): seed the "Best kopi near you" map with real places.

Requires python 3.10+ with: osmium shapely pyproj (numpy comes with shapely)
usage: python -I process.py <raw-dir> <out-dir>          writes <out-dir>/kopi.js

WHAT IS INCLUDED, AND HOW (the page repeats this in plain words)
  From the OpenStreetMap extract, every node or area tagged amenity = cafe, food_court, restaurant
  or fast_food inside Singapore that passes ONE of these tests, checked in this order:
   1. a traditional kopi & toast chain, by its brand or name tag (CHAINS below):
      Ya Kun Kaya Toast, Toast Box, Killiney Kopitiam, Wang Cafe / Heavenly Wang, Fun Toast,
      Kaffe & Toast, Good Morning Nanyang Cafe, Kopi & Tarts, OldTown White Coffee, Nanyang Old Coffee
   2. a kopitiam or coffee-shop name (name, name:en or name:zh):
      "kopi" anywhere (Kopitiam, Kedai Kopi, Lim Kopi...; not "kopiah"), "coffee shop" or
      "coffeeshop", "kafei", 咖啡店, 咖啡室 or 茶室; "eating house" or "coffee house" only for a
      food_court or cafe (an eating-house restaurant is usually a single-dish restaurant)
   3. a cuisine tag of kopitiam or kaya_toast
   4. one of the big coffee-shop operators, by name: Koufu, Kimly, Kim San Leng, Broadway
  Not included: cuisine=coffee_shop on its own. OSM uses it for any cafe (Starbucks, Dunkin'),
  so it says nothing about kopi. Hawker centres come from NEA instead (below), so OSM places
  named like a hawker centre or market within 200 m of an NEA centre are dropped as duplicates.
  Same name within 50 m (a node and an area for one shop): kept once.
  From NEA's hawker centre list: every centre whose STATUS is Existing, Existing (new),
  Existing (replacement) or Interim Centre; centres Under Construction are left out.

  "Inside Singapore": within 100 m of land (OSM coastline rings, the islands included) and inside
  Singapore's national boundary (OSM relation 536780). The same shape, simplified, ships in
  kopi.js so the page can check that a shared pin is in Singapore.

OUTPUT kopi.js
  p      places: [x, y, kind, chain, name, address, hours, osm ref, stalls]
         x, y = round(lon * 1e5), round(lat * 1e5); kind 0 coffee shop, 1 chain, 2 hawker centre;
         chain = index into chains or -1; stalls = NEA cooked-food stalls (hawker centres) or 0
  chains [[id, label], ...]   counts {...} every number the page shows
  land   [[x0, y0, dx, dy, ...], ...]  outer rings of the "inside Singapore" shape, delta-coded 1e5
  border the same, for the national boundary simplified to 60 m; the page only draws a veil outside it
"""
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date

import numpy as np
import osmium
import shapely
import shapely.wkb as wkb
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import linemerge, unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
PBF = os.path.join(RAW, 'singapore-latest.osm.pbf')
AMENITIES = {'cafe', 'food_court', 'restaurant', 'fast_food'}

CHAINS = [   # id, label, pattern on brand or name
    ('yakun', 'Ya Kun Kaya Toast', r'^ya ?kun\b'),
    ('toastbox', 'Toast Box', r'^toast ?box\b'),
    ('killiney', 'Killiney Kopitiam', r'^killiney\b(?!.*\b(curry|puff|rice)\b)|\bby killiney\b'),
    ('wang', 'Wang Cafe / Heavenly Wang', r'^heavenly wang\b|^wang caf'),
    ('funtoast', 'Fun Toast', r'^fun toast\b'),
    ('kaffe', 'Kaffe & Toast', r'^kaffe ?(&|and) ?toast'),
    ('gmn', 'Good Morning Nanyang Cafe', r'^good morning nanyang'),
    ('kopitarts', 'Kopi & Tarts', r'^kopi ?& ?tarts'),
    ('oldtown', 'OldTown White Coffee', r'^old ?town white coffee'),
    ('nanyangold', 'Nanyang Old Coffee', r'^nanyang old coffee'),
]
CHAIN_RE = [(cid, label, re.compile(p, re.I)) for cid, label, p in CHAINS]
KOPI_NAME = re.compile(r'kopi(?!ah)|coffee ?shop|kafei|咖啡店|咖啡室|茶室', re.I)
HOUSE_NAME = re.compile(r'eating ?house|coffee ?house', re.I)          # food_court / cafe only
OPERATOR = re.compile(r'^(koufu|kimly|kim san leng|broadway)\b', re.I)
CUISINE = re.compile(r'(^|;)\s*(kopitiam|kaya_toast)\s*($|;)', re.I)
HAWKERISH = re.compile(r'hawker|food cent|market', re.I)
NEA_KEEP = {'Existing', 'Existing (new)', 'Existing (replacement)', 'Interim Centre'}

_fwd = Transformer.from_crs(4326, 3414, always_xy=True)     # SVY21, metres
_inv = Transformer.from_crs(3414, 4326, always_xy=True)
to_m = lambda g: shapely.transform(g, lambda a: np.column_stack(_fwd.transform(a[:, 0], a[:, 1])))
to_ll = lambda g: shapely.transform(g, lambda a: np.column_stack(_inv.transform(a[:, 0], a[:, 1])))


def classify(t):
    """(kind, chain index, rule) or None."""
    names = [t.get(k, '') for k in ('name', 'name:en', 'name:zh')]
    for i, (cid, label, rx) in enumerate(CHAIN_RE):
        if rx.search(t.get('brand', '')) or any(rx.search(n) for n in names):
            return 1, i, 'chain'
    if any(KOPI_NAME.search(n) for n in names):
        return 0, -1, 'name'
    if t.get('amenity') in ('food_court', 'cafe') and any(HOUSE_NAME.search(n) for n in names):
        return 0, -1, 'house'
    if CUISINE.search(t.get('cuisine', '')):
        return 0, -1, 'cuisine'
    if any(OPERATOR.search(n) for n in names):
        return 0, -1, 'operator'
    return None


def address(t):
    street = ' '.join(x for x in (t.get('addr:housenumber', ''), t.get('addr:street', '')) if x).strip()
    unit = t.get('addr:unit', '')
    pc = t.get('addr:postcode', '')
    s = street + (f' #{unit.lstrip("#")}' if unit and street else '')
    if pc and re.fullmatch(r'\d{6}', pc):
        s = f'{s}, Singapore {pc}' if s else f'Singapore {pc}'
    return s[:90]


# ---------- one pass over the extract ----------
fab = osmium.geom.WKBFactory()
cands, coast, sg = [], [], None
header = osmium.io.Reader(PBF, osmium.osm.osm_entity_bits.NOTHING)
stamp = header.header().get('osmosis_replication_timestamp') or ''
header.close()
fp = osmium.FileProcessor(PBF).with_locations().with_areas()
for o in fp:
    if o.is_way():
        if o.tags.get('natural') == 'coastline':
            try:
                coast.append(wkb.loads(fab.create_linestring(o), hex=True))
            except RuntimeError:
                pass
        continue
    if o.is_area() and not o.from_way() and o.orig_id() == 536780:
        sg = wkb.loads(fab.create_multipolygon(o), hex=True)
        continue
    t = dict(o.tags)
    if t.get('amenity') not in AMENITIES:
        continue
    c = classify(t)
    if not c:
        continue
    if o.is_node():
        x, y, ref = o.location.lon, o.location.lat, f'n{o.id}'
    elif o.is_area():
        try:
            g = wkb.loads(fab.create_multipolygon(o), hex=True)
        except RuntimeError:
            continue
        p = g.representative_point()
        x, y, ref = p.x, p.y, f'{"w" if o.from_way() else "r"}{o.orig_id()}'
    else:
        continue
    name = (t.get('name') or t.get('name:en') or t.get('brand') or '').strip()
    cands.append(dict(x=x, y=y, kind=c[0], chain=c[1], rule=c[2], name=name, tags=t, ref=ref))
if sg is None:
    sys.exit('Singapore boundary (relation 536780) not found in the extract')
print('osm candidates', len(cands), 'coastline ways', len(coast), 'extract', stamp)

# ---------- "inside Singapore": land within 100 m, inside the national boundary ----------
merged = linemerge(coast)
lines = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]
islands = []
for ln in lines:
    if not ln.is_closed or len(ln.coords) < 4:
        continue
    ring = shapely.LinearRing(ln.coords)
    if ring.is_ccw:                       # OSM draws land on the left: counter-clockwise rings are land
        islands.append(Polygon(ring))
land = unary_union(islands).intersection(sg)
land_m = to_m(land)
pieces = [g for g in (land_m.geoms if hasattr(land_m, 'geoms') else [land_m]) if g.area >= 20_000]   # >= 0.02 km²
sg_m = to_m(sg)
inside_m = unary_union(pieces).buffer(100, quad_segs=4).intersection(sg_m)
shape_m = inside_m.simplify(25, preserve_topology=True)
shape_ll = to_ll(shape_m)
prep_inside = shapely.prepared.prep(to_ll(inside_m))
def rings_out(geom):
    """Outer rings, largest first, delta-coded at 1e5."""
    out = []
    for pg in sorted(geom.geoms if hasattr(geom, 'geoms') else [geom], key=lambda g: -g.area):
        pts = [(round(x * 1e5), round(y * 1e5)) for x, y in pg.exterior.coords]
        flat = [pts[0][0], pts[0][1]]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if (bx, by) != (ax, ay):
                flat += [bx - ax, by - ay]
        out.append(flat)
    return out


land_out = rings_out(shape_ll)
# the national boundary (land and territorial sea), only to draw the veil over everything outside it
border_m = unary_union([g for g in (sg_m.geoms if hasattr(sg_m, 'geoms') else [sg_m]) if g.area >= 20_000])
border_out = rings_out(to_ll(border_m.simplify(60, preserve_topology=True)))
print('land pieces', len(pieces), 'shape rings', len(land_out), 'vertices', sum(len(f) // 2 for f in land_out),
      '| border rings', len(border_out), 'vertices', sum(len(f) // 2 for f in border_out))

# ---------- NEA hawker centres ----------
nea = json.load(open(os.path.join(RAW, 'hawker-centres.geojson'), encoding='utf-8'))
meta = {}
mp = os.path.join(RAW, 'hawker-centres.meta.json')
if os.path.exists(mp):
    meta = json.load(open(mp, encoding='utf-8')).get('data', {})
status = Counter(f['properties'].get('STATUS') for f in nea['features'])
hawkers = []
for f in nea['features']:
    p = f['properties']
    if p.get('STATUS') not in NEA_KEEP:
        continue
    x, y = f['geometry']['coordinates'][:2]
    if not prep_inside.contains(Point(x, y)):
        print('NEA centre outside the shape?', p.get('NAME'))
    stalls = p.get('NUMBER_OF_COOKED_FOOD_STALLS')
    hawkers.append(dict(x=x, y=y, kind=2, chain=-1, name=p['NAME'].strip(), addr=(p.get('ADDRESS_MYENV') or '').strip()[:90],
                        hours='', ref='', stalls=int(stalls) if isinstance(stalls, (int, float)) and stalls == stalls else 0))

# ---------- clip, de-duplicate ----------
def metres(a, b):
    kx = 111320 * math.cos(math.radians((a['y'] + b['y']) / 2))
    return math.hypot((a['x'] - b['x']) * kx, (a['y'] - b['y']) * 110574)


norm = lambda s: re.sub('[^a-z0-9\\u4e00-\\u9fff]', '', s.lower())   # letters, digits and CJK only
out_list = [c for c in cands if not prep_inside.contains(Point(c['x'], c['y']))]
outside = len(out_list)
cands = [c for c in cands if prep_inside.contains(Point(c['x'], c['y']))]
dup_nea = [c for c in cands if HAWKERISH.search(c['name']) and any(metres(c, h) < 200 for h in hawkers)]
cands = [c for c in cands if c not in dup_nea]
print('outside Singapore:', '; '.join(f"{c['name']} ({c['y']:.3f}, {c['x']:.3f})" for c in out_list))
print('duplicates of NEA centres:', '; '.join(c['name'] for c in dup_nea))
grid = defaultdict(list)
kept, dups = [], 0
for c in sorted(cands, key=lambda c: (c['ref'][0] != 'n', c['ref'])):       # nodes first, then areas
    key, gx, gy = norm(c['name']), int(c['x'] / 0.001), int(c['y'] / 0.001)
    near = [k for dx in (-1, 0, 1) for dy in (-1, 0, 1) for k in grid[(gx + dx, gy + dy)]]
    if key and any(norm(k['name']) == key and metres(k, c) < 50 for k in near):
        dups += 1
        continue
    grid[(gx, gy)].append(c)
    kept.append(c)
print('outside Singapore', outside, 'duplicates of NEA centres', len(dup_nea), 'same-name duplicates', dups)

places = []
for c in kept:
    t = c['tags']
    name = c['name'] or ('Kopitiam' if c['rule'] == 'cuisine' else 'Coffee shop')
    hours = (t.get('opening_hours') or '').strip()[:60]
    places.append(dict(x=c['x'], y=c['y'], kind=c['kind'], chain=c['chain'], name=name[:70], addr=address(t), hours=hours, ref=c['ref'], stalls=0, rule=c['rule']))
places += [dict(h, rule='nea') for h in hawkers]
places.sort(key=lambda p: (p['kind'], p['name'].lower()))

# ---------- counts: every number the page shows ----------
kinds = Counter(p['kind'] for p in places)
chain_n = Counter(p['chain'] for p in places if p['kind'] == 1)
rules = Counter(p['rule'] for p in places)
counts = {
    'all': len(places), 'coffee': kinds[0], 'chain': kinds[1], 'hawker': kinds[2],
    'hawkerStalls': sum(p['stalls'] for p in places if p['kind'] == 2),
    'neaListed': len(nea['features']), 'neaUnderConstruction': status.get('Under Construction', 0),
    'chains': {CHAINS[i][0]: n for i, n in chain_n.items()},
    'rules': dict(rules), 'droppedOutside': outside, 'droppedNeaDup': len(dup_nea), 'droppedSameName': dups,
}
out = {
    'v': 1, 'built': date.today().isoformat(), 'osmExtract': stamp,
    'neaUpdated': meta.get('lastUpdatedAt', ''),
    'kinds': ['Kopitiam or coffee shop', 'Kopi & toast chain', 'Hawker centre'],
    'chains': [[cid, label] for cid, label, _ in CHAINS],
    'counts': counts,
    'p': [[round(p['x'] * 1e5), round(p['y'] * 1e5), p['kind'], p['chain'], p['name'], p['addr'], p['hours'], p['ref'], p['stalls']] for p in places],
    'land': land_out,
    'border': border_out,
}
os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, 'kopi.js')
with open(path, 'w', encoding='utf-8') as f:
    f.write('window.DAY16 = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
print(json.dumps(counts, indent=1, ensure_ascii=False))
print(path, os.path.getsize(path), 'bytes')
