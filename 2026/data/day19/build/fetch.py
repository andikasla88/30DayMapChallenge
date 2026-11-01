"""Day 19 · Smell: fetch the raw inputs from data.gov.sg (raw files go outside the repo).

  1. NEA's "Hawker Centres (GEOJSON)" dataset, d_4a086da0a5553be1d89383cd90d07ecd:
     every hawker centre with its status and number of cooked-food stalls.
  2. The latest NEA wind readings from the v2 real-time API:
       https://api-open.data.gov.sg/v2/real-time/api/wind-direction   (degrees)
       https://api-open.data.gov.sg/v2/real-time/api/wind-speed       (knots)
     Each is one reading per weather station, a 10-minute mean published every minute.
     These become the page's fallback snapshot; the page itself asks for live readings.

Gentle on the API: one request at a time, a pause between them, and a growing back-off
on HTTP 429 or a server error. Standard library only (no pip installs needed).

usage: python fetch.py <raw-dir>
"""
import json, sys, time, pathlib, urllib.request, urllib.error

RAW = pathlib.Path(sys.argv[1]); RAW.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (30DayMapChallenge day 19 build script)'}
HAWKERS = 'd_4a086da0a5553be1d89383cd90d07ecd'
PAUSE = 1.5


def get(url, parse=True):
    wait = 5
    for _ in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = r.read()
            time.sleep(PAUSE)
            return json.loads(body) if parse else body
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                print(f'  HTTP {e.code}, waiting {wait} s', flush=True)
                time.sleep(wait); wait = min(wait * 2, 120); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f'  {e}, waiting {wait} s', flush=True)
            time.sleep(wait); wait = min(wait * 2, 120)
    raise RuntimeError(f'gave up on {url}')


# 1. hawker centres: ask for a signed download link, then fetch the file
meta = get(f'https://api-open.data.gov.sg/v1/public/api/datasets/{HAWKERS}/poll-download')
if meta.get('code') != 0 or not meta.get('data', {}).get('url'):
    raise SystemExit(f'poll-download failed: {meta}')
geo = get(meta['data']['url'], parse=False)
(RAW / 'hawker-centres.geojson').write_bytes(geo)
print(f'hawker centres: {len(geo):,} bytes')

# 2. the latest wind readings
for api in ('wind-direction', 'wind-speed'):
    body = get(f'https://api-open.data.gov.sg/v2/real-time/api/{api}')
    if body.get('code') != 0:
        raise SystemExit(f'{api}: API error {body.get("code")}: {body.get("errorMsg")}')
    (RAW / f'{api}.json').write_text(json.dumps(body), encoding='utf-8')
    r = body['data']['readings'][0]
    print(f'{api}: {len(r["data"])} stations at {r["timestamp"]} ({body["data"].get("readingUnit")})')
