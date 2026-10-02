# Retained dispute deployment transition

This source prepares an **offline** transition from the old bank and worker
authority to the application-native transaction dispute workflow. The code
contract is `native-dispute-deployment-contract/v1`, agreed for source
implementation. Operator application, simulated intake activation, promotion,
and any live-state mutation remain gated to the Fly owner and independent
release review. The tools here have only synthetic test evidence.

## State and process boundary

The target image application root is `/opt/joined`. Native FLUJO listens on
loopback port 4200; the Python frontend API listens on loopback port 8082. The
retained bank ledger and new native application state are in
`/data/banking-state`; the new frontend settings input state is
`/data/native-frontend-state`. Old `/data/frontend-state` and `/data/flujo`
remain sealed private history. No old cookies, worker capabilities, chat
sessions, or bank stdio children transfer. Customers must log in again and see
an honest old-history-unavailable notice until archive access is separately
authorized.

The existing runner `--source-root` is **private bank object data** for
`bank_read.py`. Never set it to `/opt/joined`. The Fly owner supplies approved
bounded S3 object keys and hashes through the bank-only
`bank_config.source_env=/run/dispute/source.env`; the worker must not read that
file. New runner `--application-source-root /opt/joined` is solely for receipt
code inventory. The reconcile CLI `--source-root /opt/joined` also means code
inventory. They are separate values.

The app/bank process is UID/GID 10001; the worker/gateway is UID/GID 1000.
Only host control paths use supplementary reader GID 10002. The opt-in writer
publishes `admissions.json` and revocation tombstones as 0640 owned by the
bank app and reader group, with 2750 control directories. The stable lock stays
0600. No group-write permission is granted. Private bank DB/config/data/keys
remain outside group 10002. The default port behavior remains private.
The Fly owner must check actual process groups and file access in the image;
mode checks in unit tests do not establish cross-user isolation.

## Operator evidence and commands

The protected operator evidence JSON uses
`dispute-retained-operator-evidence/v1`. It names the exact retained bank
path, source inventory digest, four-table ledger schema/row hashes and counts,
an active exclusive deployment lease with its private proof file/hash,
explicit original-process retirement and worker drain with a separate proof
file/hash, preservation of late replies, and every old obligation as
`confirmed` with its original-authority receipt file/hash. It names sealed old
frontend/worker archive files and their hashes, plus a separate synthetic
coverage proof file, actual start time and `synthetic:` provenance. Unknown,
pending, uncertain, or expired-unconfirmed obligations block. An old worker
reply or new native host ACK cannot be substituted for original settlement.
No expiry is inferred from legacy bank sessions, whose old schema lacks it.

The operator must supply reviewed current evidence, not the historical
22:40 UTC counts. The plan re-reads it and the ledger through read-only SQLite
without constructing `StateStore` or changing the original DB. Plan writes a
new private file only:

```sh
python scripts/reconcile_dispute_deployment.py plan \
  --bank-config-file PRIVATE_BANK_CONFIG \
  --legacy-frontend-state-dir /data/frontend-state \
  --legacy-worker-state-dir /data/flujo \
  --native-state-dir /data/banking-state \
  --new-frontend-state-dir /data/native-frontend-state \
  --native-authority-dir /data/native-authority/control \
  --operator-evidence PRIVATE_LEGACY_ADMISSION \
  --source-root /opt/joined --output PRIVATE_PLAN
```

After a reviewed image, actual old-authority revoke/drain and exclusive
operator lease, the Fly owner may separately decide whether to run:

```sh
python scripts/reconcile_dispute_deployment.py apply \
  --plan PRIVATE_PLAN --bank-config-file PRIVATE_BANK_CONFIG \
  --operator-evidence PRIVATE_LEGACY_ADMISSION \
  --receipt PRIVATE_RECEIPT --native-reader-group 10002
python scripts/reconcile_dispute_deployment.py verify \
  --receipt PRIVATE_RECEIPT --bank-config-file PRIVATE_BANK_CONFIG \
  --source-root /opt/joined --native-state-dir /data/banking-state
```

