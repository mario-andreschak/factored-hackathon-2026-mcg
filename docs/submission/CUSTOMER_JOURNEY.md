# Savia customer story

**Ask once. Savia follows through.** A customer should be able to ask about an unfamiliar charge, compare checked evidence, and return to a useful next step without starting over.

Open the [submission portal](https://savia-rc-2026.fly.dev/submission/) for the [six-slide product pitch](media/decks/final/savia-final-pitch.pdf), [editable slides](media/decks/final/savia-final-pitch.pptx) and [140.611-second customer film](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission.mp4). Try [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate and fictional-profile login.

## From a question to a useful answer

1. A customer opens a purchase and chooses **Revisar este cargo**. Merchant, date, amount and status remain visible.
2. The customer asks **No reconozco este cargo. ¿Qué puedo hacer?** by voice or keyboard. Savia explains checked facts and useful next steps. Its voice is integrated into the same assistant dialog.
3. **Pedir ayuda a un equipo** asks for informational exploration. The recorded prototype shows two actual model reviewers comparing evidence and next steps. Saved cards show the work's status and suggestions.
4. The customer marks the explanation helpful with **Esta respuesta resolvió mi consulta**. This closes the informational inquiry; bank intake retains its separate consent and receipt state.
5. **Empezar chat nuevo** clears the visible conversation and selected context. **Ver conversación anterior** restores the previous view. Saved inquiries, suggestions and bank receipts keep their persistence rules.
6. On return, the customer can read the saved suggestions and choose **Escuchar recomendaciones**. The rc.2 supplement records useful condensed merchant and receipt advice; the complete suggestions remain on screen.

The [two-reviewer recording](measurements/team-story-summary.md) and [saved-recommendation capture](measurements/saved-recommendations-native/README.md) preserve those observed customer steps. Quiet follow-up checks and retained context are supported by the dated measurements, including a real 30-minute scheduled check.

## Confirm once. Keep the control.

Confirm once. Savia blocks the owned card, writes a durable status, and rereads an independent receipt. Asking never writes. Foreign cards, missing consent, and tampered receipts are refused.[^card-ledger]

Spanish and Portuguese card requests open the same selection-and-confirmation control. The blocked status survives a new login. [Public action acceptance](measurements/card-block-live/README.md) pins the actual customer action; [concurrency verification](measurements/CARD_BLOCK_VERIFICATION.md) records 100 simultaneous confirmations producing exactly one block and receipt.

The later [canonical voice capture](measurements/native-canonical-live/README.md) records exact Spanish/Portuguese card-guidance captions and full-playback acknowledgments. Saved-card status is reread independently from that guidance. The [final release](measurements/final-product/README.md) verifies that both saved receipts survive image promotion unchanged.

## One conversation. A team behind it.

The customer film records two completed reviewers. The foundation separately returned **300/300 correct FLUJO reference results from 300 concurrent submissions** and records collaboration with **18 Fly sandboxes live together**. The ten-team architecture has one lead and nine specialists per team, with the root coordinator separate. [Capacity and collaboration evidence](measurements/INFRASTRUCTURE_CAPACITY.md) keeps those workloads distinct.

The complete [R0–R18 engine](DISPUTE_ENGINE.md) checks owned facts, applies ordered policy, requests consent, independently verifies action receipts and preserves recovery. Policy authorizes the card action. Voice and specialist perspectives help the customer understand the evidence and return for useful advice.

[^card-ledger]: *Demo ledger. Same admission rules a production host would use.*

The [release report](RELEASE_CANDIDATE.md) identifies source/image provenance and deliverables. [Measured results](measurements/MEASURED_RESULTS.md) retain timings, language comparisons and original receipts. For local development, use the [isolated RC setup](../../deploy/rc/README.md).
