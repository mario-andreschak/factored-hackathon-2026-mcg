# Synthetic frontend checkpoint source

This directory provides test-only dependencies for a separately reviewed hosted
integration checkpoint. Importing them starts no server or request. They do not
change the shipped frontend, worker policy, banking MCP, package builder or
discovery procedure. The special package/discovery checkpoint must retain zero
banking calls and writes; a later integration run is separate evidence.

The source base is banking `1b227f64f40e52a5f653a50d56d632cd209e0429`.
Its frontend runtime is the reviewed `71ac0f02` / `ccaedb71` source. The restored
package dependency is the independently reviewed package run `36679668855`, OCI
artifact `11080919734`, reviewed packaging head `6ebeaf73`, with banking `71ac0f02`
and FLUJO `51ff39fc` installed. These identifiers do not authorize execution or
establish startup, model, browser or customer acceptance.

## Boundaries

- `frontend_driver.py` drives the actual frontend API through an injected async
  client. The real host remains responsible for cookies, owner resolution,
  selecting private transaction IDs, minting prepare UUIDs, signing assertions,
  storing action state and verifying readback. The driver submits explicit
  programmatic consent; it does not establish a browser click or human consent.
- `frontend_fault.py` is an opt-in forwarding transport for the existing private
  `ChatService._transport` seam. It withholds one completed, correlated upstream
  prepare response only after a durable MCP commit observation. It does not
  fabricate a response, alter signed headers or arguments, or expose a fault
  control to the browser or model.
- `frontend_confirm_fault.py` separately withholds one real confirmation
  response after matching case/receipt commit evidence. The shipped host then
  reads the same handle's receipt upstream; a single lost confirm response
  normally recovers inline. This is separate from prepare/restart uncertainty.
- `frontend_observers.py` supplies read-only observations of the generated
  fixture's frontend/MCP SQLite databases and real-clock ingress verification.
  Missing, stale or conflicting state must fail the checkpoint, never become a
  successful commit observation.
- `frontend_browser.py` supplies a separately scoped probe for an injected
  browser page. It observes the shipped UI's login, selected charge, disclosure,
  consent request and receipt. It launches no browser and has no default URL.
  An automation click is browser-path evidence, never human acceptance.

All test identities, keys, access codes, snapshots, state and ledger rows must
belong to the explicitly generated ephemeral fixture. Do not mount organizer
data, live S3 configuration, existing private policies or shared state. No helper
installs a graph, starts a worker, enables actions or seeds a conversation.

The current invite mode intentionally rejects configured chat. The hosted
fixture must use a separately reviewed private **demo** configuration with
explicit generated profile/customer and principal/customer bindings. Do not
relax the invite guard. Existing demo API metadata can say `organizer-snapshot`
even for generated test data; preserve and disclose that output separately from
the harness's explicit generated-fixture provenance. It is not evidence that
the product authenticates fictional provenance.

## Required hosted assembly, still unexecuted

1. Independently verify the downloaded package and restoration manifest, then
   record installed worker/MCP source identities and the frontend source/image
   identity. Record the separate harness dependency commit and file hashes.
2. Materialize the reviewed present-relative generated fixture into a fresh
   directory. Use real UTC authentication, expiry, transport and recovery clocks.
   A future business timeline requires its own reviewed source pin. These
   helpers supply no clock override and perform no coverage attestation.
3. Bind the ephemeral private policy, exact stdio registration and final saved
   graph. Verify the saved ID, canonical hash and ingress `flow-<saved-name>`.
   Disclose the deterministic provider fixture and its source hash. Do not make
   external provider/model requests or treat it as real-model acceptance.
4. Start only the separately approved hosted assembly. Keep local/shared
   containers, graphs, policies and action flags untouched. Complete bootstrap
   through actual frontend chat and normal FLUJO `runFlow` using that deterministic
   provider fixture. Never seed `conversation_id`, fabricate a worker `_post`
   result or adopt an unrelated conversation.
