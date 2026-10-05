# Savia — final product pitch

Owner-directed successor prepared October 5, 2026. Use this six-slide deck for
the product pitch; the earlier five-slide RC decks and video remain frozen.

- [Editable PowerPoint](savia-final-pitch.pptx)
- [PDF](savia-final-pitch.pdf)
- [Slide viewer with narration and evidence](savia-final-pitch.html)
- [All six slides at a glance](savia-final-pitch-contact-sheet.png)
- [Participant narration and Q&A notes](savia-final-pitch-speaker-notes.md)
- [Claim provenance](savia-final-pitch-sources.json)
- [Export hashes](savia-final-pitch-manifest.json)

The story follows one customer problem: “I don't recognize this transaction.”
Savia is the customer's voice assistant and case owner. The swarm is the
technical centerpiece: up to 100 team conversations, with ten teams of one lead
and nine specialists and separate root coordination. The diagram contains all
100 team markers. Three product slides, two technical slides and a product/pilot
close follow the organizer's approximate 60% product / 40% technical direction.
The six slides meet the required 4–6 range.

The ElevenLabs comparison is a concise positioning comparison with its official
financial-services voice showcase. It makes no unsupported winner, compliance,
exclusive-feature or comparative-latency claims. Savia's story emphasizes
persistent cases, agent collaboration, reviewed evidence and deployment choice.

The product vision is prominent, and its proof is scoped: the recorded customer
journey has two completed reviewers; the 300/300 result is a queued reference-code
load test; the exact 100-agent customer run is not qualified. Self-hosting and
local open-weight inference are foundation capabilities, not a newly verified
all-local Savia deployment. Actual human assignment, bank resolution, push/email
delivery and multi-day completion are pilot integrations. Business value is a
pilot hypothesis. Notes retain failed attempts and workload timing, so presenters
can answer technical questions accurately.

The English narration is 358 words, approximately 2:40–3:00 at 120–135 words per
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

Slide text, the eyes, the waveform, the swarm and the system diagram are editable
PowerPoint objects. PDF and PNG exports use PowerPoint's native renderer; the
HTML viewer displays those same PNGs with keyboard navigation and optional notes.
Source links and narration are also embedded in each PowerPoint notes page.

Primary references: [organizer pitch direction](https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791068906645819),
[English delivery](https://factored-hackathon.slack.com/archives/C0BUZCY0TUY/p1791153414484629),
[voice clarification](https://factored-hackathon.slack.com/archives/C0BU6V61273/p1791228494554899),
[ElevenLabs showcase](https://elevenlabs.io/blog/eleven-v4-turbo-in-elevenagents),
[PR #74 capacity evidence](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/95e2b9d62685f2669473258b88935a43dbe1bf75/docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md).
