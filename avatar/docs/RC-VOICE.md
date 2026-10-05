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

Production TypeScript/Vite build and the full unit suite passed (298 checks,
one optional upstream skip). Two subsequent compatibility checks passed in
the targeted 51-check suite, with one optional upstream skip. Eight existing
movie/read-bridge browser cases and one new held-read continuity case passed.
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
