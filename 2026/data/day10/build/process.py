"""Day 10 (Prompting only): score Claude's from-memory Singapore against the real one.

Requires: Python 3.10+, shapely>=2, pyproj>=3, numpy  (pip install shapely pyproj numpy)

Inputs (see build.sh, which downloads the raw files first):
  answer.json            Claude's answer, written from memory before any data was opened.
                         Read only. Never edited.
  sg-rail.geojson        cheeaun/sgraildata v5.1.0 (commit d64f9408ef, 12 Jul 2026):
                         184 MRT/LRT station points (LTA TrainStation points).
  routes.citymapper.json the same commit's data/raw/routes.citymapper.json: each line's stops
                         in running order (used to check the station order).
  nmp.geojson            SLA National Map Polygon, data.gov.sg d_29f066d67df3eae91df8a42f443863c8
                         (layer Coastal_Outlines: "SINGAPORE - MAIN ISLAND", the islands, Johor).

Output: memory.js (window.DAY10), the compact file the page loads, and transcript.js beside it. Coordinates are integers of 1e-5 degree,
delta-encoded per ring or list. All distances are metres on the WGS84 ellipsoid (station errors,
pyproj.Geod) or in SVY21 (EPSG:3414) metres for distances to a coastline; all areas are
geodesic km2 on WGS84.

usage: python -I process.py <answer.json> <sg-rail.geojson> <routes.citymapper.json> <nmp.geojson> <out.json>
"""
import hashlib
import json
import math
import os
import re
import sys

import numpy as np
from pyproj import Geod, Transformer
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.geometry.polygon import orient

GEOD = Geod(ellps='WGS84')
TO_SVY = Transformer.from_crs(4326, 3414, always_xy=True)
TO_WGS = Transformer.from_crs(3414, 4326, always_xy=True)
def _tf(t):
    return lambda g: shapely.transform(g, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


svy, wgs = _tf(TO_SVY), _tf(TO_WGS)
norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())

ISLANDS = {   # name in the answer -> NAME in the SLA layer
    'Sentosa': 'SENTOSA', 'Pulau Ubin': 'PULAU UBIN', 'Pulau Tekong': 'PULAU TEKONG', 'Jurong Island': 'JURONG ISLAND',
}
MORPH_TOL = {'main': 20.0, 'island': 12.0}   # metres: simplification of the real coast drawn on the page
OTHER_TOL = 12.0


def geod_km2(g):
    """Geodesic area (km2) of a lon/lat (Multi)Polygon, holes subtracted."""
    return abs(GEOD.geometry_area_perimeter(g)[0]) / 1e6


def enc(coords, k=1e5):
    """[[lng, lat], ...] -> flat delta-encoded ints."""
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * k), round(y * k)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def ring_xy(poly):
    return np.asarray(poly.exterior.coords)[:-1, :2]


def largest(g):
    return max(g.geoms, key=lambda p: p.area) if isinstance(g, MultiPolygon) else g


