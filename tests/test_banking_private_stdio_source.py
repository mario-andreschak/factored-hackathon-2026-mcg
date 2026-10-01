"""Pure fake descriptor checks; no real pipe, listener or banking runtime.

Reuse the inspected source loader which replaces Service/security/MCP before
import. Every descriptor operation and readiness wait below is an in-memory fake.
These checks do not prove Linux signal/EOF behavior or the actual SDK parser.
"""
from contextlib import asynccontextmanager, contextmanager
import stat
from types import SimpleNamespace

import anyio
import pytest

from tests.test_banking_private_host_source import FakeService, subject


@pytest.fixture
def descriptors(subject, monkeypatch):
    events, reads, writes = [], [], []
    modes = {0: stat.S_IFIFO, 1: stat.S_IFSOCK}
    blocking = {0: True, 1: False}
    def read(fd, size):
        assert fd == 0 and size == 65536
        events.append("read")
        value = reads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value
    def write(fd, value):
        assert fd == 1
        events.append("write")
        result = writes.pop(0) if writes else len(value)
        if isinstance(result, Exception):
            raise result
        if result > 0:
            emitted.extend(bytes(value[:result]))
        return result
    def set_blocking(fd, value):
        events.append(("blocking", fd, value))
        blocking[fd] = value
    emitted = bytearray()
    fake_os = SimpleNamespace(name="posix", fstat=lambda fd: SimpleNamespace(st_mode=modes[fd]),
        get_blocking=lambda fd: blocking[fd], set_blocking=set_blocking, read=read, write=write,
        close=lambda *_: pytest.fail("inherited descriptor closure forbidden"))
    monkeypatch.setattr(subject.private, "os", fake_os)
    async def readable(fd):
        assert fd == 0
        events.append("read-ready")
        await anyio.lowlevel.checkpoint()
    async def writable(fd):
        assert fd == 1
        events.append("write-ready")
        await anyio.lowlevel.checkpoint()
    monkeypatch.setattr(anyio, "wait_readable", readable)
    monkeypatch.setattr(anyio, "wait_writable", writable)
    return SimpleNamespace(subject=subject, os=fake_os, events=events, reads=reads,
        writes=writes, emitted=emitted, modes=modes, blocking=blocking)


def test_pipe_flags_restore_without_closing_inherited_descriptors(descriptors):
    state = descriptors
    with state.subject.private.cancellable_stdio_pipes() as streams:
        assert state.blocking == {0: False, 1: False}
        assert len(streams) == 2
    assert state.blocking == {0: True, 1: False}
    assert state.events == [("blocking", 0, False), ("blocking", 1, False),
        ("blocking", 1, False), ("blocking", 0, True)]


@pytest.mark.parametrize("descriptor,mode", [(0, stat.S_IFREG), (1, stat.S_IFCHR)])
def test_nonpipe_descriptors_fail_before_mutation(descriptors, descriptor, mode):
    descriptors.modes[descriptor] = mode
    with pytest.raises(ValueError, match="child stdio pipes"):
        with descriptors.subject.private.cancellable_stdio_pipes():
            pytest.fail("invalid descriptor must not enter")
    assert descriptors.events == []


def test_partial_flag_setup_restores_prior_success(descriptors):
    original = descriptors.os.set_blocking
    def fail(fd, value):
        if fd == 1:
            raise OSError("fictional setup failure")
        original(fd, value)
    descriptors.os.set_blocking = fail
    with pytest.raises(OSError, match="fictional setup failure"):
        with descriptors.subject.private.cancellable_stdio_pipes():
            pytest.fail("failed setup must not enter")
    assert descriptors.blocking == {0: True, 1: False}
    assert descriptors.events == [("blocking", 0, False), ("blocking", 0, True)]


def test_failed_output_restoration_still_restores_input(descriptors):
    original = descriptors.os.set_blocking
    output_calls = 0
    def fail(fd, value):
        nonlocal output_calls
        if fd == 1:
            output_calls += 1
            if output_calls == 2:
                raise OSError("fictional restore failure")
        original(fd, value)
    descriptors.os.set_blocking = fail
    with pytest.raises(OSError, match="fictional restore failure"):
        with descriptors.subject.private.cancellable_stdio_pipes():
            pass
    assert descriptors.blocking[0] is True


def test_input_frames_chunked_utf8_multiple_lines_and_final_eof(descriptors):
    descriptors.reads.extend([b'{"text":"caf\xc3', b'\xa9"}\n{}\r\nfinal', b'\xff', b''])
    async def scenario():
        with descriptors.subject.private.cancellable_stdio_pipes() as (stdin, _stdout):
            return [line async for line in stdin]
    assert anyio.run(scenario) == ['{"text":"caf\u00e9"}\n', '{}\r\n', 'final\ufffd']
    assert descriptors.reads == []


