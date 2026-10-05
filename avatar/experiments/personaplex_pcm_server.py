"""Single-admission PersonaPlex PCM worker for a bounded private Modal Sandbox.

Importing this module never loads weights, reads credentials, or starts a server.
The authenticated Modal tunnel must inject verified lease metadata. This worker
does not accept text input, tool results, live persona changes, or bank narration.
The explicitly opted-in initial mode warms once and accepts one private preset
selection before conversational PCM. It is a source prototype, not enabled by
the default launcher or the production browser/relay.
"""
from __future__ import annotations

import asyncio
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import uuid

import personaplex_modal as pinned
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, MAX_BUFFER_FRAMES, Pcm24Framer, pack_output

PROTOCOL = "personaplex-pcm-v1"
SAMPLE_RATE = 24_000
MODEL_DIRECTORY = Path("/opt/personaplex-weights")
READY_FILE = Path("/tmp/personaplex-ready")
WARM_FILE = Path("/tmp/personaplex-warm")
MAX_CONTROL_BYTES = 512
MAX_CONTROL_QUEUE = 8
MAX_INTERRUPT_IDS = 512
INPUT_STALL_SECONDS = 3
MODEL_STEP_SECONDS = 2
SEND_SECONDS = 1
MODEL_INIT_SECONDS = 240
PRIME_SECONDS = 15
MINIMUM_STREAM_SECONDS = 120
SUPPORTED_VOICES = frozenset({"NATM1.pt"})
IDENTIFIER = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
COMMON_BOUNDARY = ("You are a friendly general-conversation companion. You cannot see bank accounts, websites, "
                   "or task results. Do not claim that you checked account facts, disputes, or made changes. "
                   "The separate visible computer handles account work.")
PERSONAS = {
    "moss": "Your name is Moss, a gentle ancient turtle. Speak calmly and warmly in short thoughtful phrases. " + COMMON_BOUNDARY,
    "orbit": "Your name is Orbit, a focused observatory companion. Speak clearly, practically, and concisely. " + COMMON_BOUNDARY,
    "spark": "Your name is Spark, an energetic roadside mechanic. Speak briskly with playful original humor. Listen when interrupted. " + COMMON_BOUNDARY,
}


class ProtocolError(ValueError):
    """Fixed protocol category; incoming/provider text is never echoed to clients."""


class StartupProgress:
    """Fixed, flushed milestone timings; no paths, credentials or prompt text."""

    STAGES = ("initializing", "assets_verified", "source_verified", "modules_imported",
              "mimi_loaded", "lm_loaded", "streaming_initialized", "cuda_warmed", "prompt_ready", "ready")

    def __init__(self, clock=time.monotonic, writer=None):
        self.clock = clock
        self.writer = writer
        self.started = self.previous = clock()
        self.index = 0

    def mark(self, stage: str):
        if self.index >= len(self.STAGES) or stage != self.STAGES[self.index]:
            raise ProtocolError("Unexpected fixed startup milestone")
        now = self.clock()
        event = {"status": "native_startup", "stage": stage,
                 "elapsedSeconds": round(max(0, now - self.started), 3),
                 "stageSeconds": round(max(0, now - self.previous), 3)}
        self.index += 1
        self.previous = now
        if self.writer is None:
            print(json.dumps(event, separators=(",", ":")), flush=True)
        else:
            self.writer(event)


