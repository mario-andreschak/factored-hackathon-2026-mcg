"""Owned, consented, durable card protection; fictional ledger only."""
import csv
from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid

import pytest

from banking_mcp.security import BankError
from banking_mcp.service import Service
from pipeline.__main__ import main
from pipeline.fixture import write_base
from tests.test_banking_mcp import bank, action_call
from tests.banking_authority_fixtures import principal_for


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("owned-card-demo")
    write_base(root / "src")
    path = root / "src/products.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        row.update(product_type="Tarjeta Crédito", product_status="Active")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    assert main(["run", "--source", str(root / "src"), "--out", str(root / "out"),
                 "--reports", str(root / "reports")]) == 0
    return root


def prepare(bank, request=None, product="PRD000003"):
    return action_call(bank, "prepare_card_block", {"product_id": product,
        "snapshot": bank[0].repository.snapshot().id, "request_id": request or str(uuid.uuid4())})


def confirm(bank, pending):
    return action_call(bank, "confirm_card_block", {"pending_handle": pending["pending_handle"], "confirmed": True})


def test_prepare_only_does_not_block_and_explicit_confirmation_is_required(bank):
    pending = prepare(bank)
    assert pending["state"] == "pending_confirmation"
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 0
    with pytest.raises(BankError, match="confirmation_required"):
        action_call(bank, "confirm_card_block", {"pending_handle": pending["pending_handle"], "confirmed": False})
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 0


def test_signed_cross_customer_cannot_prepare_or_confirm_a_card(bank):
    with pytest.raises(BankError, match="authorization_denied"):
        prepare(bank, product="PRD000004")
    pending = prepare(bank)
    with pytest.raises(BankError, match="reference_unavailable"):
        action_call(bank, "confirm_card_block", {"pending_handle": pending["pending_handle"], "confirmed": True}, "bob")


def test_prepare_replay_is_same_handle_and_changed_target_is_denied(bank):
    request = str(uuid.uuid4())
    first = prepare(bank, request)
    assert prepare(bank, request) == first
    with pytest.raises(BankError):
        prepare(bank, request, product="PRD000004")


def test_100_parallel_confirmations_create_exactly_one_receipt_and_survive_restart(bank):
    pending = prepare(bank)
    with ThreadPoolExecutor(max_workers=100) as pool:
        results = list(pool.map(lambda _: confirm(bank, pending), range(100)))
    assert {item["state"] for item in results} == {"card_block_verified"}
    receipts = [item["receipt"] for item in results]
    assert all(receipt == receipts[0] for receipt in receipts)
    assert receipts[0]["status"] == "blocked" and receipts[0]["real_bank_action"] is False
    assert receipts[0]["simulated"] is True
    assert "PRD000003" not in json.dumps(receipts[0])
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 1
    restarted = Service(bank[0].config)
    try:
        principal = principal_for(restarted.store, "alice", restarted.config.principal_customers["alice"],
            "session-alice", "conversation-alice", int(time.time()) + 60)
        assert restarted.actions.read_card_block(principal, pending["pending_handle"])["receipt"] == receipts[0]
    finally:
        restarted.close()


def test_expired_consent_or_changed_snapshot_cannot_write(bank, monkeypatch):
    pending = prepare(bank)
    with bank[0].store.connect() as db:
        db.execute("UPDATE sandbox_card_pending SET expires=0")
    with pytest.raises(BankError, match="reference_unavailable"):
        confirm(bank, pending)
    fresh = prepare(bank)
    monkeypatch.setattr(bank[0].repository, "assert_current_snapshot",
        lambda _: (_ for _ in ()).throw(BankError("snapshot_changed")))
    with pytest.raises(BankError, match="snapshot_changed"):
        confirm(bank, fresh)
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 0


