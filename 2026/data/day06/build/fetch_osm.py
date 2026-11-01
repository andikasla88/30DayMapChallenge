"""OSM context for day 06 via Overpass: coastline, main roads, reservoirs, rail.
usage: python fetch_osm.py <raw_dir>"""
import sys, os, requests, time
RAW = sys.argv[1]
BB = '0.8,103.2,1.9,104.5'
Q = {
 'coast': f'[out:json][timeout:180];way["natural"="coastline"]({BB});out geom;',
 'roads': f'[out:json][timeout:180];way["highway"~"^(motorway|trunk|primary)$"](1.2,103.6,1.48,104.06);out geom;',
 'water': f'[out:json][timeout:180];(way["natural"="water"]["water"~"reservoir|lake|river"](1.2,103.6,1.48,104.06);relation["natural"="water"]["water"~"reservoir|lake"](1.2,103.6,1.48,104.06););out geom;',
 'rail':  f'[out:json][timeout:180];way["railway"~"^(subway|light_rail)$"](1.2,103.6,1.48,104.06);out geom;',
}
for k, q in Q.items():
    out = os.path.join(RAW, f'osm_{k}.json')
    if os.path.exists(out): continue
    for url in ('https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'):
        try:
            r = requests.post(url, data={'data': q}, timeout=300, headers={'User-Agent': '30DayMapChallenge day06 build'})
            if r.ok: open(out, 'wb').write(r.content); print(k, len(r.content)); break
            print(k, url, r.status_code)
        except Exception as e: print(k, e)
    time.sleep(5)
