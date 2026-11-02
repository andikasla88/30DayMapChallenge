#!/bin/sh
# Day 12 data build: fetch the raw files into <raw-dir> (outside the repo), then write ../power.js.
# usage: sh build.sh <raw-dir>        needs a Python with shapely, openpyxl and requests ($PY)
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-python}"
"$PY" -I "$HERE/fetch.py" "$RAW"
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/../power.js"
