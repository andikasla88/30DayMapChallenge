"""Day 04 · Clusters: bake taxis.json from the raw snapshots and landmarks.

Steps
1. Each LTA snapshot -> SVY21 (EPSG:3414) metres, rounded to 1 m. Points closer than 1.5 m
   (one unit in the feed's 5th decimal) are the same cab reported twice and are merged.
2. DBSCAN (scikit-learn) at the default eps = 200 m, minPts = 8 (the point itself counts,
   as in the page's own implementation).
3. Each cluster: convex hull of its taxis, each taxi widened to a 40 m octagon (so a queue
   of cabs on one kerb still makes a prism), taxi count, and a place name: the landmark
   with the best score (kind weight minus distance/150 m) within 700 m of the centroid.
   The page re-runs exactly this in the browser when eps/minPts change.
4. A quadratic SVY21 -> WGS84 fit (max error 0.12 m over Singapore) so the page can keep the
   points in metres and still place them on the map.

usage: python build.py <raw-dir> <out-json>
"""
import json, sys, glob, pathlib, re, datetime as dt
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import MultiPoint
from sklearn.cluster import DBSCAN

RAW = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2])
FWD = Transformer.from_crs(4326, 3414, always_xy=True)
INV = Transformer.from_crs(3414, 4326, always_xy=True)
EPS, MINPTS, PAD, NAME_R = 200, 8, 40, 700

# ---------- SVY21 -> lon/lat quadratic ----------
gx, gy = np.meshgrid(np.linspace(1000, 55000, 60), np.linspace(15000, 52000, 40)); gx = gx.ravel(); gy = gy.ravel()
glo, gla = INV.transform(gx, gy)
u, v = (gx - 28000) / 1e4, (gy - 38000) / 1e4
A = np.c_[np.ones_like(u), u, v, u * u, u * v, v * v]
CLO = np.linalg.lstsq(A, glo, rcond=None)[0]; CLA = np.linalg.lstsq(A, gla, rcond=None)[0]
err = np.hypot((A @ CLO - glo) * 111320 * np.cos(np.radians(1.35)), (A @ CLA - gla) * 110574).max()
print('quadratic fit max error %.2f m' % err)


def to_ll(x, y):
    lo, la = INV.transform(x, y)
    return round(float(lo), 5), round(float(la), 5)


