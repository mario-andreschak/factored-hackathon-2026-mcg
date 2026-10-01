"""Serve an isolated banking application with Gloria language orchestration.

Uses an existing private frontend configuration for admission, an independent
state directory, and a configured FLUJO direct model. Portal writes are disabled
for this unactivated qualification instance. Shared worker/graph are untouched.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.server.config import Settings
from frontend.server.app import create_app
from gloria_workflow.host import GloriaHostFactory
from gloria_workflow.model import FlujoModel


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:43420")
    parser.add_argument("--token-file")
    parser.add_argument("--port", type=int, default=43900)
    args = parser.parse_args()
    original = Settings.from_env()
    state = Path(args.state_dir).resolve()
    if state == original.state_dir.resolve() or original.state_dir.resolve() in state.parents:
        raise ValueError("independent qualification state directory required")
    state.mkdir(parents=True, exist_ok=True)
    token = Path(args.token_file).read_text().strip() if args.token_file else None
    model = FlujoModel(args.base_url, args.model, token)
    settings = replace(original, state_dir=state, chat={**original.chat, "action_enabled": False})
    factory = GloriaHostFactory(model, state / "gloria-workflow.sqlite3")
    import uvicorn
    uvicorn.run(create_app(settings, gloria_factory=factory), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
