# Customer-v0 language flow source

This source artifact contains **Start → Process → Finish**: three nodes and two
edges. Process chooses a bounded language-guidance value. The project host
validates that value and renders deterministic Spanish or Portuguese text.
The internal Finish control ends the flow; it does not transfer to a person.

The graph has no banking MCP node, server binding, banking tool, customer selector,
credential, opaque handle or action authority. Authentication, owned data reads,
consent, receipts and human-request status belong to the project host and interface.

The committed graph uses the placeholder model ID `existing-model-id`. Its
validation catalog is declared by the builder. Neither the graph nor its default
binding proves that a model is configured, installed or usable in a running FLUJO.
No model or runtime acceptance is established by these source checks.

## Files

| File | Purpose |
| --- | --- |
| `../../resources/prompts/customer_v0.md` | Canonical `Customer-v0-language-only/2.0.0` instructions |
| `provenance.json` | Two historical prompt-source hashes and the current adaptations |
| `build.cjs` | Pure compiler, snapshot schema, graph-boundary and hash checks |
| `generated/flow-spec.json` | Three-node FlowSpec with the exact prompt embedded |
| `generated/compiled-flow.json` | Source Flow shape with only a public model binding |
| `generated/manifest.json` | Contract, source, toolchain and generated-byte hashes |
| `builder.test.cjs` | Determinism, hash and forbidden-capability mutation checks |

## Language contract

The latest request is a `host-language-request/v1` JSON object with exactly
`schema`, `language`, `request` and `display_facts`. Language is `es` or `pt`.
The project host supplies bounded sanitized request text and either no display
facts or exactly these fields: `event_date`, `amount`, `currency`, `merchant`
and `recorded_status`. Merchant may be null. Recorded status describes the
displayed transaction; it is not a receipt or action state.

Customer and merchant text remain untrusted data. The language projection
contains no private identities, keys, bank assertions or selection handles.

Output is exactly three fields, with no prose or additional fields:

```json
{"schema":"host-language-guidance/v1","language":"es","guidance":"ask_selection"}
```

The allowed guidance values are `explain_selected`, `ask_date_or_amount`,
`ask_selection`, `suggest_human` and `unavailable`. The host owns response
validation and localized rendering. A guidance value does not authorize an action
or establish a ledger change, receipt, human pickup or successful transfer.
Malformed or free-form model output must receive the host's safe fallback.

## Pure source checks

Use Node 22.13 or later and a FLUJO checkout whose HEAD is exactly
`3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9`. The restored source tree is
`780c2cf42266f8e55ff1917c137b196ee97df959`.
The builder reads exact Git blobs, rather than modified working files.
Only the ordinary compiler, snapshot schema, validator and hash modules are
loaded; no banking integration or authority module is extracted or evaluated.

With the builder's pinned dependencies already available, run:

```powershell
cd demo/customer_v0
node build.cjs --flujo-root C:/path/to/FLUJO --check
$env:FLUJO_SOURCE_ROOT = 'C:/path/to/FLUJO'
node --test builder.test.cjs
```

To produce a separate source artifact for an existing public model ID:

```powershell
node build.cjs --flujo-root C:/path/to/FLUJO --model-id actual-configured-model-id --out C:/path/to/private-source/customer-v0
```

Model ID is the only binding input. The removed `--bank-server` option is rejected.
These commands emit or check source JSON; they do not install a graph, resolve a
live configured model, call a provider or exercise banking authorization.

The two provenance blobs are historical ES/PT wording and consent-boundary
sources from project commit `33a07442bca62fdd438472610285dd8c427241e0`.
They are not the current tool, transport or authentication contract. When that
commit is available in the project's Git object store, audit them with:

```powershell
node build.cjs --audit-provenance
```

The customer-flow CI job is configured for these source checks on Windows and
Linux. Source compilation and mutation checks do not prove provider behavior,
SDK confinement, customer isolation, action correctness or capacity.

## Saved graph provenance

Any later installation remains a separate owner-controlled step. Saving changes
metadata and the execution hash. The source example's hash is not proof of the
live saved graph, its model binding or the worker running it.

The checker can validate an independently supplied saved Flow file:

```powershell
node build.cjs --flujo-root C:/path/to/FLUJO --saved-flow C:/path/to/private-source/saved-flow.json --model-id actual-configured-model-id
```

It checks that file without writing it or reading a running FLUJO. The graph name
is `banking_customer_v0`; the reported generic completion model selector is
`flow-banking_customer_v0`. The Process model ID is a separate binding. These
declared values are configuration provenance, not proof of a live graph or model.

Prompt changes require a version and provenance update plus regenerated source
artifacts. Keep the former package and PR28 evidence as historical artifacts;
this language source does not repin or validate them.
