"""Day 18 (NULL): turn the raw downloads into the page's data.

Requires python 3.10+ with: pyproj shapely numpy pillow rasterio pyshp scipy
usage: python -I process.py <raw-dir> <out-dir>      (after fetch.py, scan.py and s2.py)

Writes <out-dir>/null.js (window.DAY18, the Sentinel-2 crop inside as a WebP data URL). Every number the page shows is computed here.
Distances are geodesic on the WGS 84 ellipsoid: each "nearest" search runs in an azimuthal equidistant
projection centred on the point in question, where distance from the centre is exactly the geodesic distance.
"""
import base64
import io
import json
import math
import os
import re
import sys
import zipfile

import numpy as np
import shapefile   # pyshp
from pyproj import CRS, Geod, Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box, shape
import shapely
from shapely.ops import nearest_points, unary_union


def shp_transform(fn, g):
    return shapely.transform(g, lambda x, y: fn(x, y), interleaved=False)

sys.stdout.reconfigure(encoding="utf-8")
RAW, OUT = sys.argv[1], sys.argv[2]
G = Geod(ellps='WGS84')
TO_WGS = Transformer.from_crs('EPSG:3414', 'EPSG:4326', always_xy=True)
TO_SVY = Transformer.from_crs('EPSG:4326', 'EPSG:3414', always_xy=True)
load = lambda *p: json.load(open(os.path.join(RAW, *p), encoding='utf-8'))
r6 = lambda v: round(float(v), 6)


def dms(v, pos, neg, dp=3):
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = (v - d - m / 60) * 3600
    if round(s, dp) >= 60:
        m, s = m + 1, 0
    return f"{d}°{m:02d}′{s:0{(3 + dp) if dp else 2}.{dp}f}″ {h}"


def aeqd(lon, lat):
    t = Transformer.from_crs('EPSG:4326', f'+proj=aeqd +lat_0={lat} +lon_0={lon} +ellps=WGS84 +units=m', always_xy=True)
    back = Transformer.from_crs(f'+proj=aeqd +lat_0={lat} +lon_0={lon} +ellps=WGS84 +units=m', 'EPSG:4326', always_xy=True)
    return (lambda g: shp_transform(t.transform, g)), back


def nearest(lon, lat, geoms):
    """Nearest point of any geometry (lon/lat) to (lon, lat): (metres, [lon, lat], index)."""
    fwd, back = aeqd(lon, lat)
    best = None
    for i, g in enumerate(geoms):
        gp = fwd(g)
        d = gp.distance(Point(0, 0))
        if best is None or d < best[0]:
            q = nearest_points(gp, Point(0, 0))[0]
            best = (d, list(back.transform(q.x, q.y)), i)
    # the projected distance from the centre is the geodesic distance; check it against pyproj's inverse
    chk = G.inv(lon, lat, *best[1])[2]
    assert abs(chk - best[0]) < 0.01, (chk, best[0])
    return best


# ---------------------------------------------------------------- 1. SVY21's definition, checked against EPSG
conv = load('epsg', 'conversion_19864.json')
P = {p['Name']: p['ParameterValue'] for p in conv['ParameterValues']}
units = {p['Name']: p['Unit']['Name'] for p in conv['ParameterValues']}


def sexagesimal(v):   # EPSG unit 9110, "sexagesimal DMS": D.MMSSsss
    d, frac = f'{v:.7f}'.split('.')
    return int(d) + int(frac[:2]) / 60 + float(frac[2:4] + '.' + frac[4:]) / 3600


assert units['Latitude of natural origin'] == 'sexagesimal DMS'
LAT0, LON0 = sexagesimal(P['Latitude of natural origin']), sexagesimal(P['Longitude of natural origin'])
K0, FE, FN = P['Scale factor at natural origin'], P['False easting'], P['False northing']
assert (abs(LAT0 - (1 + 22 / 60)) < 1e-12 and abs(LON0 - (103 + 50 / 60)) < 1e-12 and K0 == 1
        and FE == 28001.642 and FN == 38744.572), P
