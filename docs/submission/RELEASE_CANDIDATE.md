# Savia release candidate

Status: rc.2 is the current frozen release; its rc.1 film and decks remain frozen.
The first new fleet/customer attempt is partial; further qualification is pending.
The recovered swarm connector's [source and integration pins](assistant/FLEET_CONNECTOR.md)
are merged; runtime qualification remains pending. Public visibility is verified.
Full ten-by-ten swarm qualification remains pending. Updated 2026-10-05.

Current frozen release: [v0.1.0-rc.2](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/tag/v0.1.0-rc.2).

Savia follows a customer inquiry toward a helpful answer, asks a small agent
team for different perspectives, and keeps the conversation and suggestions
available when the customer returns.

The intended product is live at [Savia RC](https://savia-rc-2026.fly.dev).
The avatar and voice are inside Savia's assistant dialog, from
`frontend/src/avatar/`, based on
`feature/savia-avatar-voice@2730d76de8e6847df4502c427ad9ced412f4a731` (PR 52).

## Actual fleet/customer qualification

The October 5 first attempt is partial; mandatory fleet customer acceptance
failed. Its [merged receipt](measurements/fleet-customer-attempt/receipt.json)
from [PR 70](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/70)
records application source `a5e48f09afe4241f6b08a2b94532b2bd3eb630f4`, image
`sha256:35903f9a1ea70f8b3c589d5680ed50307efd34870ce004bdd1833b9029b6dc93`,
native source `67d21ad3fe49059ab349d1315d02a9437daa1140` and controller source
`290dd6a7c19fa92c267bddd04f625f6cfbe39459`. Later generic source review does not
relabel that deployed native image.

The bank reply matched the selected fictional facts. Foreground native speech
completed 8.85 seconds / 212,400 PCM16 samples at 24 kHz with one exact HTTP 200
full-playback acknowledgement. The original root run failed after 5,981 ms on
its first model call: HTTP 404, Modal workspace disabled. Zero team leads, local
staff, completed reviews or native100 population were verified. An active goal
and ready root worker do not establish successful execution.

No audible execution overlap was qualified: the failed root ended 2,828 ms before
speaking was observed. The nominal 1,321 ms request overlap is not an audible or
concurrency result. Guidance audio, reload/context and the actual 1,800-second
follow-up remain unqualified. Any funded successor is a separate attempt; this
failure and the frozen rc.1/rc.2 evidence retain their original scope.

The original root was retired through the existing operator DELETE at 18:04 UTC
(13:04 Bogotá). Its case, goal, run, board and volume were preserved; the retained
goal is still `ACTIVE` and the run is `FAILED`. Retirement is not goal completion.
Funding controls 50/20 remain unsaved, awaiting the owner. A productive customer
journey and its normal-clock 30-minute follow-up are outstanding; rc.3 is not
ready.

## Frozen rc.2 Listen acceptance

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
lead and nine specialists, with Savia's root separate. The qualified rc.2
prototype demonstrated two reviewers. Exact 100-conversation customer
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

## Public release and local scope

The repository is public. The supplemental
[rc.2 release](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/tag/v0.1.0-rc.2)
is non-draft with 20 assets. Public visibility was verified on October 5 via
`gh`, anonymous GitHub repository/release APIs and the visible Public repository
badge. This closes the public visibility gate.

The frozen releases passed their source and artifact audits and contain the
film, editable decks, PDFs and measured qualification reports. Historical
credential admission was revoked. Hosted GitHub jobs now execute:
[PR 66](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/66)
startup/manifest checks pass on Ubuntu and Windows, and
[PR 67](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/67)
passes the real Chrome gateway check. Eight preexisting Windows HISTORY failures
remain. Linux deployment qualification is separate from those Windows failures
and from the pending new live/customer/native100 results above.

Owner scope correction, October 5: ignored local legacy remnants are outside RC
acceptance. Physical deletion is not a release gate or required manual action.
Dated and frozen cleanup receipts retain their original observations; this
correction does not assert that ignored remnants disappeared.

Tracked legacy root `avatar/` source is deleted and `/app/avatar` is absent from
the deployed image. No legacy code archive was created. Physical deletion of
ignored local leftovers remains incomplete: automatic approval review rejected
recursive removal as "blocked by policy". Unrelated work is preserved in a
local-only Git ref, and needed ignored private state remains on disk. The
primary source checkout is clean after an ordinary branch switch.
