"""Day 26 · Water: pull reservoirs, plants, rivers and pipelines out of the OSM extracts.

Requirements (Python 3.10+ venv): pip install osmium shapely
Run fetch.py first. Usage: python osm_extract.py <raw dir>
Writes <raw dir>/osm_water.json (plain GeoJSON-ish dicts, WGS84).
"""
import json, sys, re, os
import osmium
from shapely import wkb as swkb
from shapely.geometry import mapping

RAW = sys.argv[1] if len(sys.argv) > 1 else 'raw'
BBOX = (103.5, 1.15, 104.4, 2.1)   # w, s, e, n: Singapore plus southern Johor up to Linggiu
WKB = osmium.geom.WKBFactory()


def inside(lon, lat):
    return BBOX[0] <= lon <= BBOX[2] and BBOX[1] <= lat <= BBOX[3]


NAME_RX = re.compile(r'newater|desalination|water ?works|linggiu|reservoir|loji air|empangan|tasik|johor river|sungai johor', re.I)


class H(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.areas, self.lines, self.points = [], [], []

    def node(self, n):
        t = n.tags
        if not n.location.valid() or not inside(n.location.lon, n.location.lat):
            return
        if t.get('man_made') in ('water_works', 'wastewater_plant', 'desalination_plant') or NAME_RX.search(t.get('name', '')):
            self.points.append({'id': f'n{n.id}', 'tags': dict(t), 'lon': n.location.lon, 'lat': n.location.lat})

    def way(self, w):
        t = w.tags
        keep = t.get('man_made') == 'pipeline' or t.get('waterway') in ('river', 'canal') or \
            (t.get('bridge') and 'causeway' in t.get('name', '').lower()) or \
            (t.get('name', '').lower().find('causeway') >= 0)
        if not keep:
            return
        try:
            coords = [(n.lon, n.lat) for n in w.nodes]
        except osmium.InvalidLocationError:
            return
        if not any(inside(*c) for c in coords):
            return
        self.lines.append({'id': f'w{w.id}', 'tags': dict(t), 'coords': coords})

    def area(self, a):
        t = a.tags
        nat, lu, mm = t.get('natural'), t.get('landuse'), t.get('man_made')
        name = t.get('name', '')
        water = nat == 'water' or lu == 'reservoir' or t.get('water') == 'reservoir' or lu == 'basin'
        plant = mm in ('water_works', 'wastewater_plant', 'desalination_plant') or NAME_RX.search(name)
        if not (water or plant):
            return
        try:
            g = swkb.loads(WKB.create_multipolygon(a), hex=True)
        except Exception:
            return
        c = g.representative_point()
        if not inside(c.x, c.y):
            return
        # keep every named water body, any unnamed one over ~2 ha, and every plant site
        if water and not plant and not name and g.area < 2e-6:
            return
        self.areas.append({'id': ('w' if a.from_way() else 'r') + str(a.orig_id()), 'tags': dict(t), 'geom': mapping(g)})


out = {'areas': [], 'lines': [], 'points': []}
for f in ('singapore-latest.osm.pbf', 'malaysia-latest.osm.pbf'):
    p = os.path.join(RAW, f)
    h = H()
    h.apply_file(p, locations=True, idx='flex_mem')
    seen = {x['id'] for x in out['areas']} | {x['id'] for x in out['lines']} | {x['id'] for x in out['points']}
    for k, lst in (('areas', h.areas), ('lines', h.lines), ('points', h.points)):
        out[k] += [x for x in lst if x['id'] not in seen]
    print(f, len(h.areas), len(h.lines), len(h.points))
json.dump(out, open(os.path.join(RAW, 'osm_water.json'), 'w'))
print('areas', len(out['areas']), 'lines', len(out['lines']), 'points', len(out['points']))
