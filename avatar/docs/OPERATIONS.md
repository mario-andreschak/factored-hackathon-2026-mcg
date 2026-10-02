# Running Elsewhere

Elsewhere is a separate visual and voice companion. It serves its own frontend
and proxies a narrow set of routes on the already authenticated Savia frontend.
It has no banking signing key, FLUJO execution bearer or worker control access.
The currently installed Savia integration supports read-only inquiries. It
cannot submit a dispute, cancel a banking run or promise a selected charge was
resolved. See [ARCHITECTURE.md](ARCHITECTURE.md) for the source audit and limits.

## Local run

Use Node 22 or newer. From `avatar/`:

```powershell
npm ci
Copy-Item .env.example .env
npm run dev
```

Open `http://localhost:4317`. The API listens on loopback port 4318. With no keys
or upstream configured, this is a clearly labeled synthetic interactive demo.
Set `GEMINI_API_KEY` in the shell, ignored `.env`, or ignored `gemini.env` to
enable native Gemini Live audio. `GOOGLE_API_KEY` is an accepted alias.
The browser continuously streams PCM audio into one native Live session; the
provider detects speech, responds in native audio and permits interruptions.
`OPENAI_API_KEY` enables the alternative native Realtime WebRTC transport.
Keys are used only by the server; never use a `VITE_` variable for credentials.
The npm scripts read `.env`, `openrouter.env`, then `gemini.env`. Restart the
server after changing keys. Gemini is preferred when configured, followed by
OpenAI; `AVATAR_VOICE_PROVIDER` can explicitly select `gemini-live`,
`openai-realtime`, `openrouter-native` or `none`. The bounded PersonaPlex audition requires explicit
`personaplex` selection and an already ready operator lease. An OpenRouter key
alone does not enable voice. Explicit `openrouter-native` uses native audio
Chat requests with SSE replies; it is not a persistent Live socket.
Local voice can start before banking login. Set
`SAVIA_UPSTREAM=http://127.0.0.1:43800` to connect the installed Savia frontend.
If Savia has a fixed public origin, set `SAVIA_PUBLIC_ORIGIN` to that exact origin.
The installed local service uses `http://localhost:43800`; set that value even
when its upstream address is `http://127.0.0.1:43800`. Those origins are distinct
and a mismatch rejects login and chat mutations with 403.
The user logs in directly inside the visible Savia screen.

For the production build on loopback:

```powershell
npm run check
npm run build
npm start
```

Open `http://localhost:4318`. `/healthz` reports process health. The config route
reports whether a key and upstream are configured; it does **not** prove a
successful provider connection, available account data or healthy FLUJO worker.

## API and cookies

`GET /api/avatar/config` returns `{voiceAvailable, voiceProvider,
backgroundAsrAvailable, nativeReadBridgeAvailable, backendAvailable, saviaUrl,
mode, realtimeModel, geminiModel}`. With the explicit
PersonaPlex provider it also returns `voiceAvatar`, the fixed launch role or null
when no valid lease exists. It creates a 30-minute local `avatar_session` cookie,
HttpOnly and SameSite=Strict. `saviaUrl` is `/savia/` only when connected.

`POST /api/avatar/gemini-token` accepts JSON
`{avatar:'moss'|'orbit'|'spark',locale?:'es'|'pt'}`; other fields are rejected.
It returns `{token,model,websocketUrl,expiresAt,newSessionExpiresAt,setup}`.
The token is a one-use Gemini credential, valid for 30 minutes with a 60-second
new-session window. Keep it only in browser memory, never logs, analytics or
persistent storage. The standard Google key remains on the server. The browser
connects to the fixed Google constrained WebSocket URL with `access_token`, sends
`{setup}`, and waits for `setupComplete` before sending audio. Input is continuous
mono signed 16-bit little-endian PCM at 16 kHz; native output is 24 kHz.
A provider `interrupted` event clears pending playback. Microphone mute ends the
audio stream with `audioStreamEnd`.

The server fixes the operator-configured model (default `gemini-3.8-live`), native voice, character instructions,
audio transcription and automatic VAD with speech interruption. Both functions
are `NON_BLOCKING`: world selection affects presentation and asynchronous Savia
work independently enforces account authentication. Actual REST constraints use
`bidiGenerateContentSetup` with nested `generationConfig`; an omitted `fieldMask`
locks the whole setup, so browser-supplied instructions or tools cannot override
it. Native voices default to Charon, Kore and Puck. Model and voices are operator
configuration through `GEMINI_LIVE_*`. Short-lived tokens carry provider audio
access only, never banking authority.
Model overrides must support native audio and `NON_BLOCKING` function calls;
Gemini 3.1 Flash Live does not provide the asynchronous tool behavior used here.

