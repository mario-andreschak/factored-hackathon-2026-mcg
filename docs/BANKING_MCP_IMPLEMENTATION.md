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
Banking Customer graph uses existing Sol and private caller binding.
No temporary per-customer flow or new frontend is required for operator testing.

Old specialized routes remain protected during migration. Their retirement depends
on normal-route ownership and lifecycle acceptance.

## Verified checks

| Check | Result |
| --- | --- |
| Python pipeline/MCP/demo/evaluation suite | Latest code: **121 tests + 36 subtests passed** on Windows and Linux. |
| SQLite 500-read contention | Original 500-call test unchanged; passed three consecutive local Windows repeats. Replay race, session ownership, external writer and expiry fences also passed. |
| Chat UI | Actual Sol resolved current conversation/flow commands; actual A/B MCP lookups matched independent customer queries. Conversation preset hidden from model arguments. |
| Operator API | Actual Sol A/B reads in one operator conversation matched independent customer queries. |
| Slack bridge | Actual Bridge/FlujoClient/Sol A/B turns passed; fresh root rejected the old selection handle in an actual tool result. Delivery mocked; no Slack posts. |
| Local handoff | Actual Sol ticket creation, persisted receipt and structured handoff envelope passed after an urgency-prompt correction. |
| Native restricted profile | 42 forced-call Linux probes across Sol/Luna; approved MCP executed, forbidden native capabilities rejected. |
| Deployment | Existing worker healthy; compiled optional adapter selected; native CLI/catalog hash pins verified. |
| Normal-route HTTP security | 13 actual checks passed: foreign history/events/delete/cancel/continue, replay, missing assertion and forged body/metadata/admin/graph requests. No new model calls. |

The Slack harness selected the permanent Banking Operator graph locally.
The deployed default is still Slack Assistant. Its model path with outbound Slack
tools has not been exercised. The actual chat UI test uses operator authority,
not authenticated customer authority.

The resource-arming ordering defect is fixed. Normal customer requests reach the
provider, but pinned CLI 0.153.3 receives unsupported-model errors for both Sol
and Luna. Ordinary Sol succeeds with CLI 0.157.1. New native capability and
transport proofs are required before enrolling that binary. Actual customer model
acceptance/load remains pending. The HTTP checks used an owned failed-provider
conversation; they do not prove successful customer tool execution.

## Capacity evidence

| Test | Customers / active | p50 / p95 | Limit |
| --- | --- | --- | --- |
| Earlier live Static + stdio | 500 distinct / 32 active | 26.399 s / 48.401 s | 500/500 owner matches; zero provider calls or selected-source verification. Total 53.43 s including audit. |
| Normal Process + deterministic external fixture provider | 500 distinct / peak 4 active | 30.302 s / 59.471 s | 500/500 owner matches on contended Windows host; total 65.200 s. No native model calls. |
| Offline Slack scheduler | 500 conversations / 1,000 turns / peak 8 active | Not model latency | Mocked delivery; ordering and correlation checks. |

These tests establish isolation for their measured paths. They do not establish
500 simultaneous native model chats or a production SLA.

Actual model load must run at 1/10/50/500 distinct signed customers and stop at the
first failure. Response references require an independent owner oracle, followed
by a private persisted-tool audit. Report submitted and active counts, queue expiry,
provider errors, retries and memory separately; leave unmeasured fields null.

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
