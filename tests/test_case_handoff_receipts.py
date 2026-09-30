"""Fictional local stores only: no MCP transport, provider, S3 or live action."""
from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import sqlite3
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from banking_mcp.actions import ACTION, HANDOFF_PACKET_SCHEMA, Actions
from banking_mcp.security import BankError, Principal, StateStore


class FictionalRepository:
    def __init__(self, root, now):
        self.snapshot_info = SimpleNamespace(id="fictional-snapshot", build=root / "fictional-snapshot")
        self.snapshot_info.build.mkdir()
        (self.snapshot_info.build / "snapshot.json").write_text(json.dumps({
            "source_fingerprint": "fictional-generated-source"}), encoding="utf-8")
        event = datetime.fromtimestamp(now, timezone.utc).replace(tzinfo=None) - timedelta(days=10)
        self.rows = {
            "fixture-charge-A": {"owner": "fictional-owner-A", "transaction_date": event,
                                 "transaction_status": "Approved"},
            "fixture-charge-B": {"owner": "fictional-owner-B", "transaction_date": event,
                                 "transaction_status": "Approved"},
        }

    def snapshot(self):
        return self.snapshot_info

    def assert_current_snapshot(self, expected):
        if self.snapshot_info.id != expected:
            raise BankError("snapshot_changed")

    def owned_transaction_id(self, principal, transaction_id, build):
        if build != self.snapshot_info.id:
            raise BankError("snapshot_changed")
        row = self.rows.get(transaction_id)
        if not row or row["owner"] != principal.customer:
            raise BankError("reference_unavailable")
        return self.snapshot_info, copy.deepcopy(row)

    def _visible(self, row, snapshot):
        return {"transaction_reference": "txn_012345abcdef",
                "transaction_date": row["transaction_date"].isoformat(),
                "process_date": row["transaction_date"].date().isoformat(),
                "amount": "12.50", "currency": "MXN", "status": row["transaction_status"],
                "merchant": "Fictional store", "transaction_type": "Purchase", "channel": "POS",
                "product": "Credit Card"}


class DelayAfterAttemptStore(StateStore):
    """Create a deterministic overlap after marker commit, outside the DB gate."""
    @contextmanager
    def connect(self):
        attempted = False
        class ObservedConnection:
            def __init__(self, db):
                self.db = db
            def __getattr__(self, field):
                return getattr(self.db, field)
            def execute(self, statement, args=()):
                nonlocal attempted
                result = self.db.execute(statement, args)
                attempted = attempted or "SET confirmation_state='attempted'" in statement
                return result
        with super().connect() as db:
            yield ObservedConnection(db)
        if attempted:
            time.sleep(.2)


def _confirm_case_process(path, repository, coverage_start, evidence, principal, handle, now, barrier, results):
    actions = Actions(DelayAfterAttemptStore(path), repository, coverage_start, evidence,
                      "fictional-prepare-secret" * 3)
    actions.clock = lambda: now
    try:
        barrier.wait(timeout=15)
        results.put(actions.confirm(principal, handle, True))
    except Exception as error:
        results.put({"error": str(error)})


@pytest.fixture
def local(tmp_path):
    now = time.time() - 5
    store = StateStore(tmp_path / "state.db")
    repository = FictionalRepository(tmp_path, now)
    evidence = tmp_path / "fictional-evidence.json"
    evidence.write_text(json.dumps({"build_id": repository.snapshot_info.id,
        "source_fingerprint": "fictional-generated-source", "transactions": {
            key: {"historical_complaints": "clear_in_snapshot", "duplicate_signal": "clear",
                  "fraud_score": 0, "amount_usd": 12.50} for key in repository.rows}}), encoding="utf-8")
    coverage_start = int(now) - 90000
    store.attest_sandbox_coverage(coverage_start, "synthetic:issue21-fictional-local-ledger")
    actions = Actions(store, repository, coverage_start, evidence, "fictional-prepare-secret" * 3)
    actions.clock = lambda: now
    owner = Principal("fictional-sub-A", "fictional-owner-A", "session-A", "conversation-A",
                      int(time.time()) + 600)
    return SimpleNamespace(actions=actions, store=store, repository=repository, evidence=evidence,
                           owner=owner, now=now, root=tmp_path)


