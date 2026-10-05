# Savia evidence map

Start with the [core R0–R18 transaction dispute engine](DISPUTE_ENGINE.md):
nineteen ordered policy rule identifiers and a complete authenticated, consented,
receipt-verified, recoverable simulated banking workflow. The voice avatar and
specialist swarm are enhancements over this implemented foundation.

Reviewed 5 October 2026. Start with [the product review route](START_HERE.md)
and [submission portal](https://savia-rc-2026.fly.dev/submission/). This map connects
technical decisions to implementation, exact results and executable checks.
Source checks use generated fixtures and local files; they need no paid model,
live banking action or private organizer dataset.

## Technical judgment and useful customer behavior

The successor's [immediate card protection](measurements/CARD_BLOCK_VERIFICATION.md)
uses owned selection, explicit confirmation and a durable verified receipt.
Its local checks include 100 concurrent confirmations producing one simulated
block, cancellation, expiration, receipt tampering and new-session recovery.
Public runtime acceptance retains a separate deployment receipt.

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Recorded two-reviewer inquiry](measurements/team-story-summary.json) | **2/2 actual model workers completed**; 4.278 s from create-request start to the first completed UI poll; seven work events, then an eighth explicit helpful-closure event. Saved date/amount and receipt advice survives new chat/reload. This is an actual direct-provider customer example over fictional bank data. | [Inquiry service](../../savia_assistant/service.py), [inquiry API](../../savia_assistant/api.py), [assistant tests](../../savia_assistant/tests/) |
| [Saved recommendations spoken](measurements/saved-recommendations-native/receipt.json) | **1 native stream and 1 exact full-playback HTTP 200 acknowledgment**; 196,800 mono PCM16 samples at 24 kHz = 8.2 s. Reload retains the original reply and suggestions, with no second stream. Source `7089ca7`, image `39457d88…`; recorder exit 0. | [Voice state machine](../../frontend/src/avatar/useSaviaVoice.ts), [conversation authority](../../frontend/server/conversation.py), [capture description and audio](measurements/saved-recommendations-native/README.md) |
| [Release source-byte verification](runtime-listen-freeze.json) | **142/142 packaged source files verified**, actual served UI verified, three retained inquiries and six completed workers in that dated rc.2 deployment. | [Public gateway](../../deploy/rc/public-gateway.mjs), [startup](../../deploy/rc/public_start.py), [release report](RELEASE_CANDIDATE_RC2.md) |
| [Demand and ownership review](../DATA_REVIEW_2026-09-26.md) | **12,297/67,095 complaints** concern an unrecognized charge. All **44,570/44,570 populated complaint-product links** cross customer ownership; historical complaint links therefore cannot identify the customer's disputed charge. This directly informs fresh owned-transaction grounding. | [Banking repository](../../banking_mcp/repository.py), [selected reads](../../dispute_workflow/bank_read.py), [direct-host contract](../../frontend/DIRECT_MCP.md) |

The dated native recommendation is useful condensed speech; complete suggestions
remain visible. Its receipt preserves the omitted folio/caveat wording and human
audio-review status. Informational helpful closure is a customer acknowledgment,
and a simulated intake receipt records intake; neither is a bank refund or
dispute resolution.

The [current source qualification](measurements/verified-outcomes/README.md)
adds canonical host-script narration for registered results and read-only
verified host outcome snapshots. Its 183 tests and 195 subtests exercise the
presentation and measurement boundaries. The original native recordings retain
their dated meaning; deployment acceptance is separately pinned.