5. Attach the opt-in transport to the **lifespan-created**
   `app.state.chat_service`; do not replace the service while its revocation
   worker retains the previous instance. Correlate the login session privately
   from its cookie and ephemeral state. Never include cookies, bearer tokens,
   signed assertions or key material in receipts or logs.

## Separate stock and attested phases

A fresh ledger has no established 24-hour coverage. First exercise that stock
state, without an attestation. Then, only in the separately reviewed hosted
setup, the backend coordinator may initialize a closed, authored synthetic
past-24-hour interval with the shipped
`StateStore.attest_sandbox_coverage(start, provenance)` API. Bind its exact
authored-history artifact SHA256, ledger generation, configured start and exact
fixture-declared provenance (the present fixture uses
`synthetic:present-v1:<history-sha256>`). The history hash is distinct from the
fixture source-pin hash and the hash of the provenance string stored in SQLite.
This is explicitly fixture-seeded
history and coverage, never evidence of 24 hours of observed operation. Do not
rewrite database timestamps, seed receipts, use a future clock or substitute a
configuration-only coverage claim. All authentication, replay, TTL, attestation,
new-case, receipt and handoff clocks remain real.

In the stock phase, use an owned selected charge to prepare a `missing_evidence`
policy handoff.
Assert its actual pending record, complete owned facts, saved packet and readback,
including default empty unanswered questions. Calling selected human help without
a handle first prepares the charge; this can return the policy handoff before
the submitted customer reason/questions are forwarded. Test question freezing
and explicit retry separately with a **general** `customer_request` handoff.

Independently verify the attestation row against the exact closed fixture and
current generation before supplying `AttestedPhaseEvidence` to the driver. The
observer verifies correlation and real-clock bounds; a matching hash does not
establish the fixture's completeness, approval or history. Start a deliberately
new selected prepare identity. Use separate fresh ledger generations and driver
instances for the default and attested phases; the driver also supports an
explicit transition after a recorded stock handoff. Exercise
prepare, separate explicit consent, confirmation, fresh receipt readback and a
new same-charge existing-case check. Preserve the original receipt and handoff
evidence. Also cover confirmation response uncertainty through receipt/status
readback, explicit general handoff retry, and ownership denial. Never repeat a
confirmation to resolve uncertainty.

For the post-commit fault case, the transport must receive and drain a genuine
successful FLUJO response for the original host-reserved prepare identity,
observe its corresponding pending row (and policy handoff packet in the stock
phase), and durably consume its one-shot marker before withholding delivery. A transport exception
after that point exercises controlled response loss; it is not a literal TCP
socket-drop claim. A fault before commit or a canned 200 establishes neither
commit nor recovery. Never inject HTTP 429 after commit: the host interprets 429
as pre-admission rejection and rolls back its reservation.

Restart only the approved hosted components, retaining both frontend databases,
the browser/client cookie, FLUJO ownership/conversation state, the complete MCP
state database, stable service secrets and the consumed fault marker. Reattach
the transport to the new lifespan-created service. Recover through action status
using the existing session; do not log in again or submit a fresh prepare.

Required observations are the same server UUID, target, private transaction,
snapshot, conversation and pending handle; one original pending identity; the
same saved HOF ID/packet; legitimate frontend action/revision advancement; and
zero confirmation/case/receipt/additional-HOF writes in a prepare-only recovery.
Preserve real 570-second host recovery bounds and single-use fresh assertions.
Expired, missing or mismatched proof leaves the checkpoint unresolved.

## Runner interfaces

Use the existing async client's cookie jar for `FrontendDriver`; never put an
access code or cookie in a report. `login_and_select` verifies the fresh demo
login and owned overview. `inquire` supplies the selected public reference to
the actual chat route. `prepare` lets the host mint its UUID. After the terminal
stock handoff and independently verified setup, `begin_attested_phase` enables
a deliberate new prepare. A fresh positive assembly uses
`begin_independent_attested_phase` before any action. `explicit_confirm(confirmed=True)` is a separate API
operation; it is never automatic or retried. `read_status` and `recover` retain
the saved identity and use frontend GETs. After intake, the explicit
`begin_existing_case_check` and new prepare must return the same receipt.
General handoff retry retains its original UUID, reason and frozen questions.
The shipped UI includes its own random `request_id` in the prepare POST. The
frontend route forwards only the owned private target/snapshot, and
`ChatService.action` unconditionally mints a new server UUID. Never require
equality between the browser UUID and server UUID. Correlate the exact observed
UI request/response, then independently verify the returned server UUID against
the saved host intent. The browser UUID grants no authority.
Confirm responses may omit the original prepare UUID and top-level prepared
facts. Retain the captured UUID internally, without adding it to wire evidence,
and bind the response to the same target, handle and verified receipt facts.
Frontend status is a GET; its upstream recovery uses the worker's action POST
with `operation=receipt`, never another confirmation.

