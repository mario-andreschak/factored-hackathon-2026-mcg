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
chat with a tool call. Registered host replies use a separately configured
result transport, with screen-only formatting removed. The RC selects
`native_exact`: one isolated request asks the existing native model to read the
complete host script. The server buffers all returned PCM and requires the
complete provider transcript to match after whitespace normalization before
releasing any audio. Changed claims, omitted caveats, unexpected tools,
incomplete streams and recognized encoded formats are refused. This compares
the provider transcript; it does not independently establish waveform alignment.
The default `tts` transport sends the same registered script in bounded chunks
to the configured dedicated speech provider.
Narration accepts only an exact, once-only reply registered by the host
for the current authenticated session. Re-reading the same team update does
not reissue consumed narration. Completed results queue while the person or
their companion is speaking; pending team snapshots remain on screen only.
Assistant text joins server conversation history only after a matching receipt
for every emitted PCM sample. Interrupted, malformed or failed synthesis gets
no complete receipt. Dedicated TTS checks MIME and fragmented container/error
prefixes; native exact checks its buffered transcript, completion and PCM.
The receipt proves playback of the received provider
bytes; it does not prove that the waveform voices the complete script or aligns
with the canonical caption. Waveform comprehension needs separate human
qualification. Both result transports preserve the browser's 24 kHz protocol
and 60-second audio bound; dictation fallback supports its configured sample
rate. TTS submits complete host prose in 1200-character chunks; native exact
submits the joined script once, without an added ASR or validation-model call.
The [October 5 live result audit](../../../docs/submission/measurements/native-canonical-live/README.md)
records two exact ES/PT captions and product-UI full-playback acknowledgments,
with 12.90/16.55 seconds of actual audio. Its UI checkpoints use elapsed browser
run time; provider time to first audio, cost and human comprehension remain
unmeasured.
When the native model is unavailable the hook falls back to dictation:
recognize, send through the chat, read the reply aloud. The speech fallback
likewise accepts only unused plain-text chunks of the actual host reply.
