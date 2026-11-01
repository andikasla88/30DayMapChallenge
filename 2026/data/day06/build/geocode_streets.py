"""Resolve each HDB Property Information street name to the footprint street code (ST_COD).
For every street, geocode up to 3 of its blocks with OneMap search (browser User-Agent),
take the returned postal code, and look it up in the HDB Existing Building footprints.
Cached to <raw>/onemap_cache.json. usage: python -X utf8 geocode_streets.py <raw_dir>
Also imported by build_blocks.py for expand() and search()."""
import sys, os, json, csv, time, collections, requests

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
ABBR = {'RD': 'ROAD', 'ST': 'STREET', 'AVE': 'AVENUE', 'STH': 'SOUTH', 'NTH': 'NORTH', 'BT': 'BUKIT', 'JLN': 'JALAN',
        'LOR': 'LORONG', 'KG': 'KAMPONG', 'TG': 'TANJONG', 'UPP': 'UPPER', 'CRES': 'CRESCENT', 'CL': 'CLOSE', 'DR': 'DRIVE',
        'PK': 'PARK', 'IND': 'INDUSTRIAL', 'CTRL': 'CENTRAL', "C'WEALTH": 'COMMONWEALTH', 'PL': 'PLACE', 'HTS': 'HEIGHTS',
        'TER': 'TERRACE', 'GDNS': 'GARDENS', 'MKT': 'MARKET', 'CTR': 'CENTRE', 'SQ': 'SQUARE', 'MT': 'MOUNT', 'LK': 'LINK',
        'GRN': 'GREEN', 'VW': 'VIEW', 'BLVD': 'BOULEVARD', 'CT': 'COURT', 'ESTS': 'ESTATES', 'ST.': 'SAINT'}


def expand(s):
    return ' '.join(ABBR.get(w, w) for w in s.split())


RAW = sys.argv[1]
_cache_p = os.path.join(RAW, 'onemap_cache.json')
_cache = json.load(open(_cache_p)) if os.path.exists(_cache_p) else {}


def save_cache():
    json.dump(_cache, open(_cache_p, 'w'))


def search(q):
    if q in _cache: return _cache[q]
    for _ in range(5):
        try:
            r = requests.get('https://www.onemap.gov.sg/api/common/elastic/search',
                             params={'searchVal': q, 'returnGeom': 'Y', 'getAddrDetails': 'Y', 'pageNum': 1}, headers=UA, timeout=30)
            if r.status_code == 200:
                _cache[q] = r.json().get('results', []); time.sleep(0.25); return _cache[q]
        except Exception as e:
            print('err', e)
        time.sleep(3)
    return []


def main():
    foot = json.load(open(os.path.join(RAW, 'hdb_buildings.geojson'), encoding='utf-8'))['features']
    by_postal = {f['properties']['POSTAL_COD']: f['properties'] for f in foot}
    rows = list(csv.DictReader(open(os.path.join(RAW, 'hdb_property.csv'), encoding='utf-8')))
    streets = collections.defaultdict(list)
    for r in rows: streets[r['street']].append(r['blk_no'].strip().upper())
    out = {}
    for i, (s, blks) in enumerate(sorted(streets.items())):
        votes = collections.Counter()
        for b in blks[:3]:
            for q in (f'{b} {expand(s)}', f'{b} {s}'):
                hit = [x for x in search(q) if x['BLK_NO'].upper() == b and x['POSTAL'] in by_postal]
                if hit:
                    votes[by_postal[hit[0]['POSTAL']]['ST_COD']] += 1
                    break
            if votes and votes.most_common(1)[0][1] >= 2: break
        out[s] = votes.most_common(1)[0][0] if votes else None
        if i % 50 == 0:
            print(i, s, out[s], flush=True); save_cache()
    save_cache()
    json.dump(out, open(os.path.join(RAW, 'street_to_stcod.json'), 'w'), indent=0)
    print('unresolved', [s for s, c in out.items() if not c])


if __name__ == '__main__':
    main()
