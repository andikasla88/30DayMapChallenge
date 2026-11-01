"""Shared loading for the Day 05 viewshed: OSM buildings, HDB join, terrain."""
import glob, io, json, math, os, re
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import linemerge, polygonize, unary_union

BARGE = (103.8575, 1.2862)          # lng, lat
RADIUS = 8000                        # analysis radius, m
TO_SVY = Transformer.from_crs('EPSG:4326', 'EPSG:3414', always_xy=True)
TO_WGS = Transformer.from_crs('EPSG:3414', 'EPSG:4326', always_xy=True)
BX, BY = TO_SVY.transform(*BARGE)


def num(v):
    if v is None:
        return None
    m = re.match(r'\s*([0-9]+(?:\.[0-9]+)?)', str(v).replace(',', '.'))
    return float(m.group(1)) if m else None


# ---------- OSM ----------
def load_osm(raw):
    """Buildings and building:parts written by osm_from_pbf.py (one GeoJSON feature per line)."""
    from shapely.geometry import shape
    out = []
    for line in open(os.path.join(raw, 'osm_buildings.geojsonl'), encoding='utf-8'):
        f = json.loads(line)
        try:
            geom = shape(f['geom'])
            if not geom.is_valid:
                geom = geom.buffer(0)
        except Exception:
            continue
        if geom.is_empty:
            continue
        tags = f['tags']
        out.append({'id': f['id'], 'tags': tags, 'geom': geom,
                    'part': 'building:part' in tags and 'building' not in tags})
    return out


# ---------- HDB ----------
ABBR = {'STREET': 'ST', 'AVENUE': 'AVE', 'ROAD': 'RD', 'DRIVE': 'DR', 'BUKIT': 'BT', 'CRESCENT': 'CRES',
        'NORTH': 'NTH', 'SOUTH': 'STH', 'CENTRAL': 'CTRL', 'LORONG': 'LOR', 'JALAN': 'JLN', 'CLOSE': 'CL',
        'UPPER': 'UPP', 'PARK': 'PK', 'PLACE': 'PL', 'COMMONWEALTH': 'CWEALTH', 'GARDEN': 'GDN', 'GARDENS': 'GDNS',
        'TERRACE': 'TER', 'HEIGHTS': 'HTS', 'SAINT': 'ST', 'KAMPONG': 'KG', 'TANJONG': 'TG', 'SQUARE': 'SQ',
        'INDUSTRIAL': 'IND', 'MARKET': 'MKT', 'TELUK': 'TELOK', 'AVE.': 'AVE'}


def norm_street(s):
    s = s.upper().replace("'", '').replace('.', ' ').replace('-', ' ')
    return ' '.join(ABBR.get(t, t) for t in s.split())


def norm_blk(s):
    return re.sub(r'^(BLK|BLOCK)\s*', '', s.strip().upper()).replace(' ', '')


GENERIC = {'LOR', 'AVE', 'ST', 'RD', 'DR', 'CRES', 'NTH', 'STH', 'EAST', 'WEST', 'CTRL', 'CL', 'PL', 'LINK', 'WALK', 'VIEW',
           'LANE', 'WAY', 'TER', 'RISE', 'GDN', 'GDNS', 'PK', 'SQ', 'HTS', 'UPP', 'JLN', 'LOOP', 'RING', 'BT', 'KG', 'TG'}


def core_street(s):
    """'LOR 4 TOA PAYOH' -> 'TOA PAYOH': the place words, for a fallback join on block + place."""
    return ' '.join(t for t in norm_street(s).split() if t not in GENERIC and not t[0].isdigit())


def load_hdb(raw):
    """Exact index on (block, street) and a fallback on (block, place words) where unique:
    OSM and HDB sometimes disagree on which lorong or avenue a block is on."""
    rows = json.load(open(os.path.join(raw, 'hdb_property.json')))
    idx, core = {}, {}
    for r in rows:
        idx[(norm_blk(r['blk_no']), norm_street(r['street']))] = r
        k = (norm_blk(r['blk_no']), core_street(r['street']))
        core[k] = None if k in core else r
    return idx, {k: v for k, v in core.items() if v is not None and k[1]}


# Pretty street names for labels: expand the HDB abbreviations.
EXPAND = {'ST': 'St', 'AVE': 'Ave', 'RD': 'Rd', 'DR': 'Dr', 'BT': 'Bukit', 'CRES': 'Cres', 'NTH': 'North', 'STH': 'South',
          'CTRL': 'Central', 'LOR': 'Lorong', 'JLN': 'Jalan', 'CL': 'Close', 'UPP': 'Upper', 'PK': 'Park', 'PL': 'Place',
          "C'WEALTH": 'Commonwealth', 'GDN': 'Garden', 'GDNS': 'Gardens', 'TER': 'Terrace', 'HTS': 'Heights', 'ST.': 'St.',
          'KG': 'Kampong', 'TG': 'Tanjong', 'SQ': 'Square', 'IND': 'Industrial', 'MKT': 'Market'}


def pretty_street(s):
    return ' '.join(EXPAND.get(t, t.capitalize() if not t[0].isdigit() else t) for t in s.split())


# ---------- terrain ----------
def load_terrain(raw, z=14):
    d = os.path.join(raw, f'terrarium{z}')
    ix = json.load(open(os.path.join(d, 'index.json')))
    W = (ix['x1'] - ix['x0'] + 1) * 256
    H = (ix['y1'] - ix['y0'] + 1) * 256
    mosaic = np.zeros((H, W), np.float32)
    for x in range(ix['x0'], ix['x1'] + 1):
        for y in range(ix['y0'], ix['y1'] + 1):
            a = np.asarray(Image.open(os.path.join(d, f'{x}_{y}.png')).convert('RGB'), np.float32)
            e = a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768
            mosaic[(y - ix['y0']) * 256:(y - ix['y0'] + 1) * 256, (x - ix['x0']) * 256:(x - ix['x0'] + 1) * 256] = e
    n = 2 ** z

    def sample(lng, lat):
        px = ((np.asarray(lng) + 180) / 360 * n - ix['x0']) * 256 - 0.5
        lr = np.radians(np.asarray(lat))
        py = ((1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * n - ix['y0']) * 256 - 0.5
        x0 = np.clip(np.floor(px).astype(int), 0, W - 2); y0 = np.clip(np.floor(py).astype(int), 0, H - 2)
        fx = np.clip(px - x0, 0, 1); fy = np.clip(py - y0, 0, 1)
        return (mosaic[y0, x0] * (1 - fx) * (1 - fy) + mosaic[y0, x0 + 1] * fx * (1 - fy)
                + mosaic[y0 + 1, x0] * (1 - fx) * fy + mosaic[y0 + 1, x0 + 1] * fx * fy)
    return sample
