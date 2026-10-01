"""History reload exposes only the durable registry of its admitted owner."""
import asyncio

import pytest

from gloria_workflow.host import GloriaHostFactory, RepositoryBank
from gloria_workflow.state import TrustedBinding, new_state, start_query_batch, StateError
from tests.test_gloria_host import admitted, TrustedWorkflowSpy


def registry(admitted, tmp_path):
    chat, sid, expiry = admitted
    spy = TrustedWorkflowSpy()
    asyncio.run(chat.send("customer-a", sid, expiry, "hola", workflow=spy))
    binding = TrustedBinding(**spy.calls[0][0])
    factory = GloriaHostFactory(None, tmp_path / "gloria.sqlite3")
    state = start_query_batch(new_state(binding), [
        {"query_text": "Consulta la compra de 25 USD.", "domain": "TRANSACTION_INQUIRY"},
        {"query_text": "Consulta el estado del reclamo.", "domain": "COMPLAINT_STATUS"}])
    first, second = state["runtime"]["query_scope_order"]
    state["runtime"]["active_query_id"] = second
    state["runtime"]["query_scopes"][first]["workflow_state"]["transaction_id"] = "txn_" + "a" * 24
    factory.store.save(binding, state)
    return chat, sid, expiry, factory, binding, first, second


def test_reload_preserves_query_order_labels_active_and_exact_targets(admitted, tmp_path):
    chat, sid, expiry, factory, _, first, second = registry(admitted, tmp_path)
    assert factory.query_context(chat, "customer-a", sid, expiry) == {
        "queries": [
            {"query_id": first, "label": "Consulta la compra de 25 USD.", "transaction_reference": "txn_" + "a" * 24},
            {"query_id": second, "label": "Consulta el estado del reclamo.", "transaction_reference": None}],
        "active_query_id": second}


@pytest.mark.parametrize("field,value", [("subject", "subject-b"), ("customer_id", "customer-b"),
    ("owner", "other-owner"), ("expires", 1), ("revoked", 1)])
def test_corrupt_or_revoked_admission_never_releases_owned_registry(admitted, tmp_path, field, value):
    chat, sid, expiry, factory, *_ = registry(admitted, tmp_path)
    with chat._connection() as db:
        db.execute(f"UPDATE chat_sessions SET {field}=? WHERE session_id=?", (value, sid))
    with pytest.raises(ValueError, match="session unavailable"):
        factory.query_context(chat, "customer-a", sid, expiry)


def test_registry_cannot_be_loaded_for_other_customer_or_changed_expiry(admitted, tmp_path):
    chat, sid, expiry, factory, *_ = registry(admitted, tmp_path)
    for customer, selected_expiry in (("customer-b", expiry), ("customer-a", expiry + 1)):
        with pytest.raises(ValueError, match="session unavailable"):
            factory.query_context(chat, customer, sid, selected_expiry)


def test_revocation_during_registry_read_blocks_projection(admitted, tmp_path, monkeypatch):
    chat, sid, expiry, factory, *_ = registry(admitted, tmp_path)
    load = factory.store.load
    def revoking(binding):
        state = load(binding)
        chat.queue_revoke("customer-a", sid, expiry)
        return state
    monkeypatch.setattr(factory.store, "load", revoking)
    with pytest.raises(ValueError, match="session unavailable"):
        factory.query_context(chat, "customer-a", sid, expiry)


def test_missing_session_blocks_even_empty_registry(admitted, tmp_path):
    chat, sid, expiry = admitted
    factory = GloriaHostFactory(None, tmp_path / "gloria.sqlite3")
    with pytest.raises(ValueError, match="session unavailable"):
        factory.query_context(chat, "customer-a", sid, expiry)
