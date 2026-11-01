"""Day 25 (Is this a map?): a schematic of Singapore's MRT and LRT network, generated from the
network itself, and the true geography it morphs into.

Requires: Python 3.10+, numpy, shapely>=2, pyproj>=3   (pip install numpy shapely pyproj)
          and layout.py, in this folder.

Inputs (downloaded by build.sh, pinned to one commit):
  sg-rail.geojson         cheeaun/sgraildata, commit d64f9408ef (12 Jul 2026), data/v1/sg-rail.geojson:
                          station points (true positions) and each line's track geometry.
  routes.citymapper.json  the same commit's data/raw/routes.citymapper.json: each line's stops in
                          running order, and the line colours.

The schematic (how the diagram end is made)
  This is not LTA's map. It is generated here from the network alone:
  1. Stations are nodes, neighbouring stations on a line are links. Chains of ordinary stations
     between interchanges, termini and branch points are contracted to one edge each. A few
     ordinary stations are kept as nodes where a chain really bends (Douglas-Peucker on its true
     path, tolerance BEND_TOL_M), plus extra splits so loops and parallel chains stay drawable.
  2. layout.py places those nodes on a grid by multicriteria hill climbing, a simplified version of
     Stott et al., "Automatic metro map layout using multicriteria optimization", IEEE TVCG 17(1),
     2011: every edge octilinear (straight, or one straight and one 45-degree leg), even station
     gaps, few bends, each edge close to its true compass direction, edges kept apart, and lines
     crossing only where they really cross. See layout.py for the cost.
  3. Ordinary stations are spaced evenly along their edge's drawn path. Interchanges are single
     nodes, so every line through one passes through the same point. The finished diagram is
     scaled and centred onto the true positions by least squares (scale and shift only, no rotation).

Output: ../diagram.json. Positions are SVY21 (EPSG:3414) metres, rounded to 1 m. The page draws
them with a fitted affine SVY21 -> WGS84 transform (its worst error is printed and stored).

usage: python -I process.py <sg-rail.geojson> <routes.citymapper.json> <out.json>
"""
import itertools
import json
import math
import os
import re
import sys
import time

import numpy as np
from pyproj import Transformer
from shapely.geometry import LineString, MultiLineString, Point, shape
from shapely.ops import substring

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # layout.py sits beside this file (-I drops it)
from layout import SPACING, Layout  # noqa: E402

TO_SVY = Transformer.from_crs(4326, 3414, always_xy=True)
TO_WGS = Transformer.from_crs(3414, 4326, always_xy=True)
norm = lambda s: re.sub(r'[^a-z0-9]', '', s.lower())

BEND_TOL_M = 900.0     # Douglas-Peucker tolerance for keeping a station as a possible bend
# layout settings (env D25_LAYOUT='{"seed":..}' overrides them, for trying variants)
# seed 11, spread 1.5, anchor 0.02 was the best of a dozen tries (lowest cost with no crowding)
LAYOUT = json.loads(os.environ.get('D25_LAYOUT') or '{"seed": 11, "spread": 1.5, "anchor": 0.02}')

# citymapper route name -> (line code, display name)
LINES = {
    'NS': ('NS', 'North South Line'), 'EW': ('EW', 'East West Line'), 'NE': ('NE', 'North East Line'),
    'CC': ('CC', 'Circle Line'), 'DT': ('DT', 'Downtown Line'), 'TE': ('TE', 'Thomson-East Coast Line'),
    'BPLRT': ('BP', 'Bukit Panjang LRT'), 'SKLRT (East)': ('SK', 'Sengkang LRT'), 'SKLRT (West)': ('SK', 'Sengkang LRT'),
    'PGLRT (East)': ('PG', 'Punggol LRT'), 'PGLRT (West)': ('PG', 'Punggol LRT'),
}
# sg-rail track geometry for each line code
TRACK = {'NS': ['North South Line'], 'EW': ['East West Line'], 'NE': ['North East Line'], 'CC': ['Circle Line'],
         'DT': ['Downtown Line'], 'TE': ['Thomson-East Coast Line'], 'BP': ['Bukit Panjang LRT'],
         'SK': ['Sengkang LRT (East Loop)', 'Sengkang LRT (West Loop)'], 'PG': ['Punggol LRT (East Loop)', 'Punggol LRT (West Loop)']}
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]   # 0 = east, counter-clockwise


