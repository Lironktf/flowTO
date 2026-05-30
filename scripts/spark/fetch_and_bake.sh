#!/usr/bin/env bash
# Run the real data fetch + bake on the Spark (disk + network live there), then
# pull the baked store back to the dev box. This is the FLO-7 "real data" path:
# the dev box mocks network in tests; the Spark does the heavy fetch for real.
#
#   scripts/spark/fetch_and_bake.sh [--only centreline,intersections,tmc,ttc]
#
# Produces on the Spark (and pulls back):
#   data/parquet/{centreline,intersections,tmc,signals,bridges,zones}.parquet
#   data/catalog.duckdb · data/manifest.json · data/transit/{agency}_*.json
set -euo pipefail
HERE="$(dirname "$0")"
source "$HERE/env.sh"

ONLY="${1:-}"
ONLY_ARG=""
if [[ "$ONLY" == "--only" ]]; then
  ONLY_ARG="--only $2"
elif [[ -n "$ONLY" ]]; then
  ONLY_ARG="--only $ONLY"
fi

# 1) Push the current tree so the Spark runs this exact code.
"$HERE/push.sh"

# 2) Fetch (network) + bake (parquet/catalog/manifest + transit cache) + verify.
"$HERE/run.sh" "pip install -e '.[data,api,transit]' >/dev/null 2>&1 || true; \
  python -m torontosim.datapipeline fetch $ONLY_ARG && \
  python -m torontosim.datapipeline bake && \
  python -m torontosim.datapipeline verify"

# 3) Pull the baked artifacts back (gitignored locally; provenance via manifest).
"$HERE/pull.sh" data/parquet ./data/parquet
"$HERE/pull.sh" data/catalog.duckdb ./data/catalog.duckdb
"$HERE/pull.sh" data/manifest.json ./data/manifest.json
"$HERE/pull.sh" data/transit ./data/transit || true

echo "[spark] fetch+bake complete; verify duckdb data/catalog.duckdb \"select count(*) from centreline\""