`POST /api/avatar/realtime?avatar=moss|orbit|spark&locale=es|pt` accepts raw `application/sdp`
and returns `application/sdp`. The server creates a fixed GA Realtime session
with the configured model, two constrained function tools, input transcription
and semantic VAD with automatic response creation and speech interruption.
Only the selected provider's voice endpoints are enabled; choosing `none`
prevents provider calls even when its API key remains configured.

### Native OpenRouter adapter

The implemented `AVATAR_VOICE_PROVIDER=openrouter-native` adapter uses the existing
server-side key in ignored `openrouter.env`. It fixes `openai/gpt-audio`, Coral,
OpenAI-only routing with fallback disabled, 512 completion tokens and a 45-second
operation deadline. The browser sends a completed captured WAV directly to the
native model; background recognition supplies history/intent independently and
does not generate its speech. Output is bounded PCM16 NDJSON over same-origin
HTTP. The 24 kHz mono rate is explicitly labeled assumed. See
[native setup and constraints](OPENROUTER_NATIVE.md).

| Route | Contract |
| --- | --- |
| `POST /api/avatar/native-turn` | `{audio,format:'wav',avatar,locale}` or `{message,avatar,locale}`; streamed `start`, `caption`, `audio`, `complete` or safe `error` events |
| `POST /api/avatar/native-observe` | `{turnId,audio,format:'wav',locale}`; one recognition of the exact captured audio, bound to its avatar session |
| `POST /api/avatar/native-played` | `{turnId,locale,playedSamples,complete}`; only complete playback matching the validated sample count admits assistant history |
| `POST /api/avatar/native-reset` | `{}`; revokes reply/observer owners and clears history and task facts |
| `POST /api/avatar/native-result-receipt` | `{reply,locale}`; finds an exact recent server-observed result and returns its opaque `taskId` |
| `POST /api/avatar/native-result` | `{taskId,avatar,locale}`; consumes one server-held result after fresh account verification |

All six routes require the selected provider, local avatar cookie, allowed
origin and configured remote access gate. Browser-supplied history, backend facts,
tools and routing selectors are rejected. New speech cancels the old native
response while preserving the independent observer of its captured input. Reset,
account/locale changes, logout and upstream authentication rejection revoke that
context. Old-account read replies are withheld. A consumed result can remain
separately quoted for at most 120 seconds; forwarding private facts/history always
requires a fresh unchanged Savia identity. This does not treat an unheard spoken
tail as heard history or grant permission for a bank action.

The supervised built preview at `http://127.0.0.1:43941` explicitly enables this
adapter; Savia and the read bridge are off. Its key remains in the ignored local
configuration. The user accepted the actual Spanish browser conversation and
talk-over experience as "amazing" and "excellent". This is human feedback, not
quantitative microphone/AEC or latency qualification. Portuguese feedback and
joined spoken banking facts remain pending. A key alone still leaves an otherwise
unconfigured installation without voice.

The final source check passed TypeScript/Vite and 297 units/one optional upstream
skip. The clean native browser suite passed 16/16 in 40.9 seconds. Actual
production HTTP QA then completed two native WAV turns, with strict completion,
clean EOF, unchanged source and server shutdown; its playback receipts were
simulated and no observer ASR, Savia, bank, GPU or physical microphone was used.
See the [current validation ledger](OPENROUTER_NATIVE_VALIDATION.md) for exact
request-relative timings, the six-controlled-request cost subtotal and remaining
Portuguese/device/style/joined-banking gates. After a server restart, refresh the
preview to obtain a fresh avatar session before starting voice.

The separate local validation beta at `http://localhost:43942` configures native
voice/observer, the installed Savia upstream and `AVATAR_NATIVE_READ_BRIDGE=readonly`.
Its distinct loopback hostname isolates the host-only cookie from voice-only
`http://127.0.0.1:43941`; changing the port alone would not. Preparation checked
component config only, not a Savia login/inquiry or spoken bank result. This
human-validation availability does not close the joined read/narration gate.

The retained OpenRouter STT/chat/TTS adapter is an explicit operator opt-in,
disabled by default and not the native Live experience requested for this
product. Only `AVATAR_VOICE_PROVIDER=openrouter` enables its routes, even when
an OpenRouter key is configured. It uses these same-origin routes, the same
local session and the same public access gate:

| Route | Contract |
| --- | --- |
| `POST /api/avatar/transcribe` | JSON `{audio:base64,format:'wav',language?:ISO639-1}`. At most 30 seconds of mono 16-bit PCM WAV, 8 MB request cap. Returns only `{text}`. |
| `POST /api/avatar/conversation` | JSON `{message,avatar,history?,backendResult?}`. User/assistant text history only, at most ten messages and 8000 characters. Streams NDJSON `{type:'text',delta}`, validated `{type:'tool',name,args,id}`, then `{type:'done'}`; stream errors have a fixed `{type:'error',error,code}`. |
| `POST /api/avatar/speech` | JSON `{text,avatar}`, at most 1200 characters. Streams raw `audio/pcm`, signed 16-bit little-endian mono at 24 kHz, with `X-Audio-Sample-Rate`, `X-Audio-Channels` and `X-Audio-Format` headers. |

