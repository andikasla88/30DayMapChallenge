"""Day 26 · Water: build data/day26/water.json from the raw inputs.

Requirements (Python 3.10+ venv): pip install numpy scipy rasterio shapely pyproj
Order: fetch.py -> osm_extract.py -> process.py
Usage: python process.py <raw dir> <out json>

What it makes
  relief  Copernicus GLO-90 heights, opened (grey morphology, ~450 m) so towers and tree crowns
          sink back towards the ground, smoothed, then cut into stacked height bands like paper sheets.
  sea     three rings of shallows around the land (decorative: distance from shore, not depth).
  res     Singapore's 17 reservoirs (the PUB list) and Linggiu, from OpenStreetMap, with areas.
  river   the Johor River from Linggiu dam down to PUB's Johor River Waterworks, routed on OSM rivers.
  pipe    the water main OSM maps from the Causeway down to Bukit Timah.
  nodes   every source with its capacity and the document that states it (see FACTS).
  flows   a curve from every source to the demand hub, the width set by capacity in the page.
"""
import heapq, json, math, os, sys, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio import features
from scipy import ndimage
from shapely.geometry import shape, Polygon, MultiPolygon, LineString, Point, box, mapping
from shapely.ops import unary_union, transform
from pyproj import Transformer

RAW = sys.argv[1] if len(sys.argv) > 1 else 'raw'
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), '..', 'water.json')
W, S, E, N = 103.52, 1.13, 104.22, 2.06
Q = 1e4   # coordinate quantum: 1e-4 degrees, about 11 m

to_ea = Transformer.from_crs('EPSG:4326', 'EPSG:6933', always_xy=True).transform   # equal-area, for km²
km2 = lambda g: transform(to_ea, g).area / 1e6


# ---------------- sourced figures (every capacity, share and date on the page) ----------------
SRC = {
    'pub-local': ['PUB, Local catchment water', 'https://www.pub.gov.sg/Public/WaterLoop/OurWaterStory/Local-Catchment-Water'],
    'pub-import': ['PUB, Imported water', 'https://www.pub.gov.sg/Public/WaterLoop/OurWaterStory/ImportedWater'],
    'pub-newater': ['PUB, NEWater', 'https://www.pub.gov.sg/Public/WaterLoop/OurWaterStory/NEWater'],
    'pub-desal': ['PUB, Desalinated water', 'https://www.pub.gov.sg/Public/WaterLoop/OurWaterStory/DesalinatedWater'],
    'pub-sg60': ['PUB, Our Water Story exhibition panels (2025)', 'https://www.pub.gov.sg/-/media/PUB/Public/Key-Initiatives/Our-Water-SG60/Resources/Exhibition-Panels/Exhibition-Panels---Our-Water-Story.pdf'],
    'pub-ar17': ['PUB Annual Report 2016/17', 'https://www.pub.gov.sg/-/media/PUB/Publications/Report/PDF/annualreport2017.pdf'],
    'pub-nvc24': ['PUB media release annex, June 2024', 'https://www.pub.gov.sg/-/media/PUB/Resources/Press-Releases/2024/06/Annex-24-06-2024-PUB-Media-Release---NEWater-Visitor-Centre-to-close-on-31-July.pdf'],
    'pub-kmedp': ['PUB media release, 4 Feb 2021', 'https://www.pub.gov.sg/Resources/News-Room/PressReleases/2021/02/OfficialOpeningofKMEDP'],
    'pub-jidp': ['PUB media release, 17 Apr 2022', 'https://www.pub.gov.sg/Resources/News-Room/PressReleases/2022/04/Tuas-Power-ST-Engineering-Consortium-and-PUB'],
    'nas-2005': ['PM Lee, opening of SingSpring, 13 Sep 2005 (National Archives)', 'https://www.nas.gov.sg/archivesonline/data/pdfdoc/20050913992.htm'],
    'nas-2011': ['PUB and Hyflux media release, 13 Apr 2011 (National Archives)', 'https://www.nas.gov.sg/archivesonline/data/pdfdoc/20110413004.htm'],
    'nas-2007': ['Speech at the opening of Ulu Pandan NEWater Plant, 15 Mar 2007 (National Archives)', 'https://www.nas.gov.sg/archivesonline/data/pdfdoc/20070315978.htm'],
    'nas-2010': ['Sembcorp and PUB media release, 3 May 2010 (National Archives)', 'https://nas.gov.sg/archivesonline/data/pdfdoc/20100510002.htm'],
}
FACTS = {
    'demand_mgd': 440, 'nondomestic_pct': 60, 'domestic_pct': 40, 'demand_src': 'pub-sg60',
    'reservoirs': 17, 'catchment': 'two-thirds', 'catchment_src': 'pub-local',
    'import_mgd': 250, 'import_agreement': 1962, 'import_expires': 2061, 'import_src': 'pub-import',
    'linggiu_agreement': 1990,
    'newater_factories': 4, 'bedok_closed': '31 July 2024',
    'desal_plants': 5,
}
# PUB names the 17 reservoirs across two sources: the 11 built after 1964 (nas-2005 footnote),
# MacRitchie, Lower Peirce and Upper Seletar from before, and Marina (2008), Punggol and Serangoon (2011).
RESERVOIRS = ['Upper Peirce Reservoir', 'Kranji Reservoir', 'Pandan Reservoir', 'Jurong Lake', 'Pulau Tekong Reservoir', 'Murai Reservoir',
              'Poyan Reservoir', 'Tengeh Reservoir', 'Sarimbun Reservoir', 'Lower Seletar Reservoir', 'Bedok Reservoir',
              'MacRitchie Reservoir', 'Lower Peirce Reservoir', 'Upper Seletar Reservoir', 'Marina Reservoir', 'Punggol Reservoir', 'Serangoon Reservoir']

