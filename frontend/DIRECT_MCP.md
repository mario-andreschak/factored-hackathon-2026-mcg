# Direct bank host source migration

This candidate changes source only. Services, images, flags, shared configuration
and state have not been changed. Runtime deployment remains held pending the
project MCP transport, generic graph/provider isolation and integrated review.
Previous frontend/worker evidence belongs to the previous architecture.

The portal keeps its existing owner-scoped Repository reads. For a charge action,
the host resolves the browser's txn24 reference to exactly one owned private raw
transaction ID, current snapshot and expected transaction fields. It sends that
raw ID and snapshot to the standard MCP `prepare_unrecognized_charge` tool. MCP
independently checks the mapped principal, ownership and CURRENT snapshot. MCP's
txn12 display reference remains unchanged; neither display reference is an MCP
selection capability. Field and snapshot correlation occurs before follow-up writes.

`bank_rpc.py` owns a private bank signer and stateless Streamable HTTP handshake,
using protocol `2025-11-25` over certificate-verified HTTPS only, with explicit
absolute-path CA/certificate trust, hostname verification, no redirects and no
environment-proxy/trust overrides. Bank service bearer credentials and assertions never
reach FLUJO. Assertions have exact EdDSA header/claims, fresh JTI, RFC8785 digest
of final arguments and singleton tool scope. They expire within 60 seconds and
before the real frontend session and call deadline. The legacy claim names
`run_id` and `graph_revision` carry the actual host operation UUID and configured
reviewed host source revision. An admission callback checks owner, expiry,
revocation, the original ledger generation, action enablement and continuity
approval after the handshake, immediately before signing, and before returning
evidence. Both assertion profiles require `ledger_generation`, exactly 64
lowercase hexadecimal characters from the existing bank ledger identity.

