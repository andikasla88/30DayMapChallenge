"""Day 04 · fetch raw inputs (run once; raw files go to the scratchpad, not the repo).

1. LTA taxi availability snapshots from data.gov.sg (historical, no key):
   - 18:00 on each of the five weekdays Mon 26 to Fri 30 Oct 2026, and 02:00 the night after
     (Tue 27 to Sat 31 Oct), so each pair is "this evening" vs "tonight".
   - all 24 hourly snapshots of the representative day, Wed 28 Oct 2026.
2. Landmarks for naming clusters, from OpenStreetMap via Overpass.

usage: python fetch.py <raw-dir>
"""
import json, sys, time, pathlib, datetime as dt
import requests

RAW = pathlib.Path(sys.argv[1]); RAW.mkdir(parents=True, exist_ok=True)
API = 'https://api.data.gov.sg/v1/transport/taxi-availability'
UA = {'User-Agent': 'Mozilla/5.0 (30DayMapChallenge day 4 build script)'}

stamps = set()
for d in range(26, 31):
    stamps.add(dt.datetime(2026, 10, d, 18))
    stamps.add(dt.datetime(2026, 10, d + 1, 2))
for h in range(24):
    stamps.add(dt.datetime(2026, 10, 28, h))

for t in sorted(stamps):
    out = RAW / f"taxi_{t:%Y%m%dT%H}.json"
    if out.exists() and out.stat().st_size > 1000:
        continue
    for attempt in range(4):
        try:
            r = requests.get(API, params={'date_time': t.strftime('%Y-%m-%dT%H:%M:%S')}, headers=UA, timeout=40)
            r.raise_for_status()
            j = r.json()
            assert j['features'][0]['geometry']['coordinates']
            out.write_text(json.dumps(j))
            print(out.name, j['features'][0]['properties']['timestamp'], j['features'][0]['properties']['taxi_count'])
            break
        except Exception as e:
            print('retry', t, e); time.sleep(3 + 4 * attempt)
    time.sleep(0.6)

# Landmarks: named taxi stands, airport terminals, malls, hospitals, MRT stations, hotels, places.
OVERPASS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
Q = """[out:json][timeout:120];
area["ISO3166-1"="SG"][admin_level=2]->.sg;
(
  nwr["amenity"="taxi"]["name"](area.sg);
  nwr["aeroway"="terminal"]["name"](area.sg);
  nwr["shop"="mall"]["name"](area.sg);
  nwr["amenity"="hospital"]["name"](area.sg);
  nwr["railway"="station"]["station"="subway"]["name"](area.sg);
  nwr["tourism"="hotel"]["name"]["stars"](area.sg);
  nwr["amenity"="casino"](area.sg);
  nwr["amenity"="bus_station"]["name"](area.sg);
  node["place"~"suburb|quarter|neighbourhood"]["name"](area.sg);
);
out center tags;"""
out = RAW / 'landmarks_osm.json'
if not out.exists():
    for url in OVERPASS:
        try:
            r = requests.post(url, data={'data': Q}, headers=UA, timeout=180)
            r.raise_for_status()
            out.write_text(r.text); print('landmarks', len(r.json()['elements'])); break
        except Exception as e:
            print('overpass failed', url, e)
