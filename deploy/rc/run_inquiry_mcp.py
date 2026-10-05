"""Start the app-owned inquiry MCP from an operator-private configuration.

The generic FLUJO server config contains a file path, never the provider key.
This process has no banking configuration, credentials or bank client.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-config", type=Path, required=True)
    args = parser.parse_args()
    path = args.private_config.resolve()
    if os.name != "nt" and path.stat().st_mode & 0o077:
        raise ValueError("owner-private MCP configuration required")
    config = json.loads(path.read_text(encoding="utf-8"))
    allowed = {
        "SAVIA_INQUIRY_PROVIDER", "SAVIA_INQUIRY_MODEL_URL",
        "SAVIA_INQUIRY_MODEL_ID", "SAVIA_INQUIRY_MODEL_TOKEN",
        "SAVIA_INQUIRY_STATE_DIR", "SAVIA_INQUIRY_OWNER",
    }
    if (not isinstance(config, dict) or set(config) - allowed
            or not {"SAVIA_INQUIRY_STATE_DIR", "SAVIA_INQUIRY_OWNER"} <= set(config)
            or any(not isinstance(value, str) or not value or "\0" in value for value in config.values())):
        raise ValueError("invalid private MCP configuration")
    for key in allowed:
        os.environ.pop(key, None)
    os.environ.update(config)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from savia_assistant.mcp import main as serve
    serve()


if __name__ == "__main__":
    main()
