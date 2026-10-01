# Gloria development acceptance

## Release qualification in progress

The release lane resumed October 1, 2026; the previous pause and timebox no
longer apply. `tests/test_gloria_release.py` adds independently expected release
behavior. A failing required case remains a failure; it is not skipped or
relabeled as an accepted implementation limitation.

| Release boundary | Evidence required |
| --- | --- |
| Owned bank reads | Real repository/MCP-backed profile, complete transaction searches with product/location filters, exact rereads, historical complaint list/exact status, separate unknown historical linkage, and verified sandbox duplicate/risk coverage. Ingestion lineage alone cannot assert source verification. |
| Multiple requests | Each query executes serially with its own explicit slots, target, candidate snapshot, policy result and pending state. An inquiry cannot inherit another query's receipt or consent. |
| Native execution | Immutable pinned FLUJO graph execution, effective tool allowlist under poisoned shared state, isolated simultaneous owner/conversation contexts, trusted selection propagation, and host rendering of validated tool output. Compilation, direct Python execution and installation are distinct evidence. |
| Host consent and receipts | Prepare and explicit portal confirmation share exact owner/session/conversation/target/snapshot. Cancellation and new requests invalidate the old handle durably; revocation/restart/replay preserve scope. Uncertain writes retain receipt recovery. Contradictory receipt formats cannot verify one another. |
| Grounded ES/PT response | Conditional recommendations require reviewed, relevant policy support. A valid unrelated chunk ID does not establish that support. Repeated unsupported advice gets one repair then safe fallback. Scripted probes do not establish learned-model accuracy or human semantic adjudication. |

Run both suites from the repository root:

```powershell
python -m pytest tests/test_gloria_acceptance.py tests/test_gloria_release.py -q
```

The initial release cases use actual `Workflow`, response validation,
`ChatService` admission/action persistence, public confirmation request schema,
and `RepositoryBank` receipt binding. Their transport is an in-memory fictional
host; no shared worker, network bank, provider or deployment is activated.
The first release checkpoint exposes missing recommendation support checks,
single-query-only execution, conflicting receipt-proof promotion, durable
portal cancellation, and receipt followup after an unclear chat classification.
It is development gap evidence, not a release pass.

The bank release fixture now generates its own prototype CSV source, adds
fictional product-number suffixes and a nearby cross-product/cross-merchant
duplicate, publishes through the real pipeline, and constructs the actual
`Service`, public repository and `OwnedBankReads` port. It checks complete
profile fields, all four additional filters, full counts versus five displayed
candidates, owner-indistinguishable exact reads, unknown historical linkage,
private selector rejection, pinned-source mutation, sandbox attestation, and
verified receipt integrity in the exact half-open 24-hour window. Direct SQLite
fixture inserts represent newly invented sandbox receipts, never live actions.

Fictional event-date currency rates are separately pinned by exact file hash.
The release probes require the correct date/currency lookup independently of
the transaction source's observed USD amount. Missing files or keys, changed
bytes, duplicate keys, malformed fields, nonpositive/nonfinite/extreme rates,
invalid unrelated rows and oversized files leave USD risk unknown. USD source
transactions retain exact native magnitude without a rate lookup. Native
amount/currency remain the customer display facts; rates, conversion provenance
and their hash stay private. Actual ES/PT HTTP cases with missing rates route to
human review without an intake receipt or confirmable intake preparation; a
saved review request does not mean a person has responded.

The actual bank subset reached 23 passing assertions against a development
integration checkout after its owners repaired profile and duplicate projection.
That checkout was changing during implementation; this checkpoint is useful
for gap closure and is not substituted for a final frozen-source run. The
native closure case additionally requires a validated host selection to survive
the MCP bridge without expanding its model input schema.

The joined ES/PT cases additionally enter through the real `create_app` HTTP
routes: fictional login, server-validated selected transaction, actual typed
language adapters and workflow, authoritative source reads, private
`BankingActionHost` on the same ledger, portal confirmation and subsequent
workflow receipt rendering. They assert one saved case after confirmation
replay. A scripted model supplies classifications only; it does not supply
identity, bank evidence, action admission or receipts. These cases exposed a
first-turn admission ordering issue that source-read and spy-workflow tests
alone did not exercise: the bank port requires the trusted conversation to be
persisted before the workflow begins its reads.

