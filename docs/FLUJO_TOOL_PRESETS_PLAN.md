# Banking integration through FLUJO's existing tool presets

> **Superseded September 28:** [the coordinated next implementation plan](BANKING_MCP_NEXT_STEPS.md)
> keeps presets optional. Customer credentials must not be placed in flow snapshots
> or preset values: those structures are persisted. Use private runtime authority
> and the existing fresh per-call assertion instead. The proposal below records the
> earlier review direction.

September 28, 2026. This corrects the integration direction in the earlier banking
review. The banking adaptation below is a proposal, not a deployed feature.

## Use the feature FLUJO already has

An MCP tool can declare `customer_id`. FLUJO's existing parameter presets remove
fixed fields from the model's schema and overwrite attempted model values before
dispatch. Both the ordinary API-provider loop and the Codex/Claude adapters use
this mechanism. `@conversation.id` can supply the current conversation ID.

The earlier review identified a specific defect: Static calls skipped presets and
left dynamic references literal. That called for fixing Static dispatch. It did not
justify replacing the existing chat entry point with banking-specific routes.

## One flow, two understandable modes

| Mode | Customer parameter | Expected behavior |
| --- | --- | --- |
| Private operator test | Preset disabled; parameter visible | In existing chat or Slack, ask for an allowed test customer. |
| Bound customer run | Server supplies a fixed, hidden preset | The model cannot select or switch the customer. |

An enabled preset containing `""` still overwrites the argument. Disable the preset
to let the model supply it. An empty identity in a bound customer run must be denied.
Test access must be an explicit server configuration limited to approved test
customers; a missing identity must never silently enable it on the real server.

The current MCP has no customer selector and its synthetic demo fixes one customer.
Adapting that tool contract is necessary before the selectable test works. Keep the
existing FLUJO chat UI, Slack team thread, completion endpoint, and in-worker stdio
server. No Slack identity extension is needed for the private operator test.

## Customer runs and concurrency

The authenticated frontend resolves the customer and supplies the fixed parameters
in a private flow snapshot for that execution. Use FLUJO's existing template and
execution machinery. Do not update a shared saved flow or server configuration
between requests. One shared MCP process can serve concurrent calls with separate
arguments. A per-run in-memory copy avoids creating 500 servers or permanent flows.

Hidden fields control execution; the MCP must still verify authorization. A signed
or opaque customer binding can itself be a hidden preset parameter. It must bind
the customer and conversation, expire, and be checked by the MCP before lookup.
Reuse the existing verifier, session checks, and transaction ownership checks. A
browser or model-supplied customer ID alone is insufficient. The customer frontend
must also enforce conversation ownership and keep FLUJO's administrative APIs private.

This lets the frontend use the normal completion path and the normal tool contract.
It does not require the chat UI or Slack user to manufacture secret `_meta` values.
The precise binding adapter still needs implementation and verification. Do not
replace the currently enforced real-data checks before that adapter passes.

## Order of work and proof

The foundation fix is committed in FLUJO PR #528: `1b30dce2` repairs Static
presets/references; `8781fa99` adds the explicit `@current` namespace and fixes
entity picker routing. The reference/adapter suites passed 130 tests, including
actual Process preparation for both chat and Slack-style conversation IDs; the
banking regressions passed 45 tests. TypeScript, lint, and a Linux production build
passed. These checks do not establish that the selectable banking test is implemented.

Use `@current.conversation.id` and `@current.flow.id` in new flows. Current commands
do not open an entity hitlist. `@conversation` and `@flow` remain entity pickers;
existing saved references retain their resolution semantics. A proposed next step
is `@_meta.customer_id` in hidden presets, backed by private per-run metadata. That
metadata source and resolver are not implemented by this foundation fix.

1. Fix Static dynamic references and presets. Verify JSON quoting, node/server
   precedence, forged argument replacement, hidden values excluded from model
   history, separate concurrent conversation IDs, and configuration failure denial.
2. Verify the Codex bridge used by Slack hides fixed fields and overwrites forged
   values. Mocked SDK tests prove dispatch behavior, not a live Slack conversation.
3. Add the MCP's explicit selectable test contract. Exercise the existing graphical
   flow from both existing chat and Slack: select test A, select test B, fix A as a
   preset, then request B and verify only A's records are returned.
4. Integrate the authenticated frontend's per-run binding. Test forged IDs, foreign
   conversations, expired bindings and overlapping customer runs through the same
   completion path. The existing 500-subject Static test is useful backend evidence;
   it does not prove the new integration or provider latency.

Do not create temporary customer flows as part of this review. The immediate work
is the demonstrated FLUJO foundation defect; the banking adaptation follows it.
