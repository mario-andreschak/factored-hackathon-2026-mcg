# Savia release candidate

**READY FOR HUMAN REVIEW — owner and Gloria, October 5, 2026.**
The owner has limited this submission to the existing app, frozen video and decks,
and honest documentation. New fleet runs, provisioning, funding approval and
additional follow-up qualification are outside this release scope.

Savia is a friendly Spanish and Portuguese voice assistant that follows customer
inquiries, asks a team for different perspectives, and keeps useful answers and
follow-up together when the customer returns.

## Open the submission

Try [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate
and fictional customer profile login.

- [Play or download the submission video](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission.mp4)
- [Editable submission deck](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission-deck.pptx) and [PDF](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission-deck.pdf)
- [Editable pitch deck](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-pitch-deck.pptx) and [PDF](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-pitch-deck.pdf)
- [Customer story](CUSTOMER_JOURNEY.md) and [measurement appendix](measurements/MEASURED_RESULTS.md)

These published assets belong to [frozen rc.2](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/tag/v0.1.0-rc.2),
which reuses the rc.1 film and decks. The video is 140.611 seconds, 1080p, with
both complete integrated voice clips; decoding passed. Both editable decks and
PDFs have five slides/pages. The [media freeze receipt](media/media-freeze-receipt.json)
retains exact hashes. This documentation update leaves those assets unchanged.

## The customer story and prototype limits

A fictional customer selects an unfamiliar charge and asks Savia for help.
Savia explains checked transaction facts, offers team exploration, and retains
suggestions and conversation context. The recorded story shows two real completed
reviewers, the customer marking an informational answer helpful, a new chat view,
and a return to the saved bank reply and suggestions. The rc.2 supplement shows
**Escuchar recomendaciones** speaking useful condensed merchant and receipt advice.

The integrated avatar and conversational voice live inside the assistant dialog
at `frontend/src/avatar/`, based on
`feature/savia-avatar-voice@2730d76de8e6847df4502c427ad9ced412f4a731` (PR 52).
Native audio and exact full-playback acknowledgements support the recorded voice
claims. The original recorder's optional diagnostic timeout remains disclosed in
the appendix; physical microphone quality and independent human audio review are
unqualified. Human review of the submission is the next step.

The later October 5 fleet attempt returned correct fictional bank facts and a
complete foreground voice reply, but its root model call failed because the
provider workspace was disabled. No completed team reviews resulted from that
attempt. It is a disclosed prototype limitation, not a blocker for this submission
under the owner's reduced scope. Its [original receipt](measurements/fleet-customer-attempt/receipt.json)
and full trace remain in the measurement appendix; the earlier successful
recordings keep their original scope.

Follow-up and saved context are part of the product. Earlier recorded checks
support their stated behavior; no new extended follow-up run is required for this
handoff. Large-fleet execution, real human pickup and customer push/email delivery
remain unqualified. No refund or real bank resolution is claimed. Simulated
intake requires explicit consent and a separately verified receipt; informational
closure means that the customer found an answer helpful.

## Source and evidence provenance

| Evidence | Application source and image | Retained provenance |
| --- | --- | --- |
| Frozen rc.1 film and customer story | `9d77a759` / `sha256:484fe8ed…199a5` | [Source manifest](runtime-source-final.json), [deployment receipt](runtime-deployed.json), [native receipt](measurements/intended-savia-native/receipt.json) |
| Frozen rc.2 saved recommendation speech | `7089ca7b` / `sha256:39457d88…0d38e` | [Read-only freeze](runtime-listen-freeze.json), [supporting capture](measurements/saved-recommendations-native/README.md) |
| Later deployed prototype and partial fleet attempt | `a5e48f09` / `sha256:35903f9a…6dc93` | [Actual attempt receipt](measurements/fleet-customer-attempt/receipt.json), with full application/native/controller pins |

The later prototype uses native source `67d21ad3` and controller `290dd6a7`;
their full pins are retained in that receipt.
Newer source merges do not relabel these deployed images. Frozen rc.1/rc.2 tags,
recordings, captions, hashes and historical receipts retain their original scope.
The [measurement appendix](measurements/MEASURED_RESULTS.md) preserves language
comparisons, timing boundaries, provider failures and incomplete captures.

The repository and frozen release assets are public. Private credentials,
customer state and simulated ledgers remain outside tracked submission material.
Ignored local legacy remnants are outside release acceptance. The integrated
frontend avatar is the active voice source.

**FLUJO main stays general purpose.** Banking integration belongs in this
repository, the banking MCP or the owner-authorized isolated hackathon branch.
The [product boundary](../FLUJO_PRODUCT_BOUNDARY.md) and
[deployment source map](../FLUJO_HACKATHON_DEPLOYMENT.md) govern that separation.
