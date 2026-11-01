"""Day 14 Borgesian map: one street in extreme detail.
Usage: python -I process.py <raw-dir> <out-dir>
Requires: pyshp, pyproj, shapely, numpy  (pip install pyshp pyproj shapely numpy)

Reads what fetch.py saved:
  <raw>/lta/<Layer>/*.shp      LTA DataMall geospatial layers, SVY21 (EPSG:3414)
  <raw>/osm_streets.json       OpenStreetMap named streets (for the street centrelines)
  <raw>/osm_trees.json         OpenStreetMap trees
  <raw>/heritage_trees.geojson NParks heritage trees (data.gov.sg)
  <raw>/codes_arrow.json, codes_lane.json   LTA code -> name, from data.gov.sg

1. For each shortlisted street, every LTA object within BUF metres of its centreline is
   counted (points inside the buffer; lines and areas touching it, each feature once).
2. The street with the most objects among those 300-900 m long is chosen.
3. Everything within BUF metres of it is clipped, reprojected to WGS84 and written to
   <out>/street.json, with each object's chainage (metres along the street) and offset.
All lengths and distances are measured in SVY21 metres.
"""
import sys, os, json, math, glob
import shapefile
from pyproj import Transformer
from shapely.geometry import shape, Point, LineString, MultiLineString, Polygon, MultiPolygon, box
from shapely.ops import linemerge, unary_union
from shapely import STRtree

RAW, OUT = sys.argv[1], sys.argv[2]
fwd = Transformer.from_crs(4326, 3414, always_xy=True).transform
inv = Transformer.from_crs(3414, 4326, always_xy=True).transform
BUF = 25.0
DATA_MONTH = 'Sep 2026'

# Characterful streets: shophouse rows of Chinatown, Tanjong Pagar, Kampong Glam,
# Emerald Hill and Joo Chiat.
CANDIDATES = ['Club Street', 'Ann Siang Road', 'Keong Saik Road', 'Duxton Road', 'Duxton Hill',
              'Joo Chiat Road', 'Joo Chiat Place', 'Koon Seng Road', 'Emerald Hill Road', 'Amoy Street',
              'Telok Ayer Street', 'Bukit Pasoh Road', 'Neil Road', 'Blair Road', 'Everton Road',
              'Craig Road', 'Arab Street', 'Bussorah Street', 'Haji Lane']
SKIP_HW = {'footway', 'path', 'steps', 'cycleway', 'corridor', 'elevator', 'platform', 'construction',
           'proposed', 'bridleway', 'via_ferrata', 'track'}

# key, folder, attribute fields kept
LAYERS = [
    ('lamp', 'LampPost', ['LAMPPOST_N']),
    ('bollard', 'Bollard', []),
    ('mirror', 'ConvexMirror', ['BEARG_NUM']),
    ('hump', 'RoadHump', []),
    ('word', 'WordMarking', ['DESC_TXT', 'BEARG_NUM']),
    ('arrow', 'ArrowMarking', ['TYP_CD', 'BEARG_NUM']),
    ('lane', 'LaneMarking', ['TYP_CD']),
    ('kerb', 'KerbLine', []),
    ('sign', 'TrafficSign', ['TYP_CD', 'TYP_CD_DES', 'BEARG_NUM', 'MOUNT_MTD1']),
    ('light', 'TrafficLight', ['TYP_CD', 'BEARG_NUM']),
    ('crossing', 'RoadCrossing', []),
    ('railing', 'Railing', []),
    ('guardrail', 'GuardRail', []),
    ('cycle', 'CyclingPath', ['PATH_TYPE']),
    ('footpath', 'Footpath', []),
    ('linkway', 'CoveredLinkWay', []),
    ('busstop', 'BusStopLocation', ['BUS_STOP_N', 'LOC_DESC']),
    ('taxi', 'TaxiStand', ['TYPE_CD', 'LOC_DESC']),
    ('ctrlbox', 'ControlBox', []),
    ('loop', 'DetectorLoop', []),
    ('paint', 'StreetPaint', []),
    ('strip', 'SpeedRegulatingStrip', []),
    ('pickup', 'PassengerPickupBay', []),
    ('wall', 'RetainingWall', []),
    ('erp', 'ERPGantry', ['GNTRY_NUM']),
    ('exit', 'TrainStationExit', ['stn_name', 'exit_code']),
    ('station', 'TrainStation', ['STN_NAM']),
    ('vbridge', 'VehicleBridge_FlyOver_Underpass', ['TYP_CD']),
    ('pbridge', 'PedestrainOverheadbridge_UnderPass', ['TYP_CD']),
    ('school', 'SchoolZone', ['SITENAME']),
    ('silver', 'SilverZone', ['SITENAME']),
    ('road', 'RoadSectionLine', ['RD_CD']),
]
# Left out: ParkingStandardsZone (planning zones a kilometre across, not street objects).


