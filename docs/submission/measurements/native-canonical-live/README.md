# Native canonical guidance audit

The bounded live browser run completed on 2026-10-06 from 00:33:43.597 to 00:34:54.490 UTC (70.894 seconds). Application source is `6219bc81a8a4c7f2936769e7727e5146dd2713d0`; image is `sha256:9aa240aa6fd4616e2f029d6667ea234aa7ec8f7c1c8e1eef7a918d640a1b8b9d`. The [public receipt](receipt.json) links canonical text, real audio hashes, screenshots, timings and the exact source/image proof.

| Case | Exact host/caption match | Actual mono PCM16 at 24 kHz | Product UI ACK |
|---|---|---|---|
| Spanish, fictional Mexico profile | Yes | 309,600 samples; 12.9 s | 309,600 samples, once |
| Portuguese, fictional Colombia profile | Yes | 397,200 samples; 16.55 s | 397,200 samples, once |

Both turns came from normal product controls: start native voice, type a card-block hint, and send it. The registered host guidance was read through `native_exact`; the observer copied the actual browser fetch response without injecting a reply, audio or ACK. The UI emitted two exact complete playback ACKs. Two tampered results returned HTTP 409 before provider admission. Two provider-eligible result requests were observed, within the two-request/120-second cap.

The audio is **card guidance**. Each profile already owned a blocked fictional card. Its panel showed the verified state, and a separate status reread preserved the same saved-receipt digest. The live run performed zero prepare, confirm or cancel requests. A successful card-confirmation callback can narrate when voice is active; a status read does not invoke that callback. This capture therefore does not qualify narration of a newly confirmed block.

[Runtime verification](runtime-verification.json) preserves 183 checked source hashes, 22 retained browser files and four retained native runtime hashes. The source map distinguishes 149 application files and six standalone analytics CLI files at the new source, the unchanged 28-file portal at `4a734120`, and the retained browser build from `f3c57b26`. [Public asset verification](public-assets-verification.json) records the same runtime source/image and unchanged portal component. Analytics was not run.

The byte-exact [offline harness](offline-6219-harness.py) and [offline receipt](offline-6219-receipt.json) independently passed 43 HTTP checks in two ES/PT cases. They joined real local RC login and owned-card prepare/confirm/status APIs to the actual registered result, using scripted native SSE only. Exactly two fictional card blocks occurred in a disposable generated ledger that was removed afterward; external socket attempts and real provider calls were zero. All 183 source files were verified unchanged before and after. These mocks qualify the offline join, not live provider behavior.

Source qualification at `6219bc81` passed 107 voice tests plus one source-gate test with 89 protected-source subtests. A separate 32-source-gate result belongs to historical `5df3b026`; counts are not added across revisions. Historical `df957f99` and `5df3b026` evidence is preserved and is not relabeled as this live run.

[Artifact hashes](artifact-manifest.json) identify every public file and each byte-exact copy. The [observed live harness](live-harness.mjs) and raw offline files retain their original local paths as source provenance; no portability rewrite or dependency installation was performed. The live receipt is a whitelist extraction. Full private browser receipts, private runtime bindings, cookies, login/gateway credentials, capability handles and stacks are excluded.

The six screenshots are authenticated product snapshots at the harness checkpoints. Scrolled viewports can omit the avatar or card panel; screenshots alone do not prove active speaking or completed playback. Caption, PCM and ACK claims come from the observed product responses and controls. The Portuguese initial-status screenshot retains only generated card/receipt UI record identifiers, with no bearer capability or credential.

Provider usage and cost are unavailable and remain null. The product UI ACK follows its device-clock drain gate; physical hearing, microphone/AEC, spoken waveform/text alignment, human comprehension and fleet-wide acceptance were not measured.
