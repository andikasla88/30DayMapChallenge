"""Day 13 · Interactions: fetch the raw inputs (raw files go to a scratch folder, not the repo).

1. LTA DataMall "Passenger Volume by Origin Destination Train Stations" (PV/ODTrain).
   The API answers with a short-lived link to a zipped CSV for one month. DataMall only
   keeps the last three months or so; this tries the months before today, newest first,
   and keeps the newest one it gets.
   Needs the DataMall key in the environment variable LTA_API_KEY. It is never printed.
2. Station points, names and rail lines from cheeaun/sgraildata (GitHub, raw).

Requirements: Python 3.9+, standard library only.
usage: LTA_API_KEY=... python fetch.py <raw-dir> [YYYYMM]
"""
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

RAW = pathlib.Path(sys.argv[1])
RAW.mkdir(parents=True, exist_ok=True)
KEY = os.environ.get('LTA_API_KEY', '').strip().strip('"').strip("'")
if not KEY:
    sys.exit('LTA_API_KEY is not set. Set it from your DataMall account before running this script.')

API = 'https://datamall2.mytransport.sg/ltaodataservice/PV/ODTrain?Date={}'
SGRAIL = 'https://raw.githubusercontent.com/cheeaun/sgraildata/master/data/v1/sg-rail.geojson'
UA = 'Mozilla/5.0 (30DayMapChallenge day 13 build script)'


def get(url, headers=None, tries=4):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={'User-Agent': UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f'DataMall refused the key (HTTP {e.code}). Stopping.')
            if e.code == 404:
                return None
            if e.code == 429 or e.code >= 500:
                time.sleep(4 * (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            time.sleep(4 * (attempt + 1))
    raise RuntimeError(f'gave up on {url.split("?")[0]}')


def months_back(n):
    d = dt.date.today().replace(day=1)
    for _ in range(n):
        d = (d - dt.timedelta(days=1)).replace(day=1)
        yield d.strftime('%Y%m')


# ---------- 1. OD train volumes ----------
wanted = [sys.argv[2]] if len(sys.argv) > 2 else list(months_back(6))
got = None
for ym in wanted:
    out = RAW / f'od_train_{ym}.zip'
    if out.exists() and out.stat().st_size > 100_000:
        got = ym
        print('have', out.name)
        break
    raw = get(API.format(ym), {'AccountKey': KEY, 'accept': 'application/json'})
    body = json.loads(raw) if raw else {}
    links = [v.get('Link') for v in body.get('value', []) if v.get('Link')]
    time.sleep(1)
    if not links:
        print(ym, 'not offered')
        continue
    data = get(links[0])   # a pre-signed link: no key needed, and the key is not sent
    out.write_bytes(data)
    (RAW / 'od_train_month.txt').write_text(ym)
    print('saved', out.name, len(data), 'bytes')
    got = ym
    break
if not got:
    sys.exit('No PV/ODTrain month was offered.')
(RAW / 'od_train_month.txt').write_text(got)

# ---------- 2. stations and lines ----------
out = RAW / 'sg-rail.geojson'
if not out.exists():
    out.write_bytes(get(SGRAIL))
    print('saved', out.name)
