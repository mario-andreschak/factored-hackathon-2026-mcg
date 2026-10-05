# elsewhere.

The final-day local candidate and recording recipe are in
[RC voice runbook](docs/RC-VOICE.md). It uses the fresh fictional portal on
43900 and native audio on 43941, with conversation during background reads,
account-owned result delivery, and a provider notice before microphone use.

A separate cinematic voice companion for Savia. Begin in darkness with drawn
eyes, describe what is on your mind, and enter one of three worlds: Moss's ancient
forest, Orbit's observatory, or Spark's desert outpost. Ten original forest scenes,
animated characters, atmospheric sound and a real embedded Savia computer make
the conversation part of the scene.

Product language is Spanish LATAM or Brazilian Portuguese. Spanish is the default;
a Portuguese browser preference selects Brazilian Portuguese. The pause menu saves
an explicit language choice. PersonaPlex remains a historical English research
adapter and does not qualify for the LATAM release. The user accepted Coral's
Spanish diagnostic preview and the actual Spanish browser conversation/talk-over
experience, calling it "amazing" and "excellent". The production HTTP adapter
completed two native Spanish/Portuguese WAV requests, and its clean native
browser suite passed 16/16 synthetic cases. Portuguese listening feedback,
quantitative microphone/AEC, actual three-style acceptance and joined spoken
backend narration remain release gates. See the
[current validation ledger](docs/OPENROUTER_NATIVE_VALIDATION.md),
[open-weight candidates](docs/OPEN_WEIGHT_VOICE_OPTIONS.md) and
[native audio evidence](docs/LATAM_NATIVE_AUDIO.md).

