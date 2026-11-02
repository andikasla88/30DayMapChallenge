"""Day 27 New tool: Singapore's underground, drawn by depth. Turns the OSM extract into ../underground.js.

usage: python -I process.py <raw-dir> <out.json>
requirements: osmium>=4 (pyosmium), shapely>=2, numpy
  python -m venv venv && venv/Scripts/pip install osmium shapely numpy

What it writes
  lines     MRT lines that run underground: id, name, colour.
  tunnels   every underground MRT track in OpenStreetMap (railway=subway, or railway=construction
            with construction=subway, tagged tunnel=yes or on a layer below 0), merged per line and
            status, simplified to 3 m, as [line, status, depth key, encoded coordinates].
            Depth key 'typ' = no published depth for this stretch (the page draws LTA's stated
            typical band, 20 to 30 m). Other keys point into DEPTHS below.
  stations  stations within 70 m of an underground track: name, position, lines, status.
  pins      the published depths that belong to a point: their position comes from OSM.
  jrc       the Jurong Rock Caverns outline as mapped in OSM (way 1065800494).
  wrp       the three DTSS water reclamation plants (outline and centre) and their tunnel depths.
  ccnr      the Central Catchment Nature Reserve outline (OSM relation 13463678), simplified to 20 m.
  stats     the numbers quoted on the page, computed here.

Coordinates are [lon, lat] x 1e5, delta-encoded per ring or line.
Lengths are measured in a local metric frame (Web Mercator scaled by cos 1.35 deg, accurate
to better than 0.1% across Singapore).
"""
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np
import osmium
import shapely
from shapely import wkb
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, unary_union, nearest_points

RAW, OUT = sys.argv[1], sys.argv[2]
PBF = os.path.join(RAW, 'singapore-latest.osm.pbf')

# ---------- the published depths: every number drawn as "published" on the page ----------
# Each is quoted from an authoritative source; the page cites the same links.
DEPTHS = {
    'bcl': {'m': 43, 'what': 'Bencoolen station (Downtown Line)',
            'src': 'LTA, Downtown Line: "At 43m below ground, this is the deepest MRT station in Singapore."',
            'url': 'https://www.lta.gov.sg/content/ltaweb/en/public-transport/projects/downtown-line/maps.html'},
    'bft': {'m': 43, 'what': 'Downtown Line tunnel, Bencoolen to Fort Canning',
            'src': 'LTA, Downtown Line: "At 43m deep, this tunnel is the deepest one in Singapore."',
            'url': 'https://www.lta.gov.sg/content/ltaweb/en/public-transport/projects/downtown-line/maps.html'},
    'kap': {'m': 50, 'what': 'Cross Island Line King Albert Park station (being built)',
            'src': 'LTA news release, 7 Jul 2025: "At 50 metres deep ... CRL King Albert Park"',
            'url': 'https://www.lta.gov.sg/content/ltagov/en/newsroom/2025/7/news-releases/construction_begins_on_crl2.html'},
    'pse': {'m': 47, 'what': 'Cross Island Line Pasir Ris station (being built)',
            'src': 'LTA news release, 7 Jul 2025: "the CRL Pasir Ris station which, when completed, will be 47 metres deep"',
            'url': 'https://www.lta.gov.sg/content/ltagov/en/newsroom/2025/7/news-releases/construction_begins_on_crl2.html'},
    'ccnr': {'m': 70, 'what': 'Cross Island Line under the Central Catchment Nature Reserve (being built)',
             'src': 'MOT, 4 Dec 2019: "as deep as 70 metres below average ground level" for the 2 km under the reserve',
             'url': 'https://www.mot.gov.sg/news-resources/newsroom/cross-island-line-to-run-70-metres-under-central-catchment-nature-reserve/'},
}
TYPICAL = {'lo': 20, 'hi': 30,
           'src': 'MOT/LTA, 4 Dec 2019: "The typical tunnelling depth for LTA\'s rail projects is approximately 20 to 30 metres below average ground level."',
           'url': 'https://www.mot.gov.sg/news-resources/newsroom/cross-island-line-to-run-70-metres-under-central-catchment-nature-reserve/'}
