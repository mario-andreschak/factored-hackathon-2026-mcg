# Final public product release

The completed [human pitch, film and submission portal](https://savia-rc-2026.fly.dev/submission/) are live. The six-slide pitch and original 140.611-second customer film retain their accepted bytes.

## Observed source and release

- Application and portal source: `634aa5244374b3e105ef7864fa100530bab45ec2`, tree `e27ee184520af7fde74831cd553faf1899b4babe`.
- Running image: `registry.fly.io/savia-rc-2026@sha256:44bc554cd82ad62db51d536d580df248cbb188d24732e7ec1ed8133617c632a0`.
- [Live runtime verification](runtime-verification.json): all **183 source files**, **22 retained browser files** and **four retained native runtime files** match. The complete existing machine configuration, including CPU, memory, services, environment and volume mount, matches the preserved configuration apart from the image. Credentials and environment values are excluded from the report.
- [Public HTTP verification](public-assets-verification.json): all **27 public payloads** match their frozen hashes; health is 200, the actual entry form is present, the unauthenticated customer API returns 401, and the internal guard manifest remains non-public (404).
- [Card receipt continuity](card-status-continuity.json): **12 HTTP checks**, two ES/PT fictional profiles, two independent owned-card status reads each. The saved receipts match the earlier native audit exactly after image promotion. No new prepare, confirm, cancel or card block; no provider calls.
- [Merged source qualification](source-qualification.json): **32 tests and 106 subtests**, all **89 protected source hashes**, and the portal test. The original JUnit is preserved in [merged-source-gates.xml](merged-source-gates.xml).

## Qualification boundaries

The [actual bilingual canonical voice observation](../native-canonical-live/README.md) remains pinned to source `6219bc81` and image `9aa240aa…`. The final layer preserves the exact accepted conversation, voice and RC transport source bytes, compiled UI and native runtime. It does not relabel the earlier two real model calls as new calls on this image. Captions, PCM and full-playback acknowledgments qualify transport; independent human waveform comprehension remains separate.

The layer guards check the accepted predecessor before replacement and the full final source afterward. [Docker layer](release-layer.Dockerfile), [verifier](release-layer-verifier.py) and [expected retained files](retained-runtime.json) preserve those inputs. Read-only [runtime](runtime-harness.py), [public assets](public-assets-harness.py) and [card continuity](card-continuity-harness.mjs) harnesses retain their observed local paths; they are provenance artifacts rather than portable setup instructions. All published card observations here are status rereads; the original [public card action acceptance](../CARD_BLOCK_VERIFICATION.md) keeps its own source and workload.

Git merges and later documentation commits do not change these observation pins. Historical workload counts retain their denominators; overlapping test runs are not added together. Generic FLUJO main is unchanged. Raw private configurations, cookies, capabilities and customer session state are excluded.
