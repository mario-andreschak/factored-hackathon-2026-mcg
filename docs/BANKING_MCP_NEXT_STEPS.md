# Banking MCP: next implementation plan

September 28, 2026. **Proposal after four coordinated code reviews.** This
supersedes the older banking ingress/S3 and tool-preset integration proposals.
The changes proposed below are not deployed.

## Recommendation

Keep the Python stdio MCP inside the existing FLUJO worker, Carlos's DuckDB
snapshot pipeline, and one reusable graphical banking flow.

First enable approved customer selection through ordinary FLUJO chat and the
existing Slack bot. Then add optional, generic execution seams for authenticated
customer runs through the normal completion endpoint. Banking authentication,
policy, and signing belong in the hackathon integration. Presets are useful if
needed; they are neither mandatory nor a substitute for authorization.

The first complete demo should show verified transaction inquiry, clarification,
and structured human handoff in Spanish and Portuguese. Simulated dispute intake
is additional scope until confirmation, persistence, idempotency, and verified
receipt readback actually exist.

## Current state

| Area | Implemented | Remaining |
| --- | --- | --- |
| MCP | Banking PR #5 merged; status/list/inspect tools; Python stdio inside the existing worker. | Selectable approved test customers and normal-path customer binding. |
| Data | Gold buckets, independent customer/product ownership checks, bounded pages, opaque handles, pinned-source readback. | Explicit freshness and lifecycle contract. |
| FLUJO | Static preset/reference fixes and `@current`; ordinary chat substitution verified. | Repair CI, separate generic/banking changes, add private execution seams. |
| Chat/Slack | Existing interfaces/provider path; Slack Assistant already enables both banking registrations. | Operator A/B acceptance and a banking flow with narrowly scoped tools. |
| Authority | Real reads are enforced through specialized banking ingress and a per-call verifier. | Equivalent normal-path enforcement, then retirement of specialized routes. |
| Capacity | 500 distinct owners passed a Static backend burst. | Normal conversational/provider path at 500; Slack queue correction if used concurrently. |

Sources reviewed: banking worktree `codex/banking-mcp@2805c1d`, merged implementation
`origin/main@c9465f3`; FLUJO `codex/banking-identity-hook@1f699678`. No running service,
saved flow, MCP configuration, or application source was changed in this review.

## Same tools, two explicit modes

| Mode | Customer selector | Authority |
| --- | --- | --- |
| Private operator test | Explicit customer from a server-configured allowlist. | Explicit private operator mode over approved organizer-synthetic records or generated fixtures. |
| Authenticated customer | Omission means the verified caller's customer; supplied foreign selector is rejected before lookup. | Verified frontend session, immutable conversation owner, independently verified MCP assertion. |

Add optional typed `customer_id` to list/inspect. Require it in operator mode;
derive it from the principal when omitted in bound mode. Update Python schemas
and the hackathon TypeScript argument validator together. Missing authentication
must never enable operator mode. Preserve the marked-fixture guard for the existing
synthetic demo; add an explicit operator profile instead of bypassing that guard.

Operator handles need customer and conversation binding. If necessary, use the
existing nonsecret `@current.conversation.id` preset for correlation, accepting
opaque Slack IDs. Missing/unresolved correlation fails. Correlation is not customer
authentication. Bound handles use the signed conversation claim; a supplied
conflicting conversation is rejected.

Testers type an ordinary request for approved A or B. They do not supply secret
metadata. A fixed-A preset can demonstrate argument overwrite; actual customer
authorization is a separate authenticated-path test.

**Never convert an A/B operator conversation into a bound-A conversation.** Its
history/provider session may already contain B's results. Start a fresh chat or
Slack root thread with the same graph. Do not create temporary customer flows.

## Generic FLUJO integration

Use a small hackathon branch/composition module with a trusted server adapter
registered at build/startup. Shared FLUJO offers optional domain-neutral seams;
ordinary installations retain their behavior. Do not build a plugin framework or
publish banking routes as a general FLUJO feature.

