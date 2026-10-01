# Gloria acceptance and release qualification

## Current source integration evidence

The integrated credential correction at `d7a4f432000db0a225a010235083427f957c35b5`
has a regenerated protected source map. Its
[source qualification](qualification/gloria-credential-source-2026-10-01.json)
records the exact combined source, tests and graph checks. This is source-only
evidence: installed native/provider execution, joined live HTTP and human
adjudication were not repeated for this correction. The existing installed
publication and runtime activation gates still apply to any replacement image.

## Historical abc9068 release qualification evidence

The historical `abc90682faa5cb496c9cd3476ec7811a7e5c9281` candidate passed the
independent source qualification and all four synthetic native-port HTTP
journeys. The source suite passed **198/198 cases: 91 acceptance + 107 release**
in **58.66 seconds**, with **0 failed, 0 skipped**, and one existing
`StarletteDeprecationWarning`. Fixture04 passed **4/4** HTTP journeys in
**334,183 ms**, with matching before/after source captures. This qualifies the
selected synthetic local application paths on the frozen candidate.

Final allowlisted reports:
[independent source qualification](qualification/gloria-independent-release-2026-10-01.json)
and [joined native-port HTTP qualification](qualification/gloria-joined-native-release-2026-10-01.json).
Protected native installation and callback gates are recorded in the separate
[installed-native report](qualification/gloria-native-release-2026-10-01.json);
the HTTP report keeps `native_execution_verified=false`
and `human_adjudicated=false`.

The historical `79f6e80b35b41c4714131e918027cb95569ba128` source checkpoint
passed **193/193** cases. Its **2/4** HTTP result, the first **1/4** diagnostic,
and the earlier `ce2e350` **4/4** HTTP pass belong to their historical source and
image captures. Those measurements are recorded separately below.

The source suite uses controlled model inputs and fictional HTTP fixtures; its
native/provider execution flags are false. The separate HTTP qualification uses
the isolated native language port and fictional bank fixtures. Its
`native_execution_verified=false` remains false: protected installation and
same-turn callback evidence are separately scoped to the exact executed image.
Human-adjudication flags remain false. Neither report establishes human semantic
adjudication or held-out ES/PT accuracy.

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
The historical first release checkpoint exposed missing recommendation support checks,
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
and their hash stay private. Scripted ES/PT cases using actual local HTTP
routes with missing rates go to human review without an intake receipt or
confirmable intake preparation; a
saved review request does not mean a person has responded.

A historical bank subset reached 23 passing assertions against a development
integration checkout after its owners repaired profile and duplicate projection.
That checkout was changing during implementation; this checkpoint is useful
for gap closure and is not substituted for a final frozen-source run. The
native closure case additionally requires a validated host selection to survive
the MCP bridge without expanding its model input schema.

The scripted ES/PT source-suite cases additionally enter through real `create_app` HTTP
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
The HTTP report retains `native_execution_verified=false`. Installed-artifact
and same-turn native callback evidence remain separately scoped to the exact
executed image. Expected scenario labels are authored assertions. The HTTP
report retains `human_adjudicated=false`; the source report retains
`human_semantic_adjudication=false`.

The historical first clean local release checkpoint passed **178/178** cases in 44.23
seconds at acceptance checkout `890b9df69ebd7816e286c1e3ad6052618d41aa79`.
Git HEAD, 69 application source hashes and both test-file hashes were identical
before and after the run. The sorted source-map SHA256 was
`13837db0bd77106e8088aa6b016f8672ba37cdca108ef54a3b02b8841b11b824`.
This includes actual fictional HTTP journeys and controlled native-port
admissions; it does not establish real provider or protected native execution.

