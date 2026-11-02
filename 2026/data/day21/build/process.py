"""Day 21 (OpenStreetMap): bubble tea chains in Singapore, as OSM maps them, and the tagging to-do list.

Requires: osmium shapely pyproj
usage: python -I process.py <raw-dir> <out-dir>          writes <out-dir>/bubbletea.js

What it does
  1. Reads every node, way and multipolygon in the Singapore OSM extract and keeps the ones that sell
     something (amenity / shop / cuisine) whose name, name:en, name:zh, brand or official_name matches
     a chain in chains.py, or whose brand:wikidata is a chain's Wikidata item. Everything else tagged
     cuisine=bubble_tea is kept as "other" (independents and one-shop brands).
  2. Keeps only what lies inside Singapore (OSM relation 536780); the extract also covers Johor and Batam.
     Shops whose only amenity/shop tag carries a lifecycle prefix (disused:, was:, construction: ...) are
     closed or not yet open in OSM's eyes, and are left out.
  3. Scores each outlet's tags: brand, brand:wikidata, cuisine=bubble_tea, opening_hours, an address
     (addr:street or addr:postcode) and a floor (level or addr:floor).
  4. Writes the gap list: name-only matches with no brand tag; brand tag but no brand:wikidata (only for
     chains that have a Wikidata item); brand or brand:wikidata spelt differently from the chain's
     standard; names that are the standard name with a typo-level difference (case, accents, hyphens);
     same-chain outlets within TWIN_M metres of each other; outlets not tagged cuisine=bubble_tea;
     and odd ones (two shops on one point, no amenity/shop tag, notes in the name).
  5. Names each outlet's place: the smallest named mall, building, station, market or campus it sits in,
     else "near" the closest neighbourhood or suburb name.
  6. Draws Singapore's land outline (closed natural=coastline rings) as an SVG path for the small multiples.
"""
import collections
import datetime
import json
import math
import os
import re
import sys
import unicodedata

import osmium
import shapely
import shapely.wkb as wkb
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True   # keep build/ free of __pycache__
sys.path.insert(0, HERE)
from chains import CHAINS  # noqa: E402

RAW, OUT = sys.argv[1], sys.argv[2]
PBF = os.path.join(RAW, 'singapore-latest.osm.pbf')
TWIN_M = 30           # same chain closer than this: probably one shop mapped twice
SELL_AMENITY = {'cafe', 'fast_food', 'ice_cream', 'restaurant', 'food_court', 'bar', 'kiosk'}
# a chain's name on something that is plainly something else (a farm, a pond, a building, a bus stop)
FEATURE_KEYS = ('amenity', 'shop', 'landuse', 'leisure', 'natural', 'man_made', 'tourism', 'office', 'craft', 'healthcare',
                'building', 'highway', 'public_transport', 'railway', 'waterway', 'place', 'boundary', 'club', 'historic', 'aeroway')
NAME_KEYS = ('name', 'name:en', 'name:zh', 'brand', 'official_name', 'brand:en', 'name:zh-Hans', 'name:zh-Hant')
FIELDS = [   # key, label, test
    ('brand', 'brand', lambda t: bool(t.get('brand'))),
    ('wikidata', 'brand:wikidata', lambda t: bool(t.get('brand:wikidata'))),
    ('cuisine', 'cuisine=bubble_tea', lambda t: 'bubble_tea' in [c.strip() for c in t.get('cuisine', '').split(';')]),
    ('hours', 'opening_hours', lambda t: bool(t.get('opening_hours'))),
    ('address', 'address', lambda t: bool(t.get('addr:street') or t.get('addr:postcode'))),
    ('level', 'floor', lambda t: bool(t.get('level') or t.get('addr:floor'))),
]

for c in CHAINS:
    c['re'] = re.compile(c['match'], re.I)
    c['veto'] = re.compile(c['not_'], re.I) if c.get('not_') else None
BY_QID = {c['qid']: c for c in CHAINS if c.get('qid')}

# ---- the Name Suggestion Index and Wikidata: check the standards chains.py uses ----
nsi = {}
for f in os.listdir(RAW):
    if f.startswith('nsi-') and f.endswith('.json'):
        for it in json.load(open(os.path.join(RAW, f), encoding='utf-8'))['items']:
            q = it['tags'].get('brand:wikidata')
            inc = [str(x) for x in it.get('locationSet', {}).get('include', [])]
            # an entry for Singapore (or the world) wins over one for somewhere else
            if q and (q not in nsi or 'sg' in inc or '001' in inc):
                nsi[q] = it
