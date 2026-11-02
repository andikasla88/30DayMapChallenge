"""Day 16: turn pasted share links into pins.js entries. Standard library only.

usage:
  python -I pin_links.py <link> [<link> ...]                 print the entries
  python -I pin_links.py --by @someone <link>                credit the follower (optional)
  python -I pin_links.py --write [--by ...] <link> ...       append them to ../pins.js
  (or paste links on stdin, one per line, instead of passing them as arguments)

A share link looks like
  https://.../day16-collaborative.html?pin=1.28047,103.84554,kopi-o.gau.siewdai.peng,Ah%20Seng%20Kopi
The checks match the page: the spot must fall inside Singapore (the outline in ../kopi.js),
the stall name is cleaned and capped at 60 characters, and the order code keeps only known words.
"""
import json
import os
import re
import sys
import unicodedata
from datetime import date
from urllib.parse import parse_qs, urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
PINS = os.path.join(HERE, '..', 'pins.js')
KOPI = os.path.join(HERE, '..', 'kopi.js')


def load_js(p):   # a data script (window.DAYNN = {...};) back to its object
    t = open(p, encoding='utf-8').read()
    return json.loads(t[t.index('=') + 1:].strip().rstrip(';'))
CTRL = re.compile('[' + ''.join(re.escape(chr(a)) + '-' + re.escape(chr(b)) for a, b in (
    (0x00, 0x1F), (0x7F, 0x9F), (0xAD, 0xAD), (0x200B, 0x200F), (0x2028, 0x202E), (0x2060, 0x206F), (0xFEFF, 0xFEFF), (0xFFF9, 0xFFFB))) + ']')
XS = ['tarik', 'guyou', 'peng', 'tapao']


def clean(s, n):
    s = CTRL.sub('', unicodedata.normalize('NFC', s or ''))
    s = re.sub(r'\s+', ' ', s).strip()
    return s[:n].strip()


def rings():
    out = []
    for f in load_js(KOPI)['land']:
        x, y = f[0], f[1]
        pts = [(x / 1e5, y / 1e5)]
        for i in range(2, len(f), 2):
            x += f[i]; y += f[i + 1]
            pts.append((x / 1e5, y / 1e5))
        out.append(pts)
    return out


LAND = rings()


def in_singapore(lng, lat):
    if not (103.55 < lng < 104.15 and 1.13 < lat < 1.5):
        return False
    for pts in LAND:
        inside, j = False, len(pts) - 1
        for i in range(len(pts)):
            (xi, yi), (xj, yj) = pts[i], pts[j]
            if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
        if inside:
            return True
    return False


def order_code(code):
    """The same rules as the page's parseOrder and fixOrder, written back as a canonical code."""
    t = (code or '').lower().split('.')
    m = re.fullmatch(r'(kopi|teh)(?:-(o|c))?', t[0] if t else '')
    d, milk = (m.group(1), m.group(2) or '') if m else ('kopi', '')
    g = s = ''
    xs = set()
    for w in t[1:]:
        if w in ('gau', 'po', 'dilo'):
            g = w
        elif w in ('siewdai', 'gahdai', 'kosong'):
            s = w
        elif w in XS:
            xs.add(w)
    if s == 'kosong' and not milk:
        s = ''
    if d != 'kopi':
        xs.discard('guyou')
    return '.'.join(x for x in [d + ('-' + milk if milk else ''), g, s, *[k for k in XS if k in xs]] if x)


def entry(link, by=''):
    q = parse_qs(urlsplit(link.strip()).query)
    raw = (q.get('pin') or [''])[0]
    parts = raw.split(',')
    if len(parts) < 4:
        raise ValueError('no pin= in this link, or it is damaged')
    la, lo, code = (p.strip() for p in parts[:3])
    if not re.fullmatch(r'-?\d{1,2}(\.\d{1,7})?', la) or not re.fullmatch(r'-?\d{1,3}(\.\d{1,7})?', lo):
        raise ValueError('the coordinates are damaged')
    lat, lng = round(float(la), 5), round(float(lo), 5)
    if not in_singapore(lng, lat):
        raise ValueError(f'{lat}, {lng} is outside Singapore')
    stall = clean(','.join(parts[3:]), 60)
    if not stall:
        raise ValueError('no stall name')
    e = {'lat': lat, 'lng': lng, 'stall': stall, 'order': order_code(code)}
    if by:
        e['by'] = clean(by, 40)
    e['added'] = date.today().isoformat()
    return e


def main(argv):
    write, by, links = False, '', []
    it = iter(argv)
    for a in it:
        if a == '--write':
            write = True
        elif a == '--by':
            by = next(it, '')
        else:
            links.append(a)
    if not links:
        links = [ln for ln in sys.stdin.read().splitlines() if ln.strip()]
    pins = load_js(PINS) if write else []
    new = []
    for link in links:
        try:
            e = entry(link, by)
        except ValueError as err:
            print(f'skipped: {err}: {link[:120]}', file=sys.stderr)
            continue
        if any(abs(p['lat'] - e['lat']) < 1e-5 and abs(p['lng'] - e['lng']) < 1e-5 and p['stall'] == e['stall'] for p in pins + new):
            print(f'skipped: already there: {e["stall"]}', file=sys.stderr)
            continue
        new.append(e)
    print(json.dumps(new, ensure_ascii=False, indent=2))
    if write and new:
        with open(PINS, 'w', encoding='utf-8') as f:
            f.write('window.DAY16_PINS = ' + json.dumps(pins + new, ensure_ascii=False, indent=2) + ';\n')
            f.write('\n')
        print(f'added {len(new)} pin(s) to {os.path.normpath(PINS)}', file=sys.stderr)


if __name__ == '__main__':
    main(sys.argv[1:])
