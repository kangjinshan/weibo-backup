#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
HOST="${WEIBO_DASHBOARD_HOST:-0.0.0.0}"
PORT="${WEIBO_DASHBOARD_PORT:-8765}"

if [ ! -x "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "Python not found. Run scripts/setup_nas.sh first or set PYTHON_BIN." >&2
    exit 1
  fi
fi

cd "$ROOT"
mkdir -p logs
mkdir -p data
if [ ! -f weiboSpider/config.json ] && [ -f weiboSpider/config.example.json ]; then
  cp weiboSpider/config.example.json weiboSpider/config.json
  echo "Created weiboSpider/config.json from config.example.json. Edit user_id_list and cookie before starting a backup."
fi
export WEIBO_BACKUP_DIR="${WEIBO_BACKUP_DIR:-$ROOT}"

if ! "$PYTHON_BIN" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "Dashboard dependencies are missing for $PYTHON_BIN. Run scripts/setup_nas.sh first or set PYTHON_BIN." >&2
  exit 1
fi

UVICORN_ARGS=(dashboard.server:app --host "$HOST" --port "$PORT")
if [ -n "${WEIBO_DASHBOARD_SSL_CERTFILE:-}" ] || [ -n "${WEIBO_DASHBOARD_SSL_KEYFILE:-}" ]; then
  if [ ! -f "${WEIBO_DASHBOARD_SSL_CERTFILE:-}" ] || [ ! -f "${WEIBO_DASHBOARD_SSL_KEYFILE:-}" ]; then
    echo "SSL certificate or key file is missing." >&2
    exit 1
  fi
  UVICORN_ARGS+=(--ssl-certfile "$WEIBO_DASHBOARD_SSL_CERTFILE" --ssl-keyfile "$WEIBO_DASHBOARD_SSL_KEYFILE")
fi

exec "$PYTHON_BIN" -m uvicorn "${UVICORN_ARGS[@]}"
