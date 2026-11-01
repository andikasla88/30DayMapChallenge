"""Day 12 (Power) raw downloads. Re-runnable: files already present are kept.

Requires: Python 3.10+, requests  (pip install requests)
usage: python -I fetch.py <raw-dir>

Writes into <raw-dir>:
  SES_tidy.xlsx        EMA, Singapore Energy Statistics 2026, tidy tables workbook. Table T3.5 is
                       "Average Monthly Household Electricity Consumption by Planning Area &
                       Dwelling Type", monthly from Jan 2005 (data for 2026 is to Jun 2026).
                       data.gov.sg only carries EMA's planning-area tables for single years
                       2009-2013 (d_634194a40f36e5bc11a942ab0164fa9d and siblings), so the monthly
                       series comes from EMA's own SES download.
  pa2019.geojson       URA Master Plan 2019 Planning Area Boundary (No Sea), data.gov.sg
                       d_4765db0e87b9c86336792efe8a1f7a66, via the initiate/poll download flow.
  tengeh_osm.json      OpenStreetMap, via Overpass: the floating solar plant on Tengeh Reservoir
                       (power=plant + floating=yes) and the reservoir itself.
  pub_floating.html    PUB's floating solar page, kept so process.py can check the facts it quotes.
"""
import os
import sys
import time

import requests

RAW = sys.argv[1] if len(sys.argv) > 1 else sys.exit('usage: python -I fetch.py <raw-dir>')
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (30DayMapChallenge day 12 build)'}

EMA_TIDY = 'https://www.ema.gov.sg/content/dam/corporate/resources/singapore-energy-statistics/excel/SES_tidy.xlsx.coredownload.xlsx'
PA2019 = 'd_4765db0e87b9c86336792efe8a1f7a66'
PUB = 'https://www.pub.gov.sg/Public/WaterLoop/Sustainability/Solar/Floating'
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter']
# Tengeh Reservoir sits between Jalan Bahar and the Tuas/Jurong West edge.
BBOX = '1.31,103.64,1.36,103.70'
TENGEH_Q = (f'[out:json][timeout:90];('
            f'way["power"="plant"]({BBOX});relation["power"="plant"]({BBOX});'
            f'way["natural"="water"]["name"~"Tengeh"]({BBOX});relation["natural"="water"]["name"~"Tengeh"]({BBOX}););'
            f'out geom;')


def have(name, min_bytes=1000):
    p = os.path.join(RAW, name)
    return os.path.exists(p) and os.path.getsize(p) >= min_bytes


def save(name, data):
    with open(os.path.join(RAW, name), 'wb') as f:
        f.write(data)
    print(f'{name}: {len(data):,} bytes')


def get(url, **kw):
    for attempt in range(4):
        r = requests.get(url, headers=UA, timeout=120, **kw)
        if r.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return r
    raise SystemExit(f'gave up on {url}')


# 1. EMA SES tidy workbook (the asset path is served without the site's bot check)
if not have('SES_tidy.xlsx'):
    save('SES_tidy.xlsx', get(EMA_TIDY).content)
    time.sleep(1)

# 2. URA MP2019 planning areas, data.gov.sg initiate -> poll -> download
if not have('pa2019.geojson'):
    base = f'https://api-open.data.gov.sg/v1/public/api/datasets/{PA2019}'
    get(f'{base}/initiate-download')
    url = None
    for _ in range(20):
        time.sleep(2)
        d = get(f'{base}/poll-download').json().get('data') or {}
        url = d.get('url')
        if url:
            break
    if not url:
        raise SystemExit('data.gov.sg poll-download never returned a URL')
    save('pa2019.geojson', get(url).content)

# 3. Tengeh floating solar outline from OpenStreetMap (Overpass); gentle, with back-off
if not have('tengeh_osm.json', 200):
    for i, url in enumerate(OVERPASS * 2):
        try:
            r = requests.post(url, data={'data': TENGEH_Q}, headers=UA, timeout=300)
            if r.ok and r.text.lstrip().startswith('{'):
                save('tengeh_osm.json', r.content)
                break
            print('overpass', url, r.status_code)
        except requests.RequestException as e:
            print('overpass', url, e)
        time.sleep(15 * (i + 1))
    else:
        raise SystemExit('every Overpass server failed; try again later')

# 4. PUB's page, for checking the quoted facts
if not have('pub_floating.html'):
    save('pub_floating.html', get(PUB).content)