assert conv['InformationSource'].startswith('Singapore Land Authority')
crs = CRS.from_epsg(3414)
pp = {p.name: p.value for p in crs.coordinate_operation.params}
assert abs(pp['Latitude of natural origin'] - LAT0) < 1e-9 and abs(pp['Longitude of natural origin'] - LON0) < 1e-9
assert pp['False easting'] == FE and pp['False northing'] == FN and pp['Scale factor at natural origin'] == K0
assert crs.ellipsoid.name == 'WGS 84'
tf = load('epsg', 'transformation_8886.json')
assert tf['Name'] == 'SVY21 to WGS 84 (1)' and tf['Accuracy'] == 1.0
datum = load('epsg', 'datum_6757.json')
m = re.search(r"Latitude: (\d+)°(\d+)'([\d.]+)\"N, longitude: (\d+)°(\d+)'([\d.]+)\"E", datum['Origin'])
BASE7 = (int(m[4]) + int(m[5]) / 60 + float(m[6]) / 3600, int(m[1]) + int(m[2]) / 60 + float(m[3]) / 3600)
ext = load('epsg', 'extent_1210.json')
AOU = {k: ext[f'BoundingBox{k}'] for k in ('SouthBoundLatitude', 'WestBoundLongitude', 'EastBoundLongitude', 'NorthBoundLatitude')}

# ---------------------------------------------------------------- 2. SVY21 (0, 0)
ZLON, ZLAT = TO_WGS.transform(0, 0)
ox, oy = TO_SVY.transform(LON0, LAT0)
assert abs(ox - FE) < 1e-5 and abs(oy - FN) < 1e-5
az_oz, _, d_oz = G.inv(LON0, LAT0, ZLON, ZLAT)
grid_oz = math.hypot(FE, FN)
_, _, d_b7 = G.inv(LON0, LAT0, *BASE7)
south_by = G.inv(ZLON, ZLAT, ZLON, AOU['SouthBoundLatitude'])[2]
west_by = G.inv(ZLON, ZLAT, AOU['WestBoundLongitude'], ZLAT)[2]
assert ZLAT < AOU['SouthBoundLatitude'] and ZLON < AOU['WestBoundLongitude']
print(f'SVY21 (0,0) = {ZLAT:.10f} N, {ZLON:.10f} E   {dms(ZLAT, "N", "S")} {dms(ZLON, "E", "W")}')
print(f'origin -> zero: geodesic {d_oz:.3f} m, grid {grid_oz:.3f} m, azimuth {az_oz:.2f}; Base 7 {d_b7:.1f} m from origin')

# ---------------------------------------------------------------- 3. what is at SVY21 (0, 0)
coast = [e for e in load('osm', 'coast_sg.json')['elements'] if e['type'] == 'way' and len(e.get('geometry', [])) > 1]
lines = [LineString([(p['lon'], p['lat']) for p in w['geometry']]) for w in coast]
for w, ln in zip(coast, lines):   # the point must be water: inside no closed island ring
    if ln.is_ring:
        assert not Polygon(ln).contains(Point(ZLON, ZLAT)), w['id']
d_land, p_land, i_land = nearest(ZLON, ZLAT, lines)
land_way = coast[i_land]
land_name = land_way.get('tags', {}).get('name', '')
land_country = [f['properties'] for f in load('mr', 'nearest_land_country.json')['features']]
assert len(land_country) == 1
land_country = land_country[0]['union']
isin_z = load('osm', 'isin_zero.json')['elements']
lvl_z = {int(a['tags']['admin_level']): a['tags'].get('name:en') or a['tags'].get('name') for a in isin_z if a['tags'].get('admin_level', '').isdigit()}
print(f'nearest land: {land_name} (way {land_way["id"]}) {d_land:.1f} m at {p_land}, {land_country}; zero lies in OSM areas {lvl_z}')

