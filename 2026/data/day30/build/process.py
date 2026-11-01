"""Day 30 (Pen & paper): the truth a visitor's from-memory drawing of Singapore is scored against.

Requires: Python 3.10+, shapely>=2, pyproj>=3, numpy  (pip install shapely pyproj numpy)

Inputs (see build.sh):
  nmp.geojson   SLA National Map Polygon, data.gov.sg d_29f066d67df3eae91df8a42f443863c8,
                layer Coastal_Outlines: "SINGAPORE - MAIN ISLAND" and the other islands.
                The same file Day 10 scored Claude's drawing against.
  answer.json   Day 10's transcript: Claude's from-memory outline (read only).
  memory.json   Day 10's published scores, and its LTA station points from cheeaun/sgraildata
                v5.1.0 (read only). Four stations stand for the four landmark pins.

Output: paper.json, loaded by day30-pen-paper.html. The page scores drawings itself, in the
browser, with the same measures as Day 10:
  overlap      area inside both outlines / area inside either (main island, holes kept)
  area         the drawing's area against the real island's (Day 10: geodesic WGS84 km2)
  corners      mean distance from each corner of the drawing to the real coast (Day 10's headline)
  coast        mean distance from the real coast, every 25 m along it, to the drawing
  landmarks    straight-line distance from each pin to its MRT station
Distances are SVY21 (EPSG:3414) metres, as on Day 10. So the page can measure exactly what
Day 10 measured, the full-detail main-island ring is shipped in SVY21 decimetres.

This script re-scores Claude's Day 10 outline from the shipped (rounded) ring and checks it
against Day 10's published numbers, and writes a second, shifted-and-scaled test outline with
its shapely scores, so the page's own scorer can be checked against shapely (see the test).

usage: python -I process.py <nmp.geojson> <answer.json> <memory.json> <out.json>
"""
import json
import math
import sys

import numpy as np
from pyproj import Geod, Transformer
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon, shape
from shapely.geometry.polygon import orient

GEOD = Geod(ellps='WGS84')
TO_SVY = Transformer.from_crs(4326, 3414, always_xy=True)
TO_WGS = Transformer.from_crs(3414, 4326, always_xy=True)


def _tf(t):
    return lambda g: shapely.transform(g, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


svy, wgs = _tf(TO_SVY), _tf(TO_WGS)

# The paper sheet is a fixed window onto Web Mercator, 3 wide by 2 high, centred on the island.
WIN_W, WIN_E, WIN_CLAT = 103.565, 104.115, 1.34
SHOW_TOL = {'main': 8.0, 'other': 12.0}    # metres: simplification of the coast drawn on the map
SAMPLE_M = 25.0                            # Day 10: the real coast sampled every 25 m
LANDMARKS = [   # pin label, Day 10 station name
    ('Changi Airport', 'Changi Airport'), ('Jurong', 'Jurong East'),
    ('Woodlands', 'Woodlands'), ('Marina Bay', 'Marina Bay'),
]


def merc_y(lat):
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def merc_lat(y):
    return math.degrees(2 * math.atan(math.exp(y)) - math.pi / 2)


def geod_km2(g):
    return abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6


def enc(coords, k=1e5):
    """[[x, y], ...] -> flat delta-encoded ints at 1/k."""
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * k), round(y * k)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def dec(a, k):
    out, x, y = [], 0, 0
    for i in range(0, len(a), 2):
        x += a[i]
        y += a[i + 1]
        out.append((x / k, y / k))
    return out


def score(guess_svy, real_svy):
    """Day 10's coast measures (process.py coast_stats), for a guessed polygon in SVY21."""
    coast = real_svy.exterior
    corners = [Point(c) for c in list(guess_svy.exterior.coords)[:-1]]
    d = np.array([coast.distance(p) for p in corners])
    pts = [coast.interpolate(s) for s in np.arange(0, coast.length, SAMPLE_M)]
    rd = np.array([guess_svy.exterior.distance(p) for p in pts])
    inter, union = guess_svy.intersection(real_svy), guess_svy.union(real_svy)
    return {
        'corners': len(corners), 'mean_m': float(d.mean()), 'at_sea': sum(1 for p in corners if not real_svy.contains(p)),
        'coast_mean_m': float(rd.mean()), 'iou': float(inter.area / union.area),
        'guess_km2': geod_km2(wgs(guess_svy)), 'samples': len(pts),
    }


