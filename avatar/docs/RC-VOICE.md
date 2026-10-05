# Final-day voice candidate

The local candidate is `http://127.0.0.1:43941`, with the isolated fictional
Savia portal at `http://127.0.0.1:43900`. Start that portal using
[`deploy/rc/README.md`](../../deploy/rc/README.md) first. Its private login
binding stays in `private/rc-runtime-20261004/measurement.json`; exclude login
codes and the login screen from public recordings.

From `avatar/`, build and start with the existing server-only configuration:

```powershell
npm run build
$env:AVATAR_PORT='43941'
$env:AVATAR_VOICE_PROVIDER='openrouter-native'
$env:AVATAR_NATIVE_READ_BRIDGE='readonly'
$env:SAVIA_UPSTREAM='http://127.0.0.1:43900'
$env:SAVIA_PUBLIC_ORIGIN='http://127.0.0.1:43900'
node --env-file-if-exists=openrouter.env server/index.mjs
```

The page shows an audio/provider notice before microphone activation. Wake
the world to start voice, or use **T** for typed input. Open the pond, sign in
inside Savia, and select a fictional movement. “Revisa los detalles de este
cargo” runs an owned read in the visible portal. Ask a useful follow-up while
it runs; foreground native audio remains available. The model receives
host-owned pending-read status and bounded verified display results, never
cookies, query scopes, transaction references or bank action capabilities.
The selected movement and Savia conversation stay in the mounted iframe
across closing and reopening the pond.

The completion receipt is single-use. Its audio waits for foreground
input/output to clear, and a fresh account check precedes narration. Speak
over a reply or press Space to interrupt it. End Voice releases capture; an
already submitted read can still finish visibly without being spoken into a
later voice session. Account changes clear old audio/history/results.
Follow-up opt-in and status are available in Savia's UI; voice cannot prepare
or confirm bank actions. A verified intake is not a resolution or refund.

Capture can listen for `savia:voice-milestone` on the avatar window. Each event
contains only `{event, at}` with `performance.now()` milliseconds. Names are
`task-start`, `task-complete`, `voice-start`, `voice-audio`, `voice-complete`,
and `voice-interrupted`. Network NDJSON completion events also expose bounded
provider usage and cost; omit authentication headers from evidence.

This adapter uses complete-utterance HTTP audio input and streamed PCM output,
with continuous local listening and local interruption. It is not a persistent
duplex provider websocket. The 24 kHz output rate remains an explicit adapter
assumption. Automated input/browser recordings qualify the recorded pipeline;
physical microphone, room echo and human voice-quality acceptance remain
separate checks. Voice history is bounded and in memory; Savia owns durable
customer history and follow-ups.

Native voice waits for two continuous seconds of silence before submitting
speech. A brief thinking pause stays in the same captured message; speaking
again before the deadline resets the silence window and appends to that audio.
Response interruption still starts promptly on new speech, and capped recordings,
mute and account changes keep their existing boundaries.

Production TypeScript/Vite build and the full unit suite passed (298 checks,
one optional upstream skip). Two subsequent compatibility checks passed in
the targeted 51-check suite, with one optional upstream skip. Eight existing
movie/read-bridge browser cases and one new held-read continuity case passed.
The queued-before-ready typed-input regression also passed after the setup
race was corrected.
An initial browser trace failure came from concurrent test output cleanup;
the isolated barge-in rerun passed. Browser provider/bank fixtures are
synthetic. Actual recording and latency results belong in
`docs/submission/measurements/`.

One independent actual GPT Audio call from a fictional typed Spanish concern
completed on October 4 at 19:34 Bogota time: first PCM in 1.370 s, completed
generation in 3.766 s, 12.2 s of speech, observed cost USD 0.0170785. Its
[report](RC-VOICE-PILOT.json) records source hashes and the exact reply. It
used no microphone, bank call, generic FLUJO call or browser playback ACK;
those results cannot be claimed from this pilot. The completed WAV is at
`avatar/.local/rc-voice-pilot/opening.wav` for the media lead to reuse.

`experiments/capture_release_audio.mjs` can attach to a Playwright page to
save actual completed native response audio and usage alongside browser
recordings. It does not initiate calls. `experiments/rc_voice_pilot.mjs`
requires `--execute` and refuses an already-recorded pilot; reuse its output.

One separate actual audio-input call completed at 19:57 Bogota time on
October 4. It sent only an existing public synthetic Spanish WAV (4.137 s)
to the current native provider: 41 input audio tokens, first PCM in 2.153 s,
completed generation in 3.935 s, 9.4 s of output, USD 0.014559. The
[report](RC-VOICE-AUDIO-INPUT.json) gives the fixture hash and exact utterance.
This qualifies prerecorded audio input; it does not qualify a physical
microphone, browser playback or a banking inquiry. Reuse
`avatar/.local/rc-voice-audio-input/reply.wav`; the guarded
`experiments/rc_voice_audio_input.mjs` refuses a second dispatch.

The first actual background browser capture failed before any banking query:
fresh authenticated portal state returned 401 from its action status endpoint
before a conversation existed, expiring the embedded session. Its partial
private evidence is retained at `private/rc-voice-background-20261004/`.
It is not accepted evidence of background overlap or completed playback.
The portal status defect was repaired and a fresh login/auth/status preflight
then returned 200 for all three endpoints. The real frontend also exposed a
second compatibility issue: speaker labels and rendered Markdown changed the
reply's DOM text. The workbench now reads Savia's passive original-reply data
attribute, retaining the server's strict receipt match. The two focused browser
cases passed with a fixture that includes the real speaker-label/formatting
transformations.

The third actual browser capture qualified foreground/background overlap:
one real inquiry ran for 7.399 s; foreground native PCM began while it was
pending, and its 10 s reply completed with a server-accepted played receipt.
The result waited for that foreground drain and was spoken once with another
accepted played receipt. The initial response was interrupted. The backend
inquiry itself failed with `invalid_date_window` (`TOOL_ERROR`/R9); its spoken
result reported that failure honestly. This is concurrency proof, not a
successful banking answer. The [bounded receipt](RC-VOICE-BACKGROUND.json)
records source hashes, counts and timing. Selected fictional WAVs, visual-only
WebM and timing evidence are saved under
`docs/submission/measurements/voice-overlap/` for media reuse. Typed input and a
file-backed silent microphone were used; prerecorded speech input is qualified
separately above.

The minimal inquiry-team bridge is now included. Its mounted Savia frame emits
only an actual case pointer and event cursor. The avatar verifies frame origin
and source, fetches `/api/assistant/voice-update` through its fixed authenticated
proxy, and binds the canonical reply to the existing strict single-use receipt.
The update queues behind foreground speech and is revoked on account or voice
ownership changes. Repeated event/copy updates are suppressed. Historical closed
inquiries and queued/working snapshots stay visible without automatic speech;
the useful completed result can be announced once.

One actual new informational case on the selected fictional Nébula movement
completed two real workers. Its useful 9.4 s native update was heard once with
a server-accepted full played receipt. It created no banking chat, bank action,
refund or human work. The [qualified receipt](RC-TEAM-VOICE.json) links the
accepted WAV and visual-only video. Earlier pending-state audio overstated
progress and is rejected for media; that concrete failure motivated the final
pending-state suppression guard. The completed path is unchanged, and the final
guard's focused browser test and production build passed without another paid
probe. Full unit verification passed 304 checks with one optional skip; three
focused continuity/update browser cases passed.
