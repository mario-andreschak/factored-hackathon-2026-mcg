# Savia inquiry follow-through

Savia keeps a question while two bounded agents look at different perspectives:
one chooses a useful evidence comparison, the other a useful next step. They
make separate concurrent model calls and select reviewed suggestions. They do
not freely investigate bank systems, submit actions, or grant a refund.

`savia_assistant/service.py` owns SQLite cases, workers and meaningful events.
The existing host starts its two-second background loop; this does not block
foreground conversation. A first follow-up becomes available after 30 minutes.
Subsequent unchanged checks remain quiet. Tracking lasts at most seven days and
stops when the customer explicitly marks the explanation helpful/resolved.
Clearing chat does not remove these cases. Reading cases requires a current
authenticated host session; a renewed session for the same trusted customer
can recover them. The scheduler has no bank client and cannot extend consent.

`api.py` installs these routes through the existing host session accessor:

| Route | Contract |
| --- | --- |
| POST `/api/assistant/cases` | `{message, language:"es"|"pt", transaction_reference?}`; 202 `{id,items}`. Selected facts come from the trusted repository. Arbitrary facts/owners/model configuration are rejected. |
| GET `/api/assistant/cases?language=es` | `{items}` with status, suggestions, timestamps, and bounded events. Frontend polls and deduplicates event IDs. |
| POST `/api/assistant/cases/{id}/resolve` | `{resolved:true}` marks an informational solution, never a bank outcome. |
| GET `/api/assistant/voice-update?case_id=...&after_event_id=0&language=es` | Authenticated bounded latest status/suggestions: `{reply,mode:"assistant",status:"completed",event_id,inquiry_state,bank_authority:false}`. 204 unchanged; 404 another owner. Completed meaningful replies are registered to the current session's one-use `Conversation` narration record. Queued/working updates are not registered. |

Event kinds are `queued`, `team_working`, `worker_working`, `worker_completed`,
`worker_failed`, `team_completed`, `needs_attention`, `awaiting_customer`,
`informational_resolved`. `human_working` is available only through an explicit
operator integration hook with actual acceptance. No customer/MCP route can
produce it, and no live human acceptance has been demonstrated.

Each GET-cases item also includes the canonical `voice_update` projection:
`{version:string, reply:string, mode:"assistant", status:"completed"}`. The
version is the last meaningful event cursor. The earlier avatar bridge sends only a
`{type:"savia:inquiry-update",case_id,event_id}` notification to its voice host.
The avatar fetches the fixed authenticated voice-update route, validates the
exact server-owned reply receipt and queues it once in the same conversation.
The embedded projection and route share one canonical renderer. The final
native Savia UI uses the current-session `Conversation.remember_result` binding
for completed, awaiting-customer and informationally resolved replies. Actual
joined speech acceptance is recorded separately from API tests below.

## MCP and generic FLUJO wiring

`python -m savia_assistant.mcp` runs a scoped stdio MCP. The backend binds one
owner and a durable state directory. `savia_inquiry_tick` performs one due pass;
`savia_inquiry_status` reads that owner's cases/events. Neither tool accepts an
owner, bank context, credentials, model selector or arbitrary banking facts.
An optional token-protected streamable HTTP mode is also available for a local
bridge; stdio is the measured mode.

`mcp-config.example.json` describes the private runtime binding, with placeholders
for backend-only values. `flujo-flow.json` is an ordinary generic FLUJO graph:
Start → Static real MCP tick → Finish, with a connected MCP node. Its real
execution mode is explicit, and there is no model or banking policy in FLUJO.
`flujo-automation.json` binds that flow to a half-hour schedule with overlap skip
and no catch-up. It is exported disabled so an isolated smoke does not leave a
recurring dependency running after its process ends. Live installation and
execution must be established by a runtime receipt; these files alone are not
proof. [The runtime receipt](../runtime-mcp.json) now establishes the installed
generic MCP connection, saved graph and disabled schedule, plus one completed
manual planned execution with exactly one actual MCP call. That qualification
used separate empty fictional state and made no worker/provider calls. The app
loop owns the canonical portal's actual two-agent inquiries and follow-up. Both paths use
SQLite leases to prevent duplicate teams.

## Measured scope

[The earlier local browser recording](../measurements/team-story-final/actual-browser.webm)
shows the authenticated create request, actual working state, both completed
workers and seven meaningful events, then explicit customer acknowledgment as
the eighth event. The same case survives new chat and reload. The useful saved
date/amount comparison and next-step suggestion remain visible after closure
in [the final saved-result frame](../measurements/team-story-final/11-saved-useful-result.png).
That recording does not submit another bank confirmation or create another
banking case. This historical recording retains its original runtime/provider
scope; it is not relabeled as the final deployed native capture.

[The accepted final native receipt](../measurements/intended-savia-native/receipt.json)
pins source `9d77a7599128b668b0e34f9c2937eb40b6bd3824` and image
`sha256:484fe8edc07ac37dd78f61deb7a08254352b8ce597fa8265f917706e93d199a5`.
It records 6.6 seconds of foreground reassurance and 3.95 seconds of the exact
customer-marked helpful closure, both with complete playback acknowledgments
matching every sample. The closure is queued after foreground playback; useful
worker suggestions, new chat and exact restored bank reply remain available.
This continues the third existing inquiry with its original two completed
workers; it launches no new team or bank operation. The final read-only ledger
contains three inquiries, six workers and 24 events, with zero bank cases or
receipts. Informational closure does not establish a bank resolution.

The coordinator accepted the required product steps. The raw recorder still
reports failure at its 180-second limit because optional response diagnostics
waited after those steps and both full acknowledgments had passed. The receipt
preserves that failure, recognition errors and the lack of physical-microphone
qualification. Its optional-diagnostics fix was not recaptured. The separate
earlier partial worker overlap is not promoted to full simultaneous-speech
qualification.

`mcp-smoke.json` records an actual SDK stdio client initialization, tool listing,
tick, and status read on a fresh fictional case. Two direct OpenRouter Gemini
calls completed concurrently, producing distinct reviewed suggestions in
2,783 ms total. This is actual MCP and provider work; it is not native FLUJO
execution. The separate generic FLUJO graph's measured empty tick is recorded
in `../runtime-mcp.json`; it does not establish a native FLUJO language run for
the two workers.

`python -m pytest savia_assistant/tests -q` verifies concurrency, scope, restart
recovery, quiet follow-up, sensitive-input and model-output rejection, current
cookie authentication, renewed-session ownership, trusted fact projection,
and explicit informational resolution. Time-controlled tests establish the
half-hour/week scheduling logic, not an observed week of operation.

Reproduce the isolated provider smoke with
`python scripts/submission_assistant/mcp_smoke.py`. It reads the existing private
provider environment locally and never prints/copies credentials into artifacts.