@dataclass(frozen=True)
class Settings:
    avatar: str
    voice: str
    lease_epoch: str
    deadline_seconds: int
    model_dir: Path = MODEL_DIRECTORY
    initial_mode: bool = False

    @classmethod
    def from_env(cls, environment=None):
        values = os.environ if environment is None else environment
        avatar = values.get("PERSONAPLEX_AVATAR", "moss")
        voice = values.get("PERSONAPLEX_VOICE", "NATM1.pt")
        epoch = values.get("PERSONAPLEX_LEASE_EPOCH", "")
        raw_deadline = values.get("PERSONAPLEX_DEADLINE_SECONDS", "600")
        directory = values.get("PERSONAPLEX_MODEL_DIR", str(MODEL_DIRECTORY))
        initial = values.get("PERSONAPLEX_INITIAL_MODE", "0")
        if avatar not in PERSONAS or voice not in SUPPORTED_VOICES:
            raise ProtocolError("Unapproved fixed persona or voice")
        if not isinstance(epoch, str) or not re.fullmatch(r"[A-Za-z0-9_-]{24,128}", epoch):
            raise ProtocolError("A bounded opaque lease epoch is required")
        if not re.fullmatch(r"[0-9]{1,3}", raw_deadline) or not 30 <= int(raw_deadline) <= 600:
            raise ProtocolError("Worker deadline must be bounded to30..600s")
        if directory != str(MODEL_DIRECTORY):
            raise ProtocolError("Only the fixed offline model directory is accepted")
        if initial not in ("0", "1"):
            raise ProtocolError("Initial role mode must be explicitly0or1")
        return cls(avatar, voice, epoch, int(raw_deadline), initial_mode=initial == "1")


def parse_prime_request(raw: bytes) -> tuple[str, str]:
    """Private control accepts one opaque selection and a static preset only."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_CONTROL_BYTES:
        raise ProtocolError("Invalid bounded initial selection")

    def unique_fields(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError("Repeated initial selection field")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf8"), object_pairs_hook=unique_fields)
    except (UnicodeError, ValueError, TypeError) as error:
        raise ProtocolError("Invalid initial selection JSON") from error
    if (not isinstance(value, dict) or set(value) != {"selectionId", "avatar"}
            or not isinstance(value["selectionId"], str) or not IDENTIFIER.fullmatch(value["selectionId"])
            or not isinstance(value["avatar"], str) or value["avatar"] not in PERSONAS):
        raise ProtocolError("Only a bounded selection ID and preset are accepted")
    return value["selectionId"], value["avatar"]


def verified_lease_header(value: str | None, expected_epoch: str) -> bool:
    """Validate metadata already authenticated/injected by the Modal tunnel.

    Parsing this header alone is NOT authentication outside that private tunnel.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_CONTROL_BYTES:
        return False
    try:
        body = json.loads(value)
    except (ValueError, TypeError):
        return False
    if not isinstance(body, dict) or set(body) != {"leaseEpoch"} or not isinstance(body["leaseEpoch"], str):
        return False
    return hmac.compare_digest(body["leaseEpoch"].encode("utf8"), expected_epoch.encode("utf8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_assets(settings: Settings) -> dict[str, Path]:
    """Check the private cached image's exact pins/content, with no downloads."""
    manifest_path = settings.model_dir / "revision.json"
    if not manifest_path.is_file() or manifest_path.stat().st_size > 16_384:
        raise ProtocolError("Pinned offline manifest is unavailable")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))
    if manifest.get("source_revision") != pinned.SOURCE_REVISION or manifest.get("model_revision") != pinned.MODEL_REVISION:
        raise ProtocolError("Offline asset revisions do not match the qualified source")
    names = (*pinned.MODEL_FILES, f"voices/{settings.voice}")
    checksums = manifest.get("sha256")
    if not isinstance(checksums, dict) or set(checksums) != set(names):
        raise ProtocolError("Offline asset checksum manifest is incomplete")
    assets = {}
    root = settings.model_dir.resolve()
    for name in names:
        path = settings.model_dir / name
        checksum = checksums[name]
        if not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ProtocolError("Offline asset checksum is invalid")
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root) or path.stat().st_size <= 0:
            raise ProtocolError("Offline asset is unavailable or outside the cache")
        if not hmac.compare_digest(sha256_file(path), checksum):
            raise ProtocolError("Offline asset content does not match its pinned image manifest")
        assets[name] = path
    return assets


