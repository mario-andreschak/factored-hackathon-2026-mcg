"""Pure fake transport/lifecycle checks, not network or banking acceptance.

Owner source is loaded in an isolated package with Service, Authorizer, MCP
server/transport and uvicorn replaced BEFORE import. No bank runtime, database,
dataset, listener, native process or provider is created. Metadata assertions
exercise callback wiring; the fake manager does not prove the MCP SDK parser.
IP restrictions do not prove server identity, TLS or OS/UID isolation.
"""
from __future__ import annotations

import importlib.util
import json
import stat
import sys
import types
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import anyio
import pytest


SOURCE = Path(__file__).resolve().parents[1] / "banking_mcp"
TOKEN = "fictional-service-token-" + "x" * 32
BIND, PORT, PEER = "10.34.0.2", 43421, "10.34.0.3"
VALID_REVOKE = b'{"assertion":"fictional-signed-revoke"}'


class Record(SimpleNamespace):
    pass


class FakeMeta:
    def __init__(self, value):
        self.value = value
        self.dump_options = []

    def model_dump(self, **options):
        self.dump_options.append(options)
        return self.value


class FakeService:
    def __init__(self, config=None):
        self.config = config or SimpleNamespace(mode="delegated", service_token=TOKEN,
            http_hosts=["127.0.0.1:*"], private_host_bind=BIND,
            private_host_port=PORT, private_host_clients=(PEER,),
            private_host_cert_file=(SOURCE / "fictional-cert.pem").resolve(),
            private_host_key_file=(SOURCE / "fictional-key.pem").resolve())
        self.calls, self.revocations, self.events = [], [], []
        self.auth = SimpleNamespace(revoke_assertion=self.revoke)
        self.store = object()
        self.closed = 0

    async def call(self, name, arguments, meta):
        self.calls.append((name, arguments, meta))
        return {"fictional": True, "operation": name}

    def revoke(self, token):
        if not isinstance(token, str) or token != "fictional-signed-revoke":
            raise ValueError("this private diagnostic must not be reflected")
        self.revocations.append(token)

    def close(self):
        self.closed += 1
        self.events.append("service-close")


@pytest.fixture
def subject(monkeypatch):
    """Execute transport source only after replacing every runtime boundary."""
    package_name = "_banking_private_host_source_subject"
    package = types.ModuleType(package_name)
    package.__path__ = []
    package.__version__ = "fictional-source-test"
    monkeypatch.setitem(sys.modules, package_name, package)
    servers, managers, stdio_runs = [], [], []

    def module(name, **values):
        result = types.ModuleType(name)
        result.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, result)
        return result

    class FakeBankError(Exception):
        pass

    class FakeServer:
        def __init__(self, *args, **kwargs):
            self.request_context = SimpleNamespace(meta=None)
            self.handlers = {}
            servers.append(self)

        def list_tools(self):
            def register(handler):
                self.handlers["list"] = handler
                return handler
            return register

        def call_tool(self, **options):
            assert options == {"validate_input": False}
            def register(handler):
                self.handlers["call"] = handler
                return handler
            return register

        def create_initialization_options(self):
            return "fictional-options"

        async def run(self, read, write, options):
            assert (read, write, options) == ("fake-read", "fake-write", "fictional-options")
            stdio_runs.append(self)

    @asynccontextmanager
    async def fake_stdio_server():
        yield "fake-read", "fake-write"

    class FakeManager:
        def __init__(self, server, **options):
            self.server, self.options = server, options
            self.requests, self.events = [], []
            managers.append(self)

        @asynccontextmanager
        async def run(self):
            self.events.append("manager-enter")
            try:
                yield
            finally:
                self.events.append("manager-drained")

        async def handle_request(self, scope, receive, send):
            # The actual owner endpoint must delegate here. No parsing, tool or
            # authority is synthesized by this fake HTTP manager.
            self.requests.append((scope, receive, send))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"fake_manager":true}'})

    schema = SimpleNamespace(model_json_schema=lambda: {"type": "object", "properties": {}})
    module(package_name + ".service", Service=FakeService, ACTION_SCHEMAS={},
        DESCRIPTIONS={"read_owned": "Fictional read"}, SCHEMAS={"read_owned": schema},
        safe_error=lambda _exc: {"error": "service_unavailable"})
    module(package_name + ".security", BankError=FakeBankError,
        Authorizer=lambda *_: pytest.fail("Authorizer construction forbidden"),
        StateStore=lambda *_: pytest.fail("StateStore construction forbidden"))
    module("mcp")
    module("mcp.types", Tool=Record, ToolAnnotations=Record, TextContent=Record, CallToolResult=Record)
    sys.modules["mcp"].types = sys.modules["mcp.types"]
    module("mcp.server")
    module("mcp.server.lowlevel", Server=FakeServer)
    module("mcp.server.stdio", stdio_server=fake_stdio_server)
    module("mcp.server.streamable_http_manager", StreamableHTTPSessionManager=FakeManager)
    module("mcp.server.transport_security", TransportSecuritySettings=Record)

    def load(name):
        spec = importlib.util.spec_from_file_location(package_name + "." + name, SOURCE / (name + ".py"))
        result = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, result)
        spec.loader.exec_module(result)
        return result

    config = load("config")
    server = load("server")
    private = load("private_host")
    main = load("__main__")
    return SimpleNamespace(config=config, server=server, private=private, main=main,
        servers=servers, managers=managers, stdio_runs=stdio_runs, error=FakeBankError)