Native host-port probes use temporary admission files and controlled application
workflows. They check validated-result rendering, trusted selection copies,
failure cleanup, simultaneous distinct owners/conversations, cancellation that
preserves a sibling admission, rejection before registration for expired
bindings, and restart after an abandoned writer marker. These probes invoke no
provider and do not qualify native FLUJO callbacks or installation. Actual
native qualification must separately establish expired/removed-token fences
during provider and MCP awaits, one execution under concurrent replay, private
durable admission files, and equality between the requested source manifest hash
and the verified manifest inside the executed image.

`scripts/qualify_gloria_app.py` reproduces a separate joined application using
current-date generated source, explicit fictional event-date rates, an isolated
sandbox ledger and the real loopback HTTP routes. It covers ES/PT intake,
explicit false/true consent, receipt followup after application restart,
confirmation replay, logout revocation, and human/emergency review. Its report
includes before/after source hashes, salted identifier hashes, request/stage
latency and observed usage; unavailable usage/cost stays null. Public reports
exclude request bodies, replies, cookies, signing material and raw identity.
Bounded returned stage text is retained separately under the generated private
fixture directory for diagnosis. Only its salted hash and host validation codes
enter the public report; the observer delegates the same native model calls.

Fixture publication alone can be reproduced without a worker or provider:

```powershell
python scripts/qualify_gloria_app.py --workdir-private '<new-private-dir>' --output '<new-report.json>' --prepare-only
```

With a separately installed and qualified isolated worker:

```powershell
python scripts/qualify_gloria_app.py --workdir-private '<new-private-dir>' --output '<new-report.json>' --native-url 'http://127.0.0.1:<isolated-port>' --native-authority-dir '<isolated-authority>' --cases intake-es,intake-pt,human,emergency
```

The default language path invokes `NativeGloriaPort`; injectable scripted ports
or transports are explicitly reported as offline. Observing a model completion
does not attest that the protected native extension was installed and executed.
The report therefore retains `native_execution_verified=false` until external
installed-artifact and same-turn native callback evidence are joined to it.
Expected scenario labels are authored assertions, not human adjudication.

The first clean local release checkpoint passed **178/178** cases in 44.23
seconds at acceptance checkout `890b9df69ebd7816e286c1e3ad6052618d41aa79`.
Git HEAD, 69 application source hashes and both test-file hashes were identical
before and after the run. The sorted source-map SHA256 was
`13837db0bd77106e8088aa6b016f8672ba37cdca108ef54a3b02b8841b11b824`.
This includes actual fictional HTTP journeys and controlled native-port
admissions; it does not establish real provider or protected native execution.

The subsequent real-worker intake diagnostic failed both scenarios. Spanish
reached the expected confirmation mode but used the safe fallback after
recommendation validation rejected both generated attempts. Portuguese produced
the correct native amount, currency and event date but its `cartão` product hint
did not match the bank's Spanish product label. The run used 13 model attempts
and 100,454 reported tokens; provider cost remained unknown. Application source
changed during execution. Those failures remain diagnostic gaps, with additional
independent ES/PT product-hint cases preserving conflicting-product rejection.

The next frozen local checkpoint passed **185/185** cases in 70.44 seconds at
acceptance checkout `e306036543da9c64b8cfcb964d50110b28c8cf9d`, merging integration
candidate `b6fb52c`. All 76 graph-protected source hashes matched the generated
artifact. Git HEAD, 79 captured source hashes including that artifact, and both
test-file hashes were unchanged before and after execution; actual source bytes
matched integration. The sorted source-map SHA256 was
`20132d1003480469ab54c3c1b754820ecd34b019ad5cc218ce1aebd2d08e91b7`.

An additional independent review then exposed a false-success boundary outside
those 185 cases: Spanish and Portuguese present-progress claims said a request
was processing despite no authorization, execution or receipt. Four new release
assertions reproduce that rejection gap, including after a truthful statement
that chat cannot register the request. The frozen 185-case checkpoint remains
historical evidence; the expanded 189-case suite and actual native qualification
require a corrected, frozen source candidate.

