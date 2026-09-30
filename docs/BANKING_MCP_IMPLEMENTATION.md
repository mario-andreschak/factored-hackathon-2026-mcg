# Banking MCP implementation

Updated September 29, 2026.

## What runs now

Carlos's pipeline PRs #1/#2 provided the data pipeline and lookup library.
Banking PR #5 added the MCP server. [PR #6](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/6)
adds explicit operator testing, snapshot lifecycle checks, demo flows, evaluation
and concurrency fixes.

The MCP runs as a **Linux Python stdio child inside the existing FLUJO worker**.
There is no banking sidecar or remote MCP URL. Data, source credentials and private
configs are read-only mounts; replay/revocation state is durable and writable.

| Registration | Purpose |
| --- | --- |
| Banking MCP Demo | Marked generated fixtures for graphical development. |
| Banking MCP Operator | Explicit private allowlist of approved test customers; usable through ordinary chat and Slack. |
| Banking MCP | Authenticated customer reads; verified per-call principal required. |

Read-only tools are `banking_status`, `list_my_transactions` and
`get_my_transaction`. Inspect can optionally verify the pinned S3 object.
There are no bank mutations or dispute submissions.

## Serving data

The real S3-derived snapshot has 150,000 customers, 400,000 products and
**4,425,008 ownership-valid transactions**. Requests query customer-oriented gold
Parquet rather than scanning all date partitions.

The current gold-only rebuild adds an explicit file inventory and preserves
legacy source lineage. It does **not** newly validate the bronze objects consumed
by the previous ingestion. Selected-object S3 verification is narrower than a
claim that all data is current across newer partitions.

Missing snapshot buckets/files fail closed. Customer/product ownership is checked
independently; fraud labels are excluded. Handles bind selections to customer,
session, conversation and snapshot. DuckDB connections close at shutdown.

## FLUJO integration

