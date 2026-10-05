"""Temporary, authenticated, checksum-pinned first-volume ingestion only."""
import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

token = os.environ["FLUJO_FLY_PASSWORD"]
expected_hash = os.environ["FLUJO_UPLOAD_SHA256"]
expected_size = int(os.environ["FLUJO_UPLOAD_BYTES"])
assert len(token) >= 24 and len(expected_hash) == 64 and 0 < expected_size < 512 * 1024 * 1024


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def reply(self, status, body):
        content = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(content)
        self.close_connection = True

    def do_GET(self):
        self.reply(404, {"status": "migration pending"})

    def do_PUT(self):
        if self.path != "/_migration" or not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
            return self.reply(401, {"status": "unauthorized"})
        if self.headers.get("Content-Length") != str(expected_size):
            return self.reply(400, {"status": "invalid size"})
        digest = hashlib.sha256()
        remaining = expected_size
        filename = "/data/migration.upload"
        with open(filename, "wb") as output:
            os.chmod(filename, 0o600)
            while remaining:
                data = self.rfile.read(min(1024 * 1024, remaining))
                if not data:
                    return self.reply(400, {"status": "incomplete"})
                output.write(data)
                digest.update(data)
                remaining -= len(data)
            output.flush()
            os.fsync(output.fileno())
        if not hmac.compare_digest(digest.hexdigest(), expected_hash):
            os.unlink(filename)
            return self.reply(400, {"status": "checksum mismatch"})
        os.replace(filename, "/data/migration.tar.gz")
        self.reply(200, {"status": "stored", "bytes": expected_size, "sha256": expected_hash})


HTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
