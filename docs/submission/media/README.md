# Savia submission media

Savia is the friendly voice assistant. The 140.611-second film follows a calm
couple through increasingly absurd settings. The question stays with Savia
while life continues. The kickoff requires a short video and 4–6 slides, with
no numeric film duration; the coordinator approved a tight 120–180-second edit.

**Integrated voice product steps are accepted.** Both assistant inserts now use
complete provider audio from the intended Savia dialog, with exact full-playback
acknowledgements. The TV scenes and other actual Savia text/team inserts are
preserved. The recorder's optional diagnostic cleanup timed out after the required
product checks completed; that failure remains in the evidence receipt.

## Deliverables

- `video/savia-submission.mp4`: 1080p H.264/AAC, burned English captions.
- `video/savia-submission.srt` and `.vtt`: editable separate captions.
- `video/savia-submission-receipt.json`: hash, source intervals, actual duration
  and complete-decode result.
- `video/tv-timeline.json`: editable picture/audio/caption timeline.
- `decks/savia-submission-deck.pptx` and `savia-pitch-deck.pptx`: separate editable
  five-slide decks, matching PDFs/HTML, notes and slide previews.
- `review.html`: local artifact review index.

## Actual product inserts

Fresh Spanish model answer: source 11.6–23.6 seconds in the actual fictional
`measurements/team-story-final/actual-browser.webm`. Preserved helpful inquiry:
212.5–227.5 seconds. Two real concurrent informational model workers completed,
and the customer confirmed the explanation helped. This closes an informational
inquiry. Trusted facts and reviewed suggestions remain visible after new chat
and reload. It does not resolve a bank dispute.

The opening uses 6.6 seconds of actual conversational reassurance: “Despacio,
sí, bien tranquilo, aquí estoy.” The later 3.95-second spoken insert says “Cerró
la consulta, ya te ayudó la explicación.” It confirms the customer's helpful
closure of an informational inquiry. It does not speak the worker recommendations
or report a bank decision. Both full WAVs are preserved without truncation.

The intended integrated dialog was served from source
`9d77a7599128b668b0e34f9c2937eb40b6bd3824`. The closure arrived during foreground
playback and waited for its complete acknowledgement before speaking. Existing
team suggestions and the exact bank reply stayed saved after a new chat and
restoration. This same-session continuation made no new bank chat, inquiry or
worker request. The earlier partial attempt's worker creation during foreground
is separate evidence. The text/team and Portuguese inserts are separate actual
fictional runs; Portuguese asks for the date and amount.

Native WAVs, exact Spanish transcripts, source/image/served-JavaScript identity,
playback counts and limitations are in `measurements/intended-savia-native/receipt.json`.
The two acknowledgements were HTTP 200 with exactly 158,400 and 94,800 played
samples at 24 kHz. File-backed browser microphone input and imperfect ASR were
observed; no physical microphone or perfect recognition is claimed. Earlier
standalone voice evidence and failed partial attempts remain historical evidence.
The raw recorder exit is 1: an optional transport diagnostic hung after all
required product checks, and the 180-second timer closed the browser. Root and
measurement accepted those completed product steps separately; no rerun hid the
cleanup failure.

The earlier simulated receipt follow-up uses a legible actual snapshot hold.
One real 30-minute repeat check was observed. Seven-day tracking has controlled-
time implementation tests, without a live week observation. Bank authorization
remains separate. No real refund, bank decision, human acceptance or production
savings is claimed.

## Creative sources and failure recovery

Five moving scenes retain generated native dialogue: breakfast/shop/kayak and
the new bowling/board-game takes. The fictional cast remains consistent. The
bounded cached MiniMax batch failed after two clips; `tv/render-call.json`
preserves its identity, and `tv/render-observation.json` records recovery. The
owned ephemeral app was stopped with zero containers running. No duplicate
batch, alternate account or model download was used.

Beach and skydiving are deliberate photo cutaways with separate stock
Kore/Charon dialogue, rather than native animation or lip synchronization.
Six bridge/pickup WAVs total 43.87 seconds. Actual Savia speech stays separate.
The original local synth score contains no samples or third-party recordings.
Captions translate or summarize Spanish/Portuguese inserts. Human pickup timing
uses exact receipts; the two new native clips passed cached local ASR and sampled
frame checks. ASR alone does not prove lip sync.

## Rebuild

With Python/Pillow and FFmpeg on PATH, from the repository root:

```powershell
python scripts/submission_media/tv/prepare_edit.py
python scripts/submission_media/tv/render_spoken_update.py
python scripts/submission_media/build_video.py --timeline docs/submission/media/video/tv-timeline.json --name savia-submission
```

The prepare step rebuilds private coffee/photo cutaways without paid model calls.
The full build mixes audio, burns captions, checks a complete decode and writes
its receipt. Deck and motion generators live in `scripts/submission_media/`.
Superseded corporate drafts and rejected audio are preserved in private scratch.

Credits: Gloria Yanta Salc for prompts and customer-flow design, Carlos Diaz for
the data pipeline and lookup, Moe and the Savia team for integration.
