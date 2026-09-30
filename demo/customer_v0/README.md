# Customer-v0 flow artifact

This is a reproducible **source artifact**, ready for graph review. It has not been
installed, run with a model or tested against a live MCP.

It compiles Start → Process → Finish, with one banking MCP attached to Process.
The model receives the three banking reads and FLUJO's internal Finish routing
control tool. No banking action is a model tool.

## Files

| File | Purpose |
| --- | --- |
| `../../resources/prompts/customer_v0.md` | Canonical versioned ES/PT instructions for reviewing one owned charge |
| `provenance.json` | Exact source commits and Git-blob SHA-256s; adaptations from Gloria's PR12 |
| `build.cjs` | Source-only compiler, schema, graph and hash checks |
| `generated/flow-spec.json` | FlowSpec with the prompt embedded |
| `generated/compiled-flow.json` | Importable Flow shape with explicit empty resource/prompt/skill lists |
| `generated/manifest.json` | Input, toolchain, source and generated artifact hashes |
| `builder.test.cjs` | Determinism, hash and forbidden-capability checks |

The committed example uses placeholder binding IDs. Its validation catalog is
declared by the builder; it is **not evidence that a model or server is configured**.
Use the existing configured model and banking stdio registration when preparing
an installation artifact.

## Generate and check

Use Node 22.13 or later and a FLUJO checkout whose HEAD is exactly
`3037c1423f7d39ede4d4a9b50afae038e4dd7baa`. FLUJO does not need to be running and
its dependencies do not need to be installed. Commands below work in PowerShell;
replace the public binding placeholders and checkout path.

```powershell
cd demo/customer_v0
npm ci --ignore-scripts
node build.cjs --flujo-root C:/path/to/FLUJO --check
$env:FLUJO_SOURCE_ROOT = 'C:/path/to/FLUJO'
npm test
```

To generate with real binding IDs, use a separate output directory:

```powershell
node build.cjs --flujo-root C:/path/to/FLUJO --model-id existing-model-id-from-FLUJO --bank-server existing-registered-bank-name --out C:/path/to/private-release/customer-v0
```

Use only public model IDs/server names here. Credentials and identity authority
are supplied by the existing protected runtime; they are not builder inputs.
No customer/conversation presets or `_meta` values are embedded in this graph.

The loader reads exact **Git blob bytes** from the pinned commit. Local working
file edits and Windows line-ending conversion cannot change loaded FLUJO code.
It calls the actual compiler, `FlowSnapshotSchema.parse`, `validateFlow`,
`hashFlowExecutionSnapshot` and `createFlowExecutionSnapshot` in tests.

The banking graph check executes the unchanged exported `assertBankingGraph`
function and `BankingError` class in isolation, with the actual hash function and
tool names derived from the pinned authority AST. It omits production authority
imports, which would load workspace, policy, storage and process modules.
The manifest states this limitation and records full-file and extracted-body
hashes. This is not a production module or authentication test.

To audit all fourteen prompt provenance blobs, make the three banking commits available
in this repo's Git object store, then run:

```powershell
git fetch origin 974f92787f84fc65ae425f693f79213f82b513f6 f07cadf3dd75a20ec945cd22ed4dd4a6b4b6d344 2cf54ae5dd8bddfb875903ed61150a2b29853abe
node build.cjs --audit-provenance
```

CI repeats these source checks on Windows and Linux. It does not start FLUJO,
call a provider, dispatch MCP tools or alter a policy.

## Prompt scope

The fragment preserves Gloria's ES/PT style and grounding, adapted to the tools
available in this customer graph:

- List by **event date**, at most 90 inclusive dates within verified snapshot bounds; disclose the historical interval and anchor, preserve explicit dates and source calendar semantics.
- Treat frontend-selected display facts as user data. They are not MCP handles.
- Use a list-returned selection handle and successfully re-read before explaining.
- Keep pagination, missing merchant and pending/reversed status limitations visible.
- Leave explicit consent for the saved named charge and verified CMP/HOF wording to the UI/host action result; chat “sí”/“sim” does not authorize an action.
- Describe exact owned `get_my_transaction.existing_case` receipts and interface-verified receipts as recorded simulations. Keep local absence and uncertainty scoped; preserve the original receipt snapshot and never invent an open/resolved banking dispute.
- Describe saved human-request facts, reason and recorded unanswered questions only from the verified interface packet; do not imply a person joined.
- Keep the search separate from the host's real-time 120-day eligibility policy. The model receives no action or handoff tools.