async def exchange(app, *, headers=None, client=(PEER, 12345), path="/mcp", method="POST", body=b"{}", scheme="https"):
    raw = headers if headers is not None else [(b"host", f"{BIND}:{PORT}".encode()),
        (b"authorization", ("Bearer " + TOKEN).encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "scheme": scheme, "method": method, "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "", "headers": raw, "client": client,
        "server": (BIND, PORT)}
    messages = []
    chunks = list(body if isinstance(body, tuple) else (body,))
    position = 0
    async def receive():
        nonlocal position
        part = chunks[position]
        position += 1
        return {"type": "http.request", "body": part, "more_body": position < len(chunks)}
    async def send(message):
        messages.append(message)
    await app(scope, receive, send)
    start = next(message for message in messages if message["type"] == "http.response.start")
    content = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(content), start.get("headers", [])


def private_app(subject, service=None, **overrides):
    options = {"close_service": False, "private_host_bind": BIND,
        "private_host_port": PORT, "private_host_clients": (PEER,), **overrides}
    return subject.server.create_http_app(service or FakeService(), **options)


def test_disabled_default_selects_only_stdio(subject, monkeypatch, capsys):
    config = SimpleNamespace(private_host_port=None)
    selected, constructed = [], []
    monkeypatch.setattr(subject.main, "load_config", lambda _path: config)
    monkeypatch.setattr(subject.main, "Service", lambda value: constructed.append(FakeService(value)) or constructed[-1])
    monkeypatch.setattr(anyio, "run", lambda *args: selected.append(args))
    monkeypatch.setattr(subject.private, "private_http_server", lambda *_a, **_k: pytest.fail("HTTP runner forbidden"))
    monkeypatch.setattr(sys, "argv", ["banking_mcp", "serve", "--config", "fictional.json"])
    assert subject.main.main() == 0
    assert len(constructed) == 1
    assert selected == [(subject.server.run_stdio, constructed[0])]
    assert subject.managers == []
    assert capsys.readouterr().out == ""
    default = subject.config.Config(mode="operator-test", approved_customers={"fictional-customer"},
        data_dir=SOURCE.resolve(), state_db=(SOURCE / "unused-fictional.db").resolve(), service_token=TOKEN)
    assert (default.private_host_bind, default.private_host_port, default.private_host_clients) == (None, None, ())


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "172.16.3.4", "192.168.4.5"])
def test_explicit_private_ipv4_literal(subject, address):
    assert subject.config.private_ipv4(address) == address


