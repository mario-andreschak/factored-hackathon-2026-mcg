# Savia release candidate

**Current public product release — October 5, 2026, America/Bogota.**

Open the [submission portal](https://savia-rc-2026.fly.dev/submission/) for the human pitch, completed customer film, repository and development story. Try [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate and fictional-profile login. The [six-slide product pitch](media/decks/final/savia-final-pitch.pdf) follows Why → What → How; its [editable PowerPoint](media/decks/final/savia-final-pitch.pptx) and presenter notes share the final product narration.

## Current runtime and acceptance

| Component | Qualified source or observation |
| --- | --- |
| Application, standalone analytics sources and public portal | `634aa5244374b3e105ef7864fa100530bab45ec2`, tree `e27ee184520af7fde74831cd553faf1899b4babe` |
| Running image | `registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0` |
| Source and machine continuity | All 183 sources, 22 built browser files and four native runtime files verified; complete machine configuration preserved except image |
| Public submission | All 27 allowlisted payloads match; health and entry guard verified |
| Card ledger after promotion | Two ES/PT owned-card saved receipts match the dated predecessor; 12 HTTP checks, zero new card blocks or provider calls |
| Canonical native voice | Actual two-language captions and exact product-UI playback acknowledgments on `6219bc81` / image `9aa240aa…`; those accepted transport bytes are unchanged in the final layer |

[Final release receipts and harnesses](measurements/final-product/README.md) pin the running source, hashes, unchanged configuration, public assets and card continuity. [Live canonical voice](measurements/native-canonical-live/README.md) keeps the original audio, screenshots and exact dated source/image. Source qualification and a merge are distinct from a live observation; neither changes an older receipt's pin.

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

Frozen rc.1/rc.2 tags, recordings, captions, hashes and historical receipts retain their original scope. The [media freeze receipt](media/media-freeze-receipt.json) keeps the original film and two five-slide deck exports; the current six-slide pitch is a separately retained final artifact. [Measured results](measurements/MEASURED_RESULTS.md) preserve complete workload histories, timings and original receipts.

Private credentials, session state and simulated ledgers remain outside tracked submission material. **FLUJO main stays general purpose.** Banking integration belongs here, in Banking MCP or on the isolated hackathon branch, following the [product boundary](../FLUJO_PRODUCT_BOUNDARY.md) and [deployment source map](../FLUJO_HACKATHON_DEPLOYMENT.md).
