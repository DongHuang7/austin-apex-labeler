#!/usr/bin/env bash
# Starts the Flask app locally against dev/local.db (SQLite), in the
# background. Kills any previous instance first, so this is safe to re-run
# after code changes (no autoreload — this project's app.run() doesn't set
# debug=True). Prints the PID and confirms /login responds before exiting.
set -euo pipefail
cd "$(dirname "$0")/../.."

PORT="${PORT:-5050}"
DEV_DB_PATH="$(pwd)/dev/local.db"

if [ ! -f "$DEV_DB_PATH" ]; then
  echo "No dev DB yet — running seed_db.py first ..."
  .venv/bin/python scripts/dev/seed_db.py
fi

pkill -f "app.py" 2>/dev/null || true
sleep 1

DATABASE_URL="sqlite:///$DEV_DB_PATH" \
FLASK_SECRET_KEY="dev-only-not-a-real-secret" \
APP_BASE_URL="http://localhost:$PORT" \
GOOGLE_CLIENT_ID="dev-placeholder" \
GOOGLE_CLIENT_SECRET="dev-placeholder" \
PORT="$PORT" \
.venv/bin/python app.py > dev/server.log 2>&1 &

PID=$!
disown
sleep 2

if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$PORT/login" | grep -q 200; then
  echo "Dev server up at http://localhost:$PORT (PID $PID) — login: yifan@austinapexre.com / devpass123"
else
  echo "Server did not come up — check dev/server.log"
  exit 1
fi
