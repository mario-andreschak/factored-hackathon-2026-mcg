# Agent analytics (offline)

Builds a separate, metadata-only SQLite database for tracing Savia transaction dispute workflow
behaviour over time: what the customer wanted, how the policy decided, where
the agent struggled, and how long each stage took. A separate current host
snapshot reports saved verified simulated intake and human review requests.

Gloria Yanta Salc designed the transaction dispute prompts.

It reads the operational state **read-only** and changes neither the chat
service, the transaction dispute workflow, the banking MCP nor FLUJO.

```powershell
python -m analytics build  --state-dir <BANKING_STATE_DIR> --out <dir>\agent-analytics.sqlite3
python -m analytics report --db <dir>\agent-analytics.sqlite3          # or --json
python -m analytics feedback --db <dir>\agent-analytics.sqlite3 --turn <turn_id> --rating -1 --label intent_incorrect
```

`--state-dir` finds every `*.sqlite3` that holds current `dispute_turns`
(e.g. `dispute-workflow.sqlite3`), legacy `gloria_turns`, or `chat_messages`
(e.g. `frontend-chat.sqlite3`). When both workflow tables exist in one file,
the current table is read. Explicit `--workflow-db`/`--chat-db` are also
accepted. `build` rebuilds the derived tables each run; `feedback` rows are
kept.

## Tables

| Table | Grain | Content |
| --- | --- | --- |
| `turns` | One customer turn | Intent, language, emotional context, attack flags, names of supplied slots, clarification, pending state, policy `response_mode`/`rule_ids`/`reason_code`, transaction identification, action and handoff outcome, counters, grounding/fallback flags, node error codes, message sizes |
| `node_calls` | One workflow node in a turn | Model stage, bank tool, policy retrieval or barrier; latency, attempts, status, error code |
| `conversations` | One conversation | Turn count, intents, languages, outcome, handoff reason, turns to identify the transaction, clarify turns |
| `feedback` | A judgement | Customer or reviewer rating (-1/0/1) and short label, by turn or conversation |
| `host_sources` | One input chat database | Supported schema and rejected binding coverage; HMAC source reference |
| `host_sessions` | One immutable owner/session/expiry admission | Pseudonymous customer/session, expiry, local revocation and saved outbox state |
| `host_actions` | Latest saved action slot for an admission | Checked host outcome, persistence/receipt times, prior-evidence flags and recovery metadata |
| `host_cancellations` | One retained denied handle | HMAC reference and cancellation time, bound to its admission |

`turn_id` equals the chat `operation`, so a reviewer with access to the
operational store can open the exact transcript of a flagged turn.

Conversation `outcome` values: `action_verified`, `handoff`,
`handoff_required` (needed but not created by the host),
`awaiting_confirmation` (chat ended at the portal consent step),
`abandoned_pending` (left while choosing a candidate), `abandoned_clarify`,
`no_match`, `out_of_scope`, `out_of_policy`, `tool_error`,
`action_unverified`, `cancelled`, `blocked`, `informed`, `transcript_only`
(chat without transaction dispute workflow state) and `other`.

Portal confirmation and handoff creation happen in the trusted host. Workflow
conversation `outcome` remains the saved workflow observation; it is not
promoted by a later host result. The report's `current_host_snapshot` reads
`action_status` together with `chat_sessions` in a read-only transaction and
requires the same session, owner and immutable expiry. It uses the host's
existing receipt/handoff projector and checks terminal shape, contradictory
facts and timestamps. Foreign or absent admissions are excluded with coverage
counts. A malformed verified claim becomes `invalid_evidence`.

Host outcomes distinguish `verified_simulated_intake`,
`verified_existing_simulated_intake` (an existing receipt, not a new intake),
`verified_handoff_request`, pending preparation/confirmation and unverified
states. Prior receipts and nested/prior handoffs never complete the current
slot. A handoff proves a saved request; it does not prove a human response.
Recovery is counted as completion only once a host readback has persisted a
verified result. The extractor never invokes recovery or reads the live bank.

The denominator is **current action slots**, with admitted session, rejected
source-row and unsupported-schema counts reported separately. This is not an
attempt rate or a lifetime action ledger: a newer reservation replaces the
session's old slot. Identical source copies and rebuilds count a slot once;
disagreeing copies become `conflicting_snapshot` and cannot count as verified.
Revocation/expiry do not erase an earlier verified receipt. Local denial,
pending/confirmed/expired-unconfirmed revocation and retained cancelled handles
are reported separately. Missing cancellation/outbox schemas are explicitly
unavailable, rather than evidence of zero events.

`built_at` is extraction time. `action_updated_*` bounds the current slot's last
persistence, including recovery, while `verified_record_created_*` bounds the
saved receipt/request time. These are observed coverage bounds, not a cohort
window, action latency or customer-resolution time. Schema 2 adds these tables
on rebuild and preserves feedback; reports of schema 1 remain usable and mark
host evidence unavailable until rebuilt.

Exact workflow turn/query attribution remains unknown. The current direct host
keeps bank context separate from language conversations and clears its prepare
conversation after completion. Even native legacy stores require additional
explicit conversation/query/target/request linkage. This report does not infer
that linkage from timestamps or the session's latest conversation. Simulated
receipts establish no real bank resolution, refund, production acceptance or ROI.

## Privacy

- No message text, slot values, amounts, merchants, transaction, complaint,
  handoff or receipt identifiers are copied. Only field names, categories,
  flags, counts and durations.
- Customer and session identifiers become HMAC pseudonyms. The key is written
  beside the output as `<out>.key` (or `--key`) and never into the database.
  Keep the key with the same access controls as the operational state.
- New host tables also pseudonymize admission, source and cancellation keys.
  They copy no action/request IDs, handles, targets, snapshots, receipt IDs,
  private questions, facts, owner/subject or error text.
- Build the output inside the same isolated deployment volume as its sources;
  invite-mode and organizer-snapshot data must not share an analytics file.

## Limits

- `node_latency_ms` sums node durations; parallel nodes overlap, so it is work
  time, not wall-clock latency.
- Model token usage and cost are not persisted by the workflow today
  (`model.observations` is in memory only), so they are not available here.
- The operational stores have no retention; the analytics file is rebuilt from
  whatever they still hold.
- Host snapshots cover intake/handoff `action_status`; separate card-block
  receipts and the banking ledger's lifetime history are not joined here.
