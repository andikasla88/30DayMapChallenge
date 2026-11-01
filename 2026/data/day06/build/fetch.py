"""Day 06 raw downloads -> scratchpad/raw/day06 (not the repo).
usage: python fetch.py <raw_dir>
"""
import sys, time, os, json, requests
RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
DATASETS = {
    'hdb_property.csv': 'd_17f5382f26140b1fdae0ba2ef6239d2f',      # HDB Property Information
    'hdb_buildings.geojson': 'd_16b157c52ed637edd6ba1232e026258d',  # HDB Existing Building
    'planning_areas.geojson': 'd_4765db0e87b9c86336792efe8a1f7a66', # URA MP2019 planning areas (no sea)
}
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
for name, ds in DATASETS.items():
    out = os.path.join(RAW, name)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        print('have', name); continue
    for attempt in range(10):
        r = requests.get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{ds}/poll-download', headers=UA, timeout=60).json()
        if r.get('code') == 0 and r['data'].get('url'):
            break
        print(name, r.get('name'), 'retrying'); time.sleep(12)
    data = requests.get(r['data']['url'], timeout=300).content
    open(out, 'wb').write(data)
    print('got', name, len(data))
    time.sleep(12)
