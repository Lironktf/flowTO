#!/usr/bin/env bash
# Launch the TorontoSim API (loads the full graph + baseline OD at startup).
#   scripts/run_api.sh            # http://localhost:8000  (docs at /docs)
#   PORT=8001 scripts/run_api.sh
set -euo pipefail
cd "$(dirname "$0")/.."

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# Pin BLAS/OpenMP to 1 thread per process BEFORE the interpreter starts (numpy
# reads these at import). The day-compute pool runs many equilibrium sims in
# parallel; without this each sim's multi-threaded BLAS would oversubscribe the
# cores and every sim would slow down. One thread/worker → N workers use N cores.
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-1}"
export NUMEXPR_NUM_THREADS="${NUMEXPR_NUM_THREADS:-1}"

# Activate the local venv if present.
[ -f .venv/bin/activate ] && source .venv/bin/activate || true

exec python -c "from torontosim.api.app import serve; serve(host='${HOST}', port=${PORT})"