A subsequent historical real-worker intake diagnostic failed both scenarios. Spanish
reached the expected confirmation mode but used the safe fallback after
recommendation validation rejected both generated attempts. Portuguese produced
the correct native amount, currency and event date but its `cartão` product hint
did not match the bank's Spanish product label. The run used 13 model attempts
and 100,454 reported tokens; provider cost remained unknown. Application source
changed during execution. Those failures are historical diagnostics, with additional
independent ES/PT product-hint cases preserving conflicting-product rejection.

The next historical frozen local checkpoint passed **185/185** cases in 70.44 seconds at
acceptance checkout `e306036543da9c64b8cfcb964d50110b28c8cf9d`, merging integration
candidate `b6fb52c`. All 76 graph-protected source hashes matched the generated
artifact. Git HEAD, 79 captured source hashes including that artifact, and both
test-file hashes were unchanged before and after execution; actual source bytes
matched integration. The sorted source-map SHA256 was
`20132d1003480469ab54c3c1b754820ecd34b019ad5cc218ce1aebd2d08e91b7`.

Subsequent independent review exposed a false-success boundary outside
those 185 cases: Spanish and Portuguese present-progress claims said a request
was processing despite no authorization, execution or receipt. Four release
assertions were added to reproduce that gap, including after a truthful statement
that chat cannot register the request. The historical 185-case checkpoint was
not substituted for the expanded 189-case suite, which required a corrected,
frozen source candidate.

The historical corrected frozen candidate then passed **189/189** cases in 66.34 seconds at
acceptance checkout `1f0d96b7962427ad1961209d54a3289a7ffb2c8b`, merging integration
candidate `b0fcbba`. All 76 graph-protected hashes matched the saved artifact.
Git HEAD, 79 source hashes and both test-file hashes were unchanged before and
after execution; the checkout stayed clean and its source bytes still matched
integration afterward. The sorted source-map SHA256 was
`63c0d669659b9426499ec2d3a998590ba5be0b40705afd671004b492c549b04b`.
The four new false-progress claims reject; verified past-tense receipt notices
and truthful negative portal limitations remained usable. This was a frozen
local boundary checkpoint for `b0fcbba`; provider/native qualification was
recorded separately and did not upgrade it to the later final candidate.

The historical first complete guarded-source native run passed **1/4** scenarios in
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
unknown. The failed report is retained as private diagnostic evidence, separate
from the final qualification path. Four additional independent cases cover the
truthful PT uncertainty and rejection of added success, human-response and
unsupported contact claims; the expanded suite has 193 cases.

The corrected native admission publisher retries Windows sharing denials within
five seconds while retaining the kernel writer lock and the same fsynced private
temporary file. The owner reproduced a held Docker read handle and tested both
release of that handle and bounded persistent failure. The historical `ce2e350`
source checkpoint passed **193/193** cases in 52.33 seconds at acceptance checkout
`46fdb857be6d073175b97223e95b1706938ff915`, merging `ce2e350`. Git HEAD, both test
hashes, and all 79 captured source hashes remained unchanged; all 76 graph hashes
matched the saved artifact, and the clean checkout still matched integration
afterward. The sorted source-map SHA256 was
`4733510a3804d1f9639625af030f83ab328128edd5bb6efa7b159d0703b01a32`.

The historical `ce2e350` HTTP fixture then passed **4/4** scenarios in 357,288 ms. Both
ES/PT intakes passed explicit false/true consent, exact saved receipt readback,
application restart and native receipt followup, replay with exactly one case,
and logout revocation. Human and emergency review passed the correct language,
policy mode and reason without fallback, and their saved review requests claimed
no human response or intake. Emergency response required one bounded repair.
All 30 HTTP attempts and 39 native model attempts completed as asserted, with
291,111 reported tokens and unknown provider cost. The 69 application and 27
generated-source hashes stayed equal before and after; the external 79-file host
capture, both tests, native manifest and Git HEAD were also unchanged.

