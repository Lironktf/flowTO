#!/usr/bin/env bash
# Deploy an ISOLATED demo instance to the Spark on UNIQUE ports, so it coexists
# with another server already on :8000 / :5173 (shared box). API on :8010 (small
# OD = fast warm, TS_BACKEND=gpu/cuGraph), Vite on :5180 (proxy -> :8010), in a
# separate tmux session 'torontosim-demo'.
#
# Uses PYTHONPATH=<repo>/src (NOT pip install -e) so it never re-points the shared
# venv's editable install — another server on the box is left untouched.
#
#   scripts/spark/serve_demo.sh                # push + serve
#   scripts/spark/serve_demo.sh --no-push      # serve what's already on the Spark
#   API_PORT=8011 WEB_PORT=5181 scripts/spark/serve_demo.sh
#
# Export VITE_MAPBOX_TOKEN (a Mapbox public pk.* token) before running, or the
# basemap renders a "token required" placeholder. The token is forwarded to Vite
# as an env var — never committed.
set -euo pipefail
HERE="$(dirname "$0")"
source "$HERE/env.sh"

API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-5180}"
BACKEND="${TS_BACKEND:-gpu}"
MAX_PAIRS="${TS_MAX_PAIRS:-2000}"
SESSION="${TS_DEMO_SESSION:-torontosim-demo}"

if [[ "${1:-}" != "--no-push" ]]; then
  "$HERE/push.sh"
fi

ssh $SSH_OPTS "$SPARK_HOST" bash -s <<EOF
set -e
tmux kill-session -t "$SESSION" 2>/dev/null || true
fuser -k ${API_PORT}/tcp ${WEB_PORT}/tcp 2>/dev/null || true
sleep 2
tmux new-session -d -s "$SESSION" -n api
tmux send-keys -t "$SESSION:api" \
  "cd $REMOTE_DIR && PYTHONPATH=$REMOTE_DIR/src TS_BACKEND=$BACKEND TS_MAX_PAIRS=$MAX_PAIRS PORT=$API_PORT $REMOTE_VENV/bin/python scripts/serve_demo_api.py 2>&1 | tee /tmp/demo_api.log" C-m
tmux new-window -t "$SESSION" -n web
tmux send-keys -t "$SESSION:web" \
  "cd $REMOTE_DIR/frontend && VITE_PROXY_TARGET=http://localhost:$API_PORT VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN npm run dev -- --port $WEB_PORT --strictPort 2>&1 | tee /tmp/demo_web.log" C-m
echo "[demo] tmux '$SESSION' started: api :$API_PORT, web :$WEB_PORT"
EOF

cat <<EOF

[demo] Isolated demo on unique ports (coexists with the :8000/:5173 server).
[demo] Forward both, then open the UI:

    ssh -N -L $WEB_PORT:localhost:$WEB_PORT -L $API_PORT:localhost:$API_PORT $SPARK_HOST
    UI -> http://localhost:$WEB_PORT/app.html

[demo] Logs: ssh $SPARK_HOST -t 'tmux attach -t $SESSION'   (Ctrl-b d to detach)
[demo] Stop: ssh $SPARK_HOST 'tmux kill-session -t $SESSION'
EOF
