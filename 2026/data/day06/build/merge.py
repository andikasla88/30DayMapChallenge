"""Merge the day 06 build outputs into the one file the page loads, with every context
geometry packed as Google-polyline strings (lng, lat at 1e5).
usage: python merge.py <context.json> <blocks.json> <out sheet.json>
Run order: fetch.py, fetch_osm.py, geocode_streets.py, build_context.py, build_blocks.py, merge.py
Packed geometry: {"t": "P", "c": [[ring, ...], ...]} (polygons) or {"t": "L", "c": [line, ...]} (lines)."""
import sys, json


def polyline(pts, k=1e5):
    out, px, py = [], 0, 0
    for x, y in pts:
        x, y = round(x * k), round(y * k)
        if (x, y) == (px, py) and out: continue
        for v in (x - px, y - py):
            v = ~(v << 1) if v < 0 else v << 1
            while v >= 0x20:
                out.append(chr((0x20 | (v & 0x1f)) + 63)); v >>= 5
            out.append(chr(v + 63))
        px, py = x, y
    return ''.join(out)


def pack(g):
    t = g['type']
    if t == 'GeometryCollection':
        parts = [pack(x) for x in g['geometries']]
        lines = [c for p in parts if p['t'] == 'L' for c in p['c']]
        polys = [c for p in parts if p['t'] == 'P' for c in p['c']]
        return {'t': 'P', 'c': polys} if polys and not lines else {'t': 'L', 'c': lines}
    if t == 'Polygon': return {'t': 'P', 'c': [[polyline(r) for r in g['coordinates']]]}
    if t == 'MultiPolygon': return {'t': 'P', 'c': [[polyline(r) for r in p] for p in g['coordinates']]}
    if t == 'LineString': return {'t': 'L', 'c': [polyline(g['coordinates'])]}
    if t == 'MultiLineString': return {'t': 'L', 'c': [polyline(l) for l in g['coordinates']]}
    if t == 'Point' or t == 'MultiPoint': return {'t': 'L', 'c': []}
    raise ValueError(t)


ctx = json.load(open(sys.argv[1], encoding='utf-8'))
out = {}
for k, v in ctx.items():
    if isinstance(v, list): out[k] = [pack(g) for g in v]
    elif 'type' in v: out[k] = pack(v)
    else: out[k] = {kk: pack(g) for kk, g in v.items()}
blk = json.load(open(sys.argv[2], encoding='utf-8'))
blk['ctx'] = out
s = json.dumps(blk, separators=(',', ':'))
open(sys.argv[3], 'w', encoding='utf-8').write(s)
print('sheet.json bytes', len(s), 'context', len(json.dumps(out, separators=(',', ':'))))
