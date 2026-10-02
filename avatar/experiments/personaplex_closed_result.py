"""Source-only by default: one closed, synthetic PersonaPlex reply qualification.

--plan reads no credentials/cache and dispatches nothing. --execute explicitly
spends one bounded GPU input using the existing private weight image. A separate
--verify-asr mode spends one transcription request only on this experiment's
completed, hashed synthetic output. No browser provider or banking path changes.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
import urllib.request
import wave

import personaplex_forced_result as prior
import personaplex_modal as pinned
from personaplex_browser import DEFAULT_CACHE, cache_reference
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, MAX_PLAN_FRAMES, Pcm24Framer, PublicResultQueue

EXPERIMENT = "closed_synthetic_result_pcm_v2"
PUBLIC_REPLY = "The payment amount is forty two dollars and seventeen cents. There is no open dispute. No action was taken."
TASK_ID = "synthetic-closed-result-2"
EPOCH = "synthetic-closed-result/session-2"
WORD_PAD_FRAMES = 4
SENTENCE_PAD_FRAMES = 10
PHONEME_TAIL_FRAMES = 16
MAX_OUTPUT_DELAY_FRAMES = 16
PRELUDE_FRAMES = prior.PRELUDE_FRAMES
READY_SILENCE_FRAMES = prior.READY_SILENCE_FRAMES
SETTLE_FRAMES = prior.SETTLE_FRAMES
CONTINUATION_FRAMES = prior.CONTINUATION_FRAMES
TAIL_FRAMES = prior.TAIL_FRAMES
MAX_CLOCK_FRAMES = PRELUDE_FRAMES + READY_SILENCE_FRAMES + MAX_PLAN_FRAMES + SETTLE_FRAMES + CONTINUATION_FRAMES + TAIL_FRAMES
WORKER_SECONDS = 360
SOURCE_MODULES = ("personaplex_closed_result", "personaplex_forced_result", "personaplex_pcm_core",
                  "personaplex_modal", "personaplex_browser", "personaplex_pcm_server", "modal_diagnostic")
WORK = Path("/tmp/personaplex-closed-result")
ROOT = Path(__file__).resolve().parent.parent
DIRECTORY = ROOT / ".local" / "personaplex-closed-result"
ASR_ENDPOINT = "https://openrouter.ai/api/v1/audio/transcriptions"
ASR_MODEL = "openai/whisper-large-v3"
ARTIFACT_NAMES = frozenset({"input.wav", "closed-result.wav", "gated-timeline.wav",
                            "private-native-all.wav", "private-discarded-continuation.wav",
                            "private-token-stream.json", "public-caption.json", "report.json"})


@dataclass(frozen=True)
class CandidatePlan:
    tokens: tuple[int, ...]
    words: tuple[dict, ...]
    reply_frames: int
    phoneme_tail_frames: int


def candidate_plan(encode_word) -> CandidatePlan:
    """Slower explicit schedule, not a model-qualified pronunciation planner."""
    tokens, words = [], []
    for word in PUBLIC_REPLY.split():
        lexical = list(encode_word(word))
        if not lexical or any(type(token) is not int or not 4 <= token < 32_000 for token in lexical):
            raise ValueError("The fixed synthetic reply contains an unsupported lexical token")
        start = len(tokens)
        pads = SENTENCE_PAD_FRAMES if word.endswith(".") else WORD_PAD_FRAMES
        tokens.extend(lexical + [prior.PAD_ID] * pads + [prior.END_PADDING_ID])
        words.append({"word": word, "lexical_tokens": lexical, "start_frame": start,
                      "end_frame_exclusive": len(tokens), "pad_frames": pads})
    reply_frames = len(tokens)
    # The final acoustic completion window is still forced text padding. No
    # freely generated lexical token is admitted to the public reply window.
    tokens.extend([prior.PAD_ID] * PHONEME_TAIL_FRAMES + [prior.END_PADDING_ID])
    if not 1 <= len(tokens) <= MAX_PLAN_FRAMES:
        raise ValueError("The closed candidate exceeds the 256-frame bound")
    return CandidatePlan(tuple(tokens), tuple(words), reply_frames, PHONEME_TAIL_FRAMES + 1)


def plan() -> dict:
    value = pinned.plan()
    value.update({
        "experiment": EXPERIMENT, "fixed_synthetic_reply": PUBLIC_REPLY,
        "credential": "Existing Modal profile only on --execute; no runtime HF credential or access check",
        "prerequisite": "An already built private cache with the exact pinned source/model revisions",
        "cache": "Existing private image reference is read only on --execute; no download/build fallback",
        "public_audio_seconds": 12,
        "clock": {"sample_rate": 24_000, "frame_samples": FRAME_SAMPLES,
                  "maximum_frames": MAX_CLOCK_FRAMES, "maximum_seconds": round(MAX_CLOCK_FRAMES * .08, 3)},
        "schedule": {"word_pad3_frames": WORD_PAD_FRAMES, "sentence_pad3_frames": SENTENCE_PAD_FRAMES,
                     "each_word_final_epad0": True, "forced_phoneme_tail_pad3_frames": PHONEME_TAIL_FRAMES,
                     "forced_tail_final_epad0": True, "maximum_output_delay_frames": MAX_OUTPUT_DELAY_FRAMES},
        "output_policy": "Only delay-aligned forced reply/tail audio and approved caption; all other output discarded",
        "after_reply": "Gate permanently closed while the same model/input/cache continue; later input cannot reopen it",
        "private_audit": "Discarded native continuation audio and token records stay in the ignored result directory",
        "banking_access": False, "production_enabled": False, "browser_provider_changed": False,
        "supported_tool_api": False, "pronunciation_verified": False,
        "model_hash_load_inference_timeout_seconds": WORKER_SECONDS,
        "browser_readiness_probe_used": False,
        "asr": "Separate explicit --verify-asr after completed synthetic output; no automatic request",
        "artifacts": sorted(ARTIFACT_NAMES),
    })
    return value


def build_timeline(public_pcm: bytes, candidate: CandidatePlan) -> tuple[list[str], bytes]:
    needed = (PRELUDE_FRAMES + CONTINUATION_FRAMES) * FRAME_BYTES
    if len(public_pcm) < needed or len(public_pcm) % 2:
        raise ValueError("The pinned public fixture must contain twelve seconds of complete PCM")
    phases = [("prelude", PRELUDE_FRAMES), ("ready_silence", READY_SILENCE_FRAMES),
              ("forced_reply", candidate.reply_frames), ("forced_phoneme_tail", candidate.phoneme_tail_frames),
              ("closed_settle", SETTLE_FRAMES), ("closed_next_input", CONTINUATION_FRAMES), ("closed_tail", TAIL_FRAMES)]
    labels = [label for label, count in phases for _ in range(count)]
    pcm = (public_pcm[:PRELUDE_FRAMES * FRAME_BYTES]
           + bytes((READY_SILENCE_FRAMES + len(candidate.tokens) + SETTLE_FRAMES) * FRAME_BYTES)
           + public_pcm[PRELUDE_FRAMES * FRAME_BYTES:needed] + bytes(TAIL_FRAMES * FRAME_BYTES))
    if len(pcm) != len(labels) * FRAME_BYTES or len(labels) > MAX_CLOCK_FRAMES:
        raise ValueError("The closed experiment violates its native clock bound")
    return labels, pcm


class ClosedOutputGate:
    """One immutable native-clock window; no user-activity or resume API."""

    def __init__(self, candidate: CandidatePlan, first_input_frame: int, output_delay_frames: int):
        if type(output_delay_frames) is not int or not 0 <= output_delay_frames <= MAX_OUTPUT_DELAY_FRAMES:
            raise ValueError("Unsupported model output delay")
        self.tokens = candidate.tokens
        self.first_output = first_input_frame + output_delay_frames
        self.end_output = self.first_output + len(candidate.tokens)
        self.last_frame = -1
        self.closed = False
        self.accepted = 0

    def consider(self, frame: int, model_text_id: int) -> bool:
        if type(frame) is not int or frame != self.last_frame + 1:
            self.closed = True
            raise ValueError("Noncontinuous public output clock")
        self.last_frame = frame
        if self.closed or frame < self.first_output:
            return False
        if frame >= self.end_output:
            self.closed = True
            return False
        if type(model_text_id) is not int or model_text_id != self.tokens[frame - self.first_output]:
            self.closed = True
            raise ValueError("A public output text token differs from its forced schedule")
        self.accepted += 1
        if frame + 1 == self.end_output:
            self.closed = True
        return True


@dataclass(frozen=True)
class TimelineResult:
    records: tuple[dict, ...]
    native_pcm: bytes
    gated_pcm: bytes
    closed_reply_pcm: bytes
    discarded_continuation_pcm: bytes
    first_output_frame: int
    end_output_frame: int


def run_timeline(labels: list[str], pcm: bytes, candidate: CandidatePlan, step_frame,
                 output_delay_frames: int) -> TimelineResult:
    if len(labels) > MAX_CLOCK_FRAMES or len(pcm) != len(labels) * FRAME_BYTES:
        raise ValueError("Malformed native input timeline")
    start = labels.index("forced_reply")
    gate = ClosedOutputGate(candidate, start, output_delay_frames)
    if gate.end_output > labels.index("closed_next_input"):
        raise ValueError("The approved output window overlaps subsequent public input")
    queue, framer = PublicResultQueue(EPOCH), Pcm24Framer()
    records, native, gated, reply, discarded = [], [], [], [], []
    admitted = False
    for offset in range(0, len(pcm), 4097):
        for raw_frame in framer.push(pcm[offset:offset + 4097]):
            index = len(records)
            if index == start:
                admitted = queue.admit(TASK_ID, EPOCH, candidate.tokens)
                if not admitted:
                    raise RuntimeError("The one synthetic reply was not admitted")
            forced = queue.next_token(user_active=False)
            result = dict(step_frame(raw_frame, forced))
            audio = result.pop("pcm")
            if not isinstance(audio, bytes) or len(audio) != FRAME_BYTES:
                raise ValueError("Model output must contain one complete native PCM frame")
            if result.get("continuous_cache_preserved") is not True:
                raise ValueError("Native streaming cache changed during qualification")
            allowed = gate.consider(index, result["model_text_id"])
            native.append(audio)
            gated.append(audio if allowed else bytes(FRAME_BYTES))
            if allowed:
                reply.append(audio)
            elif index >= gate.end_output:
                discarded.append(audio)
            records.append({**result, "frame": index, "phase": labels[index], "forced_input_text_id": forced,
                            "output_source_input_frame": index - output_delay_frames,
                            "public_output": allowed, "output_sample_index": index * FRAME_SAMPLES})
    framer.finish()
    if len(records) != len(labels) or not admitted or queue.active or queue.pending or not gate.closed or gate.accepted != len(candidate.tokens):
        raise RuntimeError("The closed continuous timeline did not finish exactly once")
    return TimelineResult(tuple(records), b"".join(native), b"".join(gated), b"".join(reply),
                          b"".join(discarded), gate.first_output, gate.end_output)


def run_worker() -> None:
    """Model setup uses the existing validated offline cache, never HF access."""
    from personaplex_pcm_server import NativeModel, Settings
    loading_started = time.perf_counter()
    model = NativeModel(Settings("moss", pinned.VOICE, "synthetic_closed_result_epoch_2", pinned.FUNCTION_SECONDS))
    loaded_seconds = time.perf_counter() - loading_started
    np, torch = model.np, model.torch
    if model.lm_gen.lm_model.delays[0] != 0:
        raise RuntimeError("The pinned text stream delay changed")
    delay = model.lm_gen.max_delay
    candidate = candidate_plan(model.tokenizer.encode)
    with wave.open(str(WORK / "public.wav"), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, 24_000, 2):
            raise ValueError("Invalid pinned public input")
        public = audio.readframes((PRELUDE_FRAMES + CONTINUATION_FRAMES) * FRAME_SAMPLES)
    labels, input_pcm = build_timeline(public, candidate)
    state, cache_pointer = model.stream_state, model.cache_pointer
    offset_start = state.offset

    def step_frame(raw: bytes, forced: int | None) -> dict:
        started = time.perf_counter()
        samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
        chunk = torch.from_numpy(samples).to("cuda")[None, None]
        codes = model.mimi.encode(chunk)
        _ = model.other_mimi.encode(chunk)
        if tuple(codes.shape) != (1, 8, 1):
            raise RuntimeError("Unexpected native user code frame")
        before = state.offset
        text = None if forced is None else torch.tensor([forced], dtype=torch.long, device="cuda")
        tokens = model.lm_gen.step(codes) if text is None else model.lm_gen.step(codes, text_token=text)
        if tokens is None:
            raise RuntimeError("The primed native model returned no frame")
        pcm = model.decode(model.mimi, model.other_mimi, model.lm_gen, tokens)
        torch.cuda.synchronize()
        preserved = (model.lm_gen._streaming_state is state and state.cache.data_ptr() == cache_pointer
                     and state.offset == before + 1 and model.mimi.is_streaming and model.other_mimi.is_streaming)
        if pcm.shape != (FRAME_SAMPLES,) or not np.isfinite(pcm).all() or not preserved:
            raise RuntimeError("Invalid continuous model frame")
        text_id = int(tokens[0, 0, 0].item())
        piece = "" if text_id in (0, 1, 2, 3) else model.tokenizer.id_to_piece(text_id).replace("▁", " ")
        return {"pcm": np.clip(np.rint(pcm * 32768), -32768, 32767).astype("<i2").tobytes(),
                "model_text_id": text_id, "model_text_piece": piece, "continuous_cache_preserved": preserved,
                "lm_offset_before": before, "lm_offset_after": state.offset,
                "frame_total_ms": round((time.perf_counter() - started) * 1000, 3)}

    with torch.no_grad():
        result = run_timeline(labels, input_pcm, candidate, step_frame, delay)
    waves = {"input.wav": input_pcm, "closed-result.wav": result.closed_reply_pcm,
             "gated-timeline.wav": result.gated_pcm, "private-native-all.wav": result.native_pcm,
             "private-discarded-continuation.wav": result.discarded_continuation_pcm}
    for name, pcm in waves.items():
        (WORK / name).write_bytes(prior.wav_bytes(pcm))
    (WORK / "private-token-stream.json").write_text(json.dumps(result.records, ensure_ascii=False), encoding="utf8")
    (WORK / "public-caption.json").write_text(json.dumps({"text": PUBLIC_REPLY, "source": "fixed_synthetic_reply",
                                                          "forced_output_ids_match": True, "is_asr_proof": False}), encoding="utf8")
    timings = [record["frame_total_ms"] for record in result.records]
    after = result.records[result.end_output_frame:]
    report = {"status": "completed", "experiment": EXPERIMENT,
              "source_revision": pinned.SOURCE_REVISION, "model_revision": pinned.MODEL_REVISION,
              "synthetic_public_reply": PUBLIC_REPLY, "candidate_words": candidate.words,
              "candidate_frame_tokens": candidate.tokens, "candidate_frames": len(candidate.tokens),
              "forced_phoneme_tail_frames": candidate.phoneme_tail_frames, "model_output_delay_frames": delay,
              "public_start_output_frame": result.first_output_frame, "public_end_output_frame_exclusive": result.end_output_frame,
              "public_audio_frames": len(result.closed_reply_pcm) // FRAME_BYTES,
              "public_audio_sha256": hashlib.sha256((WORK / "closed-result.wav").read_bytes()).hexdigest(),
              "forced_output_ids_match": True, "gate_permanently_closed": True,
              "post_reply_model_frames": len(after), "post_reply_public_audio_frames": sum(r["public_output"] for r in after),
              "post_reply_public_caption_tokens": 0,
              "private_discarded_lexical_tokens": sum(r["model_text_id"] not in (0, 1, 2, 3) for r in after),
              "next_input_frames": CONTINUATION_FRAMES,
              "next_input_nonzero_frames": sum(any(input_pcm[i * FRAME_BYTES:(i + 1) * FRAME_BYTES])
                                               for i, label in enumerate(labels) if label == "closed_next_input"),
              "continuous_lm_cache_preserved": all(r["continuous_cache_preserved"] for r in result.records),
              "lm_offset_start": offset_start, "lm_offset_end": state.offset,
              "load_prompt_seconds": round(loaded_seconds, 3),
              "clock_frames": len(labels), "clock_seconds": round(len(labels) * .08, 3), "wall_clock_paced": False,
              "frame_timings_ms": {"mean": round(float(np.mean(timings)), 3), "p95": round(float(np.percentile(timings, 95)), 3),
                                   "maximum": round(max(timings), 3), "over80ms": sum(t > 80 for t in timings)},
              "gpu": {"name": torch.cuda.get_device_name(0), "peak_allocated_bytes": torch.cuda.max_memory_allocated(0)},
              "banking_access": False, "runtime_downloads": False, "runtime_hf_credential": False,
              "pronunciation_verified": False, "tool_understanding_verified": False,
              "browser_barge_in_verified": False, "production_enabled": False}
    (WORK / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf8")


def gpu_closed_result() -> dict:
    stage = "offline_cache"
    try:
        if os.environ.get("HF_TOKEN"):
            raise RuntimeError("Runtime HF credentials must not be mounted")
        WORK.mkdir(exist_ok=False)
        stage = "public_audio"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                        "/opt/personaplex/assets/test/input_assistant.wav", "-t", "12", "-ar", "24000", "-ac", "1",
                        "-c:a", "pcm_s16le", str(WORK / "public.wav")], capture_output=True, check=True, timeout=20)
        stage = "inference"
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"], cwd="/opt/personaplex",
                                 capture_output=True, timeout=WORKER_SECONDS,
                                 env={**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"})
        if process.returncode:
            raise RuntimeError("The bounded closed-result worker failed")
        stage = "artifacts"
        artifacts = {}
        for name in ARTIFACT_NAMES:
            value = (WORK / name).read_bytes()
            if len(value) > 3 * 1024 * 1024:
                raise ValueError("Oversized bounded synthetic artifact")
            if name.endswith(".wav"):
                prior.pcm_profile(value)
            else:
                json.loads(value)
            artifacts[name] = value
        return {"status": "completed", "artifacts": artifacts}
    except Exception as error:
        return {"status": "failed", **pinned.diagnostic(error, stage), "reason": "The closed synthetic experiment failed."}


def build_app(reference: str):
    import modal
    if gpu_closed_result.__module__ != "personaplex_closed_result":
        raise RuntimeError("Canonical source module identity is required")
    image = modal.Image.from_id(reference).add_local_python_source(*SOURCE_MODULES, copy=True)
    app = modal.App("elsewhere-personaplex-closed-result-qualification")
    function = app.function(image=image, gpu=pinned.GPU, cpu=(2, pinned.CPU_LIMIT),
                            memory=(32768, pinned.MEMORY_LIMIT_GIB * 1024), timeout=pinned.FUNCTION_SECONDS,
                            startup_timeout=pinned.STARTUP_SECONDS, max_containers=1, min_containers=0,
                            buffer_containers=0, scaledown_window=2, retries=0, single_use_containers=True,
                            serialized=False, include_source=True)(gpu_closed_result)
    return app, function


def private_bytes(path: Path, payload: bytes) -> None:
    """All audition/audit artifacts are private before their first byte is written."""
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        if os.name == "nt":
            domain, user = os.environ.get("USERDOMAIN", ""), os.environ.get("USERNAME", "")
            if not user:
                raise ValueError("The private output owner is unavailable")
            principal = f"{domain}\\{user}" if domain else user
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", principal + ":(F)"],
                           capture_output=True, check=True, timeout=10)
        with os.fdopen(handle, "wb") as output:
            handle = None
            output.write(payload)
    finally:
        if handle is not None:
            os.close(handle)


def save_artifacts(result: dict) -> Path:
    if result.get("status") != "completed" or set(result.get("artifacts", {})) != ARTIFACT_NAMES:
        raise ValueError("Unexpected closed experiment artifacts")
    destination = DIRECTORY / (time.strftime("%Y%m%d-%H%M%S") + "-" + str(time.time_ns()))
    destination.mkdir(parents=True, exist_ok=False)
    for name, value in result["artifacts"].items():
        if not isinstance(value, bytes) or len(value) > 3 * 1024 * 1024:
            raise ValueError("Oversized synthetic output")
        if name.endswith(".wav"):
            prior.pcm_profile(value)
        else:
            json.loads(value)
        private_bytes(destination / name, value)
    return destination


def validated_asr_audio(directory: Path) -> bytes:
    directory = Path(directory)
    if directory.is_symlink() or not directory.resolve().is_relative_to(DIRECTORY.resolve()):
        raise ValueError("ASR accepts only this experiment's ignored synthetic output")
    report_path, audio_path = directory / "report.json", directory / "closed-result.wav"
    if any(path.is_symlink() or not path.is_file() or path.stat().st_size > 3 * 1024 * 1024 for path in (report_path, audio_path)):
        raise ValueError("A completed bounded synthetic output is required")
    report = json.loads(report_path.read_text(encoding="utf8"))
    required = {"status": "completed", "experiment": EXPERIMENT, "synthetic_public_reply": PUBLIC_REPLY,
                "source_revision": pinned.SOURCE_REVISION, "model_revision": pinned.MODEL_REVISION,
                "forced_output_ids_match": True, "gate_permanently_closed": True,
                "continuous_lm_cache_preserved": True, "post_reply_public_audio_frames": 0,
                "post_reply_public_caption_tokens": 0, "banking_access": False, "production_enabled": False}
    if not isinstance(report, dict) or any(type(report.get(key)) is not type(value) or report.get(key) != value
                                          for key, value in required.items()):
        raise ValueError("The synthetic model/gate evidence is incomplete")
    audio = audio_path.read_bytes()
    if hashlib.sha256(audio).hexdigest() != report.get("public_audio_sha256"):
        raise ValueError("The approved synthetic audio hash changed")
    profile = prior.pcm_profile(audio)
    frames = report.get("public_audio_frames")
    if type(frames) is not int or not 1 <= frames <= MAX_PLAN_FRAMES or abs(profile["seconds"] - frames * .08) > .001:
        raise ValueError("The approved synthetic audio duration changed")
    return audio


def existing_openrouter_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        path = ROOT / "openrouter.env"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32_768:
            raise ValueError("An existing OpenRouter credential is required for the explicit ASR check")
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            found = re.fullmatch(r"\s*OPENROUTER_API_KEY\s*=\s*(.*?)\s*", line)
            if found:
                key = found.group(1)
                if len(key) >= 2 and key[0] == key[-1] and key[0] in "\"'":
                    key = key[1:-1]
                break
    if not 16 <= len(key) <= 8192 or any(char.isspace() for char in key):
        raise ValueError("An existing valid OpenRouter credential is required")
    return key


AMOUNT = re.compile(r"\$\s*42[.,]17\b|\b42[.,]17\s*(?:dollars?|usd)?\b|\b(?:forty[\s-]+two|42)\s+dollars?\s+and\s+(?:seventeen|17)\s+cents?\b", re.I)


def asr_verdict(text: str) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 8000:
        raise ValueError("Invalid bounded synthetic transcription")
    def canonical(value):
        value = AMOUNT.sub("forty two dollars and seventeen cents", value)
        return " ".join(re.sub(r"[^a-z0-9]+", " ", unicodedata.normalize("NFKD", value).lower()).split())
    normalized = canonical(text)
    exact = normalized == canonical(PUBLIC_REPLY)
    return {"status": "synthetic_asr_passed" if exact else "synthetic_asr_failed",
            "amount_preserved": bool(AMOUNT.search(text)), "no_open_dispute_preserved": "no open dispute" in normalized,
            "no_action_was_taken_preserved": "no action was taken" in normalized,
            "exact_propositions_without_extra_text": exact, "independent_asr_observation": True,
            "human_listening_verified": False, "production_bank_narration_enabled": False}


def verify_asr(directory: Path) -> dict:
    audio = validated_asr_audio(directory)  # Before even reading the provider key.
    receipt_path = Path(directory) / "private-asr.json"
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError("This synthetic output already has its independent ASR receipt")
    key = existing_openrouter_key()
    body = json.dumps({"model": ASR_MODEL, "input_audio": {"data": base64.b64encode(audio).decode("ascii"), "format": "wav"},
                       "response_format": "json", "temperature": 0, "language": "en"}).encode("utf8")
    request = urllib.request.Request(ASR_ENDPOINT, data=body, method="POST",
                                     headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"})
    with urllib.request.build_opener(pinned.NoRedirect).open(request, timeout=45) as response:
        value = response.read(65_537)
        if response.status != 200 or len(value) > 65_536:
            raise ValueError("The independent synthetic ASR check failed")
    text = json.loads(value).get("text")
    verdict = asr_verdict(text)
    private_bytes(receipt_path, json.dumps({"model": ASR_MODEL, "transcript": text, **verdict}, indent=2).encode("utf8"))
    return verdict


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true", help="Spend one bounded GPU input using the existing private cache")
    mode.add_argument("--verify-asr", type=Path, metavar="RESULT_DIRECTORY", help="Spend one ASR request on completed synthetic output")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cache-file", type=Path, default=DEFAULT_CACHE)
    args = parser.parse_args(argv)
    if args.worker:
        if os.environ.get("HF_HUB_OFFLINE") != "1" or not (WORK / "public.wav").is_file():
            parser.error("Worker requires the prepared offline container and fixed public fixture")
        run_worker()
        return 0
    if not args.execute and not args.verify_asr:
        print(json.dumps(plan(), indent=2))
        return 0
    stage = "synthetic_asr" if args.verify_asr else "cached_image_reference"
    try:
        if args.verify_asr:
            verdict = verify_asr(args.verify_asr)
            print(json.dumps(verdict))
            return 0 if verdict["exact_propositions_without_extra_text"] else 1
        reference = cache_reference(args.cache_file)
        stage = "app_definition"
        app, function = build_app(reference)
        stage = "bounded_gpu_input"
        with app.run(detach=False):
            job = function.spawn()
            try:
                result = job.get(timeout=pinned.FUNCTION_SECONDS + pinned.STARTUP_SECONDS + 15)
            finally:
                try:
                    job.cancel(terminate_containers=True)
                except Exception:
                    pass
        if result.get("status") != "completed":
            print(json.dumps(result))
            return 1
        stage = "private_output"
        destination = save_artifacts(result)
        print(json.dumps({"status": "completed", "output_directory": str(destination), "persistent_service": False,
                          "pronunciation_verified": False, "production_enabled": False, "termination_verification_required": True}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", **pinned.diagnostic(error, stage), "reason": "The closed synthetic qualification failed."}))
        return 1


if __name__ == "__main__":
    from importlib import import_module
    raise SystemExit(import_module("personaplex_closed_result").main())
