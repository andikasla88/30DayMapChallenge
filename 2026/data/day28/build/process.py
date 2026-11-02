"""Day 28 Feeling: turn the raw downloads into data/day28/feeling.js.

Requires: Python 3.10+, shapely>=2, pyproj>=3, numpy
          (pip install shapely pyproj numpy)
usage: python -I process.py <raw-dir> <out.json> [YYYY-MM-DD]
       <raw-dir> is the folder fetch.py filled; the date picks wbgt-<date>.json
       (default: the newest one there).

What it does
  1. Snapshot: every WBGT record of the day, oldest first, as one row of station values
     (tenths of a degree C, null when a station sent nothing). This is what the page shows
     when the live API cannot be reached, labelled with its time.
  2. Checks NEA's heat-stress labels in the data against the official WBGT thresholds the
     page uses (Low below 31 C, Moderate 31 to below 33 C, High 33 C and above; MSE and NEA
     Heat Stress Advisory, July 2023). The build stops if any reading disagrees.
  3. Land: SLA National Map Polygon, Coastal_Outlines layer, minus the polygons named
     JOHOR (MALAYSIA) and outside the map frame (Pedra Branca); unioned and simplified 15 m in
     SVY21 metres. Johor is kept separately, simplified 60 m, as grey context. Inland water:
     the Hydrographic layer's polygons over 0.05 km2 (reservoirs, rivers, basins), drawn on top.
     All shipped as lon/lat x 1e5 integers, delta-encoded per ring.
  4. Cross-check: the page interpolates in the browser. The same inverse-distance weighting
     (power 2, distances in metres) is run here on the same grid for the snapshot's latest
     record, so the page's headline numbers can be compared against these.
"""
import glob
import json
import math
import os
import sys

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import box, shape, mapping
from shapely.ops import unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
if len(sys.argv) > 3:
    WB = os.path.join(RAW, f'wbgt-{sys.argv[3]}.json')
else:
    WB = sorted(glob.glob(os.path.join(RAW, 'wbgt-*.json')))[-1]

# The map frame (and the interpolation grid), in degrees. Same numbers as the page.
W0, S0, E0, N0 = 103.59, 1.19, 104.10, 1.48
GW, GH = 640, 364
POWER = 2
KX, KY = 111320 * math.cos(math.radians(1.335)), 110574
LOW, HIGH = 31.0, 33.0   # NEA thresholds: Low < 31 <= Moderate < 33 <= High


def category(v):
    return 'Low' if v < LOW else 'Moderate' if v < HIGH else 'High'


# ---------------------------------------------------------------- 1. snapshot
raw = json.load(open(WB, encoding='utf-8'))
recs = sorted(raw['records'], key=lambda r: r['datetime'])
stations = {}
for r in recs:
    for x in r['item']['readings']:
        s = x['station']
        if s['id'] not in stations:
            stations[s['id']] = [s['id'], s['name'], s.get('townCenter') or s['name'],
                                 round(float(x['location']['longitude']), 5), round(float(x['location']['latitude']), 5)]
ids = sorted(stations)
col = {k: i for i, k in enumerate(ids)}
times, rows, bad = [], [], []
for r in recs:
    row = [None] * len(ids)
    for x in r['item']['readings']:
        v = x.get('wbgt')
        if v in (None, ''):
            continue
        v = float(v)
        row[col[x['station']['id']]] = round(v * 10)
        if x.get('heatStress') and x['heatStress'] != category(v):
            bad.append((r['datetime'], x['station']['id'], v, x['heatStress']))
    times.append(r['datetime'])
    rows.append(row)
if bad:
    raise SystemExit(f'NEA labels disagree with the thresholds: {bad[:5]}')
n_read = sum(v is not None for row in rows for v in row)
print(f'snapshot {os.path.basename(WB)}: {len(times)} records, {len(ids)} stations, {n_read} readings; '
      f'all labels match Low<{LOW}<=Moderate<{HIGH}<=High')

# ---------------------------------------------------------------- 2. land and water
to_svy = Transformer.from_crs('EPSG:4326', 'EPSG:3414', always_xy=True)
to_ll = Transformer.from_crs('EPSG:3414', 'EPSG:4326', always_xy=True)
svy = lambda g: shapely.transform(g, lambda c: np.column_stack(to_svy.transform(c[:, 0], c[:, 1])))
ll = lambda g: shapely.transform(g, lambda c: np.column_stack(to_ll.transform(c[:, 0], c[:, 1])))

nmp = json.load(open(os.path.join(RAW, 'nmp.geojson'), encoding='utf-8'))
frame = box(W0, S0, E0, N0)
sg, jb, water = [], [], []
for f in nmp['features']:
    p, g = f['properties'], f['geometry']
    if not g:
        continue
    folder = p.get('FOLDERPATH')
    if folder == 'Layers/Coastal_Outlines':
        (jb if 'JOHOR' in (p.get('NAME') or '') else sg).append(shape(g).buffer(0))
    elif folder == 'Layers/Hydrographic':
        water.append(shape(g).buffer(0))