for c in CHAINS:
    if c['nsi']:
        it = nsi.get(c['qid'])
        if not it or it['tags'].get('brand') != c['brand'] or it['tags'].get('name') != c['name']:
            sys.exit(f"chains.py disagrees with the Name Suggestion Index for {c['label']}: {it and it['tags']}")
        c['preset'] = {k: v for k, v in it['tags'].items() if k in ('amenity', 'shop', 'cuisine', 'brand', 'brand:wikidata', 'name')}
wd = json.load(open(os.path.join(RAW, 'wikidata.json'), encoding='utf-8'))['entities']
for c in CHAINS:
    if c['qid']:
        e = wd.get(c['qid'], {})
        if 'missing' in e or not e.get('labels'):
            sys.exit(f"Wikidata item {c['qid']} for {c['label']} is missing")
        c['wdLabel'] = (e['labels'].get('en') or e['labels'].get('zh'))['value']
        if not c['nsi'] and c['wdLabel'] != c['brand']:
            sys.exit(f"{c['label']}: chains.py says {c['brand']!r}, Wikidata's label is {c['wdLabel']!r}")
# chains with no Wikidata item: fetch.py's search must have found none
found = json.load(open(os.path.join(RAW, 'wikidata-search.json'), encoding='utf-8'))
for c in CHAINS:
    if not c['qid'] and found.get(c['label']):
        sys.exit(f"{c['label']}: Wikidata search now finds {found[c['label']]}; add the item to chains.py if it is this chain")


def norm(s):
    """Fold case, accents and punctuation: 'KOI The' == 'KOI Thé', 'Each-a-Cup' == 'Each A Cup'."""
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r'[\s\-_.’\'·]+', '', s.lower())


def chain_of(t):
    q = t.get('brand:wikidata')
    if q in BY_QID:
        return BY_QID[q]
    text = ' | '.join(t[k] for k in NAME_KEYS if t.get(k))
    for c in CHAINS:
        # anchored patterns (^...$) are tested against each name on its own
        vals = [t[k] for k in NAME_KEYS if t.get(k)] if '^' in c['match'] else [text]
        if any(c['re'].search(v) for v in vals) and not (c['veto'] and c['veto'].search(text)):
            return c
    return None


def sells(t):
    if t.get('amenity') == 'vending_machine':
        return False
    return bool(t.get('shop') or t.get('amenity') in SELL_AMENITY or 'bubble_tea' in t.get('cuisine', ''))


fab = osmium.geom.WKBFactory()
cands, others, coast, places, containers = [], [], [], [], []
sg = None
CONTAINER = lambda t: t.get('name') and (t.get('shop') in ('mall', 'department_store') or t.get('amenity') in (
    'marketplace', 'food_court', 'hospital', 'university', 'college') or t.get('building') or t.get('railway') == 'station'
    or t.get('public_transport') == 'station' or t.get('aeroway') == 'terminal' or t.get('landuse') == 'retail')


LIFECYCLE = re.compile(r'^(disused|was|abandoned|demolished|removed|razed|closed|construction|proposed|planned|not):(amenity|shop)$')
closed = []


def keep(o, t, geom_pt, otype, oid):
    c = chain_of(t)
    if not (t.get('amenity') or t.get('shop')) and any(LIFECYCLE.match(k) for k in t):
        closed.append((c, otype, oid, t, geom_pt))   # a shop OSM marks as closed (or not yet open): not an outlet
        return
    if c and sells(t):
        cands.append((c, otype, oid, t, geom_pt))
    elif c and not any(t.get(k) for k in FEATURE_KEYS):
        cands.append((c, otype, oid, t, geom_pt))   # a chain name with no other tag at all: an odd one
    elif 'bubble_tea' in t.get('cuisine', ''):
        others.append((otype, oid, t, geom_pt))


