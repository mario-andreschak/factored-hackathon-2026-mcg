# Savia release candidate

**Current public product release — October 5, 2026, America/Bogota.**

Open the [submission portal](https://savia-rc-2026.fly.dev/submission/) for the human pitch, completed customer film, repository and development story. Try [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate and fictional-profile login. The [six-slide product pitch](media/decks/final/savia-final-pitch.pdf) follows Why → What → How; its [editable PowerPoint](media/decks/final/savia-final-pitch.pptx) and presenter notes share the final product narration.

## Current runtime and acceptance

| Component | Qualified source or observation |
| --- | --- |
| Application and standalone analytics sources | `c44d416fcf1ab95bcb16c77651418e6570d79782`, tree `fabf02d622f51302e229137405e3607356d00ab0` |
| Fresh browser build | The same `c44d416fcf1a` source; 21 files from an isolated production build with the committed lockfile |
| Retained public portal and pitch | Source `634aa5244374b3e105ef7864fa100530bab45ec2`; all 28 tracked portal files unchanged; the retained 16-file pitch/media subset contains 12 pitch delivery files and four public assets |
| Running image | `registry.fly.io/savia-rc-2026@sha256:d6be33f27d777e9e9adf9f86ef1fb381c24e02aaf6579d5947c6482ee67dc05c` |
| Source and machine continuity | All 183 sources, 21 fresh built browser files and four retained native runtime files verified; complete machine configuration preserved except image |
| Public submission | All 27 allowlisted public payloads match; health and entry guard verified |
| Card ledger after promotion | Two ES/PT owned-card saved receipts match the dated predecessor; 12 HTTP checks, zero new card blocks or provider calls |
| Current canonical native voice | Two recorded ES/PT guidance cases across two attempts: exact host-script captions and two exact product-UI playback acknowledgments on `c44d416f` / image `d6be33f2…`; existing owned-card status is reread separately |

[Current native playback and release receipts](measurements/voice-ack-live/README.md) pin the fresh browser, running source and image, actual audio, exact acknowledgments, unchanged configuration, public assets and card continuity.

The original planned two-case capture completed ES, then stopped at a PT authentication wait before any PT provider request; its batch receipt remains failed. An explicit PT-only continuation passed. Across the two attempts, the two actual provider turns produced two exact captions, two HTTP 200 playback acknowledgments and two tampered-result HTTP 409 refusals, with zero new card writes. ES audio contains 399,600 PCM samples at 24 kHz (16.65 s); PT contains 370,800 (15.45 s).

[ACK-recovery source qualification](measurements/voice-ack-recovery/README.md) records 148 passing frontend tests, including five failure cases; the live workload adds normal playback observations without injecting an ACK failure.

The [prior final-product release](measurements/final-product/README.md) retains its original `634aa524` / image `44bc554c…` proof and 22-file browser build from `f3c57b26`. [Earlier canonical native voice](measurements/native-canonical-live/README.md) keeps its original `6219bc81` / image `9aa240aa…` audio and screenshots. Source qualification and a merge are distinct from a live observation; neither changes an older receipt's pin.

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