# seamarks near the point (OpenStreetMap / OpenSeaMap)
near = load('osm', 'near.json')['elements']
buoys = [e for e in near if e['type'] == 'node' and e.get('tags', {}).get('seamark:type', '').startswith('buoy')]
bd = sorted((G.inv(ZLON, ZLAT, b['lon'], b['lat'])[2], b) for b in buoys)
d_buoy, buoy = bd[0]
bt = buoy['tags']
print(f'nearest buoy: {d_buoy:.1f} m, node {buoy["id"]}, {bt}')
seaways = load('osm', 'seaways.json')['elements']
anch = [w for w in seaways if w.get('tags', {}).get('seamark:type') == 'anchorage']
anch_geoms = [Polygon([(p['lon'], p['lat']) for p in w['geometry']]) for w in anch]
d_anch, p_anch, i_anch = nearest(ZLON, ZLAT, [g.exterior for g in anch_geoms])
assert not anch_geoms[i_anch].contains(Point(ZLON, ZLAT))
print(f'nearest anchorage edge {d_anch:.1f} m (way {anch[i_anch]["id"]}, {anch[i_anch]["tags"]})')

# maritime zones (Marine Regions)
mr = lambda p, l: [f['properties'] for f in load('mr', f'{p}_{l}.json')['features']]
z_arch, z_eez, z_ts, z_iw = mr('svy21', 'eez_archipelagic_waters'), mr('svy21', 'eez'), mr('svy21', 'eez_12nm'), mr('svy21', 'eez_internal_waters')
z_iho = mr('svy21', 'iho')
assert len(z_arch) == 1 and not z_ts and not z_iw and len(z_iho) == 1
print('zones at SVY21 zero:', z_arch[0]['geoname'], '|', [z['geoname'] for z in z_eez], '| IHO', z_iho[0]['name'])
strait = shape(load('mr', 'iho_singapore_strait.json')['features'][0]['geometry'])
d_strait, p_strait, _ = nearest(ZLON, ZLAT, [strait])
print(f'IHO Singapore Strait limit: {d_strait:.1f} m away')
bounds_fc = load('mr', 'boundaries_sg.json')['features']
BOUNDS = []
for f in bounds_fc:
    pr = f['properties']
    terr = {pr.get('territory1'), pr.get('territory2'), pr.get('sovereign1'), pr.get('sovereign2')}
    if 'Singapore' not in terr:
        continue
    g = shape(f['geometry'])
    for part in (g.geoms if g.geom_type == 'MultiLineString' else [g]):
        part = part.simplify(0.0002)
        BOUNDS.append({'between': ' / '.join(sorted(t for t in {pr.get('territory1'), pr.get('territory2')} if t)),
                       'type': pr.get('line_type', ''), 'c': [[r6(x), r6(y)] for x, y in part.coords]})
print('boundary lines with Singapore:', len(BOUNDS), sorted({(b['between'], b['type']) for b in BOUNDS}))

# ---------------------------------------------------------------- 4. Singapore's land (SLA National Map Polygon)
LAND_ID = 'd_29f066d67df3eae91df8a42f443863c8'
nmp = load('dgs', f'{LAND_ID}.geojson')['features']
kinds = {}
for f in nmp:
    k = (f['properties'].get('FOLDERPATH') or '')
    kinds[k] = kinds.get(k, 0) + 1
print('National Map Polygon folders:', kinds)
# Coastal outlines, minus the pieces of Johor the layer also draws ("JOHOR (MALAYSIA)", "LINKWAY (JOHOR)").
coastal = [f for f in nmp if f.get('geometry') and re.search(r'coast', f['properties'].get('FOLDERPATH') or '', re.I)
           and not re.search(r'MALAYSIA|JOHOR', f['properties'].get('NAME') or '')]
