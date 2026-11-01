#!/bin/sh
# Day 09 data build. Raw downloads go to $RAW (outside the repo); output to ../density.json.
# usage: sh build.sh <raw-dir>
set -e
RAW="${1:?raw dir}"; HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PY:-C:/Users/Andika/AppData/Local/Temp/dmc30geo/Scripts/python}"   # needs geopandas, openpyxl
mkdir -p "$RAW" && cd "$RAW"
UA="Mozilla/5.0"
# SingStat, Population Trends: Geographic Distribution (latest data page, files dated 25 Sep 2026)
# https://www.singstat.gov.sg/find-data/explore-data-themes/population/geographic-distribution/latest-news-data
#   "Singapore Residents by Planning Area/Subzone, Single Year of Age and Sex, June 2026" (Excel)
curl -sL -A "$UA" -o respop2026.xlsx https://www.singstat.gov.sg/files/976b7278-e255-435e-90a6-e6658561caa4.xlsx
#   "... Age Group, Sex and Type of Dwelling, June 2026" (CSV, zipped)
curl -sL -A "$UA" -o respoptod2026.zip https://www.singstat.gov.sg/files/c6755f50-4bfb-4bfa-b7d3-00259b9509ed.zip
unzip -o -q respoptod2026.zip
# data.gov.sg: URA MP2019 Subzone Boundary (No Sea) and MP2019 Land Use
for id in d_8594ae9ff96d0c708bc2af633048edfb d_90d86daa5bfaa371668b84fa5f01424f; do
  [ -s "$id.geojson" ] && continue
  url=$(curl -s "https://api-open.data.gov.sg/v1/public/api/datasets/$id/poll-download" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['data']['url'])")
  curl -s -o "$id.geojson" "$url"
done
"$PY" -I "$HERE/prep.py" respop2026.xlsx respopagesextod2026.csv d_8594ae9ff96d0c708bc2af633048edfb.geojson d_90d86daa5bfaa371668b84fa5f01424f.geojson "$HERE/../density.json"
