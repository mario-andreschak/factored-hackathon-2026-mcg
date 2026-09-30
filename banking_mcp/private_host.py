"""Optional project host MCP transport beside the single FLUJO-owned stdio pipe.

Source preparation only: no endpoint is opened by importing this module. Both
transports share the original Service/Authorizer/Store and its ONE event loop.
This is not a FLUJO adapter or an arbitrary action dispatch endpoint.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import signal
import stat
import threading

import anyio

from .security import BankError
from .server import create_http_app, run_stdio
from .service import Service


@contextmanager
def private_instance_lock(config):
    """Reserve the one companion process BEFORE Service/state/listener creation.

    The deployment must separately provide its fixed UID launcher and private
    state mount. Native model invocations of that launcher cannot start a second
    companion against the same protected lock. No PID-file/stale-lock fallback.
    """
    if config.private_host_port is None:
        yield
        return
    if os.name != "posix":
        raise ValueError("private companion requires POSIX isolation and locking")
    import fcntl
    directory = config.state_db.parent
    if ".." in directory.parts or any(parent.is_symlink() for parent in (directory, *directory.parents)):
        raise ValueError("private host state path must not contain links")
    info = directory.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError("private host state requires an owned0700 directory")
    descriptor = os.open(directory / ".private-host.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        lock = os.fstat(descriptor)
        if (not stat.S_ISREG(lock.st_mode) or lock.st_uid != os.geteuid() or lock.st_nlink != 1
            or stat.S_IMODE(lock.st_mode) != 0o600):
            raise ValueError("invalid private host instance lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BankError("server_busy") from None
        private_tls_files(config)
        yield
    finally:
        os.close(descriptor)


def private_tls_files(config):
    """Protect the serving key; frontend must pin/verify the expected certificate."""
    if os.name != "posix":
        raise ValueError("private companion requires POSIX isolation")
    for path in (config.private_host_cert_file, config.private_host_key_file):
        if (not isinstance(path, Path) or not path.is_absolute() or ".." in path.parts
            or any(parent.is_symlink() for parent in (path, *path.parents))):
            raise ValueError("invalid private host TLS path")
        info = path.stat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400):
            raise ValueError("private host TLS files require owned0400 regular files")


async def coordinate_transports(service, *, stdio, host, stop_host):
    """One close owner, including startup failure, EOF and cancellation.

    `host` must drain on stop_host; it is shielded from group cancellation so
    shutdown can finish its HTTP requests and MCP manager first. The original
    Service's non-abandoning thread calls also drain before stdio returns.
    Pure tests can supply fakes without opening a transport or action state.
    """
    try:
        async with anyio.create_task_group() as group:
            async def serve_host():
                try:
                    with anyio.CancelScope(shield=True):
                        await host()
                finally:
                    group.cancel_scope.cancel()

            group.start_soon(serve_host)
            try:
                await stdio()
            finally:
                stop_host()
    finally:
        service.close()


def expected_startup_failure(error):
    """Only expected startup leaves may cross the CLI as a fixed public code."""
    if isinstance(error, BaseExceptionGroup):
        return bool(error.exceptions) and all(expected_startup_failure(item) for item in error.exceptions)
    return isinstance(error, (OSError, ValueError, BankError))


def private_http_server(app, *, bind, port, cert_file, key_file):
    """Construct only; explicit private interface, no forwarded identity/stdout."""
    import uvicorn

    class HostServer(uvicorn.Server):
        @contextmanager
        def capture_signals(self):
            # Uvicorn's default re-raises SIGTERM after HTTP cleanup, before the
            # outer stdio drain/Service close. Own graceful signals here instead.
            previous = {}
            if threading.current_thread() is threading.main_thread():
                previous = {number: signal.signal(number, self.handle_exit)
                            for number in (signal.SIGINT, signal.SIGTERM)}
            try:
                yield
            finally:
                for number, handler in previous.items():
                    signal.signal(number, handler)

        def handle_exit(self, _number, _frame):
            # A second signal must not bypass lifespan/request cleanup.
            self.should_exit = True

    return HostServer(uvicorn.Config(app, host=bind, port=port, workers=1,
        proxy_headers=False, access_log=False, log_config=None, log_level="critical",
        timeout_graceful_shutdown=15, lifespan="on", ssl_certfile=str(cert_file), ssl_keyfile=str(key_file)))


async def run_stdio_with_private_http(service: Service):
    """Run the original stdio server and a private standard MCP HTTP companion."""
    # Construction failures must also close the one Service exactly once.
    try:
        port = service.config.private_host_port
        if port is None:
            raise ValueError("private host port required")
        private_tls_files(service.config)
        app = create_http_app(service, close_service=False, private_host_bind=service.config.private_host_bind,
                              private_host_port=port, private_host_clients=service.config.private_host_clients)
        server = private_http_server(app, bind=service.config.private_host_bind, port=port,
                                      cert_file=service.config.private_host_cert_file, key_file=service.config.private_host_key_file)
    except BaseException as error:
        service.close()
        if isinstance(error, Exception) and expected_startup_failure(error):
            raise BankError("service_unavailable") from None
        raise

    async def stdio():
        await run_stdio(service, close_service=False)

    async def host():
        try:
            await server.serve()
        except SystemExit:
            # Uvicorn startup failure must unwind the stdio group and close the
            # shared Service, rather than terminate before the outer owner runs.
            raise BankError("service_unavailable") from None
        if not server.started:
            raise BankError("service_unavailable")

    try:
        await coordinate_transports(service, stdio=stdio, host=host,
                                    stop_host=lambda: setattr(server, "should_exit", True))
    except Exception as error:
        # AnyIO wraps a transport failure in an ExceptionGroup. Keep the CLI's
        # existing fixed public error handling; never emit private config/errors.
        if expected_startup_failure(error):
            raise BankError("service_unavailable") from None
        raise