def test_lost_readback_is_uncertain_then_recovered_without_a_second_write(bank, monkeypatch):
    pending = prepare(bank)
    original = bank[0].actions.read_card_block
    reads = [0]
    def lost(principal, handle):
        reads[0] += 1
        if reads[0] == 2:
            raise BankError("action_unverified")
        return original(principal, handle)
    monkeypatch.setattr(bank[0].actions, "read_card_block", lost)
    with pytest.raises(BankError, match="action_unverified"):
        confirm(bank, pending)
    recovered = action_call(bank, "read_card_block", {"pending_handle": pending["pending_handle"]})
    assert recovered["state"] == "card_block_verified"
    assert confirm(bank, pending)["receipt"] == recovered["receipt"]
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 1


def test_corrupt_receipt_never_claims_a_verified_block(bank):
    pending = prepare(bank)
    confirm(bank, pending)
    with bank[0].store.connect() as db:
        db.execute("UPDATE sandbox_card_blocks SET receipt_json='{}'")
    with pytest.raises(BankError, match="action_unverified"):
        action_call(bank, "read_card_block", {"pending_handle": pending["pending_handle"]})


@pytest.mark.parametrize("field,value", [("card", {"type": "Foreign card"}), ("snapshot", "wrong-snapshot"),
    ("created_at", "2026-01-01T00:00:00Z"), ("created_at", "invalid"), ("created_at", "9999-01-01T00:00:00Z")])
def test_valid_json_receipt_field_tampering_is_unverified(bank, field, value):
    pending = prepare(bank)
    confirm(bank, pending)
    with bank[0].store.connect() as db:
        receipt = json.loads(db.execute("SELECT receipt_json FROM sandbox_card_blocks").fetchone()[0])
        receipt[field] = value
        db.execute("UPDATE sandbox_card_blocks SET receipt_json=?", (json.dumps(receipt),))
    with pytest.raises(BankError, match="action_unverified"):
        action_call(bank, "read_card_block", {"pending_handle": pending["pending_handle"]})


@pytest.mark.parametrize("field,value", [("card", {"type": "Foreign card"}), ("snapshot", "wrong-snapshot"),
    ("created_at", "invalid"), ("created_at", "9999-01-01T00:00:00Z")])
def test_receipt_independent_lineage_and_timestamp_validation(bank, field, value):
    from banking_mcp.actions import _digest
    pending = prepare(bank)
    confirm(bank, pending)
    with bank[0].store.connect() as db:
        receipt = json.loads(db.execute("SELECT receipt_json FROM sandbox_card_blocks").fetchone()[0])
        receipt[field] = value
        encoded = json.dumps(receipt)
        db.execute("UPDATE sandbox_card_blocks SET receipt_json=?,receipt_sha256=?", (encoded, _digest(encoded)))
    with pytest.raises(BankError, match="action_unverified"):
        action_call(bank, "read_card_block", {"pending_handle": pending["pending_handle"]})


def test_revoked_session_cannot_commit_prepared_block(bank):
    pending = prepare(bank)
    with bank[0].store.connect() as db:
        db.execute("INSERT INTO revoked VALUES ('session-alice')")
    with pytest.raises(BankError, match="authorization_denied"):
        confirm(bank, pending)


def test_cancelling_preparation_invalidates_stale_confirmation(bank):
    pending = prepare(bank)
    principal = principal_for(bank[0].store, "alice", bank[0].config.principal_customers["alice"],
        "session-alice", "conversation-alice", int(time.time()) + 60)
    assert bank[0].actions.cancel_card_block(principal, pending["pending_handle"])["state"] == "cancelled"
    with pytest.raises(BankError, match="reference_unavailable"):
        confirm(bank, pending)
    with bank[0].store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_card_blocks").fetchone()[0] == 0


def test_stale_cancellation_never_undoes_a_committed_block(bank):
    pending = prepare(bank)
    receipt = confirm(bank, pending)["receipt"]
    principal = principal_for(bank[0].store, "alice", bank[0].config.principal_customers["alice"],
        "session-alice", "conversation-alice", int(time.time()) + 60)
    assert bank[0].actions.cancel_card_block(principal, pending["pending_handle"])["receipt"] == receipt
    assert bank[0].actions.card_status(principal, "PRD000003", bank[0].repository.snapshot().id)["receipt"] == receipt