# tap: c = local catchment, i = imported, n = NEWater, d = desalination
PLANTS = [
    # id, tap, name, mgd, opened, note, sources, where (OneMap query or [lon, lat] from OSM)
    ('ss', 'd', 'SingSpring Desalination Plant', 30, 2005, 'Singapore\'s first desalination plant.', ['nas-2005', 'pub-desal'], 'SINGSPRING DESALINATION PLANT'),
    ('ts', 'd', 'Tuas South Desalination Plant', 70, 2013, 'Opened as Tuaspring; owned by PUB since 2019. The largest of the five.', ['nas-2011', 'pub-desal'], 'TUAS SOUTH DESALINATION PLANT'),
    ('td', 'd', 'Tuas Desalination Plant', 30, 2018, 'The first here to clean seawater with dissolved-air flotation before its membranes; solar panels cover more than half its roof.', ['pub-ar17', 'pub-desal'], 'TUAS DESALINATION PLANT'),
    ('me', 'd', 'Keppel Marina East Desalination Plant', 30, 2020, 'Treats seawater in dry weather and Marina Reservoir water in wet weather.', ['pub-kmedp', 'pub-desal'], 'MARINA EAST DESALINATION PLANT'),
    ('ji', 'd', 'Jurong Island Desalination Plant', 30, 2022, 'Shares its seawater intake with a power plant next door.', ['pub-jidp', 'pub-desal'], 'JURONG ISLAND DESALINATION PLANT'),
    ('kr', 'n', 'Kranji NEWater Factory', 22, 2003, 'One of the first two NEWater plants.', ['pub-ar17', 'pub-newater'], 'KRANJI WATER RECLAMATION PLANT'),
    ('up', 'n', 'Ulu Pandan NEWater Plant', 32, 2007, '', ['nas-2007', 'pub-nvc24'], 'ULU PANDAN NEWATER PLANT'),
    ('ch', 'n', 'Changi NEWater factories', 100, 2010, 'Two factories at Changi Water Reclamation Plant: 50 mgd opened in 2010, and 50 mgd opened in 2017.', ['nas-2010', 'pub-ar17', 'pub-sg60'], 'CHANGI NEWATER FACTORY'),
]
HUB = (103.848, 1.346)   # a symbolic point for the whole island's demand (Toa Payoh-Bishan), not a real place


def enc_ring(coords):
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * Q), round(y * Q)
        if out and ix == px and iy == py:
            continue
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def enc_poly(g, min_km2=0.0):
    polys = [g] if isinstance(g, Polygon) else list(getattr(g, 'geoms', []))
    out = []
    for p in polys:
        if p.is_empty or (min_km2 and km2(p) < min_km2):
            continue
        rings = [enc_ring(p.exterior.coords)] + [enc_ring(r.coords) for r in p.interiors if km2(Polygon(r)) >= min_km2]
        if len(rings[0]) >= 8:
            out.append(rings)
    return out


def tidy(g, r=0.0004, tol=0.00045):
    # round the cut a little, the way scissors would, then thin the vertices
    g = g.buffer(r, 4).buffer(-2 * r, 4).buffer(r, 4)
    return g.simplify(tol, preserve_topology=True)


# ---------------- relief ----------------
tiles = [rasterio.open(os.path.join(RAW, f'Copernicus_DSM_COG_30_{t}_DEM.tif')) for t in ('N01_00_E103_00', 'N01_00_E104_00', 'N02_00_E103_00')]
dem, tr = merge(tiles, bounds=(W, S, E, N))
dem = dem[0].astype('float32')
land = dem != 0
# Grey opening (a ~5-cell min then max) removes narrow tall things: towers, chimneys, tree crowns.
opened = ndimage.grey_opening(np.where(land, dem, 0), size=(5, 5))
h = ndimage.gaussian_filter(opened, 1.4)
h[~land] = 0

