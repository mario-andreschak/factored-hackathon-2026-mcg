"""Actual worker pipeline tests with local fake model; never import torch/Modal."""
import asyncio
import contextlib
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import personaplex_pcm_server as worker
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, unpack_output


EPOCH = "fixed_test_lease_" + "a" * 24
HEADERS = {"X-Verified-User-Data": json.dumps({"leaseEpoch": EPOCH})}
FRAME = struct.pack("<1920h", *([100] * FRAME_SAMPLES))


async def eventually(check, timeout=2):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if check():
            return
        await asyncio.sleep(.005)
    raise AssertionError("Local worker condition did not complete")


class FakeSocket:
    def __init__(self):
        self.sent = []

    async def send_bytes(self, value):
        self.sent.append(value)

    async def send_str(self, value):
        self.sent.append(json.loads(value))


class FakeModel:
    def __init__(self, settings=None):
        self.owner = threading.get_ident()
        self.calls = []

    def step(self, frame):
        self.calls.append((threading.get_ident(), frame))
        return worker.ModelFrame(frame, 40, " hello", .02)


class FakeInitialModel(FakeModel):
    def __init__(self, settings=None, prime_action=None):
        super().__init__(settings)
        self.prime_calls = []
        self.invalidated = threading.Event()
        self.prime_action = prime_action

    def prime_once(self, avatar):
        if threading.get_ident() != self.owner or self.invalidated.is_set() or self.prime_calls:
            raise worker.ProtocolError("Fake owner cannot prime")
        self.prime_calls.append((threading.get_ident(), avatar))
        if self.prime_action:
            self.prime_action(self)
        if self.invalidated.is_set():
            raise worker.ProtocolError("Late fake prime is unavailable")

    def invalidate(self):
        self.invalidated.set()


class NativePrimeHarness(worker.NativeModel):
    """Real constructor/prime/guards; replace only heavyweight weight warmup."""

    def _load_warm(self, settings):
        self.operations = []
        self.startup = worker.StartupProgress(writer=lambda event: None)
        for stage in self.startup.STAGES[:-2]:
            self.startup.mark(stage)
        self.wrap_system_prompt = Mock(side_effect=lambda text: '<system> ' + text + ' <system>')
        self.tokenizer = SimpleNamespace(encode=Mock(side_effect=lambda text: self.operations.append(('encode', text)) or [40, 41]))
        self.torch = SimpleNamespace(no_grad=contextlib.nullcontext,
                                    cuda=SimpleNamespace(synchronize=lambda: self.operations.append('synchronize')))
        self.mimi = SimpleNamespace(reset_streaming=lambda: self.operations.append('mimi.reset'))
        self.other_mimi = SimpleNamespace(reset_streaming=lambda: self.operations.append('other.reset'))
        state = SimpleNamespace(cache=SimpleNamespace(data_ptr=lambda: 123), offset=55)
        self.lm_gen = SimpleNamespace(text_prompt_tokens=[], _streaming_state=state,
                                     reset_streaming=lambda: self.operations.append('lm.reset'),
                                     step_system_prompts=lambda mimi: self.operations.append(('stock.prime', mimi)))
        self._phase = 'WARM'