The corrected frozen candidate then passed **189/189** cases in 66.34 seconds at
acceptance checkout `1f0d96b7962427ad1961209d54a3289a7ffb2c8b`, merging integration
candidate `b0fcbba`. All 76 graph-protected hashes matched the saved artifact.
Git HEAD, 79 source hashes and both test-file hashes were unchanged before and
after execution; the checkout stayed clean and its source bytes still matched
integration afterward. The sorted source-map SHA256 was
`63c0d669659b9426499ec2d3a998590ba5be0b40705afd671004b492c549b04b`.
The four new false-progress claims reject; verified past-tense receipt notices
and truthful negative portal limitations remain usable. This is the final
local boundary checkpoint for that candidate, with actual provider/native
qualification still recorded separately.

The first complete guarded-source native run passed **1/4** scenarios in
245,605 ms. Both ES/PT intake chats returned HTTP 502 with a pre-workflow
`PermissionError`; no model call, durable turn or intake write was reached in
either case. Spanish human review passed without fallback and saved a verified
review request without claiming a human response. Portuguese emergency review
reached the correct policy mode and reason, but its repair's truthful uncertainty
sentence was incorrectly rejected as completed handoff success. Its first
unsourced emergency-contact advice remains rejected.

All 69 harness source hashes and the external 79-file host capture, both tests
and installed native manifest stayed unchanged. Git HEAD changed through an
unrelated merge while those source bytes remained equal. The run observed 15
successful model attempts and 112,334 reported tokens; provider cost stayed
unknown. It is retained in
`docs/qualification/gloria-joined-native-diagnostic-2026-10-01.json`, separate
from the final qualification path. Four additional independent cases cover the
truthful PT uncertainty and rejection of added success, human-response and
unsupported contact claims; the expanded suite has 193 cases.

The subsequent historical `79f6e80` source checkpoint passed **193/193** cases
in 78.11 seconds with unchanged HEAD, both test hashes and 80 captured source
files; all 77 graph-protected hashes matched. Its actual native HTTP diagnostic
passed **2/4** journeys in 381,043 ms, using 41 successful model attempts and
315,476 reported tokens with unknown provider cost. Spanish intake and human
review passed. Portuguese receipt followup and emergency review fell back after
one repair despite reaching their expected policy modes. All source, generated
fixture, host and installed-manifest captures remained stable.

The receipt guard split the decimal point in `209944.00 COP` as a sentence
boundary, detaching a truthful registration claim from its verified receipt ID.
The emergency guard rejected a truthful restatement that the customer needed
to speak with a human attendant as contact guidance. Its initial instruction
to call a local emergency service remained correctly rejected. Five additional
independent assertions reproduce these two gaps while preserving rejection of
a separate success sentence and appended unsupported contact advice. The
required suite now contains **198 cases: 91 acceptance and 107 release cases**.
The historical 193-case pass and 2/4 diagnostic do not qualify the next frozen
source and installed image; those require fresh matching captures.

These independently authored development cases execute the application-owned
`gloria_workflow` orchestration and deterministic motor. They use newly invented
ES/PT messages and fictional records, not the frozen router evaluation files or
organizer data. A scripted language port and an observed, read-only bank port
make classification errors, timeouts, malformed outputs, stale evidence, and
receipt uncertainty reproducible.

Run from the repository root after the Gloria implementation is integrated:

```powershell
python -m pytest tests/test_gloria_acceptance.py -q
```

## Contract-derived cases

| Area | Required observation |
| --- | --- |
| Normal ES/PT | An eligible, owned dispute requests the portal control; inquiry reports evidence; no chat action write. |
| Ambiguous and unsupported | Multiple candidates require selection; ambiguous pesos require currency; an explicit currency reply retains the amount; an unrelated balance request changes scope; unsupported history does not fabricate evidence. |
| Human and emergency | A human request in the original message survives a false intent label. Active current misuse escalates; a past unfamiliar charge alone does not imply emergency. |
| Model failure | Timeout or malformed classification fails closed. An invented success or receipt is rejected, retried once, then safely replaced. |
| Ownership | Authentication and third-party guards precede private reads, including when the model suppresses the foreign-reference signal. Stored pending state never crosses customers or conversations. |
| Consent and replay | Chat `sí/sim`, a model `CONFIRMED`, and selection never authorize intake. Replayed turns or uncertain outcomes never attempt another write; an expired session cannot replay private evidence. |
| Receipt uncertainty | An attempted action without verified readback retains `ACTION_UNVERIFIED`, including after a verified human-review receipt. Both native host envelopes and the agreed canonical test projection are exercised. |
| Policy precedence | Authentication/ownership beat old success; age/status beat new intake; an exact existing case beats risk; missing coverage never means low risk. A risk report must cover exactly 24 hours and have a nonfuture endpoint within the configured freshness bound. |