def to_svy(lon, lat):
    return fwd(lon, lat)


# ---------- the shortlisted streets, from OpenStreetMap ----------
osm = json.load(open(os.path.join(RAW, 'osm_streets.json'), encoding='utf-8'))
ways = {}
for e in osm['elements']:
    t = e.get('tags', {})
    if e['type'] != 'way' or t.get('name') not in CANDIDATES or t.get('highway') in SKIP_HW:
        continue
    pts = [to_svy(p['lon'], p['lat']) for p in e['geometry']]
    if len(pts) >= 2:
        ways.setdefault(t['name'], []).append((LineString(pts), t.get('highway'), e['id']))

def main_line(lines):
    """The longest continuous run through a street's OSM ways (drops spurs and loops)."""
    merged = linemerge(MultiLineString(lines))
    parts = list(merged.geoms) if merged.geom_type == 'MultiLineString' else [merged]
    key = lambda c: (round(c[0], 2), round(c[1], 2))
    adj = {}
    for i, p in enumerate(parts):
        a, b = key(p.coords[0]), key(p.coords[-1])
        adj.setdefault(a, []).append((i, b)); adj.setdefault(b, []).append((i, a))
    best = (0, [])
    def walk(node, used, path, length):
        nonlocal best
        if length > best[0]:
            best = (length, list(path))
        for i, nxt in adj.get(node, []):
            if i not in used:
                used.add(i); path.append((i, node))
                walk(nxt, used, path, length + parts[i].length)
                path.pop(); used.discard(i)
    for start in adj:
        walk(start, set(), [], 0)
    coords = []
    for i, frm in best[1]:
        c = list(parts[i].coords)
        if key(c[0]) != frm:
            c = c[::-1]
        coords.extend(c if not coords else c[1:])
    return LineString(coords), len(parts)


streets = {}
for name in CANDIDATES:
    if name not in ways:
        print('not found in OSM:', name); continue
    line, nparts = main_line([w[0] for w in ways[name]])
    streets[name] = {'geom': line, 'parts': nparts, 'len': line.length,
                     'all_len': sum(w[0].length for w in ways[name]), 'hw': sorted({w[1] for w in ways[name]})}

region = unary_union([s['geom'] for s in streets.values()]).buffer(BUF + 5).envelope
rminx, rminy, rmaxx, rmaxy = region.bounds


# ---------- LTA layers within the region ----------
def read_layer(folder, fields):
    shp = glob.glob(os.path.join(RAW, 'lta', folder, '*.shp'))
    shp = [s for s in shp if not s.lower().endswith('.shp.xml')]
    r = shapefile.Reader(shp[0], encodingErrors='replace')
    names = [f[0] for f in r.fields[1:]]
    idx = [names.index(f) for f in fields]
    out = []
    for sr in r.iterShapeRecords():
        s = sr.shape
        if s.shapeType == shapefile.NULL or not s.points:
            continue
        if hasattr(s, 'bbox'):
            bx = s.bbox
        else:
            x, y = s.points[0][:2]; bx = (x, y, x, y)
        if bx[2] < rminx or bx[0] > rmaxx or bx[3] < rminy or bx[1] > rmaxy:
            continue
        g = shape(s.__geo_interface__)
        if g.is_empty:
            continue
        if g.geom_type in ('Polygon', 'MultiPolygon') and not g.is_valid:
            g = g.buffer(0)
        rec = sr.record
        out.append((g, [rec[i] for i in idx]))
    return out


data = {}
for key, folder, fields in LAYERS:
    data[key] = read_layer(folder, fields)
    print(f'{key:10s} {len(data[key]):6d} in region')
trees_osm = []
for e in json.load(open(os.path.join(RAW, 'osm_trees.json'), encoding='utf-8'))['elements']:
    if e['type'] == 'node':
        trees_osm.append((Point(to_svy(e['lon'], e['lat'])), [e['id'], e.get('tags', {}).get('species', '') or e.get('tags', {}).get('genus', '') or e.get('tags', {}).get('species:en', '')]))
data['tree'] = trees_osm
heritage = []
hp = os.path.join(RAW, 'heritage_trees.geojson')
if os.path.exists(hp):
    for f in json.load(open(hp, encoding='utf-8'))['features']:
        c = f['geometry']['coordinates']
        heritage.append((Point(to_svy(c[0], c[1])), [f['properties'].get('HT', ''), f['properties'].get('NAME', '')]))
data['heritage'] = heritage

trees_idx = {k: STRtree([g for g, _ in v]) for k, v in data.items() if v}


def within(key, area):
    if key not in trees_idx:
        return []
    hits = trees_idx[key].query(area, predicate='intersects')
    return [data[key][i] for i in sorted(hits)]


