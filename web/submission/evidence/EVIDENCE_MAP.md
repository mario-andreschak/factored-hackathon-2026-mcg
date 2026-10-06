# Savia evidence map

Start with the [core R0–R18 transaction dispute engine](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/DISPUTE_ENGINE.md):
nineteen ordered policy rule identifiers and a complete authenticated, consented,
receipt-verified, recoverable simulated banking workflow. The voice avatar and
specialist swarm are enhancements over this implemented foundation.

Reviewed 5 October 2026. Start with [the product review route](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/START_HERE.md)
and [submission portal](https://savia-rc-2026.fly.dev/submission/). This map connects
technical decisions to implementation, exact results and executable checks.
Source checks use generated fixtures and local files; they need no paid model,
live banking action or private organizer dataset.

## Technical judgment and useful customer behavior

The successor's [immediate card protection](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/CARD_BLOCK_VERIFICATION.md)
uses owned selection, explicit confirmation and a durable verified receipt.
Its local checks include 100 concurrent confirmations producing one simulated
block, cancellation, expiration, receipt tampering and new-session recovery.
Public runtime acceptance retains a separate deployment receipt.

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Live canonical Spanish/Portuguese voice](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/native-canonical-live/README.md) | **2/2 registered guidance captions match the host script; 2/2 exact product-UI playback acknowledgments**. Actual 24 kHz PCM: 309,600 samples / 12.90 s ES; 397,200 / 16.55 s PT. Existing owned-card receipts survive independent status rereads; two tampered narration requests return 409. These are guidance and separate saved-status observations. | [Exact source, image, scripts, audio and receipt](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/native-canonical-live/receipt.json), [buffered result transport](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/frontend/server/conversation.py), [device-clock playback](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/frontend/src/avatar/useSaviaVoice.ts) |
| [Recorded two-reviewer inquiry](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/team-story-summary.json) | **2/2 actual model workers completed**; 4.278 s from create-request start to the first completed UI poll; seven work events, then an eighth explicit helpful-closure event. Saved date/amount and receipt advice survives new chat/reload. This is an actual direct-provider customer example over fictional bank data. | [Inquiry service](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/service.py), [inquiry API](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/api.py), [assistant tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/tests) |
| [Saved recommendations spoken](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/saved-recommendations-native/receipt.json) | **1 native stream and 1 exact full-playback HTTP 200 acknowledgment**; 196,800 mono PCM16 samples at 24 kHz = 8.2 s. Reload retains the original reply and suggestions, with no second stream. Source `7089ca7`, image `39457d88…`; recorder exit 0. | [Voice state machine](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/frontend/src/avatar/useSaviaVoice.ts), [conversation authority](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/frontend/server/conversation.py), [capture description and audio](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/saved-recommendations-native/README.md) |
| [Release source-byte verification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/runtime-listen-freeze.json) | **142/142 packaged source files verified**, actual served UI verified, three retained inquiries and six completed workers in that dated rc.2 deployment. | [Public gateway](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/deploy/rc/public-gateway.mjs), [startup](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/deploy/rc/public_start.py), [release report](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/RELEASE_CANDIDATE_RC2.md) |
| [Demand and ownership review](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/DATA_REVIEW_2026-09-26.md) | **12,297/67,095 complaints** concern an unrecognized charge. All **44,570/44,570 populated complaint-product links** cross customer ownership; historical complaint links therefore cannot identify the customer's disputed charge. This directly informs fresh owned-transaction grounding. | [Banking repository](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/banking_mcp/repository.py), [selected reads](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/bank_read.py), [direct-host contract](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/frontend/DIRECT_MCP.md) |

The dated native recommendation is useful condensed speech; complete suggestions
remain visible. Its receipt preserves the omitted folio/caveat wording and human
audio-review status. Informational helpful closure is a customer acknowledgment,
and a simulated intake receipt records intake; neither is a bank refund or
dispute resolution.

The [presentation and host-outcome qualification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/verified-outcomes/README.md)
adds canonical host-script narration for registered results and read-only
verified host outcome snapshots. Its 183 tests and 195 subtests exercise the
presentation and measurement boundaries. The original native recordings retain
their dated meaning. The compatible native successor has the separately pinned
live acceptance above.

