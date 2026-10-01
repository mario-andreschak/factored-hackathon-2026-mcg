"""Joined action ownership and bank writer fences, using fictional source data."""
import asyncio
from copy import deepcopy
import uuid

import pytest

from banking_mcp.security import Principal
from frontend.server.chat import ChatError
from gloria_workflow.state import (
    TrustedBinding, new_state, begin_turn, start_query_batch,
    activate_query_scope, checkpoint_query_scope, finish_query_batch,
)
from tests.test_gloria_action_host import joined, bank, dataset


def two_scopes(joined):
    subject, owner = joined.chat._identity(joined.customer, joined.sid, joined.expiry)
    with joined.chat._connection() as db:
        row = db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (joined.sid,)).fetchone()
    binding = TrustedBinding(owner=owner, customer_id=joined.customer, session_id=joined.sid,
        conversation_id=row["conversation_id"], expires_at=joined.expiry)
    previous = joined.backend.workflow_store.load(binding)
    state = begin_turn(new_state(binding), binding, turn_id=str(uuid.uuid4()),
        user_question="Tengo preguntas sobre dos compras.")
    state["turn"].update(language="es", effective_language="es")
    state = start_query_batch(state, [
        {"query_text": "No reconozco una compra.", "domain": "TRANSACTION_DISPUTE"},
        {"query_text": "Quiero información de otra compra.", "domain": "TRANSACTION_INQUIRY"},
    ])
    order = state["runtime"]["query_scope_order"][:]
    for query_id in order:
        state = activate_query_scope(state, binding, query_id)
        state["workflow_state"].update(missing_fields=["amount", "date"],
            policy_decision={"response_mode": "CLARIFY"})
        state["response"]["message"] = "Indica el importe y la fecha de esta compra."
        state = checkpoint_query_scope(state)
    state = finish_query_batch(state)
    joined.backend.workflow_store.save(binding, state,
        expected_revision=previous["runtime"]["store_revision"])
    principal = Principal(subject, joined.customer, joined.sid, binding.conversation_id, joined.expiry)
    return order, principal, owner, binding.conversation_id


def handoff(joined, scope, request_id):
    return joined.chat.action(joined.customer, joined.sid, joined.expiry,
        {"operation": "handoff", "reason": "customer_request", "requestId": request_id,
         "unansweredQuestions": []}, query_scope_id=scope)


def verified_general_handoff(joined):
    """Seed the frontend with an actual owned, source-read native handoff."""
    scopes, principal, owner, conversation = two_scopes(joined)
    request_id = str(uuid.uuid4())
    native = joined.bank.service.actions.handoff(principal, "customer_request", None, request_id, [])
    assert native["state"] == "created"
    action_id, revision, _ = joined.chat._reserve_action(joined.sid, owner, joined.expiry, None,
        {"state": "handoff_unverified", "request_id": request_id, "reason": "customer_request",
         "unanswered_questions": []}, prepare_conversation_id=conversation, query_scope_id=scopes[0])
    verified = {"state": "handoff_verified", "handoff": deepcopy(native["handoff"]),
        "request_id": request_id, "reason": "customer_request", "unanswered_questions": []}
    joined.chat._advance_action(joined.sid, owner, joined.expiry, action_id, revision, verified)
    return scopes, request_id, native["handoff"]["id"]


def test_general_handoff_cached_replay_cannot_cross_owned_query_scope(joined):
    scopes, request_id, _ = verified_general_handoff(joined)
    with pytest.raises(ChatError) as rejected:
        asyncio.run(handoff(joined, scopes[1], request_id))
    assert rejected.value.code == "action_mismatch"
    with joined.chat._connection() as db:
        row = db.execute("SELECT query_scope_id FROM action_status WHERE session_id=?", (joined.sid,)).fetchone()
    assert row["query_scope_id"] == scopes[0]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1


def test_general_handoff_same_scope_replay_reuses_exact_saved_receipt(joined):
    scopes, request_id, handoff_id = verified_general_handoff(joined)
    result = asyncio.run(handoff(joined, scopes[0], request_id))
    assert result["state"] == "handoff_verified"
    assert result["handoff"]["id"] == handoff_id
    assert result["query_id"] == scopes[0]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1


def test_general_handoff_uncertain_retry_cannot_cross_owned_query_scope(joined, monkeypatch):
    scopes, _, _, _ = two_scopes(joined)
    calls = []
    async def lost_response(*args, **kwargs):
        calls.append(deepcopy(args[2]))
        raise ChatError("chat_timeout", 504, "Tiempo de espera agotado.")
    monkeypatch.setattr(joined.chat, "_post", lost_response)
    request_id = str(uuid.uuid4())
    first = asyncio.run(handoff(joined, scopes[0], request_id))
    assert first["state"] == "handoff_unverified"
    assert len(calls) == 2  # The existing bounded same-identity retry.
    with pytest.raises(ChatError) as rejected:
        asyncio.run(handoff(joined, scopes[1], request_id))
    assert rejected.value.code == "action_mismatch"
    assert len(calls) == 2
    with joined.chat._connection() as db:
        row = db.execute("SELECT query_scope_id FROM action_status WHERE session_id=?", (joined.sid,)).fetchone()
    assert row["query_scope_id"] == scopes[0]


def test_cancellation_between_evidence_read_and_attempted_marker_prevents_intake(joined, monkeypatch):
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation"
    original = joined.bank.service.actions._action_evidence
    cancelled = []
    def evidence_then_cancel(*args):
        evidence = original(*args)
        cancelled.append(joined.backend.cancel(joined.chat, joined.customer,
            joined.sid, joined.expiry, pending["pending_handle"]))
        return evidence
    monkeypatch.setattr(joined.bank.service.actions, "_action_evidence", evidence_then_cancel)
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    assert cancelled == [True]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        row = db.execute("SELECT confirmation_state,expires FROM action_pending").fetchone()
    assert row == ("prepared", 0)
    # Frontend uncertainty was committed before the bank call and survives;
    # cancellation cannot falsely promote it to verified or restart a write.
    observed = asyncio.run(joined.chat.action_status(joined.customer, joined.sid, joined.expiry))
    assert observed["state"] == "action_unverified"
    assert observed["pending_handle"] == pending["pending_handle"]


def test_bank_revocation_after_evidence_read_is_rechecked_before_intake(joined, monkeypatch):
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation"
    original = joined.bank.service.actions._action_evidence
    def evidence_then_revoke(*args):
        evidence = original(*args)
        joined.bank.service.store.revoke(joined.sid)
        return evidence
    monkeypatch.setattr(joined.bank.service.actions, "_action_evidence", evidence_then_revoke)
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "prepared"
