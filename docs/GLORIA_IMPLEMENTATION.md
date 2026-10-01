# Gloria release candidate

Gloria implements the authenticated Spanish/Portuguese unrecognized-charge
journey: executable interpretation prompts, emotion/language detection, ordered
R0–R18 decisions, owned source reads, scoped clarification, explicit simulated
intake, durable receipt recovery and human handoff. Release qualification is in
progress; the historical checkpoint below is preserved as earlier evidence.

## Application and authority

`runtime.py` coordinates validated language stages and deterministic policy.
A single human message can create up to eight independent query capsules with
separate facts, snapshots, pending requests, history and receipts. Every scope
is checked for foreign-customer references before any bank read. Original
message digests include trusted selection and the chosen query scope. Completed
responses are reread before replay, including inactive query results.

`state.py` persists exact owner/customer/session/conversation bindings, query
capsules, request lineage and immutable turn inputs. Consent is never restored
as live authorization. Pending lifetime is checked on load as well as save;
expired or rejected prepared requests are cancelled by the trusted host, while
attempted or uncertain writes retain receipt recovery.

`bank_read.py` uses the existing banking `Service`, source verification and
sandbox ledger. It implements all declared transaction filters, complete
counts, owned product suffixes, profile/history reads and nearby duplicate
signals. Historical complaints remain separate with unknown transaction linkage.
Missing source coverage cannot establish uniqueness or absence. Currency risk
uses a pinned rate for the exact event date/currency; absent or invalid rates
leave risk incomplete. Exact USD amounts require no conversion. Raw identity,
source records and internal risk stay outside language model inputs.

The frontend admits the conversation before private reads and retains its
existing transcript/session fences. Browser request scopes are opaque selectors
verified against the owned registry. `action_host.py` connects explicit portal
controls to the same authoritative banking ledger used by the inquiry. It
rereads source/risk at preparation and confirmation. A chat reply cannot execute
intake. Confirmation is bound to the owner, session, conversation, query, target,
snapshot and durable request handle; receipt readback determines success.

`response.py` checks canonical response schema, facts, action claims and
recommendation support. One bounded repair precedes an ES/PT fallback. Each
query is grounded independently before its exact message is composed; facts
are never pooled into a new model prompt. These conservative text checks do
not establish arbitrary semantic understanding or human adjudication.

## Native execution

The saved generic four-node FLUJO bridge uses immutable compiler/schema blobs
from the permitted revision `0ba62296520a505e6d71eddf5aa650691f3dc311`.
Its manifest records the application, prompts, policy and native authority source
hashes. The 21 logical stages belong to the application; they are not 21 native
FLUJO node handlers. The per-turn MCP closure binds the original message and
trusted selection outside the message-only model tool schema.

`scripts/native_gloria_qualification.py` supplies `NativeGloriaPort`. Every
language call traverses an ephemeral protected native flow with an attested
CLI/catalog and capability restrictions. The host displays its validated
application result directly. The separately captured MCP projection is checked
independently of any model relay. Native installation, forced capability probes,
real provider behavior and joined application outcomes have separate evidence.
Shared workers, generic FLUJO main and active banking deployments are preserved.

Preflight batching is an explicit same-turn option. It combines only rewrite,
attack and context contracts for the same original message/history and validates
each output separately. It is neither cross-customer pooling nor physical
isolation of those three model instructions. Provider observations include
latency, input/output/cache usage and unknown usage on failures; cost is unknown
unless a configured price is actually available.

## Reproduction

Install `requirements-gloria.txt` in a fresh environment, then run:

```powershell
python -m pip check
python scripts/test_gloria.py
npm ci --ignore-scripts --prefix frontend
npm test --prefix frontend
npm run build --prefix frontend
node scripts/build_gloria_graph.mjs --flujo-root '<permitted-source-checkout>'
node scripts/build_gloria_graph.mjs --flujo-root '<permitted-source-checkout>' --check
```

The native qualification driver builds/runs a disposable isolated worker with
private authority and login mounts. It verifies installed source bytes against
the requested manifest and exercises admission, replay, restart, poisoning and
provider boundaries. A successful worker may be retained for joined qualification.

For an independent admitted application, use private frontend and bank
configuration with the same dataset/customer mapping and a separate state/ledger:

```powershell
python scripts/run_gloria.py --state-dir '<independent-state>' --bank-config-file '<private-bank-config>' --native-url 'http://127.0.0.1:<isolated-port>' --native-authority-dir '<isolated-authority>' --source-root '<generated-source>' --enable-simulated-intake
```

The existing sandbox coverage attestation is never fabricated by this runner.
Use a separate browser profile to avoid cookie interference. `--batch-preflight`
remains opt-in pending same-fixture real-provider comparison. Source tests and
synthetic smoke outcomes do not replace independent human-labelled holdout,
shared deployment acceptance or authorization to merge/activate the candidate.

## First checkpoint (historical)

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
