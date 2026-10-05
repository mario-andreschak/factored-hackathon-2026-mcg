# Reproducible fictional customer journey

Start the isolated candidate using [the RC launcher](../../deploy/rc/README.md).
Portal: `http://127.0.0.1:43900`. Read its access code privately from the generated
fixture; never include the code, cookies, keys or fixture JSON in public media.
The runtime's private `runtime.json` identifies the actual language provider.
The bank side is the project's shipped Banking MCP Service in process, with a
fresh fictional dataset and isolated simulated-intake ledger. This does not
qualify network MCP transport, native flow execution or real bank resolution.

1. Sign in to a fictional profile. Open a purchase and choose **Revisar este
   cargo**. The selected owned charge stays visible with its merchant, date,
   amount and status.
2. Ask **No reconozco este cargo. ¿Qué puedo hacer?** Savia runs the existing
   dispute engine and permitted bank reads. The answer explains the verified
   charge and next step. A failed language stage uses the selected interface
   language and retains bounded owned display facts without claiming an action.
3. Choose **Revisar recepción simulada**. Read the exact merchant/date/amount
   before explicitly confirming. A chat answer alone cannot confirm intake.
4. The host confirms the authorized simulated request and independently reads
   its receipt. The visible folio establishes intake only, without a bank
   decision, human response or refund.
5. Choose **Quiero recibir seguimiento de esta recepción**. The host saves the
   original receipt, charge and authorized session context. Its background loop
   performs the first actual receipt check on its next background tick (a
   five-second polling cadence).
6. The card shows **Última consulta**, **Próxima consulta**, the verified result
   and **Próximo paso**. Future checks run every 30 minutes during the authorized
   eight-hour session. Unchanged checks refresh the clock silently. An unavailable
   read preserves the last receipt and says that current status could not be checked.
7. Reload the page, reopen Savia, and compare the same folio and saved follow-up.
   Start another inquiry: saved follow-ups remain accessible below the conversation.
   No confirmation is resubmitted. Logout or expiry pauses background reads.
8. Select Português and ask an ambiguous question without selecting a charge,
   for example **Não reconheço uma cobrança. Qual lançamento é esse?** The
   customer must clarify the charge; model failure must remain Portuguese and
   cannot manufacture identification, resolution or a completed handoff.

The receipt follow-up API accepts only the existing bank cookie and ES/PT locale:

| Request | Result |
| --- | --- |
| `GET /api/followups?language=es` | Saved customer view; an authenticated session before its first chat gets an empty list. |
| `POST /api/followups` with `{"language":"es"}` | Opt in for the current verified simulated receipt; duplicate enrollment is idempotent. |
| `POST /api/followups/check` with `{"language":"es"}` | Bounded read-only receipt check; never confirms or resubmits a request. |

The same APIs accept `pt`. Public follow-up fields include the folio, charge
selection reference, timestamps, status, next step and bounded meaningful update
history. Private handles and bank identifiers remain on the host. The frontend's
`savia:context` event shares reference-free selected facts and public conversation
history with the integrated Savia voice surface. Native spoken turns retain a
separate, session-scoped playback acknowledgment.

Source checks cover receipt persistence and exact corroboration, ownership,
revocation/expiry, unavailable reads, concurrent check leases, fresh-login behavior,
Portuguese timeout fallback and replay binding, and readable customer facts. Actual
provider timing and recorded journey results belong to the measurement artifacts;
unit tests alone do not establish that complete customer gate.

## Savia inquiry team and new conversation

Savia's assistant dialog integrates the PR52 eyes and conversational voice.
**Hablar con Savia** starts the microphone; the same dialog retains the typed
task dialogue, selected charge, consent, receipts and saved inquiry cards.
The voice can keep conversing while a bank request works in the background.
Bank questions pass through the authenticated Savia chat. Exact host replies
remain on screen and are registered once before native narration. A spoken
caption joins conversational history only after complete playback is acknowledged.
Native voice context is session scoped. The durable bank transcript, receipts
and saved inquiries retain their existing persistence rules.

The joined RC also offers **Pedir ayuda a un equipo**. Submit an informational
question about the selected owned charge. Two separate model workers compare
the visible evidence and choose useful next steps while foreground conversation
continues. Their actual queued, working and completed events appear in the saved
inquiry card. Model prose cannot authorize bank actions or establish human work.
The card retains reviewed suggestions and asks whether they answered the question.
**Esta respuesta resolvió mi consulta** closes the informational inquiry only.

