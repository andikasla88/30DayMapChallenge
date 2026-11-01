"""Day 08 Utopia: fetch Singapore roads and parks from OpenStreetMap via Overpass.
Usage: python fetch.py <raw-dir>   (writes roads.json, parks.json)"""
import sys, os, time, requests
RAW = sys.argv[1]
URLS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
AREA = 'area["ISO3166-1"="SG"][admin_level=2]->.sg;'
Q = {
  'roads.json': '[out:json][timeout:600];' + AREA +
    'way["highway"~"^(motorway|trunk|primary|secondary|tertiary|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link|unclassified|residential|living_street|service)$"](area.sg);'
    'out tags geom qt;',
  'parks.json': '[out:json][timeout:300];' + AREA +
    '(way["leisure"~"^(park|nature_reserve)$"](area.sg);relation["leisure"~"^(park|nature_reserve)$"](area.sg);'
    'way["boundary"="protected_area"](area.sg);relation["boundary"="protected_area"](area.sg););out tags geom qt;',
}
for fn, q in Q.items():
    out = os.path.join(RAW, fn)
    if os.path.exists(out) and os.path.getsize(out) > 1000: continue
    for url in URLS * 2:
        try:
            r = requests.post(url, data={'data': q}, timeout=900, headers={'User-Agent': '30DayMapChallenge-day08/1.0'})
            if r.ok and r.text.lstrip().startswith('{'):
                open(out, 'w', encoding='utf-8').write(r.text); print(fn, len(r.text)); break
            print(url, r.status_code, r.text[:200])
        except Exception as e: print(url, e)
        time.sleep(10)
