"""Synthetic offline review evidence; no running service, credentials or writes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

import pytest

from banking_mcp.actions import Actions
from banking_mcp.security import Principal
from frontend.server.review import review_reference
from scripts import triage_recovery as cli


NOW = 2_000_000_000
ACTION_ID = "550e8400-e29b-41d4-a716-446655440000"
REQUEST_ID = "c363b123-b938-4e74-a002-d032c9964a44"
CONVERSATION = "a2deaa46-4997-4fe2-8615-c1c02c3359a7"
REFERENCE = review_reference(ACTION_ID)
SUBJECT = "synthetic-álîce"
CUSTOMER = "private-customer-a"
SESSION = "private-session-a"
OWNER = "a" * 64
TRANSACTION = "private-transaction-a"
SNAPSHOT = "synthetic-snapshot-v0"
TARGET = "txn_" + "a" * 24
FACTS = {"transaction_reference": "txn_" + "b" * 12, "amount": 25,
         "currency": "BRL", "status": "Approved"}
BINDING = cli.principal_binding(SUBJECT, CUSTOMER, SESSION, CONVERSATION)
KEY = cli.prepare_request_key(BINDING, REQUEST_ID)


@pytest.fixture
def snapshots(tmp_path):
    frontend, mcp = tmp_path / "frontend.sqlite3", tmp_path / "mcp.sqlite3"
    with sqlite3.connect(frontend) as db:
        db.executescript("""
            CREATE TABLE chat_sessions(session_id TEXT PRIMARY KEY, owner TEXT, expires INTEGER,
                conversation_id TEXT, subject TEXT, customer_id TEXT, revoked INTEGER);
            CREATE TABLE action_status(session_id TEXT PRIMARY KEY, owner TEXT, expires INTEGER,
                result_json TEXT, updated_at INTEGER, action_id TEXT, target_reference TEXT,
                prepare_transaction_id TEXT, prepare_snapshot TEXT, prepare_conversation_id TEXT,
                prepare_recovery_attempts INTEGER, prepare_recovery_deadline INTEGER);
        """)
        db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)",
                   (SESSION, OWNER, NOW + 1000, CONVERSATION, SUBJECT, CUSTOMER, 0))
        saved = {"state": "prepare_unverified", "request_id": REQUEST_ID,
                 "target_reference": TARGET, "message": "private-sentinel-do-not-print"}
        db.execute("INSERT INTO action_status VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   (SESSION, OWNER, NOW + 1000, json.dumps(saved), NOW - 700, ACTION_ID, TARGET,
                    TRANSACTION, SNAPSHOT, CONVERSATION, 6, NOW - 1))
    with sqlite3.connect(mcp) as db:
        db.executescript("""
            CREATE TABLE sessions(session TEXT PRIMARY KEY, subject TEXT, customer TEXT);
            CREATE TABLE action_pending(id TEXT PRIMARY KEY, binding TEXT, customer TEXT,
                transaction_id TEXT, snapshot TEXT, action TEXT, decision TEXT, reason TEXT,
                facts TEXT, expires REAL, request_key TEXT UNIQUE, result_json TEXT);
            CREATE TABLE sandbox_handoffs(id TEXT PRIMARY KEY, binding TEXT, customer TEXT,
                transaction_id TEXT, snapshot TEXT, reason TEXT, created_at REAL, facts TEXT,
                idempotency_key TEXT UNIQUE);
            CREATE TABLE sandbox_cases(id TEXT PRIMARY KEY, customer TEXT, transaction_id TEXT,
                action TEXT, snapshot TEXT, created_at REAL, facts TEXT,
                UNIQUE(customer,transaction_id,action));
        """)
        db.execute("INSERT INTO sessions VALUES (?,?,?)", (SESSION, SUBJECT, CUSTOMER))
        result = {"snapshot": SNAPSHOT, "action": "simulated_intake", "decision": "handoff",
                  "reason": "high_risk", "transaction": FACTS,
                  "risk": {"unrecognized_count_24h": 3, "risk_data_complete": True,
                           "coverage": "sandbox_only", "source": "sandbox_cases"}}
        db.execute("INSERT INTO action_pending VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("pending-handle-hash-do-not-print", BINDING, CUSTOMER, TRANSACTION, SNAPSHOT,
                    "simulated_intake", "handoff", "high_risk", json.dumps(FACTS), NOW + 600,
                    KEY, json.dumps(result)))
        db.execute("INSERT INTO sandbox_handoffs VALUES (?,?,?,?,?,?,?,?,?)",
                   ("HOF-abcdefgh", BINDING, CUSTOMER, TRANSACTION, SNAPSHOT, "high_risk",
                    NOW - 1, json.dumps(FACTS), KEY))
    return frontend, mcp


def update(path, table, column, value):
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE {table} SET {column}=?", (value,))


def run(snapshots):
    result = cli.triage(*snapshots, REFERENCE, now=NOW)
    assert result["state"] == "unresolved"
    assert result["required_disposition"] == "leave_unresolved_locked"
    assert result["live_action_lock"] == "unproven"
    assert result["consent_verified"] is False
    assert result["consent_for_lost_prepare_proven"] is False
    assert result["human_pickup"] == "unproven"
    assert result["scope"] == "offline_snapshots_only"
    return result


def add_old_case(path, snapshot=SNAPSHOT, customer=CUSTOMER, transaction=TRANSACTION):
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)",
                   ("CMP-SBX-oldcase1", customer, transaction, "simulated_intake", snapshot,
                    NOW - 86400, json.dumps(FACTS)))


def test_exact_digest_contract_without_prepare_or_store():
    principal = Principal(SUBJECT, CUSTOMER, SESSION, CONVERSATION, NOW - 100)
    assert cli.principal_binding(SUBJECT, CUSTOMER, SESSION, CONVERSATION) == principal.binding()
    actions = object.__new__(Actions)
    actions._prepare_secret = b"synthetic-test-secret"
    assert cli.prepare_request_key(principal.binding(), REQUEST_ID) == actions._prepare_identity(principal, REQUEST_ID)[0]
    assert cli.review_reference is review_reference
    assert review_reference(ACTION_ID) == "rev_" + hashlib.sha256(
        ("savia-demo-review-v1:" + ACTION_ID).encode()).hexdigest()[:24]
    assert review_reference("a" * 32) == "rev_" + hashlib.sha256(
        ("savia-demo-review-v1:" + "a" * 32).encode()).hexdigest()[:24]


def test_matched_handoff_is_redacted_evidence_only(snapshots):
    result = run(snapshots)
    assert result["finding"] == "exact_handoff_packet_evidence"
    assert result["handoff_evidence"] == "exact_request_matched_packet"
    assert result["recovery_exhausted"] is True
    text = json.dumps(result)
    for private in (ACTION_ID, REQUEST_ID, CONVERSATION, SUBJECT, CUSTOMER, SESSION, OWNER,
                    TRANSACTION, SNAPSHOT, TARGET, FACTS["transaction_reference"],
                    "pending-handle-hash-do-not-print", "private-sentinel-do-not-print"):
        assert private not in text
    assert result["handoff_reference"] == "HOF-abcdefgh"
    assert result["snapshot_action_locked"] is True


def test_original_expired_revoked_session_still_allows_offline_historical_review(snapshots):
    update(snapshots[0], "chat_sessions", "expires", NOW - 100)
    update(snapshots[0], "action_status", "expires", NOW - 100)
    update(snapshots[0], "chat_sessions", "revoked", 1)
    result = run(snapshots)
    assert result["finding"] == "exact_handoff_packet_evidence"
    assert result["session_expired"] is True
    assert result["session_revoked"] is True


def test_absent_pending_never_infers_no_action(snapshots):
    with sqlite3.connect(snapshots[1]) as db:
        db.execute("DELETE FROM action_pending")
    result = run(snapshots)
    assert result["finding"] == "pending_evidence_absent"
    assert result["handoff_evidence"] == "unproven"


def test_expired_pending_preserves_historical_hof_evidence_and_lock(snapshots):
    update(snapshots[1], "action_pending", "expires", NOW)
    result = run(snapshots)
    assert result["finding"] == "exact_handoff_packet_evidence"
    assert result["pending_expired"] is True
    assert result["handoff_evidence"] == "exact_request_matched_packet"


def test_expired_pending_without_matching_hof_remains_expired_evidence(snapshots):
    update(snapshots[1], "action_pending", "expires", NOW)
    with sqlite3.connect(snapshots[1]) as db:
        db.execute("DELETE FROM sandbox_handoffs")
    assert run(snapshots)["finding"] == "pending_evidence_expired"


def test_summary_counts_both_historical_hof_and_pending_expiry(snapshots):
    update(snapshots[1], "action_pending", "expires", NOW)
    result = cli.triage(*snapshots, now=NOW)
    assert result["pending_expired_count"] == 1
    assert result["findings"] == {"exact_handoff_packet_evidence": 1}


@pytest.mark.parametrize(("table", "column", "value", "finding"), [
    ("action_status", "owner", "foreign-owner", "frontend_identity_mismatch"),
    ("action_status", "expires", NOW + 2000, "frontend_identity_mismatch"),
    ("action_status", "prepare_conversation_id", str(uuid.uuid4()), "frontend_identity_mismatch"),
    ("action_status", "target_reference", "txn_" + "c" * 24, "frontend_identity_mismatch"),
    ("action_status", "prepare_transaction_id", None, "frontend_identity_mismatch"),
    ("action_status", "prepare_snapshot", None, "frontend_identity_mismatch"),
    ("chat_sessions", "subject", "foreign-subject", "mcp_identity_mismatch"),
    ("chat_sessions", "customer_id", "foreign-customer", "mcp_identity_mismatch"),
    ("chat_sessions", "subject", None, "frontend_identity_mismatch"),
    ("chat_sessions", "conversation_id", None, "frontend_identity_mismatch"),
])
def test_foreign_or_incomplete_frontend_identity_never_correlates(snapshots, table, column, value, finding):
    add_old_case(snapshots[1])
    update(snapshots[0], table, column, value)
    result = run(snapshots)
    assert result["finding"] == finding
    assert result["handoff_evidence"] == result["case_evidence"] == "unproven"


@pytest.mark.parametrize(("column", "value"), [
    ("binding", "foreign-binding"), ("customer", "foreign-customer"),
    ("transaction_id", "foreign-transaction"), ("snapshot", "foreign-snapshot"),
    ("action", "foreign-action"), ("decision", "intake"), ("reason", "missing_evidence"),
    ("facts", json.dumps({**FACTS, "amount": 999})), ("result_json", "{}"),
])
def test_foreign_or_mismatched_pending_never_reads_case_or_hof(snapshots, column, value, monkeypatch):
    add_old_case(snapshots[1])
    update(snapshots[1], "action_pending", column, value)
    traces = spy_connections(monkeypatch)
    result = run(snapshots)
    assert result["finding"] == "pending_evidence_mismatch"
    assert result["handoff_evidence"] == result["case_evidence"] == "unproven"
    assert not any("FROM sandbox_handoffs" in sql or "FROM sandbox_cases" in sql for sql in traces)


@pytest.mark.parametrize(("column", "value"), [
    ("binding", "foreign-binding"), ("customer", "foreign-customer"),
    ("transaction_id", "foreign-transaction"), ("snapshot", "foreign-snapshot"),
    ("reason", "missing_evidence"), ("facts", json.dumps({**FACTS, "amount": 999})),
])
def test_foreign_or_mismatched_hof_is_unproven(snapshots, column, value):
    update(snapshots[1], "sandbox_handoffs", column, value)
    result = run(snapshots)
    assert result["finding"] == "handoff_evidence_mismatch"
    assert result["handoff_evidence"] == "unproven"


def test_approximate_hof_does_not_match_the_saved_request(snapshots):
    update(snapshots[1], "sandbox_handoffs", "idempotency_key", "foreign-request-key")
    result = run(snapshots)
    assert result["finding"] == "exact_pending_prepare_evidence"
    assert result["handoff_evidence"] == "unproven"


@pytest.mark.parametrize("pending", ["present", "absent", "expired"])
@pytest.mark.parametrize("case_snapshot", [SNAPSHOT, "older-snapshot"])
def test_old_case_is_only_existing_case_evidence(snapshots, pending, case_snapshot):
    add_old_case(snapshots[1], case_snapshot)
    with sqlite3.connect(snapshots[1]) as db:
        db.execute("DELETE FROM sandbox_handoffs")
        if pending == "absent":
            db.execute("DELETE FROM action_pending")
        elif pending == "expired":
            db.execute("UPDATE action_pending SET expires=?", (NOW,))
    result = run(snapshots)
    assert result["case_evidence"] == "existing_case_only"
    assert result["case_snapshot_matches"] is (case_snapshot == SNAPSHOT)
    assert result["handoff_evidence"] == "unproven"


def test_intake_pending_and_old_case_do_not_prove_consent_or_handoff(snapshots):
    add_old_case(snapshots[1])
    with sqlite3.connect(snapshots[1]) as db:
        result = json.loads(db.execute("SELECT result_json FROM action_pending").fetchone()[0])
        result.update(decision="intake", reason=None)
        db.execute("UPDATE action_pending SET decision='intake',reason=NULL,result_json=?", (json.dumps(result),))
    result = run(snapshots)
    assert result["finding"] == "handoff_evidence_mismatch"
    assert result["case_evidence"] == "existing_case_only"
    assert result["handoff_evidence"] == "unproven"


def test_wrong_request_id_does_not_search_other_pending_or_hof(snapshots):
    with sqlite3.connect(snapshots[0]) as db:
        saved = json.loads(db.execute("SELECT result_json FROM action_status").fetchone()[0])
        saved["request_id"] = str(uuid.uuid4())
        db.execute("UPDATE action_status SET result_json=?", (json.dumps(saved),))
    result = run(snapshots)
    assert result["finding"] == "pending_evidence_absent"
    assert result["handoff_evidence"] == "unproven"


def test_noncanonical_request_uuid_is_rejected(snapshots):
    with sqlite3.connect(snapshots[0]) as db:
        saved = json.loads(db.execute("SELECT result_json FROM action_status").fetchone()[0])
        saved["request_id"] = REQUEST_ID.upper()
        db.execute("UPDATE action_status SET result_json=?", (json.dumps(saved),))
    assert run(snapshots)["finding"] == "frontend_identity_mismatch"


def test_duplicate_review_identity_is_ambiguous(snapshots):
    with sqlite3.connect(snapshots[0]) as db:
        db.execute("""INSERT INTO action_status SELECT 'another-session', owner, expires, result_json,
            updated_at, action_id, target_reference, prepare_transaction_id, prepare_snapshot,
            prepare_conversation_id, prepare_recovery_attempts, prepare_recovery_deadline FROM action_status""")
    assert run(snapshots)["finding"] == "review_reference_ambiguous"


def test_legacy_review_reference_matches(snapshots):
    legacy = "a" * 32
    update(snapshots[0], "action_status", "action_id", legacy)
    result = cli.triage(*snapshots, review_reference(legacy), now=NOW)
    assert result["finding"] == "exact_handoff_packet_evidence"
    assert result["snapshot_action_locked"] is True


def test_summary_counts_raw_exhausted_rows_even_when_identity_is_missing(snapshots):
    with sqlite3.connect(snapshots[0]) as db:
        db.execute("DELETE FROM chat_sessions")
    result = cli.triage(*snapshots, now=NOW)
    assert result["scope"] == "offline_snapshots_only"
    assert result["unresolved_prepare_count"] == result["recovery_exhausted_count"] == 1
    assert result["findings"] == {"frontend_identity_mismatch": 1}
    assert result["snapshot_action_locked"] is True


def test_summary_counts_unclassified_json_and_invalid_review_id(snapshots):
    update(snapshots[0], "action_status", "action_id", "invalid-action-id")
    result = cli.triage(*snapshots, now=NOW)
    assert result["unresolved_prepare_count"] == result["recovery_exhausted_count"] == 1
    assert result["review_reference_unavailable_count"] == 1
    update(snapshots[0], "action_status", "result_json", "invalid-json")
    result = cli.triage(*snapshots, now=NOW)
    assert result["unclassified_action_status_count"] == 1
    assert result["unresolved_prepare_count"] == 0


def spy_connections(monkeypatch):
    original = sqlite3.connect
    traces = []

    def connect(*args, **kwargs):
        assert "mode=ro&immutable=1" in args[0]
        assert kwargs["uri"] is True
        db = original(*args, **kwargs)
        db.set_trace_callback(traces.append)
        return db

    monkeypatch.setattr(cli.sqlite3, "connect", connect)
    return traces


def test_no_state_ledger_writes_bytes_rows_or_extra_files(snapshots, monkeypatch):
    parent = snapshots[0].parent
    before_files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.iterdir()}
    row_counts = []
    for path in snapshots:
        with sqlite3.connect(path) as db:
            tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            row_counts.append({table: db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in tables})
    with monkeypatch.context() as scope:
        traces = spy_connections(scope)
        run(snapshots)
        cli.triage(*snapshots, now=NOW)
    after_files = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in parent.iterdir()}
    assert before_files == after_files
    assert traces and not any(sql.lstrip().split()[0].upper() in {
        "INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP", "VACUUM", "ATTACH"
    } for sql in traces)
    for path, expected in zip(snapshots, row_counts):
        with sqlite3.connect(path) as db:
            assert expected == {table: db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0] for table in expected}


def test_readonly_connection_refuses_a_write(snapshots):
    with cli.readonly_snapshot(snapshots[1], cli._MCP_COLUMNS) as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("DELETE FROM action_pending")
        assert db.total_changes == 0


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_unconsolidated_snapshot_is_rejected(snapshots, suffix):
    Path(str(snapshots[0]) + suffix).write_bytes(b"synthetic-sidecar")
    with pytest.raises(cli.SnapshotError, match="snapshot_not_consolidated"):
        cli.triage(*snapshots, REFERENCE, now=NOW)


def test_same_snapshot_path_is_rejected(snapshots):
    with pytest.raises(cli.SnapshotError, match="snapshot_paths_not_distinct"):
        cli.triage(snapshots[0], snapshots[0], REFERENCE, now=NOW)


def test_missing_snapshot_is_not_created(snapshots):
    missing = snapshots[0].parent / "missing.sqlite3"
    with pytest.raises(cli.SnapshotError, match="snapshot_unavailable"):
        cli.triage(missing, snapshots[1], REFERENCE, now=NOW)
    assert not missing.exists()


@pytest.mark.parametrize("database,table", [(0, "chat_sessions"), (1, "sessions")])
def test_duplicate_saved_session_identity_is_rejected(snapshots, database, table):
    with sqlite3.connect(snapshots[database]) as db:
        db.execute(f"CREATE TABLE duplicate_identity AS SELECT * FROM {table}")
        db.execute(f"INSERT INTO duplicate_identity SELECT * FROM {table}")
        db.execute(f"DROP TABLE {table}")
        db.execute(f"ALTER TABLE duplicate_identity RENAME TO {table}")
    result = run(snapshots)
    assert result["finding"] == ("frontend_identity_mismatch" if database == 0 else "mcp_identity_mismatch")
    assert result["handoff_evidence"] == result["case_evidence"] == "unproven"


def test_summary_reports_ambiguous_review_reference(snapshots):
    with sqlite3.connect(snapshots[0]) as db:
        db.execute("""INSERT INTO action_status SELECT 'another-session', owner, expires, result_json,
            updated_at, action_id, target_reference, prepare_transaction_id, prepare_snapshot,
            prepare_conversation_id, prepare_recovery_attempts, prepare_recovery_deadline FROM action_status""")
    result = cli.triage(*snapshots, now=NOW)
    assert result["unresolved_prepare_count"] == result["recovery_exhausted_count"] == 2
    assert result["findings"] == {"review_reference_ambiguous": 2}


def test_absent_reference_and_empty_summary_do_not_assert_snapshot_or_live_lock(snapshots):
    result = cli.triage(*snapshots, "rev_" + "0" * 24, now=NOW)
    assert result["finding"] == "review_reference_not_found"
    assert result["snapshot_action_locked"] == result["live_action_lock"] == "unproven"
    with sqlite3.connect(snapshots[0]) as db:
        db.execute("DELETE FROM action_status")
    summary = cli.triage(*snapshots, now=NOW)
    assert summary["unresolved_prepare_count"] == 0
    assert summary["snapshot_action_locked"] == summary["live_action_lock"] == "unproven"


def test_input_hashes_are_reported_and_input_changes_are_rejected(snapshots, monkeypatch):
    result = run(snapshots)
    assert result["snapshot_sha256"] == {
        "frontend": hashlib.sha256(snapshots[0].read_bytes()).hexdigest(),
        "mcp": hashlib.sha256(snapshots[1].read_bytes()).hexdigest(),
    }
    original = cli._read_report

    def change_after_read(*args, **kwargs):
        output = original(*args, **kwargs)
        with snapshots[0].open("ab") as source:
            source.write(b"synthetic-external-change")
        return output

    monkeypatch.setattr(cli, "_read_report", change_after_read)
    with pytest.raises(cli.SnapshotError, match="snapshot_changed_during_read"):
        cli.triage(*snapshots, REFERENCE, now=NOW)


def test_canonicalization_failure_is_a_fixed_redacted_finding(snapshots, monkeypatch):
    def fail(*args):
        raise ValueError("private-sentinel-canonicalization-error")

    monkeypatch.setattr(cli, "principal_binding", fail)
    result = run(snapshots)
    assert result["finding"] == "frontend_identity_mismatch"
    assert "private-sentinel" not in json.dumps(result)


def test_missing_schema_is_rejected_without_migration(snapshots):
    with sqlite3.connect(snapshots[1]) as db:
        db.execute("DROP TABLE sandbox_handoffs")
    before = snapshots[1].read_bytes()
    with pytest.raises(cli.SnapshotError, match="snapshot_schema_unavailable"):
        cli.triage(*snapshots, REFERENCE, now=NOW)
    assert snapshots[1].read_bytes() == before


def test_cli_json_errors_are_redacted_and_fail_unresolved(snapshots, capsys):
    code = cli.main(["--frontend-snapshot", str(snapshots[0]), "--mcp-snapshot", str(snapshots[1]),
                     "--review-reference", "invalid-private-secret"])
    result = json.loads(capsys.readouterr().out)
    assert code == 2
    assert result["finding"] == "invalid_review_reference"
    assert result["snapshot_action_locked"] == "unproven"
    assert "invalid-private-secret" not in json.dumps(result)
