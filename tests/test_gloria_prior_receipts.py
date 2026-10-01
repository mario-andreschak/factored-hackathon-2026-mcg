"""Owned synthetic R16 ledger integrity; no model, transport or live action."""
from __future__ import annotations

import copy
import json
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from banking_mcp.actions import ACTION
from banking_mcp.security import BankError, StateStore
from tests.test_case_handoff_receipts import local


def saved_prior(local, index=0, *, created_at=None, customer=None, transaction_id=None):
    created_at = local.now - 1 if created_at is None else created_at
    customer = local.owner.customer if customer is None else customer
    transaction_id = f"fixture-prior-{index}" if transaction_id is None else transaction_id
    snapshot, row = local.repository.owned_transaction_id(
        local.owner, "fixture-charge-A", local.repository.snapshot_info.id)
    facts = local.repository._visible(row, snapshot)
    facts["transaction_reference"] = f"txn_prior{index:06d}"
    receipt = {"id": f"CMP-SBX-TEST{index:04d}", "kind": ACTION, "simulated": True,
               "snapshot": snapshot.id,
               "created_at": datetime.fromtimestamp(created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
               "status": "received", "transaction": facts}
    with local.store.connect() as db:
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)",
                   (receipt["id"], customer, transaction_id, ACTION, snapshot.id, created_at, json.dumps(facts)))
        db.execute("INSERT INTO sandbox_case_receipts VALUES (?,?)", (receipt["id"], json.dumps(receipt)))
    return receipt


def prepare(local, request_id=None):
    return local.actions.prepare(local.owner, "fixture-charge-A", local.repository.snapshot_info.id,
                                 request_id or str(uuid.uuid4()))


def corrupt(local, receipt, mutation):
    encoded = copy.deepcopy(receipt)
    if mutation == "amount":
        encoded["transaction"]["amount"] = "9999.00"
    elif mutation == "id":
        encoded["id"] = "CMP-SBX-FOREIGN1"
    elif mutation == "snapshot":
        encoded["snapshot"] = "different-snapshot"
    elif mutation == "time":
        encoded["created_at"] = "2000-01-01T00:00:00Z"
    elif mutation == "simulated_number":
        encoded["simulated"] = 1
    elif mutation == "status":
        encoded["status"] = "resolved"
    encoded = json.dumps(encoded)
    if mutation == "duplicate_key":
        encoded = encoded[:-1] + ',"status":"received"}'
    with local.store.connect() as db:
        if mutation == "missing":
            db.execute("DELETE FROM sandbox_case_receipts WHERE case_id=?", (receipt["id"],))
        elif mutation == "facts":
            db.execute("UPDATE sandbox_cases SET facts='invalid json' WHERE id=?", (receipt["id"],))
        elif mutation == "case_id":
            db.execute("UPDATE sandbox_cases SET id='invalid-id' WHERE id=?", (receipt["id"],))
        else:
            db.execute("UPDATE sandbox_case_receipts SET receipt_json=? WHERE case_id=?", (encoded, receipt["id"]))


@pytest.mark.parametrize("mutation", ["missing", "amount", "id", "snapshot", "time", "simulated_number",
                                      "status", "duplicate_key", "facts", "case_id"])
def test_corrupt_prior_never_becomes_complete_low_risk(local, mutation):
    prior = saved_prior(local)
    assert prepare(local)["risk"]["unrecognized_count_24h"] == 2
    corrupt(local, prior, mutation)
    result = prepare(local)
    assert result["risk"]["risk_data_complete"] is False
    assert result["risk"]["unrecognized_count_24h"] is None
    assert (result["decision"], result["reason"]) == ("handoff", "missing_evidence")
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases WHERE transaction_id='fixture-charge-A'").fetchone()[0] == 0


def test_verified_high_lower_bound_survives_an_additional_corrupt_prior(local):
    saved_prior(local, 0)
    saved_prior(local, 1)
    prior = saved_prior(local, 2)
    corrupt(local, prior, "missing")
    result = prepare(local)
    assert result["risk"]["risk_data_complete"] is False
    assert result["risk"]["unrecognized_count_24h"] is None
    assert (result["decision"], result["reason"]) == ("handoff", "high_risk")


def test_only_owned_prior_receipts_in_real_half_open_window_are_required(local):
    saved_prior(local, 0, created_at=local.now - 86400)
    outside = saved_prior(local, 1, created_at=local.now - 86400 - .001)
    upper = saved_prior(local, 2, created_at=local.now)
    foreign = saved_prior(local, 3, customer="fictional-owner-B")
    for receipt in (outside, upper, foreign):
        corrupt(local, receipt, "missing")
    result = prepare(local)
    assert result["risk"]["risk_data_complete"] is True
    assert result["risk"]["unrecognized_count_24h"] == 2
    assert result["decision"] == "intake"


@pytest.mark.parametrize("replay", [False, True])
def test_confirm_rechecks_prior_receipts_after_prepare_even_on_replay(local, replay):
    prior = saved_prior(local)
    request_id = str(uuid.uuid4())
    pending = prepare(local, request_id)
    assert pending["decision"] == "intake"
    corrupt(local, prior, "missing")
    if replay:
        again = prepare(local, request_id)
        assert again["pending_handle"] == pending["pending_handle"]
    with pytest.raises(BankError, match="risk_data_unavailable"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases WHERE transaction_id='fixture-charge-A'").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending LIMIT 1").fetchone()[0] == "prepared"


def test_confirm_second_writer_gate_rechecks_receipt_corrupted_after_attempt_marker(local):
    prior = saved_prior(local)
    pending = prepare(local)

    class CorruptAfterAttempt(StateStore):
        @contextmanager
        def connect(self):
            attempted = False

            class Observed:
                def __init__(self, db):
                    self.db = db

                def __getattr__(self, field):
                    return getattr(self.db, field)

                def execute(self, sql, args=()):
                    nonlocal attempted
                    result = self.db.execute(sql, args)
                    attempted = attempted or "SET confirmation_state='attempted'" in sql
                    return result

            with super().connect() as db:
                yield Observed(db)
            if attempted:
                with super().connect() as db:
                    db.execute("DELETE FROM sandbox_case_receipts WHERE case_id=?", (prior["id"],))

    local.actions.store = CorruptAfterAttempt(local.store.path, ledger_continuity_approved=True)
    with pytest.raises(BankError, match="risk_data_unavailable"):
        local.actions.confirm(local.owner, pending["pending_handle"], True)
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases WHERE transaction_id='fixture-charge-A'").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending LIMIT 1").fetchone()[0] == "attempted"
    assert local.actions.receipt(local.owner, pending["pending_handle"]) == {"state": "action_unverified", "receipt": None}


def test_existing_target_and_idempotent_confirm_do_not_add_to_prior_count(local):
    prior = saved_prior(local)
    request_id = str(uuid.uuid4())
    pending = prepare(local, request_id)
    # A later real-time boundary includes the prior created target if it were
    # not excluded by exact transaction identity.
    result = local.actions.confirm(local.owner, pending["pending_handle"], True)
    local.actions.clock = lambda: local.now + .1
    assert local.actions.confirm(local.owner, pending["pending_handle"], True) == result
    again = prepare(local, request_id)
    assert again["decision"] == "existing_case"
    fresh = prepare(local)
    assert fresh["risk"]["unrecognized_count_24h"] == 2
    assert fresh["existing_case"]["receipt"] == result["receipt"]
    with local.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 2
