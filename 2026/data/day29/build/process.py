"""Day 29 (Raster): a cloud-free surface-temperature composite of Singapore, and its honest numbers.

Requires python 3.10+ with: numpy rasterio pyproj shapely pillow scipy cmcrameri
usage: python -I process.py <raw-dir> <out-dir>
  reads  <raw-dir>/osm.pkl (osm.py) and <raw-dir>/landsat/* (fetch.py)
  writes <out-dir>/lst.png   the composite, one byte per 30 m pixel: 0 = sea or outside Singapore,
                             1 = land with no clear reading, else temperature = 18 + (byte - 2) * 0.2
                             degC (Web Mercator grid)
         <out-dir>/lst.pgw   its world file (EPSG:3857), so GIS software can place it
         <out-dir>/lst.js  grid bounds, scenes, palette, histogram, zone means, hot clusters, outlines

Method, in plain words
  Temperature  ST_B10 is Landsat's land-surface temperature (Collection 2 Level-2). USGS publishes
               it as integers; kelvin = DN x 0.00341802 + 149.0, then minus 273.15 for degC. The
               scale and offset are read from each scene's own USGS metadata (MTL) and checked.
  Clear sky    A pixel counts in a scene only if QA_PIXEL has no fill, cloud, dilated cloud, cirrus
               or cloud-shadow flag. (ST_QA, the stated uncertainty, is 4-7 K almost everywhere in
               Singapore's humid air, so it can't separate good pixels from bad; it isn't used.)
  Composite    Each scene is warped to a 30 m Web Mercator grid (bilinear). Passes differ by a few
               degrees with the weather, so each is shifted to make its land median equal the
               median of all the passes' land medians (else cloud gaps leave seams). For each pixel we take
               the median of its clear values across the kept scenes (all ~11:16 a.m. SGT), drop
               any value more than 6 degC below that median (thin cloud or haze the mask missed
               reads cold), and take the median again. That is the map.
  Land         OSM coastline land inside Singapore's boundary; the sea is left out.
  Zones        Reservoirs: the 16 named OSM reservoirs of at least 0.3 km2, shrunk 90 m from the
               shore (the thermal sensor sees 100 m pixels, so shore pixels mix in land).
               Catchment forest: the Central Catchment Nature Reserve (OSM), minus all inland water
               grown by 90 m. Industrial estates: every OSM landuse=industrial area. Each mean is
               the mean of all composite pixels inside.
  Hot roofs    The hottest 1% of land pixels form patches (8-connected). A patch is a roof cluster
               if at least half of it lies under OSM building footprints. Clusters are ranked by
               their hottest 3 x 3 window (90 m, about 0.8 ha), which is steadier than one pixel.
               For each, the hottest single scene is reported with its date and time, as measured
               that day (not shifted).
"""
import base64
import io
import json
import os
import pickle
import sys
from datetime import datetime, timedelta

import numpy as np
import rasterio
import rasterio.features
import shapely
from PIL import Image
from pyproj import Transformer
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from scipy import ndimage as ndi
from shapely.ops import unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
LS = os.path.join(RAW, 'landsat')
D = pickle.load(open(os.path.join(RAW, 'osm.pkl'), 'rb'))
NOTES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'notes.json'), encoding='utf-8'))
MULT, ADD = 0.00341802, 149.0        # USGS Collection 2 ST scale and offset
TMIN, STEP = 18.0, 0.2               # byte encoding of degC
COLD_OUTLIER = 6.0                   # degC below the first median
SHORE = 90                           # m
BBOX = (103.595, 1.155, 104.095, 1.475)
RES = 30.0