The browser detects turn endings locally and sends short recordings; it begins
playing streamed PCM before the full response arrives. Speech interruptions abort
pending voice requests and clear scheduled audio while independently admitted
Savia reads continue. This is an STT/text/TTS pipeline, with different latency
and turn detection from the direct OpenAI Realtime WebRTC transport.

Default OpenRouter models are `openai/whisper-large-v3`,
`google/gemini-3.1-flash-lite`, and `google/gemini-3.8-flash-lite-tts`.
They were checked against the live official model and endpoint catalog on
October 1, 2026. Some narrative OpenRouter documentation still names
`openai/gpt-4o-mini-tts-2025-12-15`; its live endpoints route returned 404 during
qualification, so it is not the default. Model IDs and the three fixed voices
are configurable through the `OPENROUTER_*` variables in `.env.example`.
The PCM adapter supports documented Gemini and OpenAI mini-TTS profiles; other
providers need an explicit audio-profile adapter before use. Gemini uses the
documented `speech_metadata.style` provider option for delivery, with Charon,
Kore and Puck voices by default. The model cannot pick a provider, voice or URL.

`backendResult` is an optional bounded public reply `{reply,mode?:'flujo',status?}`.
It enters the voice conversation as quoted data with further delegation disabled
for that summary turn; it cannot establish banking identity or grant permission.
Upstream usage, routing metadata, reasoning and error diagnostics are never
forwarded. Truncated streams and invalid tools cannot emit executable task events.

`POST /api/avatar/task` accepts **only** `{message}` with 1–4000 characters.
Customer IDs, conversation IDs, model choices and caller-authored metadata are
rejected. The server sends that message to Savia `/api/chat` under the user's
existing bank session and returns only `{reply, mode:'flujo', status}`. It has no
banking authority of its own. The current status values are `completed` and
`waiting_for_input`.

## Bounded self-hosted native conversation

PersonaPlex is an explicit audition candidate. Set
`AVATAR_VOICE_PROVIDER=personaplex` and `AVATAR_PERSONAPLEX_LEASE_FILE` to the
absolute ignored `avatar/.local/personaplex-browser/lease.json` path on an
isolated loopback server. Leave Savia upstream and provider keys absent for the
public-fixture voice acceptance check. At the PersonaPlex preparation stage the
development provider remained `none` until the operator selected that audition. See
[PERSONAPLEX_RELAY.md](PERSONAPLEX_RELAY.md) for prepared commands and the Modal
source/runtime constraints.
The [host-Node supervised profile](SUPERVISED-NATIVE.md) gives exact application,
foreground launcher and shutdown steps. It supports one prewarmed session,
with a 600-second total worker lifetime including warmup; it does not claim a
continuously available service or native bank narration. Default Compose has no
lease path/mount and cannot enable this provider without a separately qualified
explicit operator override.

### Optional background utterance recognition

`AVATAR_BACKGROUND_ASR=openrouter` opts in to the existing OpenRouter Whisper
transcription endpoint beside native PersonaPlex. It requires
`AVATAR_VOICE_PROVIDER=personaplex` and the existing server-side
`OPENROUTER_API_KEY`; absent or empty opt-in leaves it disabled. Values such as
`true` are rejected. This does not select the chained OpenRouter voice provider
and does not enable PersonaPlex `/conversation` or `/speech` requests.

The public config exposes only `backgroundAsrAvailable: boolean` for this
capability, before native admission. Actual `POST /api/avatar/transcribe`
requires the avatar-session owner of a ready relay connection, a valid session
and lease deadline. Tickets, pending worker dials and another browser's session
do not qualify. Fixed-endpoint PCM-WAV validation, same-origin/public ingress
gate, rate/concurrency bounds and the 45-second timeout are reused. Native end
aborts pending transcription; ownership and deadline are checked again before
publishing a result, including when the upstream ignores cancellation.

The frontend tees its existing worklet into a 25-second bounded collector with
200-ms pre-roll, 120-ms voiced onset and 500-ms trailing quiet. There is one
recognition request and one latest waiting utterance; capped recordings are
discarded. Recognition pauses when the pond is open or a task is active, and
pending audio/results are invalidated on mute, identity changes and disconnect.
Native PCM, its cache and output remain independent. Recognized user text enters
the optional transcript and can change scenery from intent; it does not change
the fixed launch role, dispatch a banking inquiry or supply facts to the native
model. Bank narration remains disabled.

