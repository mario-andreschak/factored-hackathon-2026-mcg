# Savia eyes and voice

`Eyes.tsx`, `eyes.module.css`, `audio.ts`, `utteranceObserver.ts` and
`../../public/avatar-audio-capture.js` come from
[flujo-avatar](https://github.com/flujo-app/flujo-avatar) at
`23955370541c93786db1840a40cf31c87aae2e90`. Edit them there and copy again.
They are formatted with this project's Prettier. Local adaptations: `Eyes.tsx`
drops the Next.js `'use client'` line and skips its animation loop where
`matchMedia` is missing (jsdom tests), and `UtteranceCollector` gains
`snapshot()` so the utterance can be recognized while it is still being spoken.
The collector waits for two continuous seconds of quiet, including recovery
after a capped recording; speech resuming within that window stays in one turn.

`useSaviaVoice.ts` is Savia's own hook. It keeps flujo-avatar's microphone
capture, end-of-utterance detection and approach: a finished utterance goes as
audio to a native audio model that answers in its own voice
(`/api/voice/turn`, `server/conversation.py`, the counterpart of flujo-avatar's
`openrouter-native.mjs`). Where flujo-avatar routes work through a separate
recognition lane, here the voice model itself hands bank requests to the Savia
chat with a tool call. Savia's verified reply is read through the configured
TTS provider, using the registered host prose with screen-only formatting
removed. The native model does not rewrite host results; simulation,
refund, resolution and human-response caveats remain in the exact TTS input.
Narration accepts only an exact, once-only reply registered by the host
for the current authenticated session. Re-reading the same team update does
not reissue consumed narration. Completed results queue while the person or
their companion is speaking; pending team snapshots remain on screen only.
Assistant text joins server conversation history only after a matching receipt
for every emitted PCM sample. Interrupted, malformed or failed synthesis gets
no complete receipt. MIME and fragmented container/error prefixes are checked
before the stream starts. The receipt proves playback of the received provider
bytes; it does not prove that the waveform voices the complete script or aligns
with the canonical caption. Waveform comprehension needs separate human
qualification. Result narration uses only 24 kHz TTS providers to preserve the
native browser event contract; dictation fallback still supports the provider's
configured sample rate. Host prose is split at 1200 characters and submitted
in full to TTS; emitted audio retains the existing 60-second bound. A longer
reply can take more time to speak than the previous short model retelling.
A result replaces one native completion with one synthesis request per chunk,
without an added ASR or validation-model call. Provider time to first audio
remains unmeasured.
When the native model is unavailable the hook falls back to dictation:
recognize, send through the chat, read the reply aloud. The speech fallback
likewise accepts only unused plain-text chunks of the actual host reply.
