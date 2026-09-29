# Banking MCP: decisions and remaining acceptance

Updated September 28, 2026, after four coordinated reviews and implementation.
This replaces the earlier proposal. See [implementation and measurements](BANKING_MCP_IMPLEMENTATION.md)
and [operator demo instructions](BANKING_OPERATOR_DEMO.md).

## Decisions

- Keep Carlos's pipeline and customer lookup over immutable gold Parquet. S3 supplies ingestion and optional verification of a selected source object.
- Run Python MCP through **stdio inside the existing FLUJO worker**.
- Use permanent graphical flows. Do not create a flow per customer.
- Give organizers an explicit approved customer selector in operator mode.
- Bind customer mode to a verified per-request principal, outside prompts, flow definitions, conversation metadata and model-visible arguments.
- Keep shared FLUJO changes generic and optional. Banking policy belongs in the hackathon adapter; use ordinary `/v1/chat/completions`.
- Use the existing Sol and Luna models. Restricted customer runs use a separately pinned and tested CLI profile.

## Two modes, same read tools

| Mode | Selection | Boundary |
| --- | --- | --- |
| Private operator test | Tester explicitly requests an approved dataset customer. | Private allowlist; read-only results; handles bound to customer and conversation. |
| Authenticated customer | Omit the selector to use the verified caller. | Signed ingress, immutable conversation owner, scoped tools and a fresh assertion independently verified by MCP. Foreign selectors rejected. |

Operator selection is a demo facility, not customer authentication. Never reuse an
operator conversation containing A/B results as a bound customer conversation.
Start a fresh conversation using the same approved graph.

`@current.conversation.id` supplies nonsecret correlation through a hidden preset.
A bare conversation ID is not proof of identity. `@_meta.fieldname` remains an
optional follow-up and is not required for this demo.

## Implemented and tested

| Area | Evidence |
| --- | --- |
| Data/MCP | Optional selectors, explicit operator mode, independent row ownership checks, opaque handles, snapshot inventory validation and shutdown cleanup. |
| FLUJO | Generic private execution seams; reference/preset fixes; separate optional banking integration. |
| Chat UI | Actual Sol resolved current conversation/flow references. A/B banking lookups matched independent customer queries in the same operator conversation. |
| Slack bridge | Actual Bridge/FlujoClient/Sol: A, B follow-up, then rejection of A's old handle in a fresh root. Delivery mocked; nothing posted to Slack. |
| Human handoff | Actual Sol created a local FLUJO ticket; persisted receipt, conversation/flow presets and handoff envelope verified. No bank action. |
| Queues | Bounded private admission; Slack scheduler preserves ordering within each conversation. |
| Native profile | Exact CLI/catalog hashes; 42 Linux forced-call probes across Sol/Luna. Approved MCP executed; forbidden native capabilities rejected. |
| Python CI | 121 tests and 36 subtests passed on Windows and Linux. Unchanged 500-read gate also passed three consecutive local Windows repeats. |

The Slack model test used the permanent Banking Operator flow in a harness
configuration. The deployed default remains Slack Assistant. Its actual model
path with Slack write tools has not been tested; no outbound Slack authorization
was given.

## Remaining acceptance

1. Finish the normal customer path with an existing supported model. The build
   selects the adapter, and the resource-arming defect is fixed. The pinned
   0.153.3 CLI reached the provider but received unsupported-model errors for
   both Sol and Luna. Ordinary Sol works with 0.157.1. Verify the newer binary
   against the restrictive catalog before enrolling it; keep dispatch guards.
2. Audit private tool results against independent customer oracles. Verify foreign
   history/events/control, handles and revocation through the ordinary route.
   Thirteen actual HTTP checks already passed for foreign history/control/continue,
   replay, missing assertions and forged identity/administration requests. These
   used an owned failed-provider conversation and made no new model calls.
3. Run actual model phases at 1/10/50/500 distinct customers, stopping at the first
   failure. Report queue expiry, provider limits and memory honestly.
4. Retire specialized legacy routes only after ordinary-route owner and lifecycle
   tests pass. Keep old conversations protected during migration.
5. Refresh final PR evidence after the last source changes. Human review of ES/PT
   evaluation text remains a submission task.

## Measurements and limits

| Workload | Result | Scope |
| --- | --- | --- |
| Real gold lookup | 4,425,008 ownership-valid transactions; small local check p95 about 9 ms | Local lookup, not full chat latency. |
| Earlier live Static + stdio | 500/500 distinct owner matches; p50 26.399 s / p95 48.401 s | No model calls or selected-source verification. |
| Normal Process with deterministic external fixture provider | 500/500 distinct signed owners; peak 4 active; p50 30.302 s / p95 59.471 s on contended Windows host | Ordinary execution/dispatch isolation, not native provider capacity. |
| Actual Sol operator calls | A/B lookup and handoff passed, roughly 18–26 s per call | These measured demo cases. |
| Offline Slack queue | 500 conversations / 1,000 turns; peak 8 active; mocked delivery | Scheduler ordering/correlation, not model or Slack throughput. |

None of the 500-case results above establishes 500 simultaneous native model chats.

The current gold-only rebuild copies legacy lineage. It does not newly validate
the bronze objects consumed by earlier ingestion. Selected-object verification
also does not establish freshness across newer S3 partitions.

The classifier holdout is AI-authored and frozen, not independently human reviewed.
Report its errors and abstention without claiming production performance. No
natural duplicate-charge demo cases were found; label injected duplicates synthetic.

## Review and PR ownership

Four review tasks covered generic FLUJO integration, isolation/concurrency,
MCP/data lifecycle and demo/Slack acceptance. The existing Slack task owns its
scheduler. Source owners preserve unrelated changes.

- [Banking MCP/data/demo PR #6](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/6)
- [Generic FLUJO PR #528](https://github.com/mario-andreschak/FLUJO/pull/528)
- [Optional banking integration PR #530](https://github.com/mario-andreschak/FLUJO/pull/530)
- [Slack scheduler PR #1](https://github.com/flujo-app/flujo-slack-bot/pull/1)
