# Qwen native WebSocket qualification — deferred

**Decision, 2026-10-01: deferred after the user rejected the listened-to Chelsie ES/PT samples.** The observed accent/Spanish-English mixing did not meet the required voice quality. This concerns the exact samples/preset, not every Qwen voice. No StageB browser source or cloud job was created, no GPU is active, and the app provider stays unchanged.

`experiments/qwen_live_audition.py` retains the isolated **engine-duplex WebSocket** candidate. Thirteen focused local checks, syntax and independent source review pass. The single CPU image attempt built the pinned core/Omni checkout, then failed before function dispatch because the official image exposes `python3` without a `python` alias. Exact app `ap-YhPc1HL584XBemRY9evQc3` is stopped with zero tasks; no CPU function or GPU ran. Original spent admission/failure and typed diagnosis are preserved. The explicit `--prepare-runtime-python3-fix` correction is source-ready and independently reviewed, but **has not been executed**. Runtime/import/protocol receipts and native streaming remain unqualified. Further execution is deferred.

## Exact serving stack

Freeze vLLM-Omni **423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7** and official vLLM0.30.0 linux/amd64 image **vllm/vllm-openai@sha256:5f5e535216848d0c52159c8c13a0af04be5f6fe1a84e79914300610796f76d40**. The [pinned CUDA Dockerfile](https://github.com/vllm-project/vllm-omni/blob/423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7/docker/Dockerfile.cuda) supplies the install procedure. CPU preparation installs that exact checkout, records dependency versions/lock hash and image ID, and requires CUDA13 before native GPU loading. It uses neither the earlier CUDA12.8 audition image nor an older Omni nightly with newer source.

The [duplex deploy](https://github.com/vllm-project/vllm-omni/blob/423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7/vllm_omni/deploy/qwen3_omni_duplex.yaml) inherits the [three-stage two-H100 configuration](https://github.com/vllm-project/vllm-omni/blob/423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7/vllm_omni/deploy/qwen3_omni_moe.yaml): Thinker GPU0 at0.9, Talker/Code2Wav GPU1 at0.6/0.1, async chunking, initial/subsequent codec windows4/25 with context25 and Talker seed42. The overlay bounds each stage to one sequence, Thinker128/Talker384 tokens and one duplex session. These bounded overrides remain hardware-unqualified.

There is a same-revision documentation conflict: the generic Qwen recipe bans async for `/realtime`, while the [matched engine-duplex VAD profile](https://github.com/vllm-project/vllm-omni/blob/423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7/examples/online_serving/realtime_web/README.md) explicitly uses `/v1/realtime?duplex=1` with the duplex base and async enabled. This experiment follows that exact engine-owned profile. It does **not** set `--no-async-chunk` or substitute an SSE benchmark. Source supports nonterminal native decoded-audio chunks; actual timing is unproved.

## CPU prerequisite and bounded Stage A

The existing23-file,70.53GB model cache is mounted read-only at its fixed revision; no runtime HF credentials/downloads. CPU image preparation bakes the two exact fixture hashes and [Silero ONNX](https://github.com/vllm-project/vllm-omni/blob/423f34326ed420e5acf0b1fb862a1b5ffb7e0fa7/vllm_omni/engine/duplex/vad.py), revision8b14476858ef240c50b3884bb38cc67290c1cc70, SHA2561a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3. It validates installed imports, local model/registry/config resolution, CPU ONNX initialization, CLI arguments, loopback WebSocket JSON/PCM framing under `block_network=True`, and the qualified Volume commit/tiny-receipt/local-download path. Loopback echo proves transport, not native inference. Source checkout/install/VAD commands have120/1200/45-second shell limits; image pulls and build orchestration are separate CPU preparation costs. The admitted CPU function is240s with315s job/delivery client budget.

Only a matching verified CPU receipt permits one new GPU admission. The GPU function uses **two H100s,600s lifetime,540s child,675s job/delivery client, one container, zero retries**; startup stops by360s. A CUDA driver API≥13.0/two-BF16-H100 check precedes native loading. Server binds loopback with fixed served-model name and absolute duplex overlay, external egress blocked. Two sequential45s sessions replay exact public WAV payloads at ordinary1x cadence: mono little-endian PCM16,24k input,16k model processing,24k output. Nested session.update/session.updated config, server VAD and200ms appends match the shipped profile; zero PCM continues while replies stream.

Each language must produce multiple valid24k PCM deltas, nonzero audio in an unfinished native chunk and audio before completed response.done, all bound to one immutable response ID. Each complete200ms input block is sent after its capture interval, without catchup bursts. Actual append start/completion receipts, exact once-delivered PCM hash and complete-fixture-upload timestamps distinguish configured pacing from measured delivery. The report stores decoded arrival relative to session-update send and server speech end, native assistant captions and cleanup evidence. It cannot establish audible latency, human quality, browser interruption, tools or bank speech. Runtime default is **Chelsie** because the pinned HF speaker mapping orders Chelsie first; the duplex plugin drops the voice selector, so selectable speakers are explicitly unsupported here. Voicebox cloned TTS profiles cannot be plugged into this native path.

WAVs and report are committed to the existing output Volume; only a sub4KiB allowlisted receipt returns through Modal. Local download has cumulative size/hash checks and a true async deadline. New `.local/qwen-live` admission markers are exclusive; historical native-audition markers remain intact. Failure never triggers another model, GPU, retry or extended deadline. Each actual app still requires independent stopped/zero-task confirmation.

At current [Modal prices](https://modal.com/pricing), two H100s plus8CPU/128GiB ceilings cost about **$1.55/600s**, or **$1.71 including60s startup**, below the **$2.50 finite GPU ceiling**. CPU image preparation/storage are separate. Audible barge-in, five-plus-turn history, trusted next-turn facts, browser admission and banking narration require separate proofs after Stage A passes.

## Reviewable commands

From the repository root, these checks are inert:

```powershell
python avatar/experiments/qwen_live_audition.py --plan
python -m unittest discover -s avatar/experiments -p test_qwen_live_audition.py -v
```

Historical original CPU command, whose spent marker remains preserved:

```powershell
python avatar/experiments/qwen_live_audition.py --prepare-runtime
```

Prepared diagnostic correction, currently deferred and unexecuted:

```powershell
python avatar/experiments/qwen_live_audition.py --prepare-runtime-python3-fix
```

The GPU command would require a verified runtime receipt and a separate reviewed decision to resume qualification; it has not run:

```powershell
python avatar/experiments/qwen_live_audition.py --execute
```

Only the failed CPU image preparation above has run. The interpreter correction, native streaming GPU step and browser work remain unexecuted/deferred. No app provider was enabled, and all existing exact apps are stopped with zero tasks.
