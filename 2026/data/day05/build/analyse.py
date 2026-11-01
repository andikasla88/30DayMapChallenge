"""Day 05 (Sight): who can see the Marina Bay fireworks from home?

  python analyse.py <raw-dir> <out-json>

Run order: fetch.py (HDB, terrain) -> osm_from_pbf.py (OSM buildings) -> analyse.py.

1. Buildings from OSM (outlines and building:parts) within 8 km of the barge. Heights from
   OSM height / building:levels; HDB blocks joined to HDB Property Information by block +
   street (or, where OSM and HDB disagree on the lorong, block + place words with matching
   floor counts) get max_floor_lvl x 2.8 m and their dwelling units. Large buildings with no
   height in OSM get one from the terrain DSM minus ground; the rest default to 1-2 floors.
2. Ground: AWS terrain tiles (SRTM-based DSM) with buildings masked out and a grey opening,
   so towers in the DSM do not raise the ground.
3. A 5 m surface model in SVY21 (ground + building tops) and a building-id raster.
4. For sample points along each building's bay-facing facade, one ray to each burst
   (150 m and 250 m above the barge). Along the ray the lowest eye height that clears every
   obstacle is max_i (E_i - zb t_i) / (1 - t_i), where E_i is the obstacle height minus
   earth curvature (refraction k = 0.13) and t_i the fraction of the way to the burst. A floor
   sees the show if its eye height (floor base + 1.5 m) clears that for any facade point.
5. Out: one compact JSON (footprints as delta-coded 1e-5 degree integers).
"""
import json, math, os, sys, time
from collections import Counter
import numpy as np
from scipy import ndimage
from rasterio import features
from rasterio.transform import from_origin
import shapely
from shapely.geometry import Point, Polygon, MultiPolygon, mapping
from shapely.ops import transform as stransform, unary_union

sys.path.insert(0, os.path.dirname(__file__))
from common import *

RAW, OUT = sys.argv[1], sys.argv[2]
BURSTS = [150.0, 250.0]
CELL = 5.0
HALF = RADIUS + 600
EYE = 1.5
R_EFF = 6371000 / (1 - 0.13)
t0 = time.time()
log = lambda *a: print(f'[{time.time() - t0:6.1f}s]', *a, flush=True)

# ---------- buildings ----------
osm = load_osm(RAW)
hdb, hdb_core = load_hdb(RAW)
log('osm features', len(osm), 'hdb rows', len(hdb))
proj = lambda g: stransform(lambda x, y, z=None: TO_SVY.transform(x, y), g)
barge = Point(BX, BY)
HOUSE = {'house', 'detached', 'semidetached_house', 'terrace', 'bungalow', 'residential_house'}
SMALL = {'roof', 'shed', 'garage', 'garages', 'hut', 'kiosk', 'carport', 'canopy', 'shelter', 'toilets', 'cabin',
         'service', 'transformer_tower', 'bridge', 'gatehouse', 'guardhouse', 'pavilion', 'shrine', 'container'}

recs = []
for f in osm:
    g = proj(f['geom'])
    if g.area < 12 or g.distance(barge) > RADIUS + 300:
        continue
    t = f['tags']
    h = num(t.get('height')) or num(t.get('building:height'))
    lv = num(t.get('building:levels'))
    mh = num(t.get('min_height'))
    kind = t.get('building') or t.get('building:part') or 'yes'
    r = {'osm': f['id'], 'g': g, 'part': f['part'], 'tags': t, 'kind': kind, 'h': h, 'lv': lv, 'mh': mh, 'hdb': None}
    hn, st = t.get('addr:housenumber'), t.get('addr:street')
    if hn and st and not f['part']:
        key = (norm_blk(hn), norm_street(st))
        if key in hdb:
            r['hdb'] = hdb[key]
        else:
            alt = hdb_core.get((key[0], core_street(st)))
            # Only when the floor counts agree (or OSM has none): avoids joining a shophouse.
            if alt and (lv is None or abs(int(alt['max_floor_lvl']) - lv) <= 3) and r['kind'] not in HOUSE | SMALL:
                r['hdb'] = alt
                r['fallback'] = True
    recs.append(r)
