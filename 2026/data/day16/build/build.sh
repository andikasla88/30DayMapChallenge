#!/bin/sh
# Day 16 data build: fetch, then process. Raw downloads go to $1 (outside the repo); kopi.js goes to ..
# usage: sh build.sh <raw-dir>
# Python needs: requests osmium shapely pyproj  (set PY to that python). No API keys.
# pins.js is not built: the owner adds followers' pins by hand (see README.md and pin_links.py).
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"               # OSM Singapore extract + NEA hawker centres
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/.."  # -> kopi.js
