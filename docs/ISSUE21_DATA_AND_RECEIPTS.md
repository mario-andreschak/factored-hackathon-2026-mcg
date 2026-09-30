# Charge search, existing cases and saved human-help requests

These are the source contracts for issue #21, points 2 and 3. The companion
FLUJO and frontend changes must use these same fields. Installation and customer
acceptance are separate from these source tests.

## Search by event date

`list_my_transactions` keeps its existing arguments and owner checks. The
default window has at most 90 inclusive calendar days ending at the latest
ownership-valid event date in the serving snapshot, bounded by its first event
date. Explicit dates are preserved: a complete window of at most 90 days may
select any interval within the snapshot's verified event bounds. Partial or
out-of-coverage dates fail safely for clarification instead of being clipped or
shifted to the snapshot default. Partition dates do not define the window.

```json
{
  "date_window": {
    "start": "2026-03-21",
    "end": "2026-06-18",
    "basis": "transaction_date",
    "calendar": "source_timestamp_calendar_date",
    "anchor": "2026-06-18",
    "max_calendar_days": 90
  },
  "snapshot_event_dates": {
    "first": "2023-06-18",
    "last": "2026-06-18",
    "basis": "transaction_date",
    "calendar": "source_timestamp_calendar_date"
  }
}
```

These example dates are illustrative. The actual bounds come from the exact
served gold files after lineage, source-reference and ownership checks. Newly
published snapshots record that aggregate. Older pinned snapshots can derive it
from their validated files; supplied aggregates must match. Missing dates in
served ownership-valid rows or incoherent metadata make the dataset unavailable.
Rows quarantined by the pipeline are not served. This does not establish that
newer S3 objects have been ingested; freshness remains `derived_snapshot` unless
selected-source verification succeeds.

The source contract stores timestamps without a declared timezone. Search uses
their recorded calendar date, without inventing a timezone conversion. Intake
eligibility still uses its separate real-time 120-day policy. Authentication,
consent, pending expiry and revocation clocks retain their existing behavior.

## Show a saved case instead of creating another

`get_my_transaction` adds `existing_case`. It first resolves the principal-bound
selection and exact owned charge; it does not accept case identity from text.

| State | Meaning | Receipt |
| --- | --- | --- |
| `verified` | Exact persisted owner/charge receipt matched | Saved receipt, including `status: "received"` |
| `not_found` | Verified absence in this local ledger, with no unresolved attempt | `null` |
| `action_unverified` | Legacy, corrupt or uncertain evidence | `null` |

Every projection also has `coverage: "sandbox_only"` and
`source: "sandbox_cases"`. A historical complaint cannot prove that a case is
associated with this charge, or that none exists elsewhere.

New receipts are saved atomically with the case in `sandbox_case_receipts`.
Their charge facts must match the exact selection. A prior receipt may retain
an earlier snapshot after a new publication or conversation; it is not a new
case. That receipt is verified only when its saved public charge facts still
match the current exact owned selection. Changed charge facts produce
`action_unverified`; the older receipt is not relabeled as proof of the changed
charge. Legacy rows are not given invented receipts or statuses.

Preparation returns `decision: "existing_case"`, `reason: null` and the verified
projection for an existing receipt. FLUJO must independently read that receipt
again and return terminal `existing_case_verified`. It must not call confirmation
or offer another case. The receipt's nested snapshot is the original case
snapshot; the preparation's top-level snapshot describes the current selection.

Internal `confirmation_state` records `prepared`, then a durable `attempted`
before the case write, and `verified` with a successful case/receipt commit.
Legacy `NULL` and failed attempts remain uncertain. No automatic second write is
allowed to turn an unknown outcome into success or absence. Fresh authorization
is checked throughout. If a case row is missing but a retained preparation says
that an existing case was verified, that prior evidence also keeps the outcome
`action_unverified`; it cannot justify another intake.

An overlapping confirmation performs receipt-only polling with a five-second
deadline. It closes the database connection before sleeping and rechecks
authorization on each read. The existing database gate can add contention time;
the polling deadline is not an end-to-end latency guarantee.

## Save and read back the human-help request

The host-only request field is `unanswered_questions`, default `[]`: at most
eight strings, each 1–240 characters. The host validates and normalizes the
questions once, then freezes them with the request ID for retries. Question text
is caller data, not authority or verified charge facts.

The saved `handoff.packet` has:

```json
{
  "schema": "banking-sandbox-handoff/v1",
  "transaction": {
    "transaction_reference": "txn_0123456789ab",
    "transaction_date": "2026-06-18T10:00:00",
    "process_date": "2026-06-17",
    "amount": "10.00",
    "currency": "USD",
    "status": "Approved",
    "merchant": "Demo Shop",
    "transaction_type": "Purchase",
    "channel": "POS",
    "product": "Credit Card"
  },
  "transaction_provenance": {
    "source": "owned_serving_snapshot",
    "snapshot": "example_build",
    "as_of": "2026-09-29T12:00:00Z"
  },
  "reason": "customer_request",
  "unanswered_questions": ["An unanswered customer question"],
  "human_responded": false
}
```

The example is fictional. Both transaction and provenance are `null` for general help.
For a selected charge, the server rechecks ownership, facts and the serving
pointer before saving; browser/model facts cannot replace them. Pointer checks
are point-in-time checks, not a lock against future dataset publication.
`transaction_provenance.as_of` is the host's UTC time recorded after the owned
snapshot recheck. It is not the source-data cutoff or proof that bank data are
current.

`read_verified_handoff` checks the saved packet before its ID may be shown. The
response retains the saved facts and adds `handoff.transaction_currentness`:
`same_snapshot`, `different_snapshot`, `unknown` or `not_applicable`. It does not
silently relabel older facts as current. A changed payload under an existing
request ID fails instead of overwriting the packet. Missing legacy packets stay
unverified.

Customer wording is **request saved**. `human_responded` is always false here;
the packet does not establish agent pickup or a live-bank operation.

## Evidence boundaries

Focused tests use newly generated fiction and temporary state. They cover date
boundaries, ownership, missing dates, legacy migration, exact receipts, retries,
write failures, snapshot changes and ES/PT question preservation. They are not
real-model or deployed customer acceptance.

The snapshot reader derives and validates event bounds once per newly selected
snapshot. That cold scan has not been measured against the real 4.4-million-row
dataset for this source revision; the earlier lookup benchmark does not measure
this changed startup path.

The earlier package receipt remains pinned to banking `529bcca` and FLUJO
`961fd13`. It does not validate these changed runtime files. Its source-drift
guard remains intact; a new reviewed source pair needs a separate private
remote package/discovery run. Existing workers, graphs, policies and action
settings are unchanged by this source work.