class NativePrimeTests(unittest.TestCase):
    def test_fixed_default_still_primes_original_role_in_constructor(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600))
        self.assertEqual((model.phase, model.avatar), ('PRIMED', 'moss'))
        model.wrap_system_prompt.assert_called_once_with(worker.PERSONAS['moss'])
        self.assertEqual(model.operations[1:], ['mimi.reset', 'other.reset', 'lm.reset',
                                                ('stock.prime', model.mimi), 'mimi.reset', 'synchronize'])
        self.assertEqual(model.cache_pointer, 123)
        self.assertEqual(model.initial_prompt_tokens, (40, 41))

    def test_staged_warm_has_no_prompt_or_pcm_until_one_static_role_is_primed(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        self.assertEqual((model.phase, model.avatar, model.operations), ('WARM', None, []))
        with self.assertRaises(worker.ProtocolError): model.step(FRAME)
        with self.assertRaises(worker.ProtocolError): model.prime_once('arbitrary prompt')
        self.assertEqual(model.phase, 'WARM')
        model.prime_once('spark')
        model.wrap_system_prompt.assert_called_once_with(worker.PERSONAS['spark'])
        model.tokenizer.encode.assert_called_once_with('<system> ' + worker.PERSONAS['spark'] + ' <system>')
        before = list(model.operations)
        for role in ('spark', 'orbit', 'moss'):
            with self.assertRaises(worker.ProtocolError): model.prime_once(role)
        self.assertEqual(model.operations, before)

    def test_wrong_thread_cannot_prime_or_touch_native_cache(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        with ThreadPoolExecutor(max_workers=1) as executor:
            with self.assertRaises(worker.ProtocolError): executor.submit(model.prime_once, 'orbit').result()
            with self.assertRaises(worker.ProtocolError): executor.submit(model.step, FRAME).result()
        self.assertEqual((model.phase, model.operations), ('WARM', []))

    def test_failed_prime_and_external_invalidation_are_terminal(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        def failed(_mimi): raise RuntimeError('private error must remain local')
        model.lm_gen.step_system_prompts = failed
        with self.assertRaises(RuntimeError): model.prime_once('orbit')
        self.assertEqual(model.phase, 'CLOSED')
        with self.assertRaises(worker.ProtocolError): model.prime_once('moss')
        other = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        other.invalidate()
        with self.assertRaises(worker.ProtocolError): other.prime_once('moss')
        self.assertEqual((other.phase, other.operations), ('CLOSED', []))

    def test_staged_prompt_mutation_is_rejected_before_pcm_inference(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        model.prime_once('orbit'); model.lm_gen.text_prompt_tokens = [99]
        with self.assertRaises(worker.ProtocolError): model.step(FRAME)
        self.assertEqual(model.phase, 'CLOSED')

    def test_invalidation_inside_stock_prime_never_commits_selected_role_or_cache(self):
        model = NativePrimeHarness(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True))
        model.lm_gen.step_system_prompts = lambda mimi: model.invalidate()
        with self.assertRaises(worker.ProtocolError): model.prime_once('spark')
        self.assertEqual((model.phase, model.avatar), ('CLOSED', None))
        self.assertFalse(hasattr(model, 'cache_pointer'))
        self.assertFalse(hasattr(model, 'initial_prompt_tokens'))
        self.assertEqual(model.startup.index, len(model.startup.STAGES) - 2)


class WorkerPureTests(unittest.TestCase):
    def test_initial_mode_requires_explicit_opt_in_and_strict_private_payload(self):
        self.assertFalse(worker.Settings.from_env({'PERSONAPLEX_LEASE_EPOCH': EPOCH}).initial_mode)
        self.assertTrue(worker.Settings.from_env({'PERSONAPLEX_LEASE_EPOCH': EPOCH, 'PERSONAPLEX_INITIAL_MODE': '1'}).initial_mode)
        for value in ('true', 'initial', '', '2'):
            with self.assertRaises(worker.ProtocolError):
                worker.Settings.from_env({'PERSONAPLEX_LEASE_EPOCH': EPOCH, 'PERSONAPLEX_INITIAL_MODE': value})
        self.assertEqual(worker.parse_prime_request(b'{"selectionId":"opaque_123","avatar":"orbit"}'), ('opaque_123', 'orbit'))
        for raw in (b'', b' ' * 513, b'\xff', b'[]', b'{"selectionId":"x","avatar":"moss","avatar":"spark"}',
                    b'{"selectionId":"x","avatar":"moss","prompt":"custom"}', b'{"selectionId":true,"avatar":"moss"}',
                    b'{"selectionId":"../escape","avatar":"moss"}', b'{"selectionId":"x","avatar":"custom"}'):
            with self.subTest(raw=raw[:90]), self.assertRaises(worker.ProtocolError): worker.parse_prime_request(raw)

    def test_initial_prime_budget_and_ready_admission_preserve_original_expiry(self):
        settings = worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True)
        with patch.object(worker.time, 'monotonic', return_value=101):
            state = worker.WorkerState(settings, started=100); state.mark_warm()
        self.assertEqual(state.health()['avatar'], None)
        with patch.object(worker.time, 'monotonic', return_value=565.001):
            self.assertFalse(state.reserve_prime('once', 'orbit'))
            self.assertEqual((state.phase, state.avatar, state.selection_id), ('WARM', None, None))
        with patch.object(worker.time, 'monotonic', return_value=565):
            self.assertTrue(state.reserve_prime('once', 'orbit'))
            self.assertFalse(state.reserve_prime('twice', 'spark'))
            self.assertEqual((state.health()['phase'], state.health()['avatar'], state.health()['promptHash']), ('priming', 'orbit', None))
        with patch.object(worker.time, 'monotonic', return_value=580):
            state.publish_prime()
            self.assertTrue(state.health()['ready'])
        self.assertEqual(state.deadline, 700)
        self.assertEqual(state.prompt_hash, worker.hashlib.sha256(worker.PERSONAS['orbit'].encode()).hexdigest())
        with patch.object(worker.time, 'monotonic', return_value=580.001):
            self.assertFalse(state.health()['ready']); self.assertFalse(state.admit())
        with patch.object(worker.time, 'monotonic', return_value=580): self.assertTrue(state.admit())
        with patch.object(worker.time, 'monotonic', return_value=699): self.assertTrue(state.health()['ready'])
        with patch.object(worker.time, 'monotonic', return_value=700): self.assertFalse(state.health()['ready'])
        state.close(); self.assertEqual(state.health()['phase'], 'closed')

    def test_late_prime_cannot_publish_ready_or_reset_reserved_choice(self):
        with patch.object(worker.time, 'monotonic', return_value=101):
            state = worker.WorkerState(worker.Settings('moss', 'NATM1.pt', EPOCH, 600, initial_mode=True), started=100)
            state.mark_warm(); self.assertTrue(state.reserve_prime('one', 'spark'))
        with patch.object(worker.time, 'monotonic', return_value=580.001):
            with self.assertRaises(worker.ProtocolError): state.publish_prime()
            self.assertFalse(state.ready); self.assertFalse(state.reserve_prime('other', 'moss'))
        self.assertEqual((state.avatar, state.selection_id, state.prompt_hash), ('spark', 'one', None))
        state.model = FakeInitialModel(); state.close()
        self.assertTrue(state.model.invalidated.is_set())
        with self.assertRaises(worker.ProtocolError): state.publish_prime()

    def test_startup_bound_consumes_existing_lifetime_without_extending_it(self):
        settings = worker.Settings("moss", "NATM1.pt", EPOCH, 600)
        state = worker.WorkerState(settings, started=100)
        self.assertEqual(state.startup_deadline, 340)
        self.assertEqual(state.deadline, 700)
        short = worker.WorkerState(worker.Settings("moss", "NATM1.pt", EPOCH, 30), started=100)
        self.assertEqual(short.startup_deadline, 130)
        self.assertEqual(short.deadline, 130)

    def test_startup_diagnostics_are_ordered_timings_without_dynamic_data(self):
        now = [10.0]
        events = []
        progress = worker.StartupProgress(clock=lambda: now[0], writer=events.append)
        progress.mark("initializing")
        now[0] = 15.5
        progress.mark("assets_verified")
        now[0] = 16.0
        progress.mark("source_verified")
        self.assertEqual(events[-1], {"status": "native_startup", "stage": "source_verified",
                                     "elapsedSeconds": 6.0, "stageSeconds": .5})
        for unsafe in ("https://provider.invalid?token=secret", EPOCH, "assets_verified", "ready"):
            with self.assertRaises(worker.ProtocolError):
                progress.mark(unsafe)
        self.assertEqual(len(events), 3)
        self.assertNotIn(EPOCH, json.dumps(events))

    def test_fixed_settings_lease_header_and_single_admission(self):
        settings = worker.Settings.from_env({"PERSONAPLEX_LEASE_EPOCH": EPOCH})
        self.assertEqual((settings.avatar, settings.voice, settings.deadline_seconds), ("moss", "NATM1.pt", 600))
        self.assertTrue(worker.verified_lease_header(HEADERS["X-Verified-User-Data"], EPOCH))
        for value in (None, "{}", "not-json", json.dumps({"leaseEpoch": "wrong"}), json.dumps({"leaseEpoch": EPOCH, "bankId": "unexpected"})):
            self.assertFalse(worker.verified_lease_header(value, EPOCH))
        for name, value in (("PERSONAPLEX_AVATAR", "unknown"), ("PERSONAPLEX_VOICE", "../voice.pt"),
                            ("PERSONAPLEX_DEADLINE_SECONDS", "601"), ("PERSONAPLEX_DEADLINE_SECONDS", "0"),
                            ("PERSONAPLEX_MODEL_DIR", "https://external.invalid/weights")):
            with self.subTest(name=name), self.assertRaises(worker.ProtocolError):
                worker.Settings.from_env({"PERSONAPLEX_LEASE_EPOCH": EPOCH, name: value})
        state = worker.WorkerState(settings)
        self.assertFalse(state.admit())
        state.ready = True
        self.assertTrue(state.admit())
        self.assertFalse(state.admit())
        self.assertEqual(set(state.health()), {"ready", "protocol", "avatar", "sourceRevision", "modelRevision"})
        self.assertNotIn(EPOCH, json.dumps(state.health()))

    def test_offline_pins_hashes_and_lookup_guard_have_no_network_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = (*worker.pinned.MODEL_FILES, "voices/NATM1.pt")
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(("fixed-" + name).encode())
            manifest = {"source_revision": worker.pinned.SOURCE_REVISION, "model_revision": worker.pinned.MODEL_REVISION,
                        "sha256": {name: worker.sha256_file(root / name) for name in names}}
            (root / "revision.json").write_text(json.dumps(manifest))
            assets = worker.verify_assets(worker.Settings("moss", "NATM1.pt", EPOCH, 600, root))
            download = worker.offline_download_guard(assets)
            self.assertEqual(download(worker.pinned.MODEL_REPO, "config.json"), str(root / "config.json"))
            for repo, name, options in (("other/repo", "config.json", {}),
                                        (worker.pinned.MODEL_REPO, "../config.json", {}),
                                        (worker.pinned.MODEL_REPO, "config.json", {"revision": "main"})):
                with self.assertRaises(worker.ProtocolError):
                    download(repo, name, **options)
            (root / "model.safetensors").write_bytes(b"altered")
            with self.assertRaises(worker.ProtocolError):
                worker.verify_assets(worker.Settings("moss", "NATM1.pt", EPOCH, 600, root))

    def test_input_frame_bounds_include_partial_frame_and_reject_text_or_tools(self):
        inbox = worker.Inbox()
        inbox.accept_binary(b"\x10" + bytes(FRAME_BYTES * 6))
        with self.assertRaises(worker.ProtocolError):
            inbox.accept_binary(b"\x10\x00\x00")
        for packet in (b"\x01\x00\x00", b"\x10", b"\x10\x00", b"\x10" + bytes(FRAME_BYTES * 6 + 2)):
            with self.subTest(packet_size=len(packet)), self.assertRaises(worker.ProtocolError):
                worker.Inbox().accept_binary(packet)
        for event in ({"type": "public_result", "id": "task", "text": "account result"},
                      {"type": "setPersona", "id": "world"}, {"type": "interrupt", "id": "ok", "extra": True}):
            with self.assertRaises(worker.ProtocolError):
                worker.Inbox().accept_control(json.dumps(event))

    def test_caption_generation_completion_unique_ids_and_unicode_bounds(self):
        caption = worker.Caption()
        active = caption.update(worker.ModelFrame(bytes(FRAME_BYTES), 40, " hello", .02), 0)
        self.assertEqual((active["generation"], active["text"], active["done"]), (0, "hello", False))
        quiet = worker.ModelFrame(bytes(FRAME_BYTES), 3, "", 0)
        for _ in range(7):
            self.assertIsNone(caption.update(quiet, 0))
        self.assertTrue(caption.update(quiet, 0)["done"])
        other = worker.Caption().update(worker.ModelFrame(bytes(FRAME_BYTES), 40, " hello", .02), 0)
        self.assertNotEqual(active["id"], other["id"])
        bounded = caption.update(worker.ModelFrame(bytes(FRAME_BYTES), 40, "🙂" * 3000, .02), 1)
        self.assertTrue(bounded["done"])
        self.assertLessEqual(len(bounded["text"].encode()), 8000)
        self.assertLess(len(json.dumps(bounded, ensure_ascii=False)), 12000)


class WorkerStreamTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.tasks = []
        self.streams = []

    async def asyncTearDown(self):
        for stream in self.streams:
            stream.close()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.executor.shutdown(wait=True, cancel_futures=True)

    async def start_stream(self, model=None):
        ws = FakeSocket()
        model = model or FakeModel()
        stream = worker.Stream(ws, model, self.executor, time.monotonic() + 5)
        task = asyncio.create_task(stream.run())
        self.streams.append(stream)
        self.tasks.append(task)
        await eventually(lambda: bool(ws.sent))
        self.assertEqual(ws.sent[0]["type"], "ready")
        return stream, ws, model, task

    async def test_irregular_pcm_partitions_keep_one_model_owner_and_global_clock(self):
        stream, ws, model, _ = await self.start_stream()
        stream.inbox.accept_binary(b"\x10" + FRAME[:1200])
        stream.inbox.accept_binary(b"\x10" + FRAME[1200:])
        await eventually(lambda: any(isinstance(value, bytes) for value in ws.sent))
        first = unpack_output(next(value for value in ws.sent if isinstance(value, bytes)))
        self.assertEqual((first.generation, first.sample_index, first.pcm), (0, 0, FRAME))
        stream.inbox.accept_binary(b"\x10" + bytes(FRAME_BYTES))
        await eventually(lambda: sum(isinstance(value, bytes) for value in ws.sent) == 2)
        second = unpack_output([value for value in ws.sent if isinstance(value, bytes)][1])
        self.assertEqual(second.sample_index, FRAME_SAMPLES)
        self.assertEqual(model.calls[0][1], FRAME)
        self.assertEqual(model.calls[1][1], bytes(FRAME_BYTES))
        self.assertEqual(len({thread for thread, _ in model.calls}), 1)

    async def test_interrupt_during_gpu_step_discards_old_output_ack_advances_once_and_clock_continues(self):
        started, release = threading.Event(), threading.Event()

        class BlockingModel(FakeModel):
            def step(self, frame):
                started.set()
                if not release.wait(1):
                    raise AssertionError("Test did not release fake computation")
                return super().step(frame)

        stream, ws, model, _ = await self.start_stream(BlockingModel())
        stream.inbox.accept_binary(b"\x10" + FRAME)
        await eventually(started.is_set)
        stream.inbox.accept_control(json.dumps({"type": "interrupt", "id": "cancel-1"}))
        release.set()
        await eventually(lambda: any(isinstance(value, dict) and value.get("type") == "interrupted" for value in ws.sent))
        self.assertFalse(any(isinstance(value, bytes) for value in ws.sent))
        self.assertFalse(any(isinstance(value, dict) and value.get("type") == "transcript" for value in ws.sent))
        ack = next(value for value in ws.sent if isinstance(value, dict) and value.get("type") == "interrupted")
        self.assertEqual(ack, {"type": "interrupted", "id": "cancel-1", "generation": 1})
        stream.inbox.accept_control(json.dumps({"type": "interrupt", "id": "cancel-1"}))
        await eventually(lambda: sum(isinstance(value, dict) and value.get("type") == "interrupted" for value in ws.sent) == 2)
        self.assertEqual(stream.generation, 1)
        stream.inbox.accept_binary(b"\x10" + FRAME)
        await eventually(lambda: any(isinstance(value, bytes) for value in ws.sent))
        output = unpack_output(next(value for value in ws.sent if isinstance(value, bytes)))
        self.assertEqual((output.generation, output.sample_index), (1, FRAME_SAMPLES))
        self.assertEqual(len(model.calls), 2)

    async def test_disconnect_during_pending_computation_suppresses_late_pcm_and_caption(self):
        started, release = threading.Event(), threading.Event()

        class BlockingModel(FakeModel):
            def step(self, frame):
                started.set()
                release.wait(1)
                return super().step(frame)

        stream, ws, _, task = await self.start_stream(BlockingModel())
        stream.inbox.accept_binary(b"\x10" + FRAME)
        await eventually(started.is_set)
        stream.close()
        release.set()
        await asyncio.wait_for(task, 1)
        self.assertEqual(len(ws.sent), 1)

    async def test_worker_deadline_prevents_further_output(self):
        stream, ws, model, task = await self.start_stream()
        stream.deadline = time.monotonic() + .02
        with self.assertRaises(TimeoutError):
            await asyncio.wait_for(task, .2)
        self.assertEqual(len(model.calls), 0)
        self.assertEqual(len(ws.sent), 1)


class WorkerHttpTests(unittest.IsolatedAsyncioTestCase):
    @contextlib.asynccontextmanager
    async def initial_worker(self, prime_action=None, lifetime=600):
        with socket.socket() as reserve:
            reserve.bind(('127.0.0.1', 0)); port = reserve.getsockname()[1]
        models = []
        def factory(settings):
            model = FakeInitialModel(settings, prime_action); models.append(model); return model
        with tempfile.TemporaryDirectory() as directory, patch.object(worker, 'READY_FILE', Path(directory) / 'ready'), \
                patch.object(worker, 'WARM_FILE', Path(directory) / 'warm'):
            settings = worker.Settings('moss', 'NATM1.pt', EPOCH, lifetime, initial_mode=True)
            server = asyncio.create_task(worker.serve(settings, model_factory=factory, port=port))
            try:
                await eventually(lambda: worker.WARM_FILE.exists())
                yield f'http://127.0.0.1:{port}', models, server
            finally:
                if not server.done(): server.cancel()
                await asyncio.gather(server, return_exceptions=True)
                self.assertFalse(worker.READY_FILE.exists())
                self.assertFalse(worker.WARM_FILE.exists())

    async def test_initial_warm_is_authenticated_not_pcm_ready_and_bad_prime_does_not_consume_choice(self):
        from aiohttp import ClientSession, WSServerHandshakeError
        async with self.initial_worker() as (base, models, _), ClientSession() as client:
            async with client.get(base + '/healthz', headers=HEADERS) as response:
                health = await response.json()
                self.assertEqual(health, {'ready': False, 'protocol': worker.PROTOCOL, 'avatar': None,
                    'sourceRevision': worker.pinned.SOURCE_REVISION, 'modelRevision': worker.pinned.MODEL_REVISION,
                    'selection': 'initial', 'phase': 'warm', 'voice': 'NATM1.pt', 'promptHash': None, 'selectionId': None})
            self.assertFalse(worker.READY_FILE.exists())
            with self.assertRaises(WSServerHandshakeError) as rejected: await client.ws_connect(base + '/api/chat', headers=HEADERS)
            self.assertEqual(rejected.exception.status, 409)
            async with client.post(base + '/api/prime', json={'selectionId': 'once', 'avatar': 'orbit'}) as response:
                self.assertEqual(response.status, 401)
            for value in ('{"selectionId":"once","avatar":"orbit","prompt":"private"}',
                          '{"selectionId":"once","avatar":"moss","avatar":"spark"}', ' ' * 513):
                async with client.post(base + '/api/prime', data=value, headers={**HEADERS, 'Content-Type': 'application/json'}) as response:
                    self.assertEqual(response.status, 400)
            self.assertEqual(models[0].prime_calls, [])
            async with client.get(base + '/healthz', headers=HEADERS) as response: self.assertEqual((await response.json())['phase'], 'warm')

    async def test_initial_once_primes_then_streams_on_same_owner_with_unchanged_clock_and_expiry(self):
        from aiohttp import ClientSession
        async with self.initial_worker() as (base, models, server), ClientSession() as client:
            async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'one', 'avatar': 'orbit'}) as response:
                self.assertEqual(response.status, 200); health = await response.json()
            self.assertEqual((health['ready'], health['phase'], health['avatar'], health['selectionId']), (True, 'primed', 'orbit', 'one'))
            self.assertEqual(health['promptHash'], worker.hashlib.sha256(worker.PERSONAS['orbit'].encode()).hexdigest())
            self.assertTrue(worker.WARM_FILE.exists()); self.assertTrue(worker.READY_FILE.exists())
            async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'other', 'avatar': 'spark'}) as response: self.assertEqual(response.status, 409)
            async with client.ws_connect(base + '/api/chat', headers=HEADERS) as ws:
                self.assertEqual((await ws.receive_json())['type'], 'ready')
                await ws.send_bytes(b'\x10' + FRAME)
                packet = unpack_output((await ws.receive(timeout=1)).data)
                self.assertEqual((packet.generation, packet.sample_index, packet.pcm), (0, 0, FRAME))
                async with client.get(base + '/healthz', headers=HEADERS) as response: self.assertEqual((await response.json())['phase'], 'streaming')
            await asyncio.wait_for(server, 2)
            model = models[0]
            self.assertEqual(model.prime_calls, [(model.owner, 'orbit')])
            self.assertEqual(model.calls, [(model.owner, FRAME)])

    async def test_concurrent_prime_and_pcm_are_rejected_while_first_selection_is_running(self):
        from aiohttp import ClientSession, WSServerHandshakeError
        started, release = threading.Event(), threading.Event()
        def block(model): started.set(); release.wait(2)
        async with self.initial_worker(block) as (base, models, _), ClientSession() as client:
            first = asyncio.create_task(client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'first', 'avatar': 'spark'}))
            try:
                await eventually(started.is_set)
                async with client.get(base + '/healthz', headers=HEADERS) as response:
                    value = await response.json()
                    self.assertEqual((value['ready'], value['phase'], value['avatar'], value['selectionId'], value['promptHash']), (False, 'priming', 'spark', 'first', None))
                async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'second', 'avatar': 'orbit'}) as response: self.assertEqual(response.status, 409)
                with self.assertRaises(WSServerHandshakeError) as rejected: await client.ws_connect(base + '/api/chat', headers=HEADERS)
                self.assertEqual(rejected.exception.status, 409)
                self.assertFalse(worker.READY_FILE.exists())
                release.set()
                response = await asyncio.wait_for(first, 1)
                self.assertEqual(response.status, 200); await response.read(); response.release()
                self.assertEqual(models[0].prime_calls, [(models[0].owner, 'spark')])
            finally:
                release.set()
                if not first.done(): first.cancel()
                await asyncio.gather(first, return_exceptions=True)

    async def test_initial_insufficient_budget_never_calls_model_or_admits_stream(self):
        from aiohttp import ClientSession, WSServerHandshakeError
        async with self.initial_worker(lifetime=134) as (base, models, _), ClientSession() as client:
            async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'one', 'avatar': 'moss'}) as response: self.assertEqual(response.status, 503)
            self.assertEqual(models[0].prime_calls, [])
            self.assertFalse(worker.READY_FILE.exists())
            with self.assertRaises(WSServerHandshakeError): await client.ws_connect(base + '/api/chat', headers=HEADERS)

    async def test_prime_timeout_closes_worker_and_suppresses_late_completion(self):
        from aiohttp import ClientSession
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        def block(model):
            started.set(); release.wait(2); returned.set()
        with patch.object(worker, 'PRIME_SECONDS', .15):
            async with self.initial_worker(block) as (base, models, server), ClientSession() as client:
                try:
                    async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'one', 'avatar': 'orbit'}) as response:
                        self.assertEqual(response.status, 503)
                        self.assertEqual(await response.json(), {'error': 'Initial selection failed'})
                    await asyncio.wait_for(server, 1)
                    self.assertTrue(started.is_set()); self.assertTrue(models[0].invalidated.is_set())
                    self.assertFalse(worker.READY_FILE.exists()); self.assertFalse(worker.WARM_FILE.exists())
                    release.set(); await eventually(returned.is_set)
                    self.assertFalse(worker.READY_FILE.exists())
                    self.assertEqual(len(models[0].prime_calls), 1)
                finally: release.set()

    async def test_prime_owner_disconnect_closes_worker_and_cannot_publish_late_ready(self):
        from aiohttp import ClientSession
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        def block(model): started.set(); release.wait(2); returned.set()
        async with self.initial_worker(block) as (base, models, server):
            client = ClientSession()
            first = asyncio.create_task(client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'one', 'avatar': 'moss'}))
            try:
                await eventually(started.is_set)
                first.cancel(); await asyncio.gather(first, return_exceptions=True); await client.close()
                await asyncio.wait_for(server, 1)
                self.assertTrue(models[0].invalidated.is_set())
                self.assertFalse(worker.READY_FILE.exists()); self.assertFalse(worker.WARM_FILE.exists())
                release.set(); await eventually(returned.is_set)
                self.assertFalse(worker.READY_FILE.exists())
            finally:
                release.set(); first.cancel(); await asyncio.gather(first, return_exceptions=True); await client.close()

    async def test_failed_prime_returns_only_fixed_error_and_cannot_retry(self):
        from aiohttp import ClientSession
        def failed(model): raise RuntimeError('private prompt URL/token must never appear')
        async with self.initial_worker(failed) as (base, models, server), ClientSession() as client:
            async with client.post(base + '/api/prime', headers=HEADERS, json={'selectionId': 'one', 'avatar': 'spark'}) as response:
                self.assertEqual(response.status, 503); self.assertEqual(await response.json(), {'error': 'Initial selection failed'})
            await asyncio.wait_for(server, 1)
            self.assertTrue(models[0].invalidated.is_set()); self.assertEqual(len(models[0].prime_calls), 1)
            self.assertFalse(worker.READY_FILE.exists())

    async def test_slow_initializer_times_out_without_publishing_or_admitting_a_late_model(self):
        from aiohttp import ClientSession

        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0)); port = reserve.getsockname()[1]
        initialized, release, returned = threading.Event(), threading.Event(), threading.Event()

        def model_factory(settings):
            initialized.set(); release.wait(2)
            model = FakeModel(settings); returned.set(); return model

        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "READY_FILE", Path(directory) / "ready"), \
                patch.object(worker, "MODEL_INIT_SECONDS", .15):
            settings = worker.Settings("moss", "NATM1.pt", EPOCH, 10)
            server = asyncio.create_task(worker.serve(settings, model_factory=model_factory, port=port))
            try:
                await eventually(initialized.is_set)
                async with ClientSession() as client:
                    async with client.get(f"http://127.0.0.1:{port}/healthz", headers=HEADERS) as response:
                        self.assertFalse((await response.json())["ready"])
                    async with client.get(f"http://127.0.0.1:{port}/api/chat", headers=HEADERS) as response:
                        self.assertEqual(response.status, 400)
                with self.assertRaises(TimeoutError):
                    await asyncio.wait_for(server, 1)
                self.assertFalse(worker.READY_FILE.exists())
                release.set(); await eventually(returned.is_set)
                self.assertFalse(worker.READY_FILE.exists())
            finally:
                release.set()
                if not server.done(): server.cancel()
                await asyncio.gather(server, return_exceptions=True)

    async def test_real_local_http_auth_readiness_single_admission_and_disconnect_cleanup(self):
        from aiohttp import ClientSession, WSMsgType, WSServerHandshakeError

        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            port = reserve.getsockname()[1]
        models = []

        def model_factory(settings):
            model = FakeModel(settings)
            models.append(model)
            return model

        with tempfile.TemporaryDirectory() as directory, patch.object(worker, "READY_FILE", Path(directory) / "ready"):
            settings = worker.Settings("moss", "NATM1.pt", EPOCH, 10)
            server = asyncio.create_task(worker.serve(settings, model_factory=model_factory, port=port))
            try:
                await eventually(lambda: worker.READY_FILE.exists())
                async with ClientSession() as client:
                    async with client.get(f"http://127.0.0.1:{port}/healthz") as response:
                        self.assertEqual(response.status, 401)
                    async with client.get(f"http://127.0.0.1:{port}/healthz", headers=HEADERS) as response:
                        self.assertEqual(response.status, 200)
                        health = await response.json()
                        self.assertTrue(health["ready"])
                        self.assertEqual(health["sourceRevision"], worker.pinned.SOURCE_REVISION)
                        self.assertEqual(set(health), {'ready', 'protocol', 'avatar', 'sourceRevision', 'modelRevision'})
                    async with client.post(f"http://127.0.0.1:{port}/api/prime", headers=HEADERS,
                                           json={'selectionId': 'initial-not-enabled', 'avatar': 'spark'}) as response:
                        self.assertEqual(response.status, 404)
                    # A plain health/probe mistake cannot consume the one stream.
                    async with client.get(f"http://127.0.0.1:{port}/api/chat", headers=HEADERS) as response:
                        self.assertEqual(response.status, 400)
                    async with client.ws_connect(f"http://127.0.0.1:{port}/api/chat", headers=HEADERS) as ws:
                        self.assertEqual((await ws.receive_json())["protocol"], worker.PROTOCOL)
                        with self.assertRaises(WSServerHandshakeError) as rejected:
                            await client.ws_connect(f"http://127.0.0.1:{port}/api/chat", headers=HEADERS)
                        self.assertEqual(rejected.exception.status, 409)
                        await ws.send_bytes(b"\x10" + FRAME)
                        message = await ws.receive(timeout=1)
                        self.assertEqual(message.type, WSMsgType.BINARY)
                        self.assertEqual(unpack_output(message.data).pcm, FRAME)
                        self.assertEqual(models[0].calls[0][0], models[0].owner)
                    await asyncio.wait_for(server, 2)
                    self.assertFalse(worker.READY_FILE.exists())
            finally:
                if not server.done():
                    server.cancel()
                    await asyncio.gather(server, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
