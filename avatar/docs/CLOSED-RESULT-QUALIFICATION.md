# Closed synthetic speech qualification

Prepared 1 October 2026. This source-only experiment dispatches no GPU or ASR
request by default and changes no production provider, banking path or release
gate. Seventeen stdlib checks qualify its scheduling, output suppression, cache
continuity checks and admission boundaries with a fake model. One authorized
synthetic model run and one independent ASR check have now completed. The closed
gate passed; spoken amount/status pronunciation did not qualify. Actual GPU
termination remains separate operator evidence.

The earlier forced-speech audition matched its planned text IDs and retained its
LM cache, but independent ASR misheard the supplied name and detected an invented
future promise after the intended result. This second trial isolates amount and
status pronunciation, with the fixed public synthetic sentence:

> The payment amount is forty two dollars and seventeen cents. There is no open
> dispute. No action was taken.

It deliberately excludes a name; a successful result cannot qualify names or
arbitrary account narration. No real financial data or bank request is involved.

## Fixed stream and closed output

`experiments/personaplex_closed_result.py` reuses the pinned forced-result PCM
helpers, result queue and existing private weight cache. The operator's cache
reference is checked only on `--execute`; no credential lookup, Hugging Face
access check, cache rebuild or weight-download fallback occurs. The model setup
uses `NativeModel`'s source/revision/hash checks and fixed offline asset paths.
The source overlay includes the current `modal_diagnostic` dependency imported by
the browser/cache helper; a staged-import test verifies this without the original
checkout, rather than relying on the older cached image's module contents.

The candidate spaces ordinary words with four PAD3 frames instead of the prior
two, sentence endings with ten instead of six, and ends each word with EPAD0.
An explicit final sixteen-frame PAD3 phoneme tail plus EPAD0 remains forced;
it does not open a free lexical continuation. These durations are experimental
parameters, not pronunciation guarantees. The whole schedule is capped at 256
native 80-ms frames.

NVIDIA's `LMGen.step` returns output aligned through `max_delay`; forcing a token
does not make its corresponding output the same current input frame. The public
gate therefore uses the initialized model's bounded delay, verifies every admitted
output text ID against its forced schedule, and closes after the approved tail.
This avoids treating pipeline delay as unapproved continuation or truncating the
approved ending. The implemented delay bound is sixteen frames, below the fixed
post-reply settling interval.
[Pinned LMGen implementation](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py#L758).

All pre-reply and subsequent free audio is zeroed in `gated-timeline.wav`.
`closed-result.wav` contains only the approved, delay-aligned output window. Once
closed, the gate has no resume or user-activity API. Another eight seconds of the
ordinary public input fixture and a final tail still advance the same Mimi/LM
stream and cache; they cannot reopen public audio or captions. Unexpected text
IDs, changed cache, partial PCM or noncontinuous clocks fail the experiment.

The public caption is the fixed synthetic reply, explicitly marked as having no
ASR proof. Full native output, discarded continuation and model token records are
saved only in the ignored private result directory. They permit examination of
whether the model still invented continuation, rather than hiding that behavior
behind a cropped file. The report separates forced IDs, accepted/discarded output,
next-input clock progress and actual frame timings from pronunciation evidence.

## Bounded execution and independent listening check

Local preparation requires no service access:

```powershell
python avatar/experiments/personaplex_closed_result.py --plan
python -m unittest discover -s avatar/experiments -p 'test_personaplex_closed_result.py' -v
```

After operator review and authorization, `--execute` spends one A100-80GB Function
input using the existing private image plus a small source overlay. It has one
container, no retries, a 600-second runtime, 60-second startup bound, at most four
CPU cores and 64 GiB RAM. The 675-second client wait cancels/terminates its one
input in `finally`. It creates no web endpoint or persistent service. Cancellation
is requested after success as well; actual absence of surviving GPU containers
must still be verified independently. Function-resource estimates match the
original bounded audition; they are not an account spending cap.
The browser launcher's 120-second readiness probe is not used here: hashing,
model loading, prompts and inference share one 360-second worker subprocess bound
inside the 600-second input. The reported load time includes cache validation.

```powershell
python avatar/experiments/personaplex_closed_result.py --execute
```

Only after actual synthetic output exists, a separately authorized `--verify-asr`
request may use OpenRouter Whisper. It accepts only this experiment's ignored
output directory, requires completed pinned-model/closed-gate evidence, checks
the public WAV's digest and duration, and refuses an existing ASR receipt before
reading the key. The key stays in the environment or ignored `openrouter.env`.
One fixed HTTPS transcription request uses English and the cropped approved WAV;
redirects and automatic retries are disabled. Raw provider errors and keys never
enter public output. See the [official transcription contract](https://openrouter.ai/docs/guides/overview/multimodal/stt).

```powershell
python avatar/experiments/personaplex_closed_result.py --verify-asr "<generated result directory>"
```

The ASR verdict accepts the exact three propositions, allowing equivalent `$42.17`
formatting. A wrong amount, changed status or any added future promise fails it.
The private receipt preserves the synthetic transcription for human listening.
An ASR pass is one independent observation; it does not verify tool understanding,
real identity binding, names, arbitrary results, browser barge-in or general speech
quality. Bank narration remains disabled. This source modification is an explicit
forced-token experiment, not a supported PersonaPlex text/tool-result API.

## Observed synthetic result

The parent-run receipt reported 64.985 seconds for cache validation/model load,
403 continuous frames (32.24 seconds) and 153 approved output frames (12.24
seconds). The LM cache remained continuous and the permanent gate released zero
audio/caption frames after the planned reply, including later public-fixture
input. Compute mean was 49.213 ms, p95 50.554 ms, maximum 150.597 ms; two frames
exceeded the native 80 ms frame interval. Mean throughput is therefore evidence
of capacity, not proof that every frame met its deadline.

The first ASR attempt stopped locally before a request because the key-file
codec was incorrectly named `utf8-sig`. It is corrected to `utf-8-sig`, with
plain/BOM UTF-8 fake-credential regression coverage. The subsequent independent
check transcribed: “doing, the payment want is $42.17. There is no app dispute.
No action was taken.” The numeric amount and final action status survived, but
the amount introduction and dispute phrase did not match the intended three
propositions. The strict verdict failed. No repeat recognition is automatic,
and native bank narration remains disabled.