print('Singapore coastal outlines:', len(coastal), sorted({f['properties'].get('NAME') or '' for f in coastal})[:12], '...')
assert coastal, 'no coastal outline polygons'
sg_polys, sg_names = [], []
for f in coastal:
    g = shapely.force_2d(shape(f['geometry']))
    parts = list(g.geoms) if g.geom_type == 'MultiPolygon' else [g]
    sg_polys += parts
    sg_names += [f['properties'].get('NAME')] * len(parts)
sg_land = unary_union([p.buffer(0) for p in sg_polys])
d_sg, p_sg, i_sg = nearest(ZLON, ZLAT, [p.exterior for p in sg_polys])
sg_svy = shp_transform(TO_SVY.transform, sg_land)
minx, miny = sg_svy.bounds[0], sg_svy.bounds[1]


def extreme(axis):
    """The land vertex with the lowest easting (axis 0) or northing (axis 1), and the name of its outline."""
    best = None
    for f in coastal:
        g = shp_transform(TO_SVY.transform, shapely.force_2d(shape(f['geometry'])))
        for poly in (g.geoms if g.geom_type == 'MultiPolygon' else [g]):
            for x, y in poly.exterior.coords:
                v = (x, y)[axis]
                if best is None or v < best[0]:
                    best = (v, x, y, f['properties'].get('NAME'))
    return best


wx = extreme(0)
sy = extreme(1)
print(f'Singapore land: lowest E {wx[0]:.1f} m at {TO_WGS.transform(wx[1], wx[2])} ({wx[3]}), lowest N {sy[0]:.1f} m at {TO_WGS.transform(sy[1], sy[2])} ({sy[3]})')
print(f'nearest Singapore land to zero: {d_sg:.1f} m at {p_sg} ({sg_names[i_sg]})')

# ---------------------------------------------------------------- 5. WGS 84 (0, 0)
WE, WN = TO_SVY.transform(0, 0)
assert math.isfinite(WE) and math.isfinite(WN)
INF = (LON0 - 90, 0.0)
assert not math.isfinite(TO_SVY.transform(*INF)[0])
z0 = {k: mr('wgs84', k) for k in ('eez', 'eez_12nm', 'eez_archipelagic_waters', 'high_seas', 'iho')}
assert not z0['eez'] and not z0['eez_12nm'] and len(z0['high_seas']) == 1 and len(z0['iho']) == 1
print('zones at 0,0: high seas', z0['high_seas'][0]['name'], '| IHO', z0['iho'][0]['name'])
gulf = shape(load('mr', 'iho_gulf_of_guinea.json')['features'][0]['geometry'])
d_gulf, p_gulf, _ = nearest(0, 0, [gulf])
print(f'IHO Gulf of Guinea limit: {d_gulf:.1f} m from 0,0 at {p_gulf}')
# Natural Earth to find the nearest coast, then OpenStreetMap's coastline there for the exact distance
zf = zipfile.ZipFile(os.path.join(RAW, 'ne_10m_land.zip'))
shp = {n.rsplit('.', 1)[1]: io.BytesIO(zf.read(n)) for n in zf.namelist() if n.startswith('ne_10m_land.')}
rdr = shapefile.Reader(shp=shp['shp'], shx=shp['shx'], dbf=shp['dbf'])
win = box(-25, -25, 25, 25)
ne, ne_null = [], None
for rec, shp_ in zip(rdr.records(), rdr.shapes()):
    g = shape(shp_.__geo_interface__)
    if rec['featurecla'] == 'Null island':   # Natural Earth's own joke: a square of "land" at 0, 0. Not land.
        ne_null = {'area_m2': round(abs(G.geometry_area_perimeter(g)[0])), 'scalerank': rec['scalerank'],
                   'c': [[r6(x), r6(y)] for x, y in g.exterior.coords], 'version': zf.read('ne_10m_land.VERSION.txt').decode().strip()}
        continue
    g = g.intersection(win)
    if not g.is_empty:
        ne.append(g)
