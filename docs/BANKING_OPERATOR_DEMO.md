# Banking operator demo and acceptance

Use one **Banking Operator** graphical flow from existing FLUJO chat and the
existing Slack team channel/thread. It reuses the configured Sol/Luna model,
approved operator banking MCP, and shipped FLUJO ticket tool. No new UI, customer
flows, remote MCP, or second worker is needed. The banking MCP remains a Python
stdio child in the existing container.

## Install one reusable graph

`demo/operator_flow.template.json` is a credential/customer-free FlowSpec;
`demo/flow.py` builds the same spec with selected existing model/server names and
a historical window. `demo/install_operator_flow.py` uses FLUJO's native compiler,
checks actual tool schemas and the bank's `operator-test` status, then adds
nonsecret current-conversation presets. It does not edit MCP configuration,
models, Slack target, the protected smoke flow, or Slack Assistant.

The parent/runtime owner first provisions the explicit private operator
registration with its approved customer allowlist and read-only snapshot. A name
alone does not make a server operator-enabled. Existing real/delegated mode and
fixed-customer Demo are not substitutes for this contract.

Run from the hackathon checkout, using the existing host credential in
`FLUJO_API_TOKEN` only if the local endpoint needs it:

```powershell
.venv/Scripts/python.exe -m demo.install_operator_flow --model "GPT-6 Sol" --bank-server "Banking MCP Operator" --ticket-server "FLUJO" --start-date 2026-06-01 --end-date 2026-06-17
```

This validates and compiles **without saving**. The runtime owner adds `--write`
to save one permanent Banking Operator graph. Subsequent installs update the
same ID, only when its ownership marker matches. Existing unrelated flows are
left alone. The helper fails if the named flow was authored elsewhere; review it
before selecting a different intended name. Compiler synthesis does not create
or save a temporary customer flow or conversation.

The graph enables exactly bank status/list/get and `create_ticket_for_human`.
MCP resource/prompt selections are explicitly empty; an omitted resource selection
would enable the shipped server's unrelated run-resource inventory. Existing
server-wide customer presets are rejected instead of silently hiding the selector.
Bank customer selectors stay visible. `conversation_id` is fixed to
`@current.conversation.id` on both customer tools, so asking to reuse a previous
Slack root's correlation cannot move its handle. Ticket title, labels,
conversation and flow attribution are fixed; ticket message remains model input.
No required secret metadata is supplied by operators. The ordinary completion
path handles both interfaces.

For live acceptance, the runtime owner selects this graph in existing chat and
uses the existing Slack `FlujoClient`/`Bridge` with mocked delivery. That can prove
the actual normal provider/flow path without posting Slack messages or changing
the audience. A real team-thread demo requires separate authorization to post.

## Short operator sequence

Use `demo/operator_cases.json` as the shared chat/Slack workload. Replace
CUSTOMER_A/B from the private approved test oracle at execution time; no private
subject/customer mapping belongs in this document or public artifacts.

1. Choose approved A. List five transactions and inspect one. Compare actual
   records with the independent owner oracle, not the assistant's customer label.
2. Choose approved B in the same **operator** conversation. Verify B results and
   discarded A selection. This intentional multi-customer operator context is
   not customer authentication or isolation evidence.
3. Start a fresh chat and fresh Slack root in the same team channel. If testing
   optional fixed A, bind the fixed selector there and ask for B. Inspect the
   advertised schema and dispatched arguments; expect A or refusal. Do not
   convert the earlier A/B transcript/provider session into a bound session.
4. In a separate root, try A's old handle with its old conversation correlation.
   The preset must overwrite correlation and the bank must reject the handle.
   Unknown customers and missing identity cannot enable an operator fallback.
5. Show normal inquiry, ambiguous selection, and explicit human/security review
   in ES and PT. Persist a local ticket and verify the actual receipt readback.
