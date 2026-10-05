# Savia's core: the deterministic transaction dispute engine

**The dispute engine is the product foundation.** Voice makes it conversational;
specialist investigation adds perspectives. The complete transaction workflow
exists independently of either enhancement: authenticate, interpret a request,
resolve owned evidence, apply ordered policy, clarify uncertainty, obtain explicit
consent, execute a permitted simulated action, verify its receipt, retain state,
and prepare a useful human handoff when needed.

Gloria designed the prompt flow and **R0–R18 decision motor: nineteen ordered
rule identifiers**. Carlos prepared its data plane and learned routing diagnostic.
The application implementation turns that design into an inspectable state machine
with durable recovery and response validation. Language interpretation and prose
generation may use models; **policy and action authority are deterministic**.

## One workflow, from the first question to a verified next step

| Stage | Customer outcome | Implemented responsibility |
| --- | --- | --- |
| Authenticate and bind context | The assistant can use only this customer's facts | Host session, ownership checks, query-scoped state and admission fences |
| Interpret and clarify | Missing date, amount, currency or selection becomes a concrete question | Executable prompts, slot/context handling, candidate snapshots and bounded clarification |
| Apply policy | A traceable rule decides whether to inform, confirm, decline or hand off | Pure ordered decision engine and versioned synthetic policy configuration |
| Obtain consent | The customer sees and explicitly confirms the proposed action | Host-issued consent bound to owner, session, conversation, target and snapshot |
| Execute and verify | A success message follows an independently read-back receipt | Banking MCP simulated ledger, signed admission, idempotency and receipt matching |
| Recover or escalate | A restart or uncertain result preserves the next safe step | Durable query/action state, original-operation recovery, revocation and verified handoff |
| Respond and retain | Facts, receipt identity and useful context survive the conversation | Grounding guards, bounded repair, deterministic fallback and persisted history |

## The R0–R18 decision inventory

The [normative policy contract](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/contracts/policy_engine.md) contains detailed
precedence and guard semantics. The [implemented engine](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/policy.py)
performs no bank I/O: its transitions are instructions for the trusted runtime,
not capabilities that grant permission.

| Rule | Decision boundary |
| --- | --- |
| R0 | Authentication required; no tools for unauthenticated or expired sessions |
| R1 | Block deceptive or inappropriate attack input |
| R2 | Block references to another customer's data |
| R3 | Consume a host-verified explicit confirmation, revalidate guards, execute and verify; preserve uncertainty if verification fails |
| R4 | Cancel a denied pending action |
| R5 | Continue from a valid owned selection of the displayed candidate snapshot |
| R6 | Handle greeting and personality requests without banking actions |
| R7 | Explain an out-of-scope request |
| R8 | Honor a human request or emergency with a handoff path |
| R9 | Bound tool retries and escalate repeated failures |
| R10 | Clarify missing search criteria and ambiguous currency |
| R11 | Explain no match and escalate repeated unsuccessful searches |
| R12 | Clarify multiple candidates or refer persistent duplicate evidence for review |
| R13 | Explain an owned transaction inquiry; inconsistent future dates require review |
| R14 | Enforce dispute date/status eligibility and handle missing evidence |
| R15 | Explain an existing linked open case without creating a duplicate |
| R16 | Hand off verified high-risk disputes; incomplete risk evidence cannot become a zero-risk assumption |
| R17 | Propose an eligible action only after the preceding guards pass; request explicit confirmation |
| R18 | Resolve complaint-status requests over owned complaint records |

This is team-authored **synthetic hackathon policy**, not a claim of any bank's
real policy or regulatory certification. The evidence distinguishes an
informational answer, a simulated intake receipt, a saved handoff, and a resolved
real bank dispute.

## Inspect the implementation and its checks

| Responsibility | Source and executable evidence |
| --- | --- |
| Ordered policy and query isolation | [policy.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/policy.py), [policy tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_policy.py), [query-policy tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_query_policy.py) |
| End-to-end runtime | [runtime.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/runtime.py), [independent acceptance](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_acceptance.py), [multi-query checks](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_multi_query.py) |
| Owned reads and selection | [bank_read.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/bank_read.py), [bank-read tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_bank_read.py), [source-read checks](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_source_reads.py) |
| Consent, action and replay | [action_host.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/action_host.py), [action-host tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_action_host.py), [prior-receipt tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_prior_receipts.py) |
| Response grounding and safe fallback | [response.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/response.py), [response tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_response.py) |
| Durable state and handoff | [state.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/state.py), [handoff.py](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/dispute_workflow/handoff.py), [state tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_state.py), [handoff tests](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/tests/test_dispute_handoff.py) |

The combined workflow/host/frontend source qualification at `ea8f6217` records
**1,725 passing tests and 428 passing subtests**, with exact protected source
hashes. This is historical combined-source qualification, not a claim that every
test belongs solely to the policy module or that later images inherited the
result. [Original receipt](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/qualification/dispute-naming-source-2026-10-01.json).

The [implementation report](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/DISPUTE_IMPLEMENTATION.md) also preserves installed
native execution, provider and joined HTTP evidence at their own revisions.
The [current release report](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/RELEASE_CANDIDATE.md) identifies deployed customer
recordings. The [evidence map](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/EVIDENCE_MAP.md) connects current public replay and
additional checks to their source identities.

## Reproduce the core without a provider

After installing the isolated dispute dependencies, run this bounded source
check from the repository root. Its test doubles use fictional data and inspect
policy, consent, response guards and recovery; it makes no paid provider calls.

```powershell
python -m pip install -r requirements-dispute.txt
python -m pytest -q tests/test_dispute_policy.py tests/test_dispute_query_policy.py tests/test_dispute_acceptance.py tests/test_dispute_action_host.py tests/test_dispute_bank_read.py tests/test_dispute_prior_receipts.py tests/test_dispute_response.py tests/test_dispute_state.py tests/test_dispute_handoff.py
```

For the broader joined source suite, use `python scripts/test_dispute.py` in the
documented [isolated dependency setup](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/LOCAL_CI.md). Historical qualification
and a new local replay each retain their own revision and execution boundary.

## Why the architecture expands

The engine owns the banking application contract. A different voice, model,
reviewer team or deployment can sit above the same consent and receipt boundary.
FLUJO retains its general-purpose chat, flow, tool, MCP and execution interfaces;
banking source stays in this repository, Banking MCP, or the separately authorized
hackathon branch. This preserves a long-lived platform while delivering a complete,
focused application. [Product boundary](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/FLUJO_PRODUCT_BOUNDARY.md).

---

[Public source document](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/blob/main/docs/submission/DISPUTE_ENGINE.md)