def prepare(local):
    return local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id,
                                 str(uuid.uuid4()))


def create_case(local):
    pending = prepare(local)
    assert pending["decision"] == "intake"
    receipt = local.actions.confirm(local.owner, pending["pending_handle"], True)
    return pending, receipt


def test_verified_local_absence_is_scoped_and_historical_signal_is_not_a_case(local):
    absent = local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    assert absent == {"state": "not_found", "receipt": None,
                      "coverage": "sandbox_only", "source": "sandbox_cases"}
    signals = json.loads(local.evidence.read_text())
    signals["transactions"]["fixture-charge-A"]["historical_complaints"] = "exact_open_case"
    local.evidence.write_text(json.dumps(signals))
    pending = prepare(local)
    assert pending["decision"] == "handoff" and pending["reason"] == "duplicate_review"
    assert pending["existing_case"] == absent
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == {
        "state": "action_unverified", "receipt": None}


def test_persisted_exact_case_is_read_back_across_restart_without_another_case(local):
    pending, receipt = create_case(local)
    assert receipt["receipt"]["status"] == "received"
    with local.store.connect() as db:
        saved = json.loads(db.execute("SELECT receipt_json FROM sandbox_case_receipts").fetchone()[0])
    assert saved == receipt["receipt"]
    restarted = Actions(StateStore(local.store.path), local.repository, None, None,
                        "fictional-prepare-secret" * 3)
    restarted.clock = local.actions.clock
    projection = restarted.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    assert projection["state"] == "verified" and projection["receipt"] == saved
    # Existing status is a read: current risk, coverage and 120-day NEW intake
    # eligibility cannot erase a previously persisted exact owner-bound receipt.
    restarted.clock = lambda: local.now + 150 * 86400
    again = restarted.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id,
                              str(uuid.uuid4()))
    assert again["decision"] == "existing_case" and again["reason"] is None
    assert again["existing_case"]["receipt"] == saved
    with pytest.raises(BankError, match="handoff_required"):
        restarted.confirm(local.owner, again["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 1
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == receipt


def test_case_read_is_owner_bound_and_receipt_handle_remains_session_bound(local):
    pending, receipt = create_case(local)
    foreign = Principal("fictional-sub-B", "fictional-owner-B", "session-B", "conversation-B",
                        int(time.time()) + 600)
    with pytest.raises(BankError, match="reference_unavailable"):
        local.actions.local_case_status(foreign, "fixture-charge-A", local.repository.snapshot_info.id)
    with pytest.raises(BankError, match="reference_unavailable"):
        local.actions.receipt(foreign, pending["pending_handle"])
    same_owner = Principal(local.owner.subject, local.owner.customer, "new-session", "new-conversation",
                           int(time.time()) + 600)
    assert local.actions.local_case_status(same_owner, "fixture-charge-A", local.repository.snapshot_info.id)["receipt"] == receipt["receipt"]
    with pytest.raises(BankError, match="reference_unavailable"):
        local.actions.receipt(same_owner, pending["pending_handle"])


def test_legacy_bare_case_is_unverified_and_never_recreated(local):
    snapshot, row = local.repository.owned_transaction_id(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    with local.store.connect() as db:
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)", (
            "CMP-SBX-ABCDEFGH", local.owner.customer, "fixture-charge-A", ACTION,
            snapshot.id, local.now, json.dumps(local.repository._visible(row, snapshot))))
    pending = prepare(local)
    assert pending["decision"] == "handoff" and pending["reason"] == "action_unverified"
    assert pending["existing_case"]["state"] == "action_unverified"
    with pytest.raises(BankError, match="handoff_required"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1


@pytest.mark.parametrize("mutation", ["status", "amount", "missing", "duplicate_key", "other_snapshot"])
def test_corrupt_or_unmatched_persisted_receipt_is_not_promoted(local, mutation):
    pending, result = create_case(local)
    receipt = copy.deepcopy(result["receipt"])
    if mutation == "status":
        receipt["status"] = "resolved"
    elif mutation == "amount":
        receipt["transaction"]["amount"] = "9999.00"
    elif mutation == "other_snapshot":
        receipt["snapshot"] = "foreign-snapshot"
    encoded = json.dumps(receipt)
    if mutation == "duplicate_key":
        encoded = encoded[:-1] + ',"status":"received"}'
    with local.store.connect() as db:
        if mutation == "missing":
            db.execute("DELETE FROM sandbox_case_receipts")
        else:
            db.execute("UPDATE sandbox_case_receipts SET receipt_json=?", (encoded,))
    assert local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)["state"] == "action_unverified"
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == {"state": "action_unverified", "receipt": None}
    assert prepare(local)["reason"] == "action_unverified"