## AI engineering and expandable FLUJO orchestration

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [New bilingual provider benchmark](measurements/luna-100/README.md), [independent audit](measurements/luna-100/run-100/audit.json) | **100/100 completed, 100/100 exact-correct, 100/100 bounded-safe**; 100 overlapping Codex app-server turns, 50 ES/50 PT, five predeclared fixture scenarios. Submit-to-completion p50/p95 **37.400/50.693 s**; zero tools/reroutes. Deterministic baseline also scores 100/100. | [Harness](../../scripts/benchmark_luna_subscription.py), [offline verifier](../../scripts/verify_luna_benchmark.py), published workload and outputs. Actual `gpt-6-luna` subscription completions; this direct-provider run is separate from Savia UI, FLUJO, Banking MCP and collaborative agents. |
| [FLUJO / inference capacity](measurements/INFRASTRUCTURE_CAPACITY.md), [aggregate receipt](measurements/infrastructure-capacity.json) | Real neutral-reference repeat: **300/300 HTTP successes and correct references** through FLUJO's flow-as-model interface; p50/p95 273.40/441.60 s including queueing. Across both original runs, **1,289/1,289 HTTP 200s**. Real filesystem tools were observed separately in **64/65** inspected first-run conversations. | October 4 originals, per-request records and source hashes are identified in the public aggregate. October 5 count verification made no additional provider call. Concurrent submissions are distinct from simultaneous GPU generations. |
| [Sandbox collaboration](measurements/INFRASTRUCTURE_CAPACITY.md#real-sandbox-and-collaboration-runs) | **18 separate Fly leaf sandboxes live together**, 17 completed leaf team runs and six matching sorted-output hashes. A larger recovered run enrolled 96 child Workers over time and used independent result checks. | Recovered orchestration source `f9d372a…`; scope includes actual tools, collaboration, output checking and cleanup. The report retains provisioning failures and timed-result distinctions. |
| [Generic FLUJO MCP execution](runtime-mcp.json) | Connected MCP, **1 actual tool call and 1 completed manual planned execution** on empty fictional state. Installed half-hour schedule is disabled. Zero paid model calls or bank operations in this smoke. | [Generic flow](assistant/flujo-flow.json), [scoped MCP server](../../savia_assistant/mcp.py), [assistant contract](assistant/README.md) |
| [Recovered-fleet connector](assistant/FLEET_CONNECTOR.md) | Application-owned goal dispatch, immutable bindings, original-run recovery, owner-scoped idempotency and independently reviewed findings are implemented. The ten-by-ten team design reuses existing fleet mechanisms. | [Fleet consumer](../../savia_assistant/fleet.py), [fleet tests](../../savia_assistant/tests/), [architecture](../architecture/system-landscape.md), [generic/domain boundary](../FLUJO_PRODUCT_BOUNDARY.md) |
| [Bounded language and policy](../DISPUTE_IMPLEMENTATION.md) | Executable interpretation prompts and ordered R0–R18 decisions connect language/emotion detection to owned facts, clarification, consent and independently verified receipts. Model prose cannot mint bank authority. | [Workflow runtime](../../dispute_workflow/runtime.py), [policy](../../dispute_workflow/policy.py), [response guards](../../dispute_workflow/response.py), [action host](../../dispute_workflow/action_host.py), [workflow checks](../../scripts/test_dispute.py) |

The prototype's two-reviewer film is a demonstrated customer workload. The
300-request benchmark and sandbox runs demonstrate other infrastructure
workloads. The [October 5 integrated fleet receipt](measurements/fleet-customer-attempt/receipt.json)
records checked bank facts, complete native speech and original-root correlation,
but no accepted fleet result after its provider's HTTP 404. Keep the successful
infrastructure results and that incomplete customer integration at their actual
scopes. The [dated ElevenLabs comparison](ELEVENLABS_COMPARISON.md) is the
separate product-alternative analysis.

## Data engineering

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Full pipeline manifest](../pipeline/manifest.json), [quality report](../pipeline/quality_report.md) | **5,899,720 rows**, six table families, **4,390 source objects**, 991.2 s for the September 27/28 full run. Every table reconciles raw = silver + quarantine + removed duplicates. | [Bronze](../../pipeline/bronze.py), [silver](../../pipeline/silver.py), [gold](../../pipeline/gold.py), [contracts](../../pipeline/contracts.yaml), [end-to-end fixture tests](../../tests/test_pipeline.py) |
| Owned serving snapshot | **4,425,008/4,425,008 ownership-valid transactions** in 128 stable buckets. Published-manifest lookup sample: **50 customers**, p50 38.6 ms, p95 51.2 ms, max 65.4 ms on local disk. | [Scoped lookup](../../pipeline/lookup.py), [banking service](../../banking_mcp/service.py); receipt timings describe this exact run, not every machine or later rebuild. |
| Atomic publication and recovery | Isolated immutable builds; `CURRENT` is replaced only after successful contract/gold completion. A failed build leaves the previous snapshot serving. Deterministic PK deduplication, late-arrival/upsert behavior, schema drift and row lineage are exercised on labeled fixtures. | [Writer lock](../../pipeline/writer.py), [common snapshot handling](../../pipeline/common.py), [synthetic fixture](../../pipeline/fixture.py), [dataset health tests](../../tests/test_dataset_health.py), [row-hash tests](../../tests/test_row_hash.py) |
| Consumer-specific gold | **3,927 contact-demand aggregates**; 171,321 classifier rows with customer/time splits; scenario seed candidates; serving transactions. | [Pipeline account](../../pipeline/README.md), [gold outputs](../../pipeline/gold.py), [source verification](../../pipeline/verify.py) |