assert ne_null, 'expected Natural Earth to carry its Null Island polygon'
print('Natural Earth "Null island":', {k: v for k, v in ne_null.items() if k != 'c'})
d_ne, p_ne, _ = nearest(0, 0, [g.boundary for g in ne])
print(f'Natural Earth nearest land to 0,0: {d_ne:.0f} m at {p_ne}')
osm_w = {}
for name in ('coast_gh', 'coast_st'):
    ways = [e for e in load('osm', f'{name}.json')['elements'] if e['type'] == 'way' and len(e.get('geometry', [])) > 1]
    lns = [LineString([(p['lon'], p['lat']) for p in w['geometry']]) for w in ways]
    osm_w[name] = nearest(0, 0, lns)
    print(f'  OSM {name}: {osm_w[name][0]:.1f} m at {osm_w[name][1]}')
best_w = min(osm_w, key=lambda k: osm_w[k][0])
d_w, p_w, _ = osm_w[best_w]
assert best_w == 'coast_gh' and abs(d_w - d_ne) < 3000, (best_w, d_w, d_ne)
rev = load('osm', 'nearest_gh_reverse.json')
assert abs(float(rev['lat']) - p_w[1]) < 0.05 and abs(float(rev['lon']) - p_w[0]) < 0.05, (rev['lat'], rev['lon'], p_w)
a_ = rev['address']
w_place = next(a_[k] for k in ('town', 'village', 'hamlet', 'suburb', 'city', 'county') if a_.get(k))
w_country = a_['country']
print(f'nearest land to 0,0 is near {w_place}, {a_.get("state")}, {w_country}')
ndbc = open(os.path.join(RAW, 'ndbc_13010.html'), encoding='utf-8', errors='replace').read()
ndbc_t = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', ndbc))
assert 'Station 13010 - Soul' in ndbc_t and '0.000 N 0.000 E' in ndbc_t and 'PIRATA' in ndbc_t
_, _, d_sg_w = G.inv(LON0, LAT0, 0, 0)
_, _, d_z_w = G.inv(ZLON, ZLAT, 0, 0)
print(f'origin -> 0,0 {d_sg_w / 1000:.1f} km; SVY21 zero -> 0,0 {d_z_w / 1000:.1f} km; SVY21 of 0,0: E {WE:.3f} N {WN:.3f}')

