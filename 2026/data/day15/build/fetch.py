"""Day 15 (Inside out): fetch everything the build needs. Re-runnable; skips files it already has.

Requires python 3.10+ with: requests rasterio pyproj
  (the whole build: pip install requests shapely pyproj numpy rasterio pillow scipy osmium)
usage: python -I fetch.py <raw-dir>

Writes into <raw-dir>:
  singapore-latest.osm.pbf  OpenStreetMap, Singapore extract (daily, from download.openstreetmap.fr).
                  Streets, places, stations, parks, islands, today's coastline (natural=coastline)
                  and Singapore's national boundary all come from it. We meant to use Overpass, but
                  every public Overpass server was unreachable or timing out on 1 Nov 2026; the
                  extract is the same OSM data, a few hours old, and kinder to shared servers.
  mss/*.tif       Landsat 1 MSS, 17 Oct 1973, scene LM01_L1TP_134059_19731017_02_T2: the green,
                  red, nir08 and nir09 bands and qa_pixel, cropped to Singapore, from Microsoft
                  Planetary Computer (USGS Landsat Collection 2 Level-1). Signed through the public
                  SAS endpoint; no key needed.
  mss/item.json, mss/mtl.json  the scene's STAC item and USGS metadata (geometric accuracy).
"""
import json
import os
import sys
import time

import requests

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day15/1.0 (static map page)'}


def download(url, out, min_size=1000):
    if os.path.exists(out) and os.path.getsize(out) > min_size:
        return
    for i in range(4):
        try:
            with requests.get(url, headers=UA, timeout=(30, 600), stream=True) as r:
                r.raise_for_status()
                with open(out + '.part', 'wb') as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            os.replace(out + '.part', out)
            print(os.path.basename(out), os.path.getsize(out), 'bytes')
            return
        except requests.RequestException as e:
            print(url, e)
            time.sleep(20 * (i + 1))
    sys.exit(f'download failed: {url}')


# ---- OpenStreetMap ----
download('https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf', os.path.join(RAW, 'singapore-latest.osm.pbf'), 10_000_000)

# ---- Landsat 1 MSS, 17 October 1973 (Planetary Computer) ----
# Chosen from a STAC search of landsat-c2-l1 over Singapore, 1972-1979: the clearest coast of the
# ten scenes (2% cloud; the 1975 and 1977 scenes have cloud on the south and east coasts).
STAC = 'https://planetarycomputer.microsoft.com/api/stac/v1/collections/landsat-c2-l1/items/'
SIGN = 'https://planetarycomputer.microsoft.com/api/sas/v1/sign'
ITEM = 'LM01_L1TP_134059_19731017_02_T2'
mss = os.path.join(RAW, 'mss')
os.makedirs(mss, exist_ok=True)
item = requests.get(STAC + ITEM, headers=UA, timeout=60).json()
json.dump(item, open(os.path.join(mss, 'item.json'), 'w'), indent=1)
sign = lambda href: requests.get(SIGN, params={'href': href}, headers=UA, timeout=60).json()['href']
if not os.path.exists(os.path.join(mss, 'mtl.json')):
    open(os.path.join(mss, 'mtl.json'), 'wb').write(requests.get(sign(item['assets']['mtl.json']['href']), timeout=60).content)

import rasterio                       # noqa: E402  (only needed for the imagery)
from rasterio.windows import from_bounds  # noqa: E402
from pyproj import Transformer        # noqa: E402

# Singapore and its strait, in the scene's UTM 48N grid
tr = Transformer.from_crs(4326, 32648, always_xy=True)
xs, ys = zip(*[tr.transform(x, y) for x in (103.45, 104.25) for y in (1.05, 1.62)])
box = (min(xs), min(ys), max(xs), max(ys))
for band in ('green', 'red', 'nir08', 'nir09', 'qa_pixel'):
    out = os.path.join(mss, f'{band}.tif')
    if os.path.exists(out):
        continue
    with rasterio.open(sign(item['assets'][band]['href'])) as src:
        win = from_bounds(*box, transform=src.transform).round_offsets().round_lengths()
        data = src.read(1, window=win)
        prof = src.profile.copy()
        prof.update(width=data.shape[1], height=data.shape[0], transform=src.window_transform(win), driver='GTiff', compress='deflate', tiled=False)
        prof.pop('blockxsize', None); prof.pop('blockysize', None)
        with rasterio.open(out, 'w', **prof) as dst:
            dst.write(data, 1)
    print(band, data.shape, data.dtype, int(data.min()), int(data.max()))
    time.sleep(1)
