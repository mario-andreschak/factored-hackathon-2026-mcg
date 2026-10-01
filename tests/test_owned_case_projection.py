"""New model read projection uses real signed authority and a fictional ledger."""
import json

import pytest

from banking_mcp.security import BankError
from tests.test_banking_mcp import action_call, bank, call, dataset
from tests.banking_authority_fixtures import principal_for


def selected_approved(bank):
    service = bank[0]
    listed = call(bank)
    selected = next(row for row in listed["transactions"] if row["status"].lower() == "approved")
    customer = service.config.principal_customers["alice"]
    import time
    principal = principal_for(service.store, "alice", customer, "session-alice", "conversation-alice", int(time.time()) + 60)
    stored = service.store.get(selected["selection_handle"], "selection", principal)
    return listed["snapshot"], selected, stored["id"]


def test_owned_get_reads_verified_existing_receipt_without_another_case(bank):
    service = bank[0]
    build, selected, transaction_id = selected_approved(bank)
    service.actions.coverage_start = int(service.actions.clock()) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:owned-projection-ledger")
    initial = call(bank, "get_my_transaction", {"selection_handle": selected["selection_handle"]})
    assert initial["existing_case"]["state"] == "not_found"
    pending = action_call(bank, "prepare_unrecognized_charge", {"transaction_id": transaction_id, "snapshot": build})
    receipt = action_call(bank, "confirm_simulated_intake", {"pending_handle": pending["pending_handle"], "confirmed": True})
    for _ in range(2):
        result = call(bank, "get_my_transaction", {"selection_handle": selected["selection_handle"]})
        assert result["existing_case"]["state"] == "verified"
        assert result["existing_case"]["receipt"] == receipt["receipt"]
        assert result["existing_case"]["receipt"]["status"] == "received"
        assert result["existing_case"]["receipt"]["transaction"] == result["transaction"]
        text = json.dumps(result)
        assert transaction_id not in text
        assert service.config.principal_customers["alice"] not in text
        assert "session-alice" not in text and "conversation-alice" not in text
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_case_receipts").fetchone()[0] == 1
    with pytest.raises(BankError, match="reference_unavailable"):
        call(bank, "get_my_transaction", {"selection_handle": selected["selection_handle"]}, "bob")


def test_get_does_not_promote_an_uncertain_confirm_attempt_to_no_case(bank):
    service = bank[0]
    build, selected, transaction_id = selected_approved(bank)
    service.actions.coverage_start = int(service.actions.clock()) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:uncertain-projection-ledger")
    action_call(bank, "prepare_unrecognized_charge", {"transaction_id": transaction_id, "snapshot": build})
    prepared = call(bank, "get_my_transaction", {"selection_handle": selected["selection_handle"]})
    assert prepared["existing_case"]["state"] == "not_found"
    with service.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state='attempted' WHERE transaction_id=?", (transaction_id,))
    result = call(bank, "get_my_transaction", {"selection_handle": selected["selection_handle"]})
    assert result["existing_case"] == {"state": "action_unverified", "receipt": None,
                                       "coverage": "sandbox_only", "source": "sandbox_cases"}
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