# ---------- landmarks ----------
KINDS = {  # code: (weight, osm kinds)
    'T': (10, ['aeroway:terminal']), 'C': (9, ['amenity:casino']), 'M': (6, ['shop:mall']),
    'H': (6.5, ['amenity:hospital']), 'X': (4, ['amenity:taxi']), 'S': (5.5, ['railway:station']),
    'O': (3, ['tourism:hotel']), 'A': (3.5, ['leisure:stadium', 'tourism:attraction']),
    'B': (3, ['amenity:bus_station']), 'K': (2, ['amenity:food_court', 'amenity:marketplace']),
    'F': (2.5, ['amenity:fuel']), 'R': (2, ['shop:car_repair']),
    'P': (3, ['place:suburb']), 'Q': (2.5, ['place:quarter', 'place:neighbourhood']),
}
KIND_OF = {k: c for c, (w, ks) in KINDS.items() for k in ks}
RENAME = {   # tidy display names (checked against the coordinates)
    r'^Changi Airport Terminal (\d)$': r'Changi Airport T\1', r'^Terminal (\d)$': r'Changi Airport T\1',
    r'^Jewel Changi Airport$': 'Jewel Changi', r' Shopping Cent(re|er)$': '', r' Shopping Mall$': '',
    r' MRT Station$': '', r' Station$': '', r'^The ': '',
}
GROUPS = [  # strip groups: places that are one destination to a taxi driver
    (r'^Changi Airport|^Jewel Changi', 'Changi Airport'),
    (r'Marina Bay Sands|Shoppes|Sands Expo', 'Marina Bay Sands'),
    (r'Resorts World|Sentosa|Universal Studios|VivoCity|HarbourFront', 'Sentosa · VivoCity'),
]
# Named areas, checked by hand against the coordinates (Nominatim reverse lookups of the
# recurring cluster centroids). A cluster whose centroid falls inside one takes its name;
# otherwise the landmark rule above applies.
AREAS = [  # name, lon, lat, radius m
    ('Changi Airport T1–T3', 103.9882, 1.3575, 950), ('Changi Airport T4', 103.9830, 1.3398, 600),
    ('Raffles Place', 103.8505, 1.2830, 330), ('Marina One · Downtown', 103.8530, 1.2775, 300),
    ('Tanjong Pagar', 103.8462, 1.2770, 320), ('Marina Bay Sands', 103.8600, 1.2830, 450),
    ('Boat Quay · Clarke Quay', 103.8478, 1.2875, 260), ('Chinatown · Hong Lim', 103.8445, 1.2850, 260),
    ('City Hall · Raffles City', 103.8525, 1.2940, 330), ('Marina Centre', 103.8605, 1.2910, 350),
    ('Bras Basah · Bencoolen', 103.8500, 1.2990, 280), ('Bugis', 103.8553, 1.2995, 280),
    ('Kampong Glam · Beach Rd', 103.8615, 1.3025, 360), ('Lavender · Jalan Besar', 103.8580, 1.3095, 420),
    ('Geylang', 103.8820, 1.3130, 700), ('Newton', 103.8420, 1.3110, 380),
    ('Orchard · Scotts Rd', 103.8320, 1.3060, 420), ('Orchard · ION', 103.8318, 1.3035, 200),
    ('Somerset', 103.8390, 1.3008, 330), ('Sin Ming', 103.8395, 1.3615, 500),
    ('Ang Mo Kio Industrial Park 2', 103.8490, 1.3845, 450), ('Seletar Aerospace Park', 103.8595, 1.4072, 600),
    ('Mandai (zoo, Night Safari)', 103.7900, 1.4060, 900), ('Resorts World Sentosa', 103.8240, 1.2550, 450),
    ('Woodlands Checkpoint', 103.7690, 1.4455, 700), ('Tan Tock Seng · Novena', 103.8460, 1.3210, 450),
]
AR = np.array([FWD.transform(lo, la) for _, lo, la, _ in AREAS]); ARR = np.array([a[3] for a in AREAS], float)
raw = json.loads((RAW / 'landmarks.json').read_text(encoding='utf-8'))
lms = {}
for r in raw:
    code = KIND_OF.get(r['kind'])
    if not code: continue
    name = r['name'].strip()
    if not re.search(r'[A-Za-z]', name): continue                     # skip names with no Latin script
    if re.search(r'(?i)joint testing|vaccination|swab|communicable disease', name): continue   # pandemic-era sites
    if code in 'XFR' and re.fullmatch(r'(?i)(taxi( stand| stop| queue)?( \w)?|esso|shell|caltex|spc|sinopec)', name):
        continue                                                       # generic stand / brand-only names say nothing
    for pat, rep in RENAME.items(): name = re.sub(pat, rep, name)
    x, y = FWD.transform(r['lon'], r['lat'])
    key = (name.lower(), round(x / 60), round(y / 60))
    if key in lms and KINDS[lms[key][1]][0] >= KINDS[code][0]: continue
    lms[key] = [name, code, int(round(x)), int(round(y))]
landmarks = sorted(lms.values(), key=lambda l: (l[1], l[0]))
LM = np.array([[l[2], l[3]] for l in landmarks], float)
LW = np.array([KINDS[l[1]][0] for l in landmarks])
lm_tree = cKDTree(LM)
print('landmarks', len(landmarks))


def name_for(Q):
    """Named areas first: the area holding most of the cluster's cabs, if together the areas
    hold at least 30 % of them ("... and around" when 3+ areas each hold a real share).
    Otherwise the best landmark near the centroid."""
    cx, cy = Q.mean(0)
    q = np.hypot(Q[:, None, 0] - AR[None, :, 0], Q[:, None, 1] - AR[None, :, 1]) / ARR[None]
    inside = q.min(1) <= 1
    if inside.sum() >= 0.3 * len(Q):
        cnt = np.bincount(q[inside].argmin(1), minlength=len(AREAS))
        top = AREAS[int(np.argmax(cnt))][0]
        return top + ' and around' if (cnt >= max(3, 0.1 * len(Q))).sum() >= 3 else top
    idx = lm_tree.query_ball_point([cx, cy], NAME_R)
    if not idx: return None
    d = np.hypot(LM[idx, 0] - cx, LM[idx, 1] - cy)
    s = LW[idx] - d / 150
    return landmarks[idx[int(np.argmax(s))]][0]


def group_for(name):
    for pat, g in GROUPS:
        if name and re.search(pat, name): return g
    return name


