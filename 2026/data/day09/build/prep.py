"""Day 09 (Urban-rural) data prep.

Inputs (download first, see build.sh):
  respop.xlsx      SingStat "Singapore Residents by Planning Area/Subzone, Single Year of Age
                   and Sex, June 2026" (Excel; its subzone Total rows are rounded once, unlike
                   the CSV, whose age x sex cells each round to 10 and lose tiny subzones).
  respoptod.csv    SingStat "... Age Group, Sex and Type of Dwelling, June 2026" (CSV), used
                   only for each subzone's dwelling mix (shares).
  subzones.geojson URA Master Plan 2019 Subzone Boundary (No Sea), data.gov.sg
                   d_8594ae9ff96d0c708bc2af633048edfb. The June 2026 table uses the same 332
                   subzone names (URA has not published an MP2025 subzone layer; the MP2025
                   planning areas differ from MP2019 only by Changi reclamation, which is empty).
  landuse.geojson  URA Master Plan 2019 Land Use layer, data.gov.sg
                   d_90d86daa5bfaa371668b84fa5f01424f (for the spikes only).

Output: density.json
  sz:    subzones [name, planning area, residents, km2, hdb, condo, landed, other shares (%)]
  geo:   polygons for each subzone, delta-encoded integer lon/lat at 1e-5 deg
  spikes:[lon, lat, residents] per 250 m cell. Each subzone's residents are spread over its
         homes (residential land weighted by plot ratio, as a proxy for floor space), so the
         spikes stand where people actually live. Subzones with residents but no residential
         land (farms, islands, camps) spread them evenly over their dry land.

usage: python -I prep.py <respop.xlsx> <respoptod.csv> <subzones.geojson> <landuse.geojson> <out.json>
"""
import csv
import json
import math
import sys
from collections import defaultdict

import geopandas as gpd
import numpy as np
import openpyxl
from shapely.geometry import box

CELL = 250.0   # metres, SVY21
RES = {   # land use -> weight multiplier on (area x plot ratio)
    'RESIDENTIAL': 1.0, 'RESIDENTIAL / INSTITUTION': 0.6,
    'COMMERCIAL & RESIDENTIAL': 0.7, 'RESIDENTIAL WITH COMMERCIAL AT 1ST STOREY': 0.9,
    'WHITE': 0.25,
}
DRY_SKIP = {'WATERBODY', 'ROAD'}


def gpr_num(g):
    try:
        return max(0.5, float(g))
    except (TypeError, ValueError):
        return {'LND': 1.0}.get(str(g).strip(), 2.0)