@pytest.mark.parametrize("address", [None, "0.0.0.0", "8.8.8.8", "localhost", "10.1.2.3/24",
    "::1", "169.254.1.2", "127.0.0.2", "10.1.2.0", "10.1.2.255", "010.1.2.3"])
def test_noncanonical_public_or_wildcard_bind_rejected(subject, address):
    with pytest.raises(ValueError, match="explicit private IPv4"):
        subject.config.private_ipv4(address)


@pytest.mark.parametrize("options", [{"private_host_clients": ()}, {"private_host_clients": (PEER, PEER)},
    {"private_host_clients": ("8.8.8.8",)}, {"private_host_bind": "0.0.0.0"},
    {"private_host_port": None}, {"private_host_port": True}, {"private_host_port": 80}])
def test_private_app_requires_exact_bind_port_and_peer_allowlist(subject, options):
    with pytest.raises(ValueError):
        private_app(subject, **options)
    assert subject.managers == []


@pytest.mark.parametrize("client,extra,host,expected", [
    (("10.34.0.9", 1), [], None, 403),
    (None, [], None, 403),
    ((PEER, 1), [(b"origin", b"http://fictional-origin.invalid")], None, 403),
    ((PEER, 1), [], b"localhost:43421", 403),
    ((PEER, 1), [(b"host", f"{BIND}:{PORT}".encode())], None, 403),
    ((PEER, 1), [(b"forwarded", f"for={PEER}".encode())], None, 403),
    ((PEER, 1), [(b"x-forwarded-for", PEER.encode())], None, 403),
    ((PEER, 1), [(b"x-forwarded-host", f"{BIND}:{PORT}".encode())], None, 403),
    ((PEER, 1), [(b"x-forwarded-proto", b"https")], None, 403),
    (("10.34.0.9", 1), [(b"forwarded", f"for={PEER}".encode()),
        (b"x-forwarded-for", PEER.encode()), (b"x-forwarded-host", f"{BIND}:{PORT}".encode())], None, 403),
])
def test_origin_host_and_forwarded_identity_cannot_grant_access(subject, client, extra, host, expected):
    service = FakeService()
    app = private_app(subject, service)
    headers = [(b"host", host or f"{BIND}:{PORT}".encode()),
        (b"authorization", ("Bearer " + TOKEN).encode()), *extra]
    status, body, _ = anyio.run(lambda: exchange(app, headers=headers, client=client))
    assert (status, body) == (expected, {"error": "private_host_required"})
    assert subject.managers[-1].requests == [] and service.calls == [] and service.revocations == []


def test_plain_http_scope_cannot_reach_private_manager(subject):
    status, body, _ = anyio.run(lambda: exchange(private_app(subject), scheme="http"))
    assert (status, body) == (403, {"error": "private_host_required"})
    assert subject.managers[-1].requests == []


@pytest.mark.parametrize("auth", [[], [(b"authorization", b"Bearer wrong")],
    [(b"authorization", ("Bearer " + TOKEN).encode())] * 2])
def test_bearer_gate_precedes_manager_and_revoke(subject, auth):
    service = FakeService()
    app = private_app(subject, service)
    headers = [(b"host", f"{BIND}:{PORT}".encode()), *auth]
    for path in ("/mcp", "/internal/revoke"):
        status, body, _ = anyio.run(lambda: exchange(app, path=path, headers=headers,
            body=b'{"assertion":"fictional-signed-revoke"}'))
        assert (status, body) == (401, {"error": "service_authentication_required"})
    assert subject.managers[-1].requests == [] and service.revocations == []


