#!/usr/bin/env bash
# One-command start on macOS / Linux: venv -> deps -> index -> server.
#
# With certs/ from scripts/local-domain.sh it serves
# https://arnobotinteractiverobot.com; without them, http://127.0.0.1:8000.
# Either way it listens on 127.0.0.1 only — reachable from this Mac alone.
set -euo pipefail
cd "$(dirname "$0")"

DOMAIN="${ROBOT_DOMAIN:-arnobotinteractiverobot.com}"

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

if [[ -f certs/site.pem && -f certs/site.key ]]; then
  # scripts/local-domain.sh forwards 127.0.0.1:443/80 to these two ports, so
  # the plain https:// address works without a port number.
  .venv/bin/python scripts/redirect_http.py "$DOMAIN" 8080 &
  trap 'kill $! 2>/dev/null' EXIT
  echo
  echo "Open https://$DOMAIN"
  echo
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8443 \
    --ssl-keyfile certs/site.key --ssl-certfile certs/site.pem
else
  echo
  echo "Open http://127.0.0.1:8000   (run scripts/local-domain.sh for https://$DOMAIN)"
  echo
  .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
fi
