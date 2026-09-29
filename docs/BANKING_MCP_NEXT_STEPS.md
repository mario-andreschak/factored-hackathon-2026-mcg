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
| Native profile | Pinned CLI 0.157.1/catalog; Windows and Linux each passed 42 HTTPS, 42 preferred WebSocket and 14 production bridge cases across Sol/Luna. |
| Authenticated customer | Actual Sol lookup matched its independent owner oracle. B's actual tool call could not use A's handle. |
| Ordinary ownership/lifecycle | 13 HTTP attack checks on a successful conversation, completed events/cancel, durable revocation/ownership across restart and deletion tombstones passed. |
| CI | Banking suites passed on Windows/Linux at `e6a6313`; exact generic `8f8c571f` and optional `d28b260e` FLUJO revisions passed every required gate. |

The Slack model test used the permanent Banking Operator flow in a harness
configuration. The deployed default remains Slack Assistant. Its actual model
path with Slack write tools has not been tested; no outbound Slack authorization
was given.

## Remaining acceptance

1. Review the accepted-work lifetime. Current late starts lose their execution
   budget to the 120-second ingress expiry. A separate bounded server-owned job
   lease is being reviewed; fresh ingress, replay, session, owner, revocation and
   current-policy checks must remain enforced. The active-run bound stays 110 s.
2. After a reviewed fix, repeat actual model phases at 1/10/50/500 with independent
   tool/model/delivered-answer ownership checks, stopping at the first failure.
   The latest 500 burst failed: 216 passed, 157 expired and 127 cancelled.
3. Update final CI/PR evidence and repeat affected ordinary controls after the last
   deployment. Specialized chat/conversation routes are already retired; current
   graph ownership, revocation, restart and deletion checks passed.
4. Human review of ES/PT evaluation text remains a submission task.

## Measurements and limits

| Workload | Result | Scope |
| --- | --- | --- |
| Real gold lookup | 4,425,008 ownership-valid transactions; small local check p95 about 9 ms | Local lookup, not full chat latency. |
| Earlier live Static + stdio | 500/500 distinct owner matches; p50 26.399 s / p95 48.401 s | No model calls or selected-source verification. |
| Normal Process with deterministic external fixture provider | 500/500 distinct signed owners; peak 4 active; p50 30.302 s / p95 59.471 s on contended Windows host | Ordinary execution/dispatch isolation, not native provider capacity. |
| Actual Sol operator calls | A/B lookup and handoff passed, roughly 18–26 s per call | These measured demo cases. |
| Offline Slack queue | 500 conversations / 1,000 turns; peak 8 active; mocked delivery | Scheduler ordering/correlation, not model or Slack throughput. |
| Latest actual Sol customers | 1/10/50 passed; fifty-customer p50 22.095 s / p95 23.615 s, total 49.641 s | Full actual MCP, real model and delivered-answer owner checks passed. |
| Latest actual Sol 500 burst | 216/500 passed; 157 expired, 127 cancelled; total 121.840 s | Failed capacity. All 216 successes passed the full owner check; all 334 persisted states passed privacy checks. Peak native processes 89; worker 4.721 GB. |

None of the 500-case results above establishes 500 successful concurrent native
model chats. Keep fixture/scheduler results separate from model capacity.

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