def offline_download_guard(assets: dict[str, Path]):
    """Bind any future helper's HF lookup to verified private image files only."""
    fixed = dict(assets)

    def local_download(repo_id, filename, **options):
        if (repo_id != pinned.MODEL_REPO or filename not in fixed
                or options.get("revision") not in (None, pinned.MODEL_REVISION)):
            raise ProtocolError("Only the pinned offline assets can be requested")
        return str(fixed[filename])

    return local_download


@dataclass(frozen=True)
class ModelFrame:
    pcm: bytes
    text_id: int
    text_piece: str
    rms: float


class NativeModel:
    """Only this object, in one dedicated executor thread, accesses GPU state."""

    def __init__(self, settings: Settings):
        self.owner = threading.get_ident()
        self._phase = "NEW"
        self._invalidated = threading.Event()
        self.initial_mode = settings.initial_mode
        self.avatar = None
        try:
            self._load_warm(settings)
            if not settings.initial_mode:
                self.prime_once(settings.avatar)
        except BaseException:
            self.invalidate()
            self._phase = "CLOSED"
            raise

    @property
    def phase(self):
        return "CLOSED" if self._invalidated.is_set() else self._phase

    def invalidate(self):
        # Thread-safe cancellation metadata only; no GPU/cache operation here.
        # A running CUDA call cannot be killed by Python. Its late completion
        # must observe this flag and can never publish readiness or be reused.
        self._invalidated.set()

    def _assert_owner(self):
        if threading.get_ident() != self.owner or self._invalidated.is_set():
            raise ProtocolError("Native model owner is unavailable")

    def _load_warm(self, settings: Settings):
        self.startup = StartupProgress()
        self.startup.mark("initializing")
        assets = verify_assets(settings)
        self.startup.mark("assets_verified")
        revision = subprocess.run(["git", "-C", "/opt/personaplex", "rev-parse", "HEAD"],
                                  capture_output=True, text=True, check=True, timeout=3).stdout.strip()
        if revision != pinned.SOURCE_REVISION:
            raise ProtocolError("Installed source revision does not match the pinned cache")
        self.startup.mark("source_verified")
        if os.environ.get("HF_TOKEN"):
            raise ProtocolError("Runtime model credentials must not be mounted")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        import numpy as np
        import sentencepiece
        import torch
        import huggingface_hub
        # The pinned loaders use explicit files. offline.run_inference (unused
        # here) contains a config counter lookup; bind every such lookup locally
        # before importing helpers so this image requires no HF cache or token.
        huggingface_hub.hf_hub_download = offline_download_guard(assets)
        from moshi.models import LMGen, loaders
        from moshi.offline import decode_tokens_to_pcm, seed_all, warmup, wrap_with_system_tags
        self.startup.mark("modules_imported")

        self.np, self.torch, self.decode = np, torch, decode_tokens_to_pcm
        self.wrap_system_prompt = wrap_with_system_tags
        seed_all(42_424_242)
        self.mimi = loaders.get_mimi(str(assets["tokenizer-e351c8d8-checkpoint125.safetensors"]), "cuda")
        self.other_mimi = loaders.get_mimi(str(assets["tokenizer-e351c8d8-checkpoint125.safetensors"]), "cuda")
        self.startup.mark("mimi_loaded")
        self.tokenizer = sentencepiece.SentencePieceProcessor(str(assets["tokenizer_spm_32k_3.model"]))
        lm = loaders.get_moshi_lm(str(assets["model.safetensors"]), device="cuda")
        lm.eval()
        self.startup.mark("lm_loaded")
        if self.mimi.sample_rate != SAMPLE_RATE or int(self.mimi.sample_rate / self.mimi.frame_rate) != FRAME_SAMPLES:
            raise ProtocolError("Cached model does not match the native PCM clock")
        self.lm_gen = LMGen(lm, audio_silence_frame_cnt=int(0.5 * self.mimi.frame_rate), sample_rate=SAMPLE_RATE,
                            device="cuda", frame_rate=self.mimi.frame_rate, save_voice_prompt_embeddings=False)
        self.mimi.streaming_forever(1)
        self.other_mimi.streaming_forever(1)
        self.lm_gen.streaming_forever(1)
        self.startup.mark("streaming_initialized")
        with torch.no_grad():
            warmup(self.mimi, self.other_mimi, self.lm_gen, "cuda", FRAME_SAMPLES)
            self.startup.mark("cuda_warmed")
            self.lm_gen.load_voice_prompt_embeddings(str(assets[f"voices/{settings.voice}"]))
        self._assert_owner()
        self._phase = "WARM"

    def prime_once(self, avatar: str):
        self._assert_owner()
        if self.phase != "WARM" or not isinstance(avatar, str) or avatar not in PERSONAS:
            raise ProtocolError("Only one initial preset may be primed")
        self._phase = "PRIMING"
        try:
            with self.torch.no_grad():
                # Exact pinned offline initializer; clear warmup's dummy history
                # once, then replay the already-loaded NATM1 voice and static text.
                self.lm_gen.text_prompt_tokens = self.tokenizer.encode(self.wrap_system_prompt(PERSONAS[avatar]))
                self.mimi.reset_streaming()
                self.other_mimi.reset_streaming()
                self.lm_gen.reset_streaming()
                self.lm_gen.step_system_prompts(self.mimi)
                self.mimi.reset_streaming()
                self.torch.cuda.synchronize()
            self._assert_owner()
            self.stream_state = self.lm_gen._streaming_state
            self.cache_pointer = self.stream_state.cache.data_ptr()
            self.initial_prompt_tokens = tuple(self.lm_gen.text_prompt_tokens)
            self.avatar = avatar
            self.startup.mark("prompt_ready")
            self._phase = "PRIMED"
        except BaseException:
            self.invalidate()
            self._phase = "CLOSED"
            raise

    def step(self, raw_frame: bytes) -> ModelFrame:
        self._assert_owner()
        if self.phase not in ("PRIMED", "STREAMING"):
            raise ProtocolError("Native PCM requires a primed initial preset")
        if not isinstance(raw_frame, bytes) or len(raw_frame) != FRAME_BYTES:
            raise ProtocolError("Native model needs one complete PCM frame")
        if self.initial_mode and tuple(self.lm_gen.text_prompt_tokens) != self.initial_prompt_tokens:
            self.invalidate()
            raise ProtocolError("Initial role prompt changed during conversation")
        self._phase = "STREAMING"
        np, torch = self.np, self.torch
        samples = np.frombuffer(raw_frame, dtype="<i2").astype(np.float32) / 32768.0
        with torch.no_grad():
            chunk = torch.from_numpy(samples).to("cuda")[None, None]
            codes = self.mimi.encode(chunk)
            _ = self.other_mimi.encode(chunk)
            if tuple(codes.shape) != (1, 8, 1):
                raise ProtocolError("Unexpected native user code frame")
            offset = self.stream_state.offset
            tokens = self.lm_gen.step(codes)  # Free native conversation ONLY: no forced text/audio.
            if tokens is None:
                raise ProtocolError("Prompt-primed model did not return an agent frame")
            pcm = self.decode(self.mimi, self.other_mimi, self.lm_gen, tokens)
            if pcm.shape != (FRAME_SAMPLES,) or not np.isfinite(pcm).all():
                raise ProtocolError("Invalid decoded PCM frame")
            if (self.lm_gen._streaming_state is not self.stream_state or self.stream_state.cache.data_ptr() != self.cache_pointer
                    or self.stream_state.offset != offset + 1):
                raise ProtocolError("Native streaming cache changed during the session")
            self._assert_owner()
            if self.initial_mode and tuple(self.lm_gen.text_prompt_tokens) != self.initial_prompt_tokens:
                self.invalidate()
                raise ProtocolError("Initial role prompt changed during conversation")
            text_id = int(tokens[0, 0, 0].item())
            piece = "" if text_id in (0, 1, 2, 3) else self.tokenizer.id_to_piece(text_id).replace("▁", " ")
            rms = float(np.sqrt(np.mean(pcm * pcm)))
            signed = np.clip(np.rint(pcm * 32768), -32768, 32767).astype("<i2").tobytes()
            return ModelFrame(signed, text_id, piece, rms)


