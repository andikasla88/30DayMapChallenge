"""Day 21 (OpenStreetMap): fetch everything the build needs. Re-runnable; skips files it already has.

Requires python 3.10+ with: requests
  (the whole build: pip install requests osmium shapely pyproj)
usage: python -I fetch.py <raw-dir>

Writes into <raw-dir>:
  singapore-latest.osm.pbf   OpenStreetMap, Singapore extract (daily, from download.openstreetmap.fr).
                             Every outlet, mall, place name and the coastline come from it. We tried
                             Overpass first, but every public Overpass server timed out on 1 Nov 2026;
                             the extract is the same OSM data, a few hours old, and kinder to shared servers.
  nsi-*.json                 The Name Suggestion Index (osmlab/name-suggestion-index): the brand tags
                             (brand, brand:wikidata, name, cuisine) OSM editors suggest for each chain.
  wikidata.json              Labels and descriptions of every Wikidata item the build uses, so the page
                             only links chains to items that really are those chains.
"""
import json
import os
import sys
import time

import requests

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day21/1.0 (static map page; https://github.com/andikasla88/30DayMapChallenge)'}


def download(url, out, min_size=1000, fresh=False):
    if not fresh and os.path.exists(out) and os.path.getsize(out) > min_size:
        return
    for i in range(4):
        try:
            with requests.get(url, headers=UA, timeout=(30, 600), stream=True) as r:
                if r.status_code == 429:
                    time.sleep(30 * (i + 1))
                    continue
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

# ---- Name Suggestion Index: the brand presets OSM editors offer ----
NSI = 'https://raw.githubusercontent.com/osmlab/name-suggestion-index/main/data/brands/'
for cat in ('amenity/cafe', 'shop/beverages', 'amenity/ice_cream'):
    download(NSI + cat + '.json', os.path.join(RAW, 'nsi-' + cat.replace('/', '-') + '.json'))
    time.sleep(1)

# ---- Wikidata: confirm each item the chain table (process.py) points at ----
sys.dont_write_bytecode = True   # keep build/ free of __pycache__
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chains import CHAINS  # noqa: E402

out = os.path.join(RAW, 'wikidata.json')
if not os.path.exists(out):
    ids = sorted({c['qid'] for c in CHAINS if c.get('qid')})
    for i in range(4):
        r = requests.get('https://www.wikidata.org/w/api.php', headers=UA, timeout=60, params={
            'action': 'wbgetentities', 'ids': '|'.join(ids), 'props': 'labels|descriptions',
            'languages': 'en|zh', 'format': 'json'})
        if r.status_code == 429:
            time.sleep(30 * (i + 1))
            continue
        r.raise_for_status()
        json.dump(r.json(), open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('wikidata.json', len(ids), 'items')
        break
    else:
        sys.exit('Wikidata kept answering 429; try again later')

# ---- Wikidata: look for an item for every chain that has none in chains.py ----
# Keeps hits whose description sounds like a drinks business; process.py stops if any turn up.
out = os.path.join(RAW, 'wikidata-search.json')
if not os.path.exists(out):
    DRINKS = ('tea', 'drink', 'beverage', 'café', 'cafe', 'chain', 'singapore', 'restaurant', 'franchise', 'brand', '茶')
    found = {}
    for c in CHAINS:
        if c.get('qid'):
            continue
        for i in range(4):
            time.sleep(6)
            r = requests.get('https://www.wikidata.org/w/api.php', headers=UA, timeout=60, params={
                'action': 'wbsearchentities', 'search': c['label'], 'language': 'en', 'type': 'item', 'limit': 10, 'format': 'json'})
            if r.status_code == 429:
                time.sleep(30 * (i + 1))
                continue
            r.raise_for_status()
            hits = r.json().get('search', [])
            found[c['label']] = [f"{h['id']} {h.get('label', '')}: {h.get('description', '')}" for h in hits
                                 if any(w in h.get('description', '').lower() for w in DRINKS)]
            print('wikidata search', c['label'], len(hits), 'hits,', len(found[c['label']]), 'like a drinks business')
            break
        else:
            sys.exit('Wikidata kept answering 429; try again later')
    json.dump(found, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