The pre-read-bridge source `npm test` run passes **84 tests with one optional installed
upstream skip**. Ten new server admission/lifecycle cases pass alongside six
collector/observer cases. Two added actual-hook and two actual-Game observer
cases passed with routed synthetic recognition, as reported by their owners;
the latter retain the fixed role and clear pending text across first login. The
parent's pre-read-bridge complete rerun passes TypeScript/Vite, 84 units/1 optional skip and
46 browser cases/1 optional upstream skip. This evidence makes no live
recognition or acoustic accuracy claim. Keep this opt-in/key absent in the
original native-only fixture audition. See [observer scope](PERSONAPLEX-BACKGROUND-ASR.md).
The later separately configured observer audition completed in 12.814 seconds,
with one native admission/WS and one actual transcription 200. The public
ten-word rice-cooking request reached actual Game with matching response/delivery
hashes while native PCM continued: 23 input/12 output packets during 0.999 seconds
of recognition. Readiness 1.609 seconds, first PCM 1.965 seconds; ACK 187/209/182 ms,
mute 37 packets/37,888 zero samples, one microphone/worklet/native context and
ten audible sources. No live audio resources remained and the browser closed.
Matching launcher warmup 114.095 seconds/elapsed 144.476 seconds, worker exited,
termination acknowledged and confirmed. No Savia/read bridge/banking, adaptive
roles, narration or physical microphone was exercised. The earlier failed
question-only fixture receipt remains historical; its transcription recognized
the same request. See [release evidence](RELEASE-CHECKLIST.md) for hashes/scope.

### Explicit visible read capability

`AVATAR_NATIVE_READ_BRIDGE=readonly` is a separate default-off capability. The
server advertises `nativeReadBridgeAvailable` only for PersonaPlex with opted-in
background recognition/key and fixed Savia upstream. Only exact `readonly` is
accepted; `true`, `readwrite` and other values fail configuration. This boolean
does not authorize an account or change existing task/proxy routes. A missing
native worker still denies voice/recognition, and an unsigned bank session still
denies account reads. Three new cases qualify those boundaries; the selected
four server suites pass52/one optional installed-upstream skip, without dispatch.

Game uses the existing visible read-only Workbench and a durable native playback
hold while PCM input continues. The owners report 11 focused Game, four new hold
and three new Workbench passes. Historical TypeScript/Vite and 93-unit/one optional
skip checks pass, as does the production-container boundary below. The complete
browser rerun passes 64/one optional real-upstream skip, 65 total in 2.4 minutes.
Native bank narration remains disabled;
real replies appear in Savia/subtitles. The earlier 84-unit/46-browser and
observer Docker receipts precede `taskHold`/read-bridge sources; actual joined
native speech-to-owned-inquiry acceptance remains distinct.
See [read bridge scope](NATIVE-READ-BRIDGE.md).

Compose now forwards both observer/read-bridge flags with empty defaults; it
does not enable either feature automatically. Supply the operator-selected
flags/key through the intended environment files. A PersonaPlex runtime still
needs an independently prepared private worker and an explicit operator lease
path visible inside its container. No default lease, secret mount or GPU launch
is supplied by this Compose change.

Only the operator launcher builds the private pinned weight image and warms one
600-second GPU Sandbox. Browser/API requests cannot start, replace or retry a
GPU worker. The relay requires a fresh six-second heartbeat lease with exact
source/model pins, one-use 15-second session-bound ticket and allowed Origin/Host.
The public ingress gate also applies to Upgrade when externally configured.
Modal Connect Tokens stay in the relay's private Authorization header and ACL-
restricted lease file, never browser config, query strings or telemetry. No raw
public tunnel or permanent service is created by this audition.

`POST /api/avatar/personaplex-session` accepts only `{avatar}` matching the fixed
lease role and returns `{ticket,expiresAt,streamPath,inputSampleRate,
outputSampleRate,protocol}`. The stream path is exactly `/api/avatar/personaplex`.
The browser opens the same-origin WebSocket with that ticket, waits for native
ready, and exchanges continuous signed PCM16LE mono 24 kHz. Output carries a
generation and global sample clock. Interrupt ACK advances the generation;
pending/late audio and assistant captions are dropped. Muting supplies zero PCM
to keep the model clock moving. Frames, buffers, controls and lifetime are
bounded; malformed packets, lease loss and disconnect terminate both sockets.

Each worker admits only one native conversation. The consumed epoch becomes
unavailable for further starts; config becoming unavailable during that active
stream does not cancel it. New availability/admission/handshake/worker-ready
require at least 120 remaining lease seconds; below that threshold, the valid
lease still identifies its fixed role but is unavailable for a new start. Five
new boundary/lifecycle checks pass in the 25-case relay suite. The historical pre-LATAM full
source/image passed 93 units/one optional skip. An already admitted PCM/observer
session continues below that threshold and stops at its original expiry, with
no deadline extension. Fixed launch personas currently share the one
qualified NATM1 embedding. A visual avatar change ends native speech and uses
silent preview; no unsupported live persona update is implied. Captions come
from agent text tokens and never claim user ASR. This worker cannot see bank
accounts, inspect a browser, understand tools or narrate task results. Existing
authenticated Savia work remains independent and visible through the Workbench.

