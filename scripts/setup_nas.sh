#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$ROOT"
"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements-nas.txt

mkdir -p logs
mkdir -p data
if [ ! -f weiboSpider/config.json ] && [ -f weiboSpider/config.example.json ]; then
  cp weiboSpider/config.example.json weiboSpider/config.json
  echo "Created weiboSpider/config.json from config.example.json. Edit user_id_list and cookie before starting a backup."
fi
rm -f logs/*.pid
echo "Environment ready: $ROOT/.venv"
