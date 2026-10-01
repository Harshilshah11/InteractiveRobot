#!/usr/bin/env bash
# One-command start on macOS / Linux: venv -> deps -> index -> server.
# Serves http://127.0.0.1:8000, on this Mac only.
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment..."
  if command -v uv >/dev/null; then
    uv venv --python 3.12 .venv
    uv pip install --python .venv/bin/python -r requirements.txt
  else
    python3 -m venv .venv
    .venv/bin/python -m pip install --upgrade pip --quiet
    .venv/bin/python -m pip install -r requirements.txt
  fi
fi

.venv/bin/python -m app.ingest

echo
echo "Open http://127.0.0.1:8000"
echo
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
