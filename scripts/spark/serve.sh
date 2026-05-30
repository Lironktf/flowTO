#!/usr/bin/env bash
# Start the API (8000) + Vite dev server (5173) on the Spark in a tmux session,
# then print the `ssh -L` line to forward both to your localhost. The frontend's
# Vite proxy targets localhost:8000, so both must run on the same host (the
# Spark); SSH forwarding brings them to your machine — no ngrok / public tunnel.
#
#   scripts/spark/serve.sh                              # OSMnx baseline graph
#   TS_GRAPH_SOURCE=centreline scripts/spark/serve.sh   # real Centreline graph
#   scripts/spark/serve.sh --no-push                    # serve what's already on the Spark
#
# Requires tmux + node/npm on the Spark, and (for real data) a prior
# `scripts/spark/fetch_and_bake.sh` so the parquet store + transit cache exist.
set -euo pipefail
HERE="$(dirname "$0")"
source "$HERE/env.sh"

SESSION="${TS_TMUX_SESSION:-torontosim}"
GRAPH_SRC="${TS_GRAPH_SOURCE:-osmnx}"

# Push the current tree first (so the Spark serves this exact code) unless asked
# not to. NOTE: this serves whatever branch you have checked out locally — for
# the merged FLO-7 real-data paths, push from `main`.
if [[ "${1:-}" != "--no-push" ]]; then
  "$HERE/push.sh"
fi

# (Re)create a detached tmux session on the Spark with two windows: api + web.
# Kill any prior session first so the ports are free.
ssh $SSH_OPTS "$SPARK_HOST" bash -s <<EOF
set -e
tmux kill-session -t "$SESSION" 2>/dev/null || true
tmux new-session -d -s "$SESSION" -n api
tmux send-keys -t "$SESSION:api" \
  "cd $REMOTE_DIR && { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && pip install -e '.[data,api,transit]' >/dev/null 2>&1 || true; TS_GRAPH_SOURCE=$GRAPH_SRC HOST=127.0.0.1 PORT=8000 scripts/run_api.sh" C-m
tmux new-window -t "$SESSION" -n web
tmux send-keys -t "$SESSION:web" \
  "cd $REMOTE_DIR/frontend && npm install && npm run dev" C-m
echo "[spark] tmux session '$SESSION' started (windows: api, web)."
EOF

cat <<EOF

[serve] API + Vite are starting on the Spark (graph_source=$GRAPH_SRC).
[serve] Forward both ports to your localhost, then open the UI:

    ssh -N -L 5173:localhost:5173 -L 8000:localhost:8000 $SPARK_HOST

    UI   -> http://localhost:5173
    Docs -> http://localhost:8000/docs

[serve] Tail the logs:   ssh $SPARK_HOST -t 'tmux attach -t $SESSION'   (Ctrl-b d to detach)
[serve] Stop everything: ssh $SPARK_HOST 'tmux kill-session -t $SESSION'
EOF
