#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"

if [ ! -x "$PYTHON_BIN" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
  else
    echo "Python not found. Run scripts/setup_nas.sh first or set PYTHON_BIN." >&2
    exit 1
  fi
fi

if ! "$PYTHON_BIN" -c "import browser_cookie3" >/dev/null 2>&1; then
  echo "browser_cookie3 is missing for $PYTHON_BIN. Run scripts/setup_nas.sh first or install requirements-nas.txt." >&2
  exit 1
fi

cd "$ROOT"
exec "$PYTHON_BIN" scripts/cookie_helper.py