def test_standard_manager_and_both_callbacks_share_one_fake_service(subject):
    service = FakeService()
    app = private_app(subject, service)
    manager = subject.managers[-1]
    assert manager.options["max_request_body_size"] == 65536
    assert manager.options["stateless"] is True and manager.options["json_response"] is True
    security = manager.options["security_settings"]
    assert security.allowed_hosts == [f"{BIND}:{PORT}"] and security.allowed_origins == []
    assert security.enable_dns_rebinding_protection is True
    status, body, _ = anyio.run(lambda: exchange(app))
    assert (status, body) == (200, {"fake_manager": True})
    assert len(manager.requests) == 1 and service.calls == []
    anyio.run(lambda: subject.server.run_stdio(service, close_service=False))
    assert len(subject.stdio_runs) == 1 and service.closed == 0
    for server in (manager.server, subject.stdio_runs[0]):
        payload = {"com.flujo.bank/assertion": "fictional-signed-per-call-assertion", "opaque": {"x": 1}}
        meta = FakeMeta(payload)
        server.request_context.meta = meta
        args = {"limit": 1}
        result = anyio.run(lambda: server.handlers["call"]("read_owned", args))
        assert service.calls[-1] == ("read_owned", args, payload)
        assert service.calls[-1][2] is payload
        assert meta.dump_options == [{"by_alias": True}]
        assert result.structuredContent == {"fictional": True, "operation": "read_owned"}
        assert result.isError is False
        assert "revoke" not in {tool.name for tool in anyio.run(server.handlers["list"])}


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"{}", b'{"assertion":"wrong"}',
    b'{"assertion":1}', b'{"assertion":"fictional-signed-revoke","extra":1}', VALID_REVOKE + b" " * 10001],
    ids=["malformed-json", "array", "missing-assertion", "wrong-assertion", "nonstring-assertion", "extra-field", "oversized-body"])
def test_invalid_or_oversized_revoke_never_dispatches(subject, body):
    service = FakeService()
    status, result, headers = anyio.run(lambda: exchange(private_app(subject, service),
        path="/internal/revoke", body=body))
    assert (status, result) == (403, {"error": "authorization_denied"})
    assert (b"cache-control", b"no-store") in headers
    assert subject.managers[-1].requests == [] and service.revocations == []
    assert TOKEN not in json.dumps(result) and "private diagnostic" not in json.dumps(result)


def test_valid_revoke_uses_shared_fake_authorizer_only(subject):
    service = FakeService()
    app = private_app(subject, service)
    status, result, headers = anyio.run(lambda: exchange(app, path="/internal/revoke",
        body=b'{"assertion":"fictional-signed-revoke"}'))
    assert (status, result) == (200, {"revoked": True})
    assert service.revocations == ["fictional-signed-revoke"]
    assert subject.managers[-1].requests == [] and service.calls == []
    assert (b"cache-control", b"no-store") in headers


@pytest.mark.parametrize("size,expected", [(10000, 200), (10001, 403)])
def test_revoke_limit_counts_all_chunks_before_authorization(subject, size, expected):
    service = FakeService()
    body = VALID_REVOKE + b" " * (size - len(VALID_REVOKE))
    status, result, _ = anyio.run(lambda: exchange(private_app(subject, service),
        path="/internal/revoke", body=(body[:5000], body[5000:])))
    assert status == expected
    assert result == ({"revoked": True} if expected == 200 else {"error": "authorization_denied"})
    assert service.revocations == (["fictional-signed-revoke"] if expected == 200 else [])
    assert subject.managers[-1].requests == []


@pytest.mark.parametrize("path,method", [("/unknown", "POST"), ("/mcp", "GET"),
    ("/internal/revoke", "DELETE"), ("/mcp", "PUT")])
def test_no_arbitrary_dispatch_path(subject, path, method):
    status, body, _ = anyio.run(lambda: exchange(private_app(subject), path=path, method=method))
    assert (status, body) == (405, {"error": "method_not_allowed"})
    assert subject.managers[-1].requests == []


