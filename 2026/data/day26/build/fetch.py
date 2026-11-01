"""Day 26 · Water: download the raw inputs into <raw dir> (default ./raw). Re-runnable; skips files already there.

Requirements: Python 3.10+ standard library only.
  - Copernicus GLO-90 DEM tiles (ESA, via the AWS open-data bucket; no key)
  - OpenStreetMap daily extracts for Singapore and Malaysia (openstreetmap.fr)
  - OneMap search (SLA) for the plants OpenStreetMap does not name
Then run osm_extract.py and process.py.
"""
import json, os, sys, time, urllib.parse, urllib.request

RAW = sys.argv[1] if len(sys.argv) > 1 else 'raw'
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day26/1.0 (static map build)'}


def get(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        print('have', path); return
    print('get', url)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=600) as r, open(path, 'wb') as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(10 * (attempt + 1)); continue
            raise
    raise SystemExit('gave up on ' + url)


for t in ('N01_00_E103_00', 'N01_00_E104_00', 'N02_00_E103_00'):
    n = f'Copernicus_DSM_COG_30_{t}_DEM'
    get(f'https://copernicus-dem-90m.s3.amazonaws.com/{n}/{n}.tif', os.path.join(RAW, n + '.tif'))
for f in ('singapore-latest.osm.pbf', 'malaysia-latest.osm.pbf'):
    get('https://download.openstreetmap.fr/extracts/asia/' + f, os.path.join(RAW, f))

# OneMap's public search: the plants OSM lacks by name. One request at a time, gently.
QUERIES = ['SINGSPRING DESALINATION PLANT', 'TUAS DESALINATION PLANT', 'TUAS SOUTH DESALINATION PLANT', 'JURONG ISLAND DESALINATION PLANT',
           'MARINA EAST DESALINATION PLANT', 'ULU PANDAN NEWATER PLANT', 'CHANGI NEWATER FACTORY', 'KRANJI WATER RECLAMATION PLANT']
out_p = os.path.join(RAW, 'onemap_plants.json')
if not os.path.exists(out_p):
    res = {}
    for q in QUERIES:
        u = 'https://www.onemap.gov.sg/api/common/elastic/search?' + urllib.parse.urlencode({'searchVal': q, 'returnGeom': 'Y', 'getAddrDetails': 'Y', 'pageNum': 1})
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60) as r:
            res[q] = json.load(r).get('results', [])
        time.sleep(1)
    json.dump(res, open(out_p, 'w'), indent=1)
print('done')
