# Prepared forced-result model audition

Status: **prepared, not dispatched**. This follows the successful basic PersonaPlex voice audition. It qualifies a separate experimental path before any bank-result voice integration. Neither the Game provider nor a cloud service was changed during preparation.

The runner reuses `personaplex_modal.build_image()`, the successful Python3.11 image/dependency pins, source revision `3428dfd95309a7f3c84fd93259ded0f810d1ff91`, model revision `fdaf4090a61cb315c138a1faee287ffd6c716309`, voice `NATM1.pt`, and seed42424242. It adds only its own source modules. The Modal function remains source-backed, one A10080GB container, no retries, no volumes/endpoints,600s runtime timeout and60s startup timeout. Planning does not import Modal/torch, read a token, or access a network. Execution is a separate explicit command.

## Fixed synthetic result

> Mira Chen, the payment of forty two dollars and seventeen cents has no open dispute. No action was taken.

This is fabricated fixture data, with no account, dispute, or banking access. The result is injected server-side through the internal `LMGen.step(codes, text_token=...)` path. Only agent text is forced; agent audio remains sampled and user audio continues. The worker uses the existing [NVIDIA PCM encode/step/decode pattern](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/offline.py#L236), rather than sending result audio into the user channel.

The candidate schedule is explicit: tokenize each word with the exact pinned SentencePiece model, emit its lexical tokens one per80ms native step, then PAD3 twice and EPAD0. Sentence-final words use six PAD3 frames before EPAD0. This timing is deliberately an experiment, not a claim of correct speech alignment. The schedule is bounded to256 frames (20.48s). Lexical BOS/EOS/PAD/EPAD/unknown IDs are rejected. The [internal token cache and audio conditioning](https://github.com/NVIDIA/personaplex/blob/3428dfd95309a7f3c84fd93259ded0f810d1ff91/moshi/moshi/models/lm.py#L725) make this path mechanically plausible; intelligibility needs listening evidence.

## One continuous conversation

| Phase | Native-clock duration | Input and generation |
| --- | --- | --- |
| Prelude |4s | First4s of NVIDIA's pinned public user-audio fixture; ordinary generation. |
| Ready silence |2s | Zero PCM; ordinary generation. |
| Public reply | At most20.48s | Zero PCM; explicit agent text schedule, sampled audio. |
| Settle |2s | Zero PCM; ordinary generation resumes. |
| Continuation |8s | Next8s of the same public fixture; ordinary generation. |
| Tail |4s | Zero PCM; ordinary generation. |

Maximum total model clock:40.48s. Actual duration depends on the pinned tokenizer's fixed reply length. Raw signed16LE mono24k input is accumulated across4097-byte chunks into1920-sample frames, preserving the framing experiment's awkward-boundary checks. This offline loop advances the same native sample/frame clock; it is not wall-clock paced and does not qualify a browser WebSocket.

All normal initialization, warmup, voice/system prompts, and resets occur before this timeline. During it, the worker checks that the LM streaming object/cache allocation remain identical, the LM offset advances exactly once per frame, and Mimi streaming remains active. After the reply it omits `text_token` and runs175 ordinary frames without resetting. The continuation recording is generic public user audio; it does **not** ask about the injected amount. Thus it can demonstrate continued free audio generation, but cannot establish comprehension of a bank result.

## Artifacts and interpretation

- `input.wav`: the exact composed user/silence timeline.
- `response.wav`: full generated PCM16 mono24k audio.
- `forced-result.wav`: the injected result plus2s settling, for convenient listening.
- `continuation.wav`: post-result public-audio continuation and tail.
- `token-stream.json`: every frame's phase, forced ID, emitted agent text ID/piece, LM offsets, output sample index, encode/step/decode/total timing, and cache invariant.
- `report.json`: explicit word/frame plan, contiguous forced-token match, full agent text stream, phase boundaries, timing percentiles/80ms misses, instrumented compute real-time factor, GPU peak memory, and qualification flags.

`forced_ids_match` means the model emitted the scheduled text IDs. It is **not** external ASR or proof that the audio said those words correctly. CUDA synchronization makes timing instrumented completed-frame compute time; it omits network/browser latency and adds measurement overhead. Report flags for pronunciation, tool understanding, and browser barge-in remain false until independently qualified.

Review the isolated source before any GPU dispatch:

```powershell
python experiments/personaplex_forced_result.py --plan
python -m unittest discover -s experiments -p test_personaplex*.py -v
```

The prepared execution command, for the coordinating agent after source review and within the user's existing compute authorization:

```powershell
python experiments/personaplex_forced_result.py --execute
```

Execution verifies existing gated-model access, uses an ephemeral token, runs one bounded function, and terminates its container even on failure/client timeout. It captures upstream diagnostics rather than forwarding arbitrary errors or signed URLs. Artifacts return under `.local/personaplex-forced-result/<timestamp>/`. The inherited maximum-runtime estimate remains under$1 including the stated startup allowance; image building and provider billing behavior remain separate from that estimate. No preparation command spends compute.

Local tests verify default non-dispatch behavior, explicit PAD/EPAD ordering and bounds, exact timeline/sample preservation, one continuous callback with forced then free steps, PCM output limits, and token-evidence matching. These do not import model dependencies. A successful real run still needs listening for Mira Chen, the exact amount, the no-dispute/no-action wording, natural pacing, and post-result audio continuity before deciding whether to proceed. If this schedule fails, adjust an explicit schedule and audition again; do not ship text IDs as a substitute for audible correctness.