for o in osmium.FileProcessor(PBF).with_locations().with_areas():
    t = dict(o.tags)
    if not t:
        continue
    if o.is_area():
        if not o.from_way() and o.orig_id() == 536780:
            sg = wkb.loads(fab.create_multipolygon(o), hex=True)
            continue
        if CONTAINER(t):
            try:
                containers.append((t['name'], wkb.loads(fab.create_multipolygon(o), hex=True)))
            except RuntimeError:
                pass
        if not o.from_way() and (chain_of(t) or 'bubble_tea' in t.get('cuisine', '')):
            try:
                g = wkb.loads(fab.create_multipolygon(o), hex=True)
                keep(o, t, g.representative_point(), 'relation', o.orig_id())
            except RuntimeError:
                pass
        continue
    if o.is_way() and t.get('natural') == 'coastline':
        coast.append(wkb.loads(fab.create_linestring(o), hex=True))
        continue
    if o.is_node():
        if t.get('place') in ('suburb', 'neighbourhood', 'quarter', 'town', 'village') and t.get('name'):
            places.append((t['name'], shapely.Point(o.location.lon, o.location.lat)))
        if chain_of(t) or 'bubble_tea' in t.get('cuisine', ''):
            keep(o, t, shapely.Point(o.location.lon, o.location.lat), 'node', o.id)
    elif o.is_way() and (chain_of(t) or 'bubble_tea' in t.get('cuisine', '')):
        try:
            g = wkb.loads(fab.create_linestring(o), hex=True)
        except RuntimeError:
            continue
        g = shapely.Polygon(g.coords) if g.is_closed and len(g.coords) > 3 else g
        keep(o, t, g.representative_point() if g.geom_type == 'Polygon' else g.centroid, 'way', o.id)

if sg is None:
    sys.exit('Singapore boundary (relation 536780) missing from the extract')
inside = shapely.prepared.prep(sg)
n_before = len(cands)
cands = [x for x in cands if inside.contains(x[4])]
others = [x for x in others if inside.contains(x[3])]
closed = [x for x in closed if inside.contains(x[4])]
print(f'chain outlets {len(cands)} (dropped {n_before - len(cands)} outside Singapore), other bubble tea {len(others)}, '
      f'left out as closed or not yet open {len(closed)}: ' + ', '.join(f"{x[1]} {x[2]} {x[3].get('name', '')}" for x in closed))

# ---- where each outlet is ----
ctree = STRtree([g for _, g in containers])
ptree = STRtree([p for _, p in places])
M_PER_DEG = 111320


def where(pt):
    hits = [i for i in ctree.query(pt) if containers[i][1].contains(pt)]
    if hits:
        i = min(hits, key=lambda i: containers[i][1].area)
        name = containers[i][0]
        return ('Block ' + name if re.fullmatch(r'\d+[A-Z]?', name) else name), True   # HDB blocks are named by number
    i = ptree.nearest(pt)
    return places[i][0], False


def metres(a, b):
    kx = M_PER_DEG * math.cos(math.radians((a.y + b.y) / 2))
    return math.hypot((a.x - b.x) * kx, (a.y - b.y) * 110574)


# ---- outlets, tag scores, spellings ----
SHORT = {'node': 'n', 'way': 'w', 'relation': 'r'}
outlets = []
for c, otype, oid, t, pt in sorted(cands, key=lambda x: (CHAINS.index(x[0]), x[1], x[2])):
    flags = sum(1 << i for i, (_, _, f) in enumerate(FIELDS) if f(t))
    w, inn = where(pt)
    main = ('amenity=' + t['amenity']) if t.get('amenity') else ('shop=' + t['shop']) if t.get('shop') else ''
    outlets.append(dict(c=c, type=otype, id=oid, t=t, pt=pt, flags=flags, where=w, inside=inn, main=main))

# standard spellings: with no NSI entry and no Wikidata item, the spelling OSM uses most
for c in CHAINS:
    mine = [o for o in outlets if o['c'] is c]
    vals = collections.Counter([o['t']['brand'] for o in mine if o['t'].get('brand')] + [o['t']['name'] for o in mine if o['t'].get('name')])
    c['n'] = len(mine)
    if mine and not c['nsi'] and not c['qid']:
        top = vals.most_common(1)[0][0]
        if top != c['name']:
            sys.exit(f"{c['label']}: the spelling OSM uses most is now {top!r} ({vals[top]}), chains.py says {c['name']!r} ({vals[c['name']]})")