land = unary_union(sg).intersection(frame)
johor = unary_union(jb).intersection(box(W0 - .2, S0, E0 + .2, N0 + .2))
land_m = svy(land)
water = [w for w in water if svy(w).area > 5e4 and w.intersects(land)]
water = unary_union(water).intersection(land)
print(f'land {land_m.area / 1e6:.1f} km2 (within the frame), {len(water.geoms) if hasattr(water, "geoms") else 1} water polygons')


def simplify(g, tol):
    return ll(shapely.simplify(svy(g), tol, preserve_topology=True))


def encode(g, min_m2=0):
    """[[ring, ...], ...]: one list of delta-encoded rings per polygon."""
    out = []
    polys = g.geoms if hasattr(g, 'geoms') else [g]
    for p in polys:
        if p.is_empty or p.geom_type != 'Polygon' or svy(p).area < min_m2:
            continue
        rings = []
        for ring in [p.exterior, *p.interiors]:
            cs = [(round(x * 1e5), round(y * 1e5)) for x, y in ring.coords]
            flat, px, py = [], 0, 0
            for x, y in cs:
                flat += [x - px, y - py]
                px, py = x, y
            rings.append(flat)
        out.append(rings)
    return out


land_s = simplify(land, 15)
land_s = shapely.make_valid(land_s)
if land_s.geom_type == 'GeometryCollection':
    land_s = unary_union([g for g in land_s.geoms if g.geom_type in ('Polygon', 'MultiPolygon')])
land_enc = encode(land_s, 2000)      # drop islets under 0.2 ha
johor_enc = encode(simplify(johor, 60), 2e5)
water_enc = encode(simplify(water, 15), 2e4)

# ---------------------------------------------------------------- 3. cross-check (latest record)
lon = W0 + (np.arange(GW) + .5) / GW * (E0 - W0)
lat = N0 - (np.arange(GH) + .5) / GH * (N0 - S0)
LX, LY = np.meshgrid(lon, lat)
on_land = shapely.contains_xy(land_s, LX, LY)
name_at = {(stations[k][3], stations[k][4]): stations[k][1] for k in ids}


def summary(t):
    """What the page shows for record t: stations, hottest, coolest, mean, land share."""
    pts = [(stations[k][3], stations[k][4], rows[t][i] / 10) for i, k in enumerate(ids) if rows[t][i] is not None]
    num = np.zeros_like(LX); den = np.zeros_like(LX)
    for x, y, v in pts:
        d2 = ((LX - x) * KX) ** 2 + ((LY - y) * KY) ** 2
        w = 1 / np.maximum(d2, 1e-6) ** (POWER / 2)
        num += w * v; den += w
    vals = (num / den)[on_land]
    share = {c: round(float(np.mean((vals >= lo) & (vals < hi))), 4) for c, lo, hi in
             (('Low', -99, LOW), ('Moderate', LOW, HIGH), ('High', HIGH, 99))}
    hot = max(pts, key=lambda p: p[2]); cold = min(pts, key=lambda p: p[2])
    return {'time': times[t], 'stations': len(pts), 'hottest': [name_at[hot[:2]], hot[2]], 'coolest': [name_at[cold[:2]], cold[2]],
            'mean': round(sum(p[2] for p in pts) / len(pts), 2), 'landShare': share,
            'atModerateOrAbove': sum(p[2] >= LOW for p in pts), 'atHigh': sum(p[2] >= HIGH for p in pts)}


top = max(v for row in rows for v in row if v is not None)
peaks = [[times[t], stations[k][1]] for t in range(len(rows)) for i, k in enumerate(ids) if rows[t][i] == top]
check = {'latest': summary(len(rows) - 1), 'atDayPeak': summary(times.index(peaks[0][0])),
         'dayPeak': {'wbgt': top / 10, 'where': peaks}, 'landPixels': int(on_land.sum())}
print(json.dumps(check, indent=1))

out = {
    'frame': [[W0, S0], [E0, N0]], 'grid': [GW, GH], 'power': POWER, 'thresholds': [LOW, HIGH],
    'snapshot': {'date': raw['date'], 'fetched': raw['fetched'], 'stations': [stations[k] for k in ids],
                 'times': times, 'v': rows},
    'land': land_enc, 'johor': johor_enc, 'water': water_enc,
    'check': check,
}
with open(OUT, 'w', encoding='utf-8') as f:
    f.write('window.DAY28 = ' + json.dumps(out, separators=(',', ':'), ensure_ascii=False) + ';\n')
print(f'{OUT}: {os.path.getsize(OUT):,} bytes')
