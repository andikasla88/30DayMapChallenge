"""Day 16 (Collaborative map): fetch the raw data. Re-runnable; skips files it already has.

Requires python 3.10+ with: requests
usage: python -I fetch.py <raw-dir>

Writes into <raw-dir>:
  singapore-latest.osm.pbf  OpenStreetMap, Singapore extract (daily, from download.openstreetmap.fr).
                  The kopitiams, coffee shops and kopi chains, the coastline and Singapore's national
                  boundary all come from it. Public Overpass servers were unreliable on 1 Nov 2026;
                  the extract is the same OSM data, a few hours old, and kinder to shared servers.
  hawker-centres.geojson    NEA's "Hawker Centres (GEOJSON)" on data.gov.sg (no key needed).
  hawker-centres.meta.json  its data.gov.sg metadata (last updated, publisher).
"""
import json
import os
import sys
import time

import requests

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day16/1.0 (static map page)'}
HAWKERS = 'd_4a086da0a5553be1d89383cd90d07ecd'   # NEA, Hawker Centres (GEOJSON)


def download(url, out, min_size=1000):
    if os.path.exists(out) and os.path.getsize(out) > min_size:
        print('have', os.path.basename(out))
        return
    for i in range(4):
        try:
            with requests.get(url, headers=UA, timeout=(30, 600), stream=True) as r:
                if r.status_code == 429:
                    raise requests.RequestException('429 Too Many Requests')
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
download('https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf',
         os.path.join(RAW, 'singapore-latest.osm.pbf'), 10_000_000)

# ---- NEA hawker centres (data.gov.sg) ----
meta_out = os.path.join(RAW, 'hawker-centres.meta.json')
if not os.path.exists(meta_out):
    meta = requests.get(f'https://api-production.data.gov.sg/v2/public/api/datasets/{HAWKERS}/metadata', headers=UA, timeout=60).json()
    json.dump(meta, open(meta_out, 'w', encoding='utf-8'), indent=1)
    time.sleep(3)
out = os.path.join(RAW, 'hawker-centres.geojson')
if not (os.path.exists(out) and os.path.getsize(out) > 1000):
    for attempt in range(10):
        r = requests.get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{HAWKERS}/poll-download', headers=UA, timeout=60)
        j = r.json() if r.status_code != 429 else {}
        if j.get('code') == 0 and j['data'].get('url'):
            break
        print('hawker centres: not ready or rate-limited, retrying')
        time.sleep(12 * (attempt + 1))
    else:
        sys.exit('hawker centres: poll-download never returned a URL')
    data = requests.get(j['data']['url'], headers=UA, timeout=300).content
    open(out, 'wb').write(data)
    print('hawker-centres.geojson', len(data), 'bytes')
