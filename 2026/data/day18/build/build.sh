#!/bin/sh
# Day 18 data build: fetch, then process. Raw downloads go to $1 (outside the repo); outputs to ..
# usage: sh build.sh <raw-dir>
# Python needs: requests shapely pyproj numpy rasterio pillow pyshp scipy  (set PY to that python)
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"            # EPSG, OSM (Overpass, Nominatim), Marine Regions, Natural Earth, NOAA, data.gov.sg, STAC search
"$PY" -I "$HERE/scan.py" "$RAW"             # null-record check of the data.gov.sg point datasets -> $RAW/scan.json
"$PY" -I "$HERE/s2.py" "$RAW"               # Sentinel-2 crop around SVY21 (0, 0) -> $RAW/s2/
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/.."   # -> null.js (the Sentinel-2 crop inside it)