Local qualification passed eleven relay checks, twenty-one launcher/cache checks,
seven CPU-probe checks and ten native worker checks. The relay tests include an actual temporary Vite
proxy, proving HTTP Host translation and WebSocket Upgrade routing using the
repository's proxy settings. All 80 experiment checks pass without cloud/GPU
dispatch. An operator CPU-only probe also passed authenticated HTTP/WSS and
confirmed termination using the fixed loopback-only outbound CIDR policy. The
first cached GPU attempt warmed but failed token provisioning with fully blocked
networking and was terminated; the launcher now allows only `127.0.0.0/8` egress,
with no raw ports or public/model-download egress. Real microphone/full-duplex/
interrupt acceptance remained a separate provider check at that stage; saved
offline voice-quality approval alone is not a browser acceptance result.

The second cached worker reached the original 120-second readiness deadline
while initialization was still pending. Its SDK cancellation and later exit 137
were observed separately; no model failure or preemption is inferred. Readiness
now allows 240 seconds within the same 600-second lifetime after a later cold
verification/prompt attempt exceeded the interim 180-second allowance. Cleanup acknowledges
one stop command separately from bounded exit observation, and reports a failing
`cleanup_unconfirmed` result if exit is unobserved. Fixed worker milestones and
sanitized ignored run history preserve the diagnosis. Refresh changed worker
source using `--refresh-worker` over the existing cache ID, never `--build-cache`;
that command performs no HF access or GPU launch.

The corrected actual browser/provider audition then passed with public
prerecorded microphone audio. Its ignored `2026-10-01T09-40-43-286Z/report.json`
records one admission/WS and zero banking requests: ready 1.520 s, first native
PCM 1.769 s, zero sample-clock errors, one audible VAD barge-in, VAD ACK
129/128 ms and manual ACK 134 ms. The 1.746-second mute interval sent 37,888
all-zero samples. No microphone tracks, native audio contexts or playback sources
remained alive; the browser closed. The matching launcher receipt records
58.147-second warmup, 104.769-second elapsed run, worker exit and acknowledged/
confirmed termination. No persistent service was created. Physical microphone
echo/AEC and a natural human conversation remain separate qualification.

The raw launcher flag `nativeBrowserAcceptanceVerified:false` remains unchanged:
the launcher cannot verify browser audio. The separate browser report and matching
launcher cleanup together establish this bounded acceptance. Preserve earlier
failure/no-overlap receipts instead of overwriting them. Optional background ASR
was disabled in this first native audition. The later public rice-request check
qualifies native/ASR/actual-Game continuity; physical microphone/echo and broader
recognition accuracy remain unqualified.

The proxy keeps the upstream `flujo_bank_session` cookie HttpOnly, preserves
Secure and SameSite=Strict, and scopes its browser path to `/savia`. Its value
is kept transiently behind the local avatar session so delegation can reuse it
without returning the banking cookie to frontend JavaScript. A parent request
to `/savia/api/auth/me` synchronizes this mapping after a reload. Avatar-server
restart expires its local session map; refresh config and the Savia screen to
reconnect. This does not revoke or alter Savia's own persisted sessions.

Only the audited login/profile/me/logout, overview/transactions and read-only
chat/status/history routes, the fixed index/favicon and `/assets/` are proxied.
Authorization headers, caller cookies unrelated to banking, worker headers and
arbitrary `/v1`, admin or action routes never pass through. Upstream origin is
translated to the operator-configured Savia origin. Known HTML and JavaScript
asset roots are rewritten to `/savia/`; only the proxied page's framing policy
changes to same-origin embedding. Upstream account authentication and ownership
checks still apply to every protected request.
The proxied chat POST also rejects customer, conversation and model selectors
before contacting Savia. It accepts only the existing message and optional
opaque `txn_` transaction reference contract.

Logout immediately disables local delegation and removes the scoped browser
cookie, while Savia performs its own durable worker revocation. A failed or
timed-out logout is not reported as confirmed. A speech interruption cancels
spoken output only. A task timeout or lost connection leaves the result
unresolved: consult `/savia/api/chat/history` and its `active` flag before retrying.
Do not automatically resubmit banking work.

## Container

```powershell
docker compose -f compose.yaml up -d --build --wait
```

