"""Host snapshot evidence, admission isolation, replay, recovery and privacy."""
import asyncio
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
import uuid

import pytest

from analytics.extract import build
from analytics.report import summarize
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt
from tests.test_dispute_action_host import general_handoff, joined
from tests.test_dispute_bank_read import bank, dataset


NOW = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)
TARGET = "txn_" + "b" * 24
HANDLE = "private_pending_handle_" + "a" * 21
OWNER = "private-owner"
CUSTOMER = "private-customer"
SESSION = "private-session"
EXPIRY = int((NOW + timedelta(hours=1)).timestamp())


def _pending():
    return {"state": "pending_confirmation", "pending_handle": HANDLE,
            "snapshot": "private-snapshot", "transaction": action_facts(), "target_reference": TARGET}


def _intake():
    return {"state": "intake_verified", "receipt": action_receipt(snapshot="private-snapshot")}


def _source(tmp_path, result=None):
    path = tmp_path / "frontend-chat.sqlite3"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE chat_sessions(session_id TEXT PRIMARY KEY, owner TEXT, expires INTEGER,
                conversation_id TEXT, customer_id TEXT, subject TEXT, revoked INTEGER DEFAULT 0);
            CREATE TABLE chat_messages(id INTEGER PRIMARY KEY,session_id TEXT,operation TEXT,role TEXT,text TEXT);
            CREATE TABLE action_status(session_id TEXT PRIMARY KEY,owner TEXT,expires INTEGER,
                result_json TEXT,updated_at INTEGER,target_reference TEXT,action_id TEXT,
                prepare_recovery_attempts INTEGER,prepare_recovery_deadline INTEGER);
            CREATE TABLE cancelled_action_handles(session_id TEXT,handle_hash TEXT,owner TEXT,
                expires INTEGER,cancelled_at INTEGER,PRIMARY KEY(session_id,handle_hash));
            CREATE TABLE pending_revocations(session_id TEXT PRIMARY KEY,owner TEXT,expires INTEGER,
                subject TEXT,state TEXT,updated_at INTEGER);
        """)
        db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,0)",
                   (SESSION, OWNER, EXPIRY, "language-conversation", CUSTOMER, "private-subject"))
        db.execute("INSERT INTO action_status VALUES (?,?,?,?,?,?,?,?,?)",
                   (SESSION, OWNER, EXPIRY, json.dumps(result or _pending()), int(NOW.timestamp()),
                    TARGET, str(uuid.uuid4()), 0, 0))
    return path


def _build(tmp_path, sources, **kwargs):
    out = tmp_path / "analytics.sqlite3"
    build(out, chat_dbs=sources, now=NOW, **kwargs)
    return out, summarize(out)["current_host_snapshot"]


def _update(path, sql, args=()):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(sql, args)


def _copy(source, target):
    with closing(sqlite3.connect(source)) as db, closing(sqlite3.connect(target)) as duplicate:
        db.backup(duplicate)
    return target


@pytest.mark.parametrize("result,expected", [
    (_pending(), "pending_confirmation"),
    (_intake(), "verified_simulated_intake"),
    ({"state": "existing_case_verified", "snapshot": "new-current-snapshot",
      "transaction": action_facts(), "receipt": action_receipt(snapshot="original-old")},
     "verified_existing_simulated_intake"),
    ({"state": "handoff_verified", "handoff": action_handoff()}, "verified_handoff_request"),
    ({"state": "handoff_unverified"}, "handoff_unverified"),
])
def test_host_current_outcomes_are_distinct(result, expected, tmp_path):
    source = _source(tmp_path, result)
    before = source.read_bytes()
    out, report = _build(tmp_path, [source])
    assert report["outcomes"] == {expected: 1}
    assert report["denominators"]["current_action_slots"] == 1
    assert report["source"] == "persisted_frontend_host_projection"
    assert source.read_bytes() == before
    assert report["time_coverage"]["action_updated_through"] == NOW.isoformat().replace("+00:00", "Z")
    if expected.startswith("verified"):
        assert report["time_coverage"]["verified_record_created_from"] == "2026-09-29T15:00:00Z"
    with closing(sqlite3.connect(out)) as db:
        dump = "\n".join(db.iterdump())
    for value in (OWNER, CUSTOMER, SESSION, TARGET, HANDLE, "private-subject", "private-snapshot",
                  "CMP-SBX-abcdefgh", "HOF-abcdefgh", "Cuenta Ahorro", str(source)):
        assert value not in dump


def test_saved_host_completion_does_not_rewrite_planned_workflow_outcome(tmp_path):
    source = _source(tmp_path, _intake())
    workflow = tmp_path / "workflow.sqlite3"
    with closing(sqlite3.connect(workflow)) as db, db:
        db.execute("CREATE TABLE dispute_turns(customer,session,conversation,turn_id,state_json)")
        db.execute("INSERT INTO dispute_turns VALUES (?,?,?,?,?)", (CUSTOMER, SESSION, "workflow-context", "turn",
            json.dumps({"workflow_state": {"pending": {"type": "awaiting_confirmation"},
                       "policy_decision": {"response_mode": "CONFIRM_ACTION"}}})))
    out, report = _build(tmp_path, [source], workflow_dbs=[workflow])
    assert summarize(out)["outcomes"] == {"awaiting_confirmation": 1}
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    assert report["workflow_attribution"].startswith("unknown")


@pytest.mark.parametrize("column,value", [("owner", "foreign-customer-owner"), ("session_id", "foreign-session"),
                                         ("expires", EXPIRY + 1)])
def test_foreign_admission_cannot_supply_completion(tmp_path, column, value):
    source = _source(tmp_path, _intake())
    _update(source, f"UPDATE action_status SET {column}=?", (value,))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {}
    assert report["denominators"]["rejected_binding_source_rows"] == 1
    assert report["verified_terminal_slot_rate"] is None


@pytest.mark.parametrize("field,value", [("simulated", False), ("status", "resolved"),
                                        ("created_at", "2027-01-01T00:00:00Z")])
def test_unverified_or_future_receipt_does_not_supply_completion(tmp_path, field, value):
    receipt = _intake()
    receipt["receipt"][field] = value
    source = _source(tmp_path, receipt)
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"invalid_evidence": 1}
    assert report["verified_terminal_slot_rate"] == 0


@pytest.mark.parametrize("result", [None, [], "private-error", {"state": "fake-private-state"}])
def test_malformed_saved_result_is_bounded(tmp_path, result):
    source = _source(tmp_path)
    _update(source, "UPDATE action_status SET result_json=?", (json.dumps(result),))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"invalid_evidence": 1}


@pytest.mark.parametrize("change", ["snapshot", "facts", "handoff_reason", "handoff_packet"])
def test_contradictory_terminal_evidence_is_not_verified(tmp_path, change):
    result = {**_intake(), "snapshot": "private-snapshot", "transaction": action_facts()}
    if change == "snapshot":
        result["snapshot"] = "different"
    elif change == "facts":
        result["transaction"]["amount"] = "999.00"
    else:
        result = {"state": "handoff_verified", "reason": "high_risk", "handoff": action_handoff()}
        if change == "handoff_packet":
            result["handoff"]["packet"]["human_responded"] = True
    source = _source(tmp_path, result)
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"invalid_evidence": 1}


def test_old_blob_columns_cannot_abort_other_host_observations(tmp_path):
    source = _source(tmp_path, _intake())
    _update(source, "ALTER TABLE action_status ADD COLUMN legacy_unrelated BLOB")
    _update(source, "UPDATE action_status SET legacy_unrelated=?,action_id=?", (b"private-legacy", b"private-malformed-id"))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    _update(source, "UPDATE action_status SET target_reference=?", (b"private-invalid-target",))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"invalid_evidence": 1}


def test_prior_and_nested_receipts_do_not_complete_current_slot(tmp_path):
    result = {"state": "prepare_unverified", "prior_receipt": {"target_reference": TARGET,
              "receipt": action_receipt()}}
    source = _source(tmp_path, result)
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"prepare_unverified": 1}
    assert report["retained_prior_evidence_slots"]["receipt"] == 1
    assert report["verified_terminal_slot_rate"] == 0
    result = {"state": "action_unverified", "handoff": {
        "state": "handoff_verified", "handoff": action_handoff(snapshot=None)}}
    _update(source, "UPDATE action_status SET result_json=?", (json.dumps(result),))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"action_unverified": 1}
    assert report["verified_terminal_slot_rate"] == 0


def test_duplicate_replay_copies_and_rebuilds_do_not_double_count(tmp_path):
    source = _source(tmp_path, _intake())
    duplicate = _copy(source, tmp_path / "copy.sqlite3")
    _, report = _build(tmp_path, [source, source, duplicate])
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    assert report["denominators"]["admitted_session_snapshots"] == 1
    assert report["sources"] == {"supported": 2}
    _, rebuilt = _build(tmp_path, [source, duplicate])
    assert rebuilt == report


@pytest.mark.parametrize("change", ["pending", "different_receipt", "foreign_customer"])
def test_conflicting_source_copies_fail_closed(tmp_path, change):
    source = _source(tmp_path, _intake())
    duplicate = _copy(source, tmp_path / "copy.sqlite3")
    if change == "foreign_customer":
        _update(duplicate, "UPDATE chat_sessions SET customer_id='foreign-customer'")
    else:
        result = _pending() if change == "pending" else _intake()
        if change == "different_receipt":
            result["receipt"]["id"] = "CMP-SBX-ijklmnop"
        _update(duplicate, "UPDATE action_status SET result_json=?", (json.dumps(result),))
    _, report = _build(tmp_path, [source, duplicate])
    assert report["outcomes"] == {"conflicting_snapshot": 1}
    assert report["verified_terminal_slot_rate"] == 0


def test_revocation_preserves_verified_receipt_but_separates_lifecycle(tmp_path):
    source = _source(tmp_path, _intake())
    _update(source, "UPDATE chat_sessions SET revoked=1")
    _update(source, "INSERT INTO pending_revocations VALUES (?,?,?,?,?,?)",
            (SESSION, OWNER, EXPIRY, "private-subject", "confirmed", int(NOW.timestamp())))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    assert report["lifecycle"]["locally_revoked_session_snapshots"] == 1
    assert report["lifecycle"]["revocation_states"] == {"confirmed": 1}
    _update(source, "UPDATE pending_revocations SET owner='foreign-owner'")
    _, report = _build(tmp_path, [source])
    assert report["lifecycle"]["revocation_states"] == {"invalid_binding": 1}


def test_expiry_is_not_a_claim_that_a_saved_receipt_was_cancelled(tmp_path):
    source = _source(tmp_path, _intake())
    expired = int((NOW - timedelta(hours=1)).timestamp())
    _update(source, "UPDATE chat_sessions SET expires=?", (expired,))
    _update(source, "UPDATE action_status SET expires=?", (expired,))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    assert report["lifecycle"]["expired_session_snapshots"] == 1
    assert report["lifecycle"]["retained_cancelled_handles"] == 0


def test_recovery_attempt_metadata_does_not_imply_a_receipt(tmp_path):
    source = _source(tmp_path, {"state": "prepare_unverified", "recovery_exhausted": True})
    _update(source, "UPDATE action_status SET prepare_recovery_attempts=3,prepare_recovery_deadline=?", (EXPIRY,))
    _, report = _build(tmp_path, [source])
    assert report["outcomes"] == {"prepare_unverified": 1}
    assert report["recovery"] == {"slots_with_attempts": 1, "exhausted_slots": 1}


def test_cancellation_is_retained_history_not_a_terminal_action(tmp_path):
    source = _source(tmp_path)
    _update(source, "DELETE FROM action_status")
    _update(source, "INSERT INTO cancelled_action_handles VALUES (?,?,?,?,?)",
            (SESSION, hashlib.sha256(HANDLE.encode()).hexdigest(), OWNER, EXPIRY, int(NOW.timestamp())))
    duplicate = _copy(source, tmp_path / "copy.sqlite3")
    _, report = _build(tmp_path, [source, duplicate])
    assert report["outcomes"] == {}
    assert report["lifecycle"]["retained_cancelled_handles"] == 1
    _update(source, "UPDATE cancelled_action_handles SET owner='foreign-owner'")
    _, report = _build(tmp_path, [source])
    assert report["lifecycle"]["retained_cancelled_handles"] == 0


def test_old_host_and_analytics_schemas_remain_reportable(tmp_path):
    source = _source(tmp_path, _intake())
    _update(source, "ALTER TABLE action_status DROP COLUMN target_reference")
    out, report = _build(tmp_path, [source])
    assert report["status"] == "unavailable"
    assert report["sources"] == {"unsupported_schema": 1}
    assert report["outcomes"] == {}
    for table in ("host_sources", "host_actions", "host_sessions", "host_cancellations"):
        _update(out, f"DROP TABLE {table}")
    assert summarize(out)["current_host_snapshot"]["status"] == "unavailable"
    build(out, chat_dbs=[source], now=NOW)
    assert summarize(out)["current_host_snapshot"]["sources"] == {"unsupported_schema": 1}


def _joined_report(joined, tmp_path):
    out = tmp_path / "analytics.sqlite3"
    build(out, chat_dbs=[joined.chat._db_path])
    return summarize(out)["current_host_snapshot"]


def test_real_host_confirmation_replay_and_revocation(joined, tmp_path):
    pending = asyncio.run(joined.prepare())
    assert _joined_report(joined, tmp_path)["outcomes"] == {"pending_confirmation": 1}
    confirmed = asyncio.run(joined.confirm(pending["pending_handle"]))
    assert confirmed["state"] == "intake_verified"
    asyncio.run(joined.confirm(pending["pending_handle"]))
    assert _joined_report(joined, tmp_path)["outcomes"] == {"verified_simulated_intake": 1}
    joined.chat.queue_revoke(joined.customer, joined.sid, joined.expiry)
    report = _joined_report(joined, tmp_path)
    assert report["outcomes"] == {"verified_simulated_intake": 1}
    assert report["lifecycle"]["revocation_states"] == {"pending": 1}


def test_real_host_cancellation_and_handoff(joined, tmp_path):
    pending = asyncio.run(joined.prepare())
    assert joined.chat.cancel_pending(joined.customer, joined.sid, joined.expiry, handle=pending["pending_handle"])
    report = _joined_report(joined, tmp_path)
    assert report["outcomes"] == {}
    assert report["lifecycle"]["retained_cancelled_handles"] == 1
    general_handoff(joined)
    assert _joined_report(joined, tmp_path)["outcomes"] == {"verified_handoff_request": 1}


def test_real_host_receipt_recovery_is_observed_only_after_readback(joined, tmp_path):
    pending = asyncio.run(joined.prepare())
    confirmed = asyncio.run(joined.confirm(pending["pending_handle"]))
    # Model an admitted lost response: the bank committed but the saved host
    # slot remains uncertain until the existing status endpoint reads it back.
    uncertain = {**deepcopy(pending), "state": "action_unverified"}
    with joined.chat._connection() as db:
        db.execute("UPDATE action_status SET result_json=?", (json.dumps(uncertain),))
    assert _joined_report(joined, tmp_path)["outcomes"] == {"action_unverified": 1}
    recovered = asyncio.run(joined.chat.action_status(joined.customer, joined.sid, joined.expiry))
    assert recovered["receipt"] == confirmed["receipt"]
    assert _joined_report(joined, tmp_path)["outcomes"] == {"verified_simulated_intake": 1}
