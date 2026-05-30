#!/usr/bin/env bash
# Nsight Systems trace around a simulation run on the Spark (P11).
# Pull the .nsys-rep back with scripts/spark/pull.sh.
set -euo pipefail
source "$(dirname "$0")/env.sh"
ssh $SSH_OPTS "$SPARK_HOST" "cd $REMOTE_DIR && \
  { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && \
  nsys profile -o sim_trace --force-overwrite true \
    python -m torontosim.perf.bench || \
  echo 'nsys unavailable — falling back to in-app counters (python -m torontosim.perf.bench)'"
