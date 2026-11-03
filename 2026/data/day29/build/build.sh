#!/bin/sh
# Day 29 data build: fetch, then process. Raw downloads go to $1 (outside the repo); outputs to ..
# usage: sh build.sh <raw-dir>
# Python needs: requests numpy rasterio pyproj shapely pillow scipy osmium cmcrameri  (set PY to that python)
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
mkdir -p "$RAW"
[ -s "$RAW/singapore-latest.osm.pbf" ] || curl -fL -A "30DayMapChallenge-day29/1.0" -o "$RAW/singapore-latest.osm.pbf" \
  https://download.openstreetmap.fr/extracts/asia/singapore-latest.osm.pbf
"$PY" -I "$HERE/osm.py" "$RAW"                 # coastline land, reservoirs, reserves, land use, buildings
"$PY" -I "$HERE/fetch.py" "$RAW"               # Landsat C2 L2 survey + clear scenes (Planetary Computer)
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/.."  # -> lst.js (the code PNG inside it)
