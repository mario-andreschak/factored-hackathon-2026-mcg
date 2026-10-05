"""Prepared-only by default: bounded PersonaPlex forced-public-result audition.

--plan never reads credentials, imports Modal/torch, or accesses the network.
--execute explicitly spends GPU compute; no execution was part of preparation.
Only the pinned public NVIDIA fixture and fixed synthetic result are accepted.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

import personaplex_modal as base
from personaplex_pcm_core import FRAME_BYTES, FRAME_SAMPLES, MAX_PLAN_FRAMES, Pcm24Framer, PublicResultQueue

SAMPLE_RATE = 24_000
SEED = 42_424_242
PUBLIC_REPLY = "Mira Chen, the payment of forty two dollars and seventeen cents has no open dispute. No action was taken."
TASK_ID = "synthetic-no-dispute-1"
EPOCH = "synthetic-account/session-1"
PRELUDE_FRAMES = 50  # Four seconds of the public fixture.
READY_SILENCE_FRAMES = 25
SETTLE_FRAMES = 25
CONTINUATION_FRAMES = 100  # The next eight seconds of ordinary public user audio.
TAIL_FRAMES = 50
WORD_PAD_FRAMES = 2
SENTENCE_PAD_FRAMES = 6
PAD_ID = 3
END_PADDING_ID = 0
WORK = Path("/tmp/personaplex-forced-result")
MAX_CLOCK_FRAMES = PRELUDE_FRAMES + READY_SILENCE_FRAMES + MAX_PLAN_FRAMES + SETTLE_FRAMES + CONTINUATION_FRAMES + TAIL_FRAMES
MAX_CLOCK_SECONDS = MAX_CLOCK_FRAMES * FRAME_SAMPLES / SAMPLE_RATE


@dataclass(frozen=True)
class CandidatePlan:
    tokens: tuple[int, ...]
    words: tuple[dict, ...]


def candidate_plan(encode_word) -> CandidatePlan:
    """Explicit experimental schedule, not a qualified pronunciation planner."""
    schedule = []
    words = []
    for word in PUBLIC_REPLY.split():
        lexical = list(encode_word(word))
        if not lexical or any(type(token) is not int or not 4 <= token < 32_000 for token in lexical):
            raise ValueError("Fixed reply contains an unsupported lexical token")
        start = len(schedule)
        pads = SENTENCE_PAD_FRAMES if word.endswith(".") else WORD_PAD_FRAMES
        schedule.extend(lexical)
        schedule.extend([PAD_ID] * pads)
        schedule.append(END_PADDING_ID)
        words.append({"word": word, "lexical_tokens": lexical, "start_frame": start,
                      "end_frame_exclusive": len(schedule), "pad_frames": pads,
                      "end_padding_id": END_PADDING_ID})
    if not 1 <= len(schedule) <= MAX_PLAN_FRAMES:
        raise ValueError("Fixed candidate plan exceeds the 256-frame experiment bound")
    return CandidatePlan(tuple(schedule), tuple(words))


def plan() -> dict:
    inherited = base.plan()
    return {
        **inherited,
        "status": "prepared_not_dispatched", "experiment": "forced_public_result_pcm_v1",
        "fixed_synthetic_reply": PUBLIC_REPLY, "voice": base.VOICE, "seed": SEED,
        "public_audio_seconds": 12,
        "input": "pinned NVIDIA public input_assistant.wav only; first12s PCM24k mono",
        "clock": {"sample_rate": SAMPLE_RATE, "frame_samples": FRAME_SAMPLES,
                  "max_frames": MAX_CLOCK_FRAMES, "max_seconds": MAX_CLOCK_SECONDS},
        "phases": ["4s public prelude", "2s silence", "bounded forced reply",
                   "2s free-generation settling", "8s ordinary public continuation", "4s free-generation tail"],
        "candidate_schedule": {"lexical": "SentencePiece each fixed word", "ordinary_word_pad3_frames": WORD_PAD_FRAMES,
                               "sentence_end_pad3_frames": SENTENCE_PAD_FRAMES, "each_word_final_epad0": True},
        "streaming_cache": "One continuous LMGen/Mimi session after initial prompt; no per-result reset",
        "banking_access": False, "browser_provider_changed": False,
        "semantics_note": "Continuation fixture is ordinary user audio, not a question about this synthetic result. Token equality does not prove spoken pronunciation or tool understanding.",
        "artifacts": ["input.wav", "response.wav", "forced-result.wav", "continuation.wav", "token-stream.json", "report.json"],
    }


def pcm_profile(value: bytes) -> dict:
    if len(value) > 3 * 1024 * 1024:
        raise ValueError("Oversized experiment audio")
    with wave.open(io.BytesIO(value), "rb") as audio:
        seconds = audio.getnframes() / audio.getframerate()
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, SAMPLE_RATE, 2):
            raise ValueError("Unexpected PCM24k mono16 profile")
        if not 0 < seconds <= MAX_CLOCK_SECONDS + 0.08:
            raise ValueError("Unexpected bounded audio duration")
        return {"seconds": round(seconds, 3), "sample_rate": SAMPLE_RATE,
                "channels": 1, "sample_width_bytes": 2, "bytes": len(value)}


def wav_bytes(pcm: bytes) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(SAMPLE_RATE)
        audio.writeframes(pcm)
    return output.getvalue()


def build_timeline(public_pcm: bytes, candidate: CandidatePlan) -> tuple[list[str], bytes]:
    required = (PRELUDE_FRAMES + CONTINUATION_FRAMES) * FRAME_BYTES
    if len(public_pcm) < required or len(public_pcm) % 2:
        raise ValueError("Pinned public audio is shorter than12s or has a partial sample")
    phases = [("prelude", PRELUDE_FRAMES), ("ready_silence", READY_SILENCE_FRAMES),
              ("forced_public_reply", len(candidate.tokens)), ("settle", SETTLE_FRAMES),
              ("continuation", CONTINUATION_FRAMES), ("tail", TAIL_FRAMES)]
    labels = [label for label, count in phases for _ in range(count)]
    prelude = public_pcm[:PRELUDE_FRAMES * FRAME_BYTES]
    continuation = public_pcm[PRELUDE_FRAMES * FRAME_BYTES:required]
    pcm = (prelude + bytes((READY_SILENCE_FRAMES + len(candidate.tokens) + SETTLE_FRAMES) * FRAME_BYTES)
           + continuation + bytes(TAIL_FRAMES * FRAME_BYTES))
    if len(pcm) != len(labels) * FRAME_BYTES or len(labels) > MAX_CLOCK_FRAMES:
        raise ValueError("Input timeline violates the native clock bound")
    return labels, pcm


def run_timeline(labels: list[str], pcm: bytes, candidate: CandidatePlan, step_frame) -> list[dict]:
    """Same object/callback for every phase; intentionally no reset/prompt API."""
    queue = PublicResultQueue(EPOCH)
    framer = Pcm24Framer()
    records = []
    admitted = False
    # Awkward byte partitions deliberately exercise the rawPCM accumulation path.
    for offset in range(0, len(pcm), 4097):
        for raw_frame in framer.push(pcm[offset:offset + 4097]):
            index = len(records)
            label = labels[index]
            if label == "forced_public_reply" and not admitted:
                if not queue.admit(TASK_ID, EPOCH, candidate.tokens):
                    raise RuntimeError("Fixed public result was not admitted once")
                admitted = True
            forced = queue.next_token(user_active=False)
            result = step_frame(raw_frame, forced)
            records.append({"frame": index, "phase": label, "forced_text_id": forced, **result})
    framer.finish()
    if len(records) != len(labels) or not admitted or queue.active or queue.pending:
        raise RuntimeError("Native timeline or public-result consumption is incomplete")
    return records


def exact_subsequence(stream: list[int], expected: tuple[int, ...]) -> int | None:
    target = list(expected)
    for index in range(len(stream) - len(target) + 1):
        if stream[index:index + len(target)] == target:
            return index
    return None


def run_worker() -> None:
    """Real-model worker; called only inside the explicit prepared Modal runner."""
    import numpy as np
    import sentencepiece
    import torch
    from moshi.models import LMGen, loaders
    from moshi.offline import decode_tokens_to_pcm, seed_all, warmup, wrap_with_system_tags

    manifest = json.loads((WORK / "assets.json").read_text())
    if set(manifest) != set(base.MODEL_FILES):
        raise ValueError("Unexpected pinned asset manifest")
    seed_all(SEED)
    loading_started = time.perf_counter()
    device = "cuda"
    mimi = loaders.get_mimi(manifest["tokenizer-e351c8d8-checkpoint125.safetensors"], device)
    other_mimi = loaders.get_mimi(manifest["tokenizer-e351c8d8-checkpoint125.safetensors"], device)
    tokenizer = sentencepiece.SentencePieceProcessor(manifest["tokenizer_spm_32k_3.model"])
    lm = loaders.get_moshi_lm(manifest["model.safetensors"], device=device)
    lm.eval()
    if mimi.sample_rate != SAMPLE_RATE or int(mimi.sample_rate / mimi.frame_rate) != FRAME_SAMPLES:
        raise RuntimeError("Pinned model no longer matches the PCM24k clock")
    lm_gen = LMGen(lm, audio_silence_frame_cnt=int(0.5 * mimi.frame_rate), sample_rate=SAMPLE_RATE,
                   device=device, frame_rate=mimi.frame_rate, save_voice_prompt_embeddings=False,
                   use_sampling=True, temp=0.8, temp_text=0.7, top_k=250, top_k_text=25)
    mimi.streaming_forever(1)
    other_mimi.streaming_forever(1)
    lm_gen.streaming_forever(1)
    warmup(mimi, other_mimi, lm_gen, device, FRAME_SAMPLES)
    lm_gen.load_voice_prompt_embeddings(str(WORK / "voices" / base.VOICE))
    lm_gen.text_prompt_tokens = tokenizer.encode(wrap_with_system_tags(base.PROMPT))
    # All resets precede the one continuous experiment session, matching offline.py.
    mimi.reset_streaming()
    other_mimi.reset_streaming()
    lm_gen.reset_streaming()
    lm_gen.step_system_prompts(mimi)
    mimi.reset_streaming()
    torch.cuda.synchronize()
    loaded_seconds = time.perf_counter() - loading_started
    candidate = candidate_plan(tokenizer.encode)
    with wave.open(str(WORK / "public.wav"), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getsampwidth()) != (1, SAMPLE_RATE, 2):
            raise ValueError("Invalid fixed public input")
        public_pcm = audio.readframes((PRELUDE_FRAMES + CONTINUATION_FRAMES) * FRAME_SAMPLES)
    labels, input_pcm = build_timeline(public_pcm, candidate)
    (WORK / "input.wav").write_bytes(wav_bytes(input_pcm))
    stream_state = lm_gen._streaming_state
    cache_pointer = stream_state.cache.data_ptr()
    offset_start = stream_state.offset
    decoded = []
    cache_preserved = True

    def step_frame(raw_frame: bytes, forced: int | None) -> dict:
        nonlocal cache_preserved
        frame_started = time.perf_counter()
        samples = np.frombuffer(raw_frame, dtype="<i2").astype(np.float32) / 32768.0
        chunk = torch.from_numpy(samples).to(device)[None, None]
        torch.cuda.synchronize()
        encode_started = time.perf_counter()
        codes = mimi.encode(chunk)
        _ = other_mimi.encode(chunk)
        torch.cuda.synchronize()
        encoded_ms = (time.perf_counter() - encode_started) * 1000
        if tuple(codes.shape) != (1, 8, 1):
            raise RuntimeError("Expected one native user code frame per80ms input")
        offset_before = stream_state.offset
        forced_tensor = None if forced is None else torch.tensor([forced], dtype=torch.long, device=device)
        step_started = time.perf_counter()
        if forced is None:
            tokens = lm_gen.step(codes)
        else:
            # Force only agent text. Agent audio remains sampled, user audio continuous.
            tokens = lm_gen.step(codes, text_token=forced_tensor)
        torch.cuda.synchronize()
        step_ms = (time.perf_counter() - step_started) * 1000
        if tokens is None:
            raise RuntimeError("The prompt-primed model returned no agent frame")
        decode_started = time.perf_counter()
        pcm = decode_tokens_to_pcm(mimi, other_mimi, lm_gen, tokens)
        torch.cuda.synchronize()
        decode_ms = (time.perf_counter() - decode_started) * 1000
        if pcm.shape != (FRAME_SAMPLES,) or not np.isfinite(pcm).all():
            raise RuntimeError("Unexpected decoded native PCM frame")
        decoded.append(np.clip(pcm * 32768, -32768, 32767).astype("<i2").tobytes())
        preserved = (lm_gen._streaming_state is stream_state and stream_state.cache.data_ptr() == cache_pointer
                     and stream_state.offset == offset_before + 1 and mimi.is_streaming and other_mimi.is_streaming)
        cache_preserved = cache_preserved and preserved
        if not preserved:
            raise RuntimeError("Continuous streaming state changed unexpectedly")
        output_id = int(tokens[0, 0, 0].item())
        output_piece = {0: "[EPAD]", 1: "[BOS]", 2: "[EOS]", 3: "[PAD]"}.get(output_id)
        if output_piece is None:
            output_piece = tokenizer.id_to_piece(output_id).replace("▁", " ")
        return {"model_text_id": output_id, "model_text_piece": output_piece,
                "lm_offset_before": offset_before, "lm_offset_after": stream_state.offset,
                "output_sample_index": (len(decoded) - 1) * FRAME_SAMPLES,
                "encode_ms": round(encoded_ms, 3), "step_ms": round(step_ms, 3),
                "decode_ms": round(decode_ms, 3), "frame_total_ms": round((time.perf_counter() - frame_started) * 1000, 3),
                "continuous_cache_preserved": preserved}

    with torch.no_grad():
        records = run_timeline(labels, input_pcm, candidate, step_frame)
    output_pcm = b"".join(decoded)
    (WORK / "response.wav").write_bytes(wav_bytes(output_pcm))
    forced_start = labels.index("forced_public_reply")
    continuation_start = labels.index("continuation")
    forced_end = continuation_start
    (WORK / "forced-result.wav").write_bytes(wav_bytes(output_pcm[forced_start * FRAME_BYTES:forced_end * FRAME_BYTES]))
    (WORK / "continuation.wav").write_bytes(wav_bytes(output_pcm[continuation_start * FRAME_BYTES:]))
    (WORK / "token-stream.json").write_text(json.dumps(records, ensure_ascii=False, indent=2))
    clock_seconds = len(labels) * FRAME_SAMPLES / SAMPLE_RATE
    frame_times = [record["frame_total_ms"] for record in records]
    match = exact_subsequence([record["model_text_id"] for record in records], candidate.tokens)
    readable_text = "".join(record["model_text_piece"] for record in records if record["model_text_id"] not in (0, 1, 2, 3))
    report = {"status": "completed", "experiment": "forced_public_result_pcm_v1",
              "source_revision": base.SOURCE_REVISION, "model_revision": base.MODEL_REVISION,
              "synthetic_public_reply": PUBLIC_REPLY, "candidate_words": list(candidate.words),
              "candidate_frame_tokens": list(candidate.tokens), "candidate_frames": len(candidate.tokens),
              "forced_start_frame": forced_start, "continuation_start_frame": continuation_start,
              "forced_ids_found_contiguously_at_output_frame": match,
              "forced_ids_match": match is not None, "continuous_lm_cache_preserved": cache_preserved,
              "lm_offset_start": offset_start, "lm_offset_end": stream_state.offset,
              "clock_frames": len(labels), "clock_seconds": round(clock_seconds, 3),
              "post_result_free_generation_frames": len(labels) - (forced_start + len(candidate.tokens)),
              "model_text_stream": readable_text, "model_text_is_asr_proof": False,
              "load_prompt_seconds": round(loaded_seconds, 3),
              "frame_timings_ms": {"mean": round(float(np.mean(frame_times)), 3),
                                   "p50": round(float(np.percentile(frame_times, 50)), 3),
                                   "p95": round(float(np.percentile(frame_times, 95)), 3),
                                   "maximum": round(max(frame_times), 3),
                                   "over80ms": sum(value > 80 for value in frame_times)},
              "instrumented_compute_real_time_factor": round(sum(frame_times) / 1000 / clock_seconds, 4),
              "wall_clock_paced": False, "gpu": {"name": torch.cuda.get_device_name(0),
                                                       "peak_allocated_bytes": torch.cuda.max_memory_allocated(0)},
              "banking_access": False, "tool_understanding_verified": False,
              "pronunciation_verified": False, "browser_barge_in_verified": False}
    (WORK / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))


def gpu_forced_result() -> dict:
    from huggingface_hub import hf_hub_download
    started = time.monotonic()
    stage = "weights"
    try:
        if not os.environ.get("HF_TOKEN"):
            raise RuntimeError("HF_TOKEN was not injected")
        assets = {filename: hf_hub_download(base.MODEL_REPO, filename, revision=base.MODEL_REVISION,
                                           token=os.environ["HF_TOKEN"]) for filename in base.MODEL_FILES}
        downloaded = time.monotonic()
        WORK.mkdir(exist_ok=False)
        (WORK / "voices").mkdir()
        base.extract_voice(Path(assets["voices.tgz"]), WORK / "voices" / base.VOICE)
        (WORK / "assets.json").write_text(json.dumps(assets))
        stage = "public_audio"
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i",
                        "/opt/personaplex/assets/test/input_assistant.wav", "-t", "12", "-ar", "24000",
                        "-ac", "1", "-c:a", "pcm_s16le", str(WORK / "public.wav")],
                       check=True, capture_output=True, timeout=20)
        stage = "inference"
        # Use the mounted file's absolute path: a child interpreter must not rely
        # on Modal's dynamic parent sys.path entries for finding source modules.
        process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--worker"],
                                 cwd="/opt/personaplex", capture_output=True, timeout=360,
                                 env={**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_PROGRESS_BARS": "1"})
        if process.returncode:
            return {"status": "failed", **base.diagnostic(RuntimeError(process.stderr.decode("utf8", errors="replace")), stage),
                    "reason": "The prepared continuous forced-result worker failed."}
        stage = "output"
        files = {}
        for name in ("input.wav", "response.wav", "forced-result.wav", "continuation.wav"):
            value = (WORK / name).read_bytes()
            pcm_profile(value)
            files[name] = value
        for name in ("token-stream.json", "report.json"):
            value = (WORK / name).read_text()
            if len(value) > 2 * 1024 * 1024:
                raise ValueError("Oversized bounded result metadata")
            json.loads(value)
            files[name] = value.encode("utf8")
        report = json.loads(files["report.json"])
        report["download_seconds"] = round(downloaded - started, 3)
        report["load_and_inference_seconds"] = round(time.monotonic() - downloaded, 3)
        files["report.json"] = json.dumps(report, indent=2).encode("utf8")
        return {"status": "completed", "artifacts": files}
    except Exception as error:
        return {"status": "failed", **base.diagnostic(error, stage),
                "reason": "The bounded synthetic experiment could not complete."}


def build_app(token: str):
    import modal
    if gpu_forced_result.__module__ != "personaplex_forced_result":
        raise RuntimeError("Canonical source-backed module identity is required")
    image = base.build_image().add_local_python_source("personaplex_forced_result").add_local_python_source("personaplex_pcm_core")
    app = modal.App("elsewhere-personaplex-forced-result-audition")
    function = app.function(image=image, gpu=base.GPU, cpu=(2, base.CPU_LIMIT),
                            memory=(32768, base.MEMORY_LIMIT_GIB * 1024), timeout=base.FUNCTION_SECONDS,
                            startup_timeout=base.STARTUP_SECONDS, max_containers=1, min_containers=0,
                            buffer_containers=0, scaledown_window=2, retries=0, single_use_containers=True,
                            serialized=False, include_source=True,
                            secrets=[modal.Secret.from_dict({"HF_TOKEN": token})])(gpu_forced_result)
    return app, function


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--execute", action="store_true", help="Explicitly run one bounded paid GPU experiment")
    mode.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker:
        if not (WORK / "assets.json").is_file() or os.environ.get("HF_HUB_OFFLINE") != "1":
            parser.error("Worker requires the fixed prepared container manifest and offline model cache")
        run_worker()
        return 0
    if not args.execute:
        print(json.dumps(plan(), indent=2))
        return 0
    stage = "access"
    try:
        token = base.existing_token()
        status = base.check_access(token)
        if not base.access_allowed(status):
            print(json.dumps({"status": "blocked", "model_access_status": status, "cloud_dispatched": False}))
            return 2
        stage = "app_definition"
        app, function = build_app(token)
        stage = "app_start"
        with app.run(detach=False):
            job = function.spawn()
            try:
                stage = "gpu_input"
                result = job.get(timeout=base.FUNCTION_SECONDS + base.STARTUP_SECONDS + 15)
            finally:
                try: job.cancel(terminate_containers=True)
                except Exception: pass
        if result.get("status") != "completed":
            print(json.dumps(result))
            return 1
        stage = "local_output"
        expected = {"input.wav", "response.wav", "forced-result.wav", "continuation.wav", "token-stream.json", "report.json"}
        if set(result["artifacts"]) != expected:
            raise ValueError("Unexpected audition artifacts")
        destination = Path(__file__).resolve().parent.parent / ".local" / "personaplex-forced-result" / time.strftime("%Y%m%d-%H%M%S")
        destination.mkdir(parents=True, exist_ok=False)
        for name, value in result["artifacts"].items():
            if len(value) > 3 * 1024 * 1024:
                raise ValueError("Oversized audition artifact")
            if name.endswith(".wav"):
                pcm_profile(value)
            else:
                json.loads(value)
            (destination / name).write_bytes(value)
        print(json.dumps({"status": "completed", "output_directory": str(destination), "persistent_service": False,
                          "quality_verified": False}))
        return 0
    except Exception as error:
        print(json.dumps({"status": "failed", **base.diagnostic(error, stage),
                          "reason": "The ephemeral forced-result experiment failed."}))
        return 1


if __name__ == "__main__":
    from importlib import import_module
    raise SystemExit(import_module("personaplex_forced_result").main())