osm = json.load(open(os.path.join(RAW, 'osm_water.json')))
areas = {a['id']: a for a in osm['areas']}
by_name = {}
for a in osm['areas']:
    by_name.setdefault(a['tags'].get('name', ''), []).append(a)


def pick_area(name, pred=None):
    c = [a for a in by_name.get(name, []) if (pred or (lambda a: a['tags'].get('natural') == 'water' or a['tags'].get('landuse') == 'reservoir'))(a)]
    if not c:
        raise SystemExit('missing reservoir in OSM: ' + name)
    return max((shape(a['geom']) for a in c), key=lambda g: g.area)


res = []
for nm in RESERVOIRS:
    g = pick_area(nm)
    res.append((nm, g))
ling = pick_area('Tasik Linggiu')
res_union = unary_union([g for _, g in res] + [ling])

clip = box(W, S, E, N)
BANDS = [0, 15, 40, 80, 150, 260, 400]
relief = []
for t in BANDS:
    mask = (h > t) if t else land
    mask = ndimage.binary_opening(mask, iterations=1) if t else mask
    geoms = [shape(gm) for gm, v in features.shapes(mask.astype('uint8'), mask=mask, transform=tr) if v == 1]
    g = unary_union(geoms).intersection(clip)
    g = tidy(g).difference(res_union.buffer(0.0002))
    g = g.buffer(0)
    relief.append({'t': t, 'p': enc_poly(g, 0.25 if t == 0 else 0.15), 'km2': round(km2(g), 1)})
    print('band', t, len(relief[-1]['p']), 'polys')
land_g = unary_union([shape(gm) for gm, v in features.shapes(land.astype('uint8'), mask=land, transform=tr) if v == 1]).intersection(clip)
land_g = land_g.buffer(0.0004).buffer(-0.0004)
sea = []
for d in (0.006, 0.016, 0.032):   # about 0.7, 1.8 and 3.5 km from shore
    g = land_g.buffer(d, 6).intersection(clip).simplify(0.0012)
    sea.append(enc_poly(g, 0.5))

# ---------------- reservoirs ----------------
res_out = []
for nm, g in res:
    gs = g.simplify(0.00012, preserve_topology=True)
    res_out.append({'n': nm, 'a': round(km2(g), 2), 'p': enc_poly(gs), 'c': [round(g.representative_point().x, 4), round(g.representative_point().y, 4)]})
res_total = round(sum(r['a'] for r in res_out), 1)
ling_km2 = round(km2(ling), 1)
ling_out = {'n': 'Linggiu Reservoir', 'a': ling_km2, 'p': enc_poly(ling.simplify(0.0003, preserve_topology=True)), 'c': [103.70, 1.975]}
print('reservoirs', len(res_out), res_total, 'km2; Linggiu', ling_km2)

# ---------------- Johor River: Linggiu dam -> PUB Johor River Waterworks, on the OSM river network ----------------
works = shape(areas['w703108803']['geom'])
WORKS = (round(works.centroid.x, 4), round(works.centroid.y, 4))
dam = shape(areas['w320565393']['geom']).centroid
graph = {}
key = lambda c: (round(c[0], 6), round(c[1], 6))
for l in osm['lines']:
    if l['tags'].get('waterway') != 'river' or min(c[1] for c in l['coords']) < 1.45:
        continue
    cs = [key(c) for c in l['coords']]
    for a, b in zip(cs, cs[1:]):
        dd = math.dist(a, b)
        graph.setdefault(a, []).append((b, dd)); graph.setdefault(b, []).append((a, dd))
nodes = list(graph)
near = lambda p: min(nodes, key=lambda n: (n[0] - p[0]) ** 2 + (n[1] - p[1]) ** 2)
a0, b0 = near((dam.x, dam.y)), near(WORKS)
dist, prev, pq = {a0: 0}, {}, [(0, a0)]
while pq:
    d, u = heapq.heappop(pq)
    if u == b0:
        break
    if d > dist.get(u, 1e9):
        continue
    for v, w in graph[u]:
        if d + w < dist.get(v, 1e9):
            dist[v] = d + w; prev[v] = u; heapq.heappush(pq, (d + w, v))
path = [b0]
while path[-1] != a0:
    path.append(prev[path[-1]])
