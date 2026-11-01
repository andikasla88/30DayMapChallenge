"""Day 18 (NULL): fetch everything the build needs. Re-runnable; skips files it already has.

Requires python 3.10+ with: requests
  (the whole build: pip install requests shapely pyproj numpy rasterio pillow pyshp scipy)
usage: python -I fetch.py <raw-dir>

Writes into <raw-dir>:
  epsg/*.json          EPSG Geodetic Parameter Dataset (apps.epsg.org API): CRS 3414 (SVY21 / Singapore TM),
                       its conversion 19864, datum 6757, the SVY21 to WGS 84 transformation 8886, extent 1210.
  osm/*.json           OpenStreetMap through Overpass: coastlines from Singapore down to Karimun; named islands,
                       islets, rocks and seamark buoys/lights near SVY21 (0, 0); charted sea areas (anchorages,
                       cables) around it; the admin areas that hold it (is_in); and coastline near the two
                       candidates for land nearest WGS84 (0, 0). Plus one Nominatim reverse lookup to name that coast.
                       (Public Overpass servers were overloaded on 1 Nov 2026; the script rotates between three and
                       backs off, so a run can take a while.)
  mr/*.json            Marine Regions (Flanders Marine Institute) WFS: which maritime zone and IHO sea area holds
                       each null point, the country of the land nearest SVY21 (0, 0), the maritime boundary lines
                       around Singapore, and two IHO sea polygons.
  ne_10m_land.zip      Natural Earth 1:10m land, to find which coast is nearest WGS84 (0, 0).
  ndbc_13010.html      NOAA NDBC station page for the PIRATA buoy "Soul" at 0 N, 0 E.
  dgs/*.geojson|csv    data.gov.sg: SLA National Map Polygon (Singapore's land) and the point datasets that
                       scan.py checks for null records. dgs/catalogue.json is the full catalogue listing.
  s2/                  A Sentinel-2 L2A true-colour crop around SVY21 (0, 0) (Element 84 Earth Search, AWS open data).
"""
import json
import os
import sys
import time

import requests

RAW = sys.argv[1]
UA = {'User-Agent': '30DayMapChallenge-day18/1.0 (static map page; contact via github.com/andikasla88)'}
for sub in ('epsg', 'osm', 'mr', 'dgs', 's2'):
    os.makedirs(os.path.join(RAW, sub), exist_ok=True)

ZERO = (103.58175180795382, 1.0162642548260417)   # SVY21 (0, 0) in WGS 84; process.py recomputes and checks it


def have(path, min_size=50):
    return os.path.exists(path) and os.path.getsize(path) > min_size


def get(url, out, params=None, data=None, min_size=50, tries=5, timeout=300, check=None):
    """GET (or POST when data is given) to a file, politely: back off on 429/5xx, skip if already fetched."""
    if have(out, min_size):
        return out
    for i in range(tries):
        try:
            r = (requests.post(url, data=data, headers=UA, timeout=(30, timeout)) if data is not None
                 else requests.get(url, params=params, headers=UA, timeout=(30, timeout)))
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f'{r.status_code}')
            r.raise_for_status()
            if check and not check(r.content):
                raise requests.HTTPError('unexpected body: ' + r.content[:120].decode('utf-8', 'replace'))
            with open(out + '.part', 'wb') as f:
                f.write(r.content)
            os.replace(out + '.part', out)
            print(os.path.basename(out), len(r.content), 'bytes')
            time.sleep(1)
            return out
        except requests.RequestException as e:
            print('  retry', i + 1, url[:90], e)
            time.sleep(10 * (i + 1))
    raise SystemExit(f'download failed: {url}')


is_json = lambda b: b.lstrip()[:1] in (b'{', b'[')

# ---- EPSG registry ----
EPSG = 'https://apps.epsg.org/api/v1/'
for name, path in [('crs_3414', 'CoordRefSystem/3414/'), ('conversion_19864', 'Conversion/19864/'),
                   ('datum_6757', 'Datum/6757/'), ('transformation_8886', 'Transformation/8886/'),
                   ('extent_1210', 'Extent/1210/')]:
    get(EPSG + path, os.path.join(RAW, 'epsg', name + '.json'), check=is_json)
get(EPSG + 'CoordRefSystem/3414/export/', os.path.join(RAW, 'epsg', 'crs_3414.wkt'), params={'format': 'wkt', 'formatVersion': '2'})

# ---- OpenStreetMap via Overpass (mail.ru first: it was the one answering, and current, on 1 Nov 2026) ----
OVERPASS = ['https://maps.mail.ru/osm/tools/overpass/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
            'https://overpass-api.de/api/interpreter']


