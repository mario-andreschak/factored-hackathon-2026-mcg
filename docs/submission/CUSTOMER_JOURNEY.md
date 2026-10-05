# Savia customer story

**Ready for owner and Gloria's human review, October 5, 2026.** Savia is a
friendly voice assistant that helps a customer understand an unfamiliar charge,
asks a team for different perspectives, and keeps the inquiry and follow-up
available when the customer returns.

Open [Savia](https://savia-rc-2026.fly.dev) with **SAVIA-2026** at the entry gate
and fictional profile login. Start with the
[playable submission video](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission.mp4),
[submission deck](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission-deck.pptx)
([PDF](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-submission-deck.pdf))
and [pitch deck](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-pitch-deck.pptx)
([PDF](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/releases/download/v0.1.0-rc.2/savia-pitch-deck.pdf)).
These are the existing frozen rc.2 deliverables, reusing the rc.1 film and decks.

The film's two reviewers are one recorded customer example. The underlying FLUJO
infrastructure separately passed a **300-parallel-request test with 300/300 correct
results** and real collaboration runs with 18 Fly sandboxes live together.
Savia's architecture uses ten teams of ten conversations. See the
[infrastructure evidence](measurements/INFRASTRUCTURE_CAPACITY.md) for capacity,
collaboration and the deployed connector. A further paid fleet/load run for the
submission video was skipped because of budget constraints.

## From a question to a useful answer

1. A fictional customer opens a purchase and chooses **Revisar este cargo**.
   Merchant, date, amount and status remain visible.
2. The customer asks **No reconozco este cargo. ¿Qué puedo hacer?** by voice or
   keyboard. Savia explains checked facts and useful next steps. Its eyes and
   voice are integrated inside the same assistant dialog.
3. **Pedir ayuda a un equipo** asks for informational exploration. The earlier
   recorded prototype shows two actual model workers comparing evidence and
   useful next steps. Saved cards show the work's real status and suggestions.
4. The customer marks the explanation helpful with **Esta respuesta resolvió mi
   consulta**. This closes the informational inquiry; it does not resolve a bank
   dispute. The frozen voice recording reports that helpful closure.
5. **Empezar chat nuevo** clears the visible conversation and selected context.
   **Ver conversación anterior** restores the previous view. Saved inquiries,
   suggestions and bank receipts retain their separate persistence rules.
6. On return, the customer can read the saved suggestions and choose
   **Escuchar recomendaciones**. The rc.2 supplement records useful condensed
   merchant and receipt advice. The complete suggestions remain on screen.

The product supports quiet follow-up checks and retained context. Earlier
recordings include a real scheduled check; scheduling behavior and observation
limits are documented in the appendix. The owner has requested submission
housekeeping and human review without another fleet or extended follow-up run.

## Consent, uncertainty and limits

A separate **Revisar recepción simulada** path asks the customer to review the
exact charge and explicitly confirm before simulated intake. The host independently
verifies its receipt. A folio establishes intake only, without a refund, bank
decision or human pickup. Follow-up reads do not resubmit an action. Portuguese
clarification and fallback behavior are documented in the measured comparisons.

The later October 5 fleet attempt returned correct bank facts and complete
foreground speech, but failed its first root model call and produced no reviewed
team result. The UI preserves that failure honestly. This limitation does not
block the owner's reduced submission scope. Earlier successful recordings are
separate evidence, rather than a claim that new fleet execution succeeded.

Physical microphone quality, exact 100-agent customer completion, human pickup, push/email
delivery and real bank resolution are unqualified. The saved recommendation speech
condenses the advice; it does not read both suggestions verbatim. Independent
human audio review remains pending as part of reviewing the submission.

The [release report](RELEASE_CANDIDATE.md) identifies source/image provenance and
all deliverables. The [measurement appendix](measurements/MEASURED_RESULTS.md)
retains timings, language results, failures and original recorder receipts.
For local development, use the [isolated RC setup](../../deploy/rc/README.md);
private fixture codes, credentials and ledger state stay outside public media.