log('in radius', len(recs), 'hdb joined', sum(r['hdb'] is not None for r in recs), 'of which by block + place', sum(1 for r in recs if r.get('fallback')))

# One HDB record, one set of flats: if two OSM outlines join the same block, the bigger exact
# match carries the dwelling units (the other keeps the floors for its height).
best = {}
for r in recs:
    if r['hdb']:
        k = r['hdb']['_id']
        rank = (not r.get('fallback'), r['g'].area)
        if k not in best or rank > best[k][0]:
            best[k] = (rank, r)
for r in recs:
    r['owns_units'] = bool(r['hdb']) and best[r['hdb']['_id']][1] is r

# Height and storey for each record.
src = Counter()
for r in recs:
    h, lv, H = r['h'], r['lv'], r['hdb']
    if H:
        floors = int(H['max_floor_lvl'])
        storey = 2.8
        hh = floors * storey + 2.0
        if h and 0.75 * hh < h < 1.35 * hh:
            hh = max(h, floors * storey + 1.0)
        src['hdb'] += 1
    elif h:
        floors = int(lv) if lv and lv >= 1 else max(1, round(h / 3.4))
        hh, storey = h, h / max(floors, 1)
        src['height'] += 1
    elif lv:
        floors = max(1, int(lv))
        storey = 2.9 if r['kind'] in ('apartments', 'residential', 'hdb', 'condominium') else 3.4
        hh = floors * storey + 1.5
        src['levels'] += 1
    else:
        if r['kind'] in HOUSE:
            floors, storey = 2, 3.3
        elif r['kind'] in SMALL:
            floors, storey = 1, 4.0
        else:
            floors, storey = 2, 3.8
        hh = floors * storey + 0.5
        src['default'] += 1
    r['H'], r['floors'], r['storey'] = float(min(hh, 320)), max(1, floors), storey
    r['src'] = 'hdb' if H else 'height' if h else 'levels' if lv else 'default'
log('height source', dict(src))

# Outlines that own parts: the parts carry the 3D shape; the outline is the observer.
outlines = [r for r in recs if not r['part']]
parts = [r for r in recs if r['part']]
tree = shapely.STRtree([r['g'] for r in outlines])
for p in parts:
    c = p['g'].representative_point()
    hits = [outlines[i] for i in tree.query(c, predicate='within')]
    if hits:
        o = min(hits, key=lambda o: o['g'].area)
        o.setdefault('parts', []).append(p)
        p['owner'] = o
for o in outlines:
    if o.get('parts'):
        top = max(p['H'] for p in o['parts'])
        if top > o['H']:
            o['floors'] = max(o['floors'], round(top / o['storey']))
            o['H'] = top
log('outlines', len(outlines), 'with parts', sum(1 for o in outlines if o.get('parts')))

# ---------- rasters ----------
x0, y1 = BX - HALF, BY + HALF
N = int(2 * HALF / CELL)
tr = from_origin(x0, y1, CELL, CELL)
cx = x0 + (np.arange(N) + 0.5) * CELL
cy = y1 - (np.arange(N) + 0.5) * CELL

# Ground on a 20 m grid: DSM with building cells removed, opened, refilled, smoothed.
G = 20.0
NG = int(2 * HALF / G)
gx = x0 + (np.arange(NG) + 0.5) * G
gy = y1 - (np.arange(NG) + 0.5) * G
GX, GY = np.meshgrid(gx, gy)
lng, lat = TO_WGS.transform(GX.ravel(), GY.ravel())
sample = load_terrain(RAW)
dsm = sample(np.array(lng), np.array(lat)).reshape(NG, NG).astype(np.float32)
bmask = features.rasterize([(r['g'].buffer(25), 1) for r in recs], out_shape=(NG, NG),
                           transform=from_origin(x0, y1, G, G), fill=0, dtype='uint8').astype(bool)
