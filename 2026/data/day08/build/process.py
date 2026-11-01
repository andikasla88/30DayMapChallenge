"""Day 08 Utopia: turn every Singapore road into parkland and measure it.
Usage: python process.py <raw-dir> <out-json>
Reads roads.json and parks.json from fetch.py (OpenStreetMap via Overpass).
Width of each carriageway: the width tag, else lanes x 3.3 m, else a class default.
Tunnels are left out (they take no land). Areas are computed in SVY21 (EPSG:3414)."""
import sys, os, json, re
from collections import defaultdict
from shapely.geometry import LineString, Polygon, MultiPolygon
from shapely.ops import unary_union, transform, linemerge, polygonize
from shapely.geometry import MultiLineString
from shapely import STRtree
import warnings
warnings.filterwarnings('ignore', category=DeprecationWarning)
ALIAS = {'Marina Costal Expressway': 'Marina Coastal Expressway'}
from pyproj import Transformer

RAW, OUT = sys.argv[1], sys.argv[2]
fwd = Transformer.from_crs(4326, 3414, always_xy=True).transform
inv = Transformer.from_crs(3414, 4326, always_xy=True).transform
LANE = 3.3
CAT = {'motorway': 'x', 'motorway_link': 'x', 'trunk': 'a', 'trunk_link': 'a', 'primary': 'a', 'primary_link': 'a',
       'secondary': 'c', 'secondary_link': 'c', 'tertiary': 'c', 'tertiary_link': 'c',
       'unclassified': 'l', 'residential': 'l', 'living_street': 'l', 'service': 's'}
# default lanes when untagged: (one-way, two-way)
DEF_LANES = {'motorway': (3, 6), 'trunk': (3, 4), 'primary': (3, 4), 'secondary': (2, 3), 'tertiary': (2, 2),
             'unclassified': (1.5, 2), 'residential': (1.5, 2), 'living_street': (1.5, 2)}
SERVICE_W = {'driveway': 3.5, 'alley': 3.0, 'parking_aisle': 6.0, 'drive-through': 3.5, 'emergency_access': 4.0}


def num(s):
    m = re.match(r'\s*([0-9]+(?:\.[0-9]+)?)', s or '')
    return float(m.group(1)) if m else None


def width(t):
    hw = t['highway']
    w = num(t.get('width'))
    if w and 2 <= w <= 60 and 'ft' not in t.get('width', ''):
        return w
    lanes = num(t.get('lanes'))
    if lanes and 1 <= lanes <= 12:
        return lanes * LANE
    oneway = t.get('oneway') in ('yes', '1', '-1') or hw in ('motorway', 'motorway_link')
    if hw == 'service':
        return SERVICE_W.get(t.get('service'), 5.0)
    if hw.endswith('_link'):
        return 1.6 * LANE
    lo, lt = DEF_LANES[hw]
    return (lo if oneway else lt) * LANE


def enc(coords):   # Google polyline, precision 5, input [(lng, lat)]
    out, plat, plng = [], 0, 0
    for c in coords:
        lng, lat = c[0], c[1]
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        for d in (ilat - plat, ilng - plng):
            v = ~(d << 1) if d < 0 else d << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63))
                v >>= 5
            out.append(chr(v + 63))
        plat, plng = ilat, ilng
    return ''.join(out)


roads = json.load(open(os.path.join(RAW, 'roads.json'), encoding='utf-8'))['elements']
ways = []
skipped = defaultdict(float)
for e in roads:
    t = e.get('tags', {})
    hw = t.get('highway')
    if hw not in CAT or e.get('type') != 'way' or len(e.get('geometry') or []) < 2:
        continue
    if t.get('area') == 'yes':
        continue
    g = transform(fwd, LineString([(p['lon'], p['lat']) for p in e['geometry']]))
    if t.get('tunnel') in ('yes', 'building_passage', 'covered') or t.get('covered') == 'yes':
        skipped[CAT[hw]] += g.length
        continue
    oneway = t.get('oneway') in ('yes', '1', '-1') or hw == 'motorway'
    ways.append(dict(g=g, w=width(t), cat=CAT[hw], hw=hw, name=ALIAS.get((t.get('name') or '').strip(), (t.get('name') or '').strip()), ref=t.get('ref', ''), oneway=oneway))
