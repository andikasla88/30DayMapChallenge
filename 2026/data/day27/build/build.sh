#!/bin/sh
# Day 27 data build: fetch the OSM extract into $RAW (outside the repo), then write ../underground.js.
# usage: sh build.sh <raw-dir>
# PY must point at a Python with pyosmium>=4, shapely>=2 and numpy:
#   python -m venv venv && venv/Scripts/pip install osmium shapely numpy
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/../underground.js"