opened = ndimage.grey_opening(dsm, size=(9, 9))
ground = np.where(bmask, np.nan, opened)
w = (~np.isnan(ground)).astype(np.float32)
gz = np.nan_to_num(ground)
for sig in (3, 8, 20):
    num_ = ndimage.gaussian_filter(gz * w, sig); den = ndimage.gaussian_filter(w, sig)
    fill = num_ / np.maximum(den, 1e-6)
    ground = np.where(np.isnan(ground) & (den > 0.05), fill, ground)
ground = np.where(np.isnan(ground), 3.0, ground)
ground = ndimage.gaussian_filter(np.minimum(ground, opened + 0), 2)
ground = np.clip(ground, 0, None).astype(np.float32)
log('ground 20 m: min %.1f max %.1f' % (ground.min(), ground.max()), 'Raffles Pl %.1f, Mt Faber %.1f, Fort Canning %.1f' % tuple(float(ground_at(*TO_SVY.transform(*p))) for p in [(103.8515, 1.2840), (103.8188, 1.2726), (103.8462, 1.2950)]) if 'ground_at' in globals() else '')
ground5 = ndimage.zoom(ground, G / CELL, order=1)[:N, :N]


def ground_at(x, y):
    i = np.clip(((y1 - np.asarray(y)) / G - 0.5).astype(int), 0, NG - 1)
    j = np.clip(((np.asarray(x) - x0) / G - 0.5).astype(int), 0, NG - 1)
    return ground[i, j]


log('ground: Raffles Pl %.1f, Mt Faber %.1f, Fort Canning %.1f, Toa Payoh %.1f' % tuple(float(ground_at(*TO_SVY.transform(*p))) for p in [(103.8515, 1.2840), (103.8188, 1.2726), (103.8462, 1.2950), (103.8476, 1.3343)]))
for k, o in enumerate(outlines):
    o['idx'] = k
    c = o['g'].representative_point()
    o['z0'] = float(ground_at(c.x, c.y))

# Large buildings with no height or levels in OSM: estimate from the terrain DSM (SRTM sees
# big buildings, blurred) minus the ground, 75th percentile inside the footprint, capped.
ndsm = dsm - ground
filled = 0
for o in outlines:
    if o['src'] != 'default' or o.get('parts') or o['g'].area < 600:
        continue
    b = o['g'].bounds
    j0, j1 = int((b[0] - x0) / G), int((b[2] - x0) / G) + 1
    i0, i1 = int((y1 - b[3]) / G), int((y1 - b[1]) / G) + 1
    win = ndsm[max(i0, 0):min(i1, NG), max(j0, 0):min(j1, NG)]
    if win.size == 0:
        continue
    est = float(np.percentile(win, 75)) * 0.9
    if est > o['H'] + 4:
        o['H'] = min(est, 90.0)
        o['floors'] = max(o['floors'], int(o['H'] / o['storey']))
        filled += 1
log('heights estimated from the terrain DSM', filled)

# Surface tops: absolute heights. Parts replace their outline's footprint.
shapes_h, shapes_id = [], []
for o in outlines:
    pieces = o.get('parts') or [o]
    for p in pieces:
        shapes_h.append((p['H'] + o['z0'], p['g']))
for p in parts:
    if 'owner' not in p:   # orphan parts still block views
        z = float(ground_at(*p['g'].representative_point().coords[0]))
        shapes_h.append((p['H'] + z, p['g']))
shapes_h.sort(key=lambda s: s[0])
top = features.rasterize([(g, v) for v, g in shapes_h], out_shape=(N, N), transform=tr, fill=0, dtype='float32')
ids = features.rasterize([(o['g'], o['idx'] + 1) for o in sorted(outlines, key=lambda o: o['H'] + o['z0'])]
                         + [(p['g'], p['owner']['idx'] + 1) for p in parts if 'owner' in p],
                         out_shape=(N, N), transform=tr, fill=0, dtype='int32')
surf = np.maximum(ground5, top).astype(np.float32)
log('rasters', N, 'x', N)