Organizer rows and credentials remain private; committed receipts contain
aggregates and provenance. Synthetic fixtures reproduce injected duplicates,
late arrivals and corrections even where the organizer tables contain none.

## ML and evaluation design

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Transcript diagnosis](../../ml/README.md), [pipeline manifest](../pipeline/manifest.json) | Only **42 distinct normalized texts / 171,321 transcripts**. **2,946/2,946 test-split texts** appear in train. Text-label predictability equals the 34.9% majority baseline. The team therefore avoids presenting leakage-driven scores as model quality. | [Text inspection](../../ml/inspect_texts.py), [fraud inspection](../../ml/inspect_fraud.py), pipeline customer/time split |
| [Frozen diagnostic](../demo/intent_router_evaluation.json), [readable results](../demo/intent_router_evaluation.md) | **120 cases**, 60 ES/60 PT, 30 per class, 307 training phrases. Learned raw route **94/120 = 78.3%** accuracy vs keyword **70/120 = 58.3%**. Macro-F1 0.782 vs 0.569; human-required misroutes **3/30 vs 13/30**. | [Router](../../ml/router.py), [frozen evaluator](../../demo/evaluate_router.py), [provenance and hashes](../ml/router_holdout_provenance.md), [identity tests](../../tests/test_demo_evaluation.py) |
| Abstention tradeoff | Fixed threshold 0.65 reduces human-required misroutes to **1/30**, with **65/120 = 54.2%** total label accuracy and 52 unnecessary human routes. C=8/threshold selected from train-only CV; zero exact or ≥0.8 near-duplicate training overlaps in the frozen diagnostic. | [Train/report tests](../../tests/test_router.py), frozen confusion matrices and bootstrap intervals |

Training and held-out labels are separately AI-authored diagnostic material;
human adjudication remains a distinct review requirement. Routing quality is
a component result. It does not estimate production traffic or authorize a bank
action. This is a measured comparison with an explicit safety/coverage tradeoff.

## Analytics and strong development

[Measured operating decisions](../review/OPERATING_DECISIONS.md) independently
reconstruct Luna latency, cache/token overhead and routing safety versus extra
handoffs. The charts and hashed inputs connect each denominator to a product
decision; the [script](../../scripts/analyze_operating_evidence.py) makes no provider calls.

