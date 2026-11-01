#!/bin/sh
# Day 10 data build. Raw downloads go to $RAW (outside the repo); output to ../memory.json.
# answer.json and prompt.md in this folder are the transcript: written first, never edited.
# usage: sh build.sh <raw-dir>
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"   # needs shapely>=2, pyproj>=3, numpy (pip install shapely pyproj numpy)
mkdir -p "$RAW" && cd "$RAW"
# Rail: cheeaun/sgraildata v5.1.0, pinned to its commit of 12 Jul 2026
SGR=https://raw.githubusercontent.com/cheeaun/sgraildata/d64f9408ef
curl -sfL -o sg-rail.geojson "$SGR/data/v1/sg-rail.geojson"
sleep 1
curl -sfL -o routes.citymapper.json "$SGR/data/raw/routes.citymapper.json"
# Coast: SLA National Map Polygon (Coastal_Outlines layer), data.gov.sg
ID=d_29f066d67df3eae91df8a42f443863c8
if [ ! -s nmp.geojson ]; then
  url=$(curl -sf "https://api-open.data.gov.sg/v1/public/api/datasets/$ID/poll-download" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['data']['url'])")
  curl -sf -o nmp.geojson "$url"
fi
"$PY" -I "$HERE/process.py" "$HERE/answer.json" sg-rail.geojson routes.citymapper.json nmp.geojson "$HERE/../memory.json"
