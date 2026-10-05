# Fixed production-role qualification

`experiments/personaplex_fixed_roles.py` prepares one bounded test of the exact
production Moss, Orbit and Spark prompts. It uses the accepted NATM1 voice and
existing hashed synthetic English inputs. One bounded model run and three
separate ASR requests completed; the ASR did not observe any of the three names.
That establishes unobserved naming, not a wrong-name result or a verdict on
personality. This experiment did not enable production behavior or bank narration.

## Recorded output

Ignored receipt
`avatar/.local/personaplex-fixed-roles/20261001-062557-1790853957136559400/`
records one weights load, 900 frames, unchanged per-conversation prompt/cache and
57.032 seconds to load and prime. All three output hashes, PCM profiles, role
prompt hashes and clock evidence were checked locally. Mean frame computation
was 48.5–49.6 ms against the 80-ms native clock.

| Role | Existing active-audio frames | Native response observation |
| --- | --- | --- |
| Moss | 61 / 4.88 seconds | Empathic response and a question about one small step; native text contains Moss, but ASR did not hear the name. |
| Orbit | 38 / 3.04 seconds | Practical questions about tomorrow and the first planning step; no name observed. |
| Spark | 46 / 3.68 seconds | Friendly casual questions about doing something fun; no name observed. |

Active frames use the existing RMS threshold and are descriptive counts, not
speaking-rate or prosody measurements. The three input requests also differ.
Native captions and ASR naming remain separate receipts. No bank-related speech
was flagged. Human style review, physical microphone behavior, initial routing
latency and automatic voice/visual consistency remain unqualified. Missing
names must not turn into an invented requirement to repeat experiments until
the model says a character name; the original aim is appropriate conversational
personality and a coherent world.

The combined adaptive prompt failed its naming hypothesis. This test asks the
narrower prerequisite question: does a single fixed production role produce its
intended audible identity and conversational style? A successful name match alone
will not establish style, automatic initial routing or live role changes.

## Three independent conversations

| Production role | Existing input clip | Conversation clock |
| --- | --- | --- |
| Moss | Anxious request for one small step and its identity | 300 native frames / 24 seconds |
| Orbit | Planning request for three steps and its identity | 300 native frames / 24 seconds |
| Spark | Energetic request for momentum and its identity | 300 native frames / 24 seconds |

These are the original local `en-US` System.Speech clips used by the previous
candidate, bound to its exact scripts, rates, provenance and SHA256 manifest.
There is no new fixture generation, microphone, human audio or account data.
Each first clip appears once at frame zero; silence fills the remaining clock.
The unchanged four-file manifest and all four files are copied and checked to
preserve provenance. The fourth, slower-again clip is never fed to this runner.

Weights load once through the unchanged production `NativeModel` constructor,
which stock-primes the Moss text prompt and NATM1 voice. Before the next two
independent conversations only, the runner computes the exact production
expression `tokenizer.encode(wrap_with_system_tags(PERSONAS[role]))`, assigns
those approved tokens, then follows the stock streaming reset and voice/text
cache replay sequence. It refreshes the state/cache reference at that boundary.
The wrapper is imported from the pinned NVIDIA source, not recreated or replaced
with a chat-message format. No production prompt lookup is patched.

Each conversation then uses only ordinary free native `step` calls. A shared
pure verifier refuses prompt changes, cache/state replacement, offset jumps,
malformed PCM and invalid native frames. There are no forced tokens, prompt
updates, resets or re-prime inside a conversation. Continuity applies separately
to each conversation; it is never claimed across the two intentional fresh
conversation boundaries. The existing bank boundary is part of every unchanged
production prompt. No arbitrary prompt or runtime role API is exposed here.
The original constructor initializes the pinned random seed once; random state
then advances between conversations. Fresh conversations describe independent
streaming states, not independently reseeded statistical trials.

## Runtime and privacy bounds

The source-backed, nonserialized Function uses the existing private pinned image
plus source and synthetic-file COPY layers. It never rebuilds the weights,
downloads from HF, reads an HF token or mounts a provider key. Source revision
`3428dfd95309a7f3c84fd93259ded0f810d1ff91` and model revision
`fdaf4090a61cb315c138a1faee287ffd6c716309` stay fixed. Container destinations use
POSIX paths even when launched from Windows.

The child has a hard 360-second limit covering asset verification, one load,
priming and all 900 frames / 72 seconds of audio clock. One A100-80GB Function
has a 600-second runtime, 60-second startup, at most four CPUs / 64 GiB memory,
maximum one single-use container, no retries and no warm pool. The client has a
675-second timeout and always attempts input/container cancellation in `finally`.
Actual stopped-worker evidence still requires independent observation after
dispatch. It has no endpoint that browser users can invoke.

Ignored private artifacts under `avatar/.local/personaplex-fixed-roles/` contain
three input/output WAV pairs, assistant-token records and a report. The report
binds the output hashes, original fixture provenance, exact production prompt
hashes, pins, one load, fresh-conversation boundaries and unchanged per-role
clock/cache evidence. Assistant tokens are explicitly labelled as native model
text, not an independent transcription of audio. Structured failures retain
only fixed phase, class and episode; raw child logs, provider messages and
credentials are omitted.

## Local qualification and separate paid checks

The default plan imports no Modal/Torch and reads no cache, fixture or key.
Seventeen focused local tests pass, including a complete fake-model lifecycle,
exact prompt/wrapper construction, no in-conversation mutation, installed-SDK
definition without dispatch, staged source imports, deadline cancellation,
all-output validation before key access and a nonrepeatable ASR batch. The
existing 20 adaptive tests also pass after extracting the shared pure verifier.
The full 145-case Python experiment suite passed at preparation.

```powershell
python avatar/experiments/personaplex_fixed_roles.py --plan
python -m unittest discover -s avatar/experiments -p test_personaplex_fixed_roles.py -v
```

The completed run used this explicit operator command. It is recorded for
reproducibility and does not schedule or recommend another run:

```powershell
python avatar/experiments/personaplex_fixed_roles.py --execute
```

After completed artifacts are downloaded and verified, independent listening and
a separate explicit `--verify-asr <output-directory>` can assess the spoken names.
ASR checks all three output hashes, PCM profiles, durations, per-role prompt
hashes, cache/clock evidence and no-room-audio/model pins before reading the
existing server-side OpenRouter key. It makes at most three fixed English Whisper
requests, one per output, with 45-second request timeouts and redirects disabled.
An exclusive private admission receipt prevents repeating the batch after
success, failure or interruption. It changes no frontend voice provider.

Acceptance centers the intended calm/analytical/energetic behavior,
intelligibility, a coherent voice/visual presentation and absence of unsupported
bank claims. A spoken name can help assess consistency; an absent name is not
itself a failure of the requested personality. Contradictory names still require
review. The strict ASR naming summary reports missing names as unobserved and
returns nonzero for its naming hypothesis, not a verdict on speech quality.
Human style review remains separate, and neither a name match nor
this offline clock qualifies initial audio routing, physical microphone/AEC,
browser latency, interruptions or bank-result speech. Failed roles remain
unqualified; this runner has no automatic experiment or production-enable loop.