1. **Admission before state reads.** Verify the frontend's authenticated session,
   choose allowed workspace/graph/provider/tools, and check conversation ownership
   before loading history. Body metadata, prompts, user strings, URLs, and customer
   arguments cannot establish identity.
2. **Private per-turn context.** Keep verified authority in runtime memory, outside
   flow snapshots, tool maps, engine caches, prompts, debug output, events, and logs.
   Reauthenticate/rebind each turn or reload; missing context fails closed. Reuse
   a graph snapshot without customer secrets.
3. **Policy on every access path.** Gate history, events, media, delete, cancel,
   continue/resume, and publication. Bound runs also restrict references, resources,
   files, shared memory/KV, subflows, native capabilities, and tool scope. A crafted
   `@conversation[B].name` must not fetch B's title before MCP execution.
4. **Private dispatch after final arguments.** Apply permitted presets and normalize
   arguments, then invoke an optional trusted callback. The hackathon callback
   rechecks authority and supplies a fresh existing per-call assertion in MCP
   `_meta`. Retain issuer/audience/session/customer/tool/args checks, short expiry,
   replay protection, and independent row ownership verification.
5. **Result fence.** Recheck authority after reads/provider waits and before returning
   or persisting late results. Revocation while queued prevents publication. Each
   permitted redispatch gets a fresh assertion from current authority; never reuse
   assertions, extend expiry blindly, or replay an uncertain mutation automatically.

There is one recommended credential carrier: the existing fresh per-call assertion.
A reusable run-token verifier adds a security profile without removing private
context/ownership work; all reviewers agreed to defer it.

Keep raw FLUJO administration/control APIs private behind the customer frontend.
Preserve the verified real-data path until normal-path ownership, revocation, and
publication tests pass. Retire `/v1/banking/*` last; protect old owned conversations
during migration. The existing worker can later be rebuilt from the hackathon
branch without starting another instance.

`@_meta.fieldname` can follow as an optional **hidden-preset-only** resolver over
trusted runtime metadata. It must not resolve secrets into prompts, trust public
conversation metadata, or persist credentials. Required missing fields must fail.
This feature does not block operator tests or the proposed bound-tool contract.

## Data and capacity

Serve the immutable gold snapshot already used by the MCP. S3 remains the source
of record; ingestion and optional selected-object readback use mounted workload
credentials inside the same container. Avoid a full date-partition scan per chat.

Pinned-source verification checks the selected snapshot object. It does not detect
corrections in newer objects/partitions. Before claiming fresh source truth, pin or
validate the objects actually consumed during ingestion. Retain builds while
readers use them, close DuckDB at shutdown, and detect missing snapshot buckets
instead of reporting an empty history.

| Measurement | Scope | p95 |
| --- | --- | --- |
| Committed `lookup_bench.json`, 1/50/500 concurrency | Local Parquet, shared DuckDB connection, separate cursors; 1,000 requests per level | 34.5 ms / 1.93 s / 13.39 s |
| Deployed 500-subject FLUJO burst | Static + stdio, 32 active, one row, no provider or S3 readback | 48.401 s including queue |

README timings describe other workloads. None proves 500 model chats. Preserve
bounded admission/queues and per-call state; measure the normal path at 1/10/50/500
distinct customers with realistic pages. Separate queue/provider/tool/S3 timing;
report time to first response, full p50/p95/p99, throughput, errors/rate limits,
retries, memory, and submitted versus active counts. Tune bottlenecks before
claiming interactive performance at 500 customers.

Slack currently serializes turns globally. Preserve within-thread ordering; use
bounded across-thread execution if Slack serves concurrent customers and test it
independently. Do not change Slack identity or delivery semantics to fix queueing.

## Demo and acceptance

The supplied dictionary/summary identify organizer data as synthetic. Approved
organizer A/B facts remain viable for S3-backed inquiry; generated fixtures cover
controlled ambiguity/failure. Credentials, private subject mappings, and separately
restricted records remain private.

