"""Day 05 (Sight): fetch raw inputs into the scratchpad.

  python fetch.py <raw-dir>

1. OSM buildings via Overpass (kept for reference; on 1 Nov 2026 Overpass returned 502/504,
   so the build used osm_from_pbf.py on the BBBike Singapore extract instead).
2. HDB Property Information (data.gov.sg, d_17f5382f26140b1fdae0ba2ef6239d2f):
   block, street, max floor, dwelling units.
3. Terrain: AWS Terrain Tiles (terrarium PNG, z14) over the same area.
"""
import json, math, os, sys, time
import requests

RAW = sys.argv[1]
os.makedirs(RAW, exist_ok=True)
BARGE = (103.8575, 1.2862)   # lng, lat: open water in Marina Bay, off The Float
RADIUS = 8500
UA = {'User-Agent': 'dmc30-build/1.0 (30DayMapChallenge day 05)'}


def overpass():
    """Four bbox quadrants (one big around: query times out), merged and de-duplicated."""
    out = os.path.join(RAW, 'osm_buildings.json')
    if os.path.exists(out):
        return
    dlat = RADIUS / 111320
    dlng = dlat / math.cos(math.radians(BARGE[1]))
    s, w, n, e = BARGE[1] - dlat, BARGE[0] - dlng, BARGE[1] + dlat, BARGE[0] + dlng
    mlat, mlng = BARGE[1], BARGE[0]
    seen, elements = set(), []
    for bb in [(s, w, mlat, mlng), (s, mlng, mlat, e), (mlat, w, n, mlng), (mlat, mlng, n, e)]:
        b = ','.join(f'{v:.5f}' for v in bb)
        q = f"""[out:json][timeout:300];
(way["building"]({b}); relation["building"]({b}); way["building:part"]({b}); relation["building:part"]({b}););
out tags geom;"""
        for attempt in range(4):
            url = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter'][attempt % 2]
            try:
                r = requests.post(url, data={'data': q}, headers=UA, timeout=600)
                r.raise_for_status()
                els = r.json()['elements']
                break
            except Exception as ex:
                print('overpass failed', url, ex); time.sleep(20)
        else:
            raise SystemExit('overpass failed')
        for el in els:
            k = (el['type'], el['id'])
            if k not in seen:
                seen.add(k); elements.append(el)
        print('overpass quadrant', len(els), 'total', len(elements), flush=True)
        time.sleep(5)
    json.dump({'elements': elements}, open(out, 'w', encoding='utf-8'))


def hdb():
    out = os.path.join(RAW, 'hdb_property.json')
    if os.path.exists(out):
        return
    rid = 'd_17f5382f26140b1fdae0ba2ef6239d2f'
    rows, offset = [], 0
    while True:
        r = requests.get('https://data.gov.sg/api/action/datastore_search',
                         params={'resource_id': rid, 'limit': 5000, 'offset': offset}, headers=UA, timeout=120)
        if r.status_code == 429:
            time.sleep(8); continue
        r.raise_for_status()
        res = r.json()['result']
        rows += res['records']
        offset += len(res['records'])
        print('hdb', offset, res.get('total'))
        if not res['records'] or offset >= res.get('total', 0):
            break
        time.sleep(1.5)
    json.dump(rows, open(out, 'w'))


def terrain(z=14):
    d = os.path.join(RAW, f'terrarium{z}')
    os.makedirs(d, exist_ok=True)
    lat0 = BARGE[1]
    dlat = (RADIUS + 1500) / 111320
    dlng = dlat / math.cos(math.radians(lat0))
    def tile(lng, lat):
        n = 2 ** z
        x = (lng + 180) / 360 * n
        y = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
        return int(x), int(y)
    x0, y0 = tile(BARGE[0] - dlng, lat0 + dlat)
    x1, y1 = tile(BARGE[0] + dlng, lat0 - dlat)
    for x in range(x0, x1 + 1):
        for y in range(y0, y1 + 1):
            p = os.path.join(d, f'{x}_{y}.png')
            if os.path.exists(p):
                continue
            r = requests.get(f'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png', timeout=60)
            r.raise_for_status()
            open(p, 'wb').write(r.content)
    json.dump({'z': z, 'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1}, open(os.path.join(d, 'index.json'), 'w'))
    print('terrain tiles', (x1 - x0 + 1) * (y1 - y0 + 1))


if __name__ == '__main__':
    hdb()
    terrain()
    if '--overpass' in sys.argv:
        overpass()