def test_missing_receipt_after_unresolved_intake_including_expiry_is_not_no_match(local):
    pending = prepare(local)
    assert pending["existing_case"]["state"] == "not_found"
    with local.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state='attempted'")
    local.actions.clock = lambda: local.now + 601
    status = local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    assert status["state"] == "action_unverified" and status["receipt"] is None
    again = prepare(local)
    assert again["decision"] == "handoff" and again["reason"] == "action_unverified"


def test_database_read_failure_never_becomes_not_found(local):
    class FailedStore:
        @contextmanager
        def connect(self):
            raise sqlite3.OperationalError("fictional read unavailable")
            yield
    local.actions.store = FailedStore()
    with pytest.raises(BankError, match="service_unavailable"):
        local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)


def test_new_intake_keeps_120_day_real_wall_eligibility_and_explicit_consent(local):
    local.repository.rows["fixture-charge-A"]["transaction_date"] = (
        datetime.fromtimestamp(local.now, timezone.utc).replace(tzinfo=None) - timedelta(days=121))
    old = prepare(local)
    assert old["decision"] == "handoff" and old["reason"] == "out_of_policy"
    with pytest.raises(BankError, match="confirmation_required"):
        local.actions.confirm(local.owner, old["pending_handle"], False)
    expired = Principal(local.owner.subject, local.owner.customer, local.owner.session,
                        local.owner.conversation, int(time.time()) - 1)
    with pytest.raises(BankError, match="authorization_denied"):
        local.actions.local_case_status(expired, "fixture-charge-A", local.repository.snapshot_info.id)


def test_handoff_packet_contains_fresh_owned_facts_and_bounded_unanswered_data(local):
    pending = prepare(local)
    questions = ["¿Reconoce este comercio?", "Qual foi a data indicada?"]
    request_id = str(uuid.uuid4())
    result = local.actions.handoff(local.owner, "customer_request", pending["pending_handle"],
                                   request_id, questions)
    packet = result["handoff"]["packet"]
    provenance = packet["transaction_provenance"]
    assert provenance["source"] == "owned_serving_snapshot"
    assert provenance["snapshot"] == pending["snapshot"]
    assert abs(datetime.fromisoformat(provenance["as_of"].replace("Z", "+00:00")).timestamp() - time.time()) < 5
    assert packet == {"schema": HANDOFF_PACKET_SCHEMA, "transaction": pending["transaction"],
                      "transaction_provenance": provenance,
                      "reason": "customer_request", "unanswered_questions": questions,
                      "human_responded": False}
    assert result["handoff"]["facts"] == pending["transaction"]
    assert result["handoff"]["human_responded"] is False
    assert result["handoff"]["transaction_currentness"] == "same_snapshot"
    with local.store.connect() as db:
        row = db.execute("SELECT customer,binding,packet_json FROM sandbox_handoffs").fetchone()
    assert row[:2] == (local.owner.customer, local.owner.binding())
    assert json.loads(row[2]) == packet
    questions.append("Caller mutation cannot change saved packet")
    assert local.actions.read_handoff(local.owner, result["handoff"]["id"]) == result
    assert local.actions.handoff(local.owner, "customer_request", pending["pending_handle"],
                                 request_id, questions[:2]) == result
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.handoff(local.owner, "customer_request", pending["pending_handle"],
                              request_id, ["Different question"])
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1


