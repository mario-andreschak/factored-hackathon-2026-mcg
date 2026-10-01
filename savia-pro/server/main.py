"""Savia Pro - entry point.  python3 -m server.main [--port N] [--reload]"""

from __future__ import annotations

import argparse

import uvicorn

from .config import HOST, PORT, SERVING_DB, WEB_DIST


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--reload", action="store_true")
    args = ap.parse_args()

    if not SERVING_DB.exists():
        raise SystemExit(f"no serving database at {SERVING_DB}\n"
                         f"build it first:  python3 tools/build_serving.py")

    print(f"\n  Savia Pro")
    print(f"    api      http://{args.host}:{args.port}/api/health")
    print(f"    openapi  http://{args.host}:{args.port}/api/docs")
    print(f"    client   {'bundled' if WEB_DIST.is_dir() else 'not built - run the Vite dev server'}")
    print(f"    serving  {SERVING_DB}\n")

    uvicorn.run("server.api:app", host=args.host, port=args.port,
                reload=args.reload, log_level="warning")


if __name__ == "__main__":
    main()
