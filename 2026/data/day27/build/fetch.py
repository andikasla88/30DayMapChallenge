"""Day 27 New tool: fetch the raw input. Standard library only.

usage: python -I fetch.py <raw-dir>

Writes into <raw-dir> (keep it outside the repo):
  singapore-latest.osm.pbf   the daily OpenStreetMap extract for Singapore from
                             download.openstreetmap.fr (ODbL). It holds every MRT tunnel,
                             station, the Jurong Rock Caverns outline, the water
                             reclamation plants and the Central Catchment Nature Reserve.
A file already present is kept, so a re-run does not hit the server again
(delete it to refresh).

The published depths are not fetched: they are quoted, with their sources, in process.py.
"""
import os
import sys
import time
import urllib.error
import urllib.request

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
UA = {'User-Agent': '30DayMapChallenge-day27/1.0'}
PBF_URL = 'https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf'


def get(url, dest, tries=4):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(dest + '.part', 'wb') as out:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            os.replace(dest + '.part', dest)
            return
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                time.sleep(5 * 2 ** k)   # back off
                continue
            raise
        except urllib.error.URLError:
            time.sleep(5 * 2 ** k)
    raise SystemExit(f'gave up on {url}')


pbf = os.path.join(RAW, 'singapore-latest.osm.pbf')
if not os.path.exists(pbf):
    print('fetching', PBF_URL)
    get(PBF_URL, pbf)
print('ok', pbf, os.path.getsize(pbf), 'bytes')
