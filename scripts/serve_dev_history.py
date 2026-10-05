#!/usr/bin/env python3
"""Serve only the static history page on loopback; never expose the repository."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class HistoryHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # A rebuild replaces files at the same URLs; refresh must see the new
        # index and source, rather than a cached prior replay.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=43821)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "web/dev-history"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(HistoryHandler, directory=str(root)))
    print(f"Development history: http://127.0.0.1:{args.port}/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