# ---------- choose the street ----------
COUNT_KEYS = [k for k, _, _ in LAYERS if k not in ('road', 'school', 'silver', 'station', 'vbridge')]
rows = []
for name, s in streets.items():
    area = s['geom'].buffer(BUF)
    counts = {k: len(within(k, area)) for k in COUNT_KEYS}
    total = sum(counts.values())
    rows.append((name, s['len'], s['parts'], total, counts, s['hw']))
rows.sort(key=lambda r: -r[3])
print(f"\n{'street':20s} {'len m':>7s} parts {'objects':>7s} {'per 100 m':>9s}")
for name, L, parts, total, counts, hw in rows:
    print(f'{name:20s} {L:7.0f} {parts:5d} {total:7d} {100 * total / L:9.1f}  {hw}  ' +
          ' '.join(f'{k}={v}' for k, v in counts.items() if v))
eligible = [r for r in rows if 300 <= r[1] <= 900]
CHOSEN = eligible[0][0]
print('\nchosen:', CHOSEN)


# ---------- the chosen street: axis, buffer, chainage ----------
from collections import Counter
axis = streets[CHOSEN]['geom']
(x0, y0), (x1, y1) = axis.coords[0], axis.coords[-1]
az = math.degrees(math.atan2(x1 - x0, y1 - y0)) % 360          # compass azimuth, start -> end
if az >= 180:                                                    # run it west -> east, so it reads left to right
    axis = LineString(list(axis.coords)[::-1]); az -= 180
L = axis.length
area = axis.buffer(BUF)


def extend(line, d):
    """The axis carried straight on for d metres at both ends, so objects past the ends get a chainage too."""
    c = list(line.coords)
    def out(p, q):   # from q through p, d further
        dx, dy = p[0] - q[0], p[1] - q[1]; n = math.hypot(dx, dy)
        return (p[0] + dx / n * d, p[1] + dy / n * d)
    return LineString([out(c[0], c[1])] + c + [out(c[-1], c[-2])])


ext = extend(axis, BUF + 5)


def chain(pt):
    """Chainage along the street (m, 0 at its west end) and offset (m, + to the left / north side)."""
    s = ext.project(pt)
    a, b = ext.interpolate(max(0, s - .5)), ext.interpolate(min(ext.length, s + .5))
    p = ext.interpolate(s)
    cross = (b.x - a.x) * (pt.y - p.y) - (b.y - a.y) * (pt.x - p.x)
    d = pt.distance(p)
    return round(s - (BUF + 5), 1), round(d if cross >= 0 else -d, 1)


# Affine SVY21 -> WGS84 over the street, for the page's survey grid and cursor readout.
bx0, by0, bx1, by1 = area.buffer(150).bounds
E0, N0 = round((bx0 + bx1) / 2), round((by0 + by1) / 2)
samples = [(bx0 + (bx1 - bx0) * i / 20, by0 + (by1 - by0) * j / 20) for i in range(21) for j in range(21)]
import numpy as np
A = np.array([[1, e - E0, n - N0] for e, n in samples])
LL = np.array([inv(e, n) for e, n in samples])
coef_lon = np.linalg.lstsq(A, LL[:, 0], rcond=None)[0]
coef_lat = np.linalg.lstsq(A, LL[:, 1], rcond=None)[0]
pred = np.c_[A @ coef_lon, A @ coef_lat]
err = max(math.hypot(*(np.array(fwd(*pr)) - np.array(s))) for pr, s in zip(pred, samples))
print(f'affine SVY21->WGS84 max error over the street: {err * 1000:.2f} mm')

LON0, LAT0 = [round(v, 6) for v in inv(*axis.interpolate(L / 2).coords[0])]
Q = 1e7   # coordinates in 1e-7 degree steps (about 1.1 cm)


def enc(coords):
    """[(E, N)...] in SVY21 -> flat, delta-encoded ints of 1e-7 degrees from (LON0, LAT0)."""
    out, px, py = [], 0, 0
    for e, n in coords:
        lon, lat = inv(e, n)
        x, y = round((lon - LON0) * Q), round((lat - LAT0) * Q)
        out += [x - px, y - py]; px, py = x, y
    return out


def parts(g):
    if g.is_empty:
        return []
    if g.geom_type in ('LineString', 'Polygon', 'Point'):
        return [g]
    return [p for h in g.geoms for p in parts(h)]


def num(v):
    try:
        return round(float(v), 1)
    except (TypeError, ValueError):
        return None


