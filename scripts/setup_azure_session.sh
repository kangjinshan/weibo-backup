#!/usr/bin/env bash
# Run as root on the Azure Ubuntu host after copying the broker source.
set -euo pipefail
SOURCE_DIR="${1:?Usage: setup_azure_session.sh SOURCE_DIR}"
if [ "$(id -u)" != 0 ]; then
  echo "Run this script with sudo." >&2
  exit 1
fi
if ! id weibo-session >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/weibo-session --create-home --shell /usr/sbin/nologin weibo-session
fi
install -d -m 700 -o weibo-session -g weibo-session /var/lib/weibo-session
install -d -m 755 /opt/weibo-session /opt/weibo-session/browsers
python3 -m venv /opt/weibo-session/venv
/opt/weibo-session/venv/bin/python -m pip install -r "$SOURCE_DIR/azure_session/requirements.txt"
PLAYWRIGHT_BROWSERS_PATH=/opt/weibo-session/browsers /opt/weibo-session/venv/bin/python -m playwright install --with-deps chromium
echo "Browser runtime ready. Configure the private token before starting weibo-session.service."