class Inbox:
    """Bounded receiver queues; controls have priority over pending model frames."""

    def __init__(self):
        self.framer = Pcm24Framer()
        self.audio = deque()
        self.controls = deque()
        self.wake = asyncio.Event()
        self.closed = False

    def accept_binary(self, packet: bytes) -> None:
        if self.closed:
            return
        if not isinstance(packet, bytes) or not 3 <= len(packet) <= FRAME_BYTES * MAX_BUFFER_FRAMES + 1 or packet[0] != 0x10 or (len(packet) - 1) % 2:
            raise ProtocolError("Invalid PCM input packet")
        frames = self.framer.push(packet[1:])
        if (len(self.audio) + len(frames)) * FRAME_BYTES + len(self.framer.pending) > MAX_BUFFER_FRAMES * FRAME_BYTES:
            raise ProtocolError("Native input backlog exceeded its480ms bound")
        self.audio.extend(frames)
        if frames:
            self.wake.set()

    def accept_control(self, value: str) -> None:
        if self.closed:
            return
        if not isinstance(value, str) or not 1 <= len(value) <= MAX_CONTROL_BYTES:
            raise ProtocolError("Invalid control size")
        try:
            event = json.loads(value)
        except ValueError as error:
            raise ProtocolError("Invalid control JSON") from error
        if (not isinstance(event, dict) or set(event) != {"type", "id"} or event.get("type") != "interrupt"
                or not isinstance(event.get("id"), str) or not IDENTIFIER.fullmatch(event["id"])):
            raise ProtocolError("Only bounded interruption controls are supported")
        if len(self.controls) >= MAX_CONTROL_QUEUE:
            raise ProtocolError("Too many pending interruption controls")
        self.controls.append(event["id"])
        self.wake.set()

    async def next(self):
        while not self.closed:
            if self.controls:
                return "interrupt", self.controls.popleft()
            if self.audio:
                return "audio", self.audio.popleft()
            self.wake.clear()
            await self.wake.wait()
        return None

    def close(self):
        self.closed = True
        self.audio.clear()
        self.controls.clear()
        self.framer.discard()
        self.wake.set()


