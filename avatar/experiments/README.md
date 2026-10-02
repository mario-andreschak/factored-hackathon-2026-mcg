# Native self-hosted voice audition

This is a bounded offline qualification of NVIDIA PersonaPlex, separate from
the release server. It feeds the official public assistant WAV into the model's
native audio stream and saves up to 20 seconds of generated audio. It starts no
browser endpoint or permanent GPU service and receives no banking information.
An offline sample can establish voice quality and model loading; browser latency,
interruptions, authenticated access and live backend delegation need a later
integration. PersonaPlex's stock entrypoint does not provide Gemini/OpenAI-style
function calling.

The source is pinned to NVIDIA commit
`3428dfd95309a7f3c84fd93259ded0f810d1ff91`; model files are pinned to Hugging Face
revision `fdaf4090a61cb315c138a1faee287ffd6c716309`. The image pins Torch 2.4.1
to match the official repository's `<2.5` requirement. Only the known NATM1
voice embedding is read from the voice archive, without extracting its paths.
The actual model must fit and run on the selected hardware before making any
deployment claim.

From the repository root, these checks are local:

```powershell
python avatar/experiments/personaplex_modal.py --plan
python -m unittest discover -s avatar/experiments -p 'test_*.py' -v
```

The default plan does not read credentials, contact a service or import Modal.
This separate check reads an existing `HF_TOKEN` or the existing Hugging Face
token cache and makes an authenticated HEAD request to one fixed official model
file. It prints only status and access availability, follows no redirects and
downloads no weights:

```powershell
python avatar/experiments/personaplex_modal.py --check-access
```