The first scheduled reminder is after 30 minutes; unchanged follow-up checks stay
quiet. Inquiry tracking lasts up to seven days and survives a renewed login.
It performs no bank reads and does not extend consent or bank-session authority.
Human work is reported only after explicit operator acceptance.
Completed inquiry narration uses the authenticated case/event cursor and exact
host-projected reply. Queued and working events update the card without speaking
a completion claim; unchanged polls do not repeat a result.

**Empezar chat nuevo** archives the visible chat for that profile and clears its
selected context and composer. **Ver conversación anterior** restores the view.
The server transcript, receipts, pending consent, saved inquiry cards and receipt
follow-ups remain separate. This is a presentation boundary, not a bank-action reset.

| Request | Result |
| --- | --- |
| `GET /api/assistant/cases?language=es` | Authenticated owned inquiry cards, true worker states and bounded events. |
| `POST /api/assistant/cases` with `message`, `language`, optional `transaction_reference` | Explicitly start a bounded informational team; selected display facts are resolved by the server. |
| `POST /api/assistant/cases/{id}/resolve` with `{"resolved":true}` | Customer marks an informational answer helpful; does not resolve a bank dispute. |

The standalone frontend image can serve banking views without this optional
package; it returns an empty inquiry list and unavailable creation. Actual joined
team/provider evidence is recorded separately in `assistant/mcp-smoke.json` and
the updated browser story, rather than inferred from component tests.

## Current integrated native Savia acceptance

The coordinator accepted the required product steps on source
`9d77a7599128b668b0e34f9c2937eb40b6bd3824`, image
`sha256:484fe8edc07ac37dd78f61deb7a08254352b8ce597fa8265f917706e93d199a5`.
The served `index-DGVQHrRT.js` matches SHA256
`f06ecbad1ea5089a227a04ea7468aeb8f4b1ef023ac04a98e6b71379771cc8bd`.
See the [accepted native receipt](measurements/intended-savia-native/receipt.json).

This run continued the same authenticated session and third existing inquiry.
It captured calm foreground conversation, the customer's helpful informational
closure, retained worker suggestions, a new chat view and restoration of the
exact saved bank reply. Both native turns completed with HTTP 200 full-playback
acknowledgments matching all audio samples. The spoken result reported the
helpful closure; it did not read the recommendations or claim bank resolution
or a refund.

The safe evidence includes [integrated eyes and microphone](measurements/intended-savia-native/native-eyes-mic.png),
[retained inquiry suggestions](measurements/intended-savia-native/completed-inquiry.png),
[new chat](measurements/intended-savia-native/new-chat.png), and
[restored bank facts](measurements/intended-savia-native/restored-bank-facts.png).
The two native audio files are [foreground reassurance](measurements/intended-savia-native/foreground-calm.wav)
and [informational closure](measurements/intended-savia-native/informational-closure.wav).

This continuation created no new bank chat, inquiry or worker task. Runtime's
final read-only freeze held three inquiries, six workers and 24 events, with
zero bank cases or receipts. Earlier two-worker creation and partial speech
overlap remain separate evidence; this run does not qualify new worker creation
or full simultaneous speech. Actual ASR contained recognition errors, and a
physical microphone was not qualified.

The raw runner's completion flag remains false: an optional response-body
diagnostic reached its 180-second bound after the required product steps and
both full-playback acknowledgments had passed. Product acceptance is recorded
separately in the receipt. The raw diagnostic was retained and no rerun was made.

## Historical banking and team recordings

The unmocked `measurements/team-story-final/` recording shows the selected
charge answer in 9.34 seconds, followed by one actual two-worker inquiry request
whose useful result reached the UI in about 4.1 seconds. The customer explicitly
marked the informational explanation helpful, started a new visible conversation,
returned to the prior context and reloaded the same saved inquiry. No new bank
confirmation was submitted. The final held screenshot
`11-saved-useful-result.png` shows that the useful suggestions remain visible
after closure and reload.

This fast recording used the disclosed direct OpenRouter language profile. The
earlier `story-es-v2/` recording separately proves explicit simulated intake,
verified receipt and an actual automatic receipt follow-up. Their fictional
in-process bank scope and earlier provider failures remain in the measurement
report. Voice foreground overlap and its honest invalid-date failure are separate
artifacts; they do not turn that failed bank read into a successful answer.

The original three-case final comparison remains two useful replies out of three.
Its Portuguese selected-charge failure exposed selection loss during question
decomposition. After fixing compatible query-scope selection retention, one exact
fresh-conversation Portuguese retry completed in 18.81 seconds with a useful
answer and no repeated request for known date/amount. Generated recommendations
were rejected by the existing guard; the successful customer-facing reply was
the deterministic host display of independently checked selected facts. See
`measurements/post-fix-pt-selected.json`. This is a separate post-fix observation,
not a replacement or enlarged claim for the original comparison.