def test_no_target_handoff_does_not_invent_selected_charge_or_pickup(local):
    result = local.actions.handoff(local.owner, "emergency", None, str(uuid.uuid4()), [])
    assert result["handoff"]["facts"] == {} and result["handoff"]["snapshot"] is None
    assert result["handoff"]["packet"]["transaction"] is None
    assert result["handoff"]["packet"]["transaction_provenance"] is None
    assert result["handoff"]["transaction_currentness"] == "not_applicable"
    assert result["handoff"]["packet"]["human_responded"] is False
    assert local.actions.read_handoff(local.owner, result["handoff"]["id"]) == result


@pytest.mark.parametrize("questions", [["x"] * 9, ["x" * 241], [""], ["  "], [5], "question", ["x\ny"]])
def test_handoff_rejects_unbounded_or_wrongly_typed_questions_before_write(local, questions):
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.handoff(local.owner, "customer_request", None, str(uuid.uuid4()), questions)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0


def test_selected_handoff_rechecks_current_owned_facts_and_foreign_handles(local):
    pending = prepare(local)
    foreign = Principal("fictional-sub-B", "fictional-owner-B", "session-B", "conversation-B", int(time.time()) + 600)
    with pytest.raises(BankError, match="reference_unavailable"):
        local.actions.handoff(foreign, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    local.repository.rows["fixture-charge-A"]["transaction_status"] = "Reversed"
    with pytest.raises(BankError, match="snapshot_changed"):
        local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0


@pytest.mark.parametrize("mutation", ["legacy", "schema", "reason", "human", "transaction", "questions", "extra"])
def test_legacy_or_forged_handoff_packet_cannot_prove_creation(local, mutation):
    pending = prepare(local)
    result = local.actions.handoff(local.owner, "missing_evidence", pending["pending_handle"], str(uuid.uuid4()))
    packet = copy.deepcopy(result["handoff"]["packet"])
    if mutation == "schema":
        packet["schema"] = "foreign-schema"
    elif mutation == "reason":
        packet["reason"] = "emergency"
    elif mutation == "human":
        packet["human_responded"] = True
    elif mutation == "transaction":
        packet["transaction"]["amount"] = "999.00"
    elif mutation == "questions":
        packet["unanswered_questions"] = ["x"] * 9
    elif mutation == "extra":
        packet["agent_picked_up"] = True
    with local.store.connect() as db:
        db.execute("UPDATE sandbox_handoffs SET packet_json=?",
                   (None if mutation == "legacy" else json.dumps(packet),))
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.read_handoff(local.owner, result["handoff"]["id"])


def test_missing_handoff_durable_readback_does_not_return_created(local, monkeypatch):
    pending = prepare(local)
    original = local.actions.read_handoff
    def lost_packet(principal, handoff_id):
        with local.store.connect() as db:
            db.execute("DELETE FROM sandbox_handoffs WHERE id=?", (handoff_id,))
        return original(principal, handoff_id)
    monkeypatch.setattr(local.actions, "read_handoff", lost_packet)
    with pytest.raises(BankError, match="reference_unavailable"):
        local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))