@pytest.mark.parametrize("outcome", ["eof", "cancel", "stdio-error", "host-error"])
def test_one_close_after_both_fake_transports_drain(subject, outcome, capsys):
    service = FakeService()
    async def scenario():
        host_started, stdio_started, stop = anyio.Event(), anyio.Event(), anyio.Event()
        async def stdio():
            stdio_started.set()
            try:
                await host_started.wait()
                if outcome == "eof":
                    service.events.append("stdio-eof")
                    return
                if outcome == "stdio-error":
                    raise ValueError("fictional-stdio-error")
                await anyio.sleep_forever()
            finally:
                service.events.append("stdio-drained")
        async def host():
            host_started.set()
            try:
                if outcome == "host-error":
                    raise ValueError("fictional-host-error")
                await stop.wait()
            finally:
                service.events.append("host-drained")
        def stop_host():
            service.events.append("stop-host")
            stop.set()
        with anyio.fail_after(2):
            if outcome == "cancel":
                async with anyio.create_task_group() as group:
                    group.start_soon(lambda: subject.private.coordinate_transports(service,
                        stdio=stdio, host=host, stop_host=stop_host))
                    await host_started.wait()
                    await stdio_started.wait()
                    group.cancel_scope.cancel()
            else:
                await subject.private.coordinate_transports(service, stdio=stdio, host=host, stop_host=stop_host)
    if outcome.endswith("error"):
        with pytest.raises(ExceptionGroup):
            anyio.run(scenario)
    else:
        anyio.run(scenario)
    assert service.closed == 1
    assert service.events.count("stop-host") == 1
    assert service.events[-1] == "service-close"
    assert {"host-drained", "stdio-drained"}.issubset(service.events)
    assert capsys.readouterr().out == ""


def test_companion_failure_before_start_closes_once(subject, monkeypatch):
    service = FakeService()
    def fail(*_args, **_kwargs):
        raise ValueError("fictional-construction-failure")
    monkeypatch.setattr(subject.private, "create_http_app", fail)
    monkeypatch.setattr(subject.private, "private_tls_files", lambda _config: None)
    monkeypatch.setattr(subject.private, "private_http_server", lambda *_a, **_k: pytest.fail("runner must not be constructed"))
    with pytest.raises(subject.error, match="service_unavailable"):
        anyio.run(lambda: subject.private.run_stdio_with_private_http(service))
    assert service.closed == 1


@pytest.mark.parametrize("outcome", ["eof", "startup-exit", "not-started", "unexpected-error"])
def test_companion_runner_preserves_shared_close_ownership(subject, monkeypatch, outcome):
    service, server_options, app_options = FakeService(), [], []
    async def scenario():
        started, stopped = anyio.Event(), anyio.Event()
        class FakeRunner:
            started = False
            @property
            def should_exit(self):
                return stopped.is_set()
            @should_exit.setter
            def should_exit(self, value):
                assert value is True
                stopped.set()
            async def serve(self):
                if outcome == "startup-exit":
                    raise SystemExit(1)
                if outcome == "not-started":
                    return
                if outcome == "unexpected-error":
                    raise RuntimeError("fictional-unexpected-error")
                self.started = True
                started.set()
                await stopped.wait()
                service.events.append("runner-drained")
        runner = FakeRunner()
        def app(shared, **options):
            assert shared is service
            app_options.append(options)
            return "fictional-app"
        def make_runner(value, **options):
            assert value == "fictional-app"
            server_options.append(options)
            return runner
        async def stdio(shared, **options):
            assert shared is service and options == {"close_service": False}
            try:
                await started.wait()
            finally:
                service.events.append("stdio-drained")
        monkeypatch.setattr(subject.private, "create_http_app", app)
        monkeypatch.setattr(subject.private, "private_tls_files", lambda config: None)
        monkeypatch.setattr(subject.private, "private_http_server", make_runner)
        monkeypatch.setattr(subject.private, "run_stdio", stdio)
        with anyio.fail_after(2):
            await subject.private.run_stdio_with_private_http(service)
    if outcome == "eof":
        anyio.run(scenario)
        assert "runner-drained" in service.events
    elif outcome == "unexpected-error":
        with pytest.raises(ExceptionGroup) as caught:
            anyio.run(scenario)
        assert any(isinstance(error, RuntimeError) for error in caught.value.exceptions)
    else:
        with pytest.raises(subject.error, match="service_unavailable"):
            anyio.run(scenario)
    assert app_options == [{"close_service": False, "private_host_bind": BIND,
        "private_host_port": PORT, "private_host_clients": (PEER,)}]
    assert server_options == [{"bind": BIND, "port": PORT,
        "cert_file": service.config.private_host_cert_file, "key_file": service.config.private_host_key_file}]
    assert service.closed == 1 and service.events[-1] == "service-close"


