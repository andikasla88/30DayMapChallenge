#!/bin/sh
# Day 25 data build. Raw downloads go to $RAW (outside the repo); output to ../diagram.js.
# usage: sh build.sh <raw-dir>
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"   # needs numpy, shapely>=2, pyproj>=3 (pip install numpy shapely pyproj)
mkdir -p "$RAW" && cd "$RAW"
# Rail: cheeaun/sgraildata, pinned to the same commit as Day 10 (12 Jul 2026)
SGR=https://raw.githubusercontent.com/cheeaun/sgraildata/d64f9408ef
[ -s sg-rail.geojson ] || curl -sfL -o sg-rail.geojson "$SGR/data/v1/sg-rail.geojson"
sleep 1
[ -s routes.citymapper.json ] || curl -sfL -o routes.citymapper.json "$SGR/data/raw/routes.citymapper.json"
"$PY" -I "$HERE/process.py" sg-rail.geojson routes.citymapper.json "$HERE/../diagram.js"
