# Private demo recovery triage

When the safe prepare-recovery window is exhausted, the customer can share the
`rev_…` reference displayed in Savia with the team who provided demo access.
This identifies the saved demo action for private review. It does not open a
support ticket, notify an operator, or prove a person has picked up the case.
When Savia displays this exhausted status, its saved unresolved action is locked.
This offline review does not prove the current live lock or team pickup.

`scripts/triage_recovery.py` reviews historical evidence from detached snapshots.
It constructs no `ChatService` or MCP `StateStore`, makes no API calls, reconstructs
no pending handle, and performs zero action, ledger, or frontend-state writes.
It is a private CLI, with no public operator endpoint. It cannot reconcile or
change the customer-facing state.

## Acquire consistent private snapshots

An authorized demo team member must export each database through SQLite's backup
API into a **detached private snapshot**, separate from the deployed state volume:

- Frontend state: `frontend-chat.sqlite3`.
- MCP ledger: the MCP service's configured SQLite `state_db`.

Do not point this command at a live database. Absence of WAL companions does not
prove a file is a backup. A simple copy of the main database can omit committed
WAL records. If the acquisition process copies a database and WAL together, keep
the complete consistent set and consolidate it using an authorized SQLite backup
API step before running this CLI. Never discard WAL to make a copy pass the check.
The CLI itself performs no export, checkpoint, recovery, migration or deployment.

Record the source deployment and source revisions, ledger generation, authorized
capturer, UTC capture times for both snapshots, and SHA256 hashes in a private
capture record. Capture the same stable operation interval; a frontend/MCP pair
is not one cross-database atomic snapshot. State changes between captures can
leave missing evidence. Keep snapshots and output restricted to the demo team.

The CLI rejects missing files, two paths to the same file, unexpected schemas,
and `-wal`, `-shm` or `-journal` companions. It opens consolidated copies with
`mode=ro&immutable=1` and `PRAGMA query_only=ON`, hashes both inputs before and
after its reads, and rejects changed inputs. The output includes those SHA256
hashes. These checks reject detectable schema, sidecar and input-change problems;
they cannot prove that an input is a detached or complete backup. The authorized
capture record must document provenance and freshness. The CLI does not verify
that record or establish live state; its evidence applies only to the fixed hashes.

## Run privately

From the repository root, use the existing MCP Python dependencies. `-B` suppresses
Python bytecode caches; output goes to stdout unless the operator saves it privately.

```powershell
uv run --no-project --with-requirements requirements-mcp.txt python -B -m scripts.triage_recovery --frontend-snapshot C:\private\frontend-backup.sqlite3 --mcp-snapshot C:\private\mcp-backup.sqlite3 --review-reference rev_0123456789abcdef01234567
```

Count snapshot records before considering external demo activation:

```powershell
uv run --no-project --with-requirements requirements-mcp.txt python -B -m scripts.triage_recovery --frontend-snapshot C:\private\frontend-backup.sqlite3 --mcp-snapshot C:\private\mcp-backup.sqlite3 --summary
```

The summary counts saved unresolved prepares, raw saved exhausted attempts/windows,
validated expired pending evidence, unavailable references, malformed saved JSON,
and findings. These are **snapshot-only counts**, not a live incident queue. Missing
or malformed identity evidence remains unresolved and must be included in review.
Exit `0` means the read completed, not that an action resolved; exit `2` means the
snapshots or reference could not be safely inspected.

## Interpret evidence conservatively

The reference is derived only from the frontend's random `action_id`. The CLI
requires one matching saved row, matching frontend owner/session/expiry, saved
subject/customer/conversation and public target consistency. It checks the MCP
session's subject/customer before computing the exact RFC 8785 principal binding
and the original prepare request key. Original session expiry/revocation is
historical metadata, never permission to operate. Review after expiry remains
possible without any authorization call.

Pending evidence must match the saved binding, customer, private transaction,
snapshot and action. Its stored result must agree with its decision/reason/facts.
The frontend's `txn_24hex` reference and MCP's `txn_12hex` fact reference are
different schemes and are not compared to each other.

Only a HOF packet under that **exact original request key** is eligible; its
binding, customer, transaction, snapshot, reason and facts must match the saved
pending decision. An exact packet reports `exact_handoff_packet_evidence` and
its opaque HOF reference. A HOF packet can outlive the pending TTL, so
`pending_expired` and the summary's `pending_expired_count` remain separate.
This is persisted historical packet evidence, not live pickup or consent.

An older sandbox case for the saved customer/transaction/action, even from a
different snapshot, is only `existing_case_only`. The cases table has no request
or session binding; it cannot prove this lost prepare reached confirmation.
Missing, expired, mismatched or ambiguous evidence never proves that no action
occurred. Do not clear/reset the slot, replay, retry, confirm, mutate a record,
or promise a customer resolution using this command.

Every report requires `leave_unresolved_locked`; `snapshot_action_locked` describes
only an unresolved row actually found in the fixed copies, and `live_action_lock`
is always `unproven`. Consent for the lost prepare and human pickup remain unproven.
Share the redacted reference and validated packet evidence with the demo access
team for manual investigation. A live reconciliation and customer-response process
must be established and evidenced separately before external use. Keep action
controls disabled until the release's remaining validation gates are satisfied.
