"""Savia Pro - runtime configuration."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVING_DB = Path(os.environ.get("SAVIA_SERVING", ROOT / "var" / "serving.duckdb"))
STATE_DIR = Path(os.environ.get("SAVIA_STATE", ROOT / "var" / "state"))
WEB_DIST = Path(os.environ.get("SAVIA_WEB_DIST", ROOT / "web" / "dist"))

HOST = os.environ.get("SAVIA_HOST", "127.0.0.1")
PORT = int(os.environ.get("SAVIA_PORT", "43950"))

# Sessions are signed, not stored. A fresh key each boot means restarting the
# server invalidates every token, which is the behaviour a demo wants.
SESSION_KEY = os.environ.get("SAVIA_SESSION_KEY", secrets.token_hex(32)).encode()
SESSION_TTL_SECONDS = int(os.environ.get("SAVIA_SESSION_TTL", "3600"))

PAGE_LIMIT_MAX = 200
PAGE_LIMIT_DEFAULT = 40
