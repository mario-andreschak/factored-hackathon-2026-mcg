# PersonaPlex browser adapter audit

Audited 2026-10-01, NVIDIA source revision `3428dfd95309a7f3c84fd93259ded0f810d1ff91`, matching the bounded Modal audition. This document proposes an adapter; no PersonaPlex browser provider, tool bridge, or cloud endpoint has been enabled by this audit.

## The blocking integration question

**The stock server cannot accept a backend public reply as text during a conversation.** Its receive loop handles only binary kind `0x01` audio. Other kinds are logged as unknown. Role text and voice embedding are loaded during connection setup. Reconnecting resets the streaming state. No tool call, tool result, generation-cancel acknowledgement, or user transcript is emitted by the server. A shared process lock admits one active conversation. These facts come from the pinned [Python server](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/server.py#L159).

The frontend protocol definitions include kinds for text, controls, and metadata. Their existence does **not** establish server support. Sending `0x02 + bank-result-text` or `0x03 + pause/endTurn` to this Python server cannot implement those features. The pinned [frontend encoder](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/src/protocol/encoder.ts) and receive loop differ here.

## Actual wire framing

Connect to the authenticated application relay, which opens the approved upstream `/api/chat?voice_prompt=...&text_prompt=...`. Upstream stock parameters belong to the relay, not the browser. Set `binaryType = 'arraybuffer'`.

| Kind | Supported direction | Payload |
| --- | --- | --- |
| `0x00` | Server → browser | Readiness acknowledgement; the server sends a single zero byte after prompt initialization. |
| `0x01` | Both | Stream fragments containing **Ogg Opus pages**, including stream headers. |
| `0x02` | Server → browser | UTF-8 assistant text token, with SentencePiece word separators converted to spaces. |

Do not assume raw Opus packets, WebM MediaRecorder chunks, PCM, or a separate Ogg stream per message. Keep one encoder/decoder stream for the session. The pinned [microphone implementation](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/src/pages/Conversation/hooks/useUserAudio.ts#L61) emits pages, and the pinned [decoder](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/public/assets/decoderWorker.min.js#L117) parses Ogg boundaries and packet lacing.

Allocate frames without spreading large arrays:

```ts
const frame = new Uint8Array(page.length + 1);
frame[0] = 1;
frame.set(page, 1);
socket.send(frame);
```

## Exact codec sources

Use `opus-recorder@8.0.5`, the exact version in the audited NVIDIA [package lock](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/package-lock.json#L4833), rather than a runtime CDN or an unpinned latest codec. Its npm tarball is `https://registry.npmjs.org/opus-recorder/-/opus-recorder-8.0.5.tgz`, with integrity `sha512-tBRXc9Btds7i3bVfA7d5rekAlyOcfsivt5vSIXHxRV1Oa+s6iXFW8omZ0Lm3ABWotVcEyKt96iIIUcgbV07YOw==`.

- Encoder: npm `dist/encoderWorker.min.js`; the published encoder carries embedded WASM. Vite may import this file with `?url` and give the resulting same-origin path to Recorder.
- Decoder: npm `dist/decoderWorker.min.js` plus adjacent `dist/decoderWorker.min.wasm`. Keep their stable filenames together in `public/voice-codecs/opus-recorder-8.0.5/`, or explicitly supply the WASM location when wrapping the module.
- Recorder wrapper: package root/`dist/recorder.min.js`. Provide the existing `MediaStreamAudioSourceNode` as `sourceNode` so the app owns one microphone stream and one AudioContext.
- Licenses: Recorder MIT; bundled libopus BSD and Speex DSP BSD. The upstream [combined license notices](https://github.com/chris-rudmin/opus-recorder/blob/v8.0.5/LICENSE.md) must accompany redistributed JS/WASM. The [upstream README](https://github.com/chris-rudmin/opus-recorder/blob/v8.0.5/README.md) identifies libopus 1.3.1, SpeexDSP 1.2.0, and Emscripten 2.0.31. NVIDIA's [client license](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/LICENSE) is MIT; model weights have their separate NVIDIA license.

Mirror the official encoder configuration initially: mono, encoder sample rate 24000, 20ms Opus frames, two frames per Ogg page, streaming pages enabled, complexity 0, application 2049, resample quality 3. The input node can run at the browser's native 44.1/48kHz rate. Duration uses Opus's 48kHz granule clock.

Initialize the decoder with sample rate 24000, output rate `context.sampleRate`, and an integer buffer length near 40ms of output. The official client uses a timer and synthetic BOS prewarm. Prefer a small wrapper that acknowledges `Module.mainReady` and waits for the genuine first Ogg header; reject WASM failures and initialization timeouts. The [decoder source](https://github.com/chris-rudmin/opus-recorder/blob/v8.0.5/src/decoderWorker.js#L197) exposes that readiness promise.

Production CSP currently allows only self scripts. WASM needs the narrow `script-src 'self' 'wasm-unsafe-eval'` permission; keep worker paths same-origin. A relay preserves `connect-src 'self'`, rather than accepting arbitrary user-entered GPU URLs. [WASM CSP behavior](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/script-src#unsafe_webassembly_execution).

## Proposed `usePersonaPlex` contract

Keep the familiar state and lifecycle methods, but add explicit capabilities: `continuousAudio: true`, `textInput: false`, `livePersona: false`, and `toolResults: false` for the stock server. Unsupported `sendText` must return false with an explanation. `setPersona` must explain that voice/role changes start a fresh conversation, rather than silently pretending to update the active model.

Connection sequence: user gesture → AudioContext and single microphone → codec readiness → same-origin authenticated session admission → upstream prompt setup → `0x00` → begin continuous encoded pages. Tokenize assistant `0x02` output into a single caption stream with a quiet-gap boundary; the protocol provides no explicit turn completion. The current black-screen Game needs an input-activity callback to reveal the world, or an experimental transcript observer; an invented completed user caption would be incorrect.

Decoded output goes into a bounded AudioWorklet ring buffer, initially about 80–100ms, with real output-analyser metering. Speech phase follows audible energy, since a full-duplex server can stream encoded silence continuously. Handle queue overrun by dropping already decoded oldest PCM; **keep decoding every Opus page** to preserve codec state. Fail a persistently stalled input upload rather than replaying seconds-old microphone audio. The official [playback processor](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/client/src/audio-processor.ts) provides an adaptive jitter-buffer starting point, not a ready cancellation protocol.

For mute, disable the microphone track and continue encoding zero-valued audio. The server's inference advances with input audio frames; stopping upload freezes its conversation clock. This is an inference from the audited receive/inference loops, not a documented mute message. End voice closes everything: relay/socket, recorder, decoder worker, worklet queue, tracks, AudioContext, timers, and meters. Each reconnect creates fresh codec streams and suppresses late callbacks from the previous session.

Natural interruption remains continuous full-duplex speech. For immediate local barge-in, detect user onset, clear the audible queue, and duck output while preserving decoder processing. Resume after a short user-silence hangover and measure whether the model actually yields. A stop button can silence local playback until the next interaction; it cannot promise stock server cancellation. No bank task should be aborted by these presentation operations.

## Separate intent observer: an experiment

Fork microphone PCM locally, detect bounded utterances for an observer, and send only completed utterance audio to a separate STT/intent service. Continuous PersonaPlex speech remains the primary audio path; the observer drives `onTranscript`, mood presentation, and the existing authenticated `onTask` workflow. Tag observations and admitted tasks with utterance ID and account/session epoch. Deduplicate repeated transcripts, keep admitted reads independent of voice interruption, and show only the public result from the existing backend in the visible computer and captions.

This observer **does not make PersonaPlex know or speak the bank result**. A supportive stock persona must direct account work to the visible computer. Do not claim this arrangement provides tool-integrated voice. Feeding a TTS recording of a result into its user-audio channel is an unqualified workaround with role confusion, latency, and overlap; it should not be shipped as native tool support.

There is a possible model-level extension to investigate after the voice audition: pinned [`LMGen.step(..., text_token=...)`](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py#L725) can force a text token into the ongoing stream, and the audio depformer conditions on that token. A server-only authenticated result queue could preserve the streaming cache and feed a bounded public answer. This is **an inference from internal code, not a supported live API or proven speech mode**. It needs token/PAD pacing, exact amount/name pronunciation, interruption of a forced queue, truthful role/context behavior, and an A/B audition against free generation. It must not reset the model per utterance or let arbitrary browser strings become authoritative result text.

Acceptance must separately establish browser codec roundtrip, real microphone overlap, queue-clear timing, reconnect cleanup, mute clock continuity, and one visible owned bank read. The current offline 20-second audition establishes none of those browser/tool properties by itself.

The follow-up [PCM/forced-result experiment](PERSONAPLEX-PCM-EXPERIMENT.md) traces the internal token path further and supplies a local deterministic framing/scheduler prototype. It preserves the distinction between mechanically feasible cache-preserving injection and speech behavior that still needs model evidence.
