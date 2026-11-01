#!/bin/sh
# Day 21 data build: fetch, then process. Raw downloads go to $1 (outside the repo); output to ..
# usage: sh build.sh <raw-dir>
# Python needs: requests osmium shapely pyproj   (set PY to that python)
# To rebuild from today's OSM, empty <raw-dir> first: fetch.py skips files it already has.
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"              # OSM extract, Name Suggestion Index, Wikidata checks
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/.."   # -> bubbletea.json
