#!/usr/bin/env bash
# Nsight Systems trace around a Nemotron copilot call on the Spark (P11).
set -euo pipefail
source "$(dirname "$0")/env.sh"
ssh $SSH_OPTS "$SPARK_HOST" "cd $REMOTE_DIR && \
  { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && \
  nsys profile -o llm_trace --force-overwrite true \
    python scripts/spark/smoke_ollama.py nemotron3:33b || \
  echo 'nsys unavailable — use smoke_ollama.py eval_ms + nvidia-smi as evidence'"
