# Savia — final product pitch

Product-pitch successor prepared October 5, 2026. Use this six-slide deck for
the product pitch; the earlier five-slide RC decks and video remain frozen.

- [Editable PowerPoint](savia-final-pitch.pptx)
- [PDF](savia-final-pitch.pdf)
- [Slide viewer with narration and evidence](savia-final-pitch.html)
- [All six slides at a glance](savia-final-pitch-contact-sheet.png)
- [Participant narration and Q&A notes](savia-final-pitch-speaker-notes.md)
- [Claim provenance](savia-final-pitch-sources.json)
- [Export hashes](savia-final-pitch-manifest.json)

The story follows one customer problem: “I don't recognize this transaction.”
Savia keeps checked facts, consented actions, specialist perspectives and saved
follow-through with the same case. The customer stays at the center of the first
slide. The fourth slide shows ten teams of one lead and nine specialists, with
all 100 team conversations represented by editable markers. The fifth slide
shows the deterministic R0–R18 engine and its bank-controlled authority boundary.
Three product slides, two technical slides and a product/pilot close follow the
organizer's approximate 60% product / 40% technical direction. The six slides meet
the required 4–6 range.

The ElevenLabs commercial reference sets up the product pitch: Savia is the
bank-controlled service around owned facts, deterministic policy, consent,
receipts, follow-up and swarm investigation. The two-person, ten-day delivery
context is spoken; historical contributor credits remain intact.

The customer action wording is:

> Confirm once. Savia blocks the owned card, writes a durable status, and rereads
> an independent receipt. Asking never writes. Foreign cards, missing consent,
> and tampered receipts are refused.

The slide has one action footnote: **Demo ledger. Same admission rules a
production host would use.**

Slide 5 links the fresh 1,078 offline core checks, local Luna fixture decisions,
and two live Spanish /
Portuguese public API card-protection journeys. The data-to-product finding is
visible: historical links crossed customer ownership, so new inquiries use owned
transaction reads. The bank-pilot close proposes measuring repeat contacts,
helpful answers, handoff quality and cost per case.

Presenter notes separate **Say:** product narration from **If asked:** workload
denominators, historical failures, simulated-ledger scope and source qualification.
The recorded customer path is two reviewers. The 300/300 concurrent FLUJO result
is a queued reference-code workload; 18 sandboxes were live together in separate
historical collaboration evidence. Exact 100-agent customer completion remains
undemonstrated. The new card evidence is API/host/ledger acceptance. Those scopes
are retained in the linked notes and receipts.

The English narration is 346 words, approximately 2:34–2:53 at 120–135 words per
minute. Organizer clarification permits AI audio with a presentation-score
penalty and recommends actual participant narration. This deck creates no audio
and changes no video. The Spanish product screenshot has an English summary.

Regenerate from the repository root using the bundled Python (with python-pptx
and Pillow), then native Windows PowerPoint:

```powershell
python scripts/submission_media/decks/build_final_pitch.py
& scripts/submission_media/decks/export_final_pitch.ps1
python scripts/submission_media/decks/build_final_pitch.py --finish
```

Slide text, the eyes, the waveform, the swarm and the decision diagram are editable
PowerPoint objects. PDF and PNG exports use PowerPoint's native renderer; the
HTML viewer displays those same PNGs with keyboard navigation and optional notes.
Source links and narration are also embedded in each PowerPoint notes page.

Primary references: [organizer pitch direction](https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791068906645819),
[English delivery](https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791153414484629),
[voice clarification](https://factored-hackathon.slack.com/archives/C0BU6V61273/p1791228494554899),
[ElevenLabs showcase](https://elevenlabs.io/blog/eleven-v4-turbo-in-elevenagents),
[PR #74 capacity evidence](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/95e2b9d62685f2669473258b88935a43dbe1bf75/docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md),
[fresh core qualification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/7de0bbd670c25e4ad83476c6d7b70c45cc58a137/docs/submission/measurements/core-engine-final/README.md),
[local Luna workload](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/7de0bbd670c25e4ad83476c6d7b70c45cc58a137/docs/submission/measurements/luna-100/README.md),
[live card acceptance](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/7de0bbd670c25e4ad83476c6d7b70c45cc58a137/docs/submission/measurements/card-block-live/README.md)
and [data-informed operating decisions](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/7de0bbd670c25e4ad83476c6d7b70c45cc58a137/docs/review/OPERATING_DECISIONS.md).