def main(xlsx, tod_csv, sz_path, lu_path, out):
    # ---- residents per subzone (true totals) ----
    ws = openpyxl.load_workbook(xlsx, read_only=True).worksheets[0]
    pop = {}
    for row in ws.iter_rows(values_only=True):
        if row and row[0] and row[1] and row[0] != 'Total' and row[1] != 'Total' and row[2] == 'Total' and row[3] == 'Total':
            v = row[4]
            pop[(row[0].upper(), row[1].upper())] = int(v) if isinstance(v, (int, float)) else 0
    # ---- dwelling mix ----
    tod = defaultdict(lambda: defaultdict(int))
    for r in csv.DictReader(open(tod_csv, encoding='utf-8-sig')):
        t = r['TOD']
        k = 'hdb' if t.startswith('HDB') else 'condo' if 'Condominium' in t else 'landed' if 'Landed' in t else 'other'
        tod[(r['PA'].upper(), r['SZ'].upper())][k] += int(r['Pop'])

    sz = gpd.read_file(sz_path).to_crs(3414)
    sz['key'] = list(zip(sz.PLN_AREA_N, sz.SUBZONE_N))
    missing = [k for k in sz.key if k not in pop]
    if missing:
        raise SystemExit(f'no population for {missing}')
    sz['pop'] = sz.key.map(pop)
    sz['km2'] = sz.area / 1e6
    sz = sz.sort_values(['PLN_AREA_N', 'SUBZONE_N']).reset_index(drop=True)
    sz['i'] = sz.index

    # ---- dasymetric weights ----
    lu = gpd.read_file(lu_path)[['LU_DESC', 'GPR', 'geometry']].to_crs(3414)
    lu['LU_DESC'] = lu.LU_DESC.str.strip()
    lu['geometry'] = lu.geometry.make_valid()
    res = lu[lu.LU_DESC.isin(RES)].copy()
    res['wm'] = res.LU_DESC.map(RES) * res.GPR.map(gpr_num)
    res = gpd.overlay(res[['wm', 'geometry']], sz[['i', 'geometry']], how='intersection', keep_geom_type=True)
    res['w'] = res.area * res.wm
    wsum = res.groupby('i').w.sum()
    no_res = [i for i in sz.i if sz.loc[i, 'pop'] > 0 and wsum.get(i, 0) <= 0]
    parts = [res[['i', 'w', 'geometry']]]
    if no_res:
        dry = lu[~lu.LU_DESC.isin(DRY_SKIP)][['geometry']]
        d = gpd.overlay(dry, sz[sz.i.isin(no_res)][['i', 'geometry']], how='intersection', keep_geom_type=True)
        d['w'] = d.area
        parts.append(d[['i', 'w', 'geometry']])
    W = gpd.GeoDataFrame(np.concatenate([p.values for p in parts]), columns=['i', 'w', 'geometry'], geometry='geometry', crs=3414)
    W['w'] = W.w.astype(float)
    W['i'] = W.i.astype(int)
    tot = W.groupby('i').w.sum()
    W['p'] = W.apply(lambda r: sz.loc[r.i, 'pop'] * r.w / tot[r.i], axis=1)
    W = W[W.p > 0]

    # ---- grid ----
    x0, y0, x1, y1 = sz.total_bounds
    x0, y0 = math.floor(x0 / CELL) * CELL, math.floor(y0 / CELL) * CELL
    cells = [box(x, y, x + CELL, y + CELL) for x in np.arange(x0, x1, CELL) for y in np.arange(y0, y1, CELL)]
    grid = gpd.GeoDataFrame({'c': range(len(cells))}, geometry=cells, crs=3414)
    W['dens'] = W.p / W.area
    pieces = gpd.overlay(W[['dens', 'geometry']], grid, how='intersection', keep_geom_type=True)
    pieces['p'] = pieces.dens * pieces.area
    cellpop = pieces.groupby('c').p.sum()
    cellpop = cellpop[cellpop >= 1]
    cent = grid.loc[cellpop.index].geometry.centroid.to_crs(4326)
    spikes = [[round(pt.x, 5), round(pt.y, 5), int(round(p))] for pt, p in zip(cent, cellpop.values)]

    # ---- geometry, simplified, delta-encoded ----
    geo4326 = sz.geometry.simplify(8).to_crs(4326)

    def enc_ring(ring):
        pts = [(round(x * 1e5), round(y * 1e5)) for x, y in ring.coords]
        out, px, py = [], 0, 0
        for x, y in pts:
            out += [x - px, y - py]
            px, py = x, y
        return out

    geo = []
    for g in geo4326:
        polys = getattr(g, 'geoms', [g])
        geo.append([[enc_ring(p.exterior)] + [enc_ring(r) for r in p.interiors if r.length > 0] for p in polys])

    rows = []
    for _, r in sz.iterrows():
        t = tod.get(r.key, {})
        tt = sum(t.values()) or 1
        rows.append([r.SUBZONE_N.title(), r.PLN_AREA_N.title(), int(r['pop']), round(r.km2, 3),
                     *[round(100 * t.get(k, 0) / tt) for k in ('hdb', 'condo', 'landed', 'other')]])
    data = {'year': 2026, 'cell': CELL, 'fields': ['name', 'pa', 'pop', 'km2', 'hdb', 'condo', 'landed', 'other'],
            'sz': rows, 'geo': geo, 'spikes': spikes}
    with open(out, 'w') as f:
        json.dump(data, f, separators=(',', ':'))
    d = sz['pop'] / sz.km2
    print('subzones', len(sz), 'residents', int(sz['pop'].sum()), 'km2', round(sz.km2.sum(), 1))
    print('spike cells', len(spikes), 'max cell pop', max(s[2] for s in spikes), 'max cell density', round(max(s[2] for s in spikes) / (CELL * CELL / 1e6)))
    top = sz.assign(d=d).sort_values('d', ascending=False)
    print(top[['SUBZONE_N', 'PLN_AREA_N', 'pop', 'km2', 'd']].head(5).to_string())
    print(top[top['pop'] > 0][['SUBZONE_N', 'PLN_AREA_N', 'pop', 'km2', 'd']].tail(8).to_string())
    print('zero-resident subzones', int((sz['pop'] == 0).sum()))


if __name__ == '__main__':
    main(*sys.argv[1:6])
