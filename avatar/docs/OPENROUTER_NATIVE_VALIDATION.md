# Current native adapter validation

Snapshot: 1 October 2026. This is the current evidence ledger for the explicit
`openrouter-native` adapter. It supersedes pending-status summaries in earlier
development receipts, while preserving every historical failure and spent
admission. The complete release goal remains open.

## What has passed

| Check | Result | Scope |
| --- | --- | --- |
| Source aggregate | TypeScript/Vite build; **297 unit passes, 1 optional installed-upstream skip**, 298 total | Final ownership/account-scope/animation source; deterministic/local fixtures |
| Clean native browser suite | **16/16 passed in 40.9 seconds**: 8 hook, 3 movie, 5 visible-read cases | Synthetic microphone/provider/Savia transports; capture, playback, talk-over, cleanup, reconnect owner, first-login ACK scope and speech animation during background work |
| Actual production HTTP QA | **2/2 native audio requests completed** with strict NDJSON completion and clean EOF | Actual production server/module and provider; hash-pinned public Spanish/Portuguese WAV input; no observer ASR or banking |
| Human Spanish interaction | **Accepted** at the built preview on port 43941: the user described Spanish conversation/talk-over as "amazing" and "excellent" | Human-reported feel/voice acceptance; Savia and read bridge disabled; no quantitative AEC/device measurement |
| Restricted production image | **Passed: 41 runtime checks**; clean build **289 passes / 9 skips**, 298 total | Current native image; no provider keys, lease, Savia or paid calls; exact owned containers removed |

The clean 16-case native suite supersedes the earlier native focused-run status,
including one browser launch that exhausted Windows commit before setup. That
failed launch remains historical evidence. These 16 cases are the native suite,
not a new full cross-provider/world browser aggregate.

## Actual production HTTP receipt

Ignored receipt:
`.local/openrouter-native-component-qa/2026-10-01T17-55-22-221Z/report.json`.
Receipt SHA256:
`2c9117b55e5eaad3b392eb5a1b8020d724850b997753c859d13141b7bfc2e831`.

The harness created the actual `createAvatarServer` on an ephemeral loopback
listener, obtained its session cookie/config, and submitted the two original
hash-pinned WAVs through `/api/avatar/native-turn`. Dispatch fixed
`openai/gpt-audio`, OpenAI only, Coral, PCM16, 512 completion tokens and 45 seconds;
there was no retry or fallback. Both responses contained nonzero PCM, cumulative
caption, exact completed sample count, bounded usage and clean EOF.

| Actual native turn | Spanish | Brazilian Portuguese |
| --- | ---: | ---: |
| First decoded PCM after HTTP request | 1,763.56 ms | 1,297.11 ms |
| Last decoded PCM | 3,794.33 ms | 2,858.20 ms |
| HTTP collection complete | 3,804.26 ms | 2,860.82 ms |
| PCM bytes / samples | 499,200 / 249,600 | 381,600 / 190,800 |
| Output duration under assumed 24 kHz mono rate | 10.4 s | 7.95 s |
| Input / output audio tokens | 41 / 208 | 50 / 159 |
| Actual reported cost | $0.0156815 | $0.0127185 |

These are request-relative decoded-byte timings, not first audible output or
microphone-to-answer latency. The HTTP stream finished before the corresponding
audio's playback duration. `/native-played` was submitted twice as an explicitly
**simulated server receipt**, not proof that a browser or person heard the audio.
The **24 kHz mono PCM16 rate remains assumed**; this run does not upgrade it to a
provider-established format guarantee.

New reported cost was **$0.0284**. Including the four previous native S2S calls
at $0.031058, the **six recorded controlled native probe requests** cost
**$0.059458**. This subtotal excludes the user's live-preview usage, Modal
charges and other research; it is not total account spending. The $0.10 planning
target was a forecast, not a provider-enforced spending limit. Portuguese was
admitted only after actual Spanish usage and forecast headroom were known.

The receipt records `sourcesUnchanged:true` and `serverClosed:true`. A subsequent
read-only check independently found **10/10 current fingerprints matching**:
native module, conversation ledger, app, Savia proxy, config, server locale,
native hook, playback, Game and QA harness. Full fingerprints remain in the
receipt. All prior report/marker proofs were pinned before admission. The actual
run used **zero ASR, dedicated TTS, Savia/bank, GPU or physical microphone calls**.
Its runtime profile had banking and the read bridge disabled. Public PCM/WAV and
caption artifacts remain in the ignored receipt directory; no raw SSE or provider
identifiers were stored.

