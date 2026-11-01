"""Day 03 data prep, step 1 of 2 (run build.sh for the whole pipeline).

Reads the URA Master Plan 2019 Land Use layer and the MP2019 Planning Area
boundary (no sea) from data.gov.sg, sorts the 33 land-use descriptions into
15 "fabrics", tags every polygon with its planning area, and writes:
  <out>/patches.geojson  every non-road land-use polygon, props c,u,g,p (full precision)
  <out>/island.geojson   the island outline: union of every polygon incl. roads
  <out>/stats.json       km2 per fabric, roads, total (SVY21 planar areas, pre-simplification)

usage: python -I prep.py <landuse.geojson> <planning_area.geojson> <outdir>
"""
import json
import sys

import geopandas as gpd

# Fabric order is the legend order. Each fabric lists the LU_DESC values sewn from it.
FABRICS = [
    ('res',     ['RESIDENTIAL', 'RESIDENTIAL / INSTITUTION']),
    ('mix',     ['COMMERCIAL & RESIDENTIAL', 'RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY']),
    ('com',     ['COMMERCIAL', 'HOTEL', 'WHITE', 'COMMERCIAL / INSTITUTION']),
    ('biz',     ['BUSINESS 2', 'BUSINESS 1', 'BUSINESS 1 - WHITE', 'BUSINESS 2 - WHITE']),
    ('bpark',   ['BUSINESS PARK', 'BUSINESS PARK - WHITE']),
    ('inst',    ['EDUCATIONAL INSTITUTION', 'CIVIC & COMMUNITY INSTITUTION', 'HEALTH & MEDICAL CARE', 'PLACE OF WORSHIP']),
    ('park',    ['PARK', 'BEACH AREA']),
    ('open',    ['OPEN SPACE']),
    ('sport',   ['SPORTS & RECREATION']),
    ('water',   ['WATERBODY']),
    ('agri',    ['AGRICULTURE']),
    ('cem',     ['CEMETERY']),
    ('trans',   ['PORT / AIRPORT', 'TRANSPORT FACILITIES', 'MASS RAPID TRANSIT', 'LIGHT RAPID TRANSIT']),
    ('util',    ['UTILITY']),
    ('special', ['SPECIAL USE']),
    ('reserve', ['RESERVE SITE']),
]
LU_TO_FABRIC = {lu: i for i, (_, lus) in enumerate(FABRICS) for lu in lus}
LU_LIST = [lu for _, lus in FABRICS for lu in lus]


def main(lu_path, pa_path, out):
    lu = gpd.read_file(lu_path)[['LU_DESC', 'GPR', 'geometry']]
    lu['LU_DESC'] = lu['LU_DESC'].str.strip()
    # Horsburgh Lighthouse (104.4E) is one tiny dot 40 km east: leave it off the quilt.
    lu = lu[lu.geometry.representative_point().x < 104.15].copy()
    lu['geometry'] = lu.geometry.make_valid()
    svy = lu.to_crs(3414)
    lu['km2'] = svy.area / 1e6

    unknown = set(lu.LU_DESC) - set(LU_TO_FABRIC) - {'ROAD'}
    if unknown:
        raise SystemExit(f'unmapped LU_DESC: {unknown}')

    stats = {'total_km2': round(lu.km2.sum(), 3), 'road_km2': round(lu[lu.LU_DESC == 'ROAD'].km2.sum(), 3), 'fabrics': {}}
    for i, (key, lus) in enumerate(FABRICS):
        sub = lu[lu.LU_DESC.isin(lus)]
        stats['fabrics'][key] = {'km2': round(sub.km2.sum(), 3), 'n': int(len(sub)),
                                 'parts': {d: round(sub[sub.LU_DESC == d].km2.sum(), 3) for d in lus}}

    # Island outline: every polygon, roads included, closed by 3 m to shut slivers,
    # small holes filled, islets under 0.4 ha dropped, simplified to ~6 m.
    from shapely import Polygon, MultiPolygon
    u = svy.geometry.buffer(3, join_style='mitre').union_all().buffer(-3, join_style='mitre')
    parts = []
    for poly in getattr(u, 'geoms', [u]):
        if poly.area < 4000:
            continue
        holes = [r for r in poly.interiors if Polygon(r).area > 50000]
        parts.append(Polygon(poly.exterior, holes))
    isl = gpd.GeoSeries([MultiPolygon(parts)], crs=3414).simplify(6).to_crs(4326)
    gpd.GeoDataFrame(geometry=isl).to_file(f'{out}/island.geojson', driver='GeoJSON')

    pa = gpd.read_file(pa_path)[['PLN_AREA_N', 'geometry']]
    pa_names = sorted(pa.PLN_AREA_N.str.title().unique())
    pa['p'] = pa.PLN_AREA_N.str.title().map({n: i for i, n in enumerate(pa_names)})

    pt = lu[lu.LU_DESC != 'ROAD'].copy()
    pt['c'] = pt.LU_DESC.map(LU_TO_FABRIC)
    pt['u'] = pt.LU_DESC.map({d: i for i, d in enumerate(LU_LIST)})
    g = pt.GPR.fillna('').astype(str).str.strip()
    pt['g'] = g.where(~g.isin(['NA', '']), '')
    reps = gpd.GeoDataFrame(pt[['c']], geometry=pt.geometry.representative_point(), crs=pt.crs)
    j = gpd.sjoin(reps, pa[['p', 'geometry']], how='left', predicate='within')
    j = j[~j.index.duplicated()]
    # Points in the sea gaps between PA polygons: nearest planning area.
    miss = j.p.isna()
    if miss.any():
        near = gpd.sjoin_nearest(reps[miss].to_crs(3414), pa[['p', 'geometry']].to_crs(3414), how='left')
        near = near[~near.index.duplicated()]
        j.loc[miss, 'p'] = near.p
    pt['p'] = j.p.astype(int)
    pt[['c', 'u', 'g', 'p', 'geometry']].to_file(f'{out}/patches.geojson', driver='GeoJSON')

    stats['lu'] = LU_LIST
    stats['pa'] = pa_names
    stats['fabric_keys'] = [k for k, _ in FABRICS]
    with open(f'{out}/stats.json', 'w') as f:
        json.dump(stats, f, indent=1)
    print(json.dumps({k: v['km2'] for k, v in stats['fabrics'].items()}), stats['total_km2'], stats['road_km2'])


if __name__ == '__main__':
    main(*sys.argv[1:4])