## Evidence scope

The suite tests actual local orchestration and pure policy against injected ports.
It does not measure provider understanding, accuracy on a held-out benchmark,
native FLUJO execution isolation, a deployed joined customer path, or real bank
actions. Scripted classifications are inputs to boundary tests, not evidence of
learned-component ES/PT quality. Language assertions check the declared output
language and fallback behavior, not full linguistic quality.

The generic FLUJO main branch, shared worker, provider/model bindings, restricted
records, and frozen evaluation data are untouched. Production authorization and
the protected banking MCP remain separate from the language workflow.

## Execution evidence

Final independent local run: **91 passed, 0 failed, 0 skipped in 2.45 seconds**,
September 30, 2026 at 23:22 Bogotá (October 1 at 04:22 UTC). The tests were
executed against the actual supervisor integration package with the committed
acceptance file at `a8f5bcd9b1849605d8ed12ce9c41f4edd1904fd9`.

The previous 90/91 run exposed a topic-switch guard: after a dispute asks for
currency, “Ahora quiero saber mi saldo en USD” with model intent `OOD` wrongly
completed the old dispute. The frozen runtime now starts a new request and
returns `OUT_OF_SCOPE` without transaction search. The same assertion passes,
as do all four freshness boundaries and cached-success receipt revalidation.

The integration checkout's Git HEAD was
`6bee817dc74d414153cd714c9f6b4a7f2ca3e06e`, unchanged before and after execution.
Protected application source was committed; the source-only generated graph
was still untracked. The worker's durable `acceptance-status.json` records
SHA256 maps of 36 application modules and inputs: canonical prompts, retrieved
policies, contracts, configuration, graph artifacts, dependency requirements,
and relevant frontend/MCP action boundaries, both before and after execution.
Those maps were identical throughout the run. Their sorted JSON-map SHA256 is
`85728c34434da00b422dda4d237ba3eaab62a868e6f542d82eb3aca1e03996df`.

Earlier 83-case and 90/91 checkpoints are historical development evidence;
neither is substituted for this frozen 91/91 run.

The suite exposed status-field incompatibility, missing selection snapshots,
adapter input mismatch, absent bounded repairs and language notices, receipt
proof handling, ordinary person/spouse guards, complaint selection, and a
candidate-hash/snapshot-ID mismatch. The owners corrected those source issues;
the contract assertions were preserved. The observed test port was adjusted
to accept the real adapter's optional `correction` argument.

The initial Windows test environment lacked `tzdata`; installing it in the
isolated acceptance environment resolved that environment failure. The local
test environment uses Python 3.13, pytest 9.1.1, PyYAML 6.0.3, Jinja2 3.1.6,
and tzdata 2026.4. No provider, MCP transport, S3, or bank write is invoked by
this suite. A later source change or deployment needs its own joined run;
these passing results do not establish a deployed customer path.

The default repository bank port intentionally has no complete historical
complaint or dispute-risk adapter. Its safe `unsupported_history` error and
`HANDOFF/missing_evidence` behavior are tested, not described as full banking
coverage. Injected complete fictional observations exercise the other
canonical motor paths independently of that deployment limitation.

The supervisor's configured-model qualifier is separate evidence. Its four
synthetic mode/language cases are a development smoke check; they neither
establish held-out ES/PT accuracy nor verify action authorization or a saved
FLUJO graph. Extraction must be assessed from the captured intent/slots and
the expected source facts. Unknown provider cost must remain unknown. A
qualifier report also needs a source capture made before execution and a
matching capture afterward to identify the exact code measured.
