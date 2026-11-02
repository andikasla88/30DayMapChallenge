#!/bin/sh
# Day 03 "Singapore, quilted": rebuild 2026/data/day03/quilt.js from data.gov.sg.
# usage: sh build.sh <scratch dir>     (needs python with geopandas, node, npx mapshaper)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${1:?scratch dir}"; mkdir -p "$W"; cd "$W"
PY="${PY:-python}"
LU=d_a8c3546b26712e35021f3a681d0353ae   # URA Master Plan 2025 Land Use layer (GeoJSON, ~190 MB)
PA=d_2cc750190544007400b2cfd5d7f53209   # URA Master Plan 2025 Planning Area Boundary (No Sea)
for id in $LU $PA; do
  [ -s "$id.geojson" ] || curl -s -o "$id.geojson" "$(curl -s "https://api-open.data.gov.sg/v1/public/api/datasets/$id/poll-download" | "$PY" -c 'import sys,json;print(json.load(sys.stdin)["data"]["url"])')"
done
"$PY" -I "$HERE/prep.py" "$LU.geojson" "$PA.geojson" .
# Merge touching polygons with the same land use, plot ratio and planning area, then
# simplify topology-preservingly (shared edges stay shared) and drop crumbs.
npx --yes mapshaper@0.6.121 -i patches.geojson \
  -dissolve2 fields=c,u,g,p -explode \
  -each 'a=Math.round(this.area)' -filter 'a >= 200' \
  -simplify interval=4 keep-shapes -clean -filter-slivers min-area=100 -filter remove-empty \
  -o patches.topo.json format=topojson quantization=100000
node "$HERE/encode.mjs" patches.topo.json island.geojson stats.json "$HERE/../quilt.js"
ls -la "$HERE/../quilt.js"
