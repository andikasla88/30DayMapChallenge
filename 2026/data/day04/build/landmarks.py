"""Day 04 · landmark list for naming clusters (Overpass refused this machine with 406, so
this uses Photon, the OSM geocoder by komoot, which serves the same OpenStreetMap data).

Every DBSCAN cluster that any reasonable setting can produce (eps 120-300 m, minPts 5-14, 10+ taxis,
all 32 snapshots) is reduced to a centroid; centroids closer than 350 m are merged; each
remaining site gets one Photon reverse query for nearby named landmarks of the kinds that
make sense as a taxi gathering place. The union is written to <raw>/landmarks.json and is
baked by build.py.

usage: python landmarks.py <raw-dir>
"""
import json, sys, time, glob, pathlib, hashlib
import numpy as np, requests
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.cluster import DBSCAN

RAW = pathlib.Path(sys.argv[1])
CACHE = RAW / 'photon'; CACHE.mkdir(exist_ok=True)
FWD = Transformer.from_crs(4326, 3414, always_xy=True)
INV = Transformer.from_crs(3414, 4326, always_xy=True)
TAGS = ['aeroway:terminal', 'amenity:taxi', 'amenity:casino', 'shop:mall', 'amenity:hospital', 'railway:station',
        'tourism:hotel', 'amenity:bus_station', 'amenity:fuel', 'amenity:food_court', 'amenity:marketplace',
        'shop:car_repair', 'leisure:stadium', 'tourism:attraction', 'place:suburb', 'place:quarter', 'place:neighbourhood']


def load(f):
    c = np.array(json.load(open(f))['features'][0]['geometry']['coordinates'])
    x, y = FWD.transform(c[:, 0], c[:, 1])
    P = np.round(np.c_[x, y])
    drop = {max(p) for p in cKDTree(P).query_pairs(1.5)}
    return np.delete(P, sorted(drop), axis=0)


cents = []
for f in sorted(glob.glob(str(RAW / 'taxi_*.json'))):
    P = load(f)
    for eps in (120, 200, 300):
        for mp in (5, 8, 14):
            lab = DBSCAN(eps=eps, min_samples=mp).fit(P).labels_
            for k in range(lab.max() + 1):
                m = lab == k
                if m.sum() >= 10:
                    cents.append(P[m].mean(0))
cents = np.array(cents)
# greedy merge within 250 m
order = np.arange(len(cents)); taken = np.zeros(len(cents), bool); tree = cKDTree(cents); sites = []
for i in order:
    if taken[i]: continue
    nb = [j for j in tree.query_ball_point(cents[i], 350) if not taken[j]]
    taken[nb] = True
    sites.append(cents[nb].mean(0))
print('sites', len(sites))

out = {}
for x, y in sites:
    lon, lat = INV.transform(x, y)
    key = hashlib.md5(f'{lat:.4f},{lon:.4f}'.encode()).hexdigest()[:12]
    cf = CACHE / f'{key}.json'
    if not cf.exists():
        params = [('lat', f'{lat:.5f}'), ('lon', f'{lon:.5f}'), ('limit', '25'), ('radius', '0.7')] + [('osm_tag', t) for t in TAGS]
        for attempt in range(3):
            try:
                r = requests.get('https://photon.komoot.io/reverse', params=params, timeout=30,
                                 headers={'User-Agent': '30DayMapChallenge-day04-build'})
                r.raise_for_status(); r.json(); cf.write_text(r.text, encoding='utf-8'); break
            except Exception as e:
                print('retry', e); time.sleep(5 + 5 * attempt)
        time.sleep(0.35)
    if not cf.exists() or cf.stat().st_size < 10: cf.unlink(missing_ok=True); continue
    for ft in json.loads(cf.read_text(encoding='utf-8'))['features']:
        p = ft['properties']
        if not p.get('name'): continue
        kind = f"{p['osm_key']}:{p['osm_value']}"
        lo, la = ft['geometry']['coordinates']
        out[(p['name'], kind, round(lo, 4), round(la, 4))] = {'name': p['name'], 'kind': kind, 'lon': lo, 'lat': la}
(RAW / 'landmarks.json').write_text(json.dumps(list(out.values()), ensure_ascii=False, indent=0), encoding='utf-8')
print('landmarks', len(out))
