# Banking MCP: decisions and remaining acceptance

Updated September 29, 2026, after four coordinated reviews and implementation.
This replaces the earlier proposal. See [implementation and measurements](BANKING_MCP_IMPLEMENTATION.md)
and [operator demo instructions](BANKING_OPERATOR_DEMO.md).

**September 30 source separation; October 1 project source status:** Keep FLUJO main generic; prefer this
application and MCP for banking behavior. The owner-authorized
`codex/hackathon-banking` branch preserves the reversed #530/#532/#533
integration separately. FLUJO #534 restored the pre-#530 source tree on main at
`3fccc557`. The September 29 in-worker adapter, CLI-profile and tool-flow
descriptions below remain integration history tied to their original revisions,
not acceptance of a newly deployed branch. Project-owned host/direct-MCP
PRs #31/#32 are merged at observed project main `e967e7e` and included in the
local release integration `af3b22d`; they are not in the preserved FLUJO
branch. The old runtime and its evidence are unchanged. The
[product boundary](FLUJO_PRODUCT_BOUNDARY.md) governs new work, and the
[deployment source map](FLUJO_HACKATHON_DEPLOYMENT.md) identifies the source to use.

## Decisions

- Keep Carlos's pipeline and customer lookup over immutable gold Parquet. S3 supplies ingestion and optional verification of a selected source object.
- Run Python MCP through **stdio inside the existing FLUJO worker**.
- Use permanent graphical flows. Do not create a flow per customer.
- Give organizers an explicit approved customer selector in operator mode.
- Bind customer mode to a verified per-request principal, outside prompts, flow definitions, conversation metadata and model-visible arguments.
- Keep FLUJO main general purpose. Prefer project host/MCP ownership of banking authority, policy and orchestration; any demo-specific FLUJO integration stays on the dedicated hackathon branch. Ordinary generic language interfaces do not carry banking keys, actions or selection capabilities.
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
| FLUJO | Generic private execution seams; all reference/preset families covered; separate optional banking integration. `@current` resolves execution context without opening a picker. Explicit entity selectors, file/folder search, tool/resource/global/run references and hidden presets retain their respective behavior. |
| Chat UI | Actual Sol resolved current conversation/flow references. A/B banking lookups matched independent customer queries in the same operator conversation. |
| Slack bridge | Actual Bridge/FlujoClient/Sol: A, B follow-up, then rejection of A's old handle in a fresh root. Delivery mocked; nothing posted to Slack. |
| Human handoff | Actual Sol created a local FLUJO ticket; persisted receipt, conversation/flow presets and handoff envelope verified. No bank action. |
| Queues | Private accepted-job lease: queue at most 300 s, active at most 110 s, total at most 410 s, capped by session. Fresh request proofs remain at most 120 s. Slack preserves ordering within each conversation. |
| Native profile | Pinned CLI 0.157.1/catalog; Windows and Linux each passed 42 HTTPS, 42 preferred WebSocket and 14 production bridge cases across Sol/Luna. |
| Authenticated customer | Actual Sol lookup matched its independent owner oracle. B's actual tool call could not use A's handle. |
| Ordinary ownership/lifecycle | 19 HTTP checks passed, including expired controls and forged job authority. Events/cancel, durable revocation/ownership across restart and deletion tombstones passed on the final build. |
| CI | Banking suites passed on Windows/Linux at `0a3ab0d`. Generic `8f8c571f` and optional test-only `0afeaf0b` passed every required gate, including full/isolated suites and published baselines. |

The Slack model test used the permanent Banking Operator flow in a harness
configuration. The deployed default remains Slack Assistant. Its actual model
path with Slack write tools has not been tested; no outbound Slack authorization
was given.

## Acceptance and follow-ups

Implementation acceptance passed: actual 1/10/50/500 model phases and current
controls/lifecycle on deployed `153a0391`; every required source CI gate on
test-only `0afeaf0b`, whose production code is identical. The earlier baseline
caught a mocked fixture's 120-second test timeout. The reviewed correction gives
that fixture 450 seconds without changing assertions or baseline thresholds.
See [the final CI run](https://github.com/mario-andreschak/FLUJO/actions/runs/36528348650).

Human review of ES/PT evaluation text remains a submission task. Customer
frontend enrollment, live Slack delivery and operational monitoring are separate
deployment follow-ups; they are not prerequisites for the existing operator demo.

The 500-model gate is now passed. The reviewed lease separates accepted work from
ingress expiry; fresh controls, replay/session/owner/revocation/policy checks
remain enforced. Specialized chat/conversation routes are retired.

## Measurements and limits

| Workload | Result | Scope |
| --- | --- | --- |
| Real gold lookup | 4,425,008 ownership-valid transactions; small local check p95 about 9 ms | Local lookup, not full chat latency. |
| Earlier live Static + stdio | 500/500 distinct owner matches; p50 26.399 s / p95 48.401 s | No model calls or selected-source verification. |
| Normal Process with deterministic external fixture provider | 500/500 distinct signed owners; peak 4 active; p50 30.302 s / p95 59.471 s on contended Windows host | Ordinary execution/dispatch isolation, not native provider capacity. |
| Actual Sol operator calls | A/B lookup and handoff passed, roughly 18–26 s per call | These measured demo cases. |
| Offline Slack queue | 500 conversations / 1,000 turns; peak 8 active; mocked delivery | Scheduler ordering/correlation, not model or Slack throughput. |
| Final actual Sol customers | 1/10/50 passed; fifty-customer p50 23.804 s / p95 25.688 s, total 45.761 s | Full actual MCP, real model and delivered-answer owner checks passed. |
| Final actual Sol 500 burst | **500/500 passed**; p50 147.363 s / p95 237.784 s; total 257.693 s | Exactly 500 MCP calls/model attempts/own replies and 500 private states audited. Native peak 88; worker 4.798 GB. Admission cap 128, queued work included. |

The final model test submitted 500 customers concurrently with bounded admission.
It does not mean 500 native processes ran simultaneously. Keep fixture/scheduler
results separate from this real-model capacity evidence.

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
