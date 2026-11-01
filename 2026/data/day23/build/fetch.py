"""Day 23 (Taste): fetch the raw data. Re-runnable; every download is cached in <raw-dir>.

Requires python 3.10+ with: requests            usage: python -I fetch.py <raw-dir>
No API keys.

1. The 2026 list, from two published copies. The official MICHELIN Guide site (guide.michelin.com) answers
   scripts with an AWS WAF challenge (HTTP 202, empty body; checked 1 Nov 2026), so the names come from:
     Eatbook, "Full List Of Michelin Bib Gourmand Singapore Winners For 2026" (28 Jul 2026)
     HungryGoWhere, "Michelin Bib Gourmand Singapore 2026 is out, with a total of 97 affordable eats"
   Both must hold every name in stalls_source.json, and say 97.
2. stalls_source.json (in this folder) is the hand-checked address list: each address and postal code is the
   one on the eatery's MICHELIN Guide page, read through a search engine's index because the site blocks
   scripts (the page URL is kept per eatery). It is an input, not downloaded here.
3. OneMap search, one request per unique postal code (1.2 s apart, backs off on 429), cached as JSON.
4. NEA "Hawker Centres (GEOJSON)" on data.gov.sg, to name the hawker centres.
"""
import json
import os
import re
import sys
import time
import unicodedata

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = sys.argv[1]
os.makedirs(os.path.join(RAW, 'onemap'), exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (30DayMapChallenge day23 build; static map page)'}
LISTS = {
    'eatbook.html': 'https://eatbook.sg/michelin-bib-gourmand-2026/',
    'hungrygowhere.html': 'https://hungrygowhere.com/food-news/michelin-bib-gourmand-singapore-2026-list/',
}
HAWKERS = 'd_4a086da0a5553be1d89383cd90d07ecd'   # NEA, Hawker Centres (GEOJSON)


def get(url, **kw):
    for i in range(5):
        r = requests.get(url, headers=UA, timeout=60, **kw)
        if r.status_code == 429:
            wait = 15 * (i + 1)
            print('429, waiting', wait, 's')
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    sys.exit(f'gave up on {url}')


def text_of(html):
    html = re.sub(r'<script.*?</script>|<style.*?</style>', '', html, flags=re.S)
    import html as H
    return H.unescape(re.sub(r'<[^>]+>', '\n', html))


def norm(s):
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '', s)


# ---- 1. the published lists ----
src = json.load(open(os.path.join(HERE, 'stalls_source.json'), encoding='utf-8'))
for fn, url in LISTS.items():
    out = os.path.join(RAW, fn)
    if not os.path.exists(out):
        open(out, 'w', encoding='utf-8').write(get(url).text)
        time.sleep(2)
    txt = norm(text_of(open(out, encoding='utf-8').read()))
    if '97' not in text_of(open(out, encoding='utf-8').read()):
        sys.exit(f'{fn}: does not mention 97')
    # names as the two lists spell them, where they differ from ours
    alias = {'Xiu Ji Ikan Bilis Yong Tau Fu': ['xujiikanbilis'], 'Yi Pin Wei Braised Duck Kway Chap': ['yipinwei'],
             'Fei Fei Roasted Noodle': ['feifeiroasted'], 'Jungle Thai': ['jungle'], 'Zhup Zhup Noodles': ['zhupzhup'],
             'Indocafé': ['indocaf'], 'The Coconut Club (Beach Road)': ['thecoconutclub']}
    missing = [s['name'] for s in src if norm(s['name']) not in txt and not any(a in txt for a in alias.get(s['name'], []))]
    print(fn, 'missing:', missing or 'none')
    if missing:
        sys.exit('name check failed')

# ---- 3. OneMap ----
postals = sorted({s['postal'] for s in src})
for i, pc in enumerate(postals):
    out = os.path.join(RAW, 'onemap', pc + '.json')
    if os.path.exists(out):
        continue
    r = get('https://www.onemap.gov.sg/api/common/elastic/search',
            params={'searchVal': pc, 'returnGeom': 'Y', 'getAddrDetails': 'Y', 'pageNum': 1})
    open(out, 'w', encoding='utf-8').write(r.text)
    print(f'onemap {i + 1}/{len(postals)} {pc}: {r.json().get("found")} found')
    time.sleep(1.2)

# ---- 4. NEA hawker centres ----
out = os.path.join(RAW, 'hawker-centres.geojson')
if not os.path.exists(out):
    requests.get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{HAWKERS}/initiate-download', headers=UA, timeout=60)
    time.sleep(3)
    for attempt in range(8):
        j = requests.get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{HAWKERS}/poll-download', headers=UA, timeout=60)
        j = j.json() if j.status_code in (200, 201) else {}
        if j.get('code') == 0 and j['data'].get('url'):
            break
        time.sleep(12 * (attempt + 1))
    else:
        sys.exit('hawker centres: no download URL')
    open(out, 'wb').write(get(j['data']['url']).content)
    meta = get(f'https://api-production.data.gov.sg/v2/public/api/datasets/{HAWKERS}/metadata').json()
    json.dump(meta, open(os.path.join(RAW, 'hawker-centres.meta.json'), 'w', encoding='utf-8'), indent=1)
print('done')
