"""Explicit CPU-only Connect Token HTTP/WSS probe; --plan never accesses Modal."""
from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import secrets
import socket
import ssl
import threading
import urllib.parse
import urllib.request

LIFETIME = 30
PORT = 8080
SENTINEL = b'public-connect-probe'
HEALTH = {'ready': True, 'probe': 'modal-connect-v1'}
WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
ROOT = Path(__file__).resolve().parent.parent


def plan(policy='blocked') -> dict:
    return {'status': 'prepared_not_dispatched', 'gpu': False, 'sandbox_lifetime_seconds': LIFETIME,
            'cpu_maximum': .5, 'memory_maximum_mib': 512, 'port': PORT,
            'egressPolicy': policy, 'outbound_network_blocked': policy == 'blocked',
            'outbound_cidr_allowlist': ['127.0.0.0/8'] if policy == 'loopback-only' else [], 'raw_public_ports': False,
            'health': True, 'websocket_echo': True, 'model_download': False,
            'secret_required': False, 'persistent_service': False, 'automatic_retry': False,
            'maximum_sandbox_runtime_estimate_usd': round(LIFETIME * (.5 * .00003942 + .5 * .00000667), 6),
            'cost_note': 'Small private source image build is separate. Thirty seconds bounds the Sandbox, not image preparation.'}


def receive_exact(stream, count: int) -> bytes:
    result = b''
    while len(result) < count:
        part = stream.read(count - len(result))
        if not part: raise ConnectionError('The fixed probe connection ended.')
        result += part
    return result


def receive_frame(stream, *, masked: bool) -> tuple[int, bytes]:
    first, second = receive_exact(stream, 2)
    if first & 0x70 or not first & 0x80 or bool(second & 0x80) != masked:
        raise ValueError('The fixed probe received an invalid frame.')
    length = second & 0x7f
    if length == 126: length = int.from_bytes(receive_exact(stream, 2), 'big')
    if length == 127 or length > 512: raise ValueError('The probe frame is oversized.')
    key = receive_exact(stream, 4) if masked else None
    payload = receive_exact(stream, length)
    if key: payload = bytes(char ^ key[index % 4] for index, char in enumerate(payload))
    return first & 0x0f, payload


def send_frame(sock, opcode: int, payload: bytes, *, masked: bool) -> None:
    if len(payload) > 125: raise ValueError('The fixed outgoing frame is oversized.')
    key = secrets.token_bytes(4) if masked else b''
    data = bytes(char ^ key[index % 4] for index, char in enumerate(payload)) if masked else payload
    sock.sendall(bytes((0x80 | opcode, len(payload) | (0x80 if masked else 0))) + key + data)


def handler_for(epoch: str):
    class ProbeHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_args):
            pass

        def reply(self, status: int, body: bytes = b''):
            self.send_response(status); self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', 'application/json'); self.send_header('Connection', 'close')
            self.end_headers(); self.wfile.write(body); self.close_connection = True

        def do_GET(self):
            values = self.headers.get_all('X-Verified-User-Data', [])
            try:
                metadata = json.loads(values[0]) if len(values) == 1 and len(values[0]) <= 512 else None
                authorized = isinstance(metadata, dict) and set(metadata) == {'leaseEpoch'} and \
                    isinstance(metadata['leaseEpoch'], str) and hmac.compare_digest(metadata['leaseEpoch'], epoch)
            except (ValueError, TypeError): authorized = False
            if not authorized: self.reply(403); return
            if self.path == '/healthz':
                self.reply(200, json.dumps(HEALTH).encode()); return
            if self.path != '/api/chat': self.reply(404); return
            key = self.headers.get('Sec-WebSocket-Key', '')
            try: valid_key = len(base64.b64decode(key, validate=True)) == 16
            except ValueError: valid_key = False
            if self.headers.get('Upgrade', '').lower() != 'websocket' or \
                    'upgrade' not in self.headers.get('Connection', '').lower().split(', ') or \
                    self.headers.get('Sec-WebSocket-Version') != '13' or not valid_key:
                self.reply(400); return
            with self.server.admission_lock:
                if self.server.admitted: self.reply(409); return
                self.server.admitted = True
            self.connection.settimeout(3)
            self.send_response(101); self.send_header('Upgrade', 'websocket'); self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode())
            self.end_headers(); self.wfile.flush()
            try:
                opcode, payload = receive_frame(self.rfile, masked=True)
                if opcode != 1 or payload != SENTINEL: raise ValueError('The probe message is invalid.')
                send_frame(self.connection, 1, SENTINEL, masked=False)
                send_frame(self.connection, 8, b'\x03\xe8', masked=False)
            except (OSError, ValueError, ConnectionError): pass
            finally: self.close_connection = True
    return ProbeHandler