| Evidence | Engineering contribution | Implementation / verification |
| --- | --- | --- |
| [New public evidence replay](../review/PUBLIC_EVIDENCE.md), [hashed receipt](../review/replay-receipt.json) | **67/67 offline checks**, **7/7 pipeline invariants** and **4/4 analytics invariants** pass. Fixture execution verifies reconciliation, idempotent logical hashes, late corrections, ownership exclusion, retained previous snapshots, read-only analytics and privacy. Adds paired uncertainty to the unchanged 120-case router diagnostic. | [Replay script](../../scripts/review_evidence.py), [review dependencies](../../requirements-review.txt), public fixture/output JSON. Zero provider calls; inspected source subset is hashed, with explicit working-tree/base identity. |
| [Offline agent analytics](../../analytics/README.md) | Read-only metadata: workflow intent, rule IDs, stages, latency and feedback, plus separately verified current host intake/handoff snapshots and lifecycle coverage. Exact admission joins and HMAC identities keep host evidence distinct from planned outcomes without copying private facts. Counts describe current slots; turn/query attribution and lifetime resolution remain unknown. | [Extraction](../../analytics/extract.py), [host observations](../../analytics/host.py), [reports](../../analytics/report.py), [privacy/read-only tests](../../tests/test_agent_analytics.py), [joined-host tests](../../tests/test_host_outcome_analytics.py), [source qualification](measurements/verified-outcomes/README.md) |
| [Source qualification](../qualification/dispute-naming-source-2026-10-01.json) | Frozen combined source at `ea8f621…`: **1,725 passing tests + 428 passing subtests**, including 24 retained-state naming compatibility cases; 85 protected source and 28 preparation hashes checked. This is historical source qualification for its named snapshot. | [Implementation account](../DISPUTE_IMPLEMENTATION.md), [state migrations](../../dispute_workflow/state.py), naming/recovery tests |
| [Windows/Linux workflow](../../.github/workflows/tests.yml), [local CI policy](../LOCAL_CI.md) | Eleven independently scoped jobs: five Windows and six Linux. Separate service dependencies, immutable source pins, resource-bounded local execution, UI build, compiler/provenance checks and platform receipts. The workflow defines coverage; actual passes must come from the same-head receipts. | [Development process](DEVELOPMENT_PROCESS.md), [PR template](../../.github/pull_request_template.md) |
| Publication provenance | Actual application and browser bytes, image digests, audio sample counts, playback acknowledgments and request counts are preserved with recorded evidence. Prior observations retain their revisions rather than inheriting later fixes. | [rc.2 freeze](runtime-listen-freeze.json), [voice supplement](measurements/saved-recommendations-native/receipt.json), [release materials](RELEASE_CANDIDATE.md) |

## Reproduce without a provider

Run from the repository root. Create isolated environments for the independent
service dependency sets, as the workflow does. POSIX uses `bin/python` in place
of Windows `Scripts/python.exe`. The commands below operate on generated fixtures
or committed text and write scratch reports; they do not read `S3credentials.env`.

**One-command public replay (recommended first check):**

```powershell
python -m venv .tmp/evidence-review
& .\.tmp\evidence-review\Scripts\python.exe -m pip install -r requirements-review.txt
& .\.tmp\evidence-review\Scripts\python.exe scripts/review_evidence.py --out .tmp/evidence-review-output
```

Compare logical hashes, decisions and denominators with the published receipt;
machine paths and wall-clock times may differ. The Luna benchmark's published
records can also be audited offline through its verifier; running the benchmark
harness itself makes real subscription requests and is unnecessary for this review.

**Pipeline and frozen-router checks (Windows PowerShell):**

```powershell
python -m venv .tmp/evidence-data
& .\.tmp\evidence-data\Scripts\python.exe -m pip install -r requirements-pipeline.txt -r requirements-s3.txt -r requirements-ml.txt
& .\.tmp\evidence-data\Scripts\python.exe -m pytest -q tests/test_pipeline.py tests/test_dataset_health.py tests/test_row_hash.py tests/test_spill_location.py tests/test_demo_evaluation.py tests/test_router.py
& .\.tmp\evidence-data\Scripts\python.exe -m demo.evaluate_router --report-dir .tmp/evidence-router
```

The evaluator verifies the frozen holdout hash before fitting the fixed model;
its report remains separate from the committed result. Use the library versions
recorded in the original JSON when reproducing exact metric bytes. Do not change
the held-out examples or tune model parameters from their observed outcomes.

**Customer state, policy, analytics and ownership checks:**

```powershell
python -m venv .tmp/evidence-app
& .\.tmp\evidence-app\Scripts\python.exe -m pip install -r requirements-dispute.txt pytest pytest-subtests
& .\.tmp\evidence-app\Scripts\python.exe -m pip check
& .\.tmp\evidence-app\Scripts\python.exe -m pytest -q --import-mode=importlib savia_assistant/tests
& .\.tmp\evidence-app\Scripts\python.exe scripts/test_dispute.py
& .\.tmp\evidence-app\Scripts\python.exe -m pytest -q tests/test_agent_analytics.py tests/test_report_customer_outcomes.py
```

**Frontend validation** uses the pinned Node 22 toolchain from the workflow:

```powershell
Push-Location frontend
npm ci
npm test
npm run build
Pop-Location
```

These suites assert actual ownership, consent, durable replay, recovery,
publication and output contracts. Counts belong to the tested checkout and
selected suite. They are source checks; live provider playback and deployed
customer results have their own receipts above. The complete CI route also
includes the separately pinned customer-flow compiler, gateway browser checks
and independent MCP service environment.
