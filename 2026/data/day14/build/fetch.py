"""Day 14 Borgesian map: fetch LTA DataMall's static geospatial layers (and OSM context).
Usage: python -I fetch.py <raw-dir>
Requires: requests  (pip install requests)

Downloads every island-wide geospatial zip linked from the DataMall static-data page
(https://datamall.lta.gov.sg/content/datamall/en/static-data.html), skipping the
"Planned Map Update" one-offs, then unzips each into <raw-dir>/lta/<Name>/.
Also fetches, for the shortlisted streets, OpenStreetMap trees and street centrelines
from Overpass (trees: NParks does not publish its tree inventory as open data).
Re-runnable: files already on disk are kept.
"""
import io, os, re, sys, time, zipfile
import requests

RAW = sys.argv[1]
BASE = 'https://datamall.lta.gov.sg'
PAGE = BASE + '/content/datamall/en/static-data.html'
UA = {'User-Agent': '30DayMapChallenge-day14/1.0 (static map page)'}
os.makedirs(os.path.join(RAW, 'lta'), exist_ok=True)


def get(url, **kw):
    for attempt in range(5):
        r = requests.get(url, headers=UA, timeout=300, **kw)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1)); continue
        r.raise_for_status()
        return r
    raise RuntimeError(f'gave up on {url}')


# 1. The current links (file names carry the month, e.g. LampPost_Sep2026.zip).
html = get(PAGE).text
links = sorted(set(re.findall(r'href="(/content/dam/datamall/datasets/Geospatial/[^"/]+\.zip)"', html)))
skip = ('Traffic_Count_Data', 'Train Station Codes')
links = [l for l in links if not any(s in l for s in skip)]
print(len(links), 'geospatial zips listed')
with open(os.path.join(RAW, 'lta', 'links.txt'), 'w') as f:
    f.write('\n'.join(BASE + l for l in links))

for link in links:
    name = os.path.basename(link)[:-4]
    stem = re.sub(r'_(?:[A-Z][a-z]{2}\d{4})$', '', name)       # LampPost_Sep2026 -> LampPost
    out = os.path.join(RAW, 'lta', stem)
    if os.path.isdir(out) and os.listdir(out):
        continue
    r = get(BASE + requests.utils.quote(link))
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for m in z.infolist():
            if m.is_dir():
                continue
            fn = os.path.basename(m.filename)
            if not fn or '..' in fn:
                continue
            with open(os.path.join(out, fn), 'wb') as g:
                g.write(z.read(m))
    print(stem, len(r.content) // 1024, 'kB')
    time.sleep(1.5)

# 2. OpenStreetMap: trees and named streets over the old town and Joo Chiat.
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
BBOX = '1.270,103.835,1.320,103.910'   # s,w,n,e: Chinatown/Tanjong Pagar to Joo Chiat
Q = {
    'osm_trees.json': f'[out:json][timeout:180];node["natural"="tree"]({BBOX});out;',
    'osm_streets.json': f'[out:json][timeout:180];way["highway"]["name"]({BBOX});out tags geom;',
}
for fn, q in Q.items():
    out = os.path.join(RAW, fn)
    if os.path.exists(out) and os.path.getsize(out) > 500:
        continue
    for url in OVERPASS * 2:
        try:
            r = requests.post(url, data={'data': q}, headers=UA, timeout=400)
            if r.ok and r.text.lstrip().startswith('{'):
                open(out, 'w', encoding='utf-8').write(r.text); print(fn, len(r.text)); break
            print(url, r.status_code, r.text[:160])
        except Exception as e:
            print(url, e)
        time.sleep(10)

# 3. data.gov.sg: NParks heritage trees, and the names of LTA's arrow and lane-marking codes.
#    The DataMall shapefiles carry only a code (TYP_CD); data.gov.sg's GeoJSON copies of the
#    same LTA layers also carry TYP_NAM. The files are streamed and only the code -> name
#    pairs are kept.
DGS = 'https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download'
SETS = {
    'heritage_trees.geojson': 'd_644ff187b6d14d6316f47284a4a6c81f',   # NParks Heritage Trees
    'codes_arrow.json': 'd_2771fb949ceea676dd3eecade3830c5b',          # LTA Arrow Marking (GEOJSON)
    'codes_lane.json': 'd_fa71cc0c433275f4d2b0133358cc4fbf',           # LTA Lane Marking (GEOJSON)
}
import json
for fn, ds in SETS.items():
    out = os.path.join(RAW, fn)
    if os.path.exists(out) and os.path.getsize(out) > 20:
        continue
    url = get(DGS.format(ds)).json()['data']['url']
    if fn.endswith('.geojson'):
        open(out, 'wb').write(get(url).content)
    else:
        pairs, tail = {}, ''
        pat = re.compile(r'"TYP_CD"\s*:\s*"([^"]*)"\s*,\s*"TYP_NAM"\s*:\s*"([^"]*)"')
        with requests.get(url, headers=UA, stream=True, timeout=600) as r:
            r.raise_for_status()
            for chunk in r.iter_content(1 << 20):
                text = tail + chunk.decode('utf-8', 'replace')
                for m in pat.finditer(text):
                    pairs[m.group(1)] = m.group(2)
                tail = text[-400:]
        json.dump(pairs, open(out, 'w'), indent=1)
    print(fn, 'ok')
    time.sleep(2)
