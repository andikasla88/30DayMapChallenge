#!/usr/bin/env bash
# Day 13 · Interactions: rebuild data/day13/od.js from scratch.
#   RAW=<scratch folder for downloads> LTA_API_KEY=<your DataMall key> bash build.sh [YYYYMM]
# Python 3.9+, standard library only. The key is read from the environment and never printed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RAW="${RAW:?set RAW to a scratch folder for the raw downloads}"
: "${LTA_API_KEY:?set LTA_API_KEY to your LTA DataMall account key}"
python -I "$HERE/fetch.py" "$RAW" "$@"
python -I "$HERE/process.py" "$RAW" "$HERE/../od.js"
