#!/bin/sh
# Day 04 "Where Singapore's trades huddle": rebuild 2026/data/day04/trades.js.
# usage: sh build.sh <scratch dir>     (needs node 18+, curl, unzip; about 700 MB of downloads)
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
W="${1:?scratch dir}"; mkdir -p "$W/acra"; cd "$W"
# ACRA Information on Corporate Entities: one CSV per letter, plus "others" (data.gov.sg collection 2)
for id in $(curl -s "https://api-production.data.gov.sg/v2/public/api/collections/2/metadata" | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>console.log(JSON.parse(s).data.collectionMetadata.childDatasets.join(' ')))"); do
  [ -s "acra/$id.csv" ] || curl -s -o "acra/$id.csv" "$(curl -s "https://api-open.data.gov.sg/v1/public/api/datasets/$id/poll-download" | node -e "let s='';process.stdin.on('data',d=>s+=d).on('end',()=>console.log(JSON.parse(s).data.url))")"
  sleep 2
done
# SSIC 2025 classification structure (SingStat), sheet 1 to {code: title}
[ -s ssic2025.json ] || {
  curl -sL -A "Mozilla/5.0" -o ssic2025.xlsx "https://www.singstat.gov.sg/files/d72a3cb8-16c9-49c6-aec6-8b7360831072.xlsx"
  rm -rf ssic2025 && mkdir ssic2025 && (cd ssic2025 && unzip -oq ../ssic2025.xlsx)
  node "$HERE/ssic.mjs" ssic2025 > ssic2025.json
}
# a 2023 scrape of OneMap's postal codes, to spare OneMap most of the lookups
[ -s postal_xkjyeah.json ] || curl -sL -o postal_xkjyeah.json "https://raw.githubusercontent.com/xkjyeah/singapore-postal-codes/master/buildings.json"
node --max-old-space-size=6000 "$HERE/prep.mjs" "$W"
node "$HERE/geocode.mjs" "$W" 300
node --max-old-space-size=6000 "$HERE/analyse.mjs" "$W" "$HERE/../trades.js"
