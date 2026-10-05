# PersonaPlex PCM and forced-result experiment

Audited 2026-10-01 against NVIDIA source `3428dfd95309a7f3c84fd93259ded0f810d1ff91`, with model revision `fdaf4090a61cb315c138a1faee287ffd6c716309`. This is a design and local deterministic prototype. It is not an enabled provider, GPU endpoint, or qualified speech feature. The [stock adapter audit](PERSONAPLEX-ADAPTER.md) remains applicable.

## Answers from the pinned implementation

**Raw PCM can replace Ogg Opus in a custom endpoint while preserving the native model clock.** Mimi is configured for mono 24000Hz audio and 12.5 frames/second, giving 1920 samples every 80ms. Opus is the stock server's transport codec; it is decoded before the existing Mimi encoder/model/decoder path. A PCM endpoint can feed the same path directly. Keep the Mimi codec, streaming contexts, and model weights unchanged. This follows from the [model loader configuration](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/loaders.py#L36) and [stock inference loop](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/server.py#L191).

**A public-result token queue can mechanically advance the existing stream without resetting it.** `LMGen.step` accepts an optional `text_token`; its cache records that token as provided, and the audio depformer conditions on the provided text. Text delay is zero; several audio codebooks have a one-frame delay. The existing state continues to advance. This is an inference from the internal [step/cache implementation](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py#L681), [provided-token selection](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py#L818), and [delay configuration](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/loaders.py#L116).

It controls the agent's single text stream, not a separate tool-result/context channel. Intelligible, accurately timed result speech is unproven. One token per 80ms is not automatically correct pronunciation timing. PAD3 and end-padding0 exist, but their placement must be qualified against real audio. The prototype deliberately accepts an explicit candidate frame schedule instead of inventing an automatic speech planner. It rejects mid-session BOS/EOS. No resetting, replaying voice prompts, or supplying forced agent audio belongs in ordinary result delivery.

## Minimal isolated prototype structure

1. **Authenticated session relay:** an experimental same-origin route admits one session before touching any shared model state. Fix the approved voice/persona on the server. Reject a busy worker immediately. Bind all messages and results to the authenticated account plus session epoch.
2. **One model owner:** initialize/reset once at connection start, run the normal voice/system prompt setup, and send readiness. Only then accept continuous input. A bounded reader queue delivers PCM and controls to one inference loop; other tasks must not mutate Mimi or LMGen. A task completion posts a result plan to that owner.
3. **PCM transport:** capture using the existing worklet, continuously resample to 24000Hz, and send signed16 little-endian mono samples. Carry partial samples/frame data across chunks. Divide by 32768 before creating the model input tensor. Accumulate exactly 1920 samples, Mimi-encode, step each resulting code frame, decode the usual agent codebooks, clamp/quantize output to PCM16, and play it through a bounded worklet buffer. No WAV headers or codec reset per WebSocket message.
4. **Public result queue:** only the existing authenticated backend can submit a bounded public answer. Tokenize with the exact pinned SentencePiece model; create an explicitly timed candidate plan. Deduplicate task IDs, reject old epochs, and cap four pending plans/256 frames per plan. For each native model step, supply either one planned text token or omit `text_token` for free generation. Keep microphone audio flowing throughout.
5. **Separate intent observer:** independently derive user transcripts/intent from bounded microphone segments, admit the existing bank read once, and deliver its public result to this queue. The stock native model does not emit user ASR or tool calls. This observer remains experimental and is not implemented by the prototype.

At PCM16, each direction carries 48000 bytes/second: about 768kbit/second duplex before framing. The browser avoids the Opus WASM dependency/CSP change at the cost of higher bandwidth. An input backlog exceeding the candidate 480ms bound fails the session rather than replaying stale speech. Measure actual GPU frame deadlines; a transport test cannot establish real-time inference performance.

## Candidate framing and interruption policy

Use a new versioned route, for example `/api/avatar/personaplex-pcm-v1`. It is incompatible with the stock `/api/chat` Ogg stream. Before audio, the relay sends JSON readiness containing protocol version, sample rate 24000, PCM16LE format, frame samples 1920, and session epoch. Input binary is kind `0x10` followed by contiguous PCM. Output binary is kind `0x11`, uint32LE presentation generation, uint64LE output sample index, then PCM. JSON controls contain bounded IDs/events only; browser text must not become a trusted bank result. The local prototype implements output packing and framing/scheduling, not the route or authentication.

On user onset, clear local playback immediately, suppress the remainder of any active forced plan, and defer pending results through a measured quiet hangover. Continue every input frame, including zero audio while muted; stopping input freezes this implementation's inference clock. Bank reads that were admitted continue. Their later result may be queued once when speech can resume. An interrupted forced utterance is not automatically replayed midway through a word.

Generation tags discard output that was already queued before interruption. They do **not** erase tokens or delayed audio inside the model. Audio generated after cancellation may still continue a word from the preserved cache. Ducking through user speech helps presentation, but a truthful server cancellation guarantee requires a real overlap audition. A new account/disconnect invalidates the queue, closes the socket, and suppresses late results. A new session gets fresh state; a result does not.

## What is verified locally

`experiments/personaplex_pcm_core.py` uses only Python's standard library, with a fake injectable model step. Nine tests cover irregular byte/frame partitions, PCM endpoint conversion, truncation/backlog rejection, output generation/sample clocks, token/PAD order, bounded deduplication/epoch rejection, free/forced-speech presentation invalidation with pending-result deferral, late teardown suppression, and continuous zero-audio steps during mute/interruption. They establish wiring behavior only. No weights, GPU, network, paid calls, or Game/provider changes are involved.

```powershell
python -m unittest discover -s experiments -p test_personaplex_pcm_core.py -v
```

## Required model qualification before integration

| Experiment | Evidence required |
| --- | --- |
| PCM versus stock Opus | Same initial prompt/user recording; retained full-duplex behavior and acceptable latency/audio quality. |
| Forced public result | Exact amount, date, merchant/name, short denial and success summaries spoken correctly; compare several explicit PAD/end-padding schedules. |
| Continuation | After the result, a follow-up question referring to it receives a consistent answer without replay/reset. |
| Mid-result barge-in | Clear local audio promptly; measure residual model speech, cancellation behavior, user intelligibility, and recovery after the overlap. |
| Background completion | Result arriving during user speech waits; one read and one public summary; canceled speech never aborts the read. |
| Lifecycle/isolation | Mute maintains clock; stalled uplink fails cleanly; second session rejected before state mutation; account switch/reconnect never delivers old content. |

The bounded offline voice audition validates basic model/audio execution only. It cannot qualify this forced-text extension, browser transport, interruption, or bank-result integration.

The prepared [forced-result model audition](PERSONAPLEX-FORCED-RESULT-AUDITION.md) now supplies a bounded real-model runner using the successful pinned image. Preparing it launches nothing; its evidence remains pending until the coordinating agent executes and listens to the actual output.