6. Inject a read failure in the harness. Show a truthful failed/uncertain answer,
   bounded retries, and operator resubmission after inspection. Do not replay an
   uncertain local ticket write.

Pin each scenario to a selected record inside a <=31-process-day window. The
whole-history candidate pool does not guarantee the current window contains the
desired status. Missing merchants remain unknown; date/type/channel,
amount/currency and status are enough for grounded selection. The source's
near-duplicate pool is empty; label any generated duplicate fixture explicitly.
Never use fraud labels/scores or invalid complaint/product joins as customer facts.

## Local handoff and receipt proof

The existing ticket tool writes a **local FLUJO operator ticket**, not a banking
dispute, live-agent acknowledgment, refund, card block, or resolved case. No bank
mutation tools or broader delegated scope were added.

`demo/handoff.py` provides the host's independent expected handoff envelope and
receipt oracle. Build `TransactionEvidence` only from a successful,
host-observed `get_my_transaction` result after bank authorization. Its context
must come from the trusted host/test execution, not model arguments. The helper
does not authenticate these inputs and cannot turn model prose into verified
facts. Copying a transaction object into a model-built ticket is not proof.

After actual `create_ticket_for_human` dispatch, the private host harness reads
the returned ID through `ticketService.getTicket(id)` or the existing local
`/api/tickets/:id` endpoint. `verify_ticket_receipt` checks the persisted ID,
conversation/flow, structured message and exact expected source facts/actions.
Ticket reads are not enabled as a model tool; keep administrative endpoints
private. Missing, foreign, altered or invented facts fail verification. An urgent
human request may have empty transaction evidence instead of delaying escalation.

The NEW FLUJO `bankingOperatorHandoff.test.ts` exercises real internal tool
dispatch, actual ticket service and real isolated on-disk collection, then reads
through a fresh service instance and checks bytes. Unused services and execution
locks are isolated: it is not production locking, bound-owner authorization,
live-provider acceptance, or a full worker restart proof. Existing ticket writes
are **not idempotent**; repeated creation makes another ticket. The graph and
gateway must not automatically retry an uncertain write.

The first ticket demo is **operator-only**. Bound graphs retain bank reads until
the authenticated path independently enforces ticket ownership, selection/fact
provenance, publication and revocation. Do not broaden ticket/resource access to
make a customer demo pass. The optional fixed-A operator test does not satisfy
that gate, even when argument hiding/overwrite works.

## Evaluation and delivery evidence

The diagnostic holdout is independently **AI-authored**, not independently human
reviewed. Both frozen versions/hashes and the single pre-report similarity-screen
correction are in `docs/ml/router_holdout_provenance.md`. Final submission still
needs human adjudication. `demo/evaluate_router.py` compares existing keyword
rules and TF-IDF/logistic regression with fixed C=8/tau=.65 from earlier
training-only CV; it never tunes against the holdout or overwrites existing reports.

```powershell
.venv/Scripts/python.exe -m demo.evaluate_router
.venv/Scripts/python.exe -m pytest -q tests/test_demo_handoff.py tests/test_demo_flow.py tests/test_demo_evaluation.py tests/test_router.py
```

The resulting `docs/demo/intent_router_evaluation.*` reports measure component
labels only. Nonhuman routing is not safe automated resolution. Measure actual
provider/graph outcomes separately: successful verified inquiries, unsupported
requests, missed/unnecessary handoffs, unauthorized outcomes, queue/provider/tool
latency and cost per attempted/successful case, with counts and language mix.

This covers the challenge's grounded workflow, clarification, local handoff,
ES/PT and learned-component comparison. Existing Static 500-subject evidence and
Slack's offline scheduler harness do not prove 500 model chats or a live service
SLA. Provider-capacity, authenticated customer frontend integration, owner/history
and native-capability isolation, source freshness and operational monitoring
remain explicit gates. Organizer records are documented as synthetic; credentials,
private mappings and separately restricted inputs stay private.
