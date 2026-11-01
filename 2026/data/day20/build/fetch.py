"""Day 20 raw download: HDB resale flat prices, every transaction from Jan 2017 to the latest month.
Source: data.gov.sg, "Resale flat prices based on registration date from Jan-2017 onwards"
(dataset d_8b84c4ee58e3cfc0ece0d773c8ca6abc), fetched with the v2 download flow:
initiate-download, then poll-download until a signed URL comes back, then the CSV itself.
Requirements: requests (pip install requests h3).
usage: python fetch.py <raw_dir>        (always re-downloads, so a re-run picks up the newest month)
"""
import sys, os, time, json, requests

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
DS = 'd_8b84c4ee58e3cfc0ece0d773c8ca6abc'
API = f'https://api-open.data.gov.sg/v1/public/api/datasets/{DS}'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}


def get_json(url):
    for attempt in range(8):
        r = requests.get(url, headers=UA, timeout=60)
        if r.status_code == 429:
            wait = 15 * (attempt + 1); print('429, waiting', wait); time.sleep(wait); continue
        r.raise_for_status()
        return r.json()
    raise SystemExit('data.gov.sg kept answering 429; try again later')


meta = get_json(f'https://api-production.data.gov.sg/v2/public/api/datasets/{DS}/metadata')
json.dump(meta, open(os.path.join(RAW, 'resale_metadata.json'), 'w'), indent=1)
print('dataset:', meta.get('data', {}).get('name'), '| last updated:', meta.get('data', {}).get('lastUpdatedAt'))

init = get_json(f'{API}/initiate-download')
print('initiate:', init.get('code'), init.get('errorMsg') or init.get('data', {}).get('message'))
url = None
for attempt in range(20):
    time.sleep(4)
    p = get_json(f'{API}/poll-download')
    d = p.get('data') or {}
    if p.get('code') == 0 and d.get('url'):
        url = d['url']; break
    print('poll', attempt, d.get('status') or p.get('errorMsg'))
if not url:
    raise SystemExit('poll-download never returned a URL')
csv = requests.get(url, headers=UA, timeout=600).content
out = os.path.join(RAW, 'resale_2017on.csv')
open(out, 'wb').write(csv)
print('saved', out, len(csv), 'bytes,', csv.count(b'\n') - 1, 'rows')
