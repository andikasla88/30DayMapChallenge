#!/bin/sh
# Day 15 data build: fetch, then process. Raw downloads go to $1 (outside the repo); outputs to ..
# usage: sh build.sh <raw-dir>
# Python needs: requests shapely pyproj numpy rasterio pillow scipy osmium  (set PY to that python)
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"          # OSM extract + Landsat 1 MSS crop (Planetary Computer)
"$PY" -I "$HERE/osm_names.py" "$RAW"      # names, coastline, boundary, inland water -> $RAW/osm.pkl
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/.."   # -> inside-out.json, landsat-1973.jpg