class Caption:
    def __init__(self):
        self.prefix = uuid.uuid4().hex[:16]
        self.count = 0
        self.id = None
        self.text = ""
        self.quiet_frames = 0

    def clear(self):
        self.id = None
        self.text = ""
        self.quiet_frames = 0

    def update(self, frame: ModelFrame, generation: int):
        if frame.text_piece:
            if self.id is None:
                self.count += 1
                self.id = f"assistant-{self.prefix}-{generation}-{self.count}"
            combined = (self.text + frame.text_piece).encode("utf8")
            self.text = combined[:8000].decode("utf8", errors="ignore")
            self.quiet_frames = 0
            done = len(combined) >= 8000
        elif self.id and frame.rms < .005:
            self.quiet_frames += 1
            done = self.quiet_frames >= 8
            if not done:
                return None
        else:
            self.quiet_frames = 0
            return None
        if not self.id or not self.text.strip():
            return None
        event = {"type": "transcript", "role": "assistant", "generation": generation,
                 "id": self.id, "text": self.text.strip(), "done": done}
        if done:
            self.clear()
        return event


class Stream:
    """One inference owner and writer; cancellation never resets the model cache."""

    def __init__(self, ws, model, executor, deadline: float):
        self.ws, self.model, self.executor, self.deadline = ws, model, executor, deadline
        self.inbox = Inbox()
        self.generation = 0
        self.sample_clock = 0
        self.interrupts = {}
        self.caption = Caption()
        self.closed = False
        self.write_lock = asyncio.Lock()

    async def send(self, value):
        async with self.write_lock:
            if self.closed:
                return
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Worker lifetime reached")
            operation = self.ws.send_bytes(value) if isinstance(value, bytes) else self.ws.send_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))
            await asyncio.wait_for(operation, timeout=min(SEND_SECONDS, max(.001, self.deadline - time.monotonic())))

    async def acknowledge(self, identifier: str):
        if identifier not in self.interrupts:
            if len(self.interrupts) >= MAX_INTERRUPT_IDS or self.generation >= 0xFFFFFFFF:
                raise ProtocolError("Interruption bound reached")
            self.generation += 1
            self.interrupts[identifier] = self.generation
            self.caption.clear()
        await self.send({"type": "interrupted", "id": identifier, "generation": self.interrupts[identifier]})

    async def run(self):
        await self.send({"type": "ready", "protocol": PROTOCOL, "sampleRate": SAMPLE_RATE,
                         "frameSamples": FRAME_SAMPLES, "format": "pcm16le"})
        loop = asyncio.get_running_loop()
        while not self.closed:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Worker lifetime reached")
            item = await asyncio.wait_for(self.inbox.next(), timeout=min(INPUT_STALL_SECONDS, remaining))
            if item is None:
                return
            kind, value = item
            if kind == "interrupt":
                await self.acknowledge(value)
                continue
            generation_before = self.generation
            result = await asyncio.wait_for(loop.run_in_executor(self.executor, self.model.step, value),
                                           timeout=min(MODEL_STEP_SECONDS, max(.001, self.deadline - time.monotonic())))
            if self.closed:
                return
            if not isinstance(result, ModelFrame) or len(result.pcm) != FRAME_BYTES:
                raise ProtocolError("Invalid model output frame")
            sample_index = self.sample_clock
            self.sample_clock += FRAME_SAMPLES
            # An interrupt received during GPU computation takes effect before
            # publishing that computation. Its old audio/caption is discarded.
            while self.inbox.controls:
                await self.acknowledge(self.inbox.controls.popleft())
            if self.closed or generation_before != self.generation:
                continue
            await self.send(pack_output(self.generation, sample_index, result.pcm))
            event = self.caption.update(result, self.generation)
            if event:
                await self.send(event)

    def close(self):
        self.closed = True
        self.inbox.close()
        self.caption.clear()


