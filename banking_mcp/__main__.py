"""Run the MCP, or build an explicitly synthetic local demo."""
from __future__ import annotations

import argparse
import contextlib
import json
import secrets
import sys
from pathlib import Path

import anyio

from .config import Config, load_config
from .security import Authorizer, BankError, StateStore
from .service import Service


def build_demo(out: Path, config_file: Path):
    from pipeline.fixture import cid, write_base
    from pipeline.__main__ import main as run_pipeline
    out, config_file = out.resolve(), config_file.resolve()
    if (out / "CURRENT").exists():
        raise ValueError("refusing to overwrite an existing dataset")
    source = out / "synthetic-source"
    write_base(source)
    with contextlib.redirect_stdout(sys.stderr):
        code = run_pipeline(["run", "--source", str(source), "--out", str(out),
                             "--reports", str(out / "reports")])
    if code:
        raise ValueError("synthetic pipeline failed")
    (out / "SYNTHETIC_BANKING_DEMO.json").write_text(json.dumps({"synthetic": True, "customer": cid(6)}))
    config = Config(mode="synthetic-demo", data_dir=out, state_db=config_file.parent / "demo-state.db",
                    service_token=secrets.token_urlsafe(48), demo_customer=cid(6))
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    print("Synthetic demo prepared. It contains no organizer data.")


def main():
    p = argparse.ArgumentParser(prog="python -m banking_mcp")
    sub = p.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--config", type=Path, required=True)
    serve.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    serve.add_argument("--port", type=int, default=43421)
    serve.add_argument("--host", default="127.0.0.1")
    demo = sub.add_parser("demo")
    demo.add_argument("--out", type=Path, required=True)
    demo.add_argument("--config", type=Path, required=True)
    revoke = sub.add_parser("revoke-session")
    revoke.add_argument("--config", type=Path, required=True)
    coverage = sub.add_parser("attest-sandbox-coverage")
    coverage.add_argument("--config", type=Path, required=True)
    coverage.add_argument("--provenance", required=True)
    args = p.parse_args()
    try:
        if args.command == "demo":
            build_demo(args.out, args.config)
            return 0
        config = load_config(args.config)
        if args.command == "attest-sandbox-coverage":
            if config.mode != "delegated" or config.sandbox_report_coverage_start is None:
                raise BankError("risk_data_unavailable")
            StateStore(config.state_db).attest_sandbox_coverage(
                config.sandbox_report_coverage_start, args.provenance)
            return 0
        if args.command == "revoke-session":
            # Private control channel: never argv/env, and never an advertised tool.
            token = sys.stdin.read(8193)
            if not token or len(token) > 8192:
                raise BankError("authorization_denied")
            Authorizer(config, StateStore(config.state_db)).revoke_assertion(token)
            return 0
        if config.private_host_port is not None and args.transport != "stdio":
            raise ValueError("private host transport requires stdio")
        from .private_host import private_instance_lock
        with private_instance_lock(config):
            service = Service(config)
            from .server import create_http_app, run_stdio
            if args.transport == "stdio":
                if config.private_host_port is None:
                    anyio.run(run_stdio, service)
                else:
                    from .private_host import run_stdio_with_private_http
                    anyio.run(run_stdio_with_private_http, service)
            else:
                import uvicorn
                uvicorn.run(create_http_app(service), host=args.host, port=args.port,
                            log_level="warning", access_log=False)
        return 0
    except (OSError, ValueError, BankError):
        print("Banking MCP could not start. Check the private configuration and published pipeline snapshot.",
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