DTSS = {
    'p1': {'lo': 18, 'hi': 50, 'what': 'DTSS Phase 1: North and Spur Tunnels, 48 km, 3.3 to 6 m across',
           'src': 'PUB: "a length of 48km for DTSS Phase 1, diameters of 3.3 - 6m and depths of 18 - 50m"',
           'url': 'https://www.pub.gov.sg/Industry/Events%20and%20Programmes/Global%20Innovation%20Challenge/Challenges/2024/Condition%20Assessment%20of%20Deep%20Tunnel%20Sewerage%20System%20Tunnel'},
    'p2s': {'lo': 35, 'hi': 55, 'what': 'DTSS Phase 2: South (Domestic) Used Water Tunnel, 28 km, 3 to 6 m across',
            'src': 'PUB news release, Aug 2023, Annex: length 28 km, diameter 3m - 6m, tunnel depth 35 - 55m',
            'url': 'https://www.pub.gov.sg/Resources/News-Room/PressReleases/2023/08/PUB-completes-tunneling-works-for-second-phase-of-Deep-Tunnel-Sewerage-System'},
    'p2i': {'lo': 45, 'hi': 55, 'what': 'DTSS Phase 2: Industrial Used Water Tunnel, 7 km, 3.3 to 4 m across',
            'src': 'PUB news release, Aug 2023, Annex: length 7 km, diameter 3.3m to 4m, depth 45 - 55m',
            'url': 'https://www.pub.gov.sg/Resources/News-Room/PressReleases/2023/08/PUB-completes-tunneling-works-for-second-phase-of-Deep-Tunnel-Sewerage-System'},
}
JRC = {'m': 150, 'seabed': 130,
       'src': 'JTC: "Located at a depth of 150m below the ground, and 130m beneath the Banyan Basin on Jurong Island"; '
              '"JRC can store up to 1.47 million m3 of liquid hydrocarbons"',
       'url': 'https://www.jtc.gov.sg/find-space/jurong-rock-caverns', 'capacity_m3': 1470000}

LINES = [  # id, name, official colour
    ('NSL', 'North–South Line', '#D42E12'),
    ('EWL', 'East–West Line', '#009645'),
    ('NEL', 'North East Line', '#9900AA'),
    ('CCL', 'Circle Line', '#FA9E0D'),
    ('DTL', 'Downtown Line', '#005EC4'),
    ('TEL', 'Thomson–East Coast Line', '#9D5B25'),
    ('CRL', 'Cross Island Line', '#97C616'),
]
LINE_IX = {l[0]: i for i, l in enumerate(LINES)}

# ---------- local metric frame ----------
LON0, LAT0 = 103.82, 1.35
R = 6378137.0
K = R * math.cos(math.radians(LAT0))
mercY = lambda lat: math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
Y0 = mercY(LAT0)


def fwd(lon, lat, z=None):
    return (K * math.radians(lon - LON0), K * (mercY(lat) - Y0))


def inv(x, y, z=None):
    lat = math.degrees(2 * math.atan(math.exp(y / K + Y0)) - math.pi / 2)
    return (LON0 + math.degrees(x / K), lat)


to_m = lambda g: shapely.transform(g, lambda a: np.array([fwd(x, y) for x, y in a]).reshape(-1, 2))
to_ll = lambda g: shapely.transform(g, lambda a: np.array([inv(x, y) for x, y in a]).reshape(-1, 2))


def enc(coords):
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * 1e5), round(y * 1e5)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def line_of(t):
    s = ' '.join([t.get('ref', ''), t.get('name', ''), t.get('name:en', '')])
    for key, words in [('CRL', ['CRL', 'Cross Island', 'CPe', 'CR1']), ('TEL', ['TEL', 'Thomson', 'TE32']),
                       ('DTL', ['DTL', 'Downtown']), ('CCL', ['CCL', 'Circle']), ('NEL', ['NEL', 'North East']),
                       ('NSL', ['NSL', 'North South', 'North-South']), ('EWL', ['EWL', 'East West', 'East-West', 'CGL'])]:
        if any(w in s for w in words):
            return key
    return None


# ---------- pass 1: which line each unnamed way belongs to, from the route relations ----------
REF2 = {'NSL': 'NSL', 'EWL': 'EWL', 'CGL': 'EWL', 'NEL': 'NEL', 'CCL': 'CCL', 'DTL': 'DTL', 'TEL': 'TEL', 'CRL': 'CRL', 'CPe': 'CRL'}
way_line = {}
for o in osmium.FileProcessor(PBF, osmium.osm.RELATION):
    t = dict(o.tags)
    if t.get('route') in ('subway', 'construction') and t.get('ref') in REF2:
        for m in o.members:
            if m.type == 'w':
                way_line.setdefault(m.ref, REF2[t['ref']])

# ---------- pass 2: tunnels, stations, outlines ----------
fab = osmium.geom.WKBFactory()
tracks = []          # (line, status, shapely LineString in metres, way id)
unassigned = []
stops = defaultdict(list)   # name -> [(lon, lat, status)]
jrc = None
wrp = {}
ccnr = None
WRP_IDS = {('w', 266397369): 'Changi', ('w', 1004232926): 'Tuas', ('r', 2750400): 'Kranji'}

