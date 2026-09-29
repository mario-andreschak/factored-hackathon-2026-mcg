# Simulated unrecognized-charge intake v0

This is a private, single-customer prototype. Savia resolves a displayed transaction reference to an owned source transaction on the frontend server, opens the already owned FLUJO conversation, and asks the protected FLUJO action route to prepare a sandbox intake. The model cannot choose or call these five action tools. The customer confirms the exact prepared action in the UI; the backend then reads a persisted sandbox receipt before displaying its ID. Handoff IDs are also displayed only after a separate read.

The integration is disabled by default. Set `chat.action_enabled` to `true` in the private frontend config only after the matching FLUJO action route and delegated banking MCP source are installed. This setting never enables a live bank write. The MCP remains the existing private stdio server in the FLUJO worker; there is no remote MCP endpoint or extra container.

## Provisional policy

The R16 count is the number of distinct persisted, owner-readable sandbox unrecognized-charge cases whose server UTC `created_at` falls in `[now−24h, now)`, excluding the current transaction, plus the current distinct owned request. At three or more, the action prepares a verified human handoff. The count is private and is not sent to the browser. This is a sandbox measure, never a claim about all bank reports.

`sandbox_report_coverage_start` in the private MCP config is an operator attestation that the sandbox ledger's report history is complete from that Unix timestamp. When it is absent, later than `now−24h`, or unavailable, `risk_data_complete=false` and the count is `null`; the action routes to `missing_evidence` handoff. A complete initialized empty ledger measures zero prior sandbox cases. The decision also hands off transactions older than 120 calendar days, future-dated transactions, and statuses other than `Approved`.

Pending handles last ten minutes. Confirmation rechecks the original owner, current snapshot and transaction facts, coverage, and count. `(customer, transaction, action)` is unique in SQLite. A lost confirmation response is followed by a receipt read for the same pending handle, never another confirmation write. Only a read-back case earns `CMP-SBX-XXXXXXXX`; only a read-back handoff earns `HOF-XXXXXXXX`. A handoff packet records no human response. Spanish and Portuguese fallback text explicitly distinguishes an unverified action from a verified handoff and states that no refund or dispute resolution occurred.

An already persisted case for the same owner and transaction routes a new preparation to `duplicate_review` handoff. It does not ask the customer to create another case. A retry of the original pending handle remains idempotent.

## Verification and limits

The source tests exercise owner denial, replay, concurrent confirmation, the 24-hour threshold, missing coverage, stdio action tools, frontend API mapping, Spanish and Portuguese fallback, and lost logout acknowledgment recovery. A private joined browser→FLUJO→MCP run against one matching synthetic snapshot is still required before this prototype is enabled in a worker. The currently running worker and organizer `CURRENT` pointer are intentionally unchanged. The separate 15-case audit pack is read-side evidence and does not establish action acceptance.