## AI engineering and expandable FLUJO orchestration

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [New bilingual provider benchmark](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/luna-100/README.md), [independent audit](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/luna-100/run-100/audit.json) | **100/100 completed, 100/100 exact-correct, 100/100 bounded-safe**; 100 overlapping Codex app-server turns, 50 ES/50 PT, five predeclared fixture scenarios. Submit-to-completion p50/p95 **37.400/50.693 s**; zero tools/reroutes. Deterministic baseline also scores 100/100. | [Harness](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/scripts/benchmark_luna_subscription.py), [offline verifier](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/scripts/verify_luna_benchmark.py), published workload and outputs. Actual `gpt-6-luna` subscription completions; this direct-provider run is separate from Savia UI, FLUJO, Banking MCP and collaborative agents. |
| [FLUJO / inference capacity](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md), [aggregate receipt](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/infrastructure-capacity.json) | Real neutral-reference repeat: **300/300 HTTP successes and correct references** through FLUJO's flow-as-model interface; p50/p95 273.40/441.60 s including queueing. Across both original runs, **1,289/1,289 HTTP 200s**. Real filesystem tools were observed separately in **64/65** inspected first-run conversations. | October 4 originals, per-request records and source hashes are identified in the public aggregate. October 5 count verification made no additional provider call. Concurrent submissions are distinct from simultaneous GPU generations. |
| [Sandbox collaboration](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md#real-sandbox-and-collaboration-runs) | **18 separate Fly leaf sandboxes live together**, 17 completed leaf team runs and six matching sorted-output hashes. A larger recovered run enrolled 96 child Workers over time and used independent result checks. | Recovered orchestration source `f9d372a…`; scope includes actual tools, collaboration, output checking and cleanup. The report retains provisioning failures and timed-result distinctions. |
| [Generic FLUJO MCP execution](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/runtime-mcp.json) | Connected MCP, **1 actual tool call and 1 completed manual planned execution** on empty fictional state. Installed half-hour schedule is disabled. Zero paid model calls or bank operations in this smoke. | [Generic flow](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/assistant/flujo-flow.json), [scoped MCP server](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/mcp.py), [assistant contract](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/assistant/README.md) |
| [Recovered-fleet connector](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/assistant/FLEET_CONNECTOR.md) | Application-owned goal dispatch, immutable bindings, original-run recovery, owner-scoped idempotency and independently reviewed findings are implemented. The ten-by-ten team design reuses existing fleet mechanisms. | [Fleet consumer](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/fleet.py), [fleet tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/savia_assistant/tests), [architecture](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/architecture/system-landscape.md), [generic/domain boundary](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/FLUJO_PRODUCT_BOUNDARY.md) |
| [Bounded language and policy](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/DISPUTE_IMPLEMENTATION.md) | Executable interpretation prompts and ordered R0–R18 decisions connect language/emotion detection to owned facts, clarification, consent and independently verified receipts. Model prose cannot mint bank authority. | [Workflow runtime](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/runtime.py), [policy](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/policy.py), [response guards](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/response.py), [action host](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/action_host.py), [workflow checks](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/scripts/test_dispute.py) |

The prototype's two-reviewer film is a demonstrated customer workload. The
300-request benchmark and sandbox runs demonstrate other infrastructure
workloads. [Measured results and original receipts](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/MEASURED_RESULTS.md)
retain the customer and infrastructure denominators. The
[dated ElevenLabs comparison](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/ELEVENLABS_COMPARISON.md) gives the product positioning.

## Data engineering

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Full pipeline manifest](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/pipeline/manifest.json), [quality report](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/pipeline/quality_report.md) | **5,899,720 rows**, six table families, **4,390 source objects**, 991.2 s for the September 27/28 full run. Every table reconciles raw = silver + quarantine + removed duplicates. | [Bronze](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/bronze.py), [silver](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/silver.py), [gold](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/gold.py), [contracts](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/contracts.yaml), [end-to-end fixture tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_pipeline.py) |
| Owned serving snapshot | **4,425,008/4,425,008 ownership-valid transactions** in 128 stable buckets. Published-manifest lookup sample: **50 customers**, p50 38.6 ms, p95 51.2 ms, max 65.4 ms on local disk. | [Scoped lookup](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/lookup.py), [banking service](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/banking_mcp/service.py); receipt timings describe this exact run, not every machine or later rebuild. |
| Atomic publication and recovery | Isolated immutable builds; contract/gold validation and required snapshot/external reports finish before `CURRENT` is replaced. Stage, report and pointer-swap failures preserve the previous serving snapshot. Deterministic PK deduplication, late arrivals, schema drift and row lineage are exercised on labeled fixtures. | [249 tests and 106 subtests with exact source](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/pipeline-publication/README.md), [writer lock](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/writer.py), [common snapshot handling](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/common.py), [synthetic fixture](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/fixture.py), [dataset health tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dataset_health.py), [row-hash tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_row_hash.py) |
| Consumer-specific gold | **3,927 contact-demand aggregates**; 171,321 classifier rows with customer/time splits; scenario seed candidates; serving transactions. | [Pipeline account](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/README.md), [gold outputs](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/gold.py), [source verification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/pipeline/verify.py) |

Organizer rows and credentials remain private; committed receipts contain
aggregates and provenance. Synthetic fixtures reproduce injected duplicates,
late arrivals and corrections even where the organizer tables contain none.

## ML and evaluation design