proc = osmium.FileProcessor(PBF).with_locations().with_areas(osmium.filter.KeyFilter('man_made', 'leisure', 'boundary'))
for o in proc:
    if o.is_area():
        oid = ('w' if o.from_way() else 'r', o.orig_id())
        t = dict(o.tags)
        try:
            g = wkb.loads(fab.create_multipolygon(o), hex=True)
        except Exception:
            continue
        if oid == ('w', 1065800494):
            jrc = g
        elif oid in WRP_IDS:
            wrp[WRP_IDS[oid]] = g
        elif oid == ('r', 13463678):
            ccnr = g
        continue
    t = dict(o.tags)
    if o.is_node():
        rw = t.get('railway')
        if (rw in ('station', 'stop', 'construction') and (t.get('subway') == 'yes' or t.get('station') == 'subway')) and t.get('name'):
            st = 'construction' if (rw == 'construction' or 'construction' in t) else 'open'
            stops[t['name']].append((o.location.lon, o.location.lat, st))
        continue
    if not o.is_way():
        continue
    rw = t.get('railway')
    if rw == 'subway':
        status = 'open'
    elif rw == 'construction' and t.get('construction') in ('subway', 'rail'):
        status = 'construction'
    else:
        continue
    try:
        layer = int(t.get('layer', '0'))
    except ValueError:
        layer = 0
    if not (t.get('tunnel') == 'yes' or layer < 0) or t.get('bridge'):
        continue
    if t.get('service') in ('yard', 'siding'):
        continue
    g = to_m(wkb.loads(fab.create_linestring(o), hex=True))
    ln = line_of(t) or way_line.get(o.id)
    if ln == 'RTS' or (ln is None and 'Johor' in t.get('name', '')):
        continue
    if ln:
        tracks.append([ln, status, g, o.id])
    else:
        unassigned.append([status, g, o.id])

# unnamed ways without a route relation take the line of the nearest named track
for status, g, wid in unassigned:
    best = min(tracks, key=lambda tr: tr[2].distance(g))
    if best[2].distance(g) < 300:
        tracks.append([best[0], status, g, wid])
    else:
        print('dropped unassigned way', wid, file=sys.stderr)

print('tracks', len(tracks), 'unassigned', len(unassigned), file=sys.stderr)

# ---------- published stretches ----------
def stop_xy(name, pick=None):
    pts = stops[name]
    if pick:
        pts = [p for p in pts if pick(p)]
    xs = [fwd(p[0], p[1]) for p in pts]
    return Point(sum(x for x, _ in xs) / len(xs), sum(y for _, y in xs) / len(xs))


bcl = stop_xy('Bencoolen')
fcn = stop_xy('Fort Canning')
corridor = LineString([fcn, bcl]).buffer(90, cap_style='flat')
ccnr_m = to_m(ccnr)

groups = defaultdict(list)    # (line, status, key) -> [LineString]
stats = defaultdict(float)
for ln, status, g, wid in tracks:
    stats[f'km_{status}'] += g.length / 1000
    stats[f'km_{ln}_{status}'] += g.length / 1000
    pieces = [(g, 'typ')]
    if ln == 'DTL' and status == 'open':
        inside = g.intersection(corridor)
        pieces = [(inside, 'bft'), (g.difference(corridor), 'typ')]
    elif ln == 'CRL':
        inside = g.intersection(ccnr_m)
        pieces = [(inside, 'ccnr'), (g.difference(ccnr_m), 'typ')]
    for piece, key in pieces:
        if piece.is_empty:
            continue
        parts = list(piece.geoms) if hasattr(piece, 'geoms') else [piece]
        for p in parts:
            if p.length > 1:
                groups[(ln, status, key)].append(p)
                if key != 'typ':
                    stats[f'm_{key}'] += p.length

tunnels = []
for (ln, status, key), parts in sorted(groups.items()):
    merged = linemerge(MultiLineString(parts))
    for p in (merged.geoms if hasattr(merged, 'geoms') else [merged]):
        p = p.simplify(3)
        tunnels.append([LINE_IX[ln], 0 if status == 'open' else 1, key, enc(to_ll(p).coords)])