def test_input_retries_readiness_race_without_blocking_thread(descriptors):
    descriptors.reads.extend([BlockingIOError(), b'{}\n', b''])
    async def scenario():
        with descriptors.subject.private.cancellable_stdio_pipes() as (stdin, _stdout):
            return [line async for line in stdin]
    assert anyio.run(scenario) == ['{}\n']
    assert descriptors.events.count("read-ready") == 3


@pytest.mark.parametrize("chunks,accepted", [([b'x' * 65535 + b'\n', b''], True),
    ([b'x' * 65536, b''], True), ([b'x' * 65536, b'\n'], False),
    ([b'x' * 65536, b'x'], False)])
def test_input_line_byte_boundary(descriptors, chunks, accepted):
    descriptors.reads.extend(chunks)
    async def scenario():
        with descriptors.subject.private.cancellable_stdio_pipes() as (stdin, _stdout):
            return [line async for line in stdin]
    if accepted:
        assert len(anyio.run(scenario)[0].encode()) == 65536
    else:
        with pytest.raises(ValueError, match="message too large"):
            anyio.run(scenario)
    assert descriptors.blocking == {0: True, 1: False}


def test_output_retries_partial_writes_and_flushes_no_buffer(descriptors):
    descriptors.writes.extend([BlockingIOError(), 1, 2, 3])
    async def scenario():
        with descriptors.subject.private.cancellable_stdio_pipes() as (_stdin, stdout):
            assert await stdout.write('caf\u00e9\n') == 5
            await stdout.flush()
    anyio.run(scenario)
    assert bytes(descriptors.emitted) == 'caf\u00e9\n'.encode()
    assert descriptors.events.count("write-ready") == 4


def test_zero_write_fails_and_restores_flags(descriptors):
    descriptors.writes.append(0)
    async def scenario():
        with descriptors.subject.private.cancellable_stdio_pipes() as (_stdin, stdout):
            await stdout.write('{}\n')
    with pytest.raises(OSError, match="pipe unavailable"):
        anyio.run(scenario)
    assert descriptors.blocking == {0: True, 1: False}


@pytest.mark.parametrize("direction", ["read", "write"])
def test_idle_readiness_cancels_and_restores_flags(descriptors, monkeypatch, direction):
    async def scenario():
        ready = anyio.Event()
        async def idle(fd):
            assert fd == (0 if direction == "read" else 1)
            ready.set()
            await anyio.Event().wait()
        monkeypatch.setattr(anyio, "wait_readable" if direction == "read" else "wait_writable", idle)
        drained = anyio.Event()
        async def exchange():
            try:
                with descriptors.subject.private.cancellable_stdio_pipes() as (stdin, stdout):
                    if direction == "read":
                        async for _line in stdin:
                            pytest.fail("idle fake pipe yielded a line")
                    else:
                        await stdout.write('{}\n')
            finally:
                drained.set()
        with anyio.fail_after(2):
            async with anyio.create_task_group() as group:
                group.start_soon(exchange)
                await ready.wait()
                group.cancel_scope.cancel()
            assert drained.is_set()
    anyio.run(scenario)
    assert descriptors.blocking == {0: True, 1: False}
    assert "read" not in descriptors.events and "write" not in descriptors.events


def test_combined_transport_injects_streams_and_drains_before_close(subject, monkeypatch):
    service, events = FakeService(), []
    stdin, stdout = object(), object()
    @contextmanager
    def pipes():
        events.append("pipes-enter")
        try:
            yield stdin, stdout
        finally:
            events.append("pipes-restored")
    async def stdio(shared, **options):
        assert shared is service
        assert options == {"close_service": False, "stdin": stdin, "stdout": stdout}
        events.append("sdk-stdio-drained")
    class Runner:
        started = True
        should_exit = False
        async def serve(self):
            assert self.should_exit is True
    monkeypatch.setattr(subject.private, "cancellable_stdio_pipes", pipes)
    monkeypatch.setattr(subject.private, "private_tls_files", lambda _config: None)
    monkeypatch.setattr(subject.private, "create_http_app", lambda *_args, **_options: object())
    monkeypatch.setattr(subject.private, "private_http_server", lambda *_args, **_options: Runner())
    monkeypatch.setattr(subject.private, "run_stdio", stdio)
    anyio.run(lambda: subject.private.run_stdio_with_private_http(service))
    assert events == ["pipes-enter", "sdk-stdio-drained", "pipes-restored"]
    assert service.closed == 1


def test_supplied_text_streams_reach_sdk_transport(subject, monkeypatch):
    service, calls = FakeService(), []
    stdin, stdout = object(), object()
    @asynccontextmanager
    async def transport(**options):
        calls.append(options)
        yield "fake-read", "fake-write"
    monkeypatch.setattr(subject.server, "stdio_server", transport)
    anyio.run(lambda: subject.server.run_stdio(service, close_service=False, stdin=stdin, stdout=stdout))
    assert calls == [{"stdin": stdin, "stdout": stdout}]
    assert len(subject.stdio_runs) == 1 and service.closed == 0
