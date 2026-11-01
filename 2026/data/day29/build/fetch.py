"""Day 29 (Raster): fetch everything the build needs. Re-runnable; skips files it already has.

Requires python 3.10+ with: requests numpy rasterio pyproj shapely  (run osm.py first: it needs osm.pkl)
  (the whole build: pip install requests numpy rasterio pyproj shapely pillow scipy osmium)
usage: python -I fetch.py <raw-dir>

1. OpenStreetMap: the daily Singapore extract from download.openstreetmap.fr (fetched by build.sh
   before osm.py runs; this script only checks it is there).
2. Landsat Collection 2 Level-2 (USGS), from Microsoft Planetary Computer's public STAC:
   every Landsat 8 and 9 scene over Singapore from 1 Jan 2025 to 31 Oct 2026 (all are WRS-2 path
   125, row 59, passing at about 11:16 a.m. Singapore time). For each we read the QA_PIXEL band
   over Singapore and keep the Tier 1 scenes where at least 75% of Singapore's land is clear: no
   fill, cloud, dilated cloud, cirrus or cloud shadow flag. For those we download ST_B10 (surface
   temperature), QA_PIXEL and ST_QA (temperature uncertainty), cropped to Singapore.
   Assets are signed through the public SAS endpoint; no key is needed.

Writes into <raw-dir>/landsat/: survey.json (every scene and its clear fraction), and for each kept
scene <id>/st_b10.tif, qa_pixel.tif, st_qa.tif, item.json, mtl.json.
"""
import json
import os
import pickle
import sys
import time

import numpy as np
import rasterio
import rasterio.features
import requests
import shapely
from pyproj import Transformer
from rasterio.windows import from_bounds

RAW = sys.argv[1]
OUT = os.path.join(RAW, 'landsat')
os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day29/1.0 (static map page)'}
STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/search'
SIGN = 'https://planetarycomputer.microsoft.com/api/sas/v1/sign'
BBOX = (103.59, 1.15, 104.10, 1.48)          # Singapore and its islands, lon/lat
DATES = '2025-01-01/2026-10-31'
MIN_CLEAR = 0.75

if not os.path.exists(os.path.join(RAW, 'osm.pkl')):
    sys.exit('run osm.py first')


def get(url, **kw):
    for i in range(6):
        try:
            r = requests.get(url, headers=UA, timeout=90, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.RequestException(f'HTTP {r.status_code}')
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            print('retry', url[:80], e)
            time.sleep(15 * (i + 1))
    sys.exit(f'failed: {url}')


def sign(href):
    return get(SIGN, params={'href': href}).json()['href']


# ---- search ----
items, body = [], {'collections': ['landsat-c2-l2'], 'bbox': list(BBOX), 'datetime': DATES, 'limit': 100,
                   'query': {'platform': {'in': ['landsat-8', 'landsat-9']}}}
url = STAC
while url:
    r = requests.post(url, json=body, headers=UA, timeout=120)
    r.raise_for_status()
    page = r.json()
    items += page['features']
    nxt = [l for l in page.get('links', []) if l.get('rel') == 'next']
    url, body = (nxt[0]['href'], nxt[0].get('body', body)) if nxt else (None, None)
    time.sleep(1)
items.sort(key=lambda f: f['properties']['datetime'])
print(len(items), 'scenes')

# ---- Singapore's land on the Landsat grid (UTM 48N, 30 m) ----
D = pickle.load(open(os.path.join(RAW, 'osm.pkl'), 'rb'))
tr = Transformer.from_crs(4326, 32648, always_xy=True)
xs, ys = zip(*[tr.transform(x, y) for x in (BBOX[0], BBOX[2]) for y in (BBOX[1], BBOX[3])])
box = (min(xs), min(ys), max(xs), max(ys))
land_utm = shapely.transform(D['land'], lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


def crop(href, out=None):
    with rasterio.open(sign(href)) as src:
        win = from_bounds(*box, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=win, boundless=True, fill_value=0)
        prof = src.profile.copy()
        prof.update(width=data.shape[1], height=data.shape[0], transform=src.window_transform(win), driver='GTiff',
                    compress='deflate', tiled=False)
        prof.pop('blockxsize', None)
        prof.pop('blockysize', None)
    if out:
        with rasterio.open(out, 'w', **prof) as dst:
            dst.write(data, 1)
    return data, prof


# ---- survey: how much of Singapore's land is clear in each scene ----
survey_fn = os.path.join(OUT, 'survey.json')
survey = json.load(open(survey_fn)) if os.path.exists(survey_fn) else {}
for f in items:
    sid, p = f['id'], f['properties']
    if sid in survey:
        continue
    if p['eo:cloud_cover'] > 60:        # whole-scene cloud; Singapore can't be 80% clear
        survey[sid] = {'datetime': p['datetime'], 'scene_cloud': p['eo:cloud_cover'], 'clear': None}
        continue
    q, prof = crop(f['assets']['qa_pixel']['href'])
    land = rasterio.features.rasterize([land_utm], out_shape=q.shape, transform=prof['transform']) > 0
    bad = (q & 0b11111) > 0           # bits 0-4: fill, dilated cloud, cirrus, cloud, cloud shadow
    clear = float(1 - (bad & land).sum() / land.sum())
    survey[sid] = {'datetime': p['datetime'], 'scene_cloud': p['eo:cloud_cover'], 'clear': round(clear, 4)}
    print(sid, p['datetime'][:16], 'Singapore land clear', round(clear, 3), flush=True)
    json.dump(survey, open(survey_fn, 'w'), indent=1)
    time.sleep(1)
json.dump(survey, open(survey_fn, 'w'), indent=1)

# ---- download the clear scenes ----
keep = [f for f in items if survey[f['id']]['clear'] and survey[f['id']]['clear'] >= MIN_CLEAR and f['id'].endswith('_T1')]
print('kept', [f['id'] for f in keep])
for f in keep:
    d = os.path.join(OUT, f['id'])
    os.makedirs(d, exist_ok=True)
    json.dump(f, open(os.path.join(d, 'item.json'), 'w'), indent=1)
    mtl = os.path.join(d, 'mtl.json')      # USGS metadata: scene time and the ST_B10 scale and offset
    if not os.path.exists(mtl):
        open(mtl, 'wb').write(get(sign(f['assets']['mtl.json']['href'])).content)
    for band in ('lwir11', 'qa_pixel', 'qa'):   # ST_B10, QA_PIXEL, ST_QA in the STAC item's asset names
        name = {'lwir11': 'st_b10', 'qa_pixel': 'qa_pixel', 'qa': 'st_qa'}[band]
        out = os.path.join(d, name + '.tif')
        if os.path.exists(out):
            continue
        crop(f['assets'][band]['href'], out)
        print(f['id'], name)
        time.sleep(1)
