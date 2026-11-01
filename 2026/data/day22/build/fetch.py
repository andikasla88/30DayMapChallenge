"""Day 22 Projections: fetch the raw inputs. Standard library only.

usage: python -I fetch.py <raw-dir>

Writes into <raw-dir> (keep it outside the repo):
  nmp.geojson          SLA National Map Polygon (layer Coastal_Outlines), data.gov.sg
                       dataset d_29f066d67df3eae91df8a42f443863c8, the same file Day 10 used.
  ne_110m_land.geojson Natural Earth 1:110m land polygons, public domain, pinned to the
                       v5.1.2 tag of nvkelso/natural-earth-vector (the world inset).
  ne_110m_populated_places_simple.geojson
                       Natural Earth 1:110m populated places, same tag (city latitudes).
Files already present are kept, so a re-run does not hit the servers again.
"""
import json
import os
import sys
import time
import urllib.request

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day22/1.0'}
NMP = 'd_29f066d67df3eae91df8a42f443863c8'
NE = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/'
NE_FILES = ['ne_110m_land.geojson', 'ne_110m_populated_places_simple.geojson']


def get(url, tries=4):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * 2 ** k)   # back off
                continue
            raise
    raise SystemExit(f'gave up on {url}')


def save(name, data):
    with open(os.path.join(RAW, name), 'wb') as f:
        f.write(data)
    print(name, len(data), 'bytes')


if not os.path.exists(os.path.join(RAW, 'nmp.geojson')):
    poll = json.loads(get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{NMP}/poll-download'))
    url = poll['data']['url']
    time.sleep(1)
    save('nmp.geojson', get(url))
    time.sleep(1)
for name in NE_FILES:
    if not os.path.exists(os.path.join(RAW, name)):
        save(name, get(NE + name))
        time.sleep(1)
