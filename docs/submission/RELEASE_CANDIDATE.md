# Savia release candidate

**Current public product release — October 5, 2026, America/Bogota.**

Open the [submission portal](https://savia-rc-2026.fly.dev/submission/) for the human pitch, completed customer film, repository and development story. Try [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate and fictional-profile login. The [six-slide product pitch](media/decks/final/savia-final-pitch.pdf) follows Why → What → How; its [editable PowerPoint](media/decks/final/savia-final-pitch.pptx) and presenter notes share the final product narration.

## Current runtime and acceptance

| Component | Qualified source or observation |
| --- | --- |
| Application and standalone analytics sources | `f2fa597a481a87b5301531cf180f8f61d1f3ba70`, tree `1638e0be90b1046bbada1972b6ace1ee62a8e4fa`; 183 source entries: 149 application, six standalone analytics and 28 retained portal files |
| Retained browser build | Source `c44d416fcf1ab95bcb16c77651418e6570d79782`, tree `fabf02d622f51302e229137405e3607356d00ab0`; the same 21 files and committed-lockfile build provenance as the dated `c44d416f` release |
| Retained public portal and pitch | Source `634aa5244374b3e105ef7864fa100530bab45ec2`; all 28 tracked portal files unchanged, 27 public payloads; the retained 16-file pitch/media subset contains 12 pitch delivery files and four public assets |
| Running image | `registry.fly.io/savia-rc-2026@sha256:11854442ddd395614d8d9c7cd030d3256365941613a730657c6740406709827c` |
| Source and machine continuity | All 183 sources, 21 retained browser files and four native runtime files verified; complete current machine configuration preserved except image |
| Exact runtime source delta | `frontend/server/conversation.py` adds direct ES/PT imperative admission; `resources/dispute_workflow.flow.json` refreshes that protected source hash. This is the required source-only generated graph artifact; no FLUJO integration or browser/native rebuild |
| Public submission | All 27 allowlisted public payloads match; health and entry guard verified |
| Native request admission | Two actual `POST /api/voice/turn` message calls: `bloquea mi tarjeta` (ES) and `bloqueie meu cartão` (PT), each with one exact original-request delegate and a normal completed 24 kHz audio stream: 151,200 samples / 6.30 s ES and 57,600 samples / 2.40 s PT |
| Card ledger observations | Independent before/after owned-card status rereads preserve the existing saved receipts for both profiles; zero card writes |

[Current runtime and native-message admission receipts](measurements/native-card-admission/README.md) pin the actual application source, image, retained browser/native bytes, full configuration, public payloads and exact two-case event observations. The single successful two-case attempt took 18.542 s and made exactly two real provider message calls. These probes qualify native request admission. They do not establish ASR or microphone behavior, product-UI playback, `/api/voice/played` acknowledgment or full customer completion. A separate AI text review found no unsupported completed-action claim in the recorded captions; waveform/text alignment was not adjudicated.

The [dated canonical native playback](measurements/voice-ack-live/README.md) remains tied to `c44d416fcf1ab95bcb16c77651418e6570d79782` / image `d6be33f27…`. Its original planned two-case capture completed ES, then stopped at a PT authentication wait before any PT provider request; that batch remains failed. An explicit PT-only continuation passed. Across those two attempts, two actual provider turns produced two exact host-guidance captions, two HTTP 200 product-UI playback acknowledgments and two tampered-result `/api/voice/turn` HTTP 409 refusals, with zero new card writes. ES contains 399,600 PCM samples at 24 kHz (16.65 s); PT contains 370,800 (15.45 s). Those recorded host-result observations remain dated and separate from the new request-admission probes.

[ACK-recovery source qualification](measurements/voice-ack-recovery/README.md) records 148 passing frontend tests, including five failure cases. The new release retains the exact browser and native result transport bytes; it adds no new UI playback acceptance claim.

The [historical dispute-core workload](measurements/core-engine-final/README.md) retains its own 1,078 passing-check receipt and recorded `f3c57b26` source. The final application preserves 38/39 files in its actual qualified core subset, with only the [separately qualified banking snapshot reader](measurements/pipeline-publication/README.md) differing. Conversation admission and the generated graph are outside that 39-file subset.

The [prior final-product release](measurements/final-product/README.md) retains its original `634aa524` / image `44bc554c…` proof and 22-file browser build from `f3c57b26`. [Earlier canonical native voice](measurements/native-canonical-live/README.md) keeps its original `6219bc81` / image `9aa240aa…` audio and screenshots. Every historical receipt retains its source and observation scope.

## Product evidence

The complete [R0–R18 engine](DISPUTE_ENGINE.md) owns deterministic policy, selected facts, explicit consent, independently verified receipts and recovery. [Card protection](measurements/CARD_BLOCK_VERIFICATION.md) demonstrates one owned card, confirmed durable status and independent reread; 100 concurrent confirmations create exactly one block and receipt. Demo ledger. Same admission rules a production host would use.

The 140.611-second [customer film](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission.mp4) records a grounded answer, two completed reviewers, helpful informational closure and saved context. The [saved-recommendation capture](measurements/saved-recommendations-native/README.md) adds actual speech, exact full-playback acknowledgment and recovery after reload. [Luna](measurements/luna-100/README.md) completed 100/100 concurrent ES/PT fixture decisions; [FLUJO capacity](measurements/INFRASTRUCTURE_CAPACITY.md) returned 300/300 reference results and records collaboration with 18 live sandboxes. Each is its own workload. The ten-team customer architecture retains its separate acceptance gate.

The [publication-boundary qualification](measurements/pipeline-publication/README.md) verifies report completion before the serving-pointer swap and compatible banking/health consumers. [Verified presentation and host outcomes](measurements/verified-outcomes/README.md) retain their dated source and test qualification.

## Historical source and media provenance

| Evidence | Application source and image | Retained provenance |
| --- | --- | --- |
| Frozen rc.1 film and customer story | `9d77a759` / `sha256:484fe8ed…199a5` | [Source manifest](runtime-source-final.json), [deployment receipt](runtime-deployed.json), [native receipt](measurements/intended-savia-native/receipt.json) |
| Frozen rc.2 saved recommendation speech | `7089ca7b` / `sha256:39457d88…0d38e` | [Read-only freeze](runtime-listen-freeze.json), [supporting capture](measurements/saved-recommendations-native/README.md) |
| Later October 5 prototype | `a5e48f09` / `sha256:35903f9a…6dc93` | [Dated customer measurements and original receipts](measurements/MEASURED_RESULTS.md) |
| Accepted canonical native transport | `6219bc81` / `sha256:9aa240aa…a1b8b9d` | [Two-language live audit](measurements/native-canonical-live/README.md) |
| Prior final-product release | `634aa524` / `sha256:44bc554c…c632a0` | [Original release receipts](measurements/final-product/README.md); browser `f3c57b26`, 22 served files, four retained native files and portal source `634aa524` |

Frozen rc.1/rc.2 tags, recordings, captions, hashes and historical receipts retain their original scope. The [media freeze receipt](media/media-freeze-receipt.json) keeps the original film and two five-slide deck exports; the current six-slide pitch is a separately retained final artifact. [Measured results](measurements/MEASURED_RESULTS.md) preserve complete workload histories, timings and original receipts.

Private credentials, session state and simulated ledgers remain outside tracked submission material. **FLUJO main stays general purpose.** Banking integration belongs here, in Banking MCP or on the isolated hackathon branch, following the [product boundary](../FLUJO_PRODUCT_BOUNDARY.md) and [deployment source map](../FLUJO_HACKATHON_DEPLOYMENT.md).