def make_server(epoch: str, *, host='0.0.0.0', port=PORT):
    server = http.server.ThreadingHTTPServer((host, port), handler_for(epoch))
    server.daemon_threads = True
    server.admission_lock = threading.Lock(); server.admitted = False
    return server


def worker() -> int:
    epoch = os.environ.get('MODAL_PROBE_EPOCH', '')
    if len(epoch) != 43: return 2
    server = make_server(epoch)
    Path('/tmp/transport-ready').touch()
    deadline = threading.Timer(LIFETIME - 1, server.shutdown); deadline.daemon = True; deadline.start()
    try: server.serve_forever(poll_interval=.1)
    finally: server.server_close(); deadline.cancel()
    return 0


def origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value); host = parsed.hostname or ''
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment or \
            parsed.path not in ('', '/') or not (host.endswith('.modal.run') or host.endswith('.modal.host')):
        raise ValueError('The connect origin is invalid.')
    return 'https://' + host


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args): return None


def probe_http(base_url: str, token: str) -> bool:
    request = urllib.request.Request(base_url + '/healthz', headers={'Authorization': 'Bearer ' + token})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=3) as response:
        body = response.read(4097)
        return response.status == 200 and len(body) <= 4096 and json.loads(body) == HEALTH


def tls_connection(host: str):
    connection = socket.create_connection((host, 443), timeout=3)
    try: return ssl.create_default_context().wrap_socket(connection, server_hostname=host)
    except BaseException: connection.close(); raise


def probe_ws(base_url: str, token: str, *, connection_factory=tls_connection) -> bool:
    host = urllib.parse.urlsplit(origin(base_url)).hostname
    key = base64.b64encode(secrets.token_bytes(16)).decode()
    expected = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
    with connection_factory(host) as connection:
        connection.settimeout(3)
        # The credential stays in a TLS request header, never argv, query or output.
        request = f'GET /api/chat HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nAuthorization: Bearer {token}\r\n\r\n'
        connection.sendall(request.encode('ascii'))
        with connection.makefile('rb') as stream:
            status = stream.readline(4097)
            if len(status) > 4096 or status.split(b' ')[1:2] != [b'101']: return False
            headers = {}; size = len(status)
            for _ in range(32):
                line = stream.readline(4097); size += len(line)
                if size > 4096 or not line: raise ValueError('The handshake is oversized.')
                if line == b'\r\n': break
                name, value = line.decode('ascii').strip().split(':', 1)
                name = name.lower()
                if name in headers: raise ValueError('The handshake contains duplicate headers.')
                headers[name] = value.strip()
            else: raise ValueError('The handshake is oversized.')
            if headers.get('sec-websocket-accept') != expected or headers.get('upgrade', '').lower() != 'websocket' or \
                    headers.get('sec-websocket-extensions') or headers.get('sec-websocket-protocol'):
                return False
            send_frame(connection, 1, SENTINEL, masked=True)
            for _ in range(3):
                opcode, payload = receive_frame(stream, masked=False)
                if opcode == 9: send_frame(connection, 10, payload, masked=True); continue
                return opcode == 1 and payload == SENTINEL
            return False