def test_case_association_survives_new_snapshot_and_conversation_without_second_case(local):
    pending, saved = create_case(local)
    local.repository.snapshot_info.id = "fictional-new-snapshot"
    new_owner = Principal(local.owner.subject, local.owner.customer, "next-session", "next-conversation",
                          int(time.time()) + 600)
    projection = local.actions.local_case_status(new_owner, "fixture-charge-A", "fictional-new-snapshot")
    assert projection["state"] == "verified" and projection["receipt"] == saved["receipt"]
    assert projection["receipt"]["snapshot"] == "fictional-snapshot"
    again = local.actions.prepare(new_owner, "fixture-charge-A", "fictional-new-snapshot", str(uuid.uuid4()))
    assert again["decision"] == "existing_case" and again["snapshot"] == "fictional-new-snapshot"
    assert local.actions.receipt(new_owner, again["pending_handle"]) == saved
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        # A tampered pending snapshot is different from a legitimate new build:
        # it no longer agrees with its own persisted prepare result.
        db.execute("UPDATE action_pending SET snapshot='fictional-tampered-snapshot'")
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == {"state": "action_unverified", "receipt": None}


def test_repeated_original_prepare_after_confirm_returns_verified_existing_case(local):
    request_id = str(uuid.uuid4())
    initial = local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    saved = local.actions.confirm(local.owner, initial["pending_handle"], True)
    again = local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    assert again["decision"] == "existing_case"
    assert again["existing_case"]["receipt"] == saved["receipt"]
    assert again["pending_handle"] == initial["pending_handle"]
    # Original confirmation retry remains a read-back of that exact case.
    assert local.actions.confirm(local.owner, initial["pending_handle"], True) == saved
    with local.store.connect() as db:
        assert db.execute("SELECT decision FROM action_pending").fetchone()[0] == "intake"
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "verified"
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1


def test_snapshot_change_before_handoff_create_fails_closed_without_write(local):
    pending = prepare(local)
    local.repository.snapshot_info.id = "fictional-next-snapshot"
    with pytest.raises(BankError, match="snapshot_changed"):
        local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0


def test_saved_handoff_after_rotation_retains_historical_provenance_and_discloses_currentness(local, monkeypatch):
    pending = prepare(local)
    saved = local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    local.repository.snapshot_info.id = "fictional-next-snapshot"
    historical = local.actions.read_handoff(local.owner, saved["handoff"]["id"])
    assert historical["handoff"]["packet"] == saved["handoff"]["packet"]
    assert historical["handoff"]["transaction_currentness"] == "different_snapshot"
    assert historical["handoff"]["packet"]["transaction_provenance"]["snapshot"] == "fictional-snapshot"
    def unavailable():
        raise BankError("dataset_unavailable")
    monkeypatch.setattr(local.repository, "snapshot", unavailable)
    uncertain = local.actions.read_handoff(local.owner, saved["handoff"]["id"])
    assert uncertain["handoff"]["transaction_currentness"] == "unknown"
    assert uncertain["handoff"]["packet"] == saved["handoff"]["packet"]
    assert uncertain["handoff"]["human_responded"] is False


@pytest.mark.parametrize("provenance", [None, {"source": "caller"},
    {"source": "owned_serving_snapshot", "snapshot": "foreign-snapshot", "as_of": "2026-09-29T00:00:00Z"},
    {"source": "owned_serving_snapshot", "snapshot": "fictional-snapshot", "as_of": "2026-09-29T00:00:00"}])
def test_selected_packet_without_exact_server_provenance_is_unverified(local, provenance):
    pending = prepare(local)
    result = local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    packet = result["handoff"]["packet"]
    packet["transaction_provenance"] = provenance
    with local.store.connect() as db:
        db.execute("UPDATE sandbox_handoffs SET packet_json=?", (json.dumps(packet),))
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.read_handoff(local.owner, result["handoff"]["id"])


def test_merely_prepared_intent_replays_exactly_and_is_not_an_uncertain_write(local):
    request_id = str(uuid.uuid4())
    first = local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    assert local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id) == first
    assert local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)["state"] == "not_found"
    with local.store.connect() as db:
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "prepared"
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0