| Evidence | Exact result and scope | Implementation / verification |
| --- | --- | --- |
| [Transcript diagnosis](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/ml/README.md), [pipeline manifest](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/pipeline/manifest.json) | Only **42 distinct normalized texts / 171,321 transcripts**. **2,946/2,946 test-split texts** appear in train. Text-label predictability equals the 34.9% majority baseline. The team therefore avoids presenting leakage-driven scores as model quality. | [Text inspection](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/ml/inspect_texts.py), [fraud inspection](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/ml/inspect_fraud.py), pipeline customer/time split |
| [Frozen diagnostic](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/demo/intent_router_evaluation.json), [readable results](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/demo/intent_router_evaluation.md) | **120 cases**, 60 ES/60 PT, 30 per class, 307 training phrases. Learned raw route **94/120 = 78.3%** accuracy vs keyword **70/120 = 58.3%**. Macro-F1 0.782 vs 0.569; human-required misroutes **3/30 vs 13/30**. | [Router](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/ml/router.py), [frozen evaluator](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/demo/evaluate_router.py), [provenance and hashes](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/ml/router_holdout_provenance.md), [identity tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_demo_evaluation.py) |
| Abstention tradeoff | Fixed threshold 0.65 reduces human-required misroutes to **1/30**, with **65/120 = 54.2%** total label accuracy and 52 unnecessary human routes. C=8/threshold selected from train-only CV; zero exact or ≥0.8 near-duplicate training overlaps in the frozen diagnostic. | [Train/report tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_router.py), frozen confusion matrices and bootstrap intervals |

Training and held-out labels are separately AI-authored diagnostic material;
human adjudication remains a distinct review requirement. Routing quality is
a component result. It does not estimate production traffic or authorize a bank
action. This is a measured comparison with an explicit safety/coverage tradeoff.

## Analytics and strong development

[Measured operating decisions](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/review/OPERATING_DECISIONS.md) independently
reconstruct Luna latency, cache/token overhead and routing safety versus extra
handoffs. The charts and hashed inputs connect each denominator to a product
decision; the [script](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/scripts/analyze_operating_evidence.py) makes no provider calls.

| Evidence | Engineering contribution | Implementation / verification |
| --- | --- | --- |
| [New public evidence replay](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/review/PUBLIC_EVIDENCE.md), [hashed receipt](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/review/replay-receipt.json) | **67/67 offline checks**, **7/7 pipeline invariants** and **4/4 analytics invariants** pass. Fixture execution verifies reconciliation, idempotent logical hashes, late corrections, ownership exclusion, retained previous snapshots, read-only analytics and privacy. Adds paired uncertainty to the unchanged 120-case router diagnostic. | [Replay script](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/scripts/review_evidence.py), [review dependencies](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/requirements-review.txt), public fixture/output JSON. Zero provider calls; inspected source subset is hashed, with explicit working-tree/base identity. |
| [Offline agent analytics](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/analytics/README.md) | Read-only metadata: workflow intent, rule IDs, stages, latency and feedback, plus separately verified current host intake/handoff snapshots and lifecycle coverage. Exact admission joins and HMAC identities keep host evidence distinct from planned outcomes without copying private facts. Counts describe current slots; turn/query attribution and lifetime resolution remain unknown. | [Extraction](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/analytics/extract.py), [host observations](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/analytics/host.py), [reports](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/analytics/report.py), [privacy/read-only tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_agent_analytics.py), [joined-host tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_host_outcome_analytics.py), [source qualification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/verified-outcomes/README.md) |
| [Source qualification](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/qualification/dispute-naming-source-2026-10-01.json) | Frozen combined source at `ea8f621…`: **1,725 passing tests + 428 passing subtests**, including 24 retained-state naming compatibility cases; 85 protected source and 28 preparation hashes checked. This is historical source qualification for its named snapshot. | [Implementation account](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/DISPUTE_IMPLEMENTATION.md), [state migrations](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/state.py), naming/recovery tests |
| [Windows/Linux workflow](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/.github/workflows/tests.yml), [local CI policy](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/LOCAL_CI.md) | Eleven independently scoped jobs: five Windows and six Linux. Separate service dependencies, immutable source pins, resource-bounded local execution, UI build, compiler/provenance checks and platform receipts. The workflow defines coverage; actual passes must come from the same-head receipts. | [Development process](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/DEVELOPMENT_PROCESS.md), [PR template](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/.github/pull_request_template.md) |
| Publication provenance | Actual application and browser bytes, image digests, audio sample counts, playback acknowledgments and request counts are preserved with recorded evidence. Prior observations retain their revisions rather than inheriting later fixes. | [rc.2 freeze](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/runtime-listen-freeze.json), [voice supplement](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/measurements/saved-recommendations-native/receipt.json), [release materials](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/RELEASE_CANDIDATE.md) |

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

---

[Public source document](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/EVIDENCE_MAP.md)
