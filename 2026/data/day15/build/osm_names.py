"""Day 15 (Inside out): read the OSM extract and keep what the map needs.

Requires: osmium shapely pyproj
usage: python -I osm_names.py <raw-dir>        writes <raw-dir>/osm.pkl

  coast    today's coastline (natural=coastline ways), lon/lat LineStrings
  land     today's land: every closed coastline ring (OSM draws land on the left, so each closed
           ring wound counter-clockwise is an island), lon/lat
  sg       Singapore's national territory, land and sea (OSM relation 536780)
  islands  every named island area (place=island), for notes about whole islands
  water    inland water (natural=water, reservoirs, basins, riverbanks), lon/lat, so that
           reservoirs made by damming the sea don't count as new land
  feats    every street, place, station, park, cape, beach and island inside Singapore whose name
           holds a shore word, as (name, kind, osm id, tags, lon/lat geometry)
"""
import os
import pickle
import re
import sys

import osmium
import shapely
import shapely.wkb as wkb
from shapely.ops import linemerge, unary_union

RAW = sys.argv[1]
PBF = os.path.join(RAW, 'singapore-latest.osm.pbf')
WORD = re.compile(r'(?<![A-Za-z])(Tanjong|Tanjung|Tg|Telok|Teluk|Pasir|Pantai|Kuala|Beach|Pulau)(?![A-Za-z])')
ROADS = {'motorway', 'trunk', 'primary', 'secondary', 'tertiary', 'unclassified', 'residential', 'service',
         'living_street', 'pedestrian', 'road', 'motorway_link', 'trunk_link', 'primary_link',
         'secondary_link', 'tertiary_link'}
# a street name, not a bus stop, school, car park or block that happens to be on a street
STREET = re.compile(r'^(Jalan|Lorong|Lengkok|Lebuh|Lengkong)\b|\b(Road|Street|Avenue|Drive|Way|Lane|Close|Crescent|Rise|Walk|View|'
                    r'Place|Link|Terrace|Grove|Green|Heights|Hill|Central|Promenade|Farmway|Boulevard|Gardens?|Park|Ring|'
                    r'Circle|Square|Plaza|Vale|Loop|Track|Quay|Flyover)( South| North| East| West)?( \d+[A-Z]?)?$')
PLACES = {'suburb', 'neighbourhood', 'quarter', 'locality', 'village', 'hamlet', 'island', 'islet', 'town'}
PARKS = {'park', 'nature_reserve', 'garden'}
NATURAL = {'cape', 'beach', 'bay', 'peninsula'}

fab = osmium.geom.WKBFactory()
coast, feats, water, islands, sg = [], [], [], [], None


def kind_of(o, t):
    """What sort of named thing this is, or None if we don't map it."""
    if o.is_way() and t.get('highway') in ROADS:
        return 'street' if STREET.search(t['name']) else None
    rail = t.get('station') in ('subway', 'light_rail', 'monorail', 'train') or any(t.get(k) == 'yes' for k in ('subway', 'train', 'light_rail', 'monorail'))
    if (t.get('railway') == 'station' or (t.get('public_transport') == 'station' and rail)) and t.get('bus') != 'yes' and t.get('amenity') != 'bus_station':
        return 'station'
    if t.get('place') in PLACES:
        return 'island' if t['place'] in ('island', 'islet') else 'place'
    if t.get('leisure') in PARKS:
        return 'park'
    if t.get('natural') in NATURAL:
        return t['natural'] if t['natural'] != 'peninsula' else 'cape'
    return None


fp = osmium.FileProcessor(PBF).with_locations().with_areas()
for o in fp:
    t = dict(o.tags)
    if o.is_area():
        if not o.from_way() and o.orig_id() == 536780:
            sg = wkb.loads(fab.create_multipolygon(o), hex=True)
            continue
        if t.get('natural') == 'water' or t.get('landuse') in ('reservoir', 'basin') or t.get('waterway') == 'riverbank':
            try:
                water.append(wkb.loads(fab.create_multipolygon(o), hex=True))
            except RuntimeError:
                pass
        name = t.get('name', '')
        if t.get('place') == 'island' and name:   # every named island, for notes about whole islands
            try:
                islands.append((name, wkb.loads(fab.create_multipolygon(o), hex=True)))
            except RuntimeError:
                pass
        if not WORD.search(name):
            continue
        k = kind_of(o, t) if not (t.get('highway')) else None
        if k:
            try:
                feats.append((name, k, ('w' if o.from_way() else 'r') + str(o.orig_id()), t, wkb.loads(fab.create_multipolygon(o), hex=True)))
            except RuntimeError:
                pass
        continue
    if o.is_way() and t.get('natural') == 'coastline':
        coast.append(wkb.loads(fab.create_linestring(o), hex=True))
    name = t.get('name', '')
    if not name or not WORD.search(name):
        continue
    if o.is_node():
        k = kind_of(o, t)
        if k:
            feats.append((name, k, 'n' + str(o.id), t, shapely.Point(o.location.lon, o.location.lat)))
    elif o.is_way():
        k = kind_of(o, t)
        if k == 'street':
            try:
                feats.append((name, k, 'w' + str(o.id), t, wkb.loads(fab.create_linestring(o), hex=True)))
            except RuntimeError:
                pass

if sg is None:
    sys.exit('Singapore boundary (relation 536780) missing from the extract')
merged = linemerge(coast)
rings = [g for g in getattr(merged, 'geoms', [merged]) if g.is_closed]
land = unary_union([shapely.Polygon(r) for r in rings if shapely.LinearRing(r.coords).is_ccw])
inside = shapely.prepared.prep(sg)
feats = [f for f in feats if inside.intersects(f[4])]
print('coast ways', len(coast), 'land rings', len(rings), 'features in Singapore', len(feats))
water = unary_union([w.buffer(0) for w in water]).intersection(sg)
pickle.dump({'coast': coast, 'land': land, 'sg': sg, 'feats': feats, 'water': water, 'islands': islands}, open(os.path.join(RAW, 'osm.pkl'), 'wb'))
