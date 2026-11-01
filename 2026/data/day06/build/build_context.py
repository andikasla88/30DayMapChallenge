"""Day 06 context layers: land (from OSM coastline), water-lining rings, reservoirs, roads, rail.
usage: python -X utf8 build_context.py <raw_dir> <out_json>
Writes a compact JSON of GeoJSON-ish geometries, coordinates rounded to 5 decimals."""
import sys, os, json
import numpy as np
from shapely.geometry import shape, LineString, Polygon, MultiPolygon, box, mapping, Point
import warnings; warnings.filterwarnings("ignore")
from shapely.ops import unary_union, polygonize, linemerge, transform
from pyproj import Transformer
RAW, OUT = sys.argv[1], sys.argv[2]
fw = Transformer.from_crs(4326, 3414, always_xy=True).transform
bw = Transformer.from_crs(3414, 4326, always_xy=True).transform
def osm(k): return json.load(open(os.path.join(RAW, f'osm_{k}.json'), encoding='utf-8'))['elements']
def line(e): return LineString([(p['lon'], p['lat']) for p in e['geometry']])

BB = box(103.2, 0.8, 104.5, 1.9)
# ---- land from coastline: polygonize the coastline noded with the bbox edge, keep faces on the land side
coast = [line(e) for e in osm('coast') if len(e.get('geometry', [])) > 1]
lines = unary_union([c.intersection(BB) for c in coast] + [BB.exterior])
faces = list(polygonize(lines))
def is_land(face):
    # land lies to the LEFT of OSM coastline direction: test a point just left of the nearest coastline segment
    p = face.representative_point()
    best = None
    for c in coast:
        d = c.distance(p)
        if best is None or d < best[0]: best = (d, c)
    c = best[1]
    s = c.project(p); a = c.interpolate(max(s - 1e-5, 0)); b = c.interpolate(min(s + 1e-5, c.length))
    dx, dy = b.x - a.x, b.y - a.y
    m = c.interpolate(s)
    cross = dx * (p.y - m.y) - dy * (p.x - m.x)
    return cross > 0
land_faces = [f for f in faces if f.area > 1e-9 and is_land(f)]
land = unary_union(land_faces)
print('land faces', len(land_faces), 'area', land.area)
land_m = transform(fw, land).buffer(0)
land_m = land_m.simplify(8)
# drop tiny islets (< 2000 m2) from the drawn land; keep everything for water-lining except specks
def polys(g): return list(g.geoms) if hasattr(g, 'geoms') else [g]
land_m = unary_union([p for p in polys(land_m) if p.area > 2000])
# Singapore's own land (touching a URA Master Plan 2019 planning area) vs the neighbours'
pa = unary_union([shape(f['geometry']).buffer(0) for f in json.load(open(os.path.join(RAW, 'planning_areas.geojson'), encoding='utf-8'))['features']])
pa_m = transform(fw, pa).buffer(150)
sg_parts = [p for p in polys(land_m) if p.intersects(pa_m)]
foreign_m = unary_union([p for p in polys(land_m) if not p.intersects(pa_m)])
# ---- water-lining: rings offset into the sea
RINGS = [45, 105, 180, 270, 380, 510, 670]
bbm = transform(fw, BB)
water_lines = []
for i, d in enumerate(RINGS):
    g = land_m.buffer(d, join_style=1, resolution=4).simplify(max(6, d * 0.05))
    ring = g.boundary.intersection(bbm.buffer(-30))
    water_lines.append(ring)
# ---- reservoirs / lakes (polygons) with inner water-lining
water = []
for e in osm('water'):
    try:
        if e['type'] == 'way':
            pts = [(p['lon'], p['lat']) for p in e['geometry']]
            if len(pts) < 4 or pts[0] != pts[-1]: continue
            water.append(Polygon(pts))
        else:
            outers = [line(m) for m in e['members'] if m.get('role') == 'outer' and m.get('geometry')]
            inners = [line(m) for m in e['members'] if m.get('role') == 'inner' and m.get('geometry')]
            po = unary_union(list(polygonize(linemerge(outers))))
            pi = unary_union(list(polygonize(linemerge(inners)))) if inners else None
            water.append(po.difference(pi) if pi else po)
    except Exception as ex:
        print('water skip', e.get('id'), ex)
water_m = unary_union([transform(fw, w).buffer(0) for w in water]).simplify(5)
water_m = unary_union([p for p in polys(water_m) if p.area > 20000])
water_m = water_m.intersection(land_m)
inner_lines = []
for d in (18, 42, 72):
    g = water_m.buffer(-d, join_style=1, resolution=4)
    if not g.is_empty: inner_lines.append(g.boundary.simplify(7))
# ---- roads
roads = {'motorway': [], 'trunk': [], 'primary': []}
for e in osm('roads'):
    hw = e['tags'].get('highway')
    if hw in roads and len(e.get('geometry', [])) > 1: roads[hw].append(line(e))
road_out = {}
for k, ls in roads.items():
    g = linemerge(unary_union(ls))
    g = transform(bw, transform(fw, g).simplify(7))
    road_out[k] = g
# ---- rail: surface vs tunnel
rail_s, rail_t = [], []
for e in osm('rail'):
    if len(e.get('geometry', [])) < 2: continue
    (rail_t if e['tags'].get('tunnel') in ('yes', 'building_passage') or e['tags'].get('layer', '0').startswith('-') else rail_s).append(line(e))
def rail(ls): return transform(bw, transform(fw, linemerge(unary_union(ls))).simplify(6))

def r5(geom):
    gj = mapping(geom)
    def rnd(c):
        if isinstance(c[0], (int, float)): return [round(c[0], 5), round(c[1], 5)]
        return [rnd(x) for x in c]
    gj['coordinates'] = rnd(gj['coordinates']) if 'coordinates' in gj else None
    if gj['type'] == 'GeometryCollection':
        return {'type': 'GeometryCollection', 'geometries': [r5(g) for g in geom.geoms]}
    return gj
def ll(g): return transform(bw, g)
# the drawn coastline: the land's edge without the sheet's own cut edges
coast_m = land_m.boundary.difference(bbm.exterior.buffer(25))
out = {
    'land': r5(ll(unary_union(sg_parts))),
    'foreign': r5(ll(foreign_m)),
    'coast': r5(ll(coast_m)),
    'waterlines': [r5(ll(g)) for g in water_lines],
    'reservoirs': r5(ll(water_m)),
    'reslines': [r5(ll(g)) for g in inner_lines],
    'roads': {k: r5(v) for k, v in road_out.items()},
    'rail': r5(rail(rail_s)), 'railTunnel': r5(rail(rail_t)),
}
s = json.dumps(out, separators=(',', ':'))
open(OUT, 'w').write(s)
print('context bytes', len(s), {k: len(json.dumps(v, separators=(',', ':'))) for k, v in out.items()})