Construct `GeneratedFixturePaths` with explicit files inside the new fixture
directory. `read_login_session` privately binds the actual cookie to its saved
session, and `FrontendObservers` uses trusted public keys and the fixed scope.
Its identity, host-intent and commit callbacks are the forwarding transport's
dependencies. `verify_attested_phase` hashes the explicit authored artifact and
reads the existing generation/coverage row; it performs no initialization.
Stock missing-coverage proof must also inspect the actual coverage absence,
stored incomplete risk/null count and zero business case/receipt rows. The
worker's public prepare response does not include that risk projection.
Actual ledger readback and generation-bound before/after business-row snapshots
must establish fresh receipt creation after consent and no duplicate case or
receipt writes; shaped JSON alone is insufficient. Authentication/replay rows
are outside those business-write counts.

Construct `FileConsumedJournal` with an explicit fixture-contained path and load
its consumed marker on restart. Construct `PrepareDropTransport` with that
marker, the observer callbacks and a fresh inner transport factory for every
request. Its fixed origin must be the actual ephemeral worker. A consumed marker
is immutable; later legitimate host intents pass through without rearming.
A distinct fault phase needs a separately fixed scope and journal. The marker
contains the pending capability's hash, never the capability itself.

The API/fault/observer helpers require the existing pinned banking/core Python
dependencies, including `httpx` and `rfc8785`; the standalone frontend image
does not include all of them. Pin their reviewed source and dependency assembly
separately from the restored archive. The browser probe accepts a caller-owned
page and imports no browser launcher. The hosted runner must pin and review its
browser dependency and static frontend build before execution. Retain sanitized
step/outcome records and scoped fictional UI screenshots. Do not retain raw
Playwright traces, HAR/network records, storage dumps, cookies or assertions.
The browser truth verifier is an injected runner dependency, not an implemented
browser-to-ledger bridge in this source contribution. Its exact source must prove
the effective static build, generated owned selection before any screenshot,
current cookie/session correlation, pending receipt absence, and fresh matching
case/receipt creation. Typed callback values or declared fixture labels alone
do not establish those facts. Review and pin that adapter with the hosted runner
before executing the probe; missing adapter proof must stop that phase.
Keep the coordinator/observer alive across frontend/worker component restarts.
The pre-consent freshness baseline stays in memory. Recreating an observer after
commit loses that predecessor and must fail a fresh-creation claim rather than
reconstructing consent or absence from an existing receipt. Sanitize runner
exceptions to fixed failure codes; browser errors can echo form input values.

## Evidence limits

Pure helper tests use fakes and temporary synthetic SQLite records. They do not
start an application, make HTTP requests, restore an image, run a model, generate
actual banking commits, render a browser or restart Docker. Their results must
remain separate from later joined hosted observations. UI consent is separately
covered by the existing `frontend/src/Assistant.test.tsx` DOM tests with mocked
fetch; it must not be combined with API-driver results into invented joined
browser acceptance. The new injected browser probe remains unexecuted until its
exact source, dependency pins and hosted assembly are reviewed. A later sanitized
browser step sequence and screenshot must be reported separately from API, pure-helper and
deterministic-provider results, and must use fictional data only.

The existing 22 ES/PT historical utterances are correct UTF-8 and remain
unchanged. The future-date replay design and its new clock source remain separate
from this present-relative safety checkpoint. No helper fills human judgments or
claims that a saved handoff means a person joined.
