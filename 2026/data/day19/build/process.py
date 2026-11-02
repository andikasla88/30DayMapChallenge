"""Day 19 · Smell: turn the raw downloads into data/day19/smell.js.

  hawkers  every hawker centre that is open today (status "Existing", "Existing (new)",
           "Existing (replacement)" or "Interim Centre"; the 6 still under construction
           are left out), as [display name, lng, lat, cooked-food stalls, status code].
           A few markets list 0 cooked-food stalls; they are kept but make no plume.
  wind     the latest NEA wind readings, one row per station that reported both a
           direction and a speed: [id, name, lng, lat, direction from (deg), speed (knots)].
           The page uses this only when it cannot fetch live readings.
  summary  the counts quoted on the page.

Standard library only (no pip installs needed).
usage: python process.py <raw-dir> <out.json>
"""
import json, re, sys, pathlib

RAW = pathlib.Path(sys.argv[1]); OUT = pathlib.Path(sys.argv[2])
OPEN = {'Existing': 'E', 'Existing (new)': 'N', 'Existing (replacement)': 'R', 'Interim Centre': 'I'}


def display_name(raw):
    """'Smith Street Blk 335 (Chinatown Complex Market)' -> 'Chinatown Complex Market';
    'Bedok North Street 1 Blk 216' -> 'Blk 216 Bedok North Street 1';
    'Maxwell Food Centre (Kim Hua Market)' -> 'Maxwell Food Centre'."""
    raw = ' '.join(raw.split())
    m = re.match(r'^(.*?) Blk (.+?)(?: \((.*)\))?$', raw)
    if m:
        street, blk, alias = m.groups()
        return alias.strip() if alias else f'Blk {blk} {street}'
    return raw.split(' (')[0].strip()


geo = json.loads((RAW / 'hawker-centres.geojson').read_text(encoding='utf-8'))
rows, skipped = [], {}
for f in geo['features']:
    p = f['properties']
    status = p['STATUS']
    if status not in OPEN:
        skipped[status] = skipped.get(status, 0) + 1
        continue
    lng, lat = f['geometry']['coordinates'][:2]
    stalls = p['NUMBER_OF_COOKED_FOOD_STALLS']
    if stalls is None:
        raise SystemExit(f'no stall count for {p["NAME"]}')
    rows.append([display_name(p['NAME']), round(lng, 5), round(lat, 5), int(stalls), OPEN[status]])
rows.sort(key=lambda r: (-r[3], r[0]))
names = [r[0] for r in rows]
dupes = {n for n in names if names.count(n) > 1}
if dupes:
    raise SystemExit(f'duplicate display names: {dupes}')

updated = max(f['properties']['FMEL_UPD_D'] for f in geo['features'])
cooking = [r for r in rows if r[3] > 0]
summary = {
    'centres': len(rows),
    'cooking': len(cooking),
    'stalls': sum(r[3] for r in rows),
    'noCooked': [r[0] for r in rows if r[3] == 0],
    'underConstruction': skipped.get('Under Construction', 0),
    'largest': rows[0][:1] + rows[0][3:4],
    'medianStalls': sorted(r[3] for r in cooking)[len(cooking) // 2],
    'datasetUpdated': f'{updated[:4]}-{updated[4:6]}-{updated[6:8]}',
}

# wind: join direction and speed by station id
wd = json.loads((RAW / 'wind-direction.json').read_text(encoding='utf-8'))['data']
ws = json.loads((RAW / 'wind-speed.json').read_text(encoding='utf-8'))['data']
assert wd['readingUnit'] == 'degrees', wd['readingUnit']
assert ws['readingUnit'] == 'knots', ws['readingUnit']
stations = {s['id']: s for s in wd['stations'] + ws['stations']}
rd, rs = wd['readings'][0], ws['readings'][0]
d = {x['stationId']: x['value'] for x in rd['data']}
s = {x['stationId']: x['value'] for x in rs['data']}
wind = []
for sid in sorted(set(d) & set(s)):
    st = stations[sid]
    wind.append([sid, st['name'], st['location']['longitude'], st['location']['latitude'], d[sid], s[sid]])

out = {
    'hawkers': {'fields': ['name', 'lng', 'lat', 'stalls', 'status'], 'rows': rows},
    'summary': summary,
    'wind': {'time': rd['timestamp'], 'speedTime': rs['timestamp'], 'type': [wd['readingType'], ws['readingType']],
             'fields': ['id', 'name', 'lng', 'lat', 'dirFrom', 'knots'], 'rows': wind},
}
OUT.write_text('window.DAY19 = ' + json.dumps(out, ensure_ascii=False, separators=(',', ':')) + ';\n', encoding='utf-8')
print(f'{len(rows)} open centres ({len(cooking)} with cooked food, {summary["stalls"]:,} stalls); '
      f'skipped {skipped}; largest {summary["largest"]}; median {summary["medianStalls"]} stalls')
print(f'wind snapshot {rd["timestamp"]}: {len(wind)} stations')
print(f'wrote {OUT} ({OUT.stat().st_size:,} bytes)')
