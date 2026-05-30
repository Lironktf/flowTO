#!/usr/bin/env bash
#
# Download the real Toronto data the demand model trains on:
#   1. TMC intersection counts (City of Toronto Open Data, CKAN datastore)
#   2. Hourly weather (Environment & Climate Change Canada, per-month CSVs)
#
# Everything lands under data/raw/ where `ingest_real_data.py` expects it.
#
# Usage:
#   scripts/fetch_data.sh                 # counts (2020-2029) + weather 2020-2024
#   YEARS="2018 2019 2020 2021 2022 2023 2024" scripts/fetch_data.sh
#   WITH_2010S=1 scripts/fetch_data.sh    # also grab the 2010-2019 counts file
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RAW="$ROOT/data/raw"
WX="$RAW/weather"
mkdir -p "$RAW" "$WX"

CKAN="https://ckan0.cf.opendata.inter.prod-toronto.ca/datastore/dump"
WX_STATION="${WX_STATION:-51459}"     # 51459 = Toronto Pearson Int'l (most complete hourly)
YEARS="${YEARS:-2020 2021 2022 2023 2024}"

echo "==> TMC counts -> $RAW"
curl -fL --retry 3 --output "$RAW/tmc_raw_data_2020_2029.csv" \
  "$CKAN/262469c2-abfe-4756-9068-4ea5c7ba1af7"
if [ "${WITH_2010S:-0}" = "1" ]; then
  curl -fL --retry 3 --output "$RAW/tmc_raw_data_2010_2019.csv" \
    "$CKAN/ae400fe2-98ce-4e73-8a94-024b22e29a22"
fi

echo "==> Hourly weather (station $WX_STATION) -> $WX"
for Y in $YEARS; do
  for M in 1 2 3 4 5 6 7 8 9 10 11 12; do
    OUT="$WX/weather_${Y}_$(printf '%02d' "$M").csv"
    [ -s "$OUT" ] && continue
    URL="https://climate.weather.gc.ca/climate_data/bulk_data_e.html?format=csv&stationID=${WX_STATION}&Year=${Y}&Month=${M}&Day=1&timeframe=1&submit=Download+Data"
    curl -fsL --retry 3 --output "$OUT" "$URL" || echo "   (skip ${Y}-${M})"
  done
  echo "   weather ${Y} done"
done

echo "==> Done."
echo "    counts:  $(ls -1 "$RAW"/tmc_raw_data_*.csv 2>/dev/null | wc -l) file(s)"
echo "    weather: $(ls -1 "$WX"/*.csv 2>/dev/null | wc -l) month-file(s)"
echo "Next: python -m src.model.ingest_real_data"
