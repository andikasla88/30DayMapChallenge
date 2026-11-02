#!/bin/sh
# Day 22 data build: fetch the raw files into $RAW (outside the repo), then write ../projections.js.
# usage: sh build.sh <raw-dir>
# PY must point at a Python with shapely>=2, pyproj>=3 (PROJ 9) and numpy:
#   python -m venv venv && venv/Scripts/pip install shapely pyproj numpy
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/../projections.js"