class WorkerState:
    def __init__(self, settings: Settings, started=None):
        self.settings = settings
        self.started = time.monotonic() if started is None else started
        self.deadline = self.started + settings.deadline_seconds
        self.startup_deadline = min(self.deadline, self.started + MODEL_INIT_SECONDS)
        self.ready = False
        self.phase = "NEW"
        self.avatar = None if settings.initial_mode else settings.avatar
        self.selection_id = None
        self.prompt_hash = None
        self.admitted = False
        self.closed = asyncio.Event()
        self.model = None
        self.stream = None

    def health(self):
        remaining = self.deadline - time.monotonic()
        value = {"ready": self.ready and not self.closed.is_set() and remaining > 0
                 and (not self.settings.initial_mode or self.admitted or remaining >= MINIMUM_STREAM_SECONDS),
                 "protocol": PROTOCOL, "avatar": self.avatar,
                 "sourceRevision": pinned.SOURCE_REVISION, "modelRevision": pinned.MODEL_REVISION}
        if self.settings.initial_mode:
            value.update(selection="initial", phase="closed" if self.closed.is_set() else self.phase.lower(),
                         voice=self.settings.voice, promptHash=self.prompt_hash, selectionId=self.selection_id)
        return value

    def mark_warm(self):
        if self.phase != "NEW" or self.closed.is_set() or time.monotonic() >= self.startup_deadline:
            raise ProtocolError("Worker cannot publish warm state")
        self.phase = "WARM"

    def reserve_prime(self, selection_id: str, avatar: str) -> bool:
        # Synchronous event-loop admission, before any GPU await. No second
        # selection can enter the executor while the first is in flight.
        if (not self.settings.initial_mode or self.phase != "WARM" or self.closed.is_set()
                or not isinstance(selection_id, str) or not IDENTIFIER.fullmatch(selection_id)
                or not isinstance(avatar, str) or avatar not in PERSONAS or self.admitted
                or self.deadline - time.monotonic() < MINIMUM_STREAM_SECONDS + PRIME_SECONDS):
            return False
        self.phase, self.selection_id, self.avatar = "PRIMING", selection_id, avatar
        return True

    def publish_prime(self):
        if (self.phase != "PRIMING" or self.closed.is_set()
                or self.deadline - time.monotonic() < MINIMUM_STREAM_SECONDS):
            raise ProtocolError("Initial prime cannot publish readiness")
        self.prompt_hash = hashlib.sha256(PERSONAS[self.avatar].encode("utf8")).hexdigest()
        self.phase, self.ready = "PRIMED", True

    def close(self):
        self.ready = False
        self.phase = "CLOSED"
        self.closed.set()
        if self.model and callable(getattr(self.model, "invalidate", None)):
            self.model.invalidate()

    def admit(self) -> bool:
        if not self.health()["ready"] or self.admitted:
            return False
        self.admitted = True
        self.phase = "STREAMING"
        return True


