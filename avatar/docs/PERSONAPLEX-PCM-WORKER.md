# Bounded native PCM worker

`experiments/personaplex_pcm_server.py` is the source for one private Modal Sandbox voice session. It is natural conversation only: there is no text-input, tool-result, forced-bank-reply, or live-persona route. The separate [forced-result audition](PERSONAPLEX-FORCED-RESULT-AUDITION.md) does not enable those capabilities here.

## Startup contract

The launcher copies the worker, `personaplex_pcm_core.py`, and `personaplex_modal.py` into `/root`, then runs `python /root/personaplex_pcm_server.py` on port8080. Trusted launch environment selects `PERSONAPLEX_AVATAR` (`moss`, `orbit`, `spark`), explicitly qualified voice `PERSONAPLEX_VOICE=NATM1.pt`, opaque `PERSONAPLEX_LEASE_EPOCH`, `PERSONAPLEX_MODEL_DIR=/opt/personaplex-weights`, and `PERSONAPLEX_DEADLINE_SECONDS=600`. All personas initially share that voice; role prompts differ. Voice/role changes need a new isolated session.

The private image contains the five pinned model assets, `voices/NATM1.pt`, and `revision.json` with exact `source_revision`, `model_revision`, and a `sha256` map for those six files. The worker checks pins, source HEAD, local paths and hashes. Model loading uses explicit local files. A narrow lookup guard resolves any HF helper request only to that verified file map. Runtime HF credentials are rejected, and offline environment is set before model helper imports. It never downloads weights.

One executor thread owns model loading, CUDA warmup, prompt setup and every subsequent Mimi/LMGen step. Resets occur during initialization only. `/tmp/personaplex-ready` is created after actual model/prompt warmup, never merely after HTTP starts, and removed on session end/deadline/failure. Model initialization and the launcher's readiness wait each have a 240-second bound. The worker initialization deadline is the earlier of that bound and its overall deadline; successful initialization consumes part of the existing 600-second lifetime. The Sandbox supplies the hard process deadline if Python cannot cancel a GPU operation. There is no automatic retry or checksum/cache-verification bypass.

Startup now emits flushed JSON milestones with fixed `status:'native_startup'`, fixed `stage`, cumulative `elapsedSeconds`, and preceding `stageSeconds`. Stages cover initialization, verified asset hashes, source revision, imported modules, loaded Mimi, loaded LM, streaming setup, completed CUDA warmup, completed prompt setup, and published readiness. No paths, credentials, environment, provider exceptions or prompt text are accepted by this diagnostic emitter. A cancelled readiness RPC alone cannot identify the expensive stage; these milestones separate cold cached-image reads from model loading and warmup without enabling runtime downloads.

A later actual attempt exhausted the former 180-second readiness allowance: cold asset hashing reached `assets_verified` at 152.205 seconds, CUDA warmup at 174.309 seconds, and `prompt_ready` at 178.827 seconds after worker initialization began. Container startup also consumed roughly three seconds of the launcher window. The launcher recorded cancellation at 180.618 seconds and confirmed termination; there was no observed OOM or model exception. The new 240-second allowance gives that measured cold-read case headroom while retaining every hash check and the exact 600-second Sandbox limit. It is a source-bound change, not evidence that another actual attempt passed.

## Authenticated HTTP and native stream

Modal Connect Token authentication is the security boundary before this private worker port. Both routes require the tunnel-injected `X-Verified-User-Data` JSON exactly `{leaseEpoch: <launch epoch>}`. Parsing this header would not authenticate a standalone public deployment. No raw tunnel or public unauthenticated worker is supported.

`GET /healthz` returns only `{ready,protocol,avatar,sourceRevision,modelRevision}`. `GET /api/chat` requires a WebSocket upgrade and admits **one connection ever**. A second connection is rejected before model mutation; disconnect ends the worker rather than sharing its conversational cache with another user.

Readiness is JSON `{type:'ready',protocol:'personaplex-pcm-v1',sampleRate:24000,frameSamples:1920,format:'pcm16le'}`. Input binary is `0x10` plus complete signed16LE mono24k samples, accumulated into1920-sample/80ms native frames. Output binary is `0x11`, uint32LE generation, uint64LE global output sample index, then PCM16. The global sample clock continues through interruption, including a discarded in-flight output frame. Client/relay must unset their exact next-index expectation on generation change, accept the next global index, then enforce contiguity.

Input backlog including a partial frame is bounded to480ms, control queue to8, and interrupt IDs to512. There is a3s continuous-input stall timeout,2s completed-model-step timeout,1s egress timeout, and inclusive worker deadline. Muting must continue sending zero PCM; stopping capture stops the native clock and ends this connection.

The only JSON input control is `{type:'interrupt',id}`. Each new ID increments presentation generation exactly once and receives `{type:'interrupted',id,generation}`; duplicates repeat their original acknowledgement. Controls arriving during GPU computation are handled before that output is published, and its older audio/caption is dropped. This clears presentation, preserves cache, and lets native user audio drive the model's natural interruption response. It does not erase speech tokens from the neural cache or prove barge-in quality.

Assistant caption events contain `{type:'transcript',id,role:'assistant',text,done,generation}`. IDs are unique across streams; text is bounded, Unicode-safe, and completed after a quiet gap. They are generated agent text, not user ASR or externally verified spoken facts. The worker emits no user transcript and accepts no backend result text. Errors exposed to the client are fixed categories, never arbitrary upstream messages or request contents.

## Local evidence and remaining acceptance

Twelve worker tests pass using a fake model without torch/Modal/GPU. They exercise the actual aiohttp routes and WebSocket, lease metadata auth, readiness, one admission, exact PCM bytes/clock, one executor owner, interruption during computation, duplicate ACKs, teardown suppression, deadline, queues, pins/checksums/local lookup guard, caption generation/size/lifecycle, and fixed startup-diagnostic timing/privacy bounds. New boundary cases verify that initialization never extends the existing lifetime and that a timed-out initializer cannot later publish readiness. The worker and launcher checks together pass 34 local cases, including matching 240-second startup bounds and the unchanged 600-second/no-retry source plan.

```powershell
python -m unittest discover -s experiments -p test_personaplex_pcm_server.py -v
```

These establish implementation wiring, not model speech quality. The NATM1 offline audition received provisional positive feedback, later superseded by rejection of this English voice for the LATAM product. The real forced-text/cache/timing experiment is separate evidence. Real Game/microphone/relay/native-output interruption and mute continuity still require the explicit bounded browser audition. Bank narration remains gated because the forced-text audition's name was unclear to ASR and free continuation added an unsupported future promise.
