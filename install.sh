#!/usr/bin/env bash
# macOS / Linux convenience installer (Windows 11 is the primary platform: use install.bat there)
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' || { echo "Python 3.11+ required"; exit 1; }
[ -x .venv/bin/python ] || "$PY" -m venv .venv
.venv/bin/python -m pip install --upgrade pip --disable-pip-version-check >/dev/null
.venv/bin/python -m pip install -r requirements.txt
read -r -p "Install Playwright-managed Firefox (~80-100 MB)? [y/N] " a
if [[ "$a" =~ ^[Yy]$ ]]; then .venv/bin/python -m playwright install firefox; fi
.venv/bin/python -m app.paths --init
.venv/bin/python main.py --self-check
echo "Done. Start with ./start.sh"