def main(nmp_path, answer_path, memory_path, out_path):
    nmp = json.load(open(nmp_path, encoding='utf-8'))
    A = json.load(open(answer_path, encoding='utf-8'))
    M = json.load(open(memory_path, encoding='utf-8'))

    by_name, upd = {}, None
    for f in nmp['features']:
        p = f['properties']
        if p['FOLDERPATH'] != 'Layers/Coastal_Outlines' or not f['geometry']:
            continue
        by_name.setdefault(p['NAME'], []).append(shapely.force_2d(shape(f['geometry'])))
        if p['NAME'] == 'SINGAPORE - MAIN ISLAND':
            upd = p.get('FMEL_UPD_D')
    real_ll = orient(by_name['SINGAPORE - MAIN ISLAND'][0])
    real_km2 = geod_km2(real_ll)

    # ---- the main island in SVY21 decimetres: exactly what the page measures against ----
    rs_full = svy(real_ll)
    ext_dm = enc(list(rs_full.exterior.coords)[:-1], 10)
    holes_dm = [enc(list(h.coords)[:-1], 10) for h in rs_full.interiors]
    rs = Polygon(dec(ext_dm, 10), [dec(h, 10) for h in holes_dm])   # the rounded ring the page decodes
    assert rs.is_valid
    cen = rs.centroid

    # ---- Claude's Day 10 outline, re-scored from the rounded ring ----
    ring = [c[:2] for c in A['main_island']['ring']]
    if ring[0] == ring[-1]:
        ring = ring[:-1]
    claude_ll = orient(Polygon(ring))
    claude = score(svy(claude_ll), rs)
    pub = M['stats']['coast']['main']
    check = {k: (claude[k], pub[k]) for k in ('iou', 'mean_m', 'coast_mean_m', 'guess_km2', 'corners', 'at_sea')}
    for k, (mine, theirs) in check.items():
        tol = {'iou': 6e-4, 'mean_m': .1, 'coast_mean_m': 1.0, 'guess_km2': .01}.get(k, 0)
        assert abs(mine - theirs) <= tol, (k, mine, theirs)
    assert abs(real_km2 - pub['real_km2']) < .01, (real_km2, pub['real_km2'])

    # A test outline for the page's scorer: Claude's, scaled 1.08 about its centroid and moved 1.2 km east, 0.6 km south.
    gc = svy(claude_ll).centroid
    test_svy = shapely.transform(svy(claude_ll), lambda c: np.column_stack([gc.x + 1.08 * (c[:, 0] - gc.x) + 1200, gc.y + 1.08 * (c[:, 1] - gc.y) - 600]))
    test = score(test_svy, rs)
    test_ll = list(wgs(test_svy).exterior.coords)[:-1]

    # ---- the coast drawn on the map ----
    simp = lambda g, tol: orient(wgs(svy(g).simplify(tol, preserve_topology=True)))
    main_show = simp(Polygon(real_ll.exterior), SHOW_TOL['main'])
    others = []
    for name, gs in by_name.items():
        if name in ('JOHOR (MALAYSIA)', 'LINKWAY', 'SINGAPORE - MAIN ISLAND'):
            continue
        for g in gs:
            for p in (g.geoms if isinstance(g, MultiPolygon) else [g]):
                q = simp(Polygon(p.exterior), SHOW_TOL['other'])
                if not q.is_empty and q.area > 0:
                    others.append(enc(list(q.exterior.coords)[:-1]))

    # ---- landmarks: Day 10's station rows [name, codes, guess codes, glng, glat, tlng, tlat, err] ----
    st = {r[0]: r for r in M['st']}
    marks = []
    for label, station in LANDMARKS:
        r = st[station]
        marks.append({'label': label, 'station': station, 'codes': r[1], 't': [r[5], r[6]], 'claude': [r[3], r[4]], 'claude_m': r[7]})

    s0, s1 = merc_y(WIN_CLAT) - math.radians(WIN_E - WIN_W) / 3, merc_y(WIN_CLAT) + math.radians(WIN_E - WIN_W) / 3
    window = [WIN_W, round(merc_lat(s0), 6), WIN_E, round(merc_lat(s1), 6)]

    rnd = lambda v: {k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()}
    out = {
        'meta': {
            'coast_source': 'SLA National Map Polygon, Coastal_Outlines, data.gov.sg d_29f066d67df3eae91df8a42f443863c8',
            'coast_updated': upd, 'stations_source': M['meta']['rail_source'],
            'claude_answer_sha256': M['meta']['answer_sha256'], 'model': M['meta']['model'],
        },
        'window': window,
        'truth': {
            'km2': round(real_km2, 4), 'coast_km': round(rs.exterior.length / 1000, 3), 'samples': claude['samples'],
            'vertices': len(ext_dm) // 2, 'holes': len(holes_dm), 'centroid': [round(cen.x, 1), round(cen.y, 1)],
        },
        'sv': {'ext': ext_dm, 'holes': holes_dm},
        'show': {'main': enc(list(main_show.exterior.coords)[:-1]), 'others': others},
        'marks': marks,
        'claude': {'ring': enc(ring), 'day10': rnd({k: pub[k] for k in ('iou', 'guess_km2', 'real_km2', 'mean_m', 'coast_mean_m', 'corners', 'at_sea')})},
        'check': {'claude': rnd(claude), 'test': {'ring': [[round(x, 7), round(y, 7)] for x, y in test_ll], 'score': rnd(test)}},
    }
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, separators=(',', ':'))
    print('window', window)
    print('truth', out['truth'])
    print('claude re-scored vs Day 10:', {k: (round(a, 4), round(b, 4)) for k, (a, b) in check.items()})
    print('test', rnd(test))
    print('marks', marks)
    print('others', len(others), 'main show pts', len(out['show']['main']) // 2)


if __name__ == '__main__':
    main(*sys.argv[1:5])
