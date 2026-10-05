# One initial prompt, three conversational forms

The separate `experiments/personaplex_adaptive_prompt.py` candidate completed one
bounded native-model qualification with fixed synthetic English inputs generated
on this computer. Independent ASR did not verify its three-form hypothesis: the
planning episode named Moss instead of Orbit, and the energetic-to-calm episode
named Moshi instead of Spark then Moss. It remains outside the production worker
and browser. Bank-result narration remains disabled; no automatic retry is planned.

## Actual outcome

The completed receipt is in ignored
`avatar/.local/personaplex-adaptive-prompt/20261001-060133-1790852493566860700/`.
All three output WAV hashes, PCM profiles, durations and model/prompt pins were
verified locally before reviewing the separate three-request ASR receipt.

| Episode | Intended naming | Independently transcribed naming | Outcome |
| --- | --- | --- | --- |
| Anxious | Moss | "Maybe Moss" and a Moss description | Name observed; firm identity and style are not established. |
| Planning | Orbit | "I'm Moss" | Failed form selection. |
| Energetic to calm | Spark, then Moss | Moshi in both replies | Failed initial selection and adaptation. |

Native assistant tokens agree with these spoken-name observations. The report
records one model load, two deliberate fresh-episode resets, zero in-episode
resets, zero prompt updates and zero forced tokens. Each episode preserved its
cache and expected offset progression. Loading and priming took 65.457 seconds;
mean frame computation was 48.1–48.7 ms, below the 80-ms model clock. These
receipts establish a completed inference experiment, not successful mood routing,
human-reviewed style or browser performance. No bank-related speech was flagged
in these synthetic outputs.

The result does not support enabling adaptive production mode or interpreting
native name mentions as authoritative world-selection events. A shorter combined
prompt might change behavior, but this result does not identify a specific
correctable prompt defect. Another prompt-only retry would remain speculative.
The concrete next architecture is initial server-side role selection followed by
one fixed role prompt for the whole native conversation. That path still needs
audible identity and style qualification for each fixed role before activation.

