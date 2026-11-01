"""Day 15 (Inside out): names, distances, the 1973 waterline and the Landsat picture.

Requires: numpy shapely pyproj rasterio pillow scipy   (run osm_names.py first)
usage: python -I process.py <raw-dir> <out-dir>
  reads  <raw-dir>/osm.pkl, <raw-dir>/mss/*.tif, notes.json (next to this script)
  writes <out-dir>/inside-out.json, <out-dir>/landsat-1973.jpg

Method, in plain words
  Names     Every OSM street, place, MRT station, park, cape, beach and island in Singapore whose
            name holds tanjong/telok/pasir/pantai/kuala/beach/pulau is grouped under the place
            name it carries ("Telok Blangah Street 31" -> "Telok Blangah"). Street segments are
            merged by name. Facilities named after a place (port terminals, industrial parks)
            don't count when we measure.
  Distance  For each place name we take the point of all its streets, stations and places that
            lies nearest the sea, and measure from there to today's coastline (OSM natural=
            coastline, the mean high-water line) in SVY21 metres. Marina Bay and Kallang Basin
            are freshwater behind Marina Barrage, so they are not sea.
  1973      Landsat 1 MSS, 17 Oct 1973, band 7 (near-infrared, 0.8-1.1 um), 60 m pixels. Water
            absorbs near-infrared, so pixels at or below 42 (of 255) are water; that threshold
            sits between open water (10-30) and the darkest city blocks (~45+). Water joined to
            the open sea, after a 3x3 opening that cuts rivers narrower than ~180 m, is the 1973
            sea, except under cloud (the USGS cloud flag, widened 180 m), where we assume the
            shore hasn't moved, and specks of "land" far out at sea (haze). New land is today's
            land inside the OSM coastline, minus OSM inland water, minus 1973 land; reservoirs
            that were sea in 1973 (Marina Bay and others) are counted apart. Thin strips under
            ~90 m wide between the two coastlines are dropped as noise.
  Status    "still by the sea" if it comes within 250 m of today's coast; otherwise "the sea has
            moved" when a source says it was on the shore or it was within 250 m of the 1973
            waterline; otherwise "can't tell". Island names whose spot is now inside other land
            are "no longer an island".
"""
import json
import os
import pickle
import re
import sys
from collections import defaultdict

import numpy as np
import rasterio
import rasterio.features
import shapely
from PIL import Image
from pyproj import Transformer
from rasterio.warp import Resampling, reproject
from scipy import ndimage as ndi
from shapely.ops import unary_union

RAW, OUT = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
NOTES = json.load(open(os.path.join(HERE, 'notes.json'), encoding='utf-8'))
D = pickle.load(open(os.path.join(RAW, 'osm.pkl'), 'rb'))

NEAR = 250            # metres: "still by the sea"
WATER_DN = 42         # MSS band 7 digital number at or below which a pixel is water
SLIVER = 45           # metres: strips thinner than 2 x this between the two coastlines are noise
EXTENT = (103.45, 1.05, 104.25, 1.62)   # w, s, e, n of the Landsat crop and the picture (as in fetch.py)


def proj(src, dst):
    t = Transformer.from_crs(src, dst, always_xy=True)
    return lambda g: shapely.transform(g, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))


to_m, to_ll = proj(4326, 3414), proj(3414, 4326)
utm_to_m = proj(32648, 3414)

# ---------------- today's coast and land ----------------
sg_ll = D['sg']
sg = to_m(sg_ll)
coast = to_m(shapely.MultiLineString(D['coast']))
land = to_m(D['land']).intersection(sg)
box_m = to_m(shapely.box(*EXTENT))
print(f'today: land in Singapore {land.area / 1e6:.1f} km2 (OSM coastline)')

# ---------------- 1973 waterline from Landsat ----------------
mss = os.path.join(RAW, 'mss')
with rasterio.open(os.path.join(mss, 'nir09.tif')) as src:
    nir = src.read(1).astype(np.float32)
    T, CRS = src.transform, src.crs
qa = rasterio.open(os.path.join(mss, 'qa_pixel.tif')).read(1)
cloudy = ndi.binary_dilation((qa & (1 << 3)) > 0, np.ones((7, 7), bool))   # USGS cloud flag, plus 180 m
# Today's land, on the Landsat grid. A 1973 water body counts as sea if it reaches the edge of the
# picture or if most of it is not Singapore land today (the Johor Strait west of the Causeway is
# cut off from the edge by cloud and a narrow neck at Tuas). Reservoirs, ponds and rivers lie on
# today's land, so they stay out. Specks of "land" at sea that no land stands on today are haze,
# cloud or ships, and are put back into the sea.
m_to_utm = proj(3414, 32648)
land_now = rasterio.features.rasterize([(m_to_utm(land), 1)], out_shape=nir.shape, transform=T, dtype=np.uint8).astype(bool)
sea_now = ~land_now


