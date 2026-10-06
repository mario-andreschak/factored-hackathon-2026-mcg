# Voice ACK successor live evidence

The fresh c44 browser completed two observed language cases across two attempts. The initial planned ES/PT batch **failed after successful ES playback, before PT case creation**, during an unrecorded authentication response wait. Its saved receipt cannot distinguish the profiles wait from the login wait. Root then approved a separate PT-only continuation, which passed. The original batch remains failed.

| Observation | ES partial attempt | PT continuation |
|---|---:|---:|
| Actual provider-eligible result requests | 1 | 1 |
| Exact product UI playback ACKs (HTTP 200) | 1 | 1 |
| Tampered result rejections (HTTP 409, provider-ineligible) | 1 | 1 |
| PCM samples at 24 kHz | 399600 | 370800 |
| Captured seconds | 16.65 | 15.45 |

Across the two attempts: **2 actual provider turns, 2 UI ACKs, 2 negative checks, and 0 new card writes**. Existing blocked-card state and saved receipts were observed separately; these are guidance playbacks, not newly narrated block actions.

- [Combined public receipt](receipt.json)
- [Initial failed batch with successful ES case](attempts/es-partial-failed-batch.json)
- [Successful PT-only continuation](attempts/pt-continuation.json)
- [ES captured audio](native/es.wav) and [capability-redacted events](native/es.ndjson)
- [PT captured audio](native/pt.wav) and [capability-redacted events](native/pt.ndjson)
- [Runtime byte proof](runtime-verification.json), [public assets](public-assets-verification.json), and [read-only card continuity](card-status-continuity.json)
- [Independent portal verification](portal-successor-c44d416f-verification.json) and [external destination HEAD checks](portal-external-destinations-634aa524.json)
- [Root continuation approval scope](continuation-root-approval.json), [original/derivative SHA mapping](bundle-manifest.json), and [privacy review](privacy-review.json)

Application/browser source: `c44d416fcf1ab95bcb16c77651418e6570d79782`, tree `fabf02d622f51302e229137405e3607356d00ab0`. Actual image: `registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c`. Runtime checks verified source183/freshUI21/native4/portal28/media16; public HTTP checks verified27 portal assets; card continuity used12 checks across2 fictional profiles with0 writes/providers. Portal bytes retain source634; critical native server bytes retain source6219.

Live checks used the normal product UI and emitted real playback receipts. No ACK failure was injected live. Five ACK recovery cases and the148-test frontend suite are separate offline evidence. Exact caption matching does not prove waveform/text alignment or physical hearing. External film checks were HEAD-only; no full film playback is claimed. Raw build stages are a truthful structured transcription, not recorded terminal byte identity.

Public WAVs preserve the exact passive captured PCM. Public NDJSON omits turn receipt capabilities while preserving audio chunks, captions, sample counts, and event order. Private configuration, bindings, login codes, cookies, storage state, signed URLs, screenshots and videos are excluded. Original6219 proofs and both private actual attempt receipts remain unchanged.
