#!/usr/bin/env python3
"""Static server for Savia Lite.

Python standard library only: no pip install, no virtual environment, no
Node toolchain, no build step. It serves the files next to this script and
nothing else.

    python serve.py                  # http://127.0.0.1:43900
    python serve.py --port 8123
    python serve.py --host 0.0.0.0   # reachable from other hosts, opt-in

The portal makes no outbound requests, so this server only ever returns the
five files in this folder.
"""

from __future__ import annotations

import argparse
import contextlib
import socket
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_PORT = 43900

# Explicit types: some minimal base images ship an incomplete mime registry,
# and a module served as text/plain silently breaks the whole page.
TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}


class SaviaHandler(SimpleHTTPRequestHandler):
    server_version = "SaviaLite"
    sys_version = ""

    def guess_type(self, path):  # noqa: A003 - base class name
        suffix = Path(str(path)).suffix.lower()
        if suffix in TYPES:
            return TYPES[suffix]
        return super().guess_type(path)

    def end_headers(self):
        # Demo server: always hand back the file on disk, never a stale copy.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        # The page loads only its own files and issues no network calls.
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'none'; form-action 'none'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("savia-lite  %s\n" % (fmt % args))


def free_port(host: str, wanted: int, attempts: int = 12) -> int:
    for offset in range(attempts):
        candidate = wanted + offset
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, candidate))
            except OSError:
                continue
            return candidate
    raise SystemExit(
        f"No free TCP port between {wanted} and {wanted + attempts - 1} on {host}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Savia Lite demo portal.")
    parser.add_argument("--host", default="127.0.0.1", help="default 127.0.0.1 (loopback only)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"default {DEFAULT_PORT}")
    parser.add_argument("--no-port-search", action="store_true", help="fail instead of trying the next free port")
    args = parser.parse_args()

    missing = [name for name in ("index.html", "assets/app.js", "assets/data.js") if not (ROOT / name).exists()]
    if missing:
        raise SystemExit(f"Missing expected files: {', '.join(missing)}")

    port = args.port if args.no_port_search else free_port(args.host, args.port)
    handler = partial(SaviaHandler, directory=str(ROOT))
    shown = "127.0.0.1" if args.host in ("0.0.0.0", "::") else args.host

    with ThreadingHTTPServer((args.host, port), handler) as httpd:
        print("", flush=True)
        print("  Savia Lite is serving on:", flush=True)
        print(f"    http://{shown}:{port}/", flush=True)
        print("", flush=True)
        print("  Synthetic demo data generated in the browser.", flush=True)
        print("  No bank, no customer records, no outbound requests.", flush=True)
        print("  Stop with Ctrl+C.", flush=True)
        print("", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Stopped.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