def sea_mask(dn):
    w = nir <= dn
    lab, k = ndi.label(ndi.binary_opening(w, np.ones((3, 3), bool)))
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    share = ndi.mean(sea_now, lab, np.arange(1, k + 1))
    keep = np.zeros(k + 1, bool)
    keep[edge] = True
    keep[1:][share >= .5] = True
    keep[0] = False
    s = ndi.binary_dilation(keep[lab], np.ones((3, 3), bool)) & w
    lab2, k2 = ndi.label(~s)
    size = ndi.sum(np.ones_like(s), lab2, np.arange(1, k2 + 1))
    on_land = ndi.mean(land_now, lab2, np.arange(1, k2 + 1))
    specks = np.zeros(k2 + 1, bool)
    specks[1:] = (on_land < .05) & (size < 1500)   # under ~5 km2 and almost all at sea today
    s = s | specks[lab2]
    # under cloud we can't see the 1973 shore: assume it is where it is today
    return np.where(cloudy, sea_now, s)


water = nir <= WATER_DN
sea = sea_mask(WATER_DN)


def sea_polygon(mask):
    polys = [shapely.geometry.shape(g) for g, v in rasterio.features.shapes(mask.astype(np.uint8), mask=mask, transform=T) if v == 1]
    return utm_to_m(unary_union(polys))


sea73 = sea_polygon(sea)
frame = box_m.intersection(sg)
# 1973 "land" more than 300 m out to sea from any land today is haze or cloud on the strait
land73 = frame.difference(sea73).intersection(land.buffer(300))
today = land.intersection(box_m)


def tidy(g):   # drop strips thinner than 2 x SLIVER
    return g.buffer(-SLIVER, join_style='mitre').buffer(SLIVER, join_style='mitre').intersection(g)


inland_water = to_m(D['water']).intersection(today)   # reservoirs, ponds and rivers inside today's coastline
added_raw = today.difference(land73)
added = tidy(added_raw.difference(inland_water))       # new dry land
dammed = tidy(added_raw.intersection(inland_water))    # sea or estuary in 1973, fresh water behind a dam or barrage today
lost = tidy(land73.difference(today))
# how much of the coast cloud hid in 1973 (within 1 km of today's coastline, in Singapore)
cloud = utm_to_m(unary_union([shapely.geometry.shape(g) for g, v in rasterio.features.shapes(cloudy.astype(np.uint8), mask=cloudy, transform=T) if v == 1]))
coast_zone = coast.buffer(1000).intersection(frame)
cloud_on_sea = cloud.intersection(coast_zone).area / coast_zone.area * 100   # percent
sens = {}
for dn in (WATER_DN - 6, WATER_DN + 6):   # how much the answer moves with the threshold
    s = sea_mask(dn)
    sens[dn] = tidy(today.difference(frame.difference(sea_polygon(s)).intersection(land.buffer(300))).difference(inland_water)).area / 1e6
print(f'1973: land {land73.area / 1e6:.1f} km2; added since {added.area / 1e6:.1f} km2 '
      f'(raw {added_raw.area / 1e6:.1f}); water that was sea {dammed.area / 1e6:.1f} km2; lost {lost.area / 1e6:.2f} km2; cloud over the coast {cloud_on_sea:.1f}%; '
      f'threshold {WATER_DN - 6}/{WATER_DN + 6}: {sens[WATER_DN - 6]:.1f}/{sens[WATER_DN + 6]:.1f} km2')
waterline73 = shapely.boundary(sea73).intersection(frame.buffer(-120))   # not the frame's own edge
pickle.dump({'today': today, 'land73': land73, 'added': added, 'lost': lost, 'sg': sg}, open(os.path.join(RAW, 'debug.pkl'), 'wb'))   # for checking by eye

# ---------------- names ----------------
KW = re.compile(r'(?<![A-Za-z])(Tanjong|Tanjung|Tg|Telok|Teluk|Pasir|Pantai|Kuala|Beach|Pulau)(?![A-Za-z])')
STOP = set('Road Street Avenue Drive Way Lane Close Crescent Rise Walk View Place Link Terrace Grove Green Heights Hill '
           'Central Promenade Farmway Boulevard Park Gardens Garden Station Terminal Industrial Coast Camp West East '
           'North South Area Estate'.split())
DERIVED = re.compile(r'Terminal|Industrial|Wafer Fab|Coast Industrial')   # facilities named after the place