Pin a historical scenario window of at most 31 process dates. Select a seed whose
relevant row falls in it. Use verified date, type/channel, amount/currency, status,
product type, and opaque references when merchant names are missing. Exclude fraud
labels/scores and invalid complaint-product joins. The audited near-duplicate pool
is empty: label any injected duplicate as synthetic.

| Gate | Proof required |
| --- | --- |
| Existing chat and Slack | Select approved A, then B; reject unknown IDs. Check tool results, not just model prose. |
| Presets if used | Fixed A overwrites attempted B; hidden fields absent from model schema. This proves presets, not authentication. |
| Bound customer | Fresh A conversation/thread; B URL/body/tool/reference/handle attempts never return B data. Foreign history/events/control/resume denied before access. |
| Lifecycle | Missing/forged/expired/replayed/wrong-tool/changed-args binding denied; revoke during queue/read/model wait; reload cannot restore authority; retries retain ownership. |
| Concurrency | Distinct-owner oracle checks result/history/event/cancel isolation with reordered replies; same-thread turns ordered; overload/expiry bounded. Include normal model/provider path. |
| Hackathon outcomes | Normal verified inquiry, ambiguity clarification, and structured local human handoff with persisted receipt/readback; ES/PT. Do not claim dispute submission exists. |
| Evaluation | Reuse router/baseline work; replace provisional same-author test text with frozen independently reviewed ES/PT cases; report outcomes/errors/abstention/latency/cost. |

Operator Slack uses Codex. Its test does not prove bound CLI capability isolation.
Keep existing bound Codex/Claude exclusions and approval/elicitation/task/resource
restrictions until their actual paths pass equivalent tests. Initially use a normal
API-provider Process path for bound runs.

## Implementation order

1. Repair PR #528 CI and separate generic changes from banking code. Six failed
   suites/eight tests: ordinary Process calls add two trailing undefined arguments;
   five banking wrappers fail existing encryption/workspace coverage gates. Preserve
   guards; do not quarantine failures.
2. Add explicit operator mode and the optional-selector MCP contract. Prove normal
   graphical chat and Slack A/B acceptance inside the current worker.
3. Add optional admission/context/dispatch seams and the hackathon adapter. Prove
   ownership, reference restrictions, retry and revocation before retiring routes.
4. Run deterministic distinct-owner tests, then actual-provider/phased load tests.
   Fix data/queue/lifecycle issues relevant to those workloads.
5. Complete focused ES/PT inquiry/handoff, independent evaluation, redacted traces
   and submission artifacts. Add intake only with confirmation and verified receipts.

No new UI, MCP sidecar, FLUJO instance, temporary customer flow, reusable credential
profile, or Slack identity extension is required by this plan.

## Coordinated reviews

- [Review generic FLUJO banking integration](codex://threads/01a0ea4f-b123-7c31-8c8b-b91e65ed0e69)
- [Review banking isolation and concurrency](codex://threads/01a0ea4f-bfb6-7903-ac13-2173b417577d)
- [Review banking MCP and data lookup](codex://threads/01a0ea4f-ca41-7662-a44f-dbf7d1bee32f)
- [Review banking demo and Slack acceptance](codex://threads/01a0ea4f-dc61-7e13-a69f-540e13958850)

They coordinated with [Assess Slack bot feasibility](codex://threads/01a0e573-d7f9-7a20-afe1-026d1d547fed).
The credential-carrier disagreement was resolved in favor of the existing per-call
verifier. A blanket organizer-data restriction was corrected after reading the PDFs.

Evidence: Python `service.py`, `security.py`, `repository.py`, `config.py`; committed
`lookup_bench.json`; current FLUJO normal route state read at line 139, persisted
snapshot in `runFlow.ts:1398`, tool map/reference projection in `ProcessNode.ts:645/800`,
foreign reference load in `resolveDynamicReferences.ts:59`, CLI gate/dispatch in
`ModelHandler.ts:1969/3877`, final-args signer in `mcp/tools.ts:296`, and authority/owner
checks in `banking/authority.ts:199` and `banking/store.ts:134`.
