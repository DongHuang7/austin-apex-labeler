#!/usr/bin/env bash
# Idempotent local dev venv setup. Safe to re-run any time — only installs
# what's missing. Creates server/.venv (gitignored), separate from whatever
# environment `flask run`/production uses, so local testing never touches
# real dependencies or the real database.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ ! -d .venv ]; then
  echo "Creating .venv ..."
  python3 -m venv .venv
fi

.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
echo "Dev venv ready at $(pwd)/.venv"