gaps = []   # (outlet index, kind, text, fix, extra)
for i, o in enumerate(outlets):
    c, t = o['c'], o['t']
    brand, q, name = t.get('brand'), t.get('brand:wikidata'), t.get('name', '')
    want = f"brand={c['brand']}" + (f" + brand:wikidata={c['qid']}" if c['qid'] else '')
    if not brand:
        how = 'its brand:wikidata' if q == c['qid'] and q else 'its name'
        gaps.append((i, 'brand', f'Matched by {how} only: no brand tag', 'Add ' + want, None))
    elif brand != c['brand']:
        gaps.append((i, 'spelling', f'brand={brand}', f"Change to brand={c['brand']}", None))
    if brand and c['qid'] and not q:
        gaps.append((i, 'wikidata', 'Has a brand, but no brand:wikidata', f"Add brand:wikidata={c['qid']}", None))
    if q and c['qid'] and q != c['qid']:
        gaps.append((i, 'spelling', f'brand:wikidata={q}', f"Change to brand:wikidata={c['qid']} ({c['wdLabel']})", None))
    if q and not c['qid']:
        gaps.append((i, 'spelling', f'brand:wikidata={q}, but we found no Wikidata item for {c["label"]}', 'Check the item is this chain', None))
    if name and name != c['name'] and norm(name) == norm(c['name']):
        gaps.append((i, 'spelling', f'name={name}', f"Change to name={c['name']}", None))
    if not FIELDS[2][2](t):
        gaps.append((i, 'cuisine', f"Not marked as bubble tea{(' (' + o['main'] + ')') if o['main'] else ''}", 'Add cuisine=bubble_tea', None))
    odd = []
    if ';' in name:
        odd.append(('Two shops share one point', 'Split into one point per shop'))
    if not o['main']:
        odd.append(('No amenity or shop tag, so most maps hide it', 'Add amenity=cafe'))
    if re.search(r'here|somewhere|closed|\?', name, re.I):
        odd.append(('The name holds a note, not a shop name', 'Check on the ground, then fix the name'))
    for text, fix in odd:
        gaps.append((i, 'odd', text, fix, None))

# twins: same chain, closer than TWIN_M metres
seen = set()
for c in CHAINS:
    mine = [i for i, o in enumerate(outlets) if o['c'] is c]
    for a in mine:
        for b in mine:
            if a < b:
                d = metres(outlets[a]['pt'], outlets[b]['pt'])
                if d < TWIN_M and (a, b) not in seen:
                    seen.add((a, b))
                    oa, ob = outlets[a], outlets[b]
                    same_level = (oa['t'].get('level') or '?') == (ob['t'].get('level') or '?')
                    la, lb = oa['t'].get('level'), ob['t'].get('level')
                    lv = '' if same_level else f" (level {la} here, {'level ' + lb if lb else 'no level'} there)" if la else f" ({'level ' + lb if lb else 'no level'} there, no level here)"
                    gaps.append((a, 'twin', f"{round(d)} m from {ob['type']} {ob['id']}{lv}",
                                 'Same shop twice? Merge them' if same_level else 'Check: same shop, or two floors?', [b, round(d, 1)]))

kinds = collections.Counter(g[1] for g in gaps)
print('gaps', len(gaps), dict(kinds), 'outlets with at least one gap', len({g[0] for g in gaps}))

# ---- Singapore's land, for the small multiples ----
merged = linemerge(coast)
rings = [g for g in getattr(merged, 'geoms', [merged]) if g.is_closed]
land = unary_union([shapely.Polygon(r) for r in rings if shapely.LinearRing(r.coords).is_ccw]).intersection(sg)
polys = [p for p in getattr(land, 'geoms', [land]) if p.geom_type == 'Polygon' and p.area * M_PER_DEG ** 2 > 0.15e6]
W, S, E, N = 103.596, 1.2, 104.09, 1.475
LAT0 = 1.35
KX = math.cos(math.radians(LAT0))
VW = 1000
SC = VW / ((E - W) * KX)
VH = round((N - S) * SC)


def px(x, y):
    return (x - W) * KX * SC, (N - y) * SC


def path(poly, tol):
    p = poly.simplify(tol, preserve_topology=True)
    out = []
    for ring in [p.exterior]:
        pts = [px(x, y) for x, y in ring.coords]
        out.append('M' + 'L'.join(f'{x:.1f},{y:.1f}' for x, y in pts[:-1]) + 'Z')
    return ''.join(out)


