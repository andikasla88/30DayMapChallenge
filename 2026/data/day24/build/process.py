"""Day 24 Network: build a small walking graph for two showcase areas, with every metre
marked as under an LTA covered linkway, under some other mapped shelter, or in the open.
Usage: python -I process.py <raw-dir> <out-dir>      (run fetch.py first)
Requires: shapely>=2 pyproj pyshp osmium   (pip install shapely pyproj pyshp osmium)

Method
1. LTA covered linkways (roof outlines, SVY21 polygons). Island-wide length: touching roofs
   are merged, and each merged outline is read as a strip of even width, so its length L
   solves  L * w = area  and  L + w = perimeter / 2.
2. OpenStreetMap walking network: footways, paths, steps, corridors, cycleways, tracks and
   every road a person may walk along (no motorways, trunk roads, road tunnels, foot=no,
   or private access; no road whose pavements are mapped as separate footways, since those
   footways are where people walk). Ways are split where they share nodes, so the graph has
   real junctions.
3. Each OSM segment is cut where it enters or leaves a linkway roof (roof outline grown by
   2 m, to allow for the small offsets between OSM and LTA's survey). The part inside is
   "LTA linkway". Other OSM ways tagged covered, arcade, tunnel, building passage or indoor
   are "other shelter". Everything else is "open".
4. Linkway roofs with less than 40% of their length matched by an OSM way get a centre line
   (from a Voronoi diagram of the outline), joined to the nearest OSM node at each end.
5. Only the largest connected piece of each area's network is kept; chains of nodes are
   collapsed into edges, thinned by 0.4 m, and coded compactly for the page.
6. Presets: MRT/LRT station or exit -> HDB block pairs, routed here with the page's own
   weights so the page and this script agree (the page re-routes them in the browser).
"""
import json, math, os, re, sys, heapq, collections
import osmium, shapefile, shapely
from shapely.geometry import shape, box, LineString, Point, MultiPoint, MultiLineString
from shapely.ops import unary_union
from shapely import STRtree
from pyproj import Transformer

RAW, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
TO_M = Transformer.from_crs(4326, 3414, always_xy=True)
TO_LL = Transformer.from_crs(3414, 4326, always_xy=True)

AREAS = [
    {'id': 'ne', 'name': 'Sengkang & Punggol', 'bbox': (103.878, 1.379, 103.922, 1.414), 'dest': 'hdb'},
    {'id': 'cbd', 'name': 'CBD & Chinatown', 'bbox': (103.838, 1.271, 103.862, 1.300), 'dest': 'food'},
]
TOL = 2.0          # m: roof outline grown by this much
WET = 5            # the page's default: an open metre counts as 5
SIMPLIFY = 0.4     # m
WALK = {'footway', 'path', 'pedestrian', 'steps', 'corridor', 'living_street', 'residential', 'service',
        'unclassified', 'tertiary', 'secondary', 'primary', 'cycleway', 'track', 'tertiary_link',
        'secondary_link', 'primary_link', 'elevator', 'road'}
PATHS = {'footway', 'path', 'pedestrian', 'steps', 'corridor', 'cycleway', 'track', 'elevator'}
BIG_ROADS = {'tertiary', 'secondary', 'primary', 'tertiary_link', 'secondary_link', 'primary_link'}


def strip_len(p):
    a, h = p.area, p.length / 2
    return (h + math.sqrt(max(h * h - 4 * a, 0))) / 2


def sheltered_tag(t):
    return (t.get('covered') in ('yes', 'arcade', 'colonnade') or t.get('tunnel') in ('yes', 'building_passage', 'covered')
            or t.get('indoor') in ('yes', 'corridor') or t.get('highway') == 'corridor')