# ---------- facade samples ----------
def facade_points(o):
    g = o['g']
    poly = max(g.geoms, key=lambda p: p.area) if isinstance(g, MultiPolygon) else g
    ring = poly.exterior
    L = ring.length
    n = max(8, int(L / 6))
    pts = np.array([ring.interpolate(i * L / n).coords[0] for i in range(n)])
    d = np.array([BX, BY]) - pts
    dist = np.hypot(d[:, 0], d[:, 1])
    u = d / dist[:, None]
    q = pts + u * 4.0
    out = ~shapely.contains_xy(poly, q[:, 0], q[:, 1])
    cand = q[out] if out.any() else q[[np.argmin(dist)]]
    if len(cand) > 7:
        sel = np.linspace(0, len(cand) - 1, 7).round().astype(int)
        cand = cand[sel]
    closest = q[np.argmin(dist)]
    return np.vstack([cand, closest[None]])


obs = []   # (outline idx, x, y)
for o in outlines:
    for x, y in facade_points(o):
        obs.append((o['idx'], x, y))
obs = np.array(obs)
log('observer points', len(obs))

# ---------- rays ----------
STEP = 2.5


def march(zb):
    n = len(obs)
    thr = np.full(n, -1e9, np.float32)
    blk = np.full(n, -1, np.int64)
    ox, oy = obs[:, 1], obs[:, 2]
    D = np.hypot(BX - ox, BY - oy)
    own = obs[:, 0].astype(np.int64) + 1
    order = np.argsort(D)
    B = 600
    for s in range(0, n, B):
        sl = order[s:s + B]
        Dm = D[sl]
        M = int(Dm.max() / STEP) + 1
        d = (np.arange(1, M + 1) * STEP)[None, :]                     # metres from the observer
        tt = d / Dm[:, None]
        valid = tt < 0.995
        px = ox[sl, None] + (BX - ox[sl, None]) * np.minimum(tt, 1)
        py = oy[sl, None] + (BY - oy[sl, None]) * np.minimum(tt, 1)
        j = np.clip(((px - x0) / CELL).astype(np.int64), 0, N - 1)
        i = np.clip(((y1 - py) / CELL).astype(np.int64), 0, N - 1)
        E = surf[i, j] - d * (Dm[:, None] - d) / (2 * R_EFF)
        valid &= ids[i, j] != own[sl, None]
        need = np.where(valid, (E - zb * tt) / np.maximum(1 - tt, 1e-3), -1e9)
        a = need.argmax(1)
        thr[sl] = need[np.arange(len(sl)), a]
        hit = ids[i[np.arange(len(sl)), a], j[np.arange(len(sl)), a]]
        blk[sl] = hit - 1
    return thr, blk


res = {}
for zb in BURSTS:
    zabs = zb   # burst height above sea level; the bay is at ~0 m
    thr, blk = march(zabs)
    res[zb] = (thr, blk)
    log('burst', zb, 'done')

# ---------- per building ----------
for o in outlines:
    o['view'] = {}
for zb in BURSTS:
    thr, blk = res[zb]
    best = {}
    for k in range(len(obs)):
        bi = int(obs[k, 0])
        if bi not in best or thr[k] < thr[best[bi]]:
            best[bi] = k
    for o in outlines:
        k = best[o['idx']]
        need = float(thr[k])                     # absolute eye height needed
        rel = need - o['z0']
        # floor f (1-based) eye height: (f - 1) * storey + EYE
        f = max(1, math.floor((rel - EYE) / o['storey']) + 2) if rel > EYE else 1
        if (f - 1) * o['storey'] + EYE >= o['H'] or f > o['floors']:
            f = 0
        o['view'][zb] = (f, k, int(blk[k]) if rel > EYE else -2)

# ---------- labels ----------
def label(o):
    t, H = o['tags'], o['hdb']
    if H:
        return f"Blk {H['blk_no']} {pretty_street(H['street'])}"
    name = t.get('name') or t.get('name:en')
    if name:
        return name
    hn, st = t.get('addr:housenumber'), t.get('addr:street')
    if hn and st:
        return f'{hn} {st}'
    return ''