The OpenRouter candidate uses `openai/gpt-audio` for native audio input and
streamed native output, with no separate STT/chat/TTS chain. This is a completed
audio request followed by an SSE response, rather than a persistent Live socket.
Native capture waits for two continuous seconds of silence so brief thinking
pauses stay in the same message. Resumed speech resets that window; talk-over
still interrupts the companion promptly.
Production HTTP QA produced first decoded PCM after 1.764 seconds for Spanish
and 1.297 seconds for Portuguese; these are request timings, not first audible
microphone-to-answer latency. Continuous
local capture, response cancellation, playback-clock history and mood selection
are tested with synthetic browser input. The supervised built preview at
[port 43941](http://127.0.0.1:43941) explicitly enables native audio; Savia and the
read bridge are off there. Its credential stays in an ignored local file. A key
alone still leaves an otherwise unconfigured installation's provider `none`. See the
[native adapter setup](docs/OPENROUTER_NATIVE.md) and
[exact audition receipts](docs/OPENROUTER_S2S_AUDITION.md).

A separate [read-only validation beta](http://localhost:43942) is prepared with
native voice, observer recognition and the visible Savia read bridge configured.
It uses `localhost` to keep its host-only session separate from the voice-only
`127.0.0.1:43941` preview; cookies are not isolated by port. Only component config
was checked when preparing it. Its availability does not qualify login, a new
owned inquiry, spoken banking facts or a complete release.

## Run locally

Requires Node 22 or newer.

```powershell
cd C:\Users\Moe\Documents\GitHub\factored-hackathon-2026\avatar
npm ci
```

Keep your existing credential in ignored `openrouter.env`:

```dotenv
OPENROUTER_API_KEY=your-key
```

Set the explicit provider in ignored `.env`:

```dotenv
AVATAR_VOICE_PROVIDER=openrouter-native
```

Keep credentials out of source control and browser variables. The server reads
`.env`, `openrouter.env` and `gemini.env`; restart it when changing configuration.

```powershell
npm run dev
```

Open [the local world](http://127.0.0.1:4317), click the eyes, and allow microphone
access. The avatar sends completed utterances directly to GPT Audio and plays its
streamed native reply. Speak over the reply to stop it while retaining your new
utterance. Recognition runs separately for captions and presentation intent; it
does not generate the voice. The long-lived key stays on the server. Camera input
is reserved for a later addition. Direct Gemini Live remains an alternative;
its natural conversation is unverified here because of the billing prerequisite.

The historical `AVATAR_VOICE_PROVIDER=personaplex` adapter remains wired into the
game. It requires an operator-prepared, ready, bounded worker lease configured
through `AVATAR_PERSONAPLEX_LEASE_FILE`; clicking the eyes cannot start a GPU.
The launch chooses one fixed Moss, Orbit or Spark role and the reviewed NATM1
voice. Earlier provisional voice feedback was superseded by the user's rejection
of this English voice for the Spanish/Portuguese product. A bounded browser audition
with public prerecorded microphone audio passed native duplex, audible VAD
interruption, mute and cleanup checks. Physical microphone/AEC behavior and a
natural human conversation remain separate checks. It supplies native continuous audio and
assistant captions. Optional `AVATAR_BACKGROUND_ASR=openrouter`, with the existing
server-side OpenRouter key, recognizes completed user utterances for transcript
and intent-based scenery. One actual public rice-cooking request was recognized
and delivered to Game while native audio continued; physical microphone/echo
and broader recognition accuracy remain unverified. The launch role stays fixed;
no bank request or native
result narration is triggered by the observer's default configuration. A separate
`AVATAR_NATIVE_READ_BRIDGE=readonly` candidate can opt in to visible owned read
inquiries when Savia is configured, with a durable native playback hold and
caption-only actual results. Its historical Game/hold/identity checks and
production image passed; these predate the native OpenRouter adapter.
Joined actual spoken inquiry acceptance is separate.
Recognition pauses while the
pond is open and resets on mute, identity changes and disconnect. Typing or choosing another character ends
that voice session and continues visually. A consumed lease needs a new operator
audition before voice can start again. See the
[supervised host-Node setup](docs/SUPERVISED-NATIVE.md),
[relay contract](docs/PERSONAPLEX_RELAY.md) and
[self-hosted assessment](docs/SELF-HOSTED-VOICE.md).

An `openrouter.env` key can remain alongside the native voice configuration.
OpenRouter supplies the endpointed native audio adapter, while direct Gemini/OpenAI
use persistent Live transports. The existing Savia/FLUJO workflow performs account
reasoning. No credentials or upstream means
a silent visual preview with fictional example data.

## Controls

| Action | Control |
| --- | --- |
| Interrupt the companion | Speak over it, or press Space |
| Pause / settings | Escape |
| Type instead of speaking | T |
| Travel | Click the companion, or use the arrow keys |
| Open Savia | Click the pool or the in-world computer |
| Select companion, subtitles, reduced motion, microphone | Pause menu |

Sign in directly inside Savia. The companion moves its visible cursor to real
controls and enters an admitted request; its actual returned answer appears in
the embedded application. Compatible Gemini/OpenAI tools can return that public
answer to their voice session. Native OpenRouter can narrate a server-held,
single-use result receipt after a fresh account check. Enable the optional
read-only bridge as described in [the adapter setup](docs/OPENROUTER_NATIVE.md).
PersonaPlex has no such result channel: keyboard
fallback can show the real answer as a caption, but native bank narration stays
disabled. Passwords and access codes remain in the sign-in window. The installed
Savia service supports read-only inquiries; it does not file disputes or issue
refunds.

## Build and verify

```powershell
npm run check
npm run test:e2e
npm start
```

The production server serves the built world at
[port 4318](http://127.0.0.1:4318). Browser tests use installed Edge on Windows and
deterministic provider fixtures, without paid voice calls. Quantitative
microphone/AEC qualification and joined spoken authenticated inquiry are separate release gates.
The final source check passed TypeScript/Vite and 297 unit tests with one
optional installed-upstream skip. The clean native browser suite passed 16/16
cases in 40.9 seconds: eight hook, three movie and five visible-read cases,
including reconnect ownership, first-login ACK scope and speech animation during
background work. Actual production HTTP QA completed both native WAV turns with
strict completion/clean EOF and $0.0284 new cost. Its playback receipts were
simulated, and no ASR, Savia, physical microphone or GPU was used. The 24 kHz PCM
rate remains explicitly assumed. The new restricted image passed 41 runtime
checks; its clean build passed 289 tests with nine explicit ignored-fixture/
optional-upstream skips. Historical images and earlier cross-provider/world suites remain separate evidence in the
[current ledger](docs/OPENROUTER_NATIVE_VALIDATION.md) and release checklist.
The supervised preview on port 43941 was restarted with the final source/build;
refresh an existing tab to obtain a fresh local avatar session.
The historical host-Node PersonaPlex candidate requires at least
120 remaining worker seconds for a new voice start, while existing sessions
keep their original expiry. Actual browser voice acceptance and the
previous real owned-read evidence are recorded in the
[release checklist](docs/RELEASE-CHECKLIST.md).

See [architecture](docs/ARCHITECTURE.md), [operations](docs/OPERATIONS.md) and
[art direction](docs/ART-DIRECTION.md) for the provider contracts, container
deployment, source audit and visual assets.