# ---------- stations ----------
alltracks = unary_union([g for _, _, g, _ in tracks])
stations = []
for name, pts in sorted(stops.items()):
    for status in ('open', 'construction'):
        ps = [p for p in pts if p[2] == status]
        if not ps:
            continue
        xy = [fwd(p[0], p[1]) for p in ps]
        pt = Point(sum(x for x, _ in xy) / len(xy), sum(y for _, y in xy) / len(xy))
        near = [tr for tr in tracks if tr[2].distance(pt) < 70]
        if not near:
            continue
        lines = sorted({LINE_IX[tr[0]] for tr in near})
        lon, lat = inv(pt.x, pt.y)
        stations.append([name, round(lon * 1e5), round(lat * 1e5), lines, 0 if status == 'open' else 1])
# a name can appear twice (open and construction) at the same place: keep the open one only
seen = {}
for s in stations:
    k = s[0]
    if k in seen and math.hypot(s[1] - seen[k][1], s[2] - seen[k][2]) < 300:
        seen[k][3] = sorted(set(seen[k][3]) | set(s[3]))
        continue
    seen.setdefault(k, s)
stations = [s for s in stations if seen.get(s[0]) is s]


def on_line(ln, pt, status=None):
    """The point on line ln's underground track nearest to pt (metres)."""
    cands = [tr[2] for tr in tracks if tr[0] == ln and (status is None or tr[1] == status)]
    u = unary_union(cands)
    return nearest_points(u, pt)[0]


crl = [tr for tr in tracks if tr[0] == 'CRL']
pins = []
def pin(key, p, note=''):
    lon, lat = inv(p.x, p.y)
    pins.append({'k': key, 'x': round(lon * 1e5), 'y': round(lat * 1e5)})

pin('bcl', bcl)
kap_st = stop_xy('King Albert Park')
pse_st = stop_xy('Pasir Ris')
kap = on_line('CRL', kap_st)
pse = on_line('CRL', pse_st)
stats['kap_offset_m'] = kap.distance(kap_st)
stats['pse_offset_m'] = pse.distance(pse_st)
if stats['kap_offset_m'] < 400:
    pin('kap', kap)
if stats['pse_offset_m'] < 400:
    pin('pse', pse)
# the CCNR stretch: its middle
cc_parts = [p for (ln, s, k), ps in groups.items() if k == 'ccnr' for p in ps]
if cc_parts:
    u = unary_union(cc_parts)
    c = u.centroid
    pin('ccnr', nearest_points(u, c)[0])
bft_parts = [p for (ln, s, k), ps in groups.items() if k == 'bft' for p in ps]

# ---------- outlines ----------
def poly_enc(g, tol):
    g = to_ll(to_m(g).simplify(tol))
    polys = list(g.geoms) if hasattr(g, 'geoms') else [g]
    return [[enc(p.exterior.coords)] + [enc(r.coords) for r in p.interiors] for p in polys]


def centre(g):
    c = to_ll(to_m(g).representative_point())
    return [round(c.x * 1e5), round(c.y * 1e5)]

jrc_m = to_m(jrc)
out_wrp = []
for name, keys in [('Changi', ['p1']), ('Kranji', ['p1']), ('Tuas', ['p2s', 'p2i'])]:
    g = wrp[name]
    out_wrp.append({'n': f'{name} Water Reclamation Plant', 'c': centre(g), 'g': poly_enc(g, 5), 't': keys})

# station counts: open underground stations; an interchange counts once per name
open_st = [s for s in stations if s[4] == 0]
stats.update({
    'stations_open': len(open_st),
    'stations_construction': len([s for s in stations if s[4] == 1]),
    'jrc_area_m2': jrc_m.area,
    'ccnr_crl_tracks': len(cc_parts),
})
stats = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in stats.items()}

ts = None
try:
    ts = osmium.io.Reader(PBF, osmium.osm.osm_entity_bits.NOTHING).header().get('osmosis_replication_timestamp')
except Exception:
    pass

out = {
    'meta': {'osm': ts, 'frame': [LON0, LAT0]},
    'lines': [{'id': i, 'n': n, 'c': c} for i, n, c in LINES],
    'tunnels': tunnels,
    'stations': stations,
    'pins': pins,
    'depths': DEPTHS, 'typical': TYPICAL, 'dtss': DTSS,
    'jrc': {'g': poly_enc(jrc, 2), 'c': centre(jrc), **JRC},
    'wrp': out_wrp,
    'ccnr': {'g': poly_enc(ccnr, 20), 'c': centre(ccnr)},
    'stats': stats,
}
with open(OUT, 'w', encoding='utf-8') as f:
    f.write('window.DAY27 = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
print(json.dumps(stats, indent=1), file=sys.stderr)
print('wrote', OUT, os.path.getsize(OUT), 'bytes', file=sys.stderr)