async def serve(settings: Settings, model_factory=NativeModel, port=8080):
    from aiohttp import web, WSMsgType

    state = WorkerState(settings)
    executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="personaplex-owner")
    READY_FILE.unlink(missing_ok=True)
    WARM_FILE.unlink(missing_ok=True)

    def authenticated(request):
        return verified_lease_header(request.headers.get("X-Verified-User-Data"), settings.lease_epoch)

    async def health(request):
        if not authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return web.json_response(state.health())

    async def prime(request):
        if not authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        if request.content_type != "application/json":
            return web.json_response({"error": "Invalid initial selection"}, status=400)
        try:
            selection_id, avatar = parse_prime_request(await request.read())
        except (ProtocolError, web.HTTPRequestEntityTooLarge):
            return web.json_response({"error": "Invalid initial selection"}, status=400)
        if state.phase != "WARM" or state.closed.is_set():
            return web.json_response({"error": "Initial selection unavailable"}, status=409)
        if state.deadline - time.monotonic() < MINIMUM_STREAM_SECONDS + PRIME_SECONDS:
            return web.json_response({"error": "Worker lifetime is insufficient"}, status=503)
        if not state.reserve_prime(selection_id, avatar):
            return web.json_response({"error": "Initial selection unavailable"}, status=409)
        published = False
        watcher = None
        future = None
        try:
            transport = request.transport
            if transport is None or transport.is_closing():
                raise ConnectionError("Initial selection owner disconnected")

            async def disconnected():
                while not transport.is_closing() and not state.closed.is_set():
                    await asyncio.sleep(.025)

            watcher = asyncio.create_task(disconnected())
            future = asyncio.get_running_loop().run_in_executor(executor, state.model.prime_once, avatar)
            done, _ = await asyncio.wait({future, watcher}, return_when=asyncio.FIRST_COMPLETED,
                                         timeout=min(PRIME_SECONDS, max(.001, state.deadline - time.monotonic() - MINIMUM_STREAM_SECONDS)))
            if future not in done or watcher in done or transport.is_closing() or state.closed.is_set():
                raise TimeoutError("Initial selection was not completed")
            future.result()
            # Future initial-speech prelude processing belongs HERE on the same
            # executor, before public readiness. This prototype accepts no PCM
            # prelude endpoint, input text, arbitrary prompt or cache mutation.
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
            watcher = None
            if transport.is_closing() or state.closed.is_set():
                raise ConnectionError("Initial selection owner disconnected")
            state.publish_prime()
            READY_FILE.write_text(PROTOCOL + "\n", encoding="utf8")
            if isinstance(getattr(state.model, "startup", None), StartupProgress):
                state.model.startup.mark("ready")
            response = web.json_response(state.health())
            # Complete the private response while still inside the admitted
            # request's cancellation guard. A failed write closes this worker.
            await asyncio.wait_for(response.prepare(request), timeout=SEND_SECONDS)
            await asyncio.wait_for(response.write_eof(), timeout=SEND_SECONDS)
            published = True
            return response
        except Exception:
            return web.json_response({"error": "Initial selection failed"}, status=503)
        finally:
            if not published:
                state.close()
                READY_FILE.unlink(missing_ok=True)
                WARM_FILE.unlink(missing_ok=True)
                # Canceling this Future never terminates a running CUDA call;
                # invalidation above suppresses its late successful completion.
                if future is not None:
                    future.cancel()
            if watcher is not None:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)

    async def chat(request):
        if not authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)
        ws = web.WebSocketResponse(max_msg_size=FRAME_BYTES * MAX_BUFFER_FRAMES + 1, heartbeat=15)
        if not ws.can_prepare(request).ok:
            return web.json_response({"error": "WebSocket required"}, status=400)
        if not state.admit():
            return web.json_response({"error": "Worker unavailable"}, status=409)
        try:
            await ws.prepare(request)
            stream = Stream(ws, state.model, executor, state.deadline)
            state.stream = stream

            async def receive():
                async for message in ws:
                    if message.type == WSMsgType.BINARY:
                        stream.inbox.accept_binary(message.data)
                    elif message.type == WSMsgType.TEXT:
                        stream.inbox.accept_control(message.data)
                    elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                        break
                stream.close()

            tasks = [asyncio.create_task(receive()), asyncio.create_task(stream.run())]
            try:
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED,
                                                   timeout=max(.001, state.deadline - time.monotonic()))
                for task in done:
                    task.result()
                if not done:
                    raise TimeoutError("Worker deadline reached")
            except Exception:
                # All diagnostics are fixed; no upstream errors, paths or input
                # strings are reflected through the authenticated voice stream.
                try:
                    await stream.send({"type": "error", "code": "native_stream_ended"})
                except Exception:
                    pass
            finally:
                stream.close()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await ws.close(code=1000)
        finally:
            state.close()
            READY_FILE.unlink(missing_ok=True)
        return ws

    app = web.Application(client_max_size=MAX_CONTROL_BYTES)
    app.router.add_get("/healthz", health)
    app.router.add_get("/api/chat", chat)
    if settings.initial_mode:
        app.router.add_post("/api/prime", prime)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()
    try:
        state.model = await asyncio.wait_for(asyncio.get_running_loop().run_in_executor(executor, model_factory, settings),
                                             timeout=max(.001, state.startup_deadline - time.monotonic()))
        if time.monotonic() >= state.startup_deadline:
            raise TimeoutError("Model initialization deadline reached")
        if settings.initial_mode:
            state.mark_warm()
            WARM_FILE.write_text(PROTOCOL + "\n", encoding="utf8")
        else:
            state.phase, state.ready = "PRIMED", True
            READY_FILE.write_text(PROTOCOL + "\n", encoding="utf8")
            if isinstance(getattr(state.model, "startup", None), StartupProgress):
                state.model.startup.mark("ready")
        try:
            await asyncio.wait_for(state.closed.wait(), timeout=max(.001, state.deadline - time.monotonic()))
        except TimeoutError:
            pass
    finally:
        state.close()
        if state.stream:
            state.stream.close()
            try:
                await state.stream.ws.close(code=1000)
            except Exception:
                pass
        READY_FILE.unlink(missing_ok=True)
        WARM_FILE.unlink(missing_ok=True)
        await runner.cleanup()
        executor.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    try:
        asyncio.run(serve(Settings.from_env()))
        return 0
    except Exception:
        # The bounded Sandbox enforces its own hard deadline even if a GPU
        # operation cannot be canceled by Python. Never print arbitrary errors.
        print(json.dumps({"status": "failed", "code": "native_worker_unavailable"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