That historical `ce2e350` run used installed frame manifest SHA256
`eaf5e124d3fc6cf533f940512da35bf976a993c0861836165d6a7e738bf603eb`
and coordinator-supplied image
`sha256:1ecdffb8856c6d24935f5ff045906e5434a278670ba6616b368231c3be04efbe`.
The installed-image and callback checks remain separately scoped evidence; the
HTTP report observes model calls and host behavior without self-attesting
protected native execution. These `ce2e350` metrics and image identifiers are
historical and are not copied into the final candidate's measurements.

The subsequent `87f9c6f` repair and `f6339ba` graph checkpoint are historical
cleanup-boundary evidence. A durable denial marker for the exact stage token is
published before registry cleanup, so a persistent Windows replacement denial
cannot leave that retained token admitted. Targeted completed/cancelled cleanup
checks preserve sibling records; deferred registry-read probes exercise the
exact native fence declarations without provider execution. This narrow repair
does not replace the final source checkpoint or the four actual HTTP journeys.

The historical 79 source checkpoint passed **193/193** cases: **91 acceptance
and 102 release**, with **0 failed and 0 skipped**, in **78.11 seconds**. The
acceptance checkout was `2f5ccdf2f137508b6df2d6a9c47261105bf5f4e5`, joined to
integration root `79f6e80b35b41c4714131e918027cb95569ba128`. Recorded HEAD,
both test-file hashes and all **80 outer application source hashes** were stable
before and after execution; the acceptance checkout stayed clean and captured
source bytes matched integration.
All **77 graph-protected hashes** matched the saved graph. The sorted source-map
SHA256 is
`425932555e46d367dff9bdfe45ff78e6fe3b832bb29abcf5fb0a1d9fe456d044`.
The historical allowlisted independent checkpoint JSON SHA256 is
`1d352dab65199a2d77c303247a84fac85d158bddd0a445ea2326cdb41ad04b13`.
This source checkpoint uses scripted language inputs and fictional HTTP; it does
not establish provider execution, human adjudication or held-out accuracy.

The historical 79 installed manifest SHA256 is
`4e4861fe21555351cb8fe6e6fc1e261fc331696d07cb64237626c4f21034aeab`,
and its historical image identifier is
`sha256:ade71c6b726b9476bcfba00f2b819cede7e27b88188060acfec10ac01c0775e0`.
For that historical 79 image, independent outer-host and installed-image
captures each contain **80 application files**; all **78 shared files** are
hash-equal. Its graph protects **77 source files**. These capture sets remain
distinct; source/image/callback qualification is separate from the HTTP report's
observation of model calls and host behavior. The HTTP report retains
`native_execution_verified=false`.

The historical 79 HTTP collector completed with **2/4 passing scenarios** and
a failing overall verdict in **381,043 ms**. It observed **25 HTTP attempts**,
**6 completed workflow turns**, **2 safe fallbacks**, and **41 successful model
calls** reporting **315,476 tokens**. All 41 model calls had unknown cost; the
reported provider cost remains `null`. Successful model transport does not mean
that the corresponding generated response or customer journey passed.

| Historical 79 journey | Verdict | HTTP attempts | Model calls | Reported tokens | Completed workflow turns | Safe fallbacks |
| --- | --- | --- | --- | --- | --- | --- |
| ES intake | PASS | 12 | 12 | 89,461 | 2 | 0 |
| PT intake | FAIL | 8 | 14 | 113,670 | 2 | 1 |
| Human review | PASS | 3 | 7 | 50,246 | 1 | 0 |
| Emergency review | FAIL | 2 | 8 | 62,099 | 1 | 1 |
| Total | FAIL: 2/4 passed | 25 | 41 | 315,476 | 6 | 2 |

The 69 harness application hashes and 27 generated-source hashes stayed stable.
The external 80-file host capture, 80 installed files, 78 shared hash-equal
files, 77 protected graph sources, recorded HEAD and installed manifest also
remained stable. The allowlisted historical diagnostic JSON SHA256 is
`4450f4b7fdaf433286aea4437548fb01e2e527b5c85423b0a85e37de72494704`.
Its `native_execution_verified=false` and human-adjudication flag remain false.
These failures are historical diagnostics, not final release acceptance.