def test_case_write_failure_keeps_durable_attempt_marker_and_never_retries_or_claims_no_match(local, monkeypatch):
    request_id = str(uuid.uuid4())
    pending = local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    other_prepared = prepare(local)
    assert other_prepared["decision"] == "intake"
    original = local.store.connect
    insert_attempts = []
    class FailingWrite:
        def __init__(self, db):
            self.db = db
        def execute(self, statement, args=()):
            if "INSERT INTO sandbox_cases" in statement:
                insert_attempts.append(statement)
                raise sqlite3.OperationalError("fictional uncertain case write")
            return self.db.execute(statement, args)
    @contextmanager
    def fail_case_write():
        with original() as db:
            yield FailingWrite(db)
    monkeypatch.setattr(local.store, "connect", fail_case_write)
    with pytest.raises(sqlite3.OperationalError, match="fictional uncertain case write"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    with original() as db:
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "attempted"
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 0
    assert local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)["state"] == "action_unverified"
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == {"state": "action_unverified", "receipt": None}
    replay = local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    assert replay["decision"] == "handoff" and replay["reason"] == "action_unverified"
    fresh = prepare(local)
    assert fresh["decision"] == "handoff" and fresh["existing_case"]["state"] == "action_unverified"
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    # Another intent prepared BEFORE the uncertain write is not a retry escape.
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.confirm(local.owner, other_prepared["pending_handle"], True)
    assert len(insert_attempts) == 1


def test_legacy_pending_without_confirmation_state_is_uncertain_not_clean_absence(local):
    pending = prepare(local)
    with local.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state=NULL")
    assert local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)["state"] == "action_unverified"
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)


@pytest.mark.parametrize("operation", ["confirm", "handoff"])
def test_current_pointer_flip_between_owned_read_and_writer_does_not_persist_action(local, monkeypatch, operation):
    pending = prepare(local)
    original = local.repository.owned_transaction_id
    def flip_after_owned_read(principal, transaction_id, build):
        snapshot, row = original(principal, transaction_id, build)
        # Keep the returned immutable snapshot separate from the new pointer.
        old_snapshot = copy.copy(snapshot)
        local.repository.snapshot_info.id = "fictional-next-snapshot"
        return old_snapshot, row
    monkeypatch.setattr(local.repository, "owned_transaction_id", flip_after_owned_read)
    with pytest.raises(BankError, match="snapshot_changed"):
        if operation == "confirm":
            local.actions.confirm(local.owner, pending["pending_handle"], True)
        else:
            local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "prepared"


@pytest.mark.parametrize("corruption", ["attempted_decision", "prepared_result", "invalid_state"])
def test_corrupt_pending_intent_never_becomes_clean_local_absence(local, corruption):
    prepare(local)
    with local.store.connect() as db:
        if corruption == "attempted_decision":
            db.execute("UPDATE action_pending SET decision='handoff',confirmation_state='attempted'")
        elif corruption == "prepared_result":
            db.execute("UPDATE action_pending SET result_json='{}'")
        else:
            db.execute("UPDATE action_pending SET confirmation_state='unknown'")
    assert local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)["state"] == "action_unverified"


def test_two_threads_confirm_same_handle_read_one_case_after_committed_marker(local):
    pending = prepare(local)
    local.actions.store = DelayAfterAttemptStore(local.store.path)
    barrier = threading.Barrier(2)
    def confirm_together():
        barrier.wait(timeout=5)
        return local.actions.confirm(local.owner, pending["pending_handle"], True)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = list(executor.map(lambda _: confirm_together(), range(2)))
    assert first == second and first["state"] == "created"
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 1


def test_two_processes_confirm_same_handle_read_one_case_after_committed_marker(local):
    pending = prepare(local)
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    children = [context.Process(target=_confirm_case_process, args=(local.store.path, local.repository,
        local.actions.coverage_start, local.evidence, local.owner, pending["pending_handle"],
        local.now, barrier, results)) for _ in range(2)]
    try:
        for child in children:
            child.start()
        replies = [results.get(timeout=20) for _ in children]
        for child in children:
            child.join(timeout=10)
            assert child.exitcode == 0
        assert replies[0] == replies[1] and replies[0]["state"] == "created"
        with local.store.connect() as db:
            assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 1
    finally:
        for child in children:
            if child.is_alive():
                child.terminate()
                child.join(timeout=5)
        results.close()


