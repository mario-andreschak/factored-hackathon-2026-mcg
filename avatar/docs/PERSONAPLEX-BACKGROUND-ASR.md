# Background utterance recognition beside native voice

Design review, 1 October 2026. The first server admission increment is now
implemented and passes ten new focused deterministic cases (34 cases across the
OpenRouter and PersonaPlex server suites). The frontend collector/scene observer
is now implemented, with six pure collector/lifecycle cases, two added
actual-hook and two actual-Game browser passes reported by their owners. The source aggregate
passed 84 cases with one optional installed-upstream skip; that pre-read-bridge
complete check also passed TypeScript/Vite and 46 browser cases/one optional
upstream skip. The current source/final image pass TypeScript/Vite, 93 units/one
optional skip and the disabled-provider boundaries. The separately opted-in
[visible read bridge](NATIVE-READ-BRIDGE.md) has focused Game/hold/identity passes;
the complete current browser rerun passes 64/one optional real-upstream skip.
Joined native/public-ASR/actual-Game acceptance now passes as described below;
the authenticated read bridge and physical microphone remain separate.
No live provider call, bank query, model download or
deployment was made by this implementation.

The separately invoked real provider/browser check completed in 12.814 seconds
with one native admission/WS and one actual transcription 200. The public
rice-cooking request reached Game with identical response/delivery hashes;
native input/output continued during the 0.999-second recognition request.
Readiness was 1.609 seconds and first output PCM 1.965 seconds. ACKs were
187/209/182 ms; mute sent 37 packets/37,888 all-zero samples. One microphone,
worklet and native context were owned; ten sources were audibly nonzero, and no
tracks/contexts/sources remained after cleanup. The browser closed and the
matching worker exited with termination acknowledged and confirmed; warmup
114.095 seconds, launcher elapsed 144.476 seconds. Receipt:
`avatar/.local/personaplex-observer-browser/2026-10-01T10-58-05-889Z/report.json`.
Banking, Savia, the read bridge, adaptive roles and physical microphones were
absent. This qualifies one public prerecorded request, not room echo, human
conversation or recognition across languages/accents.

The prior `2026-10-01T10-51-15-752Z` failed receipt is retained. Its actual
transcription200 already recognized `Prevent rice from becoming sticky when
cooking on the stove.`; the original harness required a question. The corrected
run accepts a meaningful rice-cooking request and observes Game delivery with
the same ten-word SHA256. No bank query was introduced by that correction.

PersonaPlex continues receiving microphone PCM and generating its own speech.
A second, bounded branch recognizes completed user utterances for subtitles,
scene cues and the existing visible Savia workflow. Recognition never feeds
`/conversation` or `/speech`; it never synthesizes the native character's reply.
It does not add a tool-result channel to the model.

## Existing pieces and required changes

| Piece | Current contract | Needed change |
| --- | --- | --- |
| `server/openrouter.mjs` | `validateTranscription` accepts only `{audio, format:'wav', language?}`. Mono PCM16 WAV, 8–48 kHz, at most 30.1 seconds, bounded base64. `transcribe` calls the fixed OpenRouter transcription endpoint with the operator-selected STT model and returns `{text}`. | Reuse unchanged validation/provider behavior. No arbitrary URLs, account identifiers, browser-supplied model or provider key. |
| `server/app.mjs` | `/transcribe` now permits the opted-in observer only for its ready native owner. Same origin, avatar session and operator gate for public access remain enforced. | `/conversation` and `/speech` stay denied under PersonaPlex. Native termination aborts recognition and suppresses late results. |
| `server/config.mjs` and `src/domain.ts` | Server configuration now accepts exact operator-only `AVATAR_BACKGROUND_ASR=openrouter`; config exposes configured `backgroundAsrAvailable: boolean`, default false, without keys. | Frontend consumes the capability before admission; an active ready native owner is additionally required for the actual request. |
| `src/experiments/usePersonaPlex.ts` | One microphone/worklet streams continuous 24 kHz PCM. Its optional `UtteranceCollector`/`UtteranceObserver` tees that capture into recognition while preserving the native clock, ACKs, mute zeros and playback. Assistant captions still come from the worker. | Acoustic recognition, echo behavior and packing cost remain to qualify. |
| `src/Game.tsx` | Separate `onObservedTranscript` appends user history and changes intent scenery. It preserves the active `voiceAvatar`; no observed text invokes `delegate`. Account events reset the observer before first-login exceptions. | Future delegation must be reviewed separately and use the existing single-owner Workbench path. |

`OPENROUTER_STT_MODEL` currently defaults to `openai/whisper-large-v3`. The
existing implementation already sends WAV JSON, uses a fixed endpoint with
redirects disabled, propagates aborts and returns sanitized errors. A provider
configuration change or failure must not silently select the old chained voice.

Observer admission is bound to the relay's currently ready native connection and
its server-held avatar-session owner. `server/personaplex.mjs` already binds
admission tickets to `session.id`. Its new internal `observerSignal(session)`
returns a cancellation signal only after readiness and valid ownership, session
expiry and lease deadline checks. A browser cannot supply an epoch, worker token
or lease ID as proof. Native teardown aborts pending observer work; deadline and
ownership are rechecked before dispatch and publication. The existing voice
rate, global concurrency and 45-second timeout guards are retained. A distinct
per-lease recognition budget remains a later policy decision.

## Capture and recognition lifecycle

The pure `UtteranceCollector` plus a hook-local observer are owned by the native
`Session`. They receive the same unmuted Float32 worklet packets after native
readiness. No second microphone is acquired and native sending does not wait
for recognition.

