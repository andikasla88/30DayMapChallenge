"""Day 18 (NULL): look for null records in public Singapore point datasets.

Requires python 3.10+ with: pyproj
usage: python -I scan.py <raw-dir>        (after fetch.py; writes <raw-dir>/scan.json)

For every dataset in scan_list.SCAN, every record is sorted into exactly one bucket, first match wins:
  no_geometry   the record has no geometry, an empty one, or a coordinate that is not a finite number
  wgs84_zero    it sits at 0 deg N, 0 deg E (within 1e-6 deg, about 11 cm)
  svy21_zero    it sits at SVY21 (0, 0), i.e. within 1 m of 1.0162643 N, 103.5817518 E
  far_away      it lies outside a generous Singapore box (0.9 to 1.6 N, 103.4 to 104.5 E)
  fine          everything else
For every record not in "fine" the scan keeps its name, postal code and coordinate fields, and notes
what explains the position (a blank postal code, or X and Y recorded as 0).
For HDB's car park list (a CSV) the point comes from its own x_coord / y_coord columns, read as SVY21.
"""
import csv
import html
import json
import math
import os
import re
import sys

from pyproj import Transformer

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scan_list import SCAN  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
RAW = sys.argv[1]
TO_WGS = Transformer.from_crs('EPSG:3414', 'EPSG:4326', always_xy=True)
Z_LON, Z_LAT = TO_WGS.transform(0, 0)
COORD_FIELD = re.compile(r'^(x|y|x_?addr|y_?addr|x_?coord(inate)?s?|y_?coord(inate)?s?|lat|lng|lon|long|latitude|longitude|easting|northing)$', re.I)
TD = re.compile(r'<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', re.S | re.I)
catalogue = {d['datasetId']: d for d in json.load(open(os.path.join(RAW, 'dgs', 'catalogue.json'), encoding='utf-8'))}


def bucket(lon, lat):
    if lon is None or lat is None or not (math.isfinite(lon) and math.isfinite(lat)):
        return 'no_geometry'
    if abs(lon) < 1e-6 and abs(lat) < 1e-6:
        return 'wgs84_zero'
    if abs(lon - Z_LON) < 1e-5 and abs(lat - Z_LAT) < 1e-5:
        return 'svy21_zero'
    if not (0.9 <= lat <= 1.6 and 103.4 <= lon <= 104.5):
        return 'far_away'
    return 'fine'


def pairs(coords):
    """Every [lon, lat] pair in a GeoJSON coordinates array."""
    if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
        yield coords
    elif isinstance(coords, (list, tuple)):
        for c in coords:
            yield from pairs(c)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fields_of(props):
    """Plain properties plus the key-value table many data.gov.sg layers keep in an HTML "Description"."""
    out = {k: v for k, v in props.items() if k not in ('Description', 'description')}
    desc = props.get('Description') or props.get('description')
    if isinstance(desc, str) and '<th' in desc.lower():
        for k, v in TD.findall(desc):
            k = html.unescape(re.sub('<[^>]+>', '', k)).strip()
            out[k] = html.unescape(re.sub('<[^>]+>', '', v)).strip()
    return out


def blank(v):
    return v is None or str(v).strip().lower() in ('', 'null', 'none', 'nan', 'na', 'n/a', '-')


def describe(f):
    """A readable name, the address, and what in the record explains where it was put."""
    name = next((str(f[k]) for k in ('HCI_NAME', 'NAME', 'Name', 'name') if not blank(f.get(k)) and not str(f[k]).startswith('kml_')), '')
    postal = next((f[k] for k in f if 'POSTAL' in k.upper()), None)
    coords = {k: f[k] for k in f if COORD_FIELD.match(k.strip()) or re.match(r'^LAND[XY]ADDRESSPOINT$', k)}
    why = []
    if any(re.search('POSTAL', k, re.I) for k in f) and blank(postal):
        why.append('no postal code')
    zeros = [k for k, v in coords.items() if not blank(v) and num(v) == 0]
    if zeros:
        why.append(' and '.join(zeros) + ' recorded as 0')
    return {'name': name, 'postal': None if blank(postal) else str(postal), 'coord_fields': {k: (None if blank(v) else str(v)) for k, v in coords.items()}, 'why': '; '.join(why)}


results = []
for dataset_id, kind in SCAN:
    meta = catalogue.get(dataset_id, {})
    r = {'id': dataset_id, 'name': meta.get('name', dataset_id), 'agency': meta.get('managedByAgencyName', ''),
         'updated': (meta.get('lastUpdatedAt') or '')[:10], 'records': 0,
         'buckets': {'no_geometry': 0, 'wgs84_zero': 0, 'svy21_zero': 0, 'far_away': 0, 'fine': 0}, 'odd': []}
    if kind == 'csv':
        for row in csv.DictReader(open(os.path.join(RAW, 'dgs', f'{dataset_id}.csv'), encoding='utf-8-sig')):
            r['records'] += 1
            x, y = num(row.get('x_coord')), num(row.get('y_coord'))
            if x is None or y is None:
                b = 'no_geometry'
            elif x == 0 and y == 0:
                b = 'svy21_zero'
            else:
                b = bucket(*TO_WGS.transform(x, y))
            r['buckets'][b] += 1
            if b != 'fine':
                r['odd'].append({'bucket': b, 'name': row.get('address', ''), 'x': row.get('x_coord'), 'y': row.get('y_coord')})
    else:
        gj = json.load(open(os.path.join(RAW, 'dgs', f'{dataset_id}.geojson'), encoding='utf-8'))
        for f in gj.get('features', []):
            r['records'] += 1
            g = f.get('geometry') or {}
            pts = list(pairs(g.get('coordinates'))) if g else []
            if not pts:
                b = 'no_geometry'
            else:
                bs = [bucket(num(p[0]), num(p[1]) if len(p) > 1 else None) for p in pts]
                b = next((k for k in ('no_geometry', 'wgs84_zero', 'svy21_zero', 'far_away') if k in bs), 'fine')
            r['buckets'][b] += 1
            if b != 'fine':
                r['odd'].append({'bucket': b, **describe(fields_of(f.get('properties') or {})), 'pt': pts[0][:2] if pts else None})
    results.append(r)
    print(f"{r['records']:>6}  {r['buckets']}  {r['name'][:50]}")
    for o in r['odd'][:8]:
        print('        ', o)

json.dump({'svy21_zero_wgs84': [Z_LON, Z_LAT], 'datasets': results}, open(os.path.join(RAW, 'scan.json'), 'w', encoding='utf-8'), indent=1)
tot = {k: sum(r['buckets'][k] for r in results) for k in results[0]['buckets']}
print(len(results), 'datasets', sum(r['records'] for r in results), 'records', tot)