def morph_pairs(guess_ll, real_ll):
    """Pair every vertex of a guessed ring with a point of the real ring, keeping both in order.

    Both rings are anticlockwise lon/lat polygons. Every guessed corner is assigned to a real
    vertex by dynamic programming (monotone along both rings, total SVY21 distance minimal,
    every starting offset tried). The real vertices between two assigned ones are paired with
    points spread along the guessed edge between those two corners, in proportion to distance
    along the real coast. Returns two equal-length lists of [lng, lat]: start (the guess, with
    extra points on its straight edges) and end (the real coast).
    """
    G = np.array([TO_SVY.transform(x, y) for x, y in ring_xy(guess_ll)])
    R = np.array([TO_SVY.transform(x, y) for x, y in ring_xy(real_ll)])
    n, M = len(G), len(R)
    D = np.hypot(G[:, None, 0] - R[None, :, 0], G[:, None, 1] - R[None, :, 1])   # n x M
    best = None
    for j0 in range(M):
        idx = (np.arange(M) + j0) % M          # real vertices in order, starting at j0
        C = np.full(M, np.inf)
        C[0] = D[0, j0]
        back = []
        ar = np.arange(M)
        for i in range(1, n):
            run = np.minimum.accumulate(C)
            # where the running minimum was last reached, for backtracking
            arg = np.maximum.accumulate(np.where(C == run, ar, 0))
            back.append(arg)
            C = run + D[i, idx]
        total = C.min()
        if best is None or total < best[0]:
            j = int(C.argmin())
            path = [j]
            for arg in reversed(back):
                j = int(arg[j])
                path.append(j)
            path.reverse()
            best = (total, j0, path)
    _, j0, path = best
    # walk the pairs
    Rl = np.asarray(real_ll.exterior.coords)[:-1, :2]
    Gl = ring_xy(guess_ll)
    seg = np.hypot(*np.diff(np.vstack([R, R[:1]]), axis=0).T)   # real edge k -> k+1 (SVY21 m)
    start, end = [], []
    path_abs = [j0 + p for p in path] + [j0 + M]
    for i in range(n):
        a, b = path_abs[i], path_abs[i + 1]
        g0, g1 = Gl[i], Gl[(i + 1) % n]
        L = sum(seg[k % M] for k in range(a, b))
        acc = 0.0
        for k in range(a, b):
            f = acc / L if L > 0 else 0.0
            start.append([g0[0] + f * (g1[0] - g0[0]), g0[1] + f * (g1[1] - g0[1])])
            end.append(list(Rl[k % M]))
            acc += seg[k % M]
        if a == b:   # two guessed corners on the same real vertex: keep the corner anyway
            start.append(list(g0))
            end.append(list(Rl[a % M]))
    return start, end


def coast_stats(guess_ll, real_ll):
    """Distances between a guessed outline and the real coast, in SVY21 metres."""
    gs, rs = svy(guess_ll), svy(real_ll)
    coast = rs.exterior
    corners = [Point(c) for c in list(gs.exterior.coords)[:-1]]
    d = np.array([coast.distance(p) for p in corners])
    at_sea = sum(1 for p in corners if not rs.contains(p))
    # the other way round: every 25 m of real coast, its distance to the guessed outline
    L = coast.length
    pts = [coast.interpolate(s) for s in np.arange(0, L, 25.0)]
    rd = np.array([gs.exterior.distance(p) for p in pts])
    k = int(rd.argmax())
    far = wgs(pts[k])
    # the three worst stretches of real coast, at least 6 km apart
    worst = []
    for i in np.argsort(-rd):
        if len(worst) == 3:
            break
        if all(pts[i].distance(pts[j]) >= 6000 for j in worst):
            worst.append(int(i))
    far3 = [[round(wgs(pts[i]).x, 5), round(wgs(pts[i]).y, 5), round(float(rd[i]))] for i in worst]
    # each guessed corner as [lng, lat, metres to the real coast], for region checks
    corner_ll = [[round(x, 5), round(y, 5), round(float(dd), 1)] for (x, y), dd in zip(list(guess_ll.exterior.coords)[:-1], d)]
    inter, union = gs.intersection(rs), gs.union(rs)
    return {
        'corners': len(corners), 'mean_m': float(d.mean()), 'median_m': float(np.median(d)),
        'max_m': float(d.max()), 'min_m': float(d.min()), 'at_sea': at_sea,
        'corners_ll': corner_ll,
        'coast_mean_m': float(rd.mean()), 'coast_max_m': float(rd.max()), 'coast_far': [far.x, far.y], 'far3': far3,
        'iou': float(inter.area / union.area),
        'guess_km2': geod_km2(guess_ll), 'real_km2': geod_km2(real_ll),
        'real_coast_km': coast.length / 1000, 'guess_coast_km': gs.exterior.length / 1000,
    }