def toponym(name, kind):
    name = re.sub(r'\s*\(.*?\)', '', name).replace('Paagar', 'Pagar').strip()
    if kind in ('cape', 'island', 'beach'):   # a natural feature's whole name is its name
        return name
    w = name.split()
    i = next(j for j, x in enumerate(w) if KW.fullmatch(x))
    if w[i] == 'Pulau':
        return ' '.join(w[i:])
    if w[i] == 'Beach':
        if i > 0 and w[i - 1] not in ('Jalan', 'Lorong'):
            return w[i - 1] + ' Beach'
        return ' '.join(w[i:i + 2])
    if i + 1 < len(w) and w[i + 1] not in STOP and not w[i + 1][0].isdigit():
        return f'{w[i]} {w[i + 1]}'
    return name


KIND_ORDER = {'place': 0, 'station': 1, 'cape': 2, 'beach': 3, 'island': 4, 'park': 5, 'street': 6}
groups = defaultdict(list)
DROP = re.compile('|'.join(NOTES['drop_names']))
for name, kind, oid, tags, g in D['feats']:
    t = toponym(name, kind)
    t = NOTES['alias'].get(t, t)
    if t in NOTES['drop'] or DROP.search(name):
        continue
    groups[t].append((name, kind, oid, to_m(g)))

sea73_prep = shapely.prepared.prep(sea73)
own_area = {n for n, k, oid, t, g in D['feats'] if k == 'island' and oid[0] != 'n'}
zones = [(n, to_m(g)) for n, g in D['islands'] if n in NOTES['zones']]
out_groups = []
for topo, feats in groups.items():
    note = NOTES['names'].get(topo, {})
    word = KW.search(topo).group(1).replace('Tanjung', 'Tanjong').replace('Teluk', 'Telok').replace('Tg', 'Tanjong')
    members = {}
    for name, kind, oid, g in feats:
        nm = re.sub(r'\s*\(cape\)', '', name).replace('Paagar', 'Pagar')
        dist = g.distance(coast)
        if nm not in members or dist < members[nm][1]:
            members[nm] = (kind if not (kind == 'island' and oid[0] == 'n') else 'island-point', dist, g)
    # the point to measure from: nearest the sea, ignoring facilities named after the place
    core = {k: v for k, v in members.items() if not DERIVED.search(k)} or members
    near_name, (near_kind, d_now, g) = min(core.items(), key=lambda kv: kv[1][1])
    if note.get('from') in members:   # a port's roads carry the name onto new land: measure the place itself
        near_name = note['from']
        near_kind, d_now, g = members[near_name]
    line = shapely.shortest_line(g, coast)
    a, c = shapely.Point(line.coords[0]), shapely.Point(line.coords[-1])
    if d_now < 1:   # touches the coast: anchor at a tidy point on the feature instead
        a = c = shapely.Point(line.coords[0])
    in_sea73 = sea73_prep.contains(a) if box_m.contains(a) else None
    d73 = None if in_sea73 is None else (0 if in_sea73 else a.distance(waterline73))
    zone = next((n for n, zg in zones if zg.contains(a)), None)
    status = None
    if word == 'Pulau':
        if topo in own_area or note.get('island'):   # still an island: label it on the island
            status, d_now, d73 = 'right', 0, None
            a = c = shapely.Point(next(v[2] for k, v in members.items() if v[0] in ('island', 'island-point', 'place')).representative_point().coords[0])
        else:                                        # the name's spot is now inside other land
            status = 'joined'
    if not status:
        if d_now <= NEAR:
            status = 'right'
        elif note.get('shore') or (d73 is not None and d73 <= NEAR):
            status = 'wrong'
        else:
            status = 'unsure'
    kinds = sorted({v[0].replace('island-point', 'island') for v in members.values()}, key=lambda k: KIND_ORDER.get(k, 9))
    out_groups.append({
        'n': topo, 'w': word, 's': status, 'd': round(d_now), 'd73': None if d73 is None else round(d73),
        'sea73': bool(in_sea73), 'via': near_name, 'k': kinds, 'z': zone,
        'a': [round(x, 5) for x in to_ll(a).coords[0]], 'c': [round(x, 5) for x in to_ll(c).coords[0]],
        'm': sorted([[k, v[0].replace('island-point', 'island'), round(v[1])] for k, v in members.items()], key=lambda r: r[2]),
    })

out_groups.sort(key=lambda g: -g['d'])
for g in out_groups:
    print(f"{g['d']:6d} {str(g['d73']):>6s} {g['s']:7s} {g['n']:26s} via {g['via']} ({len(g['m'])})")


