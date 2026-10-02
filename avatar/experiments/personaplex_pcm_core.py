"""Isolated transport/scheduler experiment; this does not load or run PersonaPlex.

The caller supplies an already initialized, single-owner model step function.
Token schedules are explicit because speech timing has NOT been model-qualified.
No network, credentials, cloud SDK, torch, or application provider is imported.
"""

from collections import deque
from dataclasses import dataclass
from itertools import islice
import struct
from typing import Callable, Iterable

SAMPLE_RATE = 24_000
FRAME_SAMPLES = 1_920  # 24kHz / the pinned Mimi 12.5Hz frame rate.
FRAME_BYTES = FRAME_SAMPLES * 2
MAX_BUFFER_FRAMES = 6  # Fail stale input rather than replaying a large backlog.
MAX_PLAN_FRAMES = 256
MAX_PENDING_RESULTS = 4
MAX_SESSION_TASK_IDS = 1_024
OUTPUT_KIND = 0x11
OUTPUT_HEADER = struct.Struct("<BIQ")  # kind, presentation generation, sample index


class Pcm24Framer:
    """Accumulate continuous signed16LE mono PCM across arbitrary byte boundaries."""

    def __init__(self) -> None:
        self.pending = bytearray()
        self.sample_index = 0

    def push(self, payload: bytes) -> list[bytes]:
        if len(self.pending) + len(payload) > FRAME_BYTES * MAX_BUFFER_FRAMES:
            raise BufferError("Input backlog exceeds the experimental 480ms bound")
        self.pending.extend(payload)
        complete = len(self.pending) // FRAME_BYTES
        frames = [bytes(self.pending[n * FRAME_BYTES:(n + 1) * FRAME_BYTES])
                  for n in range(complete)]
        del self.pending[:complete * FRAME_BYTES]
        self.sample_index += complete * FRAME_SAMPLES
        return frames

    def finish(self) -> None:
        if self.pending:
            raise ValueError("Truncated PCM frame at end of stream")

    def discard(self) -> None:
        """Teardown discards a partial capture frame; it never creates fake samples."""
        self.pending.clear()


def pcm16_to_float(frame: bytes) -> tuple[float, ...]:
    if len(frame) != FRAME_BYTES:
        raise ValueError("Model input must contain exactly 1920 signed16LE samples")
    return tuple(value / 32768.0 for value in struct.unpack("<1920h", frame))


@dataclass(frozen=True)
class OutputPcm:
    generation: int
    sample_index: int
    pcm: bytes


def pack_output(generation: int, sample_index: int, pcm: bytes) -> bytes:
    """Versioned experimental framing, incompatible with stock Ogg-Opus kind1."""
    if not 0 <= generation <= 0xFFFFFFFF or not 0 <= sample_index <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("Invalid output clock/generation")
    if not pcm or len(pcm) % 2 or len(pcm) > FRAME_BYTES * MAX_BUFFER_FRAMES:
        raise ValueError("Output payload must contain bounded complete PCM16 samples")
    return OUTPUT_HEADER.pack(OUTPUT_KIND, generation, sample_index) + pcm


def unpack_output(packet: bytes) -> OutputPcm:
    if len(packet) <= OUTPUT_HEADER.size:
        raise ValueError("Missing output PCM")
    kind, generation, sample_index = OUTPUT_HEADER.unpack_from(packet)
    if kind != OUTPUT_KIND:
        raise ValueError("Unexpected experimental packet kind")
    pcm = packet[OUTPUT_HEADER.size:]
    # Reuse the encoder validation rather than accepting odd/truncated sample data.
    pack_output(generation, sample_index, pcm)
    return OutputPcm(generation, sample_index, pcm)


@dataclass(frozen=True)
class ResultPlan:
    task_id: str
    epoch: str
    tokens: tuple[int, ...]


