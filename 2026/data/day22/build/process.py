"""Day 22 Projections: how big is Singapore in Web Mercator, Mercator, UTM 48N and SVY21?

Requires: Python 3.10+, shapely>=2, pyproj>=3 (PROJ 9), numpy
          (pip install shapely pyproj numpy)
usage: python -I process.py <raw-dir> <out.json>
       <raw-dir> is the folder fetch.py filled.

What it does
  1. Singapore = every polygon of SLA's Coastal_Outlines layer except the ones named
     JOHOR (MALAYSIA): the main island, Pulau Tekong, Jurong Island, Sentosa, Ubin, the
     Southern Islands, Pedra Branca, and the linkways and the Singapore half of the Causeway.
     They are unioned (no overlap counted twice). Areas use the full-resolution outline.
  2. True area: geodesic, on the WGS 84 ellipsoid (pyproj.Geod, Karney's algorithm).
  3. Projected areas: the outline transformed with pyproj into each projection and measured
     as a flat polygon (shoelace): EPSG:3857 Web Mercator, EPSG:3395 World Mercator (the
     ellipsoidal Mercator), EPSG:32648 UTM 48N, EPSG:3414 SVY21, and a Lambert azimuthal
     equal-area projection on the WGS 84 ellipsoid centred on the island (the control).
  4. Scale factors: at every vertex of the outline and a 500 m grid of points on land, the
     map's scale is measured directly: step 5 m north, south, east and west on the ellipsoid
     (Geod.fwd), project, and divide map distance by ground distance. This is measured
     against the ellipsoid on purpose: PROJ's own get_factors() treats EPSG:3857 as the
     sphere it pretends to be and reports only sec(lat), missing Web Mercator's 0.67%
     north-south stretch. For the conformal projections both methods agree (checked below).
  5. The outline is simplified (15 m, in SVY21 metres) for drawing only; it is shipped as
     lon/lat in integer micro-degrees, delta-encoded per ring. Rings wind the way d3-geo
     wants them (outer rings clockwise, holes anticlockwise), the reverse of RFC 7946.
  6. World inset: Natural Earth 1:110m land, rounded to 0.01 degree, cut at 85 deg N/S.
     Cities for the "drag it north" ruler: Natural Earth 1:110m populated places.
"""
import json
import os
import sys

import numpy as np
import shapely
from pyproj import CRS, Geod, Proj, Transformer
from shapely.geometry import box, shape
from shapely.ops import unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
GEOD = Geod(ellps='WGS84')
GBTB_HA = 101   # Gardens by the Bay, official: "101 hectares" (gardensbythebay.com.sg media room, 2011)