def proj(src, dst):
    t = Transformer.from_crs(src, dst, always_xy=True)
    return lambda g: shapely.transform(g, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


to_m, to_merc, to_ll = proj(4326, 3414), proj(4326, 3857), proj(3857, 4326)
m_to_merc = proj(3414, 3857)

# ---------------- the target grid: Web Mercator, 30 m ----------------
tm = Transformer.from_crs(4326, 3857, always_xy=True)
x0, y0 = tm.transform(BBOX[0], BBOX[1])
x1, y1 = tm.transform(BBOX[2], BBOX[3])
x0, y1 = np.floor(x0 / RES) * RES, np.ceil(y1 / RES) * RES
W, H = int(np.ceil((x1 - x0) / RES)), int(np.ceil((y1 - y0) / RES))
T = from_origin(x0, y1, RES, RES)
ll = Transformer.from_crs(3857, 4326, always_xy=True)
west, north = ll.transform(x0, y1)
east, south = ll.transform(x0 + W * RES, y1 - H * RES)
print('grid', W, H)


def raster(geoms_ll, all_touched=False):
    gs = [to_merc(g) for g in geoms_ll if g is not None and not g.is_empty]
    if not gs:
        return np.zeros((H, W), bool)
    return rasterio.features.rasterize(gs, out_shape=(H, W), transform=T, all_touched=all_touched) > 0


# ---------------- scenes ----------------
scenes, stack = [], []
for sid in sorted(os.listdir(LS), key=lambda x: x[17:25] if x.startswith('L') else x):   # by date
    d = os.path.join(LS, sid)
    if not os.path.isdir(d) or not os.path.exists(os.path.join(d, 'st_qa.tif')):
        continue
    mtl = json.load(open(os.path.join(d, 'mtl.json')))['LANDSAT_METADATA_FILE']
    rs = mtl['LEVEL2_SURFACE_TEMPERATURE_PARAMETERS']
    mult, add = float(rs['TEMPERATURE_MULT_BAND_ST_B10']), float(rs['TEMPERATURE_ADD_BAND_ST_B10'])
    assert abs(mult - MULT) < 1e-9 and abs(add - ADD) < 1e-9, (sid, mult, add)
    img = mtl['IMAGE_ATTRIBUTES']
    t_utc = datetime.fromisoformat(img['DATE_ACQUIRED'] + 'T' + img['SCENE_CENTER_TIME'][:8])
    t_sgt = t_utc + timedelta(hours=8)
    with rasterio.open(os.path.join(d, 'st_b10.tif')) as s:
        st, prof = s.read(1), s.profile
    qa = rasterio.open(os.path.join(d, 'qa_pixel.tif')).read(1)
    ok = (st > 0) & ((qa & 0b11111) == 0)
    c = np.where(ok, st * mult + add - 273.15, np.nan).astype(np.float32)
    dst = np.full((H, W), np.nan, np.float32)
    reproject(c, dst, src_transform=prof['transform'], src_crs=prof['crs'], dst_transform=T, dst_crs='EPSG:3857',
              resampling=Resampling.bilinear, src_nodata=np.nan, dst_nodata=np.nan)
    stack.append(dst)
    scenes.append({'id': sid, 'date': t_sgt.strftime('%Y-%m-%d'), 'time': t_sgt.strftime('%H:%M'),
                   'sat': 'Landsat ' + sid[3]})
    print(sid, t_sgt, 'valid px', int(np.isfinite(dst).sum()))
S = np.stack(stack)
# Passes differ by a few degrees with the day's weather. To stop the cloud gaps leaving seams, each
# pass is first shifted so that its land median equals the median of all the passes' land medians.
land0 = raster([D['land']])
lvl = np.array([np.nanmedian(S[k][land0]) for k in range(len(S))])
target = float(np.median(lvl))
for k in range(len(S)):
    S[k] += target - lvl[k]
    scenes[k]['land_median'] = round(float(lvl[k]), 2)
    scenes[k]['shift'] = round(target - float(lvl[k]), 2)
print('pass land medians', lvl.round(2), 'target', round(target, 2))
with np.errstate(all='ignore'):
    med0 = np.nanmedian(S, 0)
    cold = S < med0 - COLD_OUTLIER
    print('cold outliers dropped', int(cold.sum()), [int(c.sum()) for c in cold])
    S[cold] = np.nan
    med = np.nanmedian(S, 0)
n_obs = np.isfinite(S).sum(0)

# ---------------- land ----------------
land = raster([D['land']])
valid = land & np.isfinite(med)
print('land px', int(land.sum()), 'valid', int(valid.sum()), 'obs per pixel', np.percentile(n_obs[valid], [5, 50, 95]))
vals = med[valid]
q = {k: round(float(np.percentile(vals, p)), 2) for k, p in (('p1', 1), ('p5', 5), ('p25', 25), ('median', 50),
                                                             ('p75', 75), ('p95', 95), ('p99', 99))}
q['mean'] = round(float(vals.mean()), 2)
q['min'], q['max'] = round(float(vals.min()), 2), round(float(vals.max()), 2)
print('land degC', q)

# ---------------- the byte image ----------------
code = np.zeros((H, W), np.uint8)
code[land] = 1
code[valid] = np.clip(np.round((med[valid] - TMIN) / STEP) + 2, 2, 255).astype(np.uint8)
buf = io.BytesIO()   # the PNG rides inside lst.js as a data URL (png), so the page also works opened from disk
Image.fromarray(code, 'L').save(buf, 'PNG', optimize=True)
png_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode()
with open(os.path.join(OUT, 'lst.pgw'), 'w') as f:   # world file: pixel size, rotation, centre of top-left pixel
    f.write(f'{RES}\n0\n0\n{-RES}\n{x0 + RES / 2}\n{y1 - RES / 2}\n')
hist = np.bincount(code[valid], minlength=256)[2:].tolist()   # hist[i] counts code i + 2
print('png bytes', len(buf.getvalue()))


# ---------------- zones ----------------
def zone_mean(mask):
    m = mask & valid
    return (round(float(med[m].mean()), 2), int(m.sum())) if m.any() else (None, 0)


def shrink(g_ll, metres):
    return proj(3414, 4326)(to_m(g_ll).buffer(-metres))


water_all = unary_union([g.buffer(0) for _, _, _, g in D['water']])
solar = unary_union([g.buffer(0) for g in D['solar']]) if D.get('solar') else shapely.Polygon()
reservoirs = []
for name, kind, oid, g in D['water']:
    if kind != 'reservoir' or not name:
        continue
    km2 = to_m(g).area / 1e6
    if km2 < 0.3:
        continue
    inner = shrink(g, SHORE)
    im = raster([inner])
    t, n = zone_mean(im)
    c = g.representative_point()
    sol = to_m(g.intersection(solar)).area / to_m(g).area
    reservoirs.append({'name': name, 'km2': round(km2, 2), 'mean': t, 'px': n, 'cover': round(n / max(1, int(im.sum())), 2),
                       'solar': round(sol, 2), 'at': [round(c.x, 5), round(c.y, 5)], 'g': g, 'oid': oid})
print('reservoir coverage', [(r['name'], r['mean'], r['px'], r['cover'], r['solar']) for r in reservoirs])
# Landsat leaves gaps in its temperature over some inland water; a reservoir needs data over a
# quarter of its open water to count. One largely under floating solar panels is reported apart.
nodata = [r['name'] for r in reservoirs if r['cover'] < 0.25]
solar_res = sorted([r for r in reservoirs if r['cover'] >= 0.25 and r['solar'] >= 0.1], key=lambda r: -r['solar'])
reservoirs = sorted([r for r in reservoirs if r['cover'] >= 0.25 and r['solar'] < 0.1], key=lambda r: r['mean'])
res_mask = raster([shrink(r['g'], SHORE) for r in reservoirs])
res_mean, res_px = zone_mean(res_mask)
print('reservoirs', len(reservoirs), res_mean, res_px, [(r['name'], r['mean']) for r in reservoirs], 'no data', nodata, 'solar', [(r['name'], r['mean'], r['solar']) for r in solar_res])

ccnr = [g for n, o, g in D['reserves'] if n == 'Central Catchment Nature Reserve'][0]
wet = proj(3414, 4326)(to_m(water_all).buffer(SHORE))
forest_g = ccnr.difference(wet)
forest_mean, forest_px = zone_mean(raster([forest_g]))
print('forest', forest_mean, forest_px, round(to_m(forest_g).area / 1e6, 2), 'km2')

ind = unary_union([g.buffer(0) for lu, n, o, g in D['landuse'] if lu == 'industrial'])
ind_mean, ind_px = zone_mean(raster([ind]))
print('industrial', ind_mean, ind_px, round(to_m(ind).area / 1e6, 1), 'km2')

# ---------------- hot roof clusters ----------------
bld = raster([g for _, _, _, g in D['buildings']])
hot = valid & (med >= q['p99'])
lab, n = ndi.label(hot, structure=np.ones((3, 3)))
win = np.where(valid, med, np.nan)
with np.errstate(all='ignore'):
    # 3 x 3 mean, only where all nine pixels are valid
    s = ndi.uniform_filter(np.nan_to_num(win), 3)
    cnt = ndi.uniform_filter(valid.astype(float), 3)
    m3 = np.where(cnt > 0.999, s, -np.inf)
objs = ndi.find_objects(lab)
cands = []
for i, sl in enumerate(objs, 1):
    cm = lab[sl] == i
    npx = int(cm.sum())
    if npx < 3:
        continue
    share = float(bld[sl][cm].mean())
    sub = np.where(cm, m3[sl], -np.inf)
    k = np.unravel_index(np.argmax(sub), sub.shape)
    peak = float(sub[k])
    if not np.isfinite(peak):
        continue
    r, c = k[0] + sl[0].start, k[1] + sl[1].start
    cands.append({'lab': i, 'px': npx, 'share': share, 'peak3': peak, 'rc': (r, c), 'mean': float(med[sl][cm].mean())})
roofs = sorted([c for c in cands if c['share'] >= 0.5], key=lambda c: -c['peak3'])
print('hot patches', len(cands), 'roof clusters', len(roofs))

blds = D['buildings']
btree = shapely.STRtree([g for _, _, _, g in blds])
lus = [x for x in D['landuse'] if x[0] not in ('grass', 'meadow')]
ltree = shapely.STRtree([g for _, _, _, g in lus])
pl = D['places']
pl_xy = np.array([[p[2], p[3]] for p in pl])


def ll_of(r, c):
    x, y = x0 + (c + 0.5) * RES, y1 - (r + 0.5) * RES
    return ll.transform(x, y)


def describe(cl):
    i = cl['lab']
    rr, cc = np.nonzero(lab == i)
    xs, ys = ll.transform(x0 + (cc + 0.5) * RES, y1 - (rr + 0.5) * RES)
    patch = to_ll(unary_union([shapely.box(x0 + c * RES, y1 - (r + 1) * RES, x0 + (c + 1) * RES, y1 - r * RES) for r, c in zip(rr, cc)]))
    lon, lat = ll_of(*cl['rc'])
    pk = shapely.Point(lon, lat)
    # buildings under the patch, biggest overlap first
    hits = []
    for j in btree.query(patch):
        oid, kind, name, g = blds[j]
        a = to_m(g.intersection(patch)).area
        if a > 0:
            hits.append((a, kind, name, oid, to_m(g).area))
    hits.sort(reverse=True)
    kinds = {}
    for a, kind, name, oid, ga in hits:
        kinds[kind] = kinds.get(kind, 0) + a
    named = [h for h in hits if h[2]][:3]
    lu = None
    for j in ltree.query(pk):
        if lus[j][3].contains(pk):
            if lu is None or (lus[j][1] and not lu[1]):
                lu = lus[j]
    dist = np.hypot((pl_xy[:, 0] - lon) * np.cos(np.radians(lat)), pl_xy[:, 1] - lat)
    near = pl[int(np.argmin(dist))]
    # the hottest single scene over the 3 x 3 window
    r, c = cl['rc']
    # as measured that day (the shift taken back off)
    per = [float(np.nanmean(S[k, r - 1:r + 2, c - 1:c + 2])) - scenes[k]['shift'] for k in range(len(S))]
    kmax = int(np.nanargmax(per))
    return {
        'peak': round(cl['peak3'], 1), 'mean': round(cl['mean'], 1), 'ha': round(cl['px'] * RES * RES * np.cos(np.radians(lat)) ** 2 / 1e4, 1),   # Mercator metres -> ground
        'at': [round(lon, 5), round(lat, 5)],
        'bbox': [round(min(xs), 5), round(min(ys), 5), round(max(xs), 5), round(max(ys), 5)],
        'roof': round(cl['share'] * 100), 'kinds': sorted(kinds, key=lambda k: -kinds[k])[:3],
        'names': [h[2] for h in named], 'biggest_m2': round(hits[0][4]) if hits else None,
        'landuse': [lu[0], lu[1]] if lu else None, 'place': near[0],
        'hottest_scene': {'date': scenes[kmax]['date'], 'time': scenes[kmax]['time'], 't': round(per[kmax], 1)},
        'n_obs': int(n_obs[r, c]),
    }


top = []
for cl in roofs:
    d = describe(cl)
    # one entry per site: skip a cluster within 400 m of one already listed
    if any(np.hypot((d['at'][0] - t['at'][0]) * 111320, (d['at'][1] - t['at'][1]) * 110574) < 400 for t in top):
        continue
    lon, lat = d['at']
    d['industrial'] = bool(ind.intersects(shapely.Point(lon, lat).buffer(0.0006)))
    note = next((n for n in NOTES['clusters'] if np.hypot((n['at'][0] - lon) * 111320, (n['at'][1] - lat) * 110574) < 250), None)
    if note:
        d.update({k: note[k].replace('{ha}', str(round(d['ha']))) for k in ('label', 'short', 'what')})
    else:   # a new cluster after a rebuild: name it from OSM; add a note for a better one
        where = (d['landuse'][1] if d['landuse'] and d['landuse'][1] else None) or (d['names'][0] if d['names'] else None) or d['place']
        d.update({'label': where, 'short': where, 'what': f"Roofs mapped as {', '.join(d['kinds'][:2]) or 'buildings'} near {d['place']}"})
        print('  no note for', d['at'], '- named from OSM:', where)
    d['ha'] = float(d['ha'])
    d['bbox'] = [float(v) for v in d['bbox']]
    top.append(d)
    print(len(top), d)
    if len(top) == 10:
        break

# ---------------- outlines (compact) ----------------
def enc(g, tol=0.00008):
    g = g.simplify(tol, preserve_topology=True)
    out = []
    for p in getattr(g, 'geoms', [g]):
        if p.is_empty or p.geom_type != 'Polygon':
            continue
        rings = []
        for ring in [p.exterior] + list(p.interiors):
            cs = np.round(np.array(ring.coords) * 1e5).astype(int)
            if len(cs) < 4:
                continue
            d = np.vstack([cs[:1], np.diff(cs, axis=0)])
            rings.append(d.ravel().tolist())
        if rings:
            out.append(rings)
    return out


berlin = None
try:
    from cmcrameri import cm
    berlin = ['#%02X%02X%02X' % tuple(int(round(v * 255)) for v in cm.berlin(x)[:3]) for x in np.linspace(0, 1, 65)]
except ImportError:
    sys.exit('pip install cmcrameri (Crameri scientific colour maps) for the palette')

out = {
    'png': png_url,
    'grid': {'w': W, 'h': H, 'res': RES, 'bounds': [[round(west, 6), round(south, 6)], [round(east, 6), round(north, 6)]],
             'tmin': TMIN, 'step': STEP, 'first': 2, 'nodata_land': int((land & ~valid).sum())},
    'scenes': scenes, 'obs_median': int(np.median(n_obs[valid])),
    'land': q, 'hist': hist, 'palette': berlin,
    'norm': {'lo': round(q['p1'] - 1, 1), 'hi': round(top[0]['peak'] + .5, 1),
             'axis': [float(np.floor(q['p1'] - 2)), float(np.ceil(top[0]['peak'] + 1))]},
    'zones': {
        'reservoirs': {'mean': res_mean, 'px': res_px, 'items': [{k: r[k] for k in ('name', 'km2', 'mean', 'at', 'cover')} for r in reservoirs],
                       'nodata': nodata, 'solar': [{k: r[k] for k in ('name', 'km2', 'mean', 'at', 'solar')} for r in solar_res]},
        'forest': {'mean': forest_mean, 'px': forest_px, 'km2': round(to_m(forest_g).area / 1e6, 1)},
        'industrial': {'mean': ind_mean, 'px': ind_px, 'km2': round(to_m(ind).area / 1e6, 1)},
    },
    'hot': top,
    'shapes': {
        'reservoirs': [enc(r['g']) for r in reservoirs + solar_res],
        'forest': enc(ccnr),
        'industrial': enc(ind, 0.00015),
        'land': enc(D['land'], 0.00012),
    },
}
open(os.path.join(OUT, 'lst.js'), 'w', encoding='utf-8').write('window.DAY29 = ' + json.dumps(out, separators=(',', ':')) + ';\n')
print('json bytes', os.path.getsize(os.path.join(OUT, 'lst.js')))
