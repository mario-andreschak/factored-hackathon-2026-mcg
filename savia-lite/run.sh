#!/usr/bin/env bash
# Start Savia Lite on http://127.0.0.1:43900 (macOS / Linux / WSL).
set -euo pipefail
cd "$(dirname "$0")"
exec "${PYTHON:-python3}" serve.py "$@"
