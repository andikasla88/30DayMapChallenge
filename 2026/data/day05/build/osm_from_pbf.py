"""Fallback for Overpass (it was overloaded): buildings from the BBBike Singapore extract.

  python osm_from_pbf.py <raw-dir>      (expects <raw-dir>/pbf/Singapore.osm.pbf from
  https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.pbf)

Writes <raw-dir>/osm_buildings.geojsonl: one building / building:part per line, within 8.6 km
of the barge, with its tags.
"""
import json, math, os, sys
import osmium
import requests

RAW = sys.argv[1]
BARGE = (103.8575, 1.2862)
R = 8600
KEEP = {'building', 'building:part', 'height', 'building:height', 'building:levels', 'min_height', 'building:min_level',
        'addr:housenumber', 'addr:street', 'addr:postcode', 'name', 'name:en'}
fab = osmium.geom.GeoJSONFactory()
kx = 111320 * math.cos(math.radians(BARGE[1]))
out = open(os.path.join(RAW, 'osm_buildings.geojsonl'), 'w', encoding='utf-8')
n = 0


class H(osmium.SimpleHandler):
    def area(self, a):
        global n
        t = a.tags
        if 'building' not in t and 'building:part' not in t:
            return
        try:
            g = json.loads(fab.create_multipolygon(a))
        except Exception:
            return
        lng, lat = g['coordinates'][0][0][0]
        if math.hypot((lng - BARGE[0]) * kx, (lat - BARGE[1]) * 110574) > R:
            return
        tags = {k: v for k, v in t if k in KEEP}
        oid = ('w' if a.from_way() else 'r') + str(a.orig_id())
        out.write(json.dumps({'id': oid, 'tags': tags, 'geom': g}, ensure_ascii=False) + '\n')
        n += 1


pbf = os.path.join(RAW, 'pbf', 'Singapore.osm.pbf')
if not os.path.exists(pbf):
    os.makedirs(os.path.dirname(pbf), exist_ok=True)
    r = requests.get('https://download.bbbike.org/osm/bbbike/Singapore/Singapore.osm.pbf', headers={'User-Agent': 'dmc30-build/1.0'}, timeout=600)
    r.raise_for_status()
    open(pbf, 'wb').write(r.content)
H().apply_file(os.path.join(RAW, 'pbf', 'Singapore.osm.pbf'), locations=True)
print('buildings', n)