# ---------- 1. linkways ----------
r = shapefile.Reader(os.path.join(RAW, 'CoveredLinkWay', 'CoveredLinkWay.shp'))
roofs = [shape(s.__geo_interface__).buffer(0) for s in r.shapes()]
roofs = [p for p in roofs if not p.is_empty]
merged = unary_union(roofs)
merged_parts = list(merged.geoms) if hasattr(merged, 'geoms') else [merged]
island = {
    'roofs': len(roofs),
    'km': round(sum(strip_len(p) for p in merged_parts) / 1000, 1),
    'km_unmerged': round(sum(strip_len(p) for p in roofs) / 1000, 1),
    'area_m2': round(merged.area),
    'median_width_m': round(sorted(p.area / strip_len(p) for p in merged_parts if strip_len(p) > 0)[len(merged_parts) // 2], 2),
}
print('island', island)

# ---------- 2. OSM ----------
ways, stations, entrances, blocks, stops, food = [], [], [], [], [], []
LO = min(a['bbox'][0] for a in AREAS) - .01, min(a['bbox'][1] for a in AREAS) - .01
HI = max(a['bbox'][2] for a in AREAS) + .01, max(a['bbox'][3] for a in AREAS) + .01
inb = (lambda lon, lat: LO[0] <= lon <= HI[0] and LO[1] <= lat <= HI[1])


class H(osmium.SimpleHandler):
    def way(self, w):
        t = w.tags
        hw = t.get('highway')
        if hw not in WALK or t.get('area') == 'yes':
            return
        foot, acc = t.get('foot'), t.get('access')
        if foot == 'no' or (acc in ('no', 'private') and foot not in ('yes', 'designated', 'permissive')):
            return
        if hw in BIG_ROADS and t.get('tunnel') == 'yes' and foot not in ('yes', 'designated'):
            return
        if hw not in PATHS and foot not in ('yes', 'designated') and not walk_along(t, hw):
            return
        try:
            nodes = [(n.ref, n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not any(inb(lon, lat) for _, lon, lat in nodes):
            return
        ways.append((w.id, hw, sheltered_tag(t), nodes))

    def node(self, n):
        t = n.tags
        lon, lat = n.location.lon, n.location.lat
        if not inb(lon, lat):
            return
        if t.get('railway') == 'station' and t.get('name'):
            stations.append({'name': t.get('name'), 'ref': t.get('ref', ''), 'lon': lon, 'lat': lat,
                             'lrt': t.get('station') == 'light_rail' or (t.get('ref', '')[:2] in ('SE', 'SW', 'PE', 'PW'))})
        elif t.get('railway') == 'subway_entrance':
            entrances.append({'ref': t.get('ref', ''), 'name': t.get('name', ''), 'lon': lon, 'lat': lat})
        elif t.get('railway') == 'stop' and (t.get('subway') == 'yes' or t.get('train') == 'yes') and t.get('name'):
            stops.append({'name': t.get('name'), 'lon': lon, 'lat': lat, 'lrt': False})
        if is_food(t):
            food.append({'name': t['name'], 'lon': lon, 'lat': lat})

    def area(self, a):
        t = a.tags
        hdb = t.get('residential', '').lower() == 'hdb' and 'addr:housenumber' in t and 'addr:street' in t
        if not hdb and not is_food(t):
            return
        try:
            ring = next(iter(a.outer_rings()))
            pts = [(n.lon, n.lat) for n in ring][:-1]
        except Exception:
            return
        lon = sum(p[0] for p in pts) / len(pts); lat = sum(p[1] for p in pts) / len(pts)
        if not inb(lon, lat):
            return
        if hdb:
            blocks.append({'blk': t['addr:housenumber'], 'street': t['addr:street'], 'lon': lon, 'lat': lat})
        else:
            food.append({'name': t['name'], 'lon': lon, 'lat': lat})


def walk_along(t, hw):
    """A road whose pavements are mapped as their own footways (sidewalk=separate), or a big road
    with no pavement, is left out: people walk on those footways, not down the middle of the road."""
    both = t.get('sidewalk:both') or t.get('sidewalk')
    left = t.get('sidewalk:left') or (both if both in ('separate', 'no', 'none') else None)
    right = t.get('sidewalk:right') or (both if both in ('separate', 'no', 'none') else None)
    if both in ('yes', 'both', 'left', 'right') or left == 'yes' or right == 'yes':
        return True
    sides = {left, right} - {None}
    if 'separate' in sides:
        return False
    if sides and sides <= {'no', 'none'} and hw in BIG_ROADS:
        return False
    return True


def is_food(t):
    nm = t.get('name', '')
    return nm.endswith(('Food Centre', 'Hawker Centre')) or nm == 'Lau Pa Sat'


H().apply_file(os.path.join(RAW, 'singapore-latest.osm.pbf'), locations=True)
osm_time = osmium.io.Reader(os.path.join(RAW, 'singapore-latest.osm.pbf'), osmium.osm.osm_entity_bits.NOTHING).header().get('osmosis_replication_timestamp')
print('ways', len(ways), 'stations', len(stations), 'entrances', len(entrances), 'hdb blocks', len(blocks))


# ---------- 3-5. per area ----------
def centerline(poly):
    """Medial axis of a thin roof outline, spurs pruned."""
    w = poly.area / max(strip_len(poly), 1)
    ring_pts = []
    for ring in [poly.exterior] + list(poly.interiors):
        ring_pts += list(LineString(ring.coords).segmentize(0.8).coords)
    edges = shapely.voronoi_polygons(MultiPoint(ring_pts), only_edges=True)
    inner = [g for g in getattr(edges, 'geoms', [edges]) if poly.contains(g)]
    if not inner:
        return []
    lines = list(getattr(shapely.line_merge(MultiLineString(inner)), 'geoms', []))
    if not lines:
        lines = [shapely.line_merge(MultiLineString(inner))]
    for _ in range(4):   # prune short dangling spurs
        deg = collections.Counter()
        for l in lines:
            deg[tuple(round(c, 3) for c in l.coords[0])] += 1
            deg[tuple(round(c, 3) for c in l.coords[-1])] += 1
        keep = []
        for l in lines:
            a, b = tuple(round(c, 3) for c in l.coords[0]), tuple(round(c, 3) for c in l.coords[-1])
            if (deg[a] == 1 or deg[b] == 1) and l.length < 1.5 * w and len(lines) > 1:
                continue
            keep.append(l)
        if len(keep) == len(lines):
            break
        lines = keep
        m = shapely.line_merge(MultiLineString(lines))
        lines = list(getattr(m, 'geoms', [m]))
    return [l.simplify(0.5) for l in lines if l.length > 2]


def build(area):
    w, s, e, n = area['bbox']
    x0, y0 = TO_M.transform(w, s)
    x1, y1 = TO_M.transform(e, n)
    B = box(x0, y0, x1, y1)
    roof_parts = [p for p in merged_parts if p.intersects(B)]
    grown = [p.buffer(TOL) for p in roof_parts]
    gtree = STRtree(grown)

    V = {}       # id -> (x, y)
    segs = []    # [u, v, cover, kind]   cover: 0 open, 1 LTA linkway, 2 other shelter
    nid = [-1]

    def newv(x, y):
        nid[0] -= 1
        V[nid[0]] = (x, y)
        return nid[0]

    raw = []     # (u, v, sheltered, kind)
    for _, hw, shel, nodes in ways:
        pts = []
        for ref, lon, lat in nodes:
            if ref not in V:
                V[ref] = TO_M.transform(lon, lat)
            pts.append(ref)
        kind = 'path' if hw in PATHS else 'road'
        for a, b in zip(pts, pts[1:]):
            if a == b:
                continue
            mx, my = (V[a][0] + V[b][0]) / 2, (V[a][1] + V[b][1]) / 2
            if B.contains(Point(mx, my)):
                raw.append((a, b, shel, kind))

    # 4. unmatched roofs get a centre line
    seg_lines = [LineString([V[a], V[b]]) for a, b, _, _ in raw]
    stree = STRtree(seg_lines)
    added_km, added_n = 0.0, 0
    vtx_ids = list({v for a, b, _, _ in raw for v in (a, b)})
    vtree = STRtree([Point(V[v]) for v in vtx_ids])
    for p, g in zip(roof_parts, grown):
        el = strip_len(p)
        inside = sum(seg_lines[i].intersection(g).length for i in stree.query(g))
        if el < 15 or inside >= 0.4 * el:
            continue
        lines = centerline(p)
        if not lines:
            continue
        added_n += 1
        ends = collections.Counter()
        cl_ids = {}
        for l in lines:
            cs = list(l.coords)
            ids = []
            for c in cs:
                k = (round(c[0], 2), round(c[1], 2))
                if k not in cl_ids:
                    cl_ids[k] = newv(*c)
                ids.append(cl_ids[k])
            for a, b in zip(ids, ids[1:]):
                raw.append((a, b, False, 'path'))
                added_km += math.dist(V[a], V[b]) / 1000
            ends[ids[0]] += 1
            ends[ids[-1]] += 1
        width = p.area / max(el, 1)
        for vid, d in ends.items():
            if d != 1:
                continue
            pt = Point(V[vid])
            j = vtree.nearest(pt)
            near = vtx_ids[j]
            dist = pt.distance(Point(V[near]))
            if dist <= max(12, width + 8):
                raw.append((vid, near, False, 'path'))
                added_km += dist / 1000

    # 3. cut segments at the roofs
    for a, b, shel, kind in raw:
        line = LineString([V[a], V[b]])
        L = line.length
        iv = []
        for i in gtree.query(line):
            x = line.intersection(grown[i])
            for piece in getattr(x, 'geoms', [x]):
                if piece.is_empty or piece.geom_type != 'LineString' or piece.length < 0.5:
                    continue
                t0, t1 = sorted((line.project(Point(piece.coords[0])), line.project(Point(piece.coords[-1]))))
                iv.append([t0, t1])
        iv.sort()
        mergd = []
        for t0, t1 in iv:
            if mergd and t0 <= mergd[-1][1] + 0.5:
                mergd[-1][1] = max(mergd[-1][1], t1)
            else:
                mergd.append([t0, t1])
        base = 2 if shel else 0
        if not mergd:
            segs.append([a, b, base, kind]); continue
        # snap interval ends close to the segment ends
        cuts = []   # (t, cover-after)
        pos, prev = 0.0, a
        for t0, t1 in mergd:
            if t0 < 0.5: t0 = 0.0
            if t1 > L - 0.5: t1 = L
            if t0 > pos:
                q = newv(*line.interpolate(t0).coords[0])
                segs.append([prev, q, base, kind]); prev = q
            if t1 >= L:
                segs.append([prev, b, 1, kind]); prev = b; pos = L; break
            q = newv(*line.interpolate(t1).coords[0])
            segs.append([prev, q, 1, kind]); prev = q; pos = t1
        if pos < L:
            segs.append([prev, b, base, kind])

    # 5. largest connected piece
    parent = {}
    def find(x):
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]; x = parent[x]
        return x
    for a, b, _, _ in segs:
        ra, rb = find(a), find(b)
        if ra != rb: parent[ra] = rb
    size = collections.Counter()
    for a, b, _, _ in segs:
        size[find(a)] += math.dist(V[a], V[b])
    main = size.most_common(1)[0][0]
    dropped = sum(v for k, v in size.items() if k != main) / 1000
    segs = [sg for sg in segs if find(sg[0]) == main]

    # stats on the kept network
    st = {'path_km': 0, 'path_lta_km': 0, 'path_other_km': 0, 'all_km': 0, 'all_lta_km': 0, 'all_other_km': 0}
    for a, b, c, kind in segs:
        d = math.dist(V[a], V[b]) / 1000
        st['all_km'] += d
        if c == 1: st['all_lta_km'] += d
        if c == 2: st['all_other_km'] += d
        if kind == 'path':
            st['path_km'] += d
            if c == 1: st['path_lta_km'] += d
            if c == 2: st['path_other_km'] += d
    st = {k: round(v, 2) for k, v in st.items()}
    st['roof_km'] = round(sum(strip_len(p.intersection(B)) for p in roof_parts if not p.intersection(B).is_empty) / 1000, 2)
    st['centrelines_added'] = added_n
    st['centreline_km'] = round(added_km, 2)
    st['dropped_islands_km'] = round(dropped, 2)

    # contract chains
    adj = collections.defaultdict(list)
    for i, (a, b, c, k) in enumerate(segs):
        adj[a].append(i); adj[b].append(i)
    junction = {v for v, l in adj.items() if len(l) != 2}
    used = [False] * len(segs)
    edges = []   # (a, b, [vertex ids], [covers])
    def walk(start, si):
        ids, cov = [start], []
        cur, s_ = start, si
        while True:
            used[s_] = True
            a, b, c, k = segs[s_]
            nxt = b if a == cur else a
            ids.append(nxt); cov.append(c)
            if nxt in junction or nxt == start:
                return ids, cov
            l = adj[nxt]
            s2 = l[0] if l[1] == s_ else l[1]
            if used[s2]:
                return ids, cov
            cur, s_ = nxt, s2
    for v in list(junction):
        for si in adj[v]:
            if not used[si]:
                edges.append(walk(v, si))
    for si in range(len(segs)):   # loops with no junction
        if not used[si]:
            junction.add(segs[si][0])
            edges.append(walk(segs[si][0], si))

    # thin each run of equal cover (Douglas-Peucker), keeping run ends
    def thin(ids, cov):
        out_ids, out_cov = [ids[0]], []
        i = 0
        while i < len(cov):
            j = i
            while j < len(cov) and cov[j] == cov[i]:
                j += 1
            run = ids[i:j + 1]
            if len(run) > 2:
                ls = LineString([V[v] for v in run]).simplify(SIMPLIFY, preserve_topology=False)
                keep = set()
                for c in ls.coords:
                    keep.add(min(run, key=lambda v: (V[v][0] - c[0]) ** 2 + (V[v][1] - c[1]) ** 2))
                run2 = [v for v in run if v in keep or v in (run[0], run[-1])]
            else:
                run2 = run
            out_ids += run2[1:]
            out_cov += [cov[i]] * (len(run2) - 1)
            i = j
        return out_ids, out_cov
    edges = [thin(ids, cov) for ids, cov in edges]

    # code it: junction nodes, then each edge's inner points as deltas (1e-6 deg)
    jl = sorted({e[0][0] for e in edges} | {e[0][-1] for e in edges}, key=lambda v: (V[v][1], V[v][0]))
    jix = {v: i for i, v in enumerate(jl)}
    LL = {}
    def ll(v):
        if v not in LL:
            lon, lat = TO_LL.transform(*V[v])
            LL[v] = (round(lon * 1e6), round(lat * 1e6))
        return LL[v]
    nodes = []
    px = py = 0
    for v in jl:
        x, y = ll(v); nodes += [x - px, y - py]; px, py = x, y
    E_a, E_b, E_n, E_d, E_c = [], [], [], [], []
    for ids, cov in edges:
        E_a.append(jix[ids[0]]); E_b.append(jix[ids[-1]]); E_n.append(len(ids) - 2)
        px, py = ll(ids[0])
        for v in ids[1:-1]:
            x, y = ll(v); E_d += [x - px, y - py]; px, py = x, y
        E_c.append(''.join(map(str, cov)))
    # same lengths the page computes: equirectangular metres on the coded 1e-6 degrees
    lat0 = (s + n) / 2
    KX, KY = 111320 * math.cos(math.radians(lat0)), 110574
    def mlen(p, q):
        return math.hypot((q[0] - p[0]) / 1e6 * KX, (q[1] - p[1]) / 1e6 * KY)
    G = collections.defaultdict(list)
    seglist = []   # for snapping presets: (edge index, vertex coded coords)
    for k, (ids, cov) in enumerate(edges):
        pts = [ll(v) for v in ids]
        lo = sum(mlen(pts[i], pts[i + 1]) for i in range(len(cov)) if cov[i] == 0)
        lc = sum(mlen(pts[i], pts[i + 1]) for i in range(len(cov)) if cov[i] != 0)
        a, b = jix[ids[0]], jix[ids[-1]]
        G[a].append((b, lo, lc, k)); G[b].append((a, lo, lc, k))
        seglist.append(pts)
    print(area['id'], 'junctions', len(jl), 'edges', len(edges), 'points', len(E_d) // 2 + len(jl), st)
    return {'nodes': nodes, 'a': E_a, 'b': E_b, 'n': E_n, 'd': E_d, 'c': ''.join(E_c), 'stats': st}, G, jl, ll, jix


def dijkstra(G, src, dst, wet):
    dist = {src: 0.0}; prev = {}
    pq = [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, lo, lc, k in G[u]:
            nd = d + wet * lo + lc + (0.001 * lo if wet == 1 else 0)   # ties go to the drier way
            if nd < dist.get(v, 1e18) - 1e-9:
                dist[v] = nd; prev[v] = (u, lo, lc); heapq.heappush(pq, (nd, v))
    if dst not in dist:
        return None
    o = c = 0.0
    v = dst
    while v != src:
        u, lo, lc = prev[v]; o += lo; c += lc; v = u
    return o, c


out = {'island': island, 'osm': osm_time, 'wet': WET, 'areas': []}
for area in AREAS:
    data, G, jl, ll, jix = build(area)
    w, s, e, n = area['bbox']
    lat0 = (s + n) / 2
    KX, KY = 111320 * math.cos(math.radians(lat0)), 110574
    jpos = [None] * len(jl)
    for v, i in jix.items():
        jpos[i] = ll(v)
    def nearest_j(lon, lat, maxd=60):
        best, bd = None, 1e18
        for i, (x, y) in enumerate(jpos):
            d = math.hypot((x / 1e6 - lon) * KX, (y / 1e6 - lat) * KY)
            if d < bd:
                best, bd = i, d
        return (best, bd) if bd <= maxd else (None, bd)
    inside = lambda o: w <= o['lon'] <= e and s <= o['lat'] <= n
    sts = [st for st in stations if inside(st)]
    # entrances get their station's name
    starts = []
    refs = stations + stops
    for en in entrances:
        if not inside(en):
            continue
        nm = re.split(r' \(| Exit| Station| - ', en['name'])[0].strip() if en['name'] else ''
        if nm.lower().startswith('exit'):
            nm = ''
        lrt = False
        if not nm:
            near = min(refs, key=lambda st: math.hypot((st['lon'] - en['lon']) * KX, (st['lat'] - en['lat']) * KY))
            if math.hypot((near['lon'] - en['lon']) * KX, (near['lat'] - en['lat']) * KY) > 250:
                continue
            nm, lrt = near['name'], near['lrt']
        kind = 'LRT' if lrt else 'MRT'
        starts.append({'label': f"{nm} {kind}, Exit {en['ref']}" if en['ref'] else f'{nm} {kind}', 'lon': en['lon'], 'lat': en['lat'], 'st': nm, 'mrt': not lrt})
    for st in sts:
        if st['lrt']:
            starts.append({'label': f"{st['name']} LRT", 'lon': st['lon'], 'lat': st['lat'], 'st': st['name'], 'mrt': False})
    if area['dest'] == 'hdb':
        blks = [dict(b, label=f"Blk {b['blk']} {b['street']}") for b in blocks if inside(b)]
    else:
        blks, seen = [], set()
        for f_ in food:
            if inside(f_) and f_['name'] not in seen:
                seen.add(f_['name']); blks.append(dict(f_, label=f_['name']))
    print(area['id'], 'starts', len(starts), 'destinations', len(blks))
    cands = []
    for sp in starts:
        j0, d0 = nearest_j(sp['lon'], sp['lat'], 40)
        if j0 is None:
            continue
        for bk in blks:
            dd = math.hypot((bk['lon'] - sp['lon']) * KX, (bk['lat'] - sp['lat']) * KY)
            if not 250 <= dd <= 800:
                continue
            j1, d1 = nearest_j(bk['lon'], bk['lat'], 45)
            if j1 is None or j1 == j0:
                continue
            f = dijkstra(G, j0, j1, 1)
            dr = dijkstra(G, j0, j1, WET)
            if not f or not dr:
                continue
            fl, dl = f[0] + f[1], dr[0] + dr[1]
            if fl > 1.6 * dd + 150:
                continue
            saved = f[0] - dr[0]
            detour = dl - fl
            cands.append({'from': sp['label'], 'st': sp['st'], 'to': bk['label'], 'a': j0, 'b': j1,
                          'fast': [round(f[0]), round(f[1])], 'dry': [round(dr[0]), round(dr[1])], 'saved': round(saved), 'detour': round(detour),
                          'score': saved - 1.5 * max(detour, 0) + (150 if sp['mrt'] else 0)})
    cands.sort(key=lambda c: -c['score'])
    picks, seen_st, seen_to = [], set(), set()
    for c in cands:
        if c['st'] in seen_st or c['to'] in seen_to or c['saved'] < 60:
            continue
        picks.append(c); seen_st.add(c['st']); seen_to.add(c['to'])
        if len(picks) >= 5:
            break
    # station labels: LRT station nodes; MRT stations at the middle of their exits and stop positions
    groups = collections.defaultdict(list)
    for sp in starts:
        if sp['mrt']:
            groups[sp['st']].append((sp['lon'], sp['lat']))
    for sp in stops:
        if inside(sp):
            groups[sp['name']].append((sp['lon'], sp['lat']))
    labels = [{'name': st['name'], 'lrt': True, 'p': [round(st['lon'], 6), round(st['lat'], 6)]} for st in sts if st['lrt']]
    for nm, pts in groups.items():
        labels.append({'name': nm, 'lrt': False, 'p': [round(sum(p[0] for p in pts) / len(pts), 6), round(sum(p[1] for p in pts) / len(pts), 6)]})
    exits = [[round(en['lon'], 6), round(en['lat'], 6), en['ref']] for en in entrances if inside(en) and en['ref']]
    for c in picks:
        c['a'] = list(jpos[c['a']]); c['b'] = list(jpos[c['b']])
        c.pop('score'); c.pop('st')
        print('  preset', c)
    data.update({'id': area['id'], 'name': area['name'], 'bbox': area['bbox'], 'presets': picks,
                 'stations': labels, 'exits': exits})
    out['areas'].append(data)

with open(os.path.join(OUT, 'network.js'), 'w') as f:
    f.write('window.DAY24 = ' + json.dumps(out, separators=(',', ':')) + ';\n')
print('wrote', os.path.getsize(os.path.join(OUT, 'network.js')) // 1024, 'kB')
