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
# Ports for the API + Vite dev server. Override (with a unique tmux SESSION) to
# run a throwaway instance alongside the shared one without clobbering :8000/:5173.
API_PORT="${TS_API_PORT:-8000}"
WEB_PORT="${TS_WEB_PORT:-5173}"
# Assignment backend for the heavy startup warm-up (cpu | gpu/cuGraph). On the
# GB10 set TS_BACKEND=gpu so the 12k-pair citywide baseline warms via cuGraph.
BACKEND="${TS_BACKEND:-cpu}"

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
  "cd $REMOTE_DIR && { [ -f $REMOTE_VENV/bin/activate ] && source $REMOTE_VENV/bin/activate || true; } && pip install -e '.[data,api,transit]' >/dev/null 2>&1 || true; TS_GRAPH_SOURCE=$GRAPH_SRC TS_BACKEND=$BACKEND HOST=127.0.0.1 PORT=$API_PORT scripts/run_api.sh" C-m
tmux new-window -t "$SESSION" -n web
tmux send-keys -t "$SESSION:web" \
  "cd $REMOTE_DIR/frontend && npm install && VITE_PROXY_TARGET=http://localhost:$API_PORT npm run dev -- --port $WEB_PORT --strictPort" C-m
echo "[spark] tmux session '$SESSION' started (windows: api, web)."
EOF

cat <<EOF

[serve] API + Vite are starting on the Spark (graph_source=$GRAPH_SRC).
[serve] Forward both ports to your localhost, then open the UI:

    ssh -N -L $WEB_PORT:localhost:$WEB_PORT -L $API_PORT:localhost:$API_PORT $SPARK_HOST

    UI   -> http://localhost:$WEB_PORT
    Docs -> http://localhost:$API_PORT/docs

[serve] Tail the logs:   ssh $SPARK_HOST -t 'tmux attach -t $SESSION'   (Ctrl-b d to detach)
[serve] Stop everything: ssh $SPARK_HOST 'tmux kill-session -t $SESSION'
EOF