EXPORT = [k for k, _, _ in LAYERS] + ['tree', 'heritage']
out_layers, ledger = {}, {}
for key in EXPORT:
    hits = within(key, area)
    if not hits:
        continue
    feats, metres = [], 0.0
    kind = None
    for g, props in hits:
        if g.geom_type == 'Point':
            kind = 'pt'
            ch, off = chain(g)
            geom = enc([g.coords[0]])
        else:
            clip = g.intersection(area)
            ps = [p for p in parts(clip) if p.geom_type != 'Point']
            if not ps:
                continue
            if ps[0].geom_type == 'LineString':
                kind = 'ln'
                metres += sum(p.length for p in ps)
                geom = [enc(p.coords) for p in ps]
                mid = clip.interpolate(.5, normalized=True) if clip.geom_type == 'LineString' else ps[0].interpolate(.5, normalized=True)
            else:
                kind = 'pg'
                geom = [[enc(r.coords) for r in [p.exterior] + list(p.interiors)] for p in ps]
                mid = clip.representative_point()
            ch, off = chain(mid)
        p = []
        for v in props:
            if hasattr(v, 'isoformat'):
                v = v.isoformat()
            if isinstance(v, str):
                v = v.strip()
            p.append(v)
        feats.append([geom, ch, off] + p)
    feats.sort(key=lambda f: f[1])
    out_layers[key] = {'k': kind, 'f': feats}
    if kind == 'ln':
        out_layers[key]['m'] = round(metres, 1)
    ledger[key] = len(feats)

for key, field in [('word', 0), ('arrow', 0), ('lane', 0), ('sign', 1), ('light', 0), ('busstop', 0), ('cycle', 0), ('taxi', 0), ('vbridge', 0)]:
    if key in out_layers:
        print(key, Counter(f[3 + field] for f in out_layers[key]['f']).most_common(30))
for k, v in out_layers.items():
    print(f"{k:10s} {len(v['f']):4d}" + (f"  {v.get('m', 0):8.1f} m" if v['k'] == 'ln' else ''))

codes_arrow = json.load(open(os.path.join(RAW, 'codes_arrow.json')))
codes_lane = json.load(open(os.path.join(RAW, 'codes_lane.json')))
strip = lambda s: s.split(' - ', 1)[1] if ' - ' in s else s
used = lambda key: sorted({f[3] for f in out_layers.get(key, {'f': []})['f']})

# Lane-marking codes: LTA's own description, split into width, colour and dash pattern (metres).
import re
def lane_code(c):
    d = strip(codes_lane.get(c, c))
    o = {'d': d, 'w': None, 'dash': None, 'dbl': 'Double' in d.split(' - ')[1] if ' - ' in d else False}
    m = re.match(r'([\d.]+)m, int ([\d.]+)m, ([\d.]+)m', d)
    if m:
        o['dash'] = [float(m.group(1)), float(m.group(2))]; o['w'] = float(m.group(3))
    m = re.match(r'([\d.]+)m width', d)
    if m:
        o['w'] = float(m.group(1))
    o['col'] = 'yellow' if 'Yellow' in d else 'red' if 'Red' in d else 'white'
    return o


# The streets that meet each end (OSM names within 15 m of the end points).
def ends_at(pt):
    names = set()
    for name_, ws in [(e.get('tags', {}).get('name'), e) for e in osm['elements'] if e['type'] == 'way']:
        if not name_ or name_ == CHOSEN or ws.get('tags', {}).get('highway') in SKIP_HW:
            continue
        g = LineString([to_svy(p['lon'], p['lat']) for p in ws['geometry']])
        if g.distance(pt) < 15:
            names.add(name_)
    return sorted(names)


res = {
    'meta': {
        'street': CHOSEN, 'length_m': round(L, 1), 'buffer_m': BUF, 'azimuth': round(az, 2),
        'area_m2': round(area.area), 'origin': [LON0, LAT0], 'q': Q, 'lta_month': DATA_MONTH,
        'osm_base': osm.get('osm3s', {}).get('timestamp_osm_base', ''),
        'ends': [ends_at(Point(axis.coords[0])), ends_at(Point(axis.coords[-1]))],
        'lta_total': sum(ledger.get(k, 0) for k in COUNT_KEYS),
        'heritage_trees': ledger.get('heritage', 0),
    },
    'aff': {'E0': E0, 'N0': N0, 'lon': [float(v) for v in coef_lon], 'lat': [float(v) for v in coef_lat],
            'err_mm': round(err * 1000, 3)},
    'axis': enc(axis.coords),
    'area': [enc(r.coords) for r in [area.exterior]],
    'L': out_layers,
    'codes': {'arrow': {c: strip(codes_arrow.get(c, c)) for c in used('arrow')},
              'lane': {c: lane_code(c) for c in used('lane')}},
    'cand': [[r[0], round(r[1]), r[3]] for r in rows],
}
print(res['meta'])
print(res['codes']['lane'])
os.makedirs(OUT, exist_ok=True)
fn = os.path.join(OUT, 'street.json')
json.dump(res, open(fn, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False)
print('wrote', fn, os.path.getsize(fn) // 1024, 'kB')
