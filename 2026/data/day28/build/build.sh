#!/usr/bin/env bash
# Day 28 · Feeling: rebuild data/day28/feeling.js from scratch.
#   RAW=<scratch folder for downloads> PY=<python with shapely, pyproj, numpy> bash build.sh [YYYY-MM-DD]
# fetch.py needs only the standard library; process.py needs shapely>=2, pyproj>=3, numpy.
# No API key is needed. The date (Singapore time) defaults to today: the snapshot is that day so far.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RAW="${RAW:?set RAW to a scratch folder for the raw downloads}"
PY="${PY:-python}"
python -I "$HERE/fetch.py" "$RAW" ${1:+"$1"}
"$PY" -I "$HERE/process.py" "$RAW" "$HERE/../feeling.js" ${1:+"$1"}