def test_runner_has_no_proxy_workers_or_access_logs(subject, monkeypatch, capsys):
    configs = []
    class FakeRunner:
        def __init__(self, config):
            self.config = config
    def config(app, **options):
        configs.append((app, options))
        return options
    monkeypatch.setitem(sys.modules, "uvicorn", SimpleNamespace(Server=FakeRunner, Config=config))
    cert_file, key_file = (SOURCE / "fictional-cert.pem").resolve(), (SOURCE / "fictional-key.pem").resolve()
    runner = subject.private.private_http_server("fictional-app", bind=BIND, port=PORT,
        cert_file=cert_file, key_file=key_file)
    assert configs == [("fictional-app", {"host": BIND, "port": PORT, "workers": 1,
        "proxy_headers": False, "access_log": False, "log_config": None,
        "log_level": "critical", "timeout_graceful_shutdown": 15, "lifespan": "on",
        "ssl_certfile": str(cert_file), "ssl_keyfile": str(key_file)})]
    runner.handle_exit(15, None)
    runner.handle_exit(15, None)
    assert runner.should_exit is True
    assert capsys.readouterr().out == ""


def test_expected_startup_groups_normalize_without_swallowing_unexpected_or_cancel(subject):
    expected = ExceptionGroup("fictional-expected", [OSError("private-path"),
        ExceptionGroup("nested", [ValueError("private-value"), subject.error("private-code")])])
    assert subject.private.expected_startup_failure(expected) is True
    assert subject.private.expected_startup_failure(RuntimeError("unexpected")) is False
    assert subject.private.expected_startup_failure(ExceptionGroup("mixed", [expected, RuntimeError("unexpected")])) is False
    assert subject.private.expected_startup_failure(BaseExceptionGroup("cancel", [expected, KeyboardInterrupt()])) is False


def test_grouped_expected_startup_reaches_fixed_cli_error_after_lock(subject, monkeypatch, capsys):
    service, events = FakeService(), []
    @contextmanager
    def lock(config):
        assert config is service.config
        events.append("lock-before-service")
        try:
            yield
        finally:
            events.append("unlock")
    def construct(config):
        assert events == ["lock-before-service"] and config is service.config
        events.append("fake-service")
        return service
    async def fail(shared, **_options):
        assert shared is service
        shared.close()
        raise ExceptionGroup("fictional-private-startup", [subject.error("private-path-and-secret")])
    monkeypatch.setattr(subject.main, "load_config", lambda _path: service.config)
    monkeypatch.setattr(subject.main, "Service", construct)
    monkeypatch.setattr(subject.private, "private_instance_lock", lock)
    monkeypatch.setattr(subject.private, "private_tls_files", lambda _config: None)
    monkeypatch.setattr(subject.private, "create_http_app", lambda *_a, **_k: "fictional-app")
    monkeypatch.setattr(subject.private, "private_http_server", lambda *_a, **_k: SimpleNamespace(started=False))
    monkeypatch.setattr(subject.private, "coordinate_transports", fail)
    monkeypatch.setattr(sys, "argv", ["banking_mcp", "serve", "--config", "fictional-private-config.json"])
    assert subject.main.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == "Banking MCP could not start. Check the private configuration and published pipeline snapshot.\n"
    assert TOKEN not in output.err and "private-path-and-secret" not in output.err
    assert service.closed == 1 and events == ["lock-before-service", "fake-service", "unlock"]