def overpass(query, out):
    if have(os.path.join(RAW, 'osm', out), 200):
        return
    for i in range(6):
        url = OVERPASS[i % len(OVERPASS)]
        try:
            r = requests.post(url, data={'data': query}, headers=UA, timeout=(30, 300))
            if r.ok and is_json(r.content):
                with open(os.path.join(RAW, 'osm', out), 'wb') as f:
                    f.write(r.content)
                print(out, len(r.content), 'bytes from', url)
                time.sleep(3)
                return
            print('  overpass', url, r.status_code)
        except requests.RequestException as e:
            print('  overpass', url, e)
        time.sleep(15 * (i + 1))
    raise SystemExit('overpass failed: ' + out)


overpass('[out:json][timeout:180];(way["natural"="coastline"](0.75,103.20,1.50,104.15););out geom;', 'coast_sg.json')
overpass('[out:json][timeout:120][bbox:0.75,103.30,1.30,103.85];(node["place"~"^(island|islet)$"];way["place"~"^(island|islet)$"];'
         'relation["place"~"^(island|islet)$"];node["seamark:type"];node["natural"~"^(rock|bare_rock|reef|shoal)$"];'
         'way["natural"~"^(reef|shoal|bare_rock)$"];);out tags center;', 'near.json')
overpass('[out:json][timeout:120][bbox:0.85,103.40,1.20,103.80];(way["seamark:type"];);out tags geom;', 'seaways.json')
# Which administrative areas hold SVY21 (0, 0).
overpass(f'[out:json][timeout:60];is_in({ZERO[1]},{ZERO[0]})->.a;area.a["admin_level"];out tags;', 'isin_zero.json')
# The coastline vertex nearest to it: process.py finds the exact nearest point; a vertex is enough to ask
# Marine Regions (below) which country the land belongs to.
import math  # noqa: E402
_best = None
for w in json.load(open(os.path.join(RAW, 'osm', 'coast_sg.json'), encoding='utf-8'))['elements']:
    for p in w.get('geometry', []):
        d = math.hypot((p['lat'] - ZERO[1]) * 110574, (p['lon'] - ZERO[0]) * 111300)
        if _best is None or d < _best[0]:
            _best = (d, p['lat'], p['lon'])
# The two coasts Natural Earth puts nearest WGS84 (0, 0): Cape Three Points (Ghana) and Ilheu das Rolas (Sao Tome).
overpass('[out:json][timeout:120];(way["natural"="coastline"](4.3,-2.8,5.2,-1.6););out geom;', 'coast_gh.json')
overpass('[out:json][timeout:120];(way["natural"="coastline"](-0.1,6.3,0.5,6.8););out geom;', 'coast_st.json')
# Name the place: Nominatim (one request) at the Ghana coastline vertex nearest 0, 0.
_gh = min(((p['lat'], p['lon']) for w in json.load(open(os.path.join(RAW, 'osm', 'coast_gh.json'), encoding='utf-8'))['elements']
           for p in w.get('geometry', [])), key=lambda q: math.hypot(*q))
get('https://nominatim.openstreetmap.org/reverse', os.path.join(RAW, 'osm', 'nearest_gh_reverse.json'), check=is_json,
    params={'format': 'jsonv2', 'lat': f'{_gh[0]:.6f}', 'lon': f'{_gh[1]:.6f}', 'zoom': 14, 'accept-language': 'en'})

# ---- Marine Regions (VLIZ) WFS ----
MRW = 'https://geo.vliz.be/geoserver/MarineRegions/wfs'
POINTS = {'svy21': f'{ZERO[0]} {ZERO[1]}', 'wgs84': '0 0'}
LAYERS = {'eez': 'mrgid,geoname,territory1,sovereign1,pol_type', 'eez_12nm': 'mrgid,geoname,territory1,sovereign1,pol_type',
          'eez_24nm': 'mrgid,geoname,territory1,sovereign1,pol_type', 'eez_internal_waters': 'mrgid,geoname,territory1,sovereign1,pol_type',
          'eez_archipelagic_waters': 'mrgid,geoname,territory1,sovereign1,pol_type', 'high_seas': 'mrgid,name,source', 'iho': 'mrgid,name'}
for pname, pt in POINTS.items():
    for layer, props in LAYERS.items():
        get(MRW, os.path.join(RAW, 'mr', f'{pname}_{layer}.json'), check=is_json, params={
            'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature', 'typeName': f'MarineRegions:{layer}',
            'outputFormat': 'application/json', 'propertyName': props, 'CQL_FILTER': f'INTERSECTS(the_geom,POINT({pt}))'})