The account must already have access to the gated
[NVIDIA model](https://huggingface.co/nvidia/personaplex-7b-v1). The script never
accepts a model license or submits account-sharing consent. A 401/403 stops the
experiment before creating a Modal app. No permanent Modal secret is required:
the existing token enters the eventual job through documented
[`Secret.from_dict`](https://modal.com/docs/guide/secrets), kept separate from
the image and source. The client uses its existing Modal profile. It requires
Python 3.10 or newer and sends the canonical experiment module as source to the
pinned Python 3.11 container. It does not serialize a Python function across
interpreter versions.

The following command spends compute. It is intended only after the model
license/access step and the audition scope have been authorized:

```powershell
python avatar/experiments/personaplex_modal.py --execute
```

One ephemeral Function uses one `A100-80GB`, maximum one container, no retries,
600-second runtime, 60-second startup timeout, at most four physical CPU cores
and 64 GiB RAM. A separate 675-second client deadline cancels the input and
terminates its container, including after failures. The app stays connected
to the local process, without deploy, detach, schedules, volumes, min containers
or a public endpoint. The GPU is stopped after the one input. Local results go
to ignored `avatar/.local/personaplex-smoke/<timestamp>/` as `response.wav`,
`text.json` and `report.json`.

Current standard [Modal rates](https://modal.com/pricing) give a 600-second
GPU/CPU/RAM estimate of **$0.5331** at these maximum resource limits, or **$0.5882**
including 60 seconds startup and two seconds idle. CPU image building is billed
separately. The total target is about **$1**, which is an estimate, not an account
spending cap. No region premium or nonpreemptible setting is selected. The first
run must download roughly 17 GB of gated model assets and can time out before
producing audio; it does not automatically retry.

Eight local checks cover credential-free planning, access refusal before
dispatch, redirect handling, output bounds, safe voice-member reads,
single-input cancellation on failure/deadline and sanitized failure diagnostics.
Modal CLI 1.5.5 accepted the lazy source-backed image/app configuration on local
Python 3.13 without dispatching a GPU during preparation. Existing model access
was initially 403 and later the authenticated HEAD returned 302.

One authorized audition on October 1, 2026 built its image but stopped before GPU
admission: the original serialized function used local Python 3.13 while the
container used Python 3.11. Modal reported $0.00 usage and no remaining live
containers. The corrected source-backed function keeps the pinned dependencies
and container version. The single corrected bounded retry completed successfully
on October 1, 2026. It downloaded the fixed assets in 251.91 seconds and completed
model loading, inference and output normalization in another 42.78 seconds on an
NVIDIA A100-SXM4-80GB. Peak allocated tensors used 19,448,048,640 bytes (18.11 GiB);
this is not total GPU or process memory. The saved sample is 20 seconds of valid
24 kHz mono PCM WAV. Modal subsequently showed no live apps or containers and
remaining credit of $29.85 from the initial $30; this observed balance change is
not a pricing benchmark.

The generated public-fixture transcript identified itself as Moss and answered
the fixture's cooking question. This establishes that the pinned native model
loads and produces context-related voice on the chosen hardware. It does not
establish browser barge-in, live transport latency, banking access, tool
delegation or production readiness. User review of the saved audio precedes any
further cloud work. Subsequent failures
save a report in the ignored output directory with a fixed failure code, stage
and safe exception class. Provider messages, URLs and credentials are omitted.

Official entrypoint and prerequisites:
[NVIDIA PersonaPlex](https://github.com/NVIDIA/personaplex),
[pinned offline source](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/offline.py),
[Modal resource limits](https://modal.com/docs/guide/resources).

## Forced synthetic result: observed evidence

The authorized fixed-public-result experiment completed on October 1, 2026;
its ignored output is `avatar/.local/personaplex-forced-result/20261001-024017/`.
No account data entered the test. It forced the sentence naming Mira Chen and a
payment of forty two dollars and seventeen cents with no open dispute and no
action taken. The resulting 27.04-second PCM stream retained the same LM cache,
and its forced text-token IDs matched the planned contiguous sequence. On the
A100-80GB, instrumented frame compute averaged 51.51 ms, p95 52.39 ms and maximum
57.03 ms against an 80-ms native frame. This was not wall-clock-paced streaming
and does not measure browser latency or interruption behavior. Download still
took 211.15 seconds; load/prompt initialization took 30.74 seconds. Baking the
fixed weights before operator warmup remains necessary.

Text tokens were not treated as proof of pronunciation. One bounded independent
OpenRouter Whisper transcription of only `forced-result.wav`, with English
specified, completed in 3.55 seconds. It heard:

> By Merchant, the payment of $42.17 was no open dispute. No action was taken.
> No action will be taken.

The amount survived, but the intended name did not. The model's unsupported
future promise was also detected in the audio, not merely its text stream.
This one ASR observation does not replace human listening, but it prevents a
claim that exact forced IDs make bank-result narration reliable. The ignored
`forced-result-asr.json` and `forced-result-asr.txt` save only this synthetic
verification; no frontend provider was changed and no additional Modal job was
started for it. Bank-result speech stays gated on accurate names/amounts and a
bounded continuation. Native browser barge-in, tool understanding and private
banking-result delivery remain unqualified.

See [relay candidate](../docs/PERSONAPLEX_RELAY.md) for one-use same-origin
admission, private Sandbox Connect Tokens, pinned weight caching and bounded
worker termination. Relay, launcher, browser hook and PCM worker source are
implemented and locally qualified. The private weight cache completed; a GPU
attempt warmed its model/prompt in about 80 seconds without runtime download,
then failed Connect Token provisioning before browser admission. Its worker was
terminated. A subsequent public-fixture browser qualification passed actual
continuous native audio, audible interruption/resume, zero-input mute and
complete browser/worker cleanup; see the relay document for its distinct receipt.
Physical-microphone/AEC and human-conversation acceptance remain separate.

The operator-owned CPU-only `modal_transport_probe.py` later passed actual
authenticated health and WSS echo with a fixed `127.0.0.0/8` outbound allowlist
and confirmed termination. The failed fully blocked network policy produced a
safe `ConflictError`/`FAILED_PRECONDITION`; the voice launcher now uses only that
loopback CIDR policy. The CPU probe's default `--plan` reads no credentials or
operator files. Each explicitly reviewed `--execute --egress-policy loopback-only`
uses one 30-second, half-core/512-MiB Sandbox, no GPU/model/HF access and no retry.
It is not callable from a browser request. All 103 current Python experiment
checks pass locally; CPU HTTP/WSS acceptance is separate from the later native
voice browser receipt.

A later cached worker remained in model initialization at the former 120-second
readiness deadline and was interrupted during cleanup. Its later stopped state
and exit 137 were verified separately. An interim 180-second allowance also
expired during a later measured cold asset read: hash verification took 152.205
worker seconds and prompt readiness arrived at 178.827 seconds, with container
startup included in the launcher's window. Termination was confirmed. Readiness
and worker model initialization now each permit 240 seconds inside
the unchanged 600-second Sandbox/worker lifetime. Every checksum and pinned
cache check remains required; there is no automatic retry. This revised source
bound still needs its next explicitly reviewed actual run. Fixed milestones identify
the initialization phase. Cleanup records stop acknowledgment separately from
observed exit, retaining a failure warning when exit remains unconfirmed. The
prepared `personaplex_browser.py --refresh-worker` command copies only updated
source over the existing cached image, with no HF read/download or GPU launch.
The expensive `--build-cache` command is not needed for worker-source changes.

## Prepared intrinsic pacing qualification

The source-only `personaplex_intrinsic_result.py` candidate preserves sampled
PAD/EPAD timing between approved words rather than imposing a fixed PAD count.
It begins after a measured silent-code drain, measures the quiet tail only
after the final delayed lexical output, and permanently drops all subsequent
native conversation. Its first GPU attempt failed during inference and retained
no underlying child error. The exact Modal app stopped with zero tasks. A
source-only structured diagnostic fix now retains safe worker phase/policy codes
and frame counters, with no raw child logs. No speech/ASR acceptance or retry
has occurred for this candidate. See
[intrinsic pacing review](../docs/PERSONAPLEX_INTRINSIC_PACING.md) for the pinned
algorithm, bounds, artifact privacy and separate listening/ASR gate. Production
bank-result speech remains disabled.

## Prepared initial adaptive-role prompt

`personaplex_adaptive_prompt.py` is a separate candidate with one
combined initial Moss/Orbit/Spark prompt and one NATM1 voice. It loads weights
once and tests three independent episodes of fixed local synthetic English
audio; the third changes from energetic to slower speech without a cache reset
or prompt update inside that conversation. All four input fixtures were
generated locally and hashed, with no room microphone/provider. Its actual
bounded run completed, but independent ASR failed the three-form hypothesis:
planning named Moss rather than Orbit, and both energetic-to-calm replies named
Moshi. Native tokens agreed, while cache/clock checks passed. Twenty focused
cases pass; the full 124-case Python suite passed at the original preparation. See
[adaptive prompt review](../docs/PERSONAPLEX_ADAPTIVE_PROMPT.md) for exact bounds,
independent ASR/listening gates and explicit later commands. Production prompt,
bank narration and browser behavior remain unchanged.

## Prepared fixed production-role qualification

`personaplex_fixed_roles.py` prepares the next narrower prerequisite: the exact
production Moss, Orbit and Spark prompts, NATM1 voice, and the original hashed
anxious/planning/energetic first clips. One unchanged production constructor
loads weights and primes Moss; stock resets and voice/text replay occur only
before the other two independent conversations. Each conversation then preserves
its prompt/cache for 300 frames, totaling 900 frames / 72 seconds. No combined
adaptive prompt, forced speech or live role mutation is used. Seventeen focused
local cases and the 20 shared-verifier adaptive regressions pass, including real
SDK app definition without dispatch. Its one bounded model run and three
independent ASR requests subsequently completed. Names were unobserved by ASR;
the outputs included empathic small-step, practical planning and casual responses
respectively, while subjective personality remains unqualified. See [fixed role review](../docs/PERSONAPLEX_FIXED_ROLES.md)
for source pins, runtime bounds, private artifacts and independent speech/style
gates. Production role prompts, browser behavior and bank narration are unchanged.
