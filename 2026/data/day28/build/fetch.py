"""Day 28 Feeling: fetch the raw inputs. Standard library only.

usage: python -I fetch.py <raw-dir> [YYYY-MM-DD]

Writes into <raw-dir> (keep it outside the repo):
  wbgt-<date>.json   Every WBGT record NEA has published so far on <date> (Singapore time;
                     default: today), from the data.gov.sg v2 real-time weather API:
                       https://api-open.data.gov.sg/v2/real-time/api/weather?api=wbgt&date=<date>
                     One record every 15 minutes, one reading per station (each a 15-minute
                     average). The API pages its answer, newest first; every page is followed.
                     This becomes the page's fallback snapshot; the page itself asks for
                     live readings when it opens.
  nmp.geojson        SLA National Map Polygon, data.gov.sg dataset
                     d_29f066d67df3eae91df8a42f443863c8 (its Coastal_Outlines layer is the land).
                     Kept if already present, so a re-run does not download it again.

Gentle on the APIs: one request at a time, a pause between them, a growing back-off on
HTTP 429 or a server error. No API key is needed.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
SGT = dt.timezone(dt.timedelta(hours=8))
DATE = sys.argv[2] if len(sys.argv) > 2 else dt.datetime.now(SGT).strftime('%Y-%m-%d')
UA = {'User-Agent': '30DayMapChallenge-day28/1.0'}
API = 'https://api-open.data.gov.sg/v2/real-time/api/weather'
NMP = 'd_29f066d67df3eae91df8a42f443863c8'
PAUSE = 1.5


def get(url):
    wait = 5
    for _ in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                body = r.read()
            time.sleep(PAUSE)
            return body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                print(f'  HTTP {e.code}, waiting {wait} s', flush=True)
                time.sleep(wait); wait = min(wait * 2, 120); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f'  {e}, waiting {wait} s', flush=True)
            time.sleep(wait); wait = min(wait * 2, 120)
    raise SystemExit(f'gave up on {url}')


# 1. WBGT: every page of the day
records, token, pages = [], None, 0
while True:
    q = {'api': 'wbgt', 'date': DATE}
    if token:
        q['paginationToken'] = token
    body = json.loads(get(API + '?' + urllib.parse.urlencode(q)))
    if body.get('code') != 0:
        raise SystemExit(f'WBGT API error {body.get("code")}: {body.get("errorMsg")}')
    data = body['data']
    records += data['records']
    pages += 1
    token = data.get('paginationToken')
    if not token or not data['records'] or pages > 20:
        break
if not records:
    raise SystemExit(f'no WBGT records for {DATE}')
out = os.path.join(RAW, f'wbgt-{DATE}.json')
with open(out, 'w', encoding='utf-8') as f:
    json.dump({'date': DATE, 'fetched': dt.datetime.now(SGT).isoformat(timespec='seconds'), 'records': records}, f)
print(f'WBGT {DATE}: {len(records)} records over {pages} pages, '
      f'{records[-1]["datetime"]} to {records[0]["datetime"]}')

# 2. the land: SLA National Map Polygon
path = os.path.join(RAW, 'nmp.geojson')
if not os.path.exists(path):
    poll = json.loads(get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{NMP}/poll-download'))
    if poll.get('code') != 0 or not poll.get('data', {}).get('url'):
        raise SystemExit(f'poll-download failed: {poll}')
    data = get(poll['data']['url'])
    with open(path, 'wb') as f:
        f.write(data)
    print(f'nmp.geojson: {len(data):,} bytes')
