# ElevenAgents transaction dispute reference for Savia WhatsApp

The [ElevenLabs demonstration](https://www.youtube.com/watch?v=1QJTfaaxVag)
provides a conversational reference for Savia: a customer reports an unfamiliar
charge, corrects a verification mistake, pauses to consult another account holder,
and requests a dispute. The standalone WhatsApp experiment adapts those interaction
patterns to fictional RC data and asynchronous voice notes.

## Source and captions

- Title: Transaction dispute handled by ElevenAgents | Eleven v4 Turbo.
- Publisher: ElevenLabs; published September 29, 2026; duration 2 minutes 3 seconds.
- Reviewed October 5, 2026, through YouTube's visible description, timestamped
  transcript panel, and demonstration frames in a separate local browser tab.
- The player initially reported captions unavailable, but expanding the description
  exposed **Show transcript**, which displayed English timestamped captions.
- Captions contain apparent recognition errors, including inconsistent customer
  names and a mistaken word for card. These notes paraphrase the sequence rather
  than treating captions as an exact spoken record.

The linked video is third-party material. A complete verbatim transcript is not
included without permission or an applicable license; the publisher's transcript
remains available on the source page. Gemini or AI Studio was unnecessary once
YouTube's transcript became available.

## Timestamped sequence

| Time | Paraphrased event |
| --- | --- |
| [00:03](https://www.youtube.com/watch?v=1QJTfaaxVag&t=3s) | Narration frames responsive, empathetic bank service and language support. |
| [00:29](https://www.youtube.com/watch?v=1QJTfaaxVag&t=29s) | Agent greeting; customer reports an unfamiliar card charge. |
| [00:38](https://www.youtube.com/watch?v=1QJTfaaxVag&t=38s) | Agent offers spoken or keypad card entry and allows a pause. |
| [00:58](https://www.youtube.com/watch?v=1QJTfaaxVag&t=58s) | Agent initiates phone-code verification; a wrong response is corrected. |
| [01:17](https://www.youtube.com/watch?v=1QJTfaaxVag&t=77s) | After verification, the agent reviews recent charges. |
| [01:30](https://www.youtube.com/watch?v=1QJTfaaxVag&t=90s) | Customer checks with another account holder before deciding. |
| [01:40](https://www.youtube.com/watch?v=1QJTfaaxVag&t=100s) | Customer explicitly requests a dispute; agent signals processing. |
| [01:50](https://www.youtube.com/watch?v=1QJTfaaxVag&t=110s) | Agent claims dispute completion, future provisional credit, card freeze and replacement, and continued wallet access. |

## Application to the local experiment

The video's final bank outcomes are demonstration claims, not evidence that Savia's
fictional hackathon RC can perform live banking operations. Savia must retain its
existing ownership, consent, receipt, recovery, and action-policy boundaries.
Linking a personal WhatsApp account does not verify a bank customer. The lab must
not collect real card numbers or authentication codes to imitate the video.

The local `mcp-whatsapp-web` tool contract supports messages and media. Its
`send_media` tool accepts a local audio path or base64 and converts it to mono
Opus/Ogg when `as_audio_message=true`. Incoming `ptt` messages can be retrieved
and their media downloaded. The inspected backend contract exposes no live-call
control or streaming audio interface. A recorded WhatsApp voice-note exchange has
different turn timing from the video's live telephone dialogue.

For the lab, useful behavior checks are: acknowledge the concern, preserve the
conversation across several notes, let the customer correct an input, tolerate a
pause, identify the intended transaction, require the RC's established consent,
and report only an outcome supported by a verified result. Use fictional
identifiers and demo verification. If a message send has an uncertain outcome,
hold it for reconciliation rather than automatically replaying it.

Keep the bridge in this repository's standalone package and use existing generic
FLUJO chat, flow, tool, MCP, and execution interfaces. It is outside the current
deployment and does not alter FLUJO main.

## Local contract provenance

- WhatsApp MCP inspected at commit
  `65d39c4d83b7e9bacdd65e46059f18f185199f8d`: `src/tools/media.ts` and
  `src/services/backend.ts`.
- RC base supplied for this isolated stream: `843da506`.
- Product boundary: [FLUJO product boundary](../../../docs/FLUJO_PRODUCT_BOUNDARY.md).
- Runtime acceptance context: [release candidate report](../../../docs/submission/RELEASE_CANDIDATE.md).

Source preservation, a successful local dry run, and the publisher's demonstration
do not establish deployment acceptance or a live banking capability.
