# Gloria iteration checkpoint

This branch implements the application-owned ES/PT workflow described in
`graph_config_v3.yaml`: validated interpretation prompts, a same-turn parallel
rewrite/attack/context barrier, persistent conversation state, ordered R0–R18
policy decisions, owned read adapters, reviewed policy retrieval, narrative
handoff summaries, response grounding, one bounded repair and deterministic
fallbacks. The language workflow has no action write port. Chat consent cannot
authorize the existing portal's simulated intake.

## Source and execution boundaries

`gloria_workflow/runtime.py` owns the orchestration and `policy.py` owns the
deterministic motor. `state.py` persists owner/customer/session/conversation
state and immutable turn inputs in SQLite with revision checks. A cached
success needs a fresh owned-target and independently verified host receipt.
Field answers retain explicit earlier criteria; new requests clear them.
Missing duplicate/risk coverage cannot imply low risk. The policy requires a
complete 24-hour report whose end is no more than the configured 20 seconds old.

`prompts.py` renders canonical YAML prompts through the configured generic
FLUJO model endpoint. `response.py` validates grounded messages and safe ES/PT
fallbacks. Host identity, credentials, capabilities and raw customer records
are excluded from model inputs. Textual grounding remains conservative; it
does not prove arbitrary semantic claims or redact arbitrary names/addresses.

`host.py` binds frontend repository reads to the admitted profile and session,
checks revocation, distinguishes candidate hashes from serving snapshot IDs,
and independently reads existing host action status. Supported search fields
are transaction ID, event date range, currency, merchant, amount, transaction
type and channel. Type and channel use exact canonical enum matches. An omitted
date uses an inclusive 90-day window anchored to the latest owned event.
Populated city, country, product hint and product last-four filters return
`unsupported_filter` before searching; those filters require a qualified
adapter and never silently select a charge from an unfiltered result.

The default repository adapter intentionally reports incomplete source/risk
readback and duplicate coverage; historical complaints return an unsupported
error. Those paths fall back or request human assistance. Complete fictional
read ports qualify the canonical motor separately from the live bank adapter.

The optional frontend factory runs Gloria under existing admission and session
checks. It has not qualified the join to the protected banking conversation and
portal action routes. The isolated runner forces portal actions off.

`resources/gloria_workflow.flow.json` is a source-only four-node generic FLUJO
bridge (Start/Process/MCP/Finish). Its manifest names 21 logical application
stages and eight interpretation/generation stages. The build uses immutable
compiler/schema/validator blobs from the permitted FLUJO revision
`0ba62296520a505e6d71eddf5aa650691f3dc311`; it records protected source hashes
and rejects stale builds. These are not 21 installed FLUJO node handlers.
`tool.py` supplies a per-turn `gloria_run_turn` MCP tool whose closure fixes
host identity and the exact original user message. No shared worker graph,
model binding or bank MCP registration was changed or activated.

## Reproduction

Install `requirements-gloria.txt` in an isolated environment. It combines the
frontend, pipeline and S3 dependencies with MCP 1.30.0 and timezone data.

```powershell
python -m pytest tests/test_gloria_prompts.py tests/test_gloria_response.py tests/test_gloria_policy.py tests/test_gloria_policy_review.py tests/test_gloria_state.py tests/test_gloria_acceptance.py tests/test_gloria_host.py tests/test_gloria_prior_receipts.py -q
node scripts/build_gloria_graph.mjs --flujo-root C:/Users/Moe/Documents/GitHub/FLUJO
node scripts/build_gloria_graph.mjs --flujo-root C:/Users/Moe/Documents/GitHub/FLUJO --check
python -m pytest tests/test_gloria_graph.py -q
python scripts/qualify_gloria.py --model 'model-GPT-6 Luna' --output '<independent-path>/real-workflow-smoke.json'
```

