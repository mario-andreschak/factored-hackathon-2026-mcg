"""Offline regressions for conditional banking-source I/O and cancellation.

The controlled transport is test data. These tests do not certify organizer
data, deployed throughput, authorization, provider behavior, or a customer case.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import io
import threading
import time
from types import SimpleNamespace

import pytest

from banking_mcp.security import BankError
import dispute_workflow.bank_read as reads


class Transport:
    def __init__(self, records, *, mutate=None, get_gate=None, read_gate=None):
        self.records, self.mutate = records, mutate
        self.get_gate, self.read_gate = get_gate, read_gate
        self.lock = threading.Lock()
        self.calls, self.clients, self.configs, self.sessions = [], [], [], []
        self.active_bodies, self.peak_bodies = 0, 0
        self.entered = threading.Event()
        self.body_entered = threading.Event()
        self.close_observations = []

    def install(self, monkeypatch):
        import boto3
        transport = self

        class Session:
            def __init__(self):
                transport.sessions.append(threading.get_ident())

            def client(self, service, **options):
                assert service == "s3"
                transport.configs.append(options["config"])
                client = transport.new_client()
                transport.clients.append(client)
                return client

        monkeypatch.setattr(boto3.session, "Session", Session)
        monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: pytest.fail("shared default session"))
        monkeypatch.setattr(reads, "load_env", lambda path: {
            "Region": "test-region", "AccessKeyID": "test-access", "SecretAccessKey": "test-secret",
            "BucketName": "test-bucket"})

    def new_client(self):
        transport = self

        class Body(io.BytesIO):
            def __init__(self, raw):
                super().__init__(raw)
                with transport.lock:
                    transport.active_bodies += 1
                    transport.peak_bodies = max(transport.peak_bodies, transport.active_bodies)

            def read(self, size=-1):
                transport.entered.set()
                transport.body_entered.set()
                if transport.read_gate is not None:
                    assert transport.read_gate.wait(5), "test must release in-flight body"
                return super().read(size)

            def close(self):
                if not self.closed:
                    with transport.lock:
                        transport.active_bodies -= 1
                super().close()

        class Client:
            closed = False

            def get_object(self, **request):
                assert not self.closed
                with transport.lock:
                    transport.calls.append(request.copy())
                    number = len(transport.calls)
                transport.entered.set()
                if transport.get_gate is not None:
                    assert transport.get_gate.wait(5), "test must release in-flight request"
                obj, raw = transport.records[request["Key"][5:]]
                assert request == {"Bucket": "test-bucket", "Key": "data/" + obj["key"], "IfMatch": obj["etag"]}
                response = {"Body": Body(raw), "ContentLength": len(raw), "ETag": '"' + obj["etag"] + '"'}
                if transport.mutate:
                    transport.mutate(response, request, number)
                return response

            def close(self):
                with transport.lock:
                    transport.close_observations.append(transport.active_bodies)
                self.closed = True

        return Client()


def record(index=0, raw=b"a,b\n1,2\n"):
    obj = {"key": f"complaints/part-{index:04d}.csv", "bytes": len(raw), "etag": f"etag-{index}"}
    return obj, raw


def port(records):
    """I/O-only diagnostic port; no Service/admission/ledger is constructed."""
    adapter = object.__new__(reads.OwnedBankReads)
    adapter.service = SimpleNamespace(config=SimpleNamespace(source_env="test.env"))
    adapter.source_root = None
    adapter._source_local = threading.local()
    snapshot = SimpleNamespace(objects={obj["key"]: obj for obj, _ in records.values()})
    return adapter, snapshot


def test_complete_1097_inventory_is_fresh_conditional_and_client_is_prepared_before_pool(monkeypatch):
    records = dict((obj["key"], (obj, raw)) for obj, raw in (record(i) for i in range(1097)))
    transport = Transport(records)
    transport.install(monkeypatch)
    adapter, snapshot = port(records)
    objects = list(snapshot.objects.values())
    controller = threading.get_ident()
    for _ in range(2):
        with adapter._source_scope() as operation:
            verified = operation.all_sources(objects, lambda key: adapter._source_in_operation(snapshot, key, operation))
            assert verified == set(records)
            assert isinstance(verified, set), "table bytes must not be retained as reusable clearance"
    assert len(transport.sessions) == len(transport.clients) == 2
    assert transport.sessions == [controller, controller]
    assert all(config.max_pool_connections == reads.SOURCE_READ_WORKERS == 128 for config in transport.configs)
    assert all(config.retries["total_max_attempts"] == 1 for config in transport.configs)
    assert Counter(call["Key"] for call in transport.calls) == Counter({"data/" + key: 2 for key in records})
    assert transport.active_bodies == 0 and transport.close_observations == [0, 0]
    assert all(client.closed for client in transport.clients)


@pytest.mark.parametrize("field,value", [("ETag", '"different"'), ("ETag", None),
    ("ContentLength", -1), ("ContentLength", True), ("ContentLength", None)])
def test_wrong_response_identity_or_size_closes_body_and_never_verifies(monkeypatch, field, value):
    obj, raw = record()
    transport = Transport({obj["key"]: (obj, raw)}, mutate=lambda response, *_: response.update({field: value}))
    transport.install(monkeypatch)
    adapter, snapshot = port(transport.records)
    with pytest.raises(BankError, match="source_verification_unavailable"):
        adapter._source(snapshot, obj["key"])
    assert transport.active_bodies == 0 and transport.close_observations == [0]


@pytest.mark.parametrize("actual", [b"short", b"a,b\n1,2\nextra"])
def test_streamed_bytes_are_checked_independently_of_content_length(monkeypatch, actual):
    obj, _ = record()
    transport = Transport({obj["key"]: (obj, actual)},
        mutate=lambda response, *_: response.update(ContentLength=obj["bytes"]))
    transport.install(monkeypatch)
    adapter, snapshot = port(transport.records)
    with pytest.raises(BankError, match="source_verification_unavailable"):
        adapter._source(snapshot, obj["key"])
    assert transport.active_bodies == 0 and transport.close_observations == [0]


def test_history_correlates_a_new_source_read_after_full_inventory(monkeypatch):
    raw = b"complaint_id,customer_id,status,category,subcategory\nCMP-1,owner,Closed,Transactions,Dispute\n"
    obj, _ = record(raw=raw)
    transport = Transport({obj["key"]: (obj, raw)})
    transport.install(monkeypatch)
    adapter, snapshot = port(transport.records)
    adapter.principal = SimpleNamespace(customer="owner")
    # The query path is supplied only so this test reaches the actual reader's
    # full-inventory and per-row source checks without constructing authority.
    from pathlib import Path
    snapshot.build = Path("test-build")
    monkeypatch.setattr(adapter, "_table_complete", lambda *_: None)
    monkeypatch.setattr(adapter, "_table_sources", lambda *_: [obj])
    row = {"complaint_id": "CMP-1", "customer_id": "owner", "status": "Closed", "category": "Transactions",
           "subcategory": "Dispute", "_source_file": obj["key"]}
    monkeypatch.setattr(adapter, "_query", lambda *_: [row])
    assert adapter._historical(snapshot) == [row]
    assert len(transport.calls) == 2
    # A changed response on the mandatory new read cannot inherit the earlier
    # completed inventory's source clearance.
    transport.calls.clear()
    transport.mutate = lambda response, request, number: response.update(ETag='"changed"') if number == 2 else None
    with pytest.raises(BankError, match="source_verification_unavailable"):
        adapter._historical(snapshot)
    assert len(transport.calls) == 2 and transport.active_bodies == 0
    assert transport.close_observations == [0, 0]


def test_failed_foreign_inventory_object_blocks_owned_query(monkeypatch):
    records = dict((obj["key"], (obj, raw)) for obj, raw in (record(i) for i in range(20)))
    bad = next(iter(records))
    transport = Transport(records, mutate=lambda response, request, _: response.update(ETag='"changed"')
                          if request["Key"] == "data/" + bad else None)
    transport.install(monkeypatch)
    adapter, snapshot = port(records)
    monkeypatch.setattr(adapter, "_table_complete", lambda *_: None)
    monkeypatch.setattr(adapter, "_table_sources", lambda *_: list(snapshot.objects.values()))
    monkeypatch.setattr(adapter, "_query", lambda *_: pytest.fail("partial inventory cannot become history"))
    with pytest.raises(BankError, match="source_verification_unavailable"):
        adapter._historical(snapshot)
    assert transport.active_bodies == 0 and transport.close_observations == [0]


@pytest.mark.parametrize("size", [6, 9])
def test_declared_byte_window_bounds_dispatch_without_retaining_table(monkeypatch, tmp_path, size):
    monkeypatch.setattr(reads, "SOURCE_READ_WORKERS", 4)
    monkeypatch.setattr(reads, "MAX_IN_FLIGHT_SOURCE_BYTES", 8)
    raw = b"x" * size
    objects = [record(i, raw=raw)[0] for i in range(3)]
    entered, release = threading.Event(), threading.Event()
    lock, calls = threading.Lock(), []

    def read(key):
        with lock:
            calls.append(key)
        entered.set()
        assert release.wait(5)
        return raw

    operation = reads._SourceReadOperation(None, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as controller:
        worker = controller.submit(operation.all_sources, objects, read)
        try:
            assert entered.wait(3)
            # A second body cannot fit while the first is in flight, despite
            # spare workers. The oversized case must run entirely alone.
            with lock:
                assert len(calls) == 1
        finally:
            release.set()
        assert worker.result(timeout=3) == {obj["key"] for obj in objects}
    operation.close()
    assert len(calls) == 3 and operation.finished.is_set()


def test_worker_window_has_no_unbounded_executor_queue(monkeypatch, tmp_path):
    monkeypatch.setattr(reads, "SOURCE_READ_WORKERS", 4)
    objects = [record(i)[0] for i in range(20)]
    entered, release = threading.Event(), threading.Event()
    lock, calls = threading.Lock(), []

    def read(key):
        with lock:
            calls.append(key)
            if len(calls) == 4:
                entered.set()
        assert release.wait(5)
        return record()[1]

    operation = reads._SourceReadOperation(None, tmp_path)
    with ThreadPoolExecutor(max_workers=1) as controller:
        worker = controller.submit(operation.all_sources, objects, read)
        try:
            assert entered.wait(3)
            with lock:
                assert len(calls) == 4
            # The real pool's queue remains empty while every worker is busy.
            assert operation.executor._work_queue.qsize() == 0
        finally:
            release.set()
        assert worker.result(timeout=3) == {obj["key"] for obj in objects}
    operation.close()
    assert len(calls) == 20


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_third_history_pool_waits_and_stopped_waiter_cannot_leak_or_steal_a_slot(monkeypatch, tmp_path, stop):
    waiting = [threading.Event() for _ in range(4)]
    owner = threading.local()

    class ObservedSlots(threading.BoundedSemaphore):
        def acquire(self, *args, **kwargs):
            acquired = super().acquire(*args, **kwargs)
            if not acquired and hasattr(owner, "index"):
                waiting[owner.index].set()
            return acquired

    slots = ObservedSlots(2)
    monkeypatch.setattr(reads, "_HISTORY_READ_SLOTS", slots)
    obj, raw = record()
    operations = [reads._SourceReadOperation(None, tmp_path) for _ in range(4)]
    entered = [threading.Event() for _ in operations]
    release = [threading.Event() for _ in operations]
    started = [threading.Event() for _ in operations]

    def run(index):
        owner.index = index
        def read(_):
            entered[index].set()
            assert release[index].wait(5)
            return raw
        started[index].set()
        try:
            return operations[index].all_sources([obj], read)
        finally:
            operations[index].close()

    with ThreadPoolExecutor(max_workers=4) as controllers:
        first, second = controllers.submit(run, 0), controllers.submit(run, 1)
        third = fourth = None
        try:
            assert entered[0].wait(3) and entered[1].wait(3)
            third = controllers.submit(run, 2)
            assert started[2].wait(3) and waiting[2].wait(3)
            assert not entered[2].is_set(), "third admitted session cannot start a third heavy pool"
            if stop == "cancel":
                operations[2].cancel()
            else:
                operations[2].deadline = time.monotonic() - 1
            with pytest.raises(BankError, match="tool_unavailable"):
                third.result(timeout=3)
            assert not entered[2].is_set()
            fourth = controllers.submit(run, 3)
            assert started[3].wait(3) and waiting[3].wait(3)
            assert not entered[3].is_set(), "cancelled waiter must not release an unowned slot"
            release[0].set()
            assert first.result(timeout=3) == {obj["key"]}
            assert entered[3].wait(3), "actual pool drain must return its slot"
            assert not second.done()
        finally:
            for event in release:
                event.set()
        assert second.result(timeout=3) == {obj["key"]}
        assert fourth is not None and fourth.result(timeout=3) == {obj["key"]}
    assert slots.acquire(blocking=False) and slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)
    slots.release()
    slots.release()


async def wait_event(event):
    deadline = time.monotonic() + 3
    while not event.is_set():
        assert time.monotonic() < deadline, "controlled I/O boundary was not reached"
        await asyncio.sleep(0.005)


def test_repeated_cancellation_waits_for_body_pool_client_and_actual_controller_exit(monkeypatch):
    records = dict((obj["key"], (obj, raw)) for obj, raw in (record(i) for i in range(200)))
    body_release, controller_release, controller_closing = threading.Event(), threading.Event(), threading.Event()
    transport = Transport(records, read_gate=body_release)
    transport.install(monkeypatch)
    adapter, snapshot = port(records)
    original_close = reads._SourceReadOperation.close

    def close(operation):
        original_close(operation)
        controller_closing.set()
        assert controller_release.wait(5)

    monkeypatch.setattr(reads._SourceReadOperation, "close", close)

    def work(*_):
        operation = adapter._operation()
        return operation.all_sources(list(snapshot.objects.values()),
            lambda key: adapter._source_in_operation(snapshot, key, operation))

    monkeypatch.setattr(adapter, "_read", work)

    async def scenario():
        task = asyncio.create_task(adapter.read("get_related_complaints", {}))
        try:
            await wait_event(transport.body_entered)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and transport.active_bodies > 0
            assert not any(client.closed for client in transport.clients)
            body_release.set()
            await wait_event(controller_closing)
            task.cancel()
            await asyncio.sleep(0)
            # The operation's finished event is already set here. Only joining
            # the real executor future prevents escaping the still-live thread.
            assert not task.done() and transport.active_bodies == 0
            assert transport.close_observations == [0]
            assert len(transport.calls) <= reads.SOURCE_READ_WORKERS
        finally:
            body_release.set()
            controller_release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert not any(thread.name.startswith("savia-source") for thread in threading.enumerate())

    asyncio.run(scenario())


def test_wait_for_timeout_drains_before_an_immediate_fresh_retry(monkeypatch):
    obj, raw = record()
    release = threading.Event()
    transport = Transport({obj["key"]: (obj, raw)}, get_gate=release)
    transport.install(monkeypatch)
    adapter, snapshot = port(transport.records)
    monkeypatch.setattr(adapter, "_read", lambda *_: adapter._source(snapshot, obj["key"]))

    async def scenario():
        read_task = asyncio.create_task(adapter.read("get_related_complaints", {}))
        await wait_event(transport.entered)
        task = asyncio.create_task(asyncio.wait_for(read_task, 0.02))
        try:
            await asyncio.sleep(0.04)
            assert not task.done() and not transport.clients[0].closed
        finally:
            release.set()
        with pytest.raises(TimeoutError):
            await task
        assert transport.clients[0].closed and transport.close_observations == [0]
        assert await adapter.read("get_related_complaints", {}) == raw
        assert len(transport.clients) == 2 and all(client.closed for client in transport.clients)
        assert transport.close_observations == [0, 0] and transport.active_bodies == 0

    asyncio.run(scenario())