Backend authorization enforces ownership. These instructions do not replace it.
Changes to the fragment require a new version, updated provenance digest and a
reviewed regenerated artifact.

## Later installation: owner-controlled steps

1. Review the generated artifact and record source commits, prompt version and
   hash, FlowSpec hash and compiled execution hash. Check repeat generation.
2. In the **existing FLUJO graphical editor**, import the prepared compiled Flow
   using its supported import mechanism, or recreate its four nodes and three
   edges. Paste the complete Start and Process prompts from the artifact.
3. Bind the existing configured model and approved banking **stdio** registration
   inside the existing worker. Expose exactly `banking_status`,
   `list_my_transactions` and `get_my_transaction`. Verify resources, prompts and
   skills are explicitly `[]`, not omitted. Leave host action tools unavailable
   to the model. No additional worker, server or container is needed.
4. Finish every edit and save. Read/export the exact authoritative persisted Flow
   through FLUJO's existing inspection mechanism. Keep that raw file private.
5. Validate and hash the supplied saved file with the same pinned source:

   ```powershell
   node build.cjs --flujo-root C:/path/to/FLUJO --saved-flow C:/path/to/private-release/saved-flow.json --model-id actual-configured-model-id --bank-server actual-registered-bank-name
   ```

   This checks the **supplied file**; it does not perform or prove the live read.
   The owner records how it was read, its flow ID and returned graph hash.
6. Approve that final saved ID/hash through the existing private policy procedure.
   The protected frontend's completion `model` must also be exactly
   `flow-` + the **saved Flow name**: FLUJO's banking adapter checks this before
   execution. Installing the new `banking_customer_v0` flow requires
   `flow-banking_customer_v0`; updating the existing `Banking_Customer` graph while
   preserving its name keeps `flow-Banking_Customer`. The builder's configured
   Process model ID is a separate binding. The saved-file checker reports the
   required ingress model but does not update the frontend.
   Check effective worker source, saved Flow, private policy, protected frontend
   model and exact stdio registration together before a customer test.
   Keep host action acceptance and its enablement gate separate.
7. After approval, **any save requires a fresh persisted hash and approval**.
   The hash includes IDs, prompts, model/server bindings, labels, positions,
   favorite/folder and timestamps. Even a no-op save refreshes `updatedAt`.

The generated hash is not the installation policy hash: saving changes metadata.
If the effective worker uses another source revision, this pin is insufficient;
review and repin the builder before approval.

## Later model and runtime evaluation

Use the already configured models. Record the real provider adapter, source
commits, saved graph hash, snapshot build, tool traces and raw ES/PT outputs.

| Scope | Evidence still required |
| --- | --- |
| Installed read path | Existing worker/stdio list → returned handle → successful owned get |
| Isolation | Two authenticated owners; foreign handles/conversations denied; overlapping owned reads |
| Model behavior | Human review of actual ES/PT wording against tool facts, including failures |
| Host actions | Explicit UI consent, actual host route, durable receipt/handoff read-back and retry/recovery |
| Capacity | Separately scoped real provider/MCP run; source tests prove no throughput |

Exercise each model case in both languages:

1. Selected context matches a successful read; mismatch does not become a fabricated match.
2. Event date differs from the partition date; explicit older windows stay within disclosed bounds.
3. Pagination and multiple similar charges require a concrete selection question.
4. Unknown merchant, pending and reversed records remain limited to returned facts.
5. Empty results and tool failures never become a global absence claim.
6. Customer switching and merchant/user injection cannot expand backend authority.
7. Chat "sí"/"sim", action requests and invented CMP/HOF IDs do not become verified actions.
8. Human/emergency requests stop unnecessary selection questions without claiming pickup.
9. Existing-case status comes from the exact owned read or verified interface state; uncertain/absent local evidence never becomes a bank-wide absence claim.
10. Unavailable action controls promise only the review the chat can perform.

Keep denials, timeouts and wording failures in the denominator. Source validation
and authored fixture agreement do not establish live model behavior, isolation,
action correctness or capacity.