print('ways', len(ways), 'tunnel km skipped', {k: round(v / 1000) for k, v in skipped.items()})

# ---- areas: dissolve per category, attribute overlaps to the higher class ----
ORDER = ['x', 'a', 'c', 'l', 's']
RANK = {c: i for i, c in enumerate(ORDER)}
buf = [w['g'].buffer(w['w'] / 2, quad_segs=2) for w in ways]
cat_union = {}
for c in ORDER:
    cat_union[c] = unary_union([b for b, w in zip(buf, ways) if w['cat'] == c])
    print('union', c, round(cat_union[c].area / 1e6, 2), flush=True)
acc = None
cat_area = {}
for c in ORDER:
    u = cat_union[c]
    cat_area[c] = u.difference(acc).area if acc is not None else u.area
    acc = u if acc is None else unary_union([acc, u])
total = acc.area
print('total km2', round(total / 1e6, 2), {c: round(a / 1e6, 2) for c, a in cat_area.items()})
cat_len = defaultdict(float)
for w in ways:
    cat_len[w['cat']] += w['g'].length


# ---- parks today (OpenStreetMap), a cross-check of the official figure ----
def park_geoms(elements):
    for e in elements:
        if e['type'] == 'way' and e.get('geometry') and len(e['geometry']) >= 4:
            c = [(p['lon'], p['lat']) for p in e['geometry']]
            if c[0] == c[-1]:
                yield Polygon(c)
        elif e['type'] == 'relation':
            mem = [m for m in e.get('members', []) if m.get('type') == 'way' and m.get('geometry') and len(m['geometry']) >= 2]
            outer = [LineString([(p['lon'], p['lat']) for p in m['geometry']]) for m in mem if m.get('role') in ('outer', '')]
            inner = [LineString([(p['lon'], p['lat']) for p in m['geometry']]) for m in mem if m.get('role') == 'inner']
            if not outer:
                continue
            po = unary_union(list(polygonize(linemerge(outer))))
            if inner:
                po = po.difference(unary_union(list(polygonize(linemerge(inner)))))
            if not po.is_empty:
                yield po


parks_osm = 0
pf = os.path.join(RAW, 'parks.json')
if os.path.exists(pf):
    pk = json.load(open(pf, encoding='utf-8'))['elements']
    pg = [transform(fwd, g.buffer(0)) for g in park_geoms(pk)]
    parks_u = unary_union([g for g in pg if g.is_valid and not g.is_empty])
    parks_osm = parks_u.area
    print('osm parks km2', round(parks_osm / 1e6, 2), 'roads inside parks km2', round(acc.intersection(parks_u).area / 1e6, 2))

# ---- per-name stats ----
by_name = defaultdict(list)
for i, w in enumerate(ways):
    if w['name']:
        by_name[w['name']].append(i)
names = sorted(by_name, key=lambda n: -sum(ways[i]['g'].length * ways[i]['w'] for i in by_name[n]))
nidx = {n: i for i, n in enumerate(names)}
stats = []
for n in names:
    ids = by_name[n]
    area = unary_union([buf[i] for i in ids]).area
    # one-way ways that run beside a twin (dual carriageways) count half towards the road's length
    ow = [i for i in ids if ways[i]['oneway']]
    paired = set()
    if len(ow) > 1:
        tree = STRtree([ways[i]['g'] for i in ow])
        for a, i in enumerate(ow):
            mid = ways[i]['g'].interpolate(0.5, normalized=True)
            for b in tree.query(mid.buffer(45)):
                if b != a and ways[ow[b]]['g'].distance(mid) < 45:
                    paired.add(i); break
    length = sum(ways[i]['g'].length / (2 if i in paired else 1) for i in ids)
    by_cat = defaultdict(float)
    for i in ids: by_cat[ways[i]['cat']] += ways[i]['g'].length * ways[i]['w']
    cat = max(by_cat, key=by_cat.get)
    ref = next((ways[i]['ref'] for i in ids if ways[i]['ref']), '')
    stats.append([round(length), round(area), cat, ref])

