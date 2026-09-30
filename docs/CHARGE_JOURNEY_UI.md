# Selected-charge journey

This documents the source UI and host boundary for issue #21. It does not record
an installed graph, an enabled action, a deployed source pair or a human response.

## Consent

Chat remains read-only. “Sí” or “sim” sends a chat message, with no action request.
The separate confirmation control names the saved prepared charge, including its
merchant, event date, exact amount/currency and full public reference. Preparation
must return a valid saved snapshot and transaction facts; a handle alone is
insufficient. A different selection, changed facts or changed snapshot prevents
confirmation. Hidden amounts must be revealed locally before confirming.

The server resolves the public reference within the authenticated owner's records
and compares the prepared facts against that same owned row. It never derives a
private transaction ID or an MCP selection handle from browser text.

The customer prompt searches by the event's recorded calendar date, with at most
90 inclusive dates in the disclosed serving snapshot. Partition dates do not
choose the window. Explicit historical windows remain unchanged within verified
bounds; unavailable coverage requires clarification. The host's separate real-time
120-day intake eligibility policy remains in force.

## Existing simulated receipt

The prepare operation can return terminal `existing_case_verified` only after
FLUJO reads the saved receipt by the same pending handle and checks its equality
with the exact owned prepare projection. This branch makes no confirm call.

The UI shows the receipt's `simulated_intake` kind, `simulated: true` marker,
`status: received`, reference, saved transaction facts and original snapshot.
The current lookup snapshot is labelled separately. “Received” describes the
local simulation; it establishes no refund, dispute resolution or human pickup.
The same selected charge has no second intake/confirmation control.

An explicit request for human help may use that same saved pending handle. It
does not create another intake. Unresolved actions for another charge stay locked.

## Saved human request

The customer may enter up to eight unanswered questions of at most 240 Unicode code points
each and press the explicit human-review control. Questions are customer text;
they never supply verified charge facts or authority.
Incoming text is trimmed once before saving. Controls and lone surrogates are
rejected; valid accented text and emoji are preserved. Saved packets must match
their canonical text exactly.

The browser sends `unanswered_questions`; the host freezes the list with the
reason, target and request UUID before sending FLUJO's HTTP `unanswered_questions`
field. FLUJO forwards it to MCP `unanswered_questions`. An uncertain retry reuses the
saved tuple. Omitted questions replay the saved list; an explicitly changed list,
reason, request ID or target is rejected.

Only verified readback can show a HOF reference. The host validates the saved
packet's schema, facts, reason, questions, provenance and human-response marker,
then projects bounded public fields for the UI. The UI displays:

- Saved charge facts and the reason for review.
- The saved unanswered questions, or that none were recorded.
- The historical snapshot and the UTC time the host consulted it, labelled
  “Snapshot consultado el/em”. This is not the bank-data cutoff or proof of freshness.
- Snapshot currentness reported during verification: same, different, unknown,
  or not applicable for a general request.
- “Request saved” and `human_responded: false`, without claiming a person joined.

General requests have no charge facts or charge provenance. Malformed, conflicting
or unverified packets do not display a verified reference. Persisted projections
retain the same evidence through refresh and restart.

## Prompt and source checks

`resources/prompts/customer_v0.md` is the canonical customer-flow prompt. The
builder reads its exact LF bytes and embeds them in the generated source example;
`demo/customer_v0/prompt.md` is removed. Provenance and the manifest pin the actual
Git source inputs and prompt digest. The model graph exposes three banking reads
with empty resource/prompt/skill attachments. Host actions remain separate.

Unit and DOM tests cover ES/PT consent, selection changes, hidden amounts, receipt
and packet validation, saved questions, ownership, retries and recovery. Source
tests and a production build establish no live model behavior or deployed proof.
