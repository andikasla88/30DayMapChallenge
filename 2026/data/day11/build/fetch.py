"""Day 11 · Sound: fetch raw lightning records from data.gov.sg (run once; raw files go outside the repo).

The v2 real-time weather API serves one lightning record about every 2 minutes, 25 records
a page, newest first. A whole day is about 29 pages: follow data.paginationToken until it
runs out. Each day is saved as one file, <raw-dir>/lightning_YYYY-MM-DD.json, holding every
record of that day. Days already on disk are skipped, so the script can be re-run.
The last day's closing 2 minutes live in the next day's 00:00 record, fetched on its own
as lightning_<next day>_midnight.json.

Gentle on the API: one request at a time, a short pause between them, and a growing
back-off on HTTP 429 or a server error.

Standard library only (no pip installs needed).
usage: python fetch.py <raw-dir> [days-back=60] [last-date=yesterday, YYYY-MM-DD]
"""
import json, sys, time, pathlib, datetime as dt, urllib.request, urllib.error, urllib.parse

RAW = pathlib.Path(sys.argv[1]); RAW.mkdir(parents=True, exist_ok=True)
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
SGT = dt.timezone(dt.timedelta(hours=8))
LAST = dt.date.fromisoformat(sys.argv[3]) if len(sys.argv) > 3 else dt.datetime.now(SGT).date() - dt.timedelta(days=1)
API = 'https://api-open.data.gov.sg/v2/real-time/api/weather'
UA = {'User-Agent': 'Mozilla/5.0 (30DayMapChallenge day 11 build script)'}
PAUSE = 1.0


def get(params):
    url = API + '?' + urllib.parse.urlencode(params)
    wait = 5
    for attempt in range(8):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                body = json.load(r)
            if body.get('code', 0) != 0:
                raise RuntimeError(f"API error {body.get('code')}: {body.get('errorMsg')}")
            return body['data']
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504):
                print(f'  HTTP {e.code}, waiting {wait} s', flush=True)
                time.sleep(wait); wait = min(wait * 2, 120); continue
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            print(f'  {e}, waiting {wait} s', flush=True)
            time.sleep(wait); wait = min(wait * 2, 120)
    raise RuntimeError(f'gave up on {url}')


def fetch_day(day):
    out = RAW / f'lightning_{day.isoformat()}.json'
    if out.exists() and out.stat().st_size > 100:
        return json.loads(out.read_text())
    records, token, pages = [], None, 0
    while True:
        params = {'api': 'lightning', 'date': day.isoformat()}
        if token: params['paginationToken'] = token
        data = get(params)
        records += data.get('records', [])
        pages += 1
        token = data.get('paginationToken')
        time.sleep(PAUSE)
        if not token: break
        if pages > 80: raise RuntimeError(f'{day}: too many pages')
    # a day is complete when its records reach back to midnight; note it if not
    stamps = sorted(r['datetime'] for r in records)
    doc = {'date': day.isoformat(), 'pages': pages, 'nRecords': len(records),
           'first': stamps[0] if stamps else None, 'last': stamps[-1] if stamps else None,
           'fetched': dt.datetime.now(SGT).isoformat(timespec='seconds'), 'records': records}
    out.write_text(json.dumps(doc, separators=(',', ':')))
    return doc


def strikes(doc):
    return sum(len(r.get('item', {}).get('readings') or []) for r in doc['records'])


if __name__ == '__main__':
    summary = []
    for k in range(DAYS):
        day = LAST - dt.timedelta(days=k)
        doc = fetch_day(day)
        n = strikes(doc)
        summary.append((day.isoformat(), doc['nRecords'], n))
        print(f"{day}  records {doc['nRecords']:4d}  span {doc['first']} .. {doc['last']}  strikes {n}", flush=True)
    # The last day's final 2 minutes (23:58-24:00) sit in the next day's 00:00 record. Asking
    # for date=<next day>T00:00:00 returns that record (and a couple before it) in one request.
    nxt = LAST + dt.timedelta(days=1)
    out = RAW / f'lightning_{nxt.isoformat()}_midnight.json'
    if not out.exists():
        data = get({'api': 'lightning', 'date': nxt.isoformat() + 'T00:00:00'})
        recs = data.get('records', [])
        out.write_text(json.dumps({'date': nxt.isoformat(), 'partial': True, 'nRecords': len(recs), 'records': recs}, separators=(',', ':')))
    (RAW / 'scan_summary.json').write_text(json.dumps(summary))
    top = sorted(summary, key=lambda s: -s[2])[:8]
    print('stormiest:', top)