PersonaPlex supports text role prompts independently of its audio voice prompt.
Its prompting guide includes empathetic, reflective and energetic scenarios.
That makes this a plausible experiment; it does not prove these three forms
will reliably follow user mood. [Pinned NVIDIA prompting guide](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/README.md#prompting-guide)

## Fixed initial conditioning

All episodes receive the same initial system prompt. It describes one companion
with three named forms, chosen from the user's tone, pace and expressed need:

| Form | Requested conversational behavior |
| --- | --- |
| Moss | Calm, warm, slow and brief when the user feels overwhelmed or wants to slow down. |
| Orbit | Clear, thoughtful, practical and concise when the user wants analysis or a plan. |
| Spark | Brisk, playful and energetic when the user wants momentum or lively company. |

The prompt asks the companion to name its matching form when asked who it is
and to mention a changed form briefly once. Subsequent adaptation uses ordinary
user audio. There is no later system-message injection, tool event, `setPersona`
command, cache reset or re-prime inside a conversation. All forms use the same
qualified NATM1 voice embedding; they are not three newly qualified voices.
The production worker's existing bank boundary is included verbatim: the model
cannot see accounts, websites or task results and must not claim account checks,
dispute facts or changes. Voice mood remains separate from task authority.

The isolated initializer temporarily substitutes only the fixed prompt lookup
while calling the verified `NativeModel` loader, then restores that lookup in
`finally`. It does not edit the production module. The loaded text-token prompt
remains fixed. Per-frame checks refuse a changed prompt, state identity, cache
pointer, offset or PCM format.

## Three independent episodes after one model load

| Episode | Input and response clock | Expected spoken naming hypothesis |
| --- | --- | --- |
| Anxious | Fixed slower English request for one small step, then silence; 24 seconds total. | Moss |
| Planning | Fixed English request for a three-step plan, then silence; 24 seconds total. | Orbit |
| Energetic to calm | Fixed brisk English request; a slower overwhelmed request begins at 12 seconds; 32 seconds total. | Spark, then Moss |

Only between these independent episodes does the runner reset all three stock
streaming participants and replay the same initial voice/text prompts, following
the pinned initialization sequence. It updates its state/pointer reference at
that boundary. The third episode keeps one uninterrupted cache through both
user requests. Continuity is checked within each episode and is never claimed
across the two deliberate fresh-episode resets.

The four fixed input WAVs were produced locally with an installed `en-US`
System.Speech voice: anxious 7.774 seconds, planning 6.684 seconds, energetic
4.840 seconds and slower-again 7.654 seconds. These are synthetic test inputs,
not the agent's output voice. There is no microphone, room recording, account
fact, provider or human audio. Each clip is PCM16 mono 24 kHz, at most 12 seconds,
with an exact script/rate and SHA256 manifest; changed provenance or audio is
refused before SDK/key access. Input is placed on a fixed 80-ms/1,920-sample clock
and silence fills the remaining episode.

## Bounded runtime and source privacy

The runner uses the existing private pinned cache, plus a source/fixture COPY
overlay. It never re-enters the 16-GB weight preparation chain, downloads a model,
reads HF credentials or mounts a provider key in the container. Source revision
`3428dfd95309a7f3c84fd93259ded0f810d1ff91` and model revision
`fdaf4090a61cb315c138a1faee287ffd6c716309` remain fixed. The model is loaded once,
with exactly three bounded episodes/1,000 frames/80 seconds total audio clock.

The child process has a 360-second hard limit covering verification, loading,
priming and all inference. One A100-80GB Function has a 600-second runtime,
60-second startup, at most four CPUs/64 GiB memory, maximum one single-use
container, no retries, no warm pool and no persistent endpoint. Its client has a
675-second deadline and cancels its input/container in `finally`; actual stopped
worker evidence must still be checked after a dispatch. No browser or
public request can invoke this runner.

Artifacts stay in ignored `avatar/.local/personaplex-adaptive-prompt/`, with
restricted output-file permissions. They include fixed input WAVs, native output
WAVs, assistant token records and a report binding hashes, pins, one load, prompt
immutability and episode continuity. Child failures return only fixed stages,
classes and episode counters; raw logs, credentials and provider URLs are omitted.

## Review and acceptance

These commands are local and spend no provider compute:

```powershell
python avatar/experiments/personaplex_adaptive_prompt.py --plan
python -m unittest discover -s avatar/experiments -p test_personaplex_adaptive_prompt.py -v
```

Twenty focused checks pass, including a complete fake-model three-episode
lifecycle, initial-lookup restoration on failure, unchanged prompt/cache inside
each episode, private cache/source COPY bounds, installed-SDK app definition
without dispatch, and paid-input cancellation.
At preparation, the full 124-case Python experiment suite passed. The default plan imports no
Modal/Torch and reads no fixture, cache or key.
Local fixture generation is already complete; `--prepare-fixtures` is an explicit
Windows-only mode that refuses to overwrite its fixed output directory.

The first execution attempt was rejected locally at app definition, before any
cloud job: Windows `Path` rendered the container fixture destination with
backslashes, which Modal correctly rejected as a nonabsolute POSIX path. The
destination now uses `PurePosixPath`; an installed-SDK definition-only check
reproduces this setup without starting an app or dispatching a Function. No
model result or adaptive behavior was obtained from that attempt.

The completed qualification used this explicit operator command. It is recorded
for reproducibility, not a recommendation to repeat the failed hypothesis:

```powershell
python avatar/experiments/personaplex_adaptive_prompt.py --execute
```

The separate, explicit `--verify-asr <output-directory>` check completed three
requests and reported the failed form sequences above. Listening and style
review are separate from that result. The ASR mode validates every completed output
hash, duration, prompt/model pin and no-room-audio/cache evidence before reading
the existing server-side OpenRouter key. It sends at most three fixed English
Whisper requests, one per output. An exclusive admission receipt blocks repeats
after completion, failure or interruption; there is no automatic ASR retry.
Transcripts remain private, while the public summary contains only named-form
observations and review flags.

Naming observations are distinct from prosody and helpfulness. Human review must
establish calm/analytical/energetic pacing, continuity, listening, natural role
adaptation and absence of unsupported account claims. Bank-related speech raises
a review flag. Assistant text tokens, input labels and an ASR name match do not
prove those properties. This offline stream is not wall-clock paced and cannot
qualify browser latency, VAD, physical microphone/AEC or frontend world switching.
The browser's user-intent classifier and the native model's chosen form remain
independent until a later measured integration aligns them. No production
capability, role change API, tool calling or bank narration is enabled here.