Apply rechecks the exact plan, archives the old bank SQLite rows in
`legacy-bank-before-native.sqlite3`, adds the current additive tables and a
new `secrets.token_hex(32)` generation in one SQLite transaction, and records
the separately proved coverage. It writes a no-overwrite receipt, verifies
the result, then atomically publishes the generation pin. Publication fsyncs
the file on both platforms and the parent directory on POSIX; Windows does
not offer a portable directory fsync, so the Fly owner must still qualify
actual retained-volume durability and restart behavior. A crash before
receipt/pin leaves an explicit manual recovery block; it never silently
re-adopts or seeds a pin. Apply and verify never restore a stale bank snapshot.
Later native sessions, replays, cases, receipts, and revocations may change
the active DB. Verify checks the generation, schema, coverage, immutable old
archive and exact original session/revocation rows. Original live replay and
capability rows must remain unchanged; expired originals may be pruned after
the archive retains their bytes. It does not pin a frozen hash of mutable DB
bytes.

Runtime uses:

```sh
python scripts/run_dispute.py --state-dir /data/banking-state \
  --bank-config-file /run/dispute/bank-config.json \
  --native-url http://127.0.0.1:4200 \
  --native-authority-dir /data/native-authority/control \
  --transition-receipt /run/dispute/transition-receipt.json \
  --application-source-root /opt/joined --native-reader-group 10002 \
  --port 8082
```

Receipt verification runs before state creation or `Service` construction.
`--enable-simulated-intake` remains a separate reviewed switch after
legitimate coverage and authority qualification. A genuinely fresh authored synthetic fixture can exercise that switch and
the reader group without a retained-state receipt. It needs a private
`QUALIFICATION_SYNTHETIC.json` marker in its bank object root or data dir.
The runner writes `native-fresh-origin.json` only after a new ledger receives
a genuine generation and pin; restart checks marker, source hash, generation
and pin. An adopted identity+pin without its receipt never counts as fresh,
even if someone removes the bank archive. This marker is local fixture
provenance, not production proof. The existing bank generation guard still
rejects populated missing-pin state. Real bank effects stay off.

## Proof limits and recovery

The local source inventory covers bank, dispute and frontend Python files;
frontend TS/TSX/CSS and public assets; prompts, policy, pipeline and config
inputs; the flow definition; runner/reconcile/native port scripts; and
`requirements-dispute.txt` plus frontend package metadata. It is a
code-change fence, not an exact OCI image or installed model/profile/provider
proof. The source image must actually carry these inputs at `/opt/joined`
or the plan fails closed. The
Fly owner must provide the image/source manifest, configuration and provider
readback separately. The operator evidence is a protected attestation; this
tool checks its exact declared files and hashes but cannot independently prove
a remote lease, the contents of a sealed archive, original worker drain, or
historical coverage semantics. Those remain hard human/operator review gates.
Do not treat a synthetic test, a source digest, or API health as end-to-end
customer acceptance.

On interrupted apply, preserve the newer bank DB, archive, pending
obligations and receipt artifacts. There is no automatic crash-resume journal:
a crash after archive publication, after schema commit, or before generation
pin publication cannot be retried through the ordinary four-table plan.
The Fly owner must freeze authority, inspect exact DB schema/generation,
archive, receipt and pin, and have an independent reviewer authorize an
explicit recovery procedure. Do not delete an artifact to replay apply or
restore a stale DB. The old authority flags and hashes in the operator
evidence are declarations, not proof of original-worker revocation or OS
process exit; the Fly owner must independently join the actual original
receipts and process-drain evidence before apply. Roll source and
gateway back only if the Fly owner verifies compatible admitted authority;
otherwise use maintenance/read-only archive mode. Customers re-login. No
public deployment or bank action activation is part of this source change.