async def run_probe(sdk, app, image, *, policy='blocked', http_check=probe_http, ws_check=probe_ws) -> dict:
    # Import the local diagnostic only in the operator client, never in worker/image.
    from modal_diagnostic import diagnostic
    if policy not in {'blocked', 'loopback-only'}: raise ValueError('The egress policy is invalid.')
    network = {'block_network': True} if policy == 'blocked' else {'outbound_cidr_allowlist': ['127.0.0.0/8']}
    sandbox = None; stage = 'sandbox_create'; failure = None; terminated = False; cleanup_failure = None
    epoch = secrets.token_urlsafe(32)
    report = {'gpu': False, 'sandboxLifetimeSeconds': LIFETIME, 'httpVerified': False,
              'websocketVerified': False, 'persistentService': False, 'automaticRetry': False, 'egressPolicy': policy}
    try:
        sandbox = await asyncio.wait_for(sdk.Sandbox.create.aio(
            'python', '/root/modal_transport_probe.py', '--worker', app=app, image=image,
            cpu=(.125, .5), memory=(128, 512), timeout=LIFETIME, **network,
            env={'MODAL_PROBE_EPOCH': epoch}, encrypted_ports=[], unencrypted_ports=[],
            readiness_probe=sdk.Probe.with_exec('test', '-f', '/tmp/transport-ready', interval_ms=250),
        ), timeout=15)
        # Backend identity is a diagnostic boolean, not a setting mutation.
        if isinstance(getattr(sandbox, '_is_v2', None), bool): report['backendV2'] = sandbox._is_v2
        stage = 'readiness'
        await asyncio.wait_for(sandbox.wait_until_ready.aio(timeout=10), timeout=11)
        stage = 'connect_token'
        credentials = await asyncio.wait_for(sandbox.create_connect_token.aio(
            user_metadata={'leaseEpoch': epoch}, port=PORT), timeout=5)
        base_url = origin(credentials.url); token = credentials.token
        if not isinstance(token, str) or not 16 <= len(token) <= 8192 or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError('The connect token is invalid.')
        stage = 'authenticated_http'
        report['httpVerified'] = await asyncio.to_thread(http_check, base_url, token)
        if not report['httpVerified']: raise RuntimeError('The authenticated health check failed.')
        stage = 'authenticated_websocket'
        report['websocketVerified'] = await asyncio.to_thread(ws_check, base_url, token)
        if not report['websocketVerified']: raise RuntimeError('The authenticated echo failed.')
        stage = 'complete'
    except BaseException as error:
        failure = diagnostic(error, stage)
    finally:
        if sandbox is not None:
            try: await asyncio.wait_for(sandbox.terminate.aio(wait=True), timeout=5); terminated = True
            except Exception as error: cleanup_failure = diagnostic(error, 'sandbox_termination')
    return {**report, 'status': 'completed' if failure is None else 'failed', 'stage': stage,
            **(failure or {}), **({'cleanupFailure': cleanup_failure} if cleanup_failure else {}),
            'workerCreated': sandbox is not None, 'terminationConfirmed': terminated}


async def run_attached(sdk, app, image, policy='blocked'):
    async with app.run.aio(detach=False):
        return await run_probe(sdk, app, image, policy=policy)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--plan', action='store_true')
    mode.add_argument('--execute', action='store_true', help='Create exactly one CPU Sandbox, never a GPU.')
    mode.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--egress-policy', choices=('blocked', 'loopback-only'), default='blocked')
    options = parser.parse_args(argv)
    if options.worker: return worker()
    if not options.execute: print(json.dumps(plan(options.egress_policy), indent=2)); return 0
    from modal_diagnostic import diagnostic
    stage = 'source_image_definition'
    try:
        import modal
        image = modal.Image.debian_slim(python_version='3.11').add_local_file(
            Path(__file__).resolve(), '/root/modal_transport_probe.py', copy=True)
        app = modal.App('elsewhere-cpu-connect-probe')
        stage = 'app_start'
        result = asyncio.run(run_attached(modal, app, image, options.egress_policy))
        destination = ROOT / '.local' / 'modal-transport-probe'; destination.mkdir(parents=True, exist_ok=True)
        (destination / 'last-run.json').write_text(json.dumps(result, indent=2), encoding='utf8')
        print(json.dumps(result)); return 0 if result['status'] == 'completed' else 1
    except Exception as error:
        print(json.dumps({'status': 'failed', **diagnostic(error, stage), 'gpu': False, 'persistentService': False})); return 1


if __name__ == '__main__': raise SystemExit(main())