keep = [o for o in outlines if o['g'].distance(barge) <= RADIUS and (o['g'].area >= 30 or o['H'] > 12)]
log('kept', len(keep))
newidx = {o['idx']: n for n, o in enumerate(keep)}

LNG0, LAT0 = BARGE
Q = 1e5


def enc_ring(coords):
    out, px, py = [], 0, 0
    for k, (x, y) in enumerate(coords[:-1]):
        lng_, lat_ = TO_WGS.transform(x, y)
        ix, iy = round((lng_ - LNG0) * Q), round((lat_ - LAT0) * Q)
        if k and ix == px and iy == py:
            continue
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def enc_pt(x, y):
    lng_, lat_ = TO_WGS.transform(x, y)
    return [round((lng_ - LNG0) * Q), round((lat_ - LAT0) * Q)]


# Footprints first, so blocker indices point at rows that exist.
rings = {}
for o in keep:
    g = o['g'].simplify(0.8, preserve_topology=True)
    poly = max(g.geoms, key=lambda p: p.area) if isinstance(g, MultiPolygon) else g
    ring = enc_ring(list(poly.exterior.coords))
    if len(ring) >= 6:
        rings[o['idx']] = ring
keep = [o for o in keep if o['idx'] in rings]
newidx = {o['idx']: n for n, o in enumerate(keep)}

rows = []
stats = {zb: Counter() for zb in BURSTS}
for o in keep:
    ring = rings[o['idx']]
    H = o['hdb']
    units = int(H['total_dwelling_units']) if H and H['residential'] == 'Y' and o['owns_units'] else 0
    lab = label(o)
    seen = any(o['view'][zb][0] for zb in BURSTS)
    for zb in BURSTS:
        f = o['view'][zb][0]
        if units:
            s_ = stats[zb]
            s_['blocks'] += 1; s_['units'] += units
            if f:
                share = (o['floors'] - f + 1) / o['floors']
                s_['blocks_view'] += 1; s_['units_view'] += round(units * share)
    named = o['tags'].get('name') or o['tags'].get('name:en')
    if not seen and o['H'] < 9 and not named and not units:
        rows.append([ring, round(o['H'], 1)])        # low, blind, no name (houses, sheds): context only
        continue
    v = []
    for zb in BURSTS:
        f, k, b = o['view'][zb]
        e = enc_pt(obs[k, 1], obs[k, 2])
        bl = newidx.get(b, -3) if b >= 0 else (-2 if b == -2 else -1)   # -1 terrain, -2 nothing, -3 a small unlisted building
        v += [f, e[0] - ring[0], e[1] - ring[1], bl]  # eye relative to the first vertex
    rows.append([ring, round(o['H'], 1), o['floors'], round(o['storey'], 1), units, lab] + v)

meta = {
    'barge': list(BARGE), 'radius': RADIUS, 'bursts': BURSTS, 'q': Q,
    'fields': ['ring', 'height', 'floors', 'storey', 'units', 'label',
               'f150', 'ex150', 'ey150', 'blk150', 'f250', 'ex250', 'ey250', 'blk250'],
    'note': 'rows of length 2 are [ring, height]: low buildings with no view and no name; eye x/y are relative to the first ring vertex',
    'stats': {str(int(zb)): dict(stats[zb]) for zb in BURSTS},
    'n': len(rows), 'built': time.strftime('%Y-%m-%d'),
}
json.dump({'meta': meta, 'b': rows}, open(OUT, 'w', encoding='utf-8'), separators=(',', ':'), ensure_ascii=False)
log('wrote', OUT, os.path.getsize(OUT), 'bytes')
print(json.dumps(meta['stats'], indent=1))
for o in keep:
    lab = label(o)
    if any(k in lab for k in ('Pinnacle', 'Blk 53 Toa Payoh', 'Blk 1 Beach', 'Interlace', 'Sail', 'Reflections', 'Blk 9 Telok Blangah', 'Blk 1A Cantonment')):
        print(lab, round(o['H']), o['floors'], o['view'][150][0], o['view'][250][0], round(o['g'].distance(barge)))
