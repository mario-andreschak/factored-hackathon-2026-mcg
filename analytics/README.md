# Agent analytics (offline)

Builds a separate, metadata-only SQLite database for tracing Savia transaction dispute workflow
behaviour over time: what the customer wanted, how the policy decided, whether
the case was resolved or handed off, where the agent struggled, and how long
each stage took.

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

`turn_id` equals the chat `operation`, so a reviewer with access to the
operational store can open the exact transcript of a flagged turn.

Conversation `outcome` values: `action_verified`, `handoff`,
`handoff_required` (needed but not created by the host),
`awaiting_confirmation` (chat ended at the portal consent step),
`abandoned_pending` (left while choosing a candidate), `abandoned_clarify`,
`no_match`, `out_of_scope`, `out_of_policy`, `tool_error`,
`action_unverified`, `cancelled`, `blocked`, `informed`, `transcript_only`
(chat without transaction dispute workflow state) and `other`.

Portal confirmation and handoff creation happen in the trusted host
(`action_status` and the banking MCP), not in the workflow store, so
`awaiting_confirmation` and `handoff_required` do not say whether the host
later completed them.

## Privacy

- No message text, slot values, amounts, merchants, transaction, complaint,
  handoff or receipt identifiers are copied. Only field names, categories,
  flags, counts and durations.
- Customer and session identifiers become HMAC pseudonyms. The key is written
  beside the output as `<out>.key` (or `--key`) and never into the database.
  Keep the key with the same access controls as the operational state.
- Build the output inside the same isolated deployment volume as its sources;
  invite-mode and organizer-snapshot data must not share an analytics file.

## Limits

- `node_latency_ms` sums node durations; parallel nodes overlap, so it is work
  time, not wall-clock latency.
- Model token usage and cost are not persisted by the workflow today
  (`model.observations` is in memory only), so they are not available here.
- The operational stores have no retention; the analytics file is rebuilt from
  whatever they still hold.