The private listener added in [backend PR #32](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/32) requires `bank.base_url` to use
`https://<approved-private-IPv4>:<configured-port>`. The literal IP and explicit
port must match the listener's configured bind address and expected `Host`
header. Its TLS certificate must include that same IP in its Subject Alternative
Name, and the mounted approved CA/certificate must verify it. This listener
rejects DNS aliases. Certificate identity verification remains enabled. The
example uses deliberately invalid IP/port placeholders and supplies no working
endpoint; actual network, peer allowlist and TLS alignment remain review gates.

The host persists an independent bank context UUID and a namespaced bank session
binding. Generic language conversation IDs cannot select or replace either one.
The host retains prepare UUID/CAS replay bounds and the exact private target tuple
plus expected facts. Only a structured pre-admission MCP `server_busy` rejection
permits rollback; HTTP 429 remains uncertain. Confirm requires explicit true,
the same saved handle/target/snapshot/facts and a live session. After any uncertain
confirm, only same-handle receipt reads are allowed. No confirm replay or guessed
handoff is issued. Existing cases also require an independent receipt read.
Handoff success requires a complete independent packet readback with unchanged
reason, questions, facts and provenance; only observed snapshot currentness may
change. Strict delegated result schemas reject synthetic/operator flags, extra
fields and contradictory prepare risk/existing-case metadata.

Logout persists local denial and the bank revocation outbox before deleting the
portal session. Fresh `bank-revoke+jwt` assertions go only to private
`/internal/revoke`; exact acknowledgement establishes confirmed delivery. Failed
delivery remains visible/retryable until session expiry. Grant TTL never exceeds
that expiry, so the existing expiry boundary is retained. The outbox retains its
original ledger generation. Matching-generation revocation may add denial while
the ledger is quarantined; a mismatch remains unconfirmed and never gets re-signed
against a replacement generation. Revocation is never a
model tool. The generic worker may finish a minimized language request after logout;
the host suppresses its result and transcript.

FLUJO receives only ordinary `/v1/chat/completions` requests with a separate generic
bearer, a fixed saved flow name, sanitized bounded user text and typed host-selected
display date, decimal amount/currency, bounded merchant and normalized recorded
status. Private known values/capabilities are excluded before dispatch. The saved
flow ID is declared provenance; it alone does not attest the live graph/provider.
The worker returns exactly:

```json
{"schema":"host-language-guidance/v1","language":"es","guidance":"explain_selected"}
```

Language may be `es` or `pt`. Guidance may be `explain_selected`,
`ask_date_or_amount`, `ask_selection`, `suggest_human` or `unavailable`. The host
renders deterministic copy. Free-form prose, extra action fields, tools or invalid
responses fall back safely and cannot claim an intake, refund or human response.
This schema must be used by the separately reviewed generic graph. A no-tool graph
alone does not attest operating-system/file/network isolation of a model process.

Configuration uses `direct-mcp.config.example.json`. Its placeholders deliberately
fail validation. Keep `action_enabled: false` and `ledger_continuity_approved: false`
until the integrated candidate is reviewed. The latter defaults to false in both
the host and bank configuration. Set `chat.ledger_generation` only through approved
private offline configuration; browser or model responses cannot adopt it.
Replace the host revision with the actual reviewed deployed source
commit; configure the matching public key and principal mapping in MCP. Bank and
language credentials are independent. Neither key nor private configuration belongs
in source control or the generic worker's model context.

Startup refuses any legacy worker-bound chat/action/revocation/transcript rows
without the direct-host marker, before schema or identity mutation. It does not
transplant old pending handles, conversations or revocation intents. Preserve the
old volume and reconcile it under its original authority before selecting isolated
state for this candidate. Changing the bank issuer, namespace, audience or approved
principal mapping also requires explicit state isolation/reconciliation. The host
also pins the bank endpoint, key ID, public signer fingerprint and TLS trust
fingerprint, plus the expected ledger generation in the immutable durable bank
policy, sessions and revocation intents. Nonempty direct-host state without this
pin is refused before migration or outbox repair. Missing, malformed or changed
pins require explicit reconciliation; old handles, request UUIDs, counters and
revocation intents are preserved. This source contract has no automatic adoption
or reset endpoint. Generation/continuity errors use a fixed blocked path and do
not trigger confirm, handoff or receipt follow-ups in the same workflow. A proven
pre-dispatch denial can release only its matching prepare-recovery reservation;
the original action remains locked. A possibly admitted operation retains both
its uncertainty and retry count, including a later callback failure in that
workflow.

The bank checks the signed generation before session/JTI mutations, inside its
state transactions and at final result fences. Host callbacks also recheck the
action and continuity flags for already admitted work. Final-fence rejection can
follow a durable write: the host keeps the original locked intent and never treats
it as a rollback or definitely absent receipt. Integrated transaction behavior
still requires the bank's independently reviewed implementation.

An older attested database restore can retain the same generation and coverage
while losing later cases. Equality alone cannot detect that rollback. Trusted
restore/import/replacement or uncertainty must pause and drain work and set the
external `ledger_continuity_approved` configuration false before reopening.
No request or startup heuristic clears it. Reopening requires explicit operator
reconciliation, rotation of the existing generation, coverage invalidation and
re-attestation, retirement of old sessions/capabilities, and explicit host adoption.
There is no new HTTP rotation/reconciliation API. Preserve and reconcile old
state before selecting isolated host state. A fresh unattested ledger already
blocks eligible intake under the bank's existing coverage rule; do not interpret
its missing receipt as evidence about the original ledger.
Changing only generic language configuration resets its locally versioned context,
shows an explicit customer notice and keeps bank inquiry/handles/revocation stable.
The host reserves a generic UUID before dispatch and retains it through malformed
output or timeout, independently of whether language output was accepted.

Earlier validation at the prior source pin used temporary SQLite/generated keys
and recording fakes; it is historical evidence for that pin. This continuity
correction permits inspected frontend in-memory callbacks with external resources
replaced before source execution. No application import/start, real key/TLS/SDK,
host SQLite, listener, browser, model, Docker or build is exercised. Such checks
establish field/control ordering, not durable recovery or runtime deployment.
Legacy ingress tests and frozen end-to-end proof packets cannot attest this new
architecture; integrated endpoint/assembly/runtime validation is pending.


Evaluation evidence also remains pending. The host operation UUID is signed but
this candidate has no durable protected trace joining it to every action/CAS
attempt, JSON-RPC request, assertion JTI/digest and independent readback. Generic
completion status does not establish accepted model output or live provider/graph
provenance; fallback and deterministic host copy must be measured separately.
A later reviewed capture contract and evaluation adapter must preserve those
joins, accepted/fallback reasons and permitted generic conversation context.
Historical scorers and blank human review packets are not relabeled by this
migration, and these pure fake tests establish no learned-model quality claim.