def test_lost_handoff_response_same_uuid_after_snapshot_rotation_reads_original_packet(local):
    pending = prepare(local)
    request_id, questions = str(uuid.uuid4()), ["¿Reconoce este comercio?"]
    saved = local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], request_id, questions)
    local.repository.snapshot_info.id = "fictional-next-snapshot"
    recovered = local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], request_id, questions)
    assert recovered["handoff"]["id"] == saved["handoff"]["id"]
    assert recovered["handoff"]["packet"] == saved["handoff"]["packet"]
    assert recovered["handoff"]["transaction_currentness"] == "different_snapshot"
    assert recovered["handoff"]["human_responded"] is False
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.handoff(local.owner, "emergency", pending["pending_handle"], request_id, questions)
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.handoff(local.owner, "customer_request", pending["pending_handle"], request_id, ["Changed question"])
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1


def test_prepare_changed_identity_is_rejected_before_source_read(local, monkeypatch):
    request_id = str(uuid.uuid4())
    local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id, request_id)
    def must_not_read(*_):
        raise AssertionError("conflicting request must be rejected before data access")
    monkeypatch.setattr(local.repository, "owned_transaction_id", must_not_read)
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.prepare(local.owner, "fixture-charge-A", "changed-snapshot", request_id)
    with pytest.raises(BankError, match="invalid_arguments"):
        local.actions.prepare(local.owner, "fixture-charge-B", local.repository.snapshot_info.id, request_id)


def test_receipt_wait_checks_fresh_revocation_without_case_write(local, monkeypatch):
    pending = prepare(local)
    with local.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state='attempted'")
    poll_started = threading.Event()
    original = local.actions._assert_action_authorized
    checks = []
    def observe_authorization(db, principal):
        original(db, principal)
        checks.append(True)
        if len(checks) >= 2:
            poll_started.set()
    monkeypatch.setattr(local.actions, "_assert_action_authorized", observe_authorization)
    def revoke_during_poll():
        assert poll_started.wait(timeout=5)
        local.store.revoke(local.owner.session)
    with ThreadPoolExecutor(max_workers=1) as executor:
        revoke = executor.submit(revoke_during_poll)
        with pytest.raises(BankError, match="authorization_denied"):
            local.actions.confirm(local.owner, pending["pending_handle"], True)
        revoke.result(timeout=5)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "attempted"


def test_receipt_poll_deadline_never_retries_an_uncertain_case_write(local, monkeypatch):
    pending = prepare(local)
    with local.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state='attempted'")
    # Shorten only this unit-test wait; production remains five seconds.
    monkeypatch.setattr("banking_mcp.actions.RECEIPT_WAIT_SECONDS", .1)
    with pytest.raises(BankError, match="action_unverified"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "attempted"


@pytest.mark.parametrize("retain_only_later_record", [True, False])
def test_retained_existing_case_intent_after_case_loss_cannot_become_no_match_or_new_intake(local, retain_only_later_record):
    create_case(local)
    later = prepare(local)
    assert later["decision"] == "existing_case"
    assert later["existing_case"]["state"] == "verified"
    with local.store.connect() as db:
        db.execute("DELETE FROM sandbox_cases")
        db.execute("DELETE FROM sandbox_case_receipts")
        if retain_only_later_record:
            retained_id = hashlib.sha256(later["pending_handle"].encode()).hexdigest()
            db.execute("DELETE FROM action_pending WHERE id<>?", (retained_id,))
            assert db.execute("SELECT decision,confirmation_state FROM action_pending").fetchall() == [
                ("existing_case", "prepared")]
    projection = local.actions.local_case_status(local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    assert projection["state"] == "action_unverified" and projection["receipt"] is None
    replacement = prepare(local)
    assert replacement["decision"] == "handoff" and replacement["reason"] == "action_unverified"
    assert replacement["existing_case"]["state"] == "action_unverified"
    with pytest.raises(BankError, match="handoff_required"):
        local.actions.confirm(local.owner, replacement["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 0