# ---------------------------------------------------------------- 6. geometry for the map
def svy_line(pts, step=2500.0):
    """A line through SVY21 points, densified every `step` metres, in lon/lat."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
        n = max(1, int(math.ceil(math.hypot(x1 - x0, y1 - y0) / step)))
        for k in range(n):
            out.append(TO_WGS.transform(x0 + (x1 - x0) * k / n, y0 + (y1 - y0) * k / n))
    out.append(TO_WGS.transform(*pts[-1]))
    return [[r6(x), r6(y)] for x, y in out]


GX, GY = (-20, 60), (-20, 55)   # km: the grid drawn on the map
grid = {'x': [], 'y': []}
worst = 0.0
for km in range(GX[0], GX[1] + 1):
    c = svy_line([(km * 1000, GY[0] * 1000), (km * 1000, GY[1] * 1000)])
    grid['x'].append([km, c])
for km in range(GY[0], GY[1] + 1):
    c = svy_line([(GX[0] * 1000, km * 1000), (GX[1] * 1000, km * 1000)])
    grid['y'].append([km, c])
for km, c in grid['x'][::7] + grid['y'][::7]:   # how far straight segments stray from the true grid line
    for a, b in zip(c[:-1], c[1:]):
        mx, my = TO_SVY.transform((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        ex, ey = TO_SVY.transform(*a)
        fx, fy = TO_SVY.transform(*b)
        worst = max(worst, abs((mx - ex) * (fy - ey) - (my - ey) * (fx - ex)) / math.hypot(fx - ex, fy - ey))
print(f'grid: {len(grid["x"])} + {len(grid["y"])} lines; straight segments stray at most {worst * 1000:.2f} mm')
assert worst < 0.05
neg = [svy_line([(GX[0] * 1e3, GY[0] * 1e3), (GX[1] * 1e3, GY[0] * 1e3), (GX[1] * 1e3, 0), (0, 0), (0, GY[1] * 1e3), (GX[0] * 1e3, GY[1] * 1e3), (GX[0] * 1e3, GY[0] * 1e3)])]
false_box = {'top': svy_line([(0, FN), (FE, FN)], 1000), 'right': svy_line([(FE, FN), (FE, 0)], 1000),
             'bottom': svy_line([(0, 0), (FE, 0)], 1000), 'left': svy_line([(0, 0), (0, FN)], 1000)}
path = [[LON0, LAT0]] + G.npts(LON0, LAT0, ZLON, ZLAT, 20) + [[ZLON, ZLAT]] + G.npts(ZLON, ZLAT, 0, 0, 360) + [[0, 0]]
path = [[r6(x), r6(y)] for x, y in path]
gulf_ring = gulf.exterior if gulf.geom_type == 'Polygon' else max(gulf.geoms, key=lambda g: g.area).exterior
# the Gulf's seaward limit is the one long straight edge of the polygon (Cape Palmas to Cape Lopez); draw just that
# (stored densified, so: runs of ring vertices on one straight lon/lat line, longer than 150 km). The ring is
# rotated to start at its northernmost vertex, on the coast, so no run is split by the ring's seam.
_gc = list(gulf_ring.coords)[:-1]
_k = max(range(len(_gc)), key=lambda k: _gc[k][1])
_gc = _gc[_k:] + _gc[:_k] + [_gc[_k]]


def _straight(i0, j):
    a0, b0 = _gc[i0], _gc[j]
    d = math.hypot(b0[0] - a0[0], b0[1] - a0[1])
    return all(abs((b0[0] - a0[0]) * (_gc[k][1] - a0[1]) - (b0[1] - a0[1]) * (_gc[k][0] - a0[0])) / d < 1e-4 for k in range(i0 + 1, j))


gulf_line, i0 = [], 0
while i0 < len(_gc) - 1:
    j = i0 + 1
    while j + 1 < len(_gc) and _straight(i0, j + 1):
        j += 1
    if G.inv(*_gc[i0], *_gc[j])[2] > 150_000:
        gulf_line.append([[r6(v) for v in _gc[i0]], [r6(v) for v in _gc[j]]])
    i0 = j
assert gulf_line and max(G.inv(*a[0], *a[1])[2] for a in gulf_line) > 1_000_000, gulf_line
print('IHO Gulf of Guinea seaward limit:', gulf_line, [round(G.inv(*a[0], *a[1])[2] / 1000) for a in gulf_line], 'km')

# ---------------------------------------------------------------- 7. Sentinel-2 at SVY21 (0, 0)
s2 = None
if os.path.exists(os.path.join(RAW, 's2', 'scene.json')):
    import rasterio
    from PIL import Image
    from scipy import ndimage
    scene = json.load(open(os.path.join(RAW, 's2', 'scene.json')))
    with rasterio.open(os.path.join(RAW, 's2', 'visual.tif')) as src:
        rgb = src.read()
        tr = src.transform
        W, H = src.width, src.height
    with rasterio.open(os.path.join(RAW, 's2', 'nir.tif')) as src:
        nir = src.read(1).astype('float64')   # digital numbers; open water here reads about 460
    cols, rows = np.meshgrid(np.arange(W) + .5, np.arange(H) + .5)
    lon = tr.c + cols * tr.a
    lat = tr.f + rows * tr.e
    kx = 111320 * math.cos(math.radians(ZLAT))
    dist = np.hypot((lon - ZLON) * kx, (lat - ZLAT) * 110574)
    R_SHIPS = 5000.0
    # Vessels: connected patches of at least 6 pixels (about 740 m2) that are over twice as bright as the water in
    # near-infrared. Thresholds from 700 to 1,400 find the same vessels here. Ships the scene classifier took for
    # cloud are kept on purpose; real cloud is all but absent near the point (that is how the scene was chosen).
    bright = (nir > 1000) & (dist <= R_SHIPS)
    lab, n = ndimage.label(bright, structure=np.ones((3, 3)))
    sizes = ndimage.sum(bright, lab, range(1, n + 1))
    keep = [i + 1 for i, sz in enumerate(sizes) if sz >= 6]
    cents = ndimage.center_of_mass(bright, lab, keep)
    ships = []
    for (rr, cc), i in zip(cents, keep):
        ships.append([r6(tr.c + (cc + .5) * tr.a), r6(tr.f + (rr + .5) * tr.e), int(sizes[i - 1])])
    print(f'Sentinel-2 {scene["id"]} {scene["datetime"]}: {len(ships)} vessels within {R_SHIPS / 1000:.0f} km', ships)
    # the picture: true colour, one linear stretch for all three bands (so hues stay true), faded out at the edge
    img = np.transpose(rgb[:3], (1, 2, 0)).astype('float64')
    lo, hi = np.percentile(img[img > 0], [0.5, 99.9])
    img = np.clip((img - lo) / (hi - lo), 0, 1) ** 0.9
    grey = img.mean(axis=2, keepdims=True)
    img = (grey + (img - grey) * 0.6) * 255           # and a little less saturated, to sit on the pale chart
    edge = np.clip((6400 - dist) / 900, 0, 1)
    alpha = (edge * 255).astype('uint8')
    im = Image.fromarray(np.dstack([img.astype('uint8'), alpha]), 'RGBA')
    buf = io.BytesIO()   # the crop rides inside null.js as a data URL (s2.img), so the page also works opened from disk
    im.save(buf, 'WEBP', quality=74, method=6)
    s2 = {'id': scene['id'], 'date': scene['datetime'][:10], 'time': scene['datetime'][11:16], 'platform': scene.get('platform'),
          'bounds': [r6(v) for v in scene['bounds']], 'ships': ships, 'radius_km': R_SHIPS / 1000, 'stac': scene['stac'],
          'img': 'data:image/webp;base64,' + base64.b64encode(buf.getvalue()).decode()}

# ---------------------------------------------------------------- 8. the null-record scan
scan = load('scan.json')
assert scan['svy21_zero_wgs84'] == [ZLON, ZLAT]
rows, strays = [], []
for d in scan['datasets']:
    b = d['buckets']
    rows.append([d['name'].replace(' (GEOJSON)', ''), d['agency'], d['records'], b['no_geometry'], b['wgs84_zero'], b['svy21_zero'], b['far_away'], d['id'], d['updated']])
    for o in d['odd']:
        assert o['bucket'] == 'svy21_zero', o          # anything else would need its own story on the page
        assert abs(o['pt'][0] - ZLON) < 1e-9 and abs(o['pt'][1] - ZLAT) < 1e-9, o   # exactly on the spot, not merely near
        strays.append({'dataset': d['name'].replace(' (GEOJSON)', ''), 'agency': d['agency'], 'id': d['id'], 'name': o['name'], 'why': o['why'],
                       'postal': o.get('postal'), 'pt': o['pt']})
tot = lambda k: sum(d['buckets'][k] for d in scan['datasets'])
land_null = [f['properties'].get('NAME') for f in nmp if not f.get('geometry')]
scan_out = {'n': len(rows), 'records': sum(r[2] for r in rows), 'no_geometry': tot('no_geometry'), 'wgs84_zero': tot('wgs84_zero'),
            'svy21_zero': tot('svy21_zero'), 'far_away': tot('far_away'), 'rows': rows, 'strays': strays,
            'land_null': land_null, 'downloaded': '1 Nov 2026'}
print('scan:', {k: v for k, v in scan_out.items() if k not in ('rows', 'strays')})
for st in strays:
    print('   stray:', st['dataset'], '|', st['name'], '|', st['why'], '|', st['pt'])

# ---------------------------------------------------------------- 9. write
out = {
    'svy21': {'lat0': LAT0, 'lon0': LON0, 'k0': K0, 'fe': FE, 'fn': FN, 'lat0_dms': dms(LAT0, 'N', 'S', 0), 'lon0_dms': dms(LON0, 'E', 'W', 0),
              'base7': [r6(BASE7[0]), r6(BASE7[1])], 'base7_m': round(d_b7, 1),
              'aou': AOU, 'datum_shift': {'code': 8886, 'accuracy_m': tf['Accuracy'], 'remark': tf['Remark']}},
    'zero': {'lon': ZLON, 'lat': ZLAT, 'lon_dms': dms(ZLON, 'E', 'W'), 'lat_dms': dms(ZLAT, 'N', 'S'),
             'from_origin_m': round(d_oz, 1), 'grid_m': round(grid_oz, 3), 'azimuth': round(az_oz, 1),
             'aou_south_km': round(south_by / 1000, 3), 'aou_west_km': round(west_by / 1000, 3),
             'land': {'name': land_name, 'osm': f'way/{land_way["id"]}', 'km': round(d_land / 1000, 3), 'pt': [r6(v) for v in p_land], 'azimuth': round(G.inv(ZLON, ZLAT, *p_land)[0], 1),
                      'country': land_country},
             'admin': [lvl_z.get(k) for k in sorted(lvl_z) if k <= 6],
             'sg': {'km': round(d_sg / 1000, 3), 'pt': [r6(v) for v in p_sg], 'name': sg_names[i_sg], 'azimuth': round(G.inv(ZLON, ZLAT, *p_sg)[0], 1)},
             'buoy': {'m': round(d_buoy), 'pt': [buoy['lon'], buoy['lat']], 'osm': f'node/{buoy["id"]}',
                      'category': bt.get('seamark:buoy_special_purpose:category'), 'colour': bt.get('seamark:buoy_special_purpose:colour'),
                      'light': f"{bt.get('seamark:light:character', '')} {bt.get('seamark:light:colour', '')} {bt.get('seamark:light:period', '')} s".strip()},
             'anchorage': {'m': round(d_anch), 'osm': f'way/{anch[i_anch]["id"]}', 'c': [[r6(x), r6(y)] for x, y in anch_geoms[i_anch].exterior.coords]},
             'zones': {'archipelagic': z_arch[0]['geoname'], 'eez': z_eez[0]['geoname'] if z_eez else None, 'iho': z_iho[0]['name'],
                       'strait_km': round(d_strait / 1000, 3), 'strait_pt': [r6(v) for v in p_strait]},
             'boundaries': BOUNDS},
    'sg_land': {'min_e': round(wx[0], 1), 'min_e_pt': [r6(v) for v in TO_WGS.transform(wx[1], wx[2])], 'min_e_name': wx[3],
                'min_n': round(sy[0], 1), 'min_n_pt': [r6(v) for v in TO_WGS.transform(sy[1], sy[2])], 'min_n_name': sy[3]},
    'wgs': {'svy_e': round(WE, 3), 'svy_n': round(WN, 3), 'inf': [r6(INF[0]), 0],
            'land': {'km': round(d_w / 1000, 3), 'pt': [r6(v) for v in p_w], 'near': w_place, 'country': w_country}, 'gulf_km': round(d_gulf / 1000, 3), 'gulf_pt': [r6(v) for v in p_gulf],
            'iho': z0['iho'][0]['name'], 'high_seas': True, 'ne_null': ne_null, 'from_origin_km': round(d_sg_w / 1000, 3), 'from_zero_km': round(d_z_w / 1000, 3)},
    'grid': grid, 'neg': neg, 'box': false_box, 'path': path, 'gulf': gulf_line, 's2': s2, 'scan': scan_out,
}
os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, 'null.js'), 'w', encoding='utf-8') as f:
    f.write('window.DAY18 = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n')
print('null.js', os.path.getsize(os.path.join(OUT, 'null.js')), 'bytes')