The real-model qualifier uses invented messages and complete synthetic reads;
it cannot execute bank writes. It records source hashes before and after,
intent/slots, response mode/language, stage traces, latency and provider token
usage. Four development smoke cases are not held-out accuracy evidence.
Provider cost is unknown. `docs/GLORIA_ACCEPTANCE.md` describes independently
authored boundary cases and source-bound execution evidence.

For a separate local app instance, use an existing private frontend admission
configuration and `scripts/run_gloria.py --state-dir '<independent-path>'
--model 'model-GPT-6 Luna'`. The state directory must be independent of the
configured active state. Use a separate browser profile to avoid session cookie
interference with another localhost instance. This runner has not been launched
as part of the checkpoint.

## Work required before activation

Qualify complete owned banking source/history/duplicate/risk reads, enforce all
supported extraction filters, and join the admitted Gloria conversation to the
protected host action/receipt lineage. Qualify the per-turn MCP registration
and saved bridge in an isolated native FLUJO execution before changing any
shared worker binding. Implement independently scoped multi-query execution;
the current workflow fails closed when decomposition finds multiple queries.
Then run independent ES/PT semantic adjudication and a joined session/action
test against the frozen release, with any model/provider cost measured.

The 60-minute iteration is a source checkpoint. The complete deployed objective
remains unfinished and the supervisor pauses at the agreed deadline.

## Frozen qualification

Core source is committed at `6bee817dc74d414153cd714c9f6b4a7f2ca3e06e`;
the generated bridge is committed at `2aa64e1`. Documentation and qualification
reports added afterward do not change protected executable source.

| Checks | Result |
| --- | --- |
| Prompts, responses, policy, state, independent acceptance and host integration | 508 passed in 10.36 seconds |
| Banking MCP, case/handoff receipt/schema, owned projection and prior receipts | 161 passed in 61.82 seconds |
| Existing frontend chat/history/revocation/action evidence | 99 passed plus 19 subtests in 16.03 seconds |
| Source-only graph compiler/schema/hash qualification | 10 passed in 26.58 seconds; build check passed |
| Independent acceptance alone, with unchanged source hashes | 91 passed in 2.45 seconds |

The first four rows are disjoint: 778 checks and 19 subtests. The separate
91-case row is included in the core total. The original dirty checkouts and
remote hackathon main at `29543041b1b2462483502ca8e8d6620be530335a` were preserved.

The frozen real configured-model run passed four synthetic expected mode and
language cases: ES dispute, PT dispute, PT active misuse, and ES human request.
Intent/amount/currency/merchant and yesterday's event date agree with the two
invented dispute fixtures. Handoff responses explicitly say creation is
unconfirmed, and neither assistance case made bank reads. Source hashes were
identical before and after. Latencies were 28.058, 35.128, 61.425 and 31.424
seconds. The PT emergency recovered a slot-extraction timeout; these are
development routing observations, not a clean-stage or speed claim.

Independent read-only semantic review agreed with the four modes, languages
and dispute facts, and found no invented receipt or completed-action claim.
It also found unsourced conditional card-blocking advice in the PT emergency
reply: the advice is absent from the reviewed synthetic policy chunks.
The textual validator allowed it. Recommendation grounding therefore remains
a known gap and must be qualified before a complete grounded-response claim.

The 25 returned model calls report 371,171 prompt tokens and 1,257 completion
tokens in total. The timed-out call has no captured provider usage. Cost remains
unknown; latency and prompt size require investigation before activation.
The report is `docs/qualification/gloria-real-model-2026-10-01.json` and the
independent source capture is `gloria-acceptance-2026-10-01.json` beside it.

Execution graph hash:
`c61410b09a88ca43a175f7111b9200ccf9bf557976750781321301b8ec1ec5ac`.
Its metadata retains `installed=false`, `actionsEnabled=false` and example
bindings. Regenerate the artifact in the target checkout before qualification;
its file hashes identify the source bytes actually checked.