outline = ''.join(path(p, 0.0007) for p in sorted(polys, key=lambda p: -p.area))
print('land polygons', len(polys), 'outline chars', len(outline))

# ---- write ----
_r = osmium.io.Reader(PBF, osmium.osm.osm_entity_bits.NOTHING)
extract_time = _r.header().get('osmosis_replication_timestamp') or datetime.datetime.fromtimestamp(os.path.getmtime(PBF), datetime.timezone.utc).isoformat()
_r.close()
ci = {c['id']: k for k, c in enumerate(CHAINS)}
counts = collections.Counter(o['c']['id'] for o in outlets)
spell = {}
for c in CHAINS:
    mine = [o for o in outlets if o['c'] is c]
    spell[c['id']] = {
        'name': collections.Counter(o['t'].get('name', '(no name)') for o in mine).most_common(),
        'brand': collections.Counter(o['t'].get('brand', '(none)') for o in mine).most_common(),
        'main': collections.Counter(o['main'] or '(none)' for o in mine).most_common(),
    }
r5 = lambda v: round(v, 5)
data = {
    'built': datetime.date.today().isoformat(),
    'extract': extract_time,
    'twinM': TWIN_M,
    'fields': [[k, label] for k, label, _ in FIELDS],
    'view': {'w': W, 's': S, 'e': E, 'n': N, 'kx': KX, 'sc': SC, 'vw': VW, 'vh': VH},
    'outline': outline,
    'chains': [dict(id=c['id'], label=c['label'], brand=c['brand'], name=c['name'], qid=c['qid'], nsi=c['nsi'],
                    wd=c.get('wdLabel'), fill=c['fill'], ink=c['ink'], n=counts[c['id']], spell=spell[c['id']],
                    f=[sum(1 for o in outlets if o['c'] is c and o['flags'] >> k & 1) for k in range(len(FIELDS))],
                    gaps=sum(1 for g in gaps if outlets[g[0]]['c'] is c))
               for c in CHAINS if counts[c['id']]],
    'totals': dict(outlets=len(outlets), chains=sum(1 for c in CHAINS if counts[c['id']]), others=len(others),
                   brand=sum(1 for o in outlets if o['flags'] & 1), wikidata=sum(1 for o in outlets if o['flags'] & 2),
                   wdEligible=sum(1 for o in outlets if o['c']['qid']),
                   wikidataOk=sum(1 for o in outlets if o['c']['qid'] and o['t'].get('brand:wikidata') == o['c']['qid']),
                   gaps=len(gaps), gapOutlets=len({g[0] for g in gaps}),
                   names=max((len(spell[c['id']]['name']), c['label']) for c in CHAINS if counts[c['id']])),
    # outlet: chain id, lon, lat, osm type letter, osm id, name, place, inside the place?, tag flags, brand, brand:wikidata, main tag, level, opening_hours
    'outlets': [[o['c']['id'], r5(o['pt'].x), r5(o['pt'].y), SHORT[o['type']], o['id'], o['t'].get('name', ''), o['where'], int(o['inside']),
                 o['flags'], o['t'].get('brand', ''), o['t'].get('brand:wikidata', ''), o['main'], o['t'].get('level', o['t'].get('addr:floor', '')),
                 o['t'].get('opening_hours', '')] for o in outlets],
    'gaps': [[g[0], g[1], g[2], g[3]] + ([g[4]] if g[4] else []) for g in gaps],
    'others': [[r5(p.x), r5(p.y), SHORT[ty], oid, t.get('name', '') or t.get('name:en', ''), int('brand' in t)] for ty, oid, t, p in others],
}
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'bubbletea.js'), 'w', encoding='utf-8') as f:
    f.write('window.DAY21 = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n')
print('bubbletea.js', os.path.getsize(os.path.join(OUT, 'bubbletea.js')), 'bytes')
for c in sorted(CHAINS, key=lambda c: -counts[c['id']]):
    mine = [o for o in outlets if o['c'] is c]
    if mine:
        fill = [sum(1 for o in mine if o['flags'] >> k & 1) for k in range(len(FIELDS))]
        print(f"  {c['label']:<18}{len(mine):>4}  " + ' '.join(f'{f:>3}' for f in fill))
