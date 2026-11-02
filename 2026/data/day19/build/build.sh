#!/usr/bin/env bash
# Day 19 · Smell: rebuild data/day19/smell.js from scratch.
#   RAW=<scratch folder for downloads> bash build.sh
# Python 3.9+, standard library only. No API key is needed.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
RAW="${RAW:?set RAW to a scratch folder for the raw downloads}"
python -I "$HERE/fetch.py" "$RAW"
python -I "$HERE/process.py" "$RAW" "$HERE/../smell.js"