@pytest.mark.parametrize("close_service", [False, True])
def test_http_manager_drains_before_its_optional_close(subject, close_service):
    service = FakeService()
    app = subject.server.create_http_app(service, close_service=close_service)
    manager = subject.managers[-1]
    async def scenario():
        async with app.router.lifespan_context(app):
            assert manager.events == ["manager-enter"] and service.closed == 0
        assert manager.events == ["manager-enter", "manager-drained"]
    anyio.run(scenario)
    assert service.closed == int(close_service)


@pytest.mark.parametrize("problem", [None, "directory-mode", "directory-owner", "lock-hardlink",
    "lock-mode", "busy", "key-mode", "key-symlink"])
def test_instance_and_tls_metadata_gates_use_only_fake_filesystem(subject, monkeypatch, problem):
    """Permission/lock wiring only; no real ownership, flock or key is touched."""
    opened, closed, locked = [], [], []
    class FakePath:
        def __init__(self, name):
            self.name = name
        def is_absolute(self):
            return self.name.startswith("/")
        @property
        def parts(self):
            return tuple(self.name.split("/"))
        def is_symlink(self):
            return problem == "key-symlink" and self.name.endswith("key.pem")
        @property
        def parent(self):
            return FakePath(self.name.rsplit("/", 1)[0] or "/")
        @property
        def parents(self):
            return (self.parent,) if self.name != "/" else ()
        def __truediv__(self, name):
            return FakePath(self.name + "/" + name)
        def stat(self):
            file = self.name.endswith(".pem")
            mode = stat.S_IFREG | (0o644 if problem == "key-mode" and self.name.endswith("key.pem") else 0o400)
            if not file:
                mode = stat.S_IFDIR | (0o755 if problem == "directory-mode" else 0o700)
            return SimpleNamespace(st_mode=mode, st_uid=999 if problem == "directory-owner" and not file else 2000, st_nlink=1)
    def open_fake(path, flags, mode):
        opened.append((path.name, flags, mode))
        return 9
    def flock_fake(descriptor, flags):
        locked.append((descriptor, flags))
        if problem == "busy":
            raise BlockingIOError("fictional-busy")
    fake_os = SimpleNamespace(name="posix", geteuid=lambda: 2000, open=open_fake, close=closed.append,
        O_RDWR=1, O_CREAT=2, O_NOFOLLOW=4, O_CLOEXEC=8,
        fstat=lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG | (0o644 if problem == "lock-mode" else 0o600),
            st_uid=2000, st_nlink=2 if problem == "lock-hardlink" else 1))
    monkeypatch.setattr(subject.private, "os", fake_os)
    monkeypatch.setattr(subject.private, "Path", FakePath)
    monkeypatch.setitem(sys.modules, "fcntl", SimpleNamespace(LOCK_EX=16, LOCK_NB=32, flock=flock_fake))
    config = SimpleNamespace(private_host_port=PORT, state_db=FakePath("/fictional-state/state.db"),
        private_host_cert_file=FakePath("/fictional-secrets/cert.pem"),
        private_host_key_file=FakePath("/fictional-secrets/key.pem"))
    entered = []
    def scenario():
        with subject.private.private_instance_lock(config):
            entered.append("authorized-lock")
            assert closed == []
    if problem == "busy":
        with pytest.raises(subject.error, match="server_busy"):
            scenario()
    elif problem is not None:
        with pytest.raises(ValueError):
            scenario()
    else:
        scenario()
        assert entered == ["authorized-lock"] and locked == [(9, 48)]
    if problem in {"directory-mode", "directory-owner"}:
        assert opened == [] and closed == []
    else:
        assert opened == [("/fictional-state/.private-host.lock", 15, 0o600)] and closed == [9]
    if problem is not None:
        assert entered == []