def tf(src, dst):
    t = Transformer.from_crs(src, dst, always_xy=True)
    return lambda g: shapely.transform(g, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


def geod_m2(g):
    return abs(GEOD.geometry_area_perimeter(g)[0])


# ---------------------------------------------------------------- 1. Singapore
nmp = json.load(open(os.path.join(RAW, 'nmp.geojson'), encoding='utf-8'))
parts, main, sla_area_main, n_feat = [], None, None, 0
for f in nmp['features']:
    p = f['properties']
    if p.get('FOLDERPATH') != 'Layers/Coastal_Outlines' or not f['geometry']:
        continue
    if 'JOHOR' in (p.get('NAME') or ''):
        continue
    g = shapely.force_2d(shape(f['geometry']))
    n_feat += 1
    parts.append(g)
    if p.get('NAME') == 'SINGAPORE - MAIN ISLAND':
        main, sla_area_main = g, float(p['SHAPE.AREA'])
sg = unary_union(parts)
sg = shapely.make_valid(sg)
upd = max(f['properties'].get('FMEL_UPD_D') or '' for f in nmp['features'])
print(f'{n_feat} Singapore polygons, union: {sg.geom_type} with {len(getattr(sg, "geoms", [sg]))} parts; data updated {upd}')

# anchor: the main island's centroid (SVY21), the centre of the equal-area control
to_svy, from_svy = tf(4326, 3414), tf(3414, 4326)
c = from_svy(to_svy(main).centroid)
ANCHOR = [round(c.x, 4), round(c.y, 4)]
LAEA = CRS.from_proj4(f'+proj=laea +lat_0={ANCHOR[1]} +lon_0={ANCHOR[0]} +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs')
PROJS = [   # id, label, crs
    ('webmerc', 'Web Mercator', CRS.from_epsg(3857)),
    ('merc', 'Mercator', CRS.from_epsg(3395)),
    ('utm', 'UTM 48N', CRS.from_epsg(32648)),
    ('svy21', 'SVY21', CRS.from_epsg(3414)),
    ('laea', 'Equal-area', LAEA),
]

# ---------------------------------------------------------------- 2-3. areas
def areas(g):
    truth = geod_m2(g)
    rows = {}
    for pid, _, crs in PROJS:
        a = tf(4326, crs)(g).area
        rows[pid] = dict(area=a, err=a - truth, pct=100 * (a - truth) / truth)
    return truth, rows


A = {}
for key, g in (('all', sg), ('main', main)):
    truth, rows = areas(g)
    A[key] = dict(truth=truth, rows=rows)
    print(f'\n{key}: true (geodesic) area {truth / 1e6:.4f} km2')
    for pid, r in rows.items():
        print(f'  {pid:8s} {r["area"] / 1e6:10.4f} km2  {r["err"] / 1e6:+9.4f} km2  {r["pct"]:+.5f}%  = {r["err"] / (GBTB_HA * 1e4):+.2f} Gardens by the Bay')
svy_main = to_svy(main).area
DIST = dict(   # km from the island's centre, on the ellipsoid
    utm_cm=GEOD.inv(ANCHOR[0], ANCHOR[1], 105.0, ANCHOR[1])[2] / 1000,
    equator=GEOD.inv(ANCHOR[0], ANCHOR[1], ANCHOR[0], 0.0)[2] / 1000)
print(f'\ncentre {ANCHOR}: {DIST["utm_cm"]:.1f} km to the UTM 48N centre line (105 E), {DIST["equator"]:.1f} km to the equator')
print(f'SLA SHAPE.AREA of the main island {sla_area_main:.1f} m2; our SVY21 area {svy_main:.1f} m2 (diff {svy_main - sla_area_main:+.4f} m2)')

# ---------------------------------------------------------------- 4. scale factors
def sample_points(g, step=500.0):
    """Every vertex of g plus a grid of points on land, as lon/lat arrays."""
    v = shapely.get_coordinates(g)
    gs = to_svy(g)
    x0, y0, x1, y1 = gs.bounds
    xs, ys = np.meshgrid(np.arange(x0, x1, step), np.arange(y0, y1, step))
    pts = shapely.points(xs.ravel(), ys.ravel())
    inside = shapely.contains(gs, pts)
    grid = shapely.get_coordinates(from_svy(shapely.multipoints(pts[inside])))
    return np.vstack([v, grid])


def scale_factors(crs, lon, lat, d=5.0):
    """Map scale against the WGS 84 ellipsoid by central differences of d metres."""
    t = Transformer.from_crs(4326, crs, always_xy=True)
    n = len(lon)
    out = {}
    for name, az in (('h', 0.0), ('k', 90.0)):
        lo1, la1, _ = GEOD.fwd(lon, lat, np.full(n, az), np.full(n, d))
        lo2, la2, _ = GEOD.fwd(lon, lat, np.full(n, az + 180.0), np.full(n, d))
        x1, y1 = t.transform(lo1, la1)
        x2, y2 = t.transform(lo2, la2)
        out[name] = (np.array(x1) - np.array(x2), np.array(y1) - np.array(y2))
    (hx, hy), (kx, ky) = out['h'], out['k']
    h = np.hypot(hx, hy) / (2 * d)
    k = np.hypot(kx, ky) / (2 * d)
    areal = np.abs(hx * ky - hy * kx) / (2 * d) ** 2
    return h, k, areal


S, NPTS = {}, {}
for key, g in (('main', main), ('all', sg)):
    P = sample_points(g)
    lon, lat = P[:, 0], P[:, 1]
    S[key] = {}
    NPTS[key] = len(lon)
    print(f'\nscale factors, {key}: {len(lon)} points')
    for pid, label, crs in PROJS:
        h, k, ar = scale_factors(crs, lon, lat)
        rec = {}
        for nm, arr in (('h', h), ('k', k), ('area', ar)):
            i0, i1 = int(arr.argmin()), int(arr.argmax())
            rec[nm] = [float(arr[i0]), float(arr[i1]), [round(lon[i0], 4), round(lat[i0], 4)], [round(lon[i1], 4), round(lat[i1], 4)]]
        S[key][pid] = rec
        print(f'  {pid:8s} h {h.min():.7f}..{h.max():.7f}  k {k.min():.7f}..{k.max():.7f}  area {ar.min():.7f}..{ar.max():.7f}')
        if pid in ('svy21', 'utm', 'merc'):   # conformal: compare with PROJ's analytic factors
            f = Proj(crs).get_factors(lon, lat)
            dev = np.abs(np.asarray(f.parallel_scale) - k).max()
            print(f'           max |k - PROJ get_factors| = {dev:.2e}')
            assert dev < 1e-7, 'scale-factor check failed'
    if key == 'main':   # Web Mercator on the equator itself, where Mercator proper is exact
        h0, k0, _ = scale_factors(CRS.from_epsg(3857), np.array([ANCHOR[0]]), np.array([0.0]))
        WM_EQ = dict(h=round(float(h0[0]), 9), k=round(float(k0[0]), 9))
        print(f'  webmerc on the equator: h {h0[0]:.7f}  k {k0[0]:.7f}')
    f3857 = Proj(CRS.from_epsg(3857)).get_factors(lon, lat)
    print(f'  (PROJ get_factors for 3857 says meridional {np.min(f3857.meridional_scale):.7f}..{np.max(f3857.meridional_scale):.7f}: the sphere it assumes)')

# ---------------------------------------------------------------- 5. outline for drawing
simp = from_svy(shapely.simplify(to_svy(sg), 15.0, preserve_topology=True))
polys = [p for p in getattr(simp, 'geoms', [simp]) if not p.is_empty]
U = 1e6


def enc(coords):
    out, px, py = [], 0, 0
    for x, y in coords[:-1]:   # rings are closed on the page
        ix, iy = round(x * U), round(y * U)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


coast = []
for p in sorted(polys, key=lambda p: -p.area):
    p = shapely.geometry.polygon.orient(p, -1.0)   # d3-geo winding: outer ring clockwise
    coast.append([enc(list(p.exterior.coords))] + [enc(list(r.coords)) for r in p.interiors])
nv = sum(len(r) // 2 for p in coast for r in p)
print(f'\ndrawing outline: {len(coast)} polygons, {nv} vertices')

# ---------------------------------------------------------------- 6. world inset and cities
land = json.load(open(os.path.join(RAW, 'ne_110m_land.geojson'), encoding='utf-8'))
clipbox = box(-180, -85, 180, 85)
world = []
for f in land['features']:
    g = shape(f['geometry']).intersection(clipbox)
    for p in getattr(g, 'geoms', [g]):
        if p.is_empty or p.geom_type != 'Polygon':
            continue
        p = shapely.geometry.polygon.orient(p, -1.0)   # clockwise for d3-geo
        ring, out, px, py = list(p.exterior.coords)[:-1], [], 0, 0
        for x, y in ring:
            ix, iy = round(x * 100), round(y * 100)
            if out and ix == px and iy == py:
                continue
            out += [ix - px, iy - py]
            px, py = ix, iy
        if len(out) >= 6:
            world.append(out)
places = json.load(open(os.path.join(RAW, 'ne_110m_populated_places_simple.geojson'), encoding='utf-8'))
WANT = ['Singapore', 'Bangkok', 'Hong Kong', 'Tokyo', 'Paris', 'London', 'Moscow', 'Oslo', 'Helsinki', 'Reykjavík']
byname = {f['properties']['name']: f for f in places['features']}
cities = []
for nm in WANT:
    f = byname.get(nm)
    if not f:
        print('missing city', nm)
        continue
    lo, la = f['geometry']['coordinates']
    cities.append([nm, round(lo, 3), round(la, 3)])
print('cities', cities)

# "Drag it north": Singapore moved to each city's latitude and longitude without changing its
# shape or size (out of an equal-area projection centred on the island, back in through one
# centred on the city), then measured in Web Mercator. The page computes the same thing live.
home_laea = tf(4326, LAEA)(sg)
for row in cities:
    lo, la = row[1], row[2]
    there = CRS.from_proj4(f'+proj=laea +lat_0={la} +lon_0={lo} +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs')
    moved = tf(there, 4326)(home_laea)
    g_true = geod_m2(moved)
    g_wm = tf(4326, 3857)(moved).area
    row.append(round(g_wm / g_true, 6))
    print(f'  Singapore at {row[0]:10s} {la:7.3f}: true {g_true / 1e6:.3f} km2, Web Mercator {g_wm / 1e6:9.2f} km2, x{g_wm / g_true:.4f}')

# ---------------------------------------------------------------- write
def r6(x):
    return float(f'{x:.6g}')


crsinfo = {}
for pid, label, crs in PROJS:
    prm = {pp.name: pp.value for pp in crs.coordinate_operation.params} if crs.coordinate_operation else {}
    crsinfo[pid] = dict(label=label, code=(f'EPSG:{crs.to_epsg()}' if crs.to_epsg() else 'custom LAEA'), params=prm)

out = dict(
    note='Day 22 Projections. Areas in m2, built by data/day22/build/process.py',
    updated=upd, anchor=ANCHOR, npoints=NPTS, wm_equator=WM_EQ, dist={k: round(v, 1) for k, v in DIST.items()}, gbtb_ha=GBTB_HA, features=n_feat,
    areas={k: dict(truth=round(v['truth'], 1), rows={p: dict(area=round(r['area'], 1), err=round(r['err'], 1), pct=r6(r['pct'])) for p, r in v['rows'].items()})
           for k, v in A.items()},
    sla_main=dict(shape_area=round(sla_area_main, 1), svy21=round(svy_main, 1)),
    scale={k: {p: {nm: [round(a[0], 9), round(a[1], 9), a[2], a[3]] for nm, a in rec.items()}
               for p, rec in v.items()} for k, v in S.items()},
    crs=crsinfo, coast=coast, world=world, cities=cities,
)
with open(OUT, 'w', encoding='utf-8') as fh:
    json.dump(out, fh, separators=(',', ':'), ensure_ascii=False)
print(f'\nwrote {OUT}: {os.path.getsize(OUT) / 1024:.0f} KB')