# The country of the land nearest SVY21 (0, 0): Marine Regions' union of each country's land and waters.
get(MRW, os.path.join(RAW, 'mr', 'nearest_land_country.json'), check=is_json, params={
    'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature', 'typeName': 'MarineRegions:eez_land',
    'outputFormat': 'application/json', 'propertyName': 'union,territory1,sovereign1,iso_ter1',
    'CQL_FILTER': f'INTERSECTS(the_geom,POINT({_best[2]} {_best[1]}))'})
# Maritime boundary lines (treaty and median lines) between Singapore, Indonesia and Malaysia.
get(MRW, os.path.join(RAW, 'mr', 'boundaries_sg.json'), check=is_json, params={
    'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature', 'typeName': 'MarineRegions:eez_boundaries',
    'outputFormat': 'application/json', 'bbox': '103.0,0.6,104.6,1.7'})
for mrgid, name in [(4336, 'singapore_strait'), (4286, 'gulf_of_guinea')]:
    get(MRW, os.path.join(RAW, 'mr', f'iho_{name}.json'), check=is_json, params={
        'service': 'WFS', 'version': '1.0.0', 'request': 'GetFeature', 'typeName': 'MarineRegions:iho',
        'outputFormat': 'application/json', 'CQL_FILTER': f'mrgid={mrgid}'})

# ---- Natural Earth, NOAA NDBC ----
get('https://naciscdn.org/naturalearth/10m/physical/ne_10m_land.zip', os.path.join(RAW, 'ne_10m_land.zip'), min_size=100_000)
get('https://www.ndbc.noaa.gov/station_page.php', os.path.join(RAW, 'ndbc_13010.html'), params={'station': '13010'})

# ---- data.gov.sg ----
DGS_LIST = 'https://api-production.data.gov.sg/v2/public/api/datasets'
DGS_POLL = 'https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download'
cat_path = os.path.join(RAW, 'dgs', 'catalogue.json')
if not have(cat_path):
    allds, page = [], 1
    while True:
        r = None
        for i in range(6):
            r = requests.get(DGS_LIST, params={'page': page}, headers=UA, timeout=60)
            if r.status_code != 429:
                break
            time.sleep(10 * (i + 1))
        r.raise_for_status()
        d = r.json()['data']
        allds += d['datasets']
        if not d['datasets'] or page >= d.get('totalPages', page):
            break
        page += 1
        time.sleep(.4)
    json.dump(allds, open(cat_path, 'w', encoding='utf-8'))
    print('catalogue', len(allds), 'datasets')

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_list import LAND, SCAN   # noqa: E402  (dataset ids live in one place, shared with scan.py)


def dgs(dataset_id, ext):
    out = os.path.join(RAW, 'dgs', f'{dataset_id}.{ext}')
    if have(out, 100):
        return
    meta = os.path.join(RAW, 'dgs', f'{dataset_id}.meta.json')
    get(f'https://api-production.data.gov.sg/v2/public/api/datasets/{dataset_id}/metadata', meta, check=is_json)
    for i in range(8):
        r = requests.get(DGS_POLL.format(dataset_id), headers=UA, timeout=60)
        if r.status_code == 429:
            time.sleep(15 * (i + 1))
            continue
        r.raise_for_status()
        d = r.json().get('data') or {}
        if d.get('url'):
            get(d['url'], out, min_size=100)
            time.sleep(3)
            return
        # not ready yet: ask data.gov.sg to prepare it, then poll again
        requests.get(DGS_POLL.replace('poll-download', 'initiate-download').format(dataset_id), headers=UA, timeout=60)
        time.sleep(6)
    raise SystemExit('data.gov.sg download failed: ' + dataset_id)


dgs(LAND, 'geojson')
for dataset_id, kind in SCAN:
    dgs(dataset_id, 'csv' if kind == 'csv' else 'geojson')

# ---- Sentinel-2 L2A around SVY21 (0, 0), Element 84 Earth Search (no key) ----
s2_items = os.path.join(RAW, 's2', 'search.json')
if not have(s2_items):
    body = {'collections': ['sentinel-2-l2a'], 'intersects': {'type': 'Point', 'coordinates': list(ZERO)},
            'datetime': '2025-11-01T00:00:00Z/2026-10-31T23:59:59Z', 'limit': 100,
            'query': {'eo:cloud_cover': {'lt': 20}}, 'sortby': [{'field': 'properties.datetime', 'direction': 'desc'}]}
    r = requests.post('https://earth-search.aws.element84.com/v1/search', json=body, headers=UA, timeout=120)
    r.raise_for_status()
    open(s2_items, 'wb').write(r.content)
    print('sentinel-2 search', len(r.json().get('features', [])), 'items')
print('fetch done')