# ---- geometry: major roads as dissolved polygons per name, minor roads as lines ----
polys = []
groups = defaultdict(list)
for i, w in enumerate(ways):
    if w['cat'] in 'xac':
        groups[(w['name'], '' if w['name'] else w['cat'])].append(i)
for (n, c), ids in groups.items():
    u = unary_union([buf[i] for i in ids]).simplify(1.1, preserve_topology=True)
    cat = min((ways[i]['cat'] for i in ids), key=RANK.get)
    parts = list(u.geoms) if isinstance(u, MultiPolygon) else [u]
    rings = []
    for p in parts:
        if p.is_empty or p.area < 30:
            continue
        holes = [h for h in p.interiors if Polygon(h).area > 40]
        p = transform(inv, Polygon(p.exterior, holes))
        rings.append([enc(p.exterior.coords)] + [enc(h.coords) for h in p.interiors])
    if rings and n:
        polys.append([nidx[n], cat, rings])
    else:   # unnamed slip roads etc.: each connected piece is its own little park
        polys += [[-1, cat, [r]] for r in rings]
# minor roads: merge touching pieces of the same road and width, then group by (class, width)
lgroups = defaultdict(list)
for i, w in enumerate(ways):
    if w['cat'] in 'ls':
        lgroups[(w['cat'], round(w['w'] * 2) / 2, nidx[w['name']] if w['name'] else -1)].append(w['g'])
packed = defaultdict(list)
nlines = 0
for (c, wd, n), gs in lgroups.items():
    m = linemerge(gs)
    for g in (m.geoms if isinstance(m, MultiLineString) else [m]):
        g = transform(inv, g.simplify(1.6 if c == 's' else 1.3))
        packed[(c, wd)] += [n, enc(g.coords)]
        nlines += 1
lines = [[c, wd, arr] for (c, wd), arr in packed.items()]

# ---- 200 m grid of road area, for the on-screen hectare counter ----
D = 200.0
cells = defaultdict(float)
for w in ways:
    g, L = w['g'], w['g'].length
    k = max(1, int(L // 20))
    for j in range(k):
        p = g.interpolate((j + .5) * L / k)
        cells[(int(p.x // D), int(p.y // D))] += w['w'] * L / k
scale = total / sum(cells.values())
cell_arr = []
for (ix, iy), a in sorted(cells.items()):
    lng, lat = inv((ix + .5) * D, (iy + .5) * D)
    cell_arr += [round(lng, 4), round(lat, 4), max(1, round(a * scale / 100))]   # area in 100 m2 units

LAND_KM2 = 745.1        # SingStat M890621: total land area as at June 2026 (SLA)
PARKS_HA_URA = 6900     # SingStat M891211: land use allocation 2020, parks and nature reserves (URA)
TRANSPORT_HA_URA = 8400  # same table: land transport infrastructure
GBTB_HA = 101           # Gardens by the Bay, all three gardens
out = dict(
    v=1, built='2026-11-01',
    totals=dict(area=round(total), cat={c: round(a) for c, a in cat_area.items()}, len={c: round(v) for c, v in cat_len.items()},
                ways=len(ways), parksOSM=round(parks_osm), parksURA=PARKS_HA_URA * 10000, transportURA=TRANSPORT_HA_URA * 10000,
                land=round(LAND_KM2 * 1e6), gbtb=GBTB_HA * 10000, tunnel={c: round(v) for c, v in skipped.items()}),
    names=names, st=stats, P=polys, L=lines, cells=cell_arr)
s = json.dumps(out, separators=(',', ':'), ensure_ascii=False)
open(OUT, 'w', encoding='utf-8').write(s)
print('bytes', len(s), 'P chars', sum(len(r) for p in polys for part in p[2] for r in part), 'lines', nlines,
      'polys', len(polys), 'cells', len(cells))
print('top names:')
for n, s_ in list(zip(names, stats))[:120]:
    print(' ', n, s_)
