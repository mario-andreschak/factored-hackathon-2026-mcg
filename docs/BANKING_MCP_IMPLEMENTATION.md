# Banking MCP implementation

Updated September 28, 2026.

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

Organizers use one permanent Banking Operator graphical flow and existing Sol.
They select an approved customer explicitly. Hidden `@current.conversation.id`
correlates handles; it is not customer authentication. A separate permanent
`Banking_Customer` graph uses existing Sol and private caller binding.
No temporary per-customer flow or new frontend is required for operator testing.

Ordinary-route ownership and lifecycle acceptance passed. The optional branch
now removes specialized chat/conversation routes; deployment is pending the
concurrent verification fix. Session revocation remains an optional integration action.

## Verified checks

| Check | Result |
| --- | --- |
| Python pipeline/MCP/demo/evaluation suite | Latest code: **121 tests + 36 subtests passed** on Windows and Linux. |
| SQLite 500-read contention | Original 500-call test unchanged; passed three consecutive local Windows repeats. Replay race, session ownership, external writer and expiry fences also passed. |
| Chat UI | Actual Sol resolved current conversation/flow commands; actual A/B MCP lookups matched independent customer queries. Conversation preset hidden from model arguments. |
| Operator API | Actual Sol A/B reads in one operator conversation matched independent customer queries. |
| Slack bridge | Actual Bridge/FlujoClient/Sol A/B turns passed; fresh root rejected the old selection handle in an actual tool result. Delivery mocked; no Slack posts. |
| Local handoff | Actual Sol ticket creation, persisted receipt and structured handoff envelope passed after an urgency-prompt correction. |
| Native restricted profile | Per platform, Windows and Linux: 42 HTTPS, 42 preferred WebSocket and 14 production tool-bridge cases across Sol/Luna. Approved MCP executed; forbidden native capabilities rejected. CLI 0.157.1 and the restrictive catalog are pinned by exact hashes. |
| Deployment | Existing worker healthy; compiled optional adapter selected; native CLI/catalog hash pins verified. |
| Authenticated customer | Actual Sol lookup completed in 16.024 s; its persisted MCP transaction reference matched the independent customer oracle. Private assertions and execution credentials were absent from state. |
| Foreign handle | Actual customer B model called `get_my_transaction` with A's handle. MCP returned `reference_unavailable`; no foreign transaction was returned. |
| Normal-route HTTP security | 13 checks passed against a successful owned conversation: foreign history/events/delete/cancel/continue, replay, missing assertion and forged body/metadata/admin/graph requests. |
| Lifecycle | Completed events/cancel, revocation, worker restart and deletion passed. Revocation persisted in both stores; fresh authorized owners retained access, and tombstones denied deleted history. |

The Slack harness selected the permanent Banking Operator graph locally.
The deployed default is still Slack Assistant. Its model path with outbound Slack
tools has not been exercised. The actual chat UI test uses operator authority,
not authenticated customer authority.

The resource-arming defect and strict MCP response-contract drift are fixed.
Trusted errors now retain their safe code across separate Next server module
graphs. The dedicated CLI 0.157.1 uses the existing Sol model and subscription;
no new provider or model was configured.

## Capacity evidence

| Test | Customers / active | p50 / p95 | Limit |
| --- | --- | --- | --- |
| Earlier live Static + stdio | 500 distinct / 32 active | 26.399 s / 48.401 s | 500/500 owner matches; zero provider calls or selected-source verification. Total 53.43 s including audit. |
| Normal Process + deterministic external fixture provider | 500 distinct / peak 4 active | 30.302 s / 59.471 s | 500/500 owner matches on contended Windows host; total 65.200 s. No native model calls. |
| Offline Slack scheduler | 500 conversations / 1,000 turns / peak 8 active | Not model latency | Mocked delivery; ordering and correlation checks. |
| Actual Sol, one customer | 1 submitted | 18.653 s / 18.653 s | Independent persisted MCP/owner audit passed. |
| Actual Sol, ten customers | 10 submitted / native peak 8 | 18.624 s / 29.387 s | 10/10 persisted MCP/owner audits; worker peak about 1.24 GB. |
| Actual Sol, fifty customers | 50 submitted / native peak 23 | 67.237 s / 78.790 s | 50/50 persisted MCP/owner audits; worker peak about 1.82 GB. |
| First actual Sol 500 burst | 500 submitted / native peak 12 | 119.868 s / 133.270 s | **Failed capacity:** 49 completed, 166 cancelled (409), 285 expired (401). Timings cover all HTTP responses, including failures. |

These tests establish isolation for their measured paths. The first actual
500-customer burst failed throughput acceptance. All 49 successful outputs
matched their owners; an additional audit of all 127 persisted states found no
foreign results or authority leaks. All temporary private CLI homes were removed.

Every run independently rehashed the 285 MB executable before transferring
credentials, creating over 100 GB of verification work during the burst.
FLUJO is adding shared verification only while identical attestation work is in
flight. Fresh caller file checks, catalog checks and authorization remain required;
completed verification is not cached. Repeat model phases after deployment.
Authorization expiry and the 110-second run bound remain unchanged.

There is no measured provider rate-limit or memory-pressure explanation for that
failure. Native process peaks and worker memory were sampled separately; neither
is server admission telemetry. First HTTP body byte is not model time to first token.
Queue/provider/tool timing decomposition and provider retry counts remain unmeasured.

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