The current implementation copies device-rate Float32 packets, caps them at 25
seconds, then uses `wavFromPcm(..., sourceRate)` to encode mono 16 kHz PCM16 WAV
(about 800 KB maximum). It does not persist recordings. Float32 retention is
bounded but varies with the device rate: about 4.8 MB per full utterance at 48
kHz, up to 19.2 MB at the collector's 192 kHz maximum. A separate incremental
16 kHz buffer remains an optimization candidate if acoustic profiling reveals
packing stalls; it is not claimed as already implemented.

The collector uses 200 ms pre-roll, 120 ms voiced onset and 500 ms trailing
quiet. These are engineering starting values, not
qualified speech-detection accuracy. Calibrate against silence, room noise,
soft speech and the native speaker on real headphones and speakers. Keep the
existing native barge-in behavior independent of this collector.

Cap each logical utterance at 25 seconds. If speech continues past the cap,
discard the capped recording and wait for quiet before a new utterance. No
observed text can become an account request. There is one ASR request in flight
and at most one latest waiting utterance; a newer one replaces that waiting
observation. This can omit subtitles during recognition backlog but cannot
replace an admitted banking task, because observer delegation is disabled.
Unrelated questions are not concatenated; there is no automatic paid retry or
unbounded queue.

Delivered user text gets a fresh local UUID. The observer checks its active
controller/epoch and current native Session before every completion callback.
Account login/logout/navigation must invalidate pending recognition even when
Game's intentional first-login exception keeps the initial native session.
An earlier account's utterance must not become a new account's query.

Disconnect, provider change, role change, mute and a privacy pause clear the
pre-roll, partial segment and waiting utterance, invalidate their epoch, and
abort in-flight ASR. Mute still sends zeros to PersonaPlex. While the pond is
open, conservatively pause the observer and clear its buffers; the user can
continue native conversation or use Savia directly. This avoids copying login
speech into the new ASR processor without inspecting credential field values.
Do not claim that this filters words already spoken into the native microphone.

An ASR error leaves native audio connected. Report recognition failure
separately from voice transport failure. Never emit a fabricated user transcript
or a completed banking result. No background ASR occurs before an admitted
native session, while muted, or in provider `none`.

## Scene cues and banking delegation

Recognized text is the user's subtitle/history entry, identified by utterance
UUID. Use `classifyMood` as the existing presentation heuristic; it is not an
emotion diagnosis. While PersonaPlex is connected or connecting, retain the
launch avatar and apply only scene/intent cues. A visual avatar change is not a
verified native persona switch. Supporting initial role selection from an ASR
utterance requires a separate pre-roll/replay admission design and qualification.

Automatic banking delegation is not implemented. For a future reviewed clear
owned-account inquiry, invoke the same visible Workbench executor
once, with the exact bounded recognized question. Acquire its task owner before
any asynchronous wait. A second question while it is busy may enter history,
but must not silently enqueue or resubmit a bank query. If Savia needs login,
open the pond and stop; successful login must not automatically replay the old
question. Ambiguous or incomplete speech requires user clarification. A broad
keyword such as “payment” alone is insufficient evidence of an owned-account
question; require an explicit read request before automatic delegation.

The current dispute/human intent labels do not authorize a state-changing bank
action. Preserve the reviewed read/information boundary and Savia's existing
auth, account epoch and detached-document checks. Do not send an account token,
credential value or backend result into the native worker.

The actual result can appear in Savia and optional subtitles. Native bank
narration remains gated. The earlier synthetic forced-result test demonstrated
an invented free continuation; its replacement qualification is independent of
this ASR observer. Existing `interrupt()` is not a durable narration gate:
new user speech can release its manual hold. The first delegation increment
should therefore disconnect native voice before the account task, matching the
current typed fallback, until a separately tested permanent output policy or
supported result channel can safely govern native narration. This limitation
must remain visible in release claims.

## Incremental ownership and checks

| Increment | Files / owner | Required evidence |
| --- | --- | --- |
| Transcription admission only | Backend: `server/config.mjs`, `server/app.mjs`, narrow `server/personaplex.mjs` owner/readiness check, `.env.example`, operations docs and focused server tests | Default/absent key/provider mismatch or absent native owner deny before fetch; explicit ready PP observer admits valid WAV; PP conversation/TTS remain denied; same-origin/session/public gate, existing rate/concurrency bounds and cancellation still enforced. |
| Collector and observer | World/native hook: new pure collector, `src/audio.ts`, `src/experiments/usePersonaPlex.ts` | Exact pre-roll/minimum/cap/quiet behavior; finite memory and queue; mute/privacy/reset erase pending audio; ASR failure does not affect native audio; no ASR-driven native clock reset. |
| World and task bridge | Root: `src/domain.ts`, `src/Game.tsx`, narrow Workbench privacy-state callback if needed | Fixed avatar survives recognized mood; exactly one history entry/query; late recognition is withheld on first login, logout and reconnect; ambiguous/capped/busy utterances never submit. |
| Browser regressions | QA: shared PersonaPlex transport fixture plus an ASR-routed Game spec | Native PCM/output continues during delayed mocked ASR; barge-in works; no `/conversation` or `/speech`; account/mute/provider/role invalidation suppresses late callbacks and second tasks. |

The bounded public native/recognition/Game check passes as recorded above. A
physical microphone and speaker echo still require a separate natural interaction;
another mocked test cannot establish those conditions. The previous real Savia
inquiry remains separate evidence. The server increment is locally qualified
with fake provider responses and real loopback WebSockets; broader recognition
accuracy remains unqualified by these server/browser checks. The full
deterministic regression and production boundaries are recorded separately in
the release checklist.