The image runs as the unprivileged Node user. Compose publishes only loopback,
drops capabilities and uses a read-only filesystem. No local `.env` enters the
build context. The backend uses Node built-ins plus the pinned `ws` 8.22.0
WebSocket transport. The runtime copies only that package, the backend and built
frontend. To connect a host service from Docker Desktop, set
`SAVIA_UPSTREAM=http://host.docker.internal:43800` and set `SAVIA_PUBLIC_ORIGIN`
to Savia's configured origin (`http://localhost:43800` for the installed service).
Confirm host networking can reach that service.
This command creates only the separate avatar service; it changes no existing
Savia or FLUJO deployment.

Compose automatically reads `.env` from the current directory. For the native
OpenRouter adapter, keep `AVATAR_VOICE_PROVIDER=openrouter-native` in ignored
`.env` and the existing `OPENROUTER_API_KEY` in ignored `openrouter.env`. Pass both
files explicitly, in this order, without displaying their contents:

```powershell
docker compose --env-file .env --env-file openrouter.env -f compose.yaml up -d --build --wait
```

The later credential file overrides duplicate variables; keep provider selection
explicit in `.env`. This same key is used server-side for native audio and optional
recognition. It is never a browser variable. For the Gemini alternative, choose
`AVATAR_VOICE_PROVIDER=gemini-live` and use its separately named credential file:

```powershell
docker compose --env-file .env --env-file gemini.env -f compose.yaml up -d --build --wait
```

Credential files and backups are excluded from the build context; keys are passed
only to the separate server's runtime environment. These commands do not imply a
qualified provider/account, microphone, banking workflow or public deployment.

## Remote ingress

For external use, place this service behind an authenticated HTTPS reverse proxy
on a private network. Configure `AVATAR_PUBLIC_ORIGIN` to one fixed HTTPS origin,
`AVATAR_HOST=0.0.0.0`, `AVATAR_ALLOW_PUBLIC_BIND=true`, and an operator-generated
`AVATAR_ACCESS_GATE_TOKEN` of at least 32 base64url characters. The ingress must
strip user-supplied `X-Avatar-Gateway-Token`, authenticate the visitor, and inject
that token on every forwarded request. Never send it to a browser or let the
public Internet bypass that ingress. Startup rejects a remote origin without
the configured gate. The application gate allows voice before the user signs
in to Savia; Savia account login independently protects banking tasks.

Forward `Host` and `Origin` consistently with the configured public URL. The
server does not trust `X-Forwarded-Host`, forwarded client addresses, browser
authorization headers or a claimed customer identity. Use separate ingress
limits per authenticated visitor and a provider project spending cap. Server
limits are shared per direct peer: 120 requests and 6 voice starts per minute,
256 local sessions, 8 simultaneous voice handshakes, 8 backend tasks and 64 proxy
requests. OpenRouter voice has 60 operations per minute per direct peer and 8
concurrent operations. The ingress is required for production identity and
visitor fairness. With `gemini-live`/`openai-realtime`, audio travels directly between browser and Google over
its constrained WebSocket, or browser and OpenAI over WebRTC after signaling.
Ephemeral-token issuance consumes the same six-start limit; Google can permit
one session for its token lifetime, so enforce provider project quotas too.
With `openrouter-native`, completed WAV input and streamed NDJSON output pass
through this server over HTTP; this adapter needs no WebSocket ingress. Allow
its bounded request bodies (native audio routes cap JSON at 8 MiB), preserve
`X-Accel-Buffering: no`, disable proxy response buffering, and set an idle/read
timeout of at least 45 seconds (for example 60 seconds). The retained explicit
`openrouter` STT/chat/TTS pipeline also passes audio through the server, but it
has a different voice path. Keep the configured provider's transport distinct.

## Release checks

`npm run check` compiles the frontend and runs deterministic tests. Server tests
exercise actual HTTP proxy behavior with a synthetic upstream, auth cookie
scoping/login/logout, same-origin and Host enforcement, fixed Realtime session
schema, bounded bodies, response-body timeouts, resource limits, strict task
projection and duplicate-task admission. `npm run test:e2e` verifies the browser
experience. These checks need no provider key or banking credentials.
Native Gemini checks cover fixed REST setup constraints, one-use token TTL,
native provider selection, secret projection, same-origin sessions, strict
requests, disabled chained endpoints, errors, deadlines and admission cleanup.
Retained opt-in OpenRouter pipeline checks cover PCM WAV limits, fixed model/voice
selection, split SSE events, safe backend summaries, tool validation, raw PCM
format, provider error sanitization, bounded tool-only-turn continuations and
upstream cancellation on disconnect.

Separately verify the installed upstream anonymously (assets load, login screen,
owned APIs remain 401), then use an authorized user login for history, a
read-only inquiry and logout revocation. A live voice acceptance check must
observe native `setupComplete` (Gemini) or `session.created` (OpenAI), audible
output, a real interrupt and disconnect/mic
cleanup. A configured API key alone is not live acceptance evidence. Keep test
credentials, bank replies and cookie jars out of logs, reports and screenshots.

