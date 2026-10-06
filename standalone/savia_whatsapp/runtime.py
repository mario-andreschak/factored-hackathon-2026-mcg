"""A local supervisor: new RC fixture, separate MCP session, loopback control UI."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import importlib.util
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import stat
import subprocess
import sys

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from . import MCP_REVISION, RC_REVISION
from .bridge import Bridge, Journal

ROOT = Path(__file__).resolve().parents[2]
CONTROL_PORT, MCP_PORT, SAVIA_PORT = 43980, 43981, 43982

_SOURCE_TREES = ("banking_mcp", "dispute_workflow", "savia_assistant", "pipeline", "resources", "config",
                 "frontend/server", "frontend/src", "frontend/public", "deploy/rc", "contracts", "standalone",
                 "whatsapp-mcp/src", "whatsapp-mcp/public")
_GENERATED_DIRS = {"__pycache__", "node_modules", "dist", ".pytest_cache", ".git"}
_REQUIRED_FEATURE = {"standalone/__init__.py", *(
    "standalone/savia_whatsapp/" + name for name in
    ("__init__.py", "__main__.py", "runtime.py", "bridge.py", "savia.py", "whatsapp.py", "control.html",
     "operator_auth.py"))}
_REQUIRED_MCP = {"whatsapp-mcp/" + name for name in
                 ("package.json", "package-lock.json", "tsconfig.json", "LICENSE", "src/index.ts")}


class BundleAdmissionError(ValueError):
    """The supplied public source is not an admitted standalone bundle."""


def _admission_error(reason):
    raise BundleAdmissionError(reason + "; export a fresh standalone package and launch inside its bundle directory.")


def _regular_file(root: Path, name: str) -> Path:
    """Validate portable manifest paths without resolving away a symlink."""
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\0" in name:
        _admission_error("Unsafe package source path")
    relative = PurePosixPath(name)
    if not relative.parts or relative.is_absolute() or relative.as_posix() != name \
            or any(part in {".", ".."} for part in relative.parts):
        _admission_error("Unsafe package source path")
    path = root
    try:
        for part in relative.parts:
            path /= part
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or (hasattr(path, "is_junction") and path.is_junction()):
                _admission_error("Linked package source is not allowed")
        if not stat.S_ISREG(mode):
            _admission_error("Package source must be a regular file")
    except OSError:
        _admission_error("Required package source is missing or unreadable")
    return path


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _admission_error("Duplicate manifest fields are not allowed")
        result[key] = value
    return result


def _read_manifest(name):
    path = _regular_file(ROOT, name)
    try:
        if path.stat().st_size > 4 * 1024 * 1024:
            _admission_error("Package manifest is too large")
        payload = path.read_bytes()
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        _admission_error("Package manifest is unreadable or invalid")
    if not isinstance(value, dict):
        _admission_error("Package manifest must be an object")
    return value, payload


def _hash_map(manifest):
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > 20000 or any(
            not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
            for name, digest in files.items()):
        _admission_error("Package manifest requires valid source hashes")
    return files


def _source_coverage(files, *, root=None, trees=None):
    # Dependency/build output is generated after export. All public source in the
    # imported RC, feature and MCP trees must belong to the admitted manifest.
    root = root if root is not None else ROOT
    for name in trees if trees is not None else _SOURCE_TREES:
        directory = root / name
        if not directory.exists():
            continue
        if directory.is_symlink() or (hasattr(directory, "is_junction") and directory.is_junction()):
            _admission_error("Linked package source is not allowed")
        for current, directories, filenames in os.walk(directory, followlinks=False):
            directories[:] = [item for item in directories if item not in _GENERATED_DIRS]
            for item in directories:
                child = Path(current) / item
                if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                    _admission_error("Linked package source is not allowed")
            for item in filenames:
                if item.endswith((".pyc", ".pyo")):
                    continue
                relative = (Path(current) / item).relative_to(root).as_posix()
                if relative not in files:
                    _admission_error("Public source is absent from the package manifest")


def verified_bundle(mcp_dir: Path | None = None) -> dict[str, str]:
    """Admit a pinned exported bundle, including an optional installed MCP copy.

    This checks manifest consistency and public source integrity without Git.
    Generated MCP dist/dependency assets belong to the separately qualified image
    build; their source inputs, including the recorded overlay, are checked here.
    """
    package, payload = _read_manifest("standalone-package.json")
    source, _ = _read_manifest("source-manifest.json")
    if package.get("schema") != "savia-whatsapp-local-package/v1" \
            or package.get("rc_revision") != RC_REVISION or package.get("whatsapp_mcp_revision") != MCP_REVISION \
            or source.get("schema") != "savia-public-rc-source/v1" or source.get("git_head") != RC_REVISION:
        _admission_error("Standalone source pins or manifest schemas do not match the qualified RC")
    feature = package.get("feature_revision")
    if not isinstance(feature, str) or not re.fullmatch(r"[0-9a-f]{40}", feature):
        _admission_error("A committed feature revision is required")
    if any(package.get(name) is not False for name in ("real_bank_actions", "state_included", "secrets_included")) \
            or source.get("fiction_only") is not True or source.get("flujo_built") is not False:
        _admission_error("Standalone package boundary declarations do not match")
    files, rc_files = _hash_map(package), _hash_map(source)
    rc_names = {name for name in files if not name.startswith(("standalone/", "whatsapp-mcp/"))
                and name not in {"source-manifest.json", ".dockerignore"}}
    if not (_REQUIRED_FEATURE | _REQUIRED_MCP | {"deploy/rc/run.py", "source-manifest.json"}) <= files.keys() \
            or "deploy/rc/run.py" not in rc_files or rc_names != rc_files.keys() \
            or any(files.get(name) != digest for name, digest in rc_files.items()):
        _admission_error("RC and standalone source coverage disagree")
    for name, digest in files.items():
        path = _regular_file(ROOT, name)
        try:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            _admission_error("Package source is unreadable")
        if actual != digest:
            _admission_error("Package source hash mismatch")
    _source_coverage(files)
    if mcp_dir is not None:
        mcp_dir = Path(mcp_dir)
        if mcp_dir.is_symlink() or (hasattr(mcp_dir, "is_junction") and mcp_dir.is_junction()):
            _admission_error("Linked installed MCP source is not allowed")
        for name, digest in files.items():
            if not name.startswith("whatsapp-mcp/"):
                continue
            installed = _regular_file(mcp_dir, name.removeprefix("whatsapp-mcp/"))
            try:
                actual = hashlib.sha256(installed.read_bytes()).hexdigest()
            except OSError:
                _admission_error("Installed MCP source is unreadable")
            if actual != digest:
                _admission_error("Installed MCP source differs from the admitted bundle")
        _source_coverage({name.removeprefix("whatsapp-mcp/"): digest for name, digest in files.items()
                          if name.startswith("whatsapp-mcp/")}, root=mcp_dir, trees=("src", "public"))
    return {"rc_revision": RC_REVISION, "whatsapp_mcp_revision": MCP_REVISION,
            "feature_revision": feature, "package_manifest_sha256": hashlib.sha256(payload).hexdigest()}


def ensure_ports_available():
    for port in (MCP_PORT, SAVIA_PORT):
        with socket.socket() as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(("127.0.0.1", port))


def private_creation_policy():
    # The unchanged RC requires private Unix ownership/permissions for bank pin state.
    # Apply before the fresh fixture and child processes create files.
    if os.name == "posix":
        os.umask(0o077)


def provider_key(filename: Path | None):
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key and filename and filename.is_file():
        for line in filename.read_text(encoding="utf-8-sig").splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('\"').strip("'")
    return key


def rc_module():
    verified_bundle()
    spec = importlib.util.spec_from_file_location("isolated_rc", ROOT / "deploy/rc/run.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.source_revision() != RC_REVISION:
        _admission_error("Loaded RC source revision disagrees with its admitted manifest")
    return module


class ReadOnlyBankBackend:
    """Keep session revocation and query reads, without bank action authority."""

    def __init__(self, backend):
        self._backend = backend

    async def post(self, path, headers, payload, chat):
        from frontend.server.chat import ChatError
        if path != "/v1/banking/session/revoke":
            raise ChatError("action_unavailable", 403, "La recepción simulada no está habilitada.")
        return await self._backend.post(path, headers, payload, chat)

    def cancel(self, *args, **kwargs):
        # Stock RC cancellation writes the bank before deleting frontend state.
        # Declining here preserves both stores, including retained pending work.
        return False

    def query_scope(self, *args, **kwargs):
        return self._backend.query_scope(*args, **kwargs)


def enforce_readonly_bank_authority(app):
    from frontend.server.dispute_chat import DisputeChatService
    service = app.state.chat_service
    if not isinstance(service, DisputeChatService) or service._bank_backend is None:
        raise RuntimeError("Standalone RC requires its admitted in-process bank backend")
    service._action_enabled = False
    if not isinstance(service._bank_backend, ReadOnlyBankBackend):
        service._bank_backend = ReadOnlyBankBackend(service._bank_backend)


def install_readonly_bank_authority(app):
    original = app.router.lifespan_context

    @asynccontextmanager
    async def readonly_lifespan(application):
        async with original(application):
            # RC constructs chat during startup. Apply before accepting requests
            # or yielding control to its newly scheduled background tasks.
            enforce_readonly_bank_authority(application)
            yield

    app.router.lifespan_context = readonly_lifespan


def serve_rc(state: Path, port: int):
    """Run only this experiment's RC, with native voice and no inherited fleet config."""
    import uvicorn
    private_creation_policy()
    module = rc_module()
    app, bank = module.application(state.resolve(), port=port, base_url="http://127.0.0.1:1",
                                  model_id="google/gemini-3.1-flash-lite", provider="openrouter",
                                  provider_key=os.environ["OPENROUTER_API_KEY"],
                                  voice_config=module.native_voice_config(), inquiry_config={})
    install_readonly_bank_authority(app)
    # Actions are out of scope; block the routes as well as keeping them absent from the adapter.
    @app.middleware("http")
    async def deny_actions(request, call_next):
        if request.url.path.startswith("/api/action/") or request.url.path.startswith("/api/followups"):
            return Response(status_code=403)
        return await call_next(request)
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, access_log=False)
    finally:
        bank.close()


