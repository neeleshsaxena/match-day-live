#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

PORT="${PORT:-5050}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --reload