# ---------- snapshots ----------
snaps = {}
for f in sorted(glob.glob(str(RAW / 'taxi_*.json'))):
    key = re.search(r'taxi_(\d{8}T\d\d)', f).group(1)
    ft = json.load(open(f))['features'][0]
    c = np.array(ft['geometry']['coordinates'])
    x, y = FWD.transform(c[:, 0], c[:, 1])
    P = np.round(np.c_[x, y])
    drop = {max(p) for p in cKDTree(P).query_pairs(1.5)}
    P = np.delete(P, sorted(drop), axis=0).astype(int)
    P = P[np.lexsort((P[:, 0], P[:, 1]))]                              # sorted: compresses better
    snaps[key] = {'ts': ft['properties']['timestamp'], 'raw': len(c), 'P': P}

OCT = np.array([[np.cos(a), np.sin(a)] for a in np.arange(8) * np.pi / 4]) * PAD


def clusters(P, eps=EPS, minpts=MINPTS):
    lab = DBSCAN(eps=eps, min_samples=minpts).fit(P).labels_
    out = []
    for k in range(lab.max() + 1):
        Q = P[lab == k]
        cx, cy = Q.mean(0)
        hull = MultiPoint((Q[:, None, :] + OCT[None]).reshape(-1, 2)).convex_hull
        ring = [to_ll(*xy) for xy in list(hull.exterior.coords)]
        nm = name_for(Q)
        out.append({'name': nm, 'group': group_for(nm), 'n': int(len(Q)), 'c': list(to_ll(cx, cy)), 'hull': ring})
    out.sort(key=lambda c: -c['n'])
    return out, lab


# k-distance: where the 8th-nearest-neighbour distance curve bends (the classic way to pick eps)
k8 = np.concatenate([cKDTree(s['P']).query(s['P'], k=MINPTS)[0][:, -1] for s in snaps.values()])
k8s = np.sort(k8)
pct_200 = float((k8 <= EPS).mean())
# knee: farthest point from the chord of the sorted curve, within the lower 90 %
yv = k8s[: int(len(k8s) * .9)]; xv = np.linspace(0, 1, len(yv)); yn = yv / yv[-1]
knee = float(yv[np.argmax(xv - yn)])
print('k8 knee ~%.0f m, %.0f%% of taxis have 7 neighbours within 200 m' % (knee, pct_200 * 100))

out_snaps, baked = {}, {}
for key, s in snaps.items():
    cl, lab = clusters(s['P'])
    baked[key] = cl
    out_snaps[key] = {'ts': s['ts'][:16], 'raw': s['raw'], 'n': int(len(s['P'])), 'inCl': int((lab >= 0).sum()),
                      'xy': s['P'].ravel().tolist()}

pairs = []
for d in range(26, 31):
    day = dt.date(2026, 10, d)
    pairs.append({'label': day.strftime('%a'), 'pm': f'202610{d:02d}T18', 'am': f'202610{d + 1:02d}T02'})


def agg(cl):
    g = {}
    for c in cl:
        if c['group']: g[c['group']] = g.get(c['group'], 0) + c['n']
    return g


summary = {}
for p in pairs:
    for side in ('pm', 'am'):
        for g, n in agg(baked[p[side]]).items():
            summary.setdefault(g, {'pm': [0] * 5, 'am': [0] * 5})[side][pairs.index(p)] = n
compare = sorted(({'name': g, 'pm': round(sum(v['pm']) / 5, 1), 'am': round(sum(v['am']) / 5, 1)} for g, v in summary.items()),
                 key=lambda r: -max(r['pm'], r['am']))[:12]
for r in compare[:8]: print('  %-28s %6.1f -> %6.1f' % (r['name'], r['pm'], r['am']))

doc = {
    'about': 'Day 04 #30DayMapChallenge 2026. Available taxis, LTA via data.gov.sg; SVY21 metres; DBSCAN eps 200 m minPts 8.',
    'geo': {'x0': 28000, 'y0': 38000, 's': 1e4, 'lon': [float('%.10g' % c) for c in CLO], 'lat': [float('%.10g' % c) for c in CLA]},
    'params': {'eps': EPS, 'minPts': MINPTS, 'pad': PAD, 'nameR': NAME_R, 'knee': round(knee), 'pct200': round(pct_200, 3)},
    'kinds': {c: w for c, (w, ks) in KINDS.items()},
    'groups': [[p, g] for p, g in GROUPS],
    'rep': '20261028',
    'pairs': pairs,
    'snaps': out_snaps,
    'clusters': baked,
    'compare': compare,
    'landmarks': landmarks,
    'areas': [[a[0], int(round(x)), int(round(y)), a[3]] for a, (x, y) in zip(AREAS, AR)],
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(doc, separators=(',', ':'), ensure_ascii=False), encoding='utf-8')
print(OUT, OUT.stat().st_size // 1024, 'KB')