class PublicResultQueue:
    """Server-owned candidate agent-text schedules, one token per native frame.

    Ordinary SentencePiece IDs plus explicit EPAD0/PAD3 are permitted. BOS/EOS
    are rejected: their use mid-session has not been qualified. This queue does
    not tokenize, infer pronunciation timing, perform bank reads, or grant trust
    to browser text. The authenticated backend must create each plan.
    """

    def __init__(self, epoch: str) -> None:
        if not epoch:
            raise ValueError("An account/session epoch is required")
        self.epoch = epoch
        self.generation = 0
        self.pending: deque[ResultPlan] = deque()
        self.seen: set[str] = set()
        self.active: ResultPlan | None = None
        self.position = 0
        self.closed = False
        self.user_was_active = False

    def admit(self, task_id: str, epoch: str, tokens: Iterable[int]) -> bool:
        if not isinstance(task_id, str) or not task_id or len(task_id) > 128:
            raise ValueError("Invalid task id")
        if self.closed or epoch != self.epoch or task_id in self.seen:
            return False
        if len(self.seen) >= MAX_SESSION_TASK_IDS:
            raise BufferError("Session task-id bound reached")
        if len(self.pending) + (self.active is not None) >= MAX_PENDING_RESULTS:
            raise BufferError("Public-result queue is full")
        plan = tuple(islice(tokens, MAX_PLAN_FRAMES + 1))
        if not 1 <= len(plan) <= MAX_PLAN_FRAMES:
            raise ValueError("Candidate plan must contain 1..256 native frames")
        if any(type(token) is not int or not 0 <= token < 32_000 or token in (1, 2)
               for token in plan):
            raise ValueError("Unsupported token or unqualified BOS/EOS")
        self.seen.add(task_id)
        self.pending.append(ResultPlan(task_id, epoch, plan))
        return True

    def interrupt(self) -> None:
        """Drop the rest of the active utterance, retaining unrelated pending reads.

        A driver must keep allow_speech false until user silence/explicit resume.
        This changes presentation generation, NOT the underlying model cache.
        Residual model speech after this point remains an unqualified behavior.
        """
        self.active = None
        self.position = 0
        self.generation += 1

    def cancel(self, task_id: str) -> None:
        self.pending = deque(plan for plan in self.pending if plan.task_id != task_id)
        if self.active is not None and self.active.task_id == task_id:
            self.interrupt()

    def next_token(self, *, user_active: bool, allow_speech: bool = True) -> int | None:
        if self.closed:
            return None
        if user_active and not self.user_was_active:
            # Free-generated output needs the same presentation invalidation as
            # forced speech, even when no result plan is currently active.
            self.interrupt()
        self.user_was_active = user_active
        if user_active or not allow_speech:
            if self.active is not None:
                self.interrupt()
            return None
        if self.active is None:
            if not self.pending:
                return None
            self.active = self.pending.popleft()
            self.position = 0
        token = self.active.tokens[self.position]
        self.position += 1
        if self.position == len(self.active.tokens):
            self.active = None
            self.position = 0
        return token

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.interrupt()
        self.pending.clear()


class ContinuousDriver:
    """Deterministic single-owner wiring, with the real model deliberately absent.

    Production step_frame would encode with Mimi, call LMGen.step with optional
    text_token, and decode. It must not reset streaming state between calls.
    """

    def __init__(self, results: PublicResultQueue,
                 step_frame: Callable[[tuple[float, ...], int | None], object]) -> None:
        self.results = results
        self.step_frame = step_frame
        self.framer = Pcm24Framer()
        self.frames = 0
        self.closed = False

    def feed(self, payload: bytes, *, user_active: bool = False,
             allow_speech: bool = True) -> list[object]:
        if self.closed:
            raise RuntimeError("Closed session cannot be resumed")
        output = []
        for frame in self.framer.push(payload):
            token = self.results.next_token(user_active=user_active, allow_speech=allow_speech)
            output.append(self.step_frame(pcm16_to_float(frame), token))
            self.frames += 1
        return output

    def close(self) -> None:
        self.closed = True
        self.results.close()
        self.framer.discard()