class Configure(BaseModel):
    phone: str
    language: str = "es"
    profile: str = "mexico"


def create_control(state: Path, mcp_dir: Path, provider_file: Path | None,
                   *, backend="baileys", ffmpeg="ffmpeg", hosted=False):
    admitted = verified_bundle(mcp_dir)
    from .operator_auth import OperatorAuth
    operator = OperatorAuth(hosted)
    private_creation_policy()
    state = state.resolve()
    state.mkdir(parents=True, exist_ok=True)
    config_file = state / "local-config.json"
    key = provider_key(provider_file)
    children, handles = [], []
    holder = {"task": None, "bridge": None, "whatsapp": None, "savia": None}
    configured, connected, release_connection = asyncio.Event(), asyncio.Event(), asyncio.Event()
    if config_file.is_file():
        configured.set()
    journal = None

    async def own_connection():
        from .whatsapp import WhatsAppConfig, WhatsAppMcpAdapter
        await configured.wait()
        value = json.loads(config_file.read_text())
        jid = value["phone"] + "@c.us"
        for attempt in range(15):
            adapter = WhatsAppMcpAdapter(WhatsAppConfig(chat_jid=jid, self_jid=jid,
                                                     url=f"http://127.0.0.1:{MCP_PORT}/mcp"))
            try:
                async with adapter:
                    holder["whatsapp"] = adapter
                    connected.set()
                    await release_connection.wait()
                    return
            except asyncio.CancelledError:
                raise
            except Exception:
                holder["whatsapp"] = None
                connected.clear()
                await asyncio.sleep(2)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal journal
        connection_task = None
        ensure_ports_available()
        lock_path = state / "active.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(lock_fd, str(os.getpid()).encode())
        os.close(lock_fd)
        # Explicit paths protect the user's other accounts and experiments.
        mcp_runtime = state / "mcp-runtime"
        clean_env = {name: value for name, value in os.environ.items()
                     if name != "OPENROUTER_API_KEY"
                     and not name.startswith(("WHATSAPP_", "BAILEYS_", "MCP_", "BANKING_", "SAVIA_", "RC_"))}
        clean_env.update(WHATSAPP_BACKEND=backend, WHATSAPP_HEADLESS="true",
                         WHATSAPP_SESSION_DIR=str(state / "whatsapp-session"),
                         BAILEYS_SESSION_DIR=str(state / "baileys-session"),
                         MCP_HTTP_HOST="127.0.0.1", MCP_HTTP_PORT=str(MCP_PORT), MCP_OAUTH="false",
                         FFMPEG_PATH=ffmpeg, LOG_LEVEL="warn", LOG_STDERR_LEVEL="warn")
        try:
            journal = Journal(state / "delivery.sqlite3")
            mcp_runtime.mkdir(exist_ok=True)
            mcp_log = (state / "mcp.stderr.log").open("ab")
            handles.append(mcp_log)
            children.append(subprocess.Popen([shutil.which("node") or "node", "--no-deprecation",
                                               str(mcp_dir / "dist/index.js"), "--http"],
                                              cwd=mcp_runtime, env=clean_env, stdout=mcp_log, stderr=mcp_log))
            if key:
                rc_state = state / "rc"
                if not (rc_state / "fixture.json").is_file():
                    await asyncio.to_thread(rc_module().prepare, rc_state)
                rc_env = dict(clean_env, OPENROUTER_API_KEY=key)
                rc_log = (state / "rc.stderr.log").open("ab")
                handles.append(rc_log)
                children.append(subprocess.Popen([sys.executable, "-m", "standalone.savia_whatsapp", "rc",
                                                  "--state", str(rc_state), "--port", str(SAVIA_PORT)],
                                                 cwd=ROOT, env=rc_env, stdout=rc_log, stderr=rc_log))
            connection_task = asyncio.create_task(own_connection())
            yield
        finally:
            task = holder["task"]
            if holder["bridge"]:
                holder["bridge"].stop()
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if holder["savia"]:
                await holder["savia"].close()
            # The MCP SDK must close in the task that entered its AnyIO contexts,
            # after all request/bridge users have stopped.
            if connection_task:
                release_connection.set()
                if not connected.is_set():
                    connection_task.cancel()
                try:
                    await connection_task
                except asyncio.CancelledError:
                    pass
            for process in reversed(children):
                if process.poll() is None:
                    process.terminate()
                    try:
                        await asyncio.to_thread(process.wait, 12)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        await asyncio.to_thread(process.wait)
            for handle in handles:
                handle.close()
            if journal:
                journal.close()
            lock_path.unlink(missing_ok=True)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Host/Origin validation prevents browser DNS rebinding and cross-site account control.
        permitted_hosts = {f"127.0.0.1:{CONTROL_PORT}", f"localhost:{CONTROL_PORT}"}
        if request.headers.get("host") not in permitted_hosts:
            return Response(status_code=403)
        if request.method not in {"GET", "HEAD"}:
            if request.headers.get("origin") not in {f"http://{host}" for host in permitted_hosts}:
                return Response(status_code=403)
        return await call_next(request)

    operator.install(app)

    async def connection():
        if not config_file.is_file():
            raise HTTPException(409, "Enter your own WhatsApp number first")
        try:
            await asyncio.wait_for(connected.wait(), 8)
        except asyncio.TimeoutError:
            raise HTTPException(503, "Local WhatsApp MCP is still starting") from None
        if not children or children[0].poll() is not None:
            raise HTTPException(503, "This environment's WhatsApp process has stopped")
        return holder["whatsapp"]

    @app.get("/")
    async def index():
        return FileResponse(Path(__file__).with_name("control.html"))

    @app.post("/configure")
    async def configure(body: Configure):
        if configured.is_set():
            raise HTTPException(409, "Restart the local environment before changing its number")
        phone = body.phone.strip().removeprefix("+")
        if not re.fullmatch(r"[1-9][0-9]{7,14}", phone):
            raise HTTPException(422, "Enter 8–15 digits including country code")
        if body.language not in {"es", "pt"} or body.profile not in {"mexico", "colombia", "argentina"}:
            raise HTTPException(422, "Choose an available language and fictional profile")
        config_file.write_text(json.dumps(dict(phone=phone, language=body.language, profile=body.profile)))
        config_file.chmod(0o600)
        configured.set()
        return {"configured": True}

    @app.get("/status")
    async def status():
        value = {"configured": config_file.is_file(), "provider_configured": bool(key),
                 "rc_source": RC_REVISION, "mcp_source": MCP_REVISION,
                 "loaded_feature_revision": admitted["feature_revision"],
                 "package_manifest_sha256": admitted["package_manifest_sha256"],
                 "operator_authentication": operator.enabled,
                 "mcp_overlay": "Baileys browser descriptor: Desktop to Chrome",
                 "children_running": all(process.poll() is None for process in children),
                 "running": bool(holder["bridge"] and holder["bridge"].running),
                 "state": holder["bridge"].last_state if holder["bridge"] else "idle",
                 "processed": holder["bridge"].processed if holder["bridge"] else 0,
                 "uncertain_delivery": journal.blocked()}
        try:
            backend_status = await (await connection()).status()
            value["authenticated"] = backend_status.authenticated
        except Exception:
            value["authenticated"] = False
        return value

    @app.get("/qr")
    async def qr():
        try:
            if not config_file.is_file():
                from mcp import ClientSession
                from mcp.client.streamable_http import streamablehttp_client
                if not children or children[0].poll() is not None:
                    return Response(status_code=204)
                async with streamablehttp_client(f"http://127.0.0.1:{MCP_PORT}/mcp") as (read, write, _):
                    async with ClientSession(read, write) as client:
                        await client.initialize()
                        result = await client.call_tool("get_qr_code", {})
                        import base64
                        data = next((base64.b64decode(item.data, validate=True) for item in result.content
                                     if item.type == "image" and item.mimeType == "image/png"), None)
            else:
                data = await (await connection()).pairing_qr()
            if data:
                return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})
        except Exception:
            pass
        return Response(status_code=204)

    start_lock = asyncio.Lock()

    @app.post("/start")
    async def start():
        async with start_lock:
            return await start_once()

    async def start_once():
        from .savia import SaviaClient
        if not key:
            raise HTTPException(409, "Set OPENROUTER_API_KEY and restart the local environment")
        if not all(process.poll() is None for process in children):
            raise HTTPException(503, "A local child process stopped; inspect the private logs")
        if journal.blocked():
            raise HTTPException(409, "Review uncertain delivery and explicitly skip it first")
        if holder["task"] and not holder["task"].done():
            raise HTTPException(409, "Test already running")
        whatsapp = await connection()
        if not (await whatsapp.status()).authenticated:
            raise HTTPException(409, "Pair your own phone first")
        value = json.loads(config_file.read_text())
        if not holder["savia"]:
            holder["savia"] = SaviaClient(f"http://127.0.0.1:{SAVIA_PORT}", state / "rc/fixture.json",
                                          profile=value["profile"], language=value["language"])
        try:
            await holder["savia"].login()
        except Exception:
            raise HTTPException(503, "Local Savia login failed; inspect the private RC log") from None
        bridge = Bridge(whatsapp, holder["savia"], journal, ffmpeg=ffmpeg)
        holder["bridge"] = bridge
        holder["task"] = asyncio.create_task(bridge.run())
        def finished(task):
            if not task.cancelled() and task.exception():
                bridge.running, bridge.last_state = False, "startup_failed"
        holder["task"].add_done_callback(finished)
        try:
            await asyncio.wait_for(bridge.ready.wait(), 75)
        except asyncio.TimeoutError:
            holder["task"].cancel()
            raise HTTPException(503, "WhatsApp baseline could not be established") from None
        if not bridge.running:
            raise HTTPException(503, "WhatsApp baseline could not be established")
        return {"started": True, "scope": "new messages in configured self chat only"}

    @app.post("/stop")
    async def stop():
        if holder["bridge"]:
            holder["bridge"].stop()
        return {"stopped": True, "in_flight_turn_may_finish": bool(holder["bridge"] and holder["bridge"].busy)}

    @app.post("/skip-uncertain")
    async def skip_uncertain():
        if holder["task"] and not holder["task"].done():
            raise HTTPException(409, "Stop the test before reviewing uncertain delivery")
        if holder["bridge"] and holder["bridge"].busy:
            raise HTTPException(409, "Wait for the active turn to finish")
        journal.acknowledge_uncertain()
        return {"skipped": True, "replayed": False}

    @app.post("/shutdown")
    async def shutdown():
        if holder["bridge"]:
            holder["bridge"].stop()
        callback = getattr(app.state, "stop_server", None)
        if callback:
            callback()
        return {"shutdown_requested": bool(callback)}

    return app
