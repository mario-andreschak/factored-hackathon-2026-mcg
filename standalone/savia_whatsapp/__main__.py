from __future__ import annotations

import argparse
from pathlib import Path
import shutil

from .runtime import create_control, serve_rc, private_creation_policy


def main():
    parser = argparse.ArgumentParser(description="Standalone Savia/WhatsApp local voice-note lab")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--state", type=Path, required=True)
    serve.add_argument("--mcp-dir", type=Path, required=True)
    serve.add_argument("--provider-env", type=Path)
    serve.add_argument("--backend", choices=("webjs", "baileys"), default="baileys")
    serve.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    serve.add_argument("--container", action="store_true", help="Bind container control UI; publish to loopback only")
    serve.add_argument("--fly-private", action="store_true",
                       help="Bind control only to Fly's private 6PN address; overrides --container")
    rc = commands.add_parser("rc")
    rc.add_argument("--state", type=Path, required=True)
    rc.add_argument("--port", type=int, default=43982)
    package = commands.add_parser("package")
    package.add_argument("--destination", type=Path, required=True)
    package.add_argument("--mcp-repo", type=Path, required=True)
    args = parser.parse_args()
    if args.command in {"rc", "serve"}:
        private_creation_policy()
    if args.command == "rc":
        serve_rc(args.state, args.port)
    elif args.command == "package":
        from .package import build_package
        build_package(args.destination.resolve(), args.mcp_repo.resolve())
    else:
        import uvicorn
        if not (args.mcp_dir / "dist/index.js").is_file():
            parser.error("Build the pinned MCP source first: npm ci && npm run build")
        app = create_control(args.state, args.mcp_dir.resolve(), args.provider_env,
                             backend=args.backend, ffmpeg=args.ffmpeg, hosted=args.fly_private)
        host = "fly-local-6pn" if args.fly_private else "0.0.0.0" if args.container else "127.0.0.1"
        server = uvicorn.Server(uvicorn.Config(app, host=host,
                                             port=43980, access_log=False))
        app.state.stop_server = lambda: setattr(server, "should_exit", True)
        server.run()


if __name__ == "__main__":
    main()