def seg_dist(p, q, a, b):
    """Shortest distance between segments pq and ab (2D numpy arrays)."""
    return LineString([p, q]).distance(LineString([a, b]))


def dp_keep(pts, tol):
    """Douglas-Peucker on a polyline: indices of interior points to keep. Closed paths work too."""
    keep = set()

    def rec(i, j):
        if j - i < 2:
            return
        a, b = pts[i], pts[j]
        ab = b - a
        L = np.hypot(*ab)
        best, k = -1.0, -1
        for m in range(i + 1, j):
            d = abs(ab[0] * (pts[m][1] - a[1]) - ab[1] * (pts[m][0] - a[0])) / L if L > 1e-9 else np.hypot(*(pts[m] - a))
            if d > best:
                best, k = d, m
        if best > tol:
            keep.add(k)
            rec(i, k)
            rec(k, j)
    rec(0, len(pts) - 1)
    return keep


def main(rail_path, routes_path, out_path):
    rail = json.load(open(rail_path, encoding='utf-8'))
    routes = json.load(open(routes_path, encoding='utf-8'))

    # ---------------- stations ----------------
    st = []
    key = {}
    for f in rail['features']:
        p = f['properties']
        if p.get('stop_type') != 'station':
            continue
        lng, lat = f['geometry']['coordinates'][:2]
        x, y = TO_SVY.transform(lng, lat)
        key[norm(p['name'])] = len(st)
        st.append({'name': p['name'], 'codes': p['station_codes'], 'lnglat': (lng, lat), 'g': np.array([x, y])})
    N = len(st)
    G = np.array([s['g'] for s in st])

    # ---------------- lines, patterns, edges ----------------
    stop_name = {}
    for s in routes['stops'].values():
        for k in ('id', 'live_code'):
            if k in s:
                stop_name[s[k]] = s['name']
    color, lname, patterns = {}, {}, []
    edges = {}          # (a, b) a<b -> set of line codes
    for r in routes['routes']:
        code, name = LINES[r['name']]
        color[code] = r['color'].upper()
        lname[code] = name
        for p in r['patterns']:
            seq = [key[norm(stop_name[sp['id']])] for sp in p['stop_points']]
            if p.get('is_circular') and seq[0] != seq[-1]:
                seq.append(seq[0])
            patterns.append((code, seq))
            for a, b in zip(seq, seq[1:]):
                if a != b:
                    edges.setdefault((min(a, b), max(a, b)), set()).add(code)
    adj = {i: set() for i in range(N)}
    for a, b in edges:
        adj[a].add(b)
        adj[b].add(a)
    assert all(adj[i] for i in range(N)), 'a station with no line'
    lines_at = {i: set() for i in range(N)}
    for (a, b), ls in edges.items():
        lines_at[a] |= ls
        lines_at[b] |= ls
    terminal = set()
    for code, seq in patterns:
        if seq[0] != seq[-1]:
            terminal |= {seq[0], seq[-1]}
    keyn = {i for i in range(N) if len(adj[i]) != 2 or len(lines_at[i]) > 1 or i in terminal}

    # ---------------- contract chains ----------------
    def chains(keyset):
        seen, out = set(), []
        for s in sorted(keyset):
            for nb in sorted(adj[s]):
                if (min(s, nb), max(s, nb)) in seen:
                    continue
                path = [s, nb]
                seen.add((min(s, nb), max(s, nb)))
                while path[-1] not in keyset:
                    cur, prev = path[-1], path[-2]
                    nxt = [n for n in adj[cur] if n != prev][0]
                    seen.add((min(cur, nxt), max(cur, nxt)))
                    path.append(nxt)
                out.append(path)
        return out

    for _ in range(20):
        paths = chains(keyn)
        added = False
        for path in paths:   # Douglas-Peucker bend candidates
            for k in dp_keep(G[path], BEND_TOL_M):
                if path[k] not in keyn:
                    keyn.add(path[k])
                    added = True
        # a chain that returns to its start, or a second chain between the same two ends, is split
        ends = {}
        for path in paths:
            ends.setdefault(frozenset((path[0], path[-1])), []).append(path)
        for ps in ends.values():
            need = [p for p in ps if p[0] == p[-1]] + sorted([p for p in ps if p[0] != p[-1]], key=len)[1:]
            for p in need:
                if len(p) <= 2:
                    continue
                # split at the station farthest from the chord (or from the start, for a loop)
                a, b = G[p[0]], G[p[-1]]
                d = [np.hypot(*(G[m] - a)) if p[0] == p[-1] else seg_dist(G[m], G[m], a, b) for m in p[1:-1]]
                keyn.add(p[1 + int(np.argmax(d))])
                added = True
        if not added:
            break
    paths = chains(keyn)
    # long LRT chains also keep their middle station, so the loops can be drawn as boxes
    for _ in range(6):
        changed = False
        for p in paths:
            if len(p) - 1 >= 6 and all(code in ('BP', 'SK', 'PG') for code in edges[(min(p[0], p[1]), max(p[0], p[1]))]):
                # long LRT chains: keep the middle station too, so loops read as boxes
                m = p[len(p) // 2]
                if m not in keyn:
                    keyn.add(m)
                    changed = True
        if not changed:
            break
        paths = chains(keyn)

    K = sorted(keyn)
    kidx = {v: i for i, v in enumerate(K)}
    E = []   # contracted edges: (ka, kb, stations along, hops)
    for p in paths:
        E.append((kidx[p[0]], kidx[p[-1]], p))
    print(f'{N} stations, {len(edges)} links, {len(K)} key nodes, {len(E)} contracted edges', file=sys.stderr)

    # geographic positions in units of the median gap
    gap = np.median([np.hypot(*(G[a] - G[b])) for a, b in edges])
    P0 = (G[K] - G[K].mean(axis=0)) / gap

    def sector(e):
        a, b, p = e
        v = P0[b] - P0[a]
        ang = math.degrees(math.atan2(v[1], v[0])) % 360
        return int(round(ang / 45)) % 8

    # ---------------- line walks over contracted edges (for bends) ----------------
    e_of = {}
    for ei, (a, b, p) in enumerate(E):
        for s, t in zip(p, p[1:]):
            e_of[(s, t)] = (ei, +1)
            e_of[(t, s)] = (ei, -1)
    turns = set()
    for code, seq in patterns:
        walk = []
        for s, t in zip(seq, seq[1:]):
            ei, d = e_of[(s, t)]
            if not walk or walk[-1] != (ei, d):
                walk.append((ei, d))
        circ = seq[0] == seq[-1]
        pairs = list(zip(walk, walk[1:])) + ([(walk[-1], walk[0])] if circ and len(walk) > 1 else [])
        for w1, w2 in pairs:
            if w1[0] != w2[0]:
                turns.add((w1, w2))

    # ---------------- the layout (see layout.py) ----------------
    hops = [len(p) - 1 for (_, _, p) in E]
    t0 = time.time()
    # pairs of chains that really cross each other (no shared station) may cross in the diagram too
    may_cross = []
    for e1, e2 in itertools.combinations(range(len(E)), 2):
        l1, l2 = LineString(G[E[e1][2]]), LineString(G[E[e2][2]])
        if not l1.intersects(l2):
            continue
        shared = {E[e1][0], E[e1][1]} & {E[e2][0], E[e2][1]}
        rest = l1.intersection(l2)
        for v in shared:   # meeting at a shared interchange is not a crossing
            rest = rest.difference(Point(G[K[v]]).buffer(60))
        if not rest.is_empty:
            may_cross.append((e1, e2))
    print(f'{len(may_cross)} pairs of chains cross on the ground', file=sys.stderr)
    lay = Layout(P0, [(a, b, h) for (a, b, _), h in zip(E, hops)], sorted(turns), may_cross, **LAYOUT).run(log=lambda m: print(m, file=sys.stderr))
    rep = lay.report()
    if os.environ.get('D25_DEBUG'):
        for e, (a, b, p) in enumerate(E):
            pa, pb = lay.pos[a], lay.pos[b]
            dang = math.degrees(math.atan2(pb[1] - pa[1], pb[0] - pa[0]))
            print(f'edge {e}: {st[K[a]]["name"]} -> {st[K[b]]["name"]} hops {hops[e]} drawn {dang:.0f} true {math.degrees(lay.geo[e]):.0f} '
                  f'cost {lay.edge_cost(e):.1f} pos {pa}->{pb}', file=sys.stderr)
    print(rep, f'{time.time() - t0:.0f}s', file=sys.stderr)
    for e, f in lay.conflicts:
        print('conflict:', [st[K[v]]['name'] for v in E[e][:2]], [st[K[v]]['name'] for v in E[f][:2]], file=sys.stderr)
    assert rep['conflicts'] == 0, 'the layout still has crowding or crossing edges'
    turn_hist = rep['turns_by_45']

    # every station along its edge's drawn polyline, evenly by length (grid units)
    Dg = np.zeros((N, 2))
    dbend = {}          # (s, t) neighbouring stations -> [(fraction along s..t, bend point)]
    spacing = []
    for e, (a, b, p) in enumerate(E):
        pts = np.array(lay.geom[e][0], dtype=float)
        cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
        L, n = cum[-1], len(p) - 1
        def at(d):
            k = min(int(np.searchsorted(cum, d, side='right')) - 1, len(pts) - 2)
            f = (d - cum[k]) / (cum[k + 1] - cum[k])
            return pts[k] + f * (pts[k + 1] - pts[k])
        for i, s_ in enumerate(p):
            Dg[s_] = at(L * i / n)
        for i in range(n):
            d0, d1 = L * i / n, L * (i + 1) / n
            inner = [((cum[k] - d0) / (d1 - d0), pts[k]) for k in range(1, len(pts) - 1) if d0 + 1e-9 < cum[k] < d1 - 1e-9]
            dbend[(p[i], p[i + 1])] = inner
            dbend[(p[i + 1], p[i])] = [(1 - f, q) for f, q in inner[::-1]]
        spacing += [L / n / SPACING] * n
    spacing = np.array(spacing)
    print(f'turns by 45-degree steps {turn_hist}; gap mean {spacing.mean():.3f} sd {spacing.std():.3f} '
          f'min {spacing.min():.3f} max {spacing.max():.3f}', file=sys.stderr)

    # ---------------- fit the diagram onto the true positions (scale + shift) ----------------
    dc, gc = Dg.mean(axis=0), G.mean(axis=0)
    scale = float(((Dg - dc) * (G - gc)).sum() / ((Dg - dc) ** 2).sum())
    Dm = (Dg - dc) * scale + gc
    disp = np.hypot(*(Dm - G).T)

    # ---------------- metrics at the diagram end (the page recomputes these live) ----------------
    links = sorted(edges)
    def bearing_err(Q):
        out = []
        for a, b in links:
            u, v = Q[b] - Q[a], Gr[b] - Gr[a]
            d = math.degrees(math.atan2(u[1], u[0]) - math.atan2(v[1], v[0]))
            out.append(abs((d + 180) % 360 - 180))
        return np.array(out)
    iu = np.triu_indices(N, 1)
    def pd(Q):
        return np.hypot(Q[:, None, 0] - Q[None, :, 0], Q[:, None, 1] - Q[None, :, 1])[iu]
    def rank(v):
        """Ranks with ties averaged (a diagram on a grid has many equal distances)."""
        order = np.argsort(v, kind='stable')
        sv = v[order]
        r = np.empty(len(v))
        i = 0
        while i < len(v):
            j = i
            while j + 1 < len(v) and sv[j + 1] == sv[i]:
                j += 1
            r[order[i:j + 1]] = (i + j) / 2
            i = j + 1
        return r
    # measured on the positions exactly as shipped (whole metres), as the page does
    Gr, Dr = np.round(G), np.round(Dm)
    rg = rank(pd(Gr))
    def spearman(Q):
        return float(np.corrcoef(rank(pd(Q)), rg)[0, 1])
    curve = []
    for t in (0, .25, .5, .75, 1):
        Q = Dr + t * (Gr - Dr)
        b = bearing_err(Q)
        curve.append({'t': t, 'mean_km': round(float(np.hypot(*(Q - Gr).T).mean() / 1000), 4),
                      'bearing_mean_deg': round(float(b.mean()), 3), 'within_22_5': round(float((b <= 22.5).mean()), 4),
                      'spearman': round(spearman(Q), 5)})
    for c in curve:
        print(c, file=sys.stderr)

    # ---------------- true track between neighbouring stations ----------------
    tracks = {}
    for code, names in TRACK.items():
        parts = []
        for f in rail['features']:
            if f['properties'].get('name') in names and 'LineString' in f['geometry']['type']:
                g = shape(f['geometry'])
                for part in (g.geoms if isinstance(g, MultiLineString) else [g]):
                    xy = np.column_stack(TO_SVY.transform(*np.asarray(part.coords)[:, :2].T))
                    parts.append(LineString(xy))
        tracks[code] = parts

    def track_between(a, b, codes):
        pa, pb = Point(G[a]), Point(G[b])
        straight = pa.distance(pb)
        best = None
        for code in sorted(codes):
            for line in tracks[code]:
                if line.distance(pa) > 250 or line.distance(pb) > 250:
                    continue
                sa, sb = line.project(pa), line.project(pb)
                cands = [substring(line, sa, sb)]
                if line.is_ring or Point(line.coords[0]).distance(Point(line.coords[-1])) < 30:
                    # on a loop the short way may wrap past the seam
                    Lr = line.length
                    lo, hi = min(sa, sb), max(sa, sb)
                    c1, c2 = substring(line, hi, Lr), substring(line, 0, lo)
                    wrap = LineString(list(c1.coords) + list(c2.coords)[1:])
                    if sa > sb:
                        wrap = LineString(list(wrap.coords)[::-1])
                    cands.append(LineString(list(wrap.coords)[::-1]) if sa < sb else wrap)
                for c in cands:
                    if c.length < 1:
                        continue
                    xy = np.asarray(c.coords)
                    if np.hypot(*(xy[0] - G[a])) > np.hypot(*(xy[-1] - G[a])):
                        xy = xy[::-1]
                    ratio = c.length / max(straight, 1)
                    if ratio < 4 and (best is None or c.length < best[0]):
                        best = (c.length, xy)
        if best is None:
            return None
        return LineString(best[1])

    # Each link is sampled at the same fractions of its length on the diagram and on the ground,
    # including the exact fraction of any diagram bend, so the page can blend point by point.
    to_m = lambda q: (np.asarray(q) - dc) * scale + gc
    E_out, fallback = [], 0
    code_list = list(color.keys())
    for a, b in links:
        line = track_between(a, b, edges[(a, b)])
        if line is None:
            fallback += 1
            line = LineString([G[a], G[b]])
        n = max(2, min(24, int(math.ceil(line.length / 120)) + 1))
        bends = dbend[(a, b)]
        fr = sorted(set([i / (n - 1) for i in range(n)] + [f for f, _ in bends]))
        fr = [f for k, f in enumerate(fr) if k == 0 or f - fr[k - 1] > 1e-6]
        dpts = [Dm[a]] + [to_m(q) for _, q in bends] + [Dm[b]]
        dfr = [0.0] + [f for f, _ in bends] + [1.0]
        geo, dia = [], []
        for f in fr[1:-1]:
            x, y = line.interpolate(f, normalized=True).coords[0]
            geo += [int(round(x)), int(round(y))]
            k = max(i for i in range(len(dfr) - 1) if dfr[i] <= f + 1e-12)
            u = (f - dfr[k]) / (dfr[k + 1] - dfr[k])
            q = dpts[k] + u * (dpts[k + 1] - dpts[k])
            dia += [int(round(q[0])), int(round(q[1]))]
        E_out.append([a, b, [code_list.index(c) for c in sorted(edges[(a, b)], key=code_list.index)], geo, dia])
    print(f'track found for {len(links) - fallback} of {len(links)} links', file=sys.stderr)

    # ---------------- each line as polylines of station indices ----------------
    L_out = []
    for code in code_list:
        ladj = {}
        for (a, b), ls in edges.items():
            if code in ls:
                ladj.setdefault(a, set()).add(b)
                ladj.setdefault(b, set()).add(a)
        used, polys = set(), []
        starts = sorted([v for v in ladj if len(ladj[v]) != 2]) + sorted(ladj)
        for s in starts:
            for nb in sorted(ladj[s]):
                if (min(s, nb), max(s, nb)) in used:
                    continue
                path = [s, nb]
                used.add((min(s, nb), max(s, nb)))
                while len(ladj[path[-1]]) == 2:
                    nxt = [n for n in ladj[path[-1]] if (min(path[-1], n), max(path[-1], n)) not in used]
                    if not nxt:
                        break
                    used.add((min(path[-1], nxt[0]), max(path[-1], nxt[0])))
                    path.append(nxt[0])
                polys.append(path)
        L_out.append([code, lname[code], color[code], polys])

    # ---------------- affine SVY21 -> WGS84 for drawing ----------------
    gx, gy = np.meshgrid(np.linspace(G[:, 0].min() - 15000, G[:, 0].max() + 15000, 25), np.linspace(G[:, 1].min() - 15000, G[:, 1].max() + 15000, 25))
    gx, gy = gx.ravel(), gy.ravel()
    lng, lat = TO_WGS.transform(gx, gy)
    Amat = np.column_stack([gx, gy, np.ones_like(gx)])
    cl = np.linalg.lstsq(Amat, lng, rcond=None)[0]
    ct = np.linalg.lstsq(Amat, lat, rcond=None)[0]
    res = max(np.abs(Amat @ cl - lng).max() * 111320, np.abs(Amat @ ct - lat).max() * 110574)

    S_out = []
    for i, s in enumerate(st):
        S_out.append([s['name'], s['codes'], int(round(G[i, 0])), int(round(G[i, 1])), int(round(Dm[i, 0])), int(round(Dm[i, 1]))])
    worst = int(np.argmax(disp))
    out = {
        'meta': {
            'source': 'cheeaun/sgraildata, commit d64f9408ef (12 Jul 2026): data/v1/sg-rail.geojson and data/raw/routes.citymapper.json',
            'method': 'Octilinear multicriteria hill climbing on a grid after Stott et al. (2011), simplified (layout.py)',
            'stations': N, 'links': len(links), 'key_nodes': len(K), 'contracted_edges': len(E),
            'turns_by_45': turn_hist, 'edges_with_a_bend': rep['edges_with_a_bend'], 'gap_units': {'mean': round(float(spacing.mean()), 4), 'sd': round(float(spacing.std()), 4),
                                                    'min': round(float(spacing.min()), 4), 'max': round(float(spacing.max()), 4)},
            'fit_scale_m_per_unit': round(scale, 2), 'median_true_gap_m': round(float(gap), 1),
            'affine_max_err_m': round(float(res), 3),
            'diagram_end': curve[0], 'curve': curve,
            'most_moved': [st[worst]['name'], round(float(disp[worst]) / 1000, 3)],
            'least_moved': [st[int(np.argmin(disp))]['name'], round(float(disp.min()) / 1000, 3)],
            'track_fallback_links': fallback,
        },
        'aff': [float(v) for v in cl] + [float(v) for v in ct],
        'S': S_out,
        'L': L_out,
        'E': E_out,
    }
    with open(out_path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, separators=(',', ':'), ensure_ascii=False)
    print(json.dumps(out['meta'], indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:4])
