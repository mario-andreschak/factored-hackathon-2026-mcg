# Tested FLUJO capacity and sandbox collaboration

Reviewed October 5, 2026. Savia builds on a working, measured FLUJO orchestration
and private inference foundation: a 300-request FLUJO load test, real tool
execution, collaborating Fly sandboxes and independently checked benchmark
outputs. The two reviewers in the submission film are the recorded customer
example, not the infrastructure's capacity limit.

## Existing load test: October 4

The original test used local production FLUJO, its `/v1/chat/completions`
flow-as-model interface, and Qwen3.8-27B FP8 served by vLLM 0.30.0 on one Modal
H100. Each request contained a unique reference code; the harness checked the
returned code as well as HTTP success. These were real provider requests.
Parallel means submitted client requests; FLUJO queues model execution.

The [public aggregate receipt](infrastructure-capacity.json) records every stage
from both runs. On October 5, its counts were checked against the original
per-request JSONL records without making another model call.

| Measured workload | Parallel requests | HTTP success | Correct reference | Latency p50 / p95 |
| --- | --- | --- | --- | --- |
| FLUJO plain flow, 1k context, neutral wording repeat | 300 | 300/300 | 300/300 | 273.40 / 441.60 s |
| FLUJO plain flow, 8k context, repeat | 32 | 32/32 | 32/32 | 35.28 / 58.02 s |
| FLUJO plain flow, 128k context, repeat | 2 | 2/2 | 2/2 | 29.66 / 29.66 s |
| FLUJO flow with filesystem tools available, repeat | 64 | 64/64 | 64/64 | 115.27 / 144.70 s |
| Direct inference, 1k context | 400 | 400/400 | 399/400 | 20.75 / 26.42 s |
| Direct inference, 500k context | 1 | 1/1 | 1/1 | 113.21 / 113.21 s |

Across both runs, **1,289/1,289 requests returned HTTP 200**. The first
300-request FLUJO stage returned 217/300 correct references: its “secret
passphrase” wording caused refused/empty replies. The neutral “order reference
code” repeat returned 300/300. Both results remain in the receipt. The original
report separately records real filesystem-tool calls in 64 of 65 inspected
saved conversations from the first tools run; correctness alone does not attest
tool execution in the repeat.

The repeat's raw summary records peak FLUJO RSS of **411.74 MB** and CPU of
**267% of one core** in the 300-request stage. This corrects the original prose
summary's lower range, which covered the first run. Latency includes admission
and queueing; 300 concurrent submissions do not mean 300 simultaneous GPU
generations. One successful 500k retrieval is a sample, not a quality study.

Source: private inference repository commit
`496e5930fa23836f5e805ef226afe840f728b888`, original
`loadtest/results/2026-10-04-SUMMARY.md`, both `summary.json` files and their
per-request records. SHA-256 hashes are in the aggregate receipt. Credentials,
provider origins, reference-code replies and native histories remain private.
The public receipt contains counts, timing/resource summaries and provenance.

## Real sandbox and collaboration runs

Recovered engine source `f9d372a66dd2cb09f4bcfed34967404cf12d9007`,
`swarm-teams/README.md` and `RECOVERY.md`, records:

- A real Fly Worker running a lead and two parallel agents, executing Linux
  commands, writing the requested file and then being retired.
- A mixed tree with **18 separate Fly leaf sandboxes live together**, 17 completed
  leaf team runs and six matching sorted-output hashes from different sandboxes.
  Shared findings and a claim checker supported the selected result. Six of 24
  leaf slots failed provisioning; operator steering was required.
- A larger recovered run with ten technology branches and 96 enrolled child
  Workers over time. Its corrected table contains 77 correct timed approaches,
  one incorrect timed approach and 12 did-not-finish entries. A separate Python
  reference and an isolated Go execution agreed on 949965 distinct values.
  This does not attest the performance of the original timed source.

These are completed infrastructure exercises, including actual collaboration,
tools, result checking and cleanup. Worker enrollment over time remains distinct
from simultaneous sandbox count. Underlying run histories remain private.

## Savia integration and submission-video budget

Savia's architecture uses ten team Machines, each with one lead and nine
specialists: 100 team conversations, with root supervision separate. It reuses
native subflow messaging, fleet delegation, shared board and relay. The
application-owned [connector](../assistant/FLEET_CONNECTOR.md) binds inquiries
to original native runs and publishes reviewed results. Startup configuration
wiring was fixed in PR #66 and deployed in the later prototype.

**An additional paid fleet/load run for the submission video was skipped because
of budget constraints.** Existing infrastructure tests and frozen successful
voice/customer recordings are retained. No new funding or capacity rerun is
required for the submission handover.

Before that decision, one October 5 integrated customer attempt was started.
Bank facts and foreground voice completed; the first background root model call
returned HTTP 404 because the provider workspace was disabled, before delegation.
Its [original receipt](fleet-customer-attempt/receipt.json) remains a failed
attempt, separate from the skipped further run and successful October 4 tests.
It does not invalidate those tests or establish a completed ten-Machine/
100-conversation customer investigation.

The supported claim is **tested FLUJO/inference capacity and real sandbox
collaboration, with integrated Savia voice and a deployed fleet connector**.
Exact 100-agent customer completion, real human pickup, customer push/email and
multi-day reliability retain their separate acceptance scopes.

## Application architecture and development process

| Responsibility | Implementation and evidence |
| --- | --- |
| Customer UI, voice and retained context | [Frontend](../../../frontend/README.md), [voice](../../../frontend/src/avatar/README.md), [customer story](../CUSTOMER_JOURNEY.md) |
| Durable inquiries, idempotent submission, dispatch and recovery | [Inquiry service](../../../savia_assistant/service.py), [fleet consumer](../../../savia_assistant/fleet.py), [connector contract](../assistant/FLEET_CONNECTOR.md) |
| Data ownership, consent and verified simulated receipts | [Direct-host contract](../../../frontend/DIRECT_MCP.md), [banking service](../../../banking_mcp/README.md) |
| Repeatable serving snapshots and lineage | [Pipeline](../../../pipeline/README.md) |
| System responsibilities and generic/domain separation | [Architecture](../../architecture/system-landscape.md), [FLUJO boundary](../../FLUJO_PRODUCT_BOUNDARY.md) |
| Reproducible checks and review | [Windows/Linux CI policy](../../LOCAL_CI.md), [workflow](../../../.github/workflows/tests.yml), [PR template](../../../.github/pull_request_template.md) |
| Deployment and publication provenance | [Release report](../RELEASE_CANDIDATE.md), [measurements](MEASURED_RESULTS.md) |

The process uses source-pinned PRs, separate Windows/Linux dependency environments,
frontend builds, ownership/recovery checks, immutable image identities and
recorded customer runs. Reports preserve failures and distinguish source checks,
infrastructure tests and customer outcomes. Independent held-out ES/PT quality
evaluation and measured business impact are separate from capacity testing.