# ---------------- compact geometry ----------------
def enc_ring(coords):
    out, px, py = [], 0, 0
    for x, y in coords:
        ix, iy = round(x * 1e5), round(y * 1e5)
        out += [ix - px, iy - py]
        px, py = ix, iy
    return out


def enc_lines(g, tol):
    g = to_ll(shapely.simplify(g, tol))
    parts = getattr(g, 'geoms', [g])
    return [enc_ring(p.coords) for p in parts if p.geom_type == 'LineString' and len(p.coords) > 1]


def enc_polys(g, tol, min_area):
    g = shapely.simplify(g, tol)
    parts = [p for p in getattr(g, 'geoms', [g]) if p.geom_type == 'Polygon' and p.area >= min_area]
    return [[enc_ring(to_ll(r).coords) for r in [p.exterior, *p.interiors]] for p in parts]


coast_sg = shapely.line_merge(coast.intersection(sg.buffer(200)))
geo = {
    'coast': enc_lines(coast_sg, 6),
    'c73': enc_lines(shapely.line_merge(waterline73), 25),
    'added': enc_polys(added, 12, 4000),
}

# ---------------- the 1973 picture: sepia, warped to Web Mercator ----------------
merc = Transformer.from_crs(4326, 3857, always_xy=True)
x0, y0 = merc.transform(EXTENT[0], EXTENT[1])
x1, y1 = merc.transform(EXTENT[2], EXTENT[3])
px = 45.0   # metres per pixel in Web Mercator (~45 m on the ground here), a little finer than the 60 m data
W, H = int(round((x1 - x0) / px)), int(round((y1 - y0) / px))
dst = np.zeros((H, W), np.float32)
clean = np.where(np.abs(nir - ndi.median_filter(nir, size=(3, 1))) > 25, ndi.median_filter(nir, size=(3, 1)), nir)
reproject(clean, dst, src_transform=T, src_crs=CRS, dst_transform=rasterio.transform.from_bounds(x0, y0, x1, y1, W, H),
          dst_crs='EPSG:3857', resampling=Resampling.bilinear)
lo, hi = np.percentile(dst[dst > 0], [1, 99.6])
L = np.clip((dst - lo) / (hi - lo), 0, 1) ** 0.82
dark, mid, light = np.array([20, 14, 9.]), np.array([140, 104, 68.]), np.array([246, 228, 196.])
Lx = L[..., None]
rgb = np.where(Lx < .5, dark + (mid - dark) * (Lx / .5), mid + (light - mid) * ((Lx - .5) / .5))
os.makedirs(OUT, exist_ok=True)
Image.fromarray(rgb.astype(np.uint8)).save(os.path.join(OUT, 'landsat-1973.jpg'), quality=82, optimize=True, progressive=True)
print('picture', W, 'x', H)

mtl = json.load(open(os.path.join(mss, 'mtl.json')))['LANDSAT_METADATA_FILE']
rec = mtl['LEVEL1_PROCESSING_RECORD']
stats = {
    'near': NEAR, 'waterDN': WATER_DN,
    'landToday': round(land.area / 1e6, 1), 'land73': round(land73.area / 1e6, 1),
    'added': round(added.area / 1e6, 1), 'dammed': round(dammed.area / 1e6, 1), 'addedRaw': round(added_raw.area / 1e6, 1), 'lost': round(lost.area / 1e6, 1),
    'addedLo': round(min(sens.values()), 1), 'addedHi': round(max(sens.values()), 1),
    'cloudCoastPct': round(cloud_on_sea, 1),
    'rmse': round(float(rec['GEOMETRIC_RMSE_MODEL'])), 'scene': rec['LANDSAT_PRODUCT_ID'], 'date': mtl['IMAGE_ATTRIBUTES']['DATE_ACQUIRED'],
    'counts': {s: sum(g['s'] == s for g in out_groups) for s in ('wrong', 'joined', 'right', 'unsure')},
}
print(stats)
json.dump({
    'stats': stats,
    'img': {'url': 'data/day15/landsat-1973.jpg', 'coords': [[EXTENT[0], EXTENT[3]], [EXTENT[2], EXTENT[3]], [EXTENT[2], EXTENT[1]], [EXTENT[0], EXTENT[1]]]},
    'geo': geo, 'groups': out_groups,
    'words': NOTES['words'], 'notes': NOTES['names'], 'zones': NOTES['zones'], 'left': NOTES['left_out'],
}, open(os.path.join(OUT, 'inside-out.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('json', os.path.getsize(os.path.join(OUT, 'inside-out.json')), 'bytes;', 'jpg', os.path.getsize(os.path.join(OUT, 'landsat-1973.jpg')), 'bytes')
