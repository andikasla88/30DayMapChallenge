# Day 16 · Collaborative map: Best kopi near you

The page has no backend. It shows two kinds of data:

- `kopi.js`: the seed places, built by the scripts here.
- `pins.js`: the followers' pins, added by hand. It ships empty (`window.DAY16_PINS = [];`).

## Rebuilding kopi.js

```sh
PY=/path/to/python sh build.sh /some/scratch/raw
```

The Python needs `requests osmium shapely pyproj`. No API keys are used.

- `fetch.py` downloads two files:
  - the daily OpenStreetMap Singapore extract from download.openstreetmap.fr
  - NEA's *Hawker Centres (GEOJSON)* from data.gov.sg (`d_4a086da0a5553be1d89383cd90d07ecd`)
- `process.py` picks the places and writes `../kopi.js`. Its docstring lists exactly what is included and why.

## pins.js: the format

The file is a script, `window.DAY16_PINS = [...];` (a script, not JSON, so the page also works opened from disk). The array itself is plain JSON. Each entry looks like this:

```json
[
  {
    "lat": 1.28047,
    "lng": 103.84554,
    "stall": "Ah Seng Kopi",
    "order": "kopi-o.gau.siewdai.peng",
    "by": "@someone",
    "added": "2026-11-16"
  }
]
```

| field | required | rule |
|---|---|---|
| `lat`, `lng` | yes | numbers, 5 decimals; the spot must fall inside Singapore (the outline in `kopi.js`) |
| `stall` | yes | text, at most 60 characters; shown as plain text, never as HTML |
| `order` | yes | an order code (below); unknown words are dropped |
| `by` | no | how the follower wants to be credited, at most 40 characters; only with their consent |
| `added` | no | `YYYY-MM-DD` |

The page skips any entry that fails these checks. It reads at most 2,000 entries.

### Order code

An order code is a drink, then any modifiers, joined by dots:

- **drink:** `kopi`, `kopi-o`, `kopi-c`, `teh`, `teh-o` or `teh-c`
- **strength:** `gau`, `po` or `dilo`
- **sweetness:** `siewdai`, `gahdai` or `kosong`. `kosong` only goes with `-o` or `-c`, because condensed milk is the sugar.
- **extras:** `tarik`, `guyou` (kopi only), `peng` and `tapao`

### Share links

A share link carries one pin:

```
day16-collaborative.html?pin=<lat>,<lng>,<order code>,<stall, URL-encoded>
```

## Adding pins from share links

```sh
python -I pin_links.py "<link>" "<link>"            # prints the entries; check them
python -I pin_links.py --write --by @someone "<link>"   # appends to ../pins.js
```

You can also paste links on stdin, one per line.

The helper makes the same checks as the page:

- the spot must be inside Singapore
- the stall name is cleaned and capped
- the order code keeps only known words

It skips a pin that is already in the file.
