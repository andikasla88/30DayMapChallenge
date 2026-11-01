"""Day 29 (Raster): read the OpenStreetMap extract and keep what the analysis needs.

Requires python 3.10+ with: osmium shapely
usage: python -I osm.py <raw-dir>        reads <raw-dir>/singapore-latest.osm.pbf, writes <raw-dir>/osm.pkl

  sg        Singapore's national territory (OSM relation 536780)
  land      today's land: every closed natural=coastline ring wound counter-clockwise
  water     inland water areas: (name, kind, geometry), kind = reservoir | water
  reserves  nature reserves and protected areas: (name, geometry)
  landuse   landuse areas: (landuse, name, geometry), e.g. industrial, residential, commercial
  buildings every building footprint: (osm id, building tag, name, geometry)
  places    named places and estates as points: (name, kind, lon, lat)
  solar     floating solar panels and plants (power=* with solar source and floating=yes): geometry
All geometry is lon/lat (EPSG:4326).
"""
import os
import pickle
import sys

import osmium
import shapely
import shapely.wkb as wkb
from shapely.ops import linemerge, unary_union

RAW = sys.argv[1]
PBF = os.path.join(RAW, 'singapore-latest.osm.pbf')
fab = osmium.geom.WKBFactory()
coast, water, reserves, landuse, buildings, places, solar, sg = [], [], [], [], [], [], [], None
PLACE_KINDS = {'suburb', 'neighbourhood', 'quarter', 'locality', 'village', 'hamlet', 'island', 'islet', 'town'}


def area_geom(o):
    try:
        return wkb.loads(fab.create_multipolygon(o), hex=True)
    except RuntimeError:
        return None


for o in osmium.FileProcessor(PBF).with_locations().with_areas():
    t = dict(o.tags)
    if o.is_area():
        if not o.from_way() and o.orig_id() == 536780:
            sg = area_geom(o)
            continue
        name = t.get('name', '')
        if t.get('power') in ('generator', 'plant') and t.get('floating') == 'yes' and 'solar' in (t.get('generator:source', '') + t.get('plant:source', '')):
            g = area_geom(o)
            if g is not None:
                solar.append(g)
        oid = ('w' if o.from_way() else 'r') + str(o.orig_id())
        if t.get('building') and t['building'] != 'no':
            g = area_geom(o)
            if g is not None:
                buildings.append((oid, t['building'], name, g))
            continue
        if t.get('landuse') == 'reservoir' or t.get('water') == 'reservoir' or t.get('natural') == 'water' or t.get('landuse') == 'basin':
            g = area_geom(o)
            if g is not None:
                kind = 'reservoir' if (t.get('landuse') == 'reservoir' or t.get('water') == 'reservoir' or 'Reservoir' in name) else 'water'
                water.append((name, kind, oid, g))
        if t.get('leisure') == 'nature_reserve' or t.get('boundary') in ('protected_area', 'national_park'):
            g = area_geom(o)
            if g is not None and name:
                reserves.append((name, oid, g))
        if t.get('landuse') and t['landuse'] not in ('reservoir', 'basin'):
            g = area_geom(o)
            if g is not None:
                landuse.append((t['landuse'], name, oid, g))
        if t.get('place') in PLACE_KINDS and name:
            g = area_geom(o)
            if g is not None:
                c = g.representative_point()
                places.append((name, t['place'], c.x, c.y))
        continue
    if o.is_way() and t.get('natural') == 'coastline':
        coast.append(wkb.loads(fab.create_linestring(o), hex=True))
    elif o.is_node() and t.get('place') in PLACE_KINDS and t.get('name'):
        places.append((t['name'], t['place'], o.location.lon, o.location.lat))

if sg is None:
    sys.exit('Singapore boundary (relation 536780) missing from the extract')
merged = linemerge(coast)
rings = [g for g in getattr(merged, 'geoms', [merged]) if g.is_closed]
land = unary_union([shapely.Polygon(r) for r in rings if shapely.LinearRing(r.coords).is_ccw]).intersection(sg)
print('land km2 (deg units)', round(land.area, 5), 'water', len(water), 'reserves', len(reserves), 'landuse', len(landuse),
      'buildings', len(buildings), 'places', len(places), 'floating solar', len(solar))
pickle.dump({'sg': sg, 'land': land, 'water': water, 'reserves': reserves, 'landuse': landuse,
             'buildings': buildings, 'places': places, 'solar': solar}, open(os.path.join(RAW, 'osm.pkl'), 'wb'))