Two response-grounding defects were observed: decimal punctuation split a
same-receipt success sentence, and a truthful restatement of a customer's human
review request was treated as contact guidance. The initial emergency instruction
to call a contact channel was correctly rejected. Five new independent
assertions at `0b41f9a`, with trusted reason context at `62ab3f5`, reproduced
three positive-case failures while both unsafe controls passed their rejection
assertions. The required source suite is now **198 cases: 91 acceptance + 107
release**. Those finite grounding fixes and the HTTP `Connection: close`
harness repair preceded the final abc freeze. The final source checkpoint
passed all five added assertions within its **198/198** result. The four final
actual HTTP journeys now pass; historical `ce2e350` and 79 measurements
are not reused as final results.

The latest-main `e967e7e` integration preserves an explicit `GloriaChatService`
for this qualification alongside the default direct MCP path. Fixture ledger
continuity is explicitly enabled only for synthetic fixtures. The durable
ledger generation is pinned across restart, and a generation mismatch remains
fenced. The before/after test and setup maps now include the third file,
`tests/banking_authority_fixtures.py`. Shared production provider/model bindings
remain unchanged.

Final integration root: `abc90682faa5cb496c9cd3476ec7811a7e5c9281`.
Final acceptance checkout: `51c503c2687dbefb77e4be93b92eeda0f4fafeca`.
Final source-suite result: **198 passed, 0 failed, 0 skipped in 58.66 seconds**
(**91 acceptance + 107 release**), with one existing
`StarletteDeprecationWarning`. All **87 outer application source hashes**,
all **84 graph-protected hashes**, all **3 test/setup hashes**, and the recorded
HEADs were stable before and after; the acceptance checkout stayed clean and
captured source bytes matched integration.
Final source-map SHA256: `c4d4047c7e8f9619bbd71074cf549f34dfd8c6305770aa2b2a869e3ffe0cf577`.
Final independent report SHA256: `b33ff0ead1127f1765a9dc9597e1d4cf4bb27b82218af3226f28d8d4846d2717` (**21,765 bytes**).

| Final test/setup path | Stable before/after SHA256 |
| --- | --- |
| `tests/test_gloria_acceptance.py` | `4dc765969b038b0343cfefe74199ba473efe618c9146a14906721e3acaba7346` |
| `tests/test_gloria_release.py` | `2644488d99a4e23d7de51dae2927b567d18ff2d5f8f46d6bb76cfc841ba584f9` |
| `tests/banking_authority_fixtures.py` | `56efb8cc974d2cf0ab4b306a2b2693eab58bdb23bcce218587775c5120288708` |

This final source report uses `scripted_offline_with_actual_fictional_http`
within `independent_local_application_release_boundaries`.
`actual_provider_invoked=false`, `native_execution_verified=false`,
`human_semantic_adjudication=false`, and
`restricted_or_frozen_evaluation_data_read=false` remain explicit. Its source
pass does not establish installed-image or same-turn native callback execution.

The separately supplied final installed-image gates verify **87 installed
application files** independently of the **87 outer application files**;
the graph protects **84 source files**. The final paired captures contain
**85 shared files**, all hash-equal. This shared count was derived from those
captures and is distinct from either 87-file total.
Final installed manifest SHA256:
`f8757e1e059370c93b32258d169d2faecbcde18b2de786e5a5bef91b91bde453`.
Final image identifier:
`sha256:402581eaa5df62914d91acbee60c2cdba63aacdfcca64957637825d3387243c7`.
Final graph SHA256:
`c082b3243a8c118d09be0d9346d576fc5a1d243ba23a75be00cb8afdacdf0d08`.
Final bridge artifact SHA256:
`640362eef0f5e7d1fbcc8ac8117e4515e64fb6b98fe8a920330a0e4721f57a5e`.
These installed-image identifiers and gates are distinct from the HTTP report's
observed calls and host behavior. The final HTTP report retains
`native_execution_verified=false` and `human_adjudicated=false`; the final source
report retains `human_semantic_adjudication=false`. Passing synthetic scenario
assertions does not establish human semantic adjudication.