## Restricted production image

Tag: `savia-elsewhere:native-20261001`, Linux/amd64.
Image ID:
`sha256:d4d4007fa7e7967286b6e19a15eba9fe136f8d4ccba6f585d669999c804f8ea2`.
Ignored evidence: `.local/docker-native-20261001/runtime-report.json` and
`build.log`. Runtime-report SHA256:
`7e6d4bc263467cc447352e2410feccedace0f3ef3a0081699e758dade8dbde25`.

The clean Docker context passed TypeScript/Vite and **289 tests with nine explicit
skips** (298 total, 7.99 seconds): eight require ignored local public WAV/prior
receipt proofs, and one is the optional installed-Savia test. These are the same
source suite's clean-context conditions, not nine failures or additional tests.

All **41 restricted runtime checks passed**. Two temporary containers used
loopback 43947/43948, UID 1000, production mode, read-only filesystem (`EROFS`),
all capabilities dropped, no-new-privileges, 256 MiB and 64 PID limits. Runtime
contained only `dist`, `server` and `node_modules/ws`; credentials, `.local`,
references, experiments, tests, docs and frontend source were absent. Page,
366,228-byte JS, 32,359-byte CSS and the exact 3,443,168-byte rigged GLB returned
200 with valid asset checksums/magic. Fourteen private paths returned 404, and all
six inactive native routes returned 503 without dispatch.

Local/public-gate profiles also checked Host, Origin, missing/wrong gateway
rejection and trusted Secure/HttpOnly/SameSite cookie issuance, without a gate
bypass. The earlier local Node-fetch Host-normalization harness failure remains
preserved; the final raw-HTTP run passed all 41 checks without a source change or
second build. Both owned containers were stopped/removed and their ports clear.
No provider credential, Savia target or lease was configured, and zero paid,
bank or GPU calls occurred. This qualifies packaging/default admission and the
local gateway boundary; it does not qualify public TLS deployment or audible
voice/banking acceptance.

## Historical evidence remains unchanged

The original Spanish S2S receipt, SDK-terminal correction and normalized-terminal
correction remain **three failed technical receipts**. The user's accepted
Spanish diagnostic audio came from the failed SDK-mode run; that listening
decision did not pass its terminal gate. The subsequent one-call Portuguese
metadata-tail experiment completed. Those four reported charges total $0.031058,
and all four old markers remain spent. The newer component run has its own
exclusive admission. See [the audition ledger](OPENROUTER_S2S_AUDITION.md) for
exact paths, hashes, shapes and charged failures.

PersonaPlex's English research receipts and rejected Qwen Chelsie ES/PT samples
remain historical. They do not qualify this product's required LATAM voices.

## Remaining release gates

The supervised read-only validation beta at `http://localhost:43942` now exposes
configured native voice/observer and the visible Savia read bridge. Its distinct
hostname isolates the host-only session from the bank-disabled voice preview at
`http://127.0.0.1:43941`; ports alone do not isolate cookies. Only component config
was verified during preparation, with no new Savia login or inquiry by root.
This is availability for human validation, not joined banking qualification.

- Portuguese subjective listening acceptance.
- Quantitative physical microphone/AEC, soft speech and acoustic interruption
  across the intended room/device setup; human Spanish talk-over approval alone
  is not that measurement.
- Actual acceptance of Moss, Orbit and Spark's three speaking styles and their
  matching presentation. They share Coral with separate instructions; cloned
  voices and actual three-style acceptance are not claimed.
- One joined spoken read-only request → visible owned Savia inquiry → accurate
  native result speech → heard-history continuation, with account ownership and
  uninterrupted background work. Local fixtures and separate historical real
  UI inquiry evidence do not close this gate.

Restricted container packaging/default-disabled admission has passed for this
source. That boundary does not itself qualify audible conversation, a bank
result or deployment availability.

This adapter uses completed audio input followed by streamed native output over
HTTP. It does not provide a persistent provider Realtime WebSocket or model-native
simultaneous listening. No additional paid probe, banking query or deployment is
authorized by this ledger. [Operator setup](OPENROUTER_NATIVE.md) describes the
explicit configuration and permission boundaries.