The GA signaling and VAD shapes were checked against the official
[WebRTC guide](https://developers.openai.com/api/docs/guides/voice-webrtc) and
[VAD guide](https://developers.openai.com/api/docs/guides/realtime-vad). Model,
account entitlement, provider quota and actual audio devices remain deployment
dependencies.
Gemini's [ephemeral-token guide](https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens),
[Live API reference](https://ai.google.dev/api/live), and official
[token converter](https://github.com/googleapis/js-genai/blob/main/src/converters/_tokens_converters.ts)
establish the fixed server wire setup. The current
[FunctionResponse type](https://github.com/googleapis/js-genai/blob/main/src/types.ts)
places asynchronous scheduling at the top level: `SILENT` for presentation-only
world acknowledgements, `WHEN_IDLE` for eventual task results.
OpenRouter's [STT guide](https://openrouter.ai/docs/guides/overview/multimodal/stt),
[TTS guide](https://openrouter.ai/docs/guides/overview/multimodal/tts), and Google's
[speech guide](https://ai.google.dev/gemini-api/docs/speech-generation) establish
the alternative transport contracts and PCM profile.

On October 1, 2026, all 35 deterministic server tests and the opt-in anonymous
integration test against the installed Savia at loopback port 43800 passed.
The installed compiled page and rewritten API bundle loaded, profiles returned
200, and anonymous account overview, identity, history and task requests remained
401. Compose configuration validation also passed. A real browser microphone
and valid WebRTC offer reached the provider, which returned HTTP 429 classified
as exhausted account credit / insufficient quota. The server now returns the
fixed public code `voice_quota_exhausted` and a clear message while keeping text
and Savia available; it never automatically retries. Direct OpenAI Realtime audio
acceptance remains blocked by that account quota.

Before the new PersonaPlex candidate, the release Docker image built successfully with frontend compilation,
55 passing unit tests and one intentionally skipped installed-service test.
An isolated production container ran as UID 1000 with a read-only
filesystem, served the built page and config, and reached installed Savia:
profiles returned 200 and anonymous identity remained 401. Only `dist` and
`server` were present in `/app`; credential files were absent. Hidden paths and
`.env` files are explicitly denied even if accidentally copied into a static
build. The final Blender-produced Spark GLB was served successfully with valid
binary glTF magic (3,443,168 bytes). Disabled voice endpoints refused provider
dispatch. The temporary qualification container was stopped and removed.

Native Gemini Live token issuance and audible full-duplex acceptance remain
unverified until the selected Google project key is configured and an actual
Live session succeeds. Mocked browser/provider tests prove protocol behavior
without proving account entitlement or real audio quality.

The separately admitted native OpenRouter `openai/gpt-audio`/Coral audio-input
auditions are documented in [OPENROUTER_S2S_AUDITION.md](OPENROUTER_S2S_AUDITION.md).
The user accepted the Spanish diagnostic preview from the second, SDK-mode
attempt; its failed technical receipt is unchanged. Three Spanish receipts remain
failed. One subsequent Portuguese request completed under explicit application
metadata-tail compatibility and saved PCM/WAV: first decoded PCM 2,616.50 ms,
last 3,557.11 ms, request 3,679.77 ms; 278,400 PCM bytes. All 42 ordered safe shapes were
saved, including expiry, bare assistant/empty-content tail and accounting.
Reported PT cost $0.009474 brings all four native S2S calls to $0.031058.
This is native model audio through endpointed Chat Completions SSE, with no
dedicated TTS or ASR chain. It is not persistent Live WebSocket evidence.
The current adapter has passed the final TypeScript/Vite and 297-unit/one-skip
source check, clean 16-case native browser suite, and actual two-turn production
HTTP QA. The earlier Windows-commit failure before browser setup remains
historical. Spanish human conversation/talk-over approval is separate from the
simulated playback receipts in HTTP QA. Portuguese quality, the assumed rate,
quantitative microphone/AEC, all three speaking styles and joined spoken bank
facts remain gates. The current restricted native image passed 41 runtime checks,
with 289 tests passing and nine explicit clean-context skips (298 total). It is
`savia-elsewhere:native-20261001`, image
`d4d4007fa7e7967286b6e19a15eba9fe136f8d4ccba6f585d669999c804f8ea2`.
The local/public-gate containers used UID1000, read-only/dropALL/no-new-privileges,
256 MiB/64 PID limits and no provider key, Savia target or lease. Assets, 14 private
404s, all six inactive native503s and Host/Origin/gateway boundaries passed;
both exact containers were removed and their loopback ports clear. No provider,
bank or GPU call occurred. Historical images below remain separate. Current
exact receipts and clean-context skip reasons are centralized in
[OPENROUTER_NATIVE_VALIDATION.md](OPENROUTER_NATIVE_VALIDATION.md). All earlier
failed audition receipts and spent markers are preserved.

The PersonaPlex candidate image was then rebuilt with frontend compilation and
68 unit passes plus one skipped installed-service check. Its isolated read-only,
capability-dropped 256-MiB runtime loaded the sole `ws` package as UID 1000,
served the same final GLB and refused disabled OpenAI/PersonaPlex requests. It
contained only `dist`, `server` and `node_modules/ws`; no provider credentials
or Savia upstream were injected, and no banking request was made. Private paths
remained unavailable. That temporary container was stopped and removed. This
qualifies packaging/default admission; the real native browser audition remains
separate.

The subsequent pre-read-bridge observer image
`e3ccd0b65721541622202e0f3790ab99b8412ee3a5e8147f281f4db8847b3ea0`
also builds successfully with TypeScript/Vite and 84 unit passes/one optional
installed-upstream skip. An isolated `elsewhere-observer-qualification:20261001`
runtime bound only loopback43946 as UID1000, read-only, all capabilities dropped,
no-new-privileges and 256 MiB. `/app` contained only `dist`, `server` and
`node_modules/ws`; private files and provider/Savia/lease configuration were
absent. An attempted `/app` write failed with EROFS. Health, page, JS, CSS and
the final 3,443,168-byte GLB returned200 with valid glTF magic; private paths
returned404. Config reported background ASR false and provider/backend disabled.
PersonaPlex admission, transcription, chained chat/speech and native provider
admission all returned503 without dispatch. The exact owned container was
stopped/removed and no43946 listener remained. This is packaging/admission
evidence, separate from the corrected actual native public-audio audition.
It predates `taskHold` and the optional read bridge.

The pre-session-policy read-bridge image
`532b0e2956b4fd43f60cc81386ac3e20e17a6941667ea821f114ea95746f5a70`
was built as `elsewhere-native-read-qualification:20261001`; TypeScript/Vite and
**88 unit passes/one optional installed-upstream skip** pass inside the build.
Its temporary runtime published only `127.0.0.1:43946`, used UID1000:1000,
read-only filesystem, all capabilities dropped, no-new-privileges, 256 MiB and
64 PID limit. `/app` contained only `dist`, `server`, `node_modules/ws`; no
provider keys, Savia target, worker lease or observer/bridge flags were supplied.
An attempted write returned EROFS. Health/page/JS/CSS and the final GLB returned
200; JavaScript/CSS sizes were 311,794/31,765 bytes, GLB was 3,443,168 bytes with
valid glTF magic. Ten private/unknown paths returned404. With the normal issued
avatar session, six disabled voice admission routes returned503; config kept
background ASR/read bridge/backend/voice false and provider `none`. No bank,
provider or GPU request occurred. The exact owned container was stopped and
removed, and both its container inventory and loopback listener count were zero.
This is final packaging/default-admission evidence, not joined live bridge or
native bank-narration proof.

After the 120-second new-start policy and per-message avatar-history correction,
the new image `64cdc922b49c2e681e09530770e3b68494d4cb06dd11f034f5d22066d499b46b`
was built as `elsewhere-native-session-qualification:20261001`. Both the parent
source check and image build pass TypeScript/Vite and **93 units/one optional
skip**, 94 total. The complete browser rerun passes 64/one optional real-upstream
skip, 65 total in 2.4 minutes. Its owned runtime passed the same UID1000/read-only/dropALL/
no-new-privileges/256-MiB/64-PID boundaries and was bound only to loopback43946.
Only dist/server/ws were present; no provider keys, lease, Savia target or opt-in
flags were configured. WriteEROFS, health/page/JS311,875 bytes/CSS31,765 bytes/
final GLB3,443,168 bytes200 with valid magic, ten private404 and six disabled
voice admission503 checks passed. Config voice/backend/observer/read bridge
stayed false. The exact owned container was stopped/removed; container/listener
counts were zero. No provider, bank or GPU dispatch occurred. This qualifies
current packaging/default admission; PersonaPlex with a Docker-mounted lease
and joined owned-read acceptance remain separate.

During earlier qualification, with the separately configured OpenRouter key,
real low-volume STT, conversation
and TTS requests all returned 200. The sample STT returned in about 1.5 seconds,
the initial tool-producing conversation in 1.8 seconds, and TTS in 3.65 seconds
with 320,640 verified PCM bytes. Those are single qualification observations,
not latency benchmarks. The initial tool-only conversational reply exposed a
silent-turn defect; the server now uses one bounded tools-disabled continuation
for world choices and a fixed short bridge for asynchronous tasks, covered by
dedicated tests. Live browser barge-in and authenticated banking acceptance are
tracked separately from these provider endpoint checks.

To repeat that anonymous installed-service check:

```powershell
$env:AVATAR_TEST_SAVIA_UPSTREAM='http://127.0.0.1:43800'
node --test tests/server.test.mjs
```
