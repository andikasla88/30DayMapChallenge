"""Day 24 Network: fetch LTA's covered linkways and the OpenStreetMap Singapore extract.
Usage: python -I fetch.py <raw-dir>
Requires: requests  (the whole build: pip install requests shapely pyproj pyshp osmium numpy)

1. LTA DataMall "Covered Linkway" (static geospatial data, zipped SVY21 shapefile). The zip's
   name carries the month (e.g. CoveredLinkWay_Sep2026.zip), so the link is read from the
   static-data page, as Day 14's fetch.py does.
   https://datamall.lta.gov.sg/content/datamall/en/static-data.html
2. OpenStreetMap, Singapore extract (daily), for the walking network:
   https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf
Re-runnable: files already on disk are kept.
"""
import io, json, os, re, sys, time, zipfile
from datetime import datetime, timezone
import requests

RAW = sys.argv[1]
BASE = 'https://datamall.lta.gov.sg'
PAGE = BASE + '/content/datamall/en/static-data.html'
PBF = 'https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf'
UA = {'User-Agent': '30DayMapChallenge-day24/1.0 (static map page)'}
os.makedirs(RAW, exist_ok=True)
meta_path = os.path.join(RAW, 'meta.json')
meta = json.load(open(meta_path)) if os.path.exists(meta_path) else {}


def get(url, **kw):
    for attempt in range(5):
        r = requests.get(url, headers=UA, timeout=600, **kw)
        if r.status_code == 429:
            time.sleep(20 * (attempt + 1)); continue
        r.raise_for_status()
        return r
    raise RuntimeError(f'gave up on {url}')


# 1. Covered linkways
out = os.path.join(RAW, 'CoveredLinkWay')
if not (os.path.isdir(out) and any(f.endswith('.shp') for f in os.listdir(out))):
    html = get(PAGE).text
    links = sorted(set(re.findall(r'href="(/content/dam/datamall/datasets/Geospatial/CoveredLinkWay[^"/]*\.zip)"', html)))
    if not links:
        sys.exit('No CoveredLinkWay zip linked from the DataMall static-data page')
    link = links[-1]
    r = get(BASE + requests.utils.quote(link))
    os.makedirs(out, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for m in z.infolist():
            fn = os.path.basename(m.filename)
            if m.is_dir() or not fn or '..' in fn:
                continue
            with open(os.path.join(out, fn), 'wb') as g:
                g.write(z.read(m))
    meta['linkway_url'] = BASE + link
    meta['linkway_fetched'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print('CoveredLinkWay', len(r.content) // 1024, 'kB from', link)
    time.sleep(1.5)

# 2. OpenStreetMap extract
pbf = os.path.join(RAW, 'singapore-latest.osm.pbf')
if not (os.path.exists(pbf) and os.path.getsize(pbf) > 10_000_000):
    with requests.get(PBF, headers=UA, stream=True, timeout=600) as r:
        r.raise_for_status()
        with open(pbf, 'wb') as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    meta['osm_fetched'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
    print('OSM extract', os.path.getsize(pbf) // (1 << 20), 'MB')

json.dump(meta, open(meta_path, 'w'), indent=1)
print('ok', meta)
