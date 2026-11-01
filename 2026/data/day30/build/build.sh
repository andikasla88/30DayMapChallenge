#!/bin/sh
# Day 30 data build: fetch SLA's coast into $RAW (outside the repo), then write ../paper.json.
# usage: sh build.sh <raw-dir>
# PY must point at a Python with shapely>=2, pyproj>=3 and numpy:
#   python -m venv venv && venv/Scripts/pip install shapely pyproj numpy
# Also reads Day 10's files, read only: ../../day10/build/answer.json (Claude's drawing)
# and ../../day10/memory.json (Day 10's published scores and its station points).
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
mkdir -p "$RAW" && cd "$RAW"
# Coast: SLA National Map Polygon (Coastal_Outlines layer), data.gov.sg, the same file Day 10 scored against
ID=d_29f066d67df3eae91df8a42f443863c8
if [ ! -s nmp.geojson ]; then
  url=$(curl -sf "https://api-open.data.gov.sg/v1/public/api/datasets/$ID/poll-download" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['data']['url'])")
  curl -sf -o nmp.geojson "$url"
fi
D10="$HERE/../../day10"
"$PY" -I "$HERE/process.py" nmp.geojson "$D10/build/answer.json" "$D10/memory.json" "$HERE/../paper.json"
