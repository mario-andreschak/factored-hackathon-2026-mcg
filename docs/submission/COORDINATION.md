# Savia final-day release candidate

Root coordinator: Codex chat `01a10966-fe1d-7b52-aab5-e6f160426231`.
Started October 4, 2026, around 19:15 America/Bogota. Submission date in the
local kickoff is October 5; verify its exact requirements before exporting.

The customer story is an unrecognized charge. Savia explains the verified
facts, clarifies ambiguity, helps the customer take the next step with consent,
remembers context, and follows up with an honest status or helpful next action.
It must not imply that an intake alone resolves a dispute or grants a refund.

## Leads

| Lead | Owned implementation and outputs |
| --- | --- |
| Release runtime | `deploy/`; live runtime/source reconciliation; isolated RC Git assembly; `runtime-status.json` |
| Customer follow-through | `frontend/`, `banking_mcp/`, `dispute_workflow/` if present; useful answer and durable follow-up; `customer-status.json` |
| Voice and background work | `frontend/src/avatar/`, `frontend/server/conversation.py`, `frontend/server/voice.py`, native worklet and focused voice tests; nonblocking conversation/history/background execution; `voice-status.json` |
| Measurements and recorded story | `scripts/submission/`, relevant new evaluation fixtures; actual baseline comparison, journey capture, `measurements/`, `measurement-status.json` |
| Repository cleanup | root README and general `docs/` outside `docs/submission/`, safe legacy cleanup; `cleanup-status.json` |
| Video and decks | `docs/submission/media/`, `scripts/submission_media/`; final MP4, presentation and pitch decks; `media-status.json` |
| Inquiry automation (added at the human's request) | `savia_assistant/`, `scripts/submission_assistant/`, `docs/submission/assistant/`; generic FLUJO MCP/schedule integration; `assistant-status.json` |

The root owns this file, `threads.json`, and `RELEASE_CANDIDATE.md`. Leads may
write their own status JSON here, with `updated_at`, `state`, `completed`,
`next`, `blockers`, `artifacts`, and changed source paths. Keep them compact.

## Delivery rules

- Read `AGENTS.md`, the FLUJO product boundary, and deployment source map first.
- Preserve existing uncommitted work and other owners' live state. Share one
  local checkout with disjoint writers. Do not switch its branch, reset, stash,
  broadly stage, or commit another lead's files. The runtime lead assembles an
  isolated release snapshot after root's integration checkpoint.
- Reuse the existing FLUJO team, dispute engine, video pilot and decks where
  useful. Do not spawn duplicate ongoing missions or extensive new probes.
- Leads use `gpt-6.1-sol`, high. The human permits each lead up to three new
  worker chats using available `gpt-6-luna`; create only useful bounded workers.
  Workers must inherit the same ownership boundaries and report their IDs.
- The human explicitly authorizes root and these leads to message the seven
  leads, their workers, and existing project/FLUJO/Claude recovery chats to
  coordinate this final-day work. Keep external Slack/email messages unsent.
- First useful checkpoint in about 15 minutes. Build deliverables immediately;
  keep root informed of a real dependency or blocker through status files.
- Use fictional customers for public demo assets and isolated full action
  acceptance. Respect existing consent and ledger continuity in shared banking
  services; preserve private data and credentials.

## Release acceptance

1. One reproducible startup and identified runtime/source candidate.
2. A recorded Spanish full customer journey with a helpful answer and visible
   follow-up; a Portuguese clarification example and honest failure/handoff.
3. Voice continues naturally while an actual task runs in the background;
   conversation history and interruption behavior are demonstrated.
4. Measured latency, completion, grounding and baseline comparison with sample
   size and scope. Use actual calls; identify simulated bank/provider portions.
5. A final playable submission MP4, editable slide deck and pitch deck with
   exports, speaker notes, and matching measured claims.
6. Current README/runbook, preserved contributor credit, coherent source
   snapshot, and a concise list of any remaining release limitations.

Root verifies the final artifacts and customer story before declaring ready.

The owner rejected the standalone Elsewhere entry and ordered removal of the
legacy root `avatar/`. The intended product is the integrated eyes and native
voice inside Savia's assistant dialog, sourced from PR 52 and merged with the
current inquiry features. Its deployed recording must qualify that exact UI.
The tracked root avatar source has been removed through Git in both checkouts;
physical remnants remain pending because automatic approval review rejected
recursive filesystem deletion. They must not be archived or reported deleted
until the actual directory is absent.

## Organizer pitch direction supplied by the human

Pitch to a bank investor: sell the product and the problem it solves. The video
should be about 90% product/creativity and 10% technical, following Why → What →
How, with a launch-event feel, animations, transitions and product mockups. The
slides should be about 60% product/creativity and 40% technical; connect data,
models and architecture to customer and bank value. Preserve the full working
journey separately while using concise proof moments in the creative edit.

## Updated human critical path (October 4, 19:52)

Savia the friendly voice assistant is the submission. The customer asks once;
Savia keeps inquiry context, can ask agents to explore different approaches,
reports actual team/human work and status changes, and follows up toward a
solution during the day or week. A new seventh lead owns the simple app-owned
automation/MCP case-event loop in `savia_assistant/`, with frontend hooks owned
by the customer lead and voice by the voice lead. Record true status events;
human work requires actual acceptance, and intake alone is not resolution.
Bank reads still require live authorization; longer case tracking does not
extend a bank session or reuse revoked consent.

The UI needs a natural conversational layer plus separate inquiry conversations
or a clear/new-chat control; clearing chat must preserve receipt/follow-up state.
The film returns to the fun TV-spot concept: calm conversation while locations
become progressively absurd, with Savia as the hero. Architecture and UI support
the assistant story. Existing model failures and actual service proofs remain
in the measurement report rather than dominate the pitch.