def main(answer_path, rail_path, routes_path, nmp_path, out_path):
    raw = open(answer_path, 'rb').read()
    A = json.loads(raw)
    rail = json.load(open(rail_path, encoding='utf-8'))
    routes = json.load(open(routes_path, encoding='utf-8'))
    nmp = json.load(open(nmp_path, encoding='utf-8'))

    # ---------------- stations ----------------
    truth = {}
    for f in rail['features']:
        p = f['properties']
        if p.get('stop_type') != 'station':
            continue
        k = norm(p['name'])
        assert k not in truth, p['name']
        truth[k] = {'name': p['name'], 'codes': p['station_codes'].split('-'), 'lnglat': f['geometry']['coordinates'][:2]}
    guess = {norm(s['name']): s for s in A['stations']}
    assert len(guess) == len(A['stations'])
    matched = [k for k in guess if k in truth]
    invented = [guess[k]['name'] for k in guess if k not in truth]
    forgotten = sorted(truth[k]['name'] for k in truth if k not in guess)

    rows = []
    for k in guess:
        g = guess[k]
        if k not in truth:
            continue
        t = truth[k]
        az, _, dist = GEOD.inv(g['lnglat'][0], g['lnglat'][1], t['lnglat'][0], t['lnglat'][1])
        rows.append({'name': t['name'], 'gcodes': g['codes'], 'tcodes': t['codes'], 'g': g['lnglat'], 't': t['lnglat'], 'err': dist, 'az': az})
    for name in forgotten:
        t = truth[norm(name)]
        rows.append({'name': t['name'], 'gcodes': [], 'tcodes': t['codes'], 'g': None, 't': t['lnglat'], 'err': None, 'az': None})
    errs = np.array([r['err'] for r in rows if r['err'] is not None])
    order = sorted([r for r in rows if r['err'] is not None], key=lambda r: -r['err'])
    code_changes = [[r['name'], r['gcodes'], r['tcodes']] for r in rows if r['g'] and sorted(r['gcodes']) != sorted(r['tcodes'])]

    def med(sel):
        v = [r['err'] for r in rows if r['err'] is not None and sel(r)]
        return {'n': len(v), 'median_m': float(np.median(v)), 'mean_m': float(np.mean(v))} if v else None
    pref = lambda r, ps: any(re.match(rf'^({"|".join(ps)})\d', c) for c in r['tcodes'])
    city_hall = truth['cityhall']['lnglat']
    near = lambda r, km: GEOD.inv(r['t'][0], r['t'][1], city_hall[0], city_hall[1])[2] <= km * 1000
    groups = {
        'all': med(lambda r: True),
        'centre_3km': med(lambda r: near(r, 3)),
        'old_lines_ns_ew': med(lambda r: pref(r, ['NS', 'EW'])),
        'new_lines_dt_te': med(lambda r: pref(r, ['DT', 'TE'])),
        'tuas_ew30_33': med(lambda r: any(c in ('EW30', 'EW31', 'EW32', 'EW33') for c in r['tcodes'])),
        'lrt': med(lambda r: pref(r, ['BP', 'SE', 'SW', 'PE', 'PW'])),
        'north_lat_1_42': med(lambda r: r['t'][1] >= 1.42),
    }
    by_line = {}
    for lp in ['NS', 'EW', 'CG', 'NE', 'CC', 'DT', 'TE', 'BP', 'SE', 'SW', 'PE', 'PW']:
        by_line[lp] = med(lambda r, lp=lp: pref(r, [lp]))
    bands = {f'within_{b}m': int((errs <= b).sum()) for b in (50, 100, 250, 500, 1000)}

    # ---------------- station order ----------------
    cm_stops = {s['live_code'] if 'live_code' in s else s['id']: s for s in (routes['stops'] if isinstance(routes['stops'], list) else routes['stops'].values())}
    stop_name = {}
    for s in (routes['stops'] if isinstance(routes['stops'], list) else routes['stops'].values()):
        for key in ('id', 'live_code'):
            if key in s:
                stop_name[s[key]] = s['name']
    real_pairs = set()
    for r in routes['routes']:
        for p in r['patterns']:
            ids = [sp['id'] for sp in p['stop_points']]
            names = [norm(stop_name[i]) for i in ids]
            for a, b in zip(names, names[1:]):
                real_pairs.add(frozenset((a, b)))
            if p.get('is_circular') and names[0] != names[-1]:
                real_pairs.add(frozenset((names[-1], names[0])))
    guess_pairs = set()
    for ln in A['lines']:
        ns = [norm(x) for x in ln['order']]
        for a, b in zip(ns, ns[1:]):
            guess_pairs.add(frozenset((a, b)))
    pairs_right = sorted(tuple(sorted(p)) for p in guess_pairs if p in real_pairs)
    pairs_wrong = sorted(tuple(sorted(p)) for p in guess_pairs if p not in real_pairs)
    pairs_missed = sorted(tuple(sorted(p)) for p in real_pairs if p not in guess_pairs)

    # ---------------- coastlines ----------------
    by_name = {}
    for f in nmp['features']:
        p = f['properties']
        if p['FOLDERPATH'] != 'Layers/Coastal_Outlines' or not f['geometry']:
            continue
        g = shape(f['geometry'])
        g = shapely.force_2d(g)
        by_name.setdefault(p['NAME'], []).append(g)
    main_feat = by_name['SINGAPORE - MAIN ISLAND'][0]
    real_main = orient(main_feat)
    guess_main = orient(Polygon([c[:2] for c in A['main_island']['ring']]))
    assert guess_main.is_valid
    coast = {'main': coast_stats(guess_main, real_main)}
    REGIONS = {   # parts of the coast the answer's self-assessment names
        'tuas': lambda x, y: x < 103.66, 'north': lambda x, y: y >= 1.42,
        'changi': lambda x, y: x >= 103.97, 'city': lambda x, y: 103.80 <= x <= 103.90 and y < 1.31,
    }
    coast['main']['regions'] = {}
    for k, fn in REGIONS.items():
        v = [c[2] for c in coast['main']['corners_ll'] if fn(c[0], c[1])]
        coast['main']['regions'][k] = {'n': len(v), 'mean_m': round(float(np.mean(v)), 1), 'median_m': round(float(np.median(v)), 1)}
    pieces = []
    simp = lambda g, tol: orient(wgs(svy(g).simplify(tol, preserve_topology=True)))
    s0, e0 = morph_pairs(guess_main, simp(Polygon(real_main.exterior), MORPH_TOL['main']))
    pieces.append({'name': 'Singapore main island', 'g': enc(s0), 'r': enc(e0)})
    used = {main_feat.wkb}   # the real polygons the morph draws; every other piece of land is drawn as is
    for ans in A['islands']:
        sla = ISLANDS[ans['name']]
        feat = max(by_name[sla], key=lambda g: g.area)
        real = orient(largest(feat))
        used.add(largest(feat).wkb)
        gpoly = orient(Polygon([c[:2] for c in ans['ring']]))
        st = coast_stats(gpoly, real)
        st['real_km2_all_parts'] = sum(geod_km2(g) for g in by_name[sla])
        gc, rc = svy(gpoly).centroid, svy(Polygon(real.exterior)).centroid
        st['centroid_off_m'] = gc.distance(rc)
        coast[ans['name']] = st
        s, e = morph_pairs(gpoly, simp(Polygon(real.exterior), MORPH_TOL['island']))
        pieces.append({'name': ans['name'], 'g': enc(s), 'r': enc(e)})

    # land the guess left out, and sea it filled in (main island only)
    gm, rm = svy(guess_main), svy(real_main)
    forgot_land, made_land = rm.difference(gm), gm.difference(rm)
    def polys(g, tol=8.0, min_m2=2000):
        out = []
        for p in (g.geoms if hasattr(g, 'geoms') else [g]):
            if p.area < min_m2:
                continue
            q = wgs(p.simplify(tol, preserve_topology=True))
            out.append([enc(list(q.exterior.coords)[:-1])] + [enc(list(h.coords)[:-1]) for h in q.interiors])
        return out
    coast['main']['forgot_land_km2'] = geod_km2(wgs(forgot_land))
    coast['main']['made_land_km2'] = geod_km2(wgs(made_land))

    # every other piece of Singapore land (not Johor, not the link bridges), for the real view
    others = []
    for name, gs in by_name.items():
        if name in ('JOHOR (MALAYSIA)', 'LINKWAY'):
            continue
        for g in gs:
            for p in (g.geoms if isinstance(g, MultiPolygon) else [g]):
                if p.wkb in used:
                    continue
                q = orient(wgs(svy(p).simplify(OTHER_TOL, preserve_topology=True)))
                if not q.is_empty and q.area > 0:
                    others.append(enc(list(q.exterior.coords)[:-1]))

    # ---------------- output ----------------
    st_out = []
    for r in sorted(rows, key=lambda r: (r['err'] is None, -(r['err'] or 0))):
        st_out.append([r['name'], '-'.join(r['tcodes']), '-'.join(r['gcodes']),
                       round(r['g'][0], 5) if r['g'] else None, round(r['g'][1], 5) if r['g'] else None,
                       round(r['t'][0], 6), round(r['t'][1], 6),
                       round(r['err'], 1) if r['err'] is not None else None])
    idx = {norm(s[0]): i for i, s in enumerate(st_out)}
    colors = {r['name']: r['color'] for r in routes['routes']}
    LINE_COLOR = {'NSL': colors['NS'], 'EWL': colors['EW'], 'CGL': colors['EW'], 'NEL': colors['NE'], 'CCL': colors['CC'], 'CE': colors['CC'],
                  'DTL': colors['DT'], 'TEL': colors['TE'], 'BPL': colors['BPLRT'], 'SKE': colors['SKLRT (East)'], 'SKW': colors['SKLRT (West)'],
                  'PGE': colors['PGLRT (East)'], 'PGW': colors['PGLRT (West)']}
    lines_out = [[ln['code'], ln['name'], LINE_COLOR[ln['code']], [idx[norm(x)] for x in ln['order']]] for ln in A['lines']]
    missed_out = [[idx[a], idx[b]] for a, b in pairs_missed]
    out = {
        'meta': {
            'answer_sha256': hashlib.sha256(raw).hexdigest(),
            'model': A['model'],
            'truth_stations': len(truth), 'guessed_stations': len(guess),
            'rail_source': 'cheeaun/sgraildata v5.1.0 (commit d64f9408ef, 12 Jul 2026)',
            'coast_source': 'SLA National Map Polygon, Coastal_Outlines, data.gov.sg d_29f066d67df3eae91df8a42f443863c8',
        },
        'stats': {
            'matched': len(matched), 'invented': invented, 'forgotten': forgotten,
            'median_m': float(np.median(errs)), 'mean_m': float(errs.mean()),
            'best': [order[-1]['name'], order[-1]['err']], 'worst': [order[0]['name'], order[0]['err']],
            'bands': bands, 'groups': groups, 'by_line': by_line,
            'pairs': {'guessed': len(guess_pairs), 'right': len(pairs_right), 'wrong': [list(p) for p in pairs_wrong],
                      'missed': [list(p) for p in pairs_missed], 'real': len(real_pairs)},
            'code_changes': code_changes,
            'coast': {k: {kk: (round(vv, 4) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in coast.items()},
        },
        'st': st_out,
        'lines': lines_out,
        'missed': missed_out,
        'morph': pieces,
        'others': others,
        'forgot': polys(forgot_land), 'made': polys(made_land),
    }
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('window.DAY10 = ' + json.dumps(out, separators=(',', ':'), ensure_ascii=False) + ';\n')
    # the transcript, verbatim, as a script beside it (the page hashes answer to check the seal)
    here = os.path.dirname(os.path.abspath(answer_path))
    transcript = {'prompt': open(os.path.join(here, 'prompt.md'), encoding='utf-8').read().replace('\r\n', '\n'),
                  'answer': open(answer_path, encoding='utf-8', newline='').read()}
    with open(os.path.join(os.path.dirname(os.path.abspath(out_path)), 'transcript.js'), 'w', encoding='utf-8', newline='\n') as fh:
        fh.write('window.DAY10_TRANSCRIPT = ' + json.dumps(transcript, separators=(',', ':')) + ';\n')
    s = out['stats']
    print(json.dumps({k: s[k] for k in ('matched', 'invented', 'forgotten', 'median_m', 'mean_m', 'best', 'worst', 'bands')}, indent=1))
    print(json.dumps(s['groups'], indent=1))
    print(json.dumps(s['by_line']))
    print('pairs', s['pairs'])
    print('codes', s['code_changes'])
    for k, v in s['coast'].items():
        print(k, {kk: vv for kk, vv in v.items() if kk != 'corners_ll'})
    print('worst 12:', [(r['name'], round(r['err'])) for r in order[:12]])
    print('best 8:', [(r['name'], round(r['err'])) for r in order[-8:]])
    print('morph sizes', [(p['name'], len(p['g']) // 2) for p in pieces], 'others', len(others))


if __name__ == '__main__':
    main(*sys.argv[1:6])
