# Savia release candidate

Status: rc.1 submission artifacts are frozen; the deployed Listen successor is qualified.
The recovered swarm connector is in development. Public visibility and physical
legacy-folder cleanup remain pending. Updated 2026-10-05.

Release target: [v0.1.0-rc.1](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/tag/v0.1.0-rc.1).

Savia follows a customer inquiry toward a helpful answer, asks a small agent
team for different perspectives, and keeps the conversation and suggestions
available when the customer returns.

The intended product is live at [Savia RC](https://savia-rc-2026.fly.dev).
The avatar and voice are inside Savia's assistant dialog, from
`frontend/src/avatar/`, based on
`feature/savia-avatar-voice@2730d76de8e6847df4502c427ad9ced412f4a731` (PR 52).

## Qualified live successor

[PR 59](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/59)
adds an explicit control to hear saved, completed team recommendations. Application
source is `7089ca7b63006a066477415aaf54a6932d21a9b2`, branch
`codex/savia-listen-saved-result`; the deployed image is
`sha256:39457d88ec4a8577d32dc4623bab5f71a5e5349b808c002db0e258510ce0d38e`.
Its 142 source hashes and served UI were verified on the unchanged Machine and
encrypted volume. The three inquiries, six completed workers and zero bank cases
or receipts were preserved. The affected 76 UI checks and production build pass.

The [supporting recording](measurements/saved-recommendations-native/README.md)
uses the existing second inquiry and legitimate session. One actual native reply
provides useful merchant and receipt guidance: 8.2 seconds, 196,800 PCM16 samples
at 24 kHz, and one exact HTTP 200 full-playback acknowledgement. Reload retains
the grounded reply and completed suggestions without another voice stream. The
runner exits successfully. No bank question, inquiry, worker, ASR, resolution or
history reset was added. Speech condenses the advice; it omits the conditional
folio recommendation and bank-not-resolved caveat rather than reading both
suggestions verbatim. The browser clip is video-only; its WAV is supplied separately.

The product target reuses the recovered `swarm_agent`, `swarm_team`,
`swarm_supervisor` and `swarm_boot` template: ten Fly team Machines, each with one
lead and nine specialists, with Savia's root separate. The current deployed
prototype still demonstrates two reviewers. Exact 100-conversation customer
execution, real human pickup and customer push/email delivery are unqualified.

## Original rc.1 customer and voice acceptance

The recorded customer story retains one useful grounded bank answer, two real
completed agent reviews, helpful informational closure, new chat and the exact
restored bank reply with saved suggestions. The same valid session and inquiry
were continued; no additional bank question, inquiry or worker was created.

Two complete native replies were captured from actual browser response bytes:
6.6 seconds / 158,400 samples and 3.95 seconds / 94,800 samples, PCM16 at 24 kHz.
Each received one matching HTTP 200 full-playback acknowledgement. A helpful
closure event arrived during foreground speech; its spoken update waited until
the first reply finished. The second reply confirms informational closure;
it does not read worker recommendations or claim a bank resolution.

The recorder's optional transport diagnostic hung after these customer checks
and reached its 180-second cleanup deadline. Its original `completed: false`
receipt is retained. Root accepted the independently verified customer steps;
this is not a successful recorder exit. Earlier interrupted captures are also
retained. The earlier actual task-start overlap is separate from this continuation.

The file-backed synthetic microphone tests browser speech handling, not physical
microphone quality. Spanish recognition was imperfect in the retained transcript.
The comparison and its scope are in [MEASURED_RESULTS.md](measurements/MEASURED_RESULTS.md):
original usefulness screening was 2/3; the Portuguese post-fix sample used a
verified host fallback. One actual 30-minute follow-up produced no duplicate
visible update. Seven-day tracking is implemented; week-long operation is unmeasured.

## Deliverables

- [Submission video](media/video/savia-submission.mp4)
- [Submission slides](media/decks/savia-submission-deck.pptx) and [PDF](media/decks/savia-submission-deck.pdf)
- [Investor pitch](media/decks/savia-pitch-deck.pptx) and [PDF](media/decks/savia-pitch-deck.pdf)
- [Customer story](CUSTOMER_JOURNEY.md) and [measured results](measurements/MEASURED_RESULTS.md)

The final video is 140.611 seconds, 1080p, with both full integrated voice clips.
Full decoding passed; all other 16 segments retain their previous hashes. Both
editable decks and PDFs have five slides/pages, with matching current evidence.
The [media freeze receipt](media/media-freeze-receipt.json) lists exact hashes.
The MP4 SHA-256 is
`44e8dad7fdfdc6bd3b8b50b5aee83ea97f62c9e8412b20a1655a937cabd0fccb`.
Creative generation and media changes are finished.

## Frozen rc.1 source

Application source:
[`9d77a7599128b668b0e34f9c2937eb40b6bd3824`](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/tree/9d77a7599128b668b0e34f9c2937eb40b6bd3824),
branch `codex/savia-grounded-voice`.
[PR 57](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/57)
merged normally at that reviewed head to `d4af8362563c96f94287689149320e844886f8e7`.
The intent correction passed 73 voice/API checks. The combined frontend passed
129 tests and its production build; the backend passed 367 tests and 336
subtests, with eight gateway checks and 15 affected inquiry/native checks.

Immutable deployed image:
`sha256:484fe8edc07ac37dd78f61deb7a08254352b8ce597fa8265f917706e93d199a5`.
All 142 packaged source hashes and the served UI were verified. JavaScript
`assets/index-DGVQHrRT.js` is SHA-256
`f06ecbad1ea5089a227a04ea7468aeb8f4b1ef023ac04a98e6b71379771cc8bd`.
Machine `851d7dc4460048` retains encrypted volume `vol_4qlemp91ly8qn98r`.
Bank cases and receipts remain zero; this is a fictional demonstration.

The separate FLUJO compatibility pin is
[`0ba62296520a505e6d71eddf5aa650691f3dc311`](https://github.com/mario-andreschak/FLUJO/tree/0ba62296520a505e6d71eddf5aa650691f3dc311),
branch `codex/hackathon-banking`. It is not built into this image. Generic
FLUJO main remains general purpose. Its legacy release-team worktrees are clean
at signed `c20ef41db311293ee4f8e2d9f83762f662f3382f`; see
[WORKTREE_CHECK.md](WORKTREE_CHECK.md).

## Remaining publication and local cleanup

The final source and artifact audit passed and publication is authorized.
The tagged release contains the film, editable decks, PDFs and measured
qualification reports. Historical credential admission was revoked. Hosted
GitHub jobs never started because of account billing limits; local checks are
reported separately.

Tracked legacy root `avatar/` source is deleted and `/app/avatar` is absent from
the deployed image. No legacy code archive was created. Physical deletion of
ignored local leftovers remains incomplete: automatic approval review rejected
recursive removal as "blocked by policy". Unrelated work is preserved in a
local-only Git ref, and needed ignored private state remains on disk. The
primary source checkout is clean after an ordinary branch switch.