river = LineString(path[::-1]).simplify(0.0003)
river_km = round(transform(Transformer.from_crs('EPSG:4326', 'EPSG:3375', always_xy=True).transform, LineString(path)).length / 1000, 0)
print('river path', len(river.coords), 'pts', river_km, 'km', 'gap to works', round(math.dist(b0, WORKS) * 111, 2), 'km')

# ---------------- the Singapore water main from the Causeway (OSM) ----------------
pipe_l = next(l for l in osm['lines'] if l['id'] == 'w407019780')
pipe = LineString(pipe_l['coords']).simplify(0.0001)
CAUSEWAY = (103.7690, 1.4520)   # mid-Causeway, from OSM way "Johor–Singapore Causeway"

# ---------------- nodes ----------------
om = json.load(open(os.path.join(RAW, 'onemap_plants.json')))
out_nodes = []
for pid, tap, name, mgd, yr, note, srcs, q in PLANTS:
    r = om[q][0]
    out_nodes.append({'id': pid, 'tap': tap, 'n': name, 'mgd': mgd, 'y': yr, 'note': note, 's': srcs, 'at': [round(float(r['LONGITUDE']), 5), round(float(r['LATITUDE']), 5)]})
out_nodes.append({'id': 'jw', 'tap': 'i', 'n': 'Johor River Waterworks', 'mgd': 250, 'y': 1962,
                  'note': 'Owned and run by PUB in Johor. Under the 1962 Water Agreement, Singapore can draw up to 250 mgd from the Johor River until 2061.',
                  's': ['pub-import', 'pub-sg60'], 'at': list(WORKS)})
out_nodes.append({'id': 'lg', 'tap': 'i', 'n': 'Linggiu Reservoir', 'mgd': None, 'y': 1990,
                  'note': f'Built by PUB under a 1990 agreement with Johor. It releases water into the Johor River so the waterworks downstream can draw reliably. {ling_km2} km² of water in OpenStreetMap.',
                  's': ['pub-import'], 'at': [round(dam.x, 4), round(dam.y, 4)]})


# ---------------- flows: a smooth curve from each source to the hub ----------------
def bezier(p0, p1, p2, p3, n=48):
    pts = []
    for i in range(n + 1):
        t = i / n; u = 1 - t
        pts.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def curve(a, b, bend=0.18):
    dx, dy = b[0] - a[0], b[1] - a[1]
    nx, ny = -dy * bend, dx * bend
    return bezier(a, (a[0] + dx * .3 + nx, a[1] + dy * .3 + ny), (a[0] + dx * .72 + nx * .6, a[1] + dy * .72 + ny * .6), b)


flows = []
for n_ in out_nodes:
    if n_['tap'] in ('d', 'n'):
        flows.append({'tap': n_['tap'], 'id': n_['id'], 'mgd': n_['mgd'], 'line': enc_ring(curve(tuple(n_['at']), HUB, .16 if n_['at'][0] < HUB[0] else -.16))})
for r in res_out:
    c = tuple(r['c'])
    if math.dist(c, HUB) < 0.012:
        continue
    flows.append({'tap': 'c', 'id': r['n'], 'mgd': None, 'line': enc_ring(curve(c, HUB, .12 if c[0] < HUB[0] else -.12))})
# imported: waterworks -> Causeway (schematic: OSM has no route for the Johor pipelines) -> OSM main -> hub
p_start, p_end = pipe.coords[0], pipe.coords[-1]
johor_leg = [WORKS] + bezier(WORKS, (103.84, 1.62), (103.775, 1.53), CAUSEWAY, 30)[1:]
tail = curve(p_end, HUB, -.1)
flows.append({'tap': 'i', 'id': 'jw', 'mgd': 250, 'line': enc_ring(johor_leg + [p_start] + list(pipe.coords)[1:] + tail[1:]),
              'split': [len(johor_leg), len(johor_leg) + len(pipe.coords)]})
river_flow = {'tap': 'i', 'id': 'lg', 'line': enc_ring(list(river.coords))}

out = {
    'q': Q, 'bands': relief, 'sea': sea, 'res': res_out, 'ling': ling_out, 'river': river_flow,
    'pipe': enc_ring(list(pipe.coords)), 'nodes': out_nodes, 'flows': flows, 'hub': HUB,
    'facts': {**FACTS, 'res_km2': res_total, 'ling_km2': ling_km2, 'river_km': river_km,
              'newater_mgd': sum(n['mgd'] for n in out_nodes if n['tap'] == 'n'),
              'desal_mgd': sum(n['mgd'] for n in out_nodes if n['tap'] == 'd')},
    'src': SRC,
}
json.dump(out, open(OUT, 'w'), separators=(',', ':'))
print('wrote', OUT, round(os.path.getsize(OUT) / 1024), 'KB', out['facts'])
