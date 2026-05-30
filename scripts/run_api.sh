#!/usr/bin/env bash
# Launch the TorontoSim API (loads the full graph + baseline OD at startup).
#   scripts/run_api.sh            # http://localhost:8000  (docs at /docs)
#   PORT=8001 scripts/run_api.sh
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Activate the local venv if present.
[ -f .venv/bin/activate ] && source .venv/bin/activate || true

exec python -c "from torontosim.api.app import serve; serve(host='${HOST}', port=${PORT})"