- [PR #528](https://github.com/mario-andreschak/FLUJO/pull/528): optional generic
  execution seams and reference/preset fixes.
- [PR #530](https://github.com/mario-andreschak/FLUJO/pull/530): separately selected
  hackathon banking adapter.
- [Slack PR #1](https://github.com/flujo-app/flujo-slack-bot/pull/1): bounded scheduler
  with durable claims and ordering within each conversation.

Customer requests use ordinary `/v1/chat/completions`. The trusted adapter verifies
ingress before history reads, pins the approved graph, binds immutable ownership,
limits references/tools/control routes, and keeps authority in runtime memory.
After final arguments/presets, it signs a fresh MCP assertion. MCP verifies issuer,
audience, session, tool, arguments, expiry and one-use replay independently.

Fresh ingress assertions remain valid for at most 120 seconds. Accepted work has
a separate opaque server-owned lease: queue at most 300 seconds, active execution
at most 110 seconds including validation/setup, total at most 410 seconds, always
capped by the verified session. Wake and execution checks enforce current policy,
ownership, revocation and cancellation. Controls and continuations require fresh
assertions; a finished job cannot sign again. The lease stays in memory and cannot
be supplied through metadata, prompts or tool arguments.

Organizers use one permanent Banking Operator graphical flow and existing Sol.
They select an approved customer explicitly. Hidden `@current.conversation.id`
correlates handles; it is not customer authentication. A separate permanent
`Banking_Customer` graph uses existing Sol and private caller binding.
No temporary per-customer flow or new frontend is required for operator testing.

Ordinary-route ownership and lifecycle acceptance passed on the deployed optional
branch. Specialized banking chat/conversation routes are removed. Session
revocation remains an optional integration action.

## Verified checks

| Check | Result |
| --- | --- |
| Python pipeline/MCP/demo/evaluation suite | Windows and Linux CI passed at `0a3ab0d`, including acceptance-runner scope checks, protected policy provisioning and the final measurements. |
| SQLite 500-read contention | Original 500-call test unchanged; passed three consecutive local Windows repeats. Replay race, session ownership, external writer and expiry fences also passed. |
| Chat UI | Actual Sol resolved current conversation/flow commands; actual A/B MCP lookups matched independent customer queries. Conversation preset hidden from model arguments. |
| Operator API | Actual Sol A/B reads in one operator conversation matched independent customer queries. |
| Slack bridge | Actual Bridge/FlujoClient/Sol A/B turns passed; fresh root rejected the old selection handle in an actual tool result. Delivery mocked; no Slack posts. |
| Local handoff | Actual Sol ticket creation, persisted receipt and structured handoff envelope passed after an urgency-prompt correction. |
| Native restricted profile | Per platform, Windows and Linux: 42 HTTPS, 42 preferred WebSocket and 14 production tool-bridge cases across Sol/Luna. Approved MCP executed; forbidden native capabilities rejected. CLI 0.157.1 and the restrictive catalog are pinned by exact hashes. |
| Deployment | Existing worker healthy at optional revision `153a0391`; compiled optional adapter selected; native CLI/catalog hash pins verified. Live policy is a protected native Linux file, provisioned from the approved staging bytes. |
| Authenticated customer | Actual Sol lookup completed in 16.024 s; its persisted MCP transaction reference matched the independent customer oracle. Private assertions and execution credentials were absent from state. |
| Foreign handle | Actual customer B model called `get_my_transaction` with A's handle. MCP returned `reference_unavailable`; no foreign transaction was returned. |
| Normal-route HTTP security | 19 checks passed: original foreign/replay/body/admin/graph checks plus expired history/cancel/revoke/continue assertions and forged job lease/metadata. |
| Lifecycle | Repeated on the current graph using a retained successful model conversation: completed events/cancel, revocation, worker restart and deletion passed. Fresh authorized owners retained access; revoked sessions and deleted history were denied. No additional model calls were needed. |
| FLUJO source checks | Accepted-job patch `153a0391` passed independent review, 16 suites/230 tests, types and lint. Generic `8f8c571f` and optional test-only `0afeaf0b` passed every required CI gate, including full/isolated suites and published baselines, Windows/Linux builds, installer and release checks. |

The Slack harness selected the permanent Banking Operator graph locally.
The deployed default is still Slack Assistant. Its model path with outbound Slack
tools has not been exercised. The actual chat UI test uses operator authority,
not authenticated customer authority.

The resource-arming defect and strict MCP response-contract drift are fixed.
Trusted errors now retain their safe code across separate Next server module
graphs. The dedicated CLI 0.157.1 uses the existing Sol model and subscription;
no new provider or model was configured.

The deployed application remains `153a0391`. The production source tree is
identical at `0afeaf0b`; only the fixture timeout and its comments changed.
The real-model measurements below belong to that deployed application, while
CI belongs to the exact tested source revision.

The earlier `153a0391` baseline correctly caught one mocked 500-owner fixture
exceeding its 120-second test timeout. Reviewed `0afeaf0b` grants that test
450 seconds, preserves every assertion and changes no production code or
baseline threshold. Its [full CI run](https://github.com/mario-andreschak/FLUJO/actions/runs/36528348650)
passed all 7,568 executed tests; the 500-owner fixture passed in 132.404 seconds.
The [installer run](https://github.com/mario-andreschak/FLUJO/actions/runs/36528348642)
also passed. No redeployment or additional model run was needed.

## Current model capacity

The current permanent customer flow uses the existing Sol model and three
read-only MCP tools. It has no Static prefetch step. Each successful request is
checked against an independent customer oracle, its persisted successful MCP
result, its real model attempt and its delivered HTTP answer.

The final phases used native Linux policy storage and the reviewed accepted-job
lease at optional revision `153a0391`. All requests were submitted together within
each phase. Admission remained capped at 128 active jobs and 512 queued jobs;
the HTTP client's explicit 450-second timeout is separate from server deadlines.

The committed acceptance runner also defaults to 450 seconds. For an authorized
replay using an existing private manifest, make the observation budget explicit:

```powershell
python scripts/banking_acceptance_load.py --manifest PRIVATE.json --phases 1,10,50,500 --timeout-seconds 450
```

Replace `PRIVATE.json` with the approved manifest path. The timeout controls the
HTTP client wait; request assertions remain at most 120 seconds and accepted-job
authority remains at most 410 seconds, capped by the session. The runner reports
aggregate response checks; its private tool/model/owner audit remains required.

| Submitted together | Result | p50 / p95 | Total |
| --- | --- | --- | --- |
| 1 | 1/1 passed | 18.054 s / 18.054 s | 18.055 s |
| 10 | 10/10 passed | 13.067 s / 17.458 s | 17.460 s |
| 50 | 50/50 passed | 23.804 s / 25.688 s | 45.761 s |
| 500 | **500/500 passed** | 147.363 s / 237.784 s | 257.693 s |

The 500-phase audit matched exactly 500 successful MCP calls, 500 completed real
Sol model attempts and 500 delivered answers to independent customer oracles in
500 distinct conversations. All 500 persisted states passed the owner/privacy
audit; no foreign results, authority markers or private CLI homes remained.
Native process peak was 88 and worker memory peaked at 4.798 GB. Timings include
queue time; this demonstrates 500 concurrent submitted requests with bounded
admission, not 500 simultaneously running native processes.

Each request used one actual fresh assertion with a lifetime of at most 120
seconds. For 293 requests, the same-run successful model terminal event and
client-observed completion occurred after that assertion expired. This evidence
joins the timing records to the exact ownership-audit correlation digest. It
establishes bounded accepted work across ingress expiry, without extending fresh
request validity. These timestamps are not network delivery or lease-acceptance
timestamps.

After the burst, all 19 ordinary HTTP security checks passed, including expired
controls and attempted lease injection. Revocation and ownership survived a
restart; deleting the owned test conversation created an enforced tombstone.
Read-only SQLite inspection confirmed MCP session binding and durable revocation.

## Earlier capacity evidence

| Test | Customers / active | p50 / p95 | Limit |
| --- | --- | --- | --- |
| Earlier live Static + stdio | 500 distinct / 32 active | 26.399 s / 48.401 s | 500/500 owner matches; zero provider calls or selected-source verification. Total 53.43 s including audit. |
| Normal Process + deterministic external fixture provider | 500 distinct / peak 4 active | 30.302 s / 59.471 s | 500/500 owner matches on contended Windows host; total 65.200 s. No native model calls. |
| Offline Slack scheduler | 500 conversations / 1,000 turns / peak 8 active | Not model latency | Mocked delivery; ordering and correlation checks. |
| Actual Sol, one customer | 1 submitted | 18.653 s / 18.653 s | Independent persisted MCP/owner audit passed. |
| Actual Sol, ten customers | 10 submitted / native peak 8 | 18.624 s / 29.387 s | 10/10 persisted MCP/owner audits; worker peak about 1.24 GB. |
| Actual Sol, fifty customers | 50 submitted / native peak 23 | 67.237 s / 78.790 s | 50/50 persisted MCP/owner audits; worker peak about 1.82 GB. |
| First actual Sol 500 burst | 500 submitted / native peak 12 | 119.868 s / 133.270 s | **Failed capacity:** 49 completed, 166 cancelled (409), 285 expired (401). Timings cover all HTTP responses, including failures. |

The first burst's 49 successful outputs and all 127 persisted states passed their
owner/privacy checks. Later bursts failed with 146 native successes, 149
Static-prefetch/model-summary successes, and then 216 native successes at
`d28b260e` (157 expired, 127 cancelled; 121.840 s total). The Static-prefetch graph
was tested separately and removed from the deployed customer flow.

The final pre-lease phase showed late unsuccessful `run.started` offsets around
100 seconds median under the same 120-second ingress expiry. Successful adapter
attempts took about 30.456 s median/40.627 s p95; MCP calls took about 1.068 s
median/3.325 s p95. These spans included runtime/tool/guard work and the offsets
were not pure queue latency. The accepted-job lease corrected that deadline
coupling; the model, permanent graph and admission cap stayed unchanged.

Identical executable verification is shared only while verification is in flight;
each caller retains fresh file/catalog/authorization checks. Completed verification
is not cached. Moving the protected policy from a Windows bind mount to native
Linux storage preceded the historical result of 216 successes. Those changes
alone did not establish sufficient throughput. There is no measured provider rate-limit
or memory-pressure explanation. Native process counts are not admission telemetry;
first HTTP body byte is not model time to first token.

## Demo and evaluation limits

The inquiry demo uses a pinned historical window of at most 31 process dates.
Pending/reversed cases exist; natural duplicate-charge cases were not found.
Label injected duplicate cases synthetic.

Handoff creates a **local FLUJO ticket**, not a banking operation. Its receipt is
read back from persisted FLUJO data. A repeated ticket write is not idempotent;
do not automatically replay an uncertain write.

The ES/PT classifier holdout is frozen and AI-authored. It is not independently
human reviewed. Routing errors/abstention are measured; production quality and
independent human evaluation remain unproven.

Private configs, keys, subject mappings, records and traces stay ignored.

## References

- [Remaining acceptance and decisions](BANKING_MCP_NEXT_STEPS.md)
- [Operator demo](BANKING_OPERATOR_DEMO.md)
- [MCP setup and assertion contract](../banking_mcp/README.md)
- [Carlos's pipeline](../pipeline/README.md)