The final fixture04 HTTP qualification passed **4/4 journeys** in
**334,183 ms** overall. All **30 HTTP checks** and **6 completed workflow turns**
passed. The run recorded **39 successful model calls**. There were
**0 failed model calls, 0 node errors and 0 safe fallbacks**. Portuguese emergency
review used **one bounded generator repair**; the other journeys required none.

| Final journey | Verdict | HTTP checks | Completed turns | Successful model calls | Reported tokens | Summed HTTP latency (ms) | Bounded generator repairs |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ES intake | PASS | 12 | 2 | 12 | 89,365 | 109,773 | 0 |
| PT intake | PASS | 12 | 2 | 12 | 89,347 | 113,988 | 0 |
| Human review (ES) | PASS | 3 | 1 | 7 | 50,271 | 48,425 | 0 |
| Emergency review (PT) | PASS | 3 | 1 | 8 | 62,107 | 56,692 | 1 |
| Total | PASS: 4/4 | 30 | 6 | 39 | 291,090 | 328,878 | 1 |

The latency column sums each journey's recorded HTTP request durations;
**328,878 ms** is their total. The separately reported **334,183 ms** overall
run includes work outside those request durations. Neither value sums model-stage
durations, which can overlap.

Both ES/PT intake paths produced `CONFIRM_ACTION` then verified `ACTION_DONE`
in the declared language. False portal consent was rejected with HTTP 422;
explicit confirmation saved one case. Receipt recovery passed after application
restart, native receipt followup rendered `ACTION_DONE`, and confirmation replay
preserved one saved case. Logout passed, and the revoked cookie could neither
read a receipt nor replay confirmation; those requests returned HTTP 401.
Human review passed `HANDOFF/customer_request` in ES; emergency review passed
`HANDOFF/emergency` in PT. Their saved review requests do not establish a human
response, external contact or bank intake. No final workflow turn used a safe
fallback.

All **75 public harness application hashes** and **27 generated-source hashes**
were equal before and after the HTTP run. The separate external captures held
all **87 outer-host sources**, all **87 installed-image sources**, all **85 shared
hash-equal files**, all **84 graph-protected files**, all **3 test/setup hashes**,
the recorded abc HEAD, image identifier and installed manifest stable. The
third test/setup hash is `tests/banking_authority_fixtures.py`, shown above with
the acceptance and release test hashes.

Final public joined-report SHA256:
`00ff2e6461aa28b4aa33c483c2e7eabe8568c5c0251ae81ef8742523ae065088` (**81,742 bytes**).
All **291,090 tokens** were reported; **0 calls had unknown token counts**.
All **39 calls had unknown provider cost**, and `cost_usd` remains `null`.
Provider cost is not inferred from tokens. `native_execution_verified=false`
and `human_adjudicated=false` remain explicit in this HTTP report; the source
report's human-semantic flag remains false. Installed-manifest and same-turn
callback verification remain separate supervisor evidence for the exact image.
Neither final report establishes held-out ES/PT accuracy or real bank actions.

These independently authored development cases execute the application-owned
`gloria_workflow` orchestration and deterministic motor. They use newly invented
ES/PT messages and fictional records, not the frozen router evaluation files or
organizer data. A scripted language port and an observed, read-only bank port
make classification errors, timeouts, malformed outputs, stale evidence, and
receipt uncertainty reproducible.

Run the independent source suites from the repository root:

```powershell
python -m pytest -q tests/test_gloria_acceptance.py tests/test_gloria_release.py
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

The independent scripted source suites test actual local orchestration and pure
policy against injected ports. They do not measure provider understanding,
accuracy on a held-out benchmark,
native FLUJO execution isolation, a deployed joined customer path, or real bank
actions. Scripted classifications are inputs to boundary tests, not evidence of
learned-component ES/PT quality. Language assertions check the declared output
language and fallback behavior, not full linguistic quality.

The source suites do not modify generic FLUJO main, the shared worker or shared
production provider/model bindings, and do not read restricted records or frozen
evaluation data. The separate HTTP qualification uses an explicitly isolated
native language port and fictional fixtures. Production authorization and the
protected banking MCP remain separate from the language workflow.

## Historical execution evidence

Historical acceptance-only checkpoint: **91 passed, 0 failed, 0 skipped in 2.45 seconds**,
September 30, 2026 at 23:22 Bogotá (October 1 at 04:22 UTC). The tests were
executed against the actual supervisor integration package with the committed
acceptance file at `a8f5bcd9b1849605d8ed12ce9c41f4edd1904fd9`.

The previous 90/91 run exposed a topic-switch guard: after a dispute asks for
currency, “Ahora quiero saber mi saldo en USD” with model intent `OOD` wrongly
completed the old dispute. The runtime at that historical checkpoint instead
started a new request and returned `OUT_OF_SCOPE` without transaction search.
The same assertion passed, as did all four freshness boundaries and
cached-success receipt revalidation.

The integration checkout's Git HEAD was
`6bee817dc74d414153cd714c9f6b4a7f2ca3e06e`, unchanged before and after execution.
Protected application source was committed; the source-only generated graph
was still untracked. A private historical capture recorded SHA256 maps of 36
application modules and inputs: canonical prompts, retrieved
policies, contracts, configuration, graph artifacts, dependency requirements,
and relevant frontend/MCP action boundaries, both before and after execution.
Those maps were identical throughout the run. Their sorted JSON-map SHA256 is
`85728c34434da00b422dda4d237ba3eaab62a868e6f542d82eb3aca1e03996df`.

Earlier 83-case and 90/91 checkpoints are historical development evidence.
The 91/91 run is also historical; none replaces the final 198-case source run
or the final four native-port HTTP journeys.

The suite exposed status-field incompatibility, missing selection snapshots,
adapter input mismatch, absent bounded repairs and language notices, receipt
proof handling, ordinary person/spouse guards, complaint selection, and a
candidate-hash/snapshot-ID mismatch. The owners corrected those source issues;
the contract assertions were preserved. The observed test port was adjusted
to accept the real adapter's optional `correction` argument.

The initial Windows test environment lacked `tzdata`; installing it in the
isolated acceptance environment resolved that historical environment failure.
That run used Python 3.13, pytest 9.1.1, PyYAML 6.0.3, Jinja2 3.1.6, and tzdata
2026.4. The standalone scripted acceptance suite invoked no provider, MCP
transport, S3 or bank write. The separate final joined qualification above
records actual native-port calls against a synthetic bank ledger. A later
source change or deployment needs its own joined run; these passing results
do not establish a deployed customer path.

At an earlier development checkpoint, the default repository bank port lacked
complete historical complaint and dispute-risk adapters. Its safe
`unsupported_history` error and `HANDOFF/missing_evidence` behavior were tested.
That historical limitation is not the current release coverage: the final
source and joined probes exercise `OwnedBankReads` and the synthetic banking
service with explicit fictional observations and the durable fixture ledger.
Their coverage remains scoped to the asserted local synthetic paths.

The supervisor's configured-model qualifier is separate evidence. Its four
synthetic mode/language cases are a development smoke check; they neither
establish held-out ES/PT accuracy nor verify action authorization or a saved
FLUJO graph. Extraction must be assessed from the captured intent/slots and
the expected source facts. Unknown provider cost must remain unknown. A
qualifier report also needs a source capture made before execution and a
matching capture afterward to identify the exact code measured.
