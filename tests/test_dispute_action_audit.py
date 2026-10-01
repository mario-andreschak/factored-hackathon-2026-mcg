"""Joined action ownership and bank writer fences, using fictional source data."""
import asyncio
from copy import deepcopy
import uuid
from types import SimpleNamespace

import pytest

from banking_mcp.security import Principal
from frontend.server.chat import ChatError
from dispute_workflow.state import (
    TrustedBinding, new_state, begin_turn, start_query_batch,
    activate_query_scope, checkpoint_query_scope, finish_query_batch,
    set_pending,
)
from tests.test_dispute_action_host import joined, bank, dataset


@pytest.fixture
def public_join(joined, tmp_path):
    from fastapi.testclient import TestClient
    from frontend.server.app import create_app
    from frontend.server.config import Settings
    observed = SimpleNamespace()
    class Inquiry:
        async def run(self, context, message, **kwargs):
            binding = TrustedBinding(**context)
            state = begin_turn(new_state(binding), binding, turn_id=str(uuid.uuid4()), user_question=message)
            state["turn"].update(language="es", effective_language="es")
            target = app.state.repository.reference("txn", binding.customer_id, "TXN00000043")
            state = start_query_batch(state, [
                {"query_text": "No reconozco esta compra.", "domain": "TRANSACTION_DISPUTE"},
                {"query_text": "Tengo otra pregunta de esta misma compra.", "domain": "TRANSACTION_INQUIRY"},
            ])
            order = state["runtime"]["query_scope_order"][:]
            for query_id in order:
                state = activate_query_scope(state, binding, query_id)
                state["workflow_state"].update(transaction_id=target, candidate_snapshot_hash="owned-candidate-digest",
                    policy_decision={"response_mode": "INFORM"})
                state["response"]["message"] = "Movimiento seleccionado en esta consulta."
                state = checkpoint_query_scope(state)
            state = finish_query_batch(state)
            joined.backend.workflow_store.save(binding, state)
            observed.binding, observed.scopes, observed.target = binding, order, target
            return state
    settings = Settings(data_dir=joined.bank.data, state_dir=tmp_path / "public-frontend",
        static_dir=tmp_path / "public-static", demo_code="fictional-audit-code", chat=joined.config,
        profiles={"mexico": {"customer_id": joined.customer}})
    app = create_app(settings, dispute_factory=lambda *args: Inquiry(), bank_backend=joined.backend)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"profile": "mexico", "code": settings.demo_code}).status_code == 200
        queried = client.post("/api/chat", json={"message": "Tengo dos preguntas sobre una compra."})
        assert queried.status_code == 200, queried.text
        observed.client, observed.app, observed.bank = client, app, joined.bank
        observed.backend = joined.backend
        observed.chat = app.state.chat_service
        yield observed


def prepare_public(public):
    response = public.client.post("/api/action/prepare", json={
        "transaction_reference": public.target, "query_scope_id": public.scopes[0]})
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "pending_confirmation", response.text
    return response.json()


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
    principal = Principal(subject, joined.customer, joined.sid, binding.conversation_id, joined.expiry,
                          joined.backend.ledger_generation)
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
        joined.bank.service.store.revoke(joined.sid, principal=args[0])
        return evidence
    monkeypatch.setattr(joined.bank.service.actions, "_action_evidence", evidence_then_revoke)
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT confirmation_state FROM action_pending").fetchone()[0] == "prepared"


@pytest.mark.parametrize("action_state", ["preparing", "prepare_unverified", "action_unverified"])
@pytest.mark.parametrize("explicit_scope", [True, False])
def test_public_handoff_same_target_cannot_replay_uncertainty_from_another_scope(public_join, action_state, explicit_scope):
    public = public_join
    prepared = prepare_public(public)
    binding = public.binding
    current, _ = public.chat._current_action(binding.session_id, binding.owner, binding.expires_at)
    public.chat._advance_action(binding.session_id, binding.owner, binding.expires_at,
        current["action_id"], current["revision"], {**prepared, "state": action_state})
    same_scope = public.client.post("/api/action/handoff", json={"transaction_reference": public.target,
        "reason": "customer_request", "query_scope_id": public.scopes[0]})
    assert same_scope.status_code == 200, same_scope.text
    assert same_scope.json()["query_id"] == public.scopes[0]
    assert same_scope.json()["state"] == action_state
    if not explicit_scope:
        state = public.backend.workflow_store.load(binding)
        state["runtime"]["active_query_id"] = public.scopes[1]
        public.backend.workflow_store.save(binding, state,
            expected_revision=state["runtime"]["store_revision"])
    body = {"transaction_reference": public.target, "reason": "customer_request"}
    if explicit_scope:
        body["query_scope_id"] = public.scopes[1]
    response = public.client.post("/api/action/handoff", json=body)
    assert response.status_code == 409, response.text
    with public.chat._connection() as db:
        assert db.execute("SELECT query_scope_id FROM action_status WHERE session_id=?",
            (binding.session_id,)).fetchone()[0] == public.scopes[0]
    with public.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM action_pending").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0


def test_public_handoff_same_target_completed_other_scope_requires_fresh_preparation(public_join, monkeypatch):
    public = public_join
    prepared = prepare_public(public)
    binding = public.binding
    subject, _ = public.chat._identity(binding.customer_id, binding.session_id, binding.expires_at)
    principal = Principal(subject, binding.customer_id, binding.session_id, binding.conversation_id, binding.expires_at,
                          public.backend.ledger_generation)
    native = public.bank.service.actions.handoff(principal, "customer_request", prepared["pending_handle"],
        prepared["request_id"], [])
    current, _ = public.chat._current_action(binding.session_id, binding.owner, binding.expires_at)
    public.chat._advance_action(binding.session_id, binding.owner, binding.expires_at,
        current["action_id"], current["revision"], {**prepared, "state": "handoff_verified",
            "handoff": native["handoff"], "reason": "customer_request"})
    same_scope = public.client.post("/api/action/handoff", json={"transaction_reference": public.target,
        "reason": "customer_request", "query_scope_id": public.scopes[0]})
    assert same_scope.status_code == 200, same_scope.text
    assert same_scope.json()["query_id"] == public.scopes[0]
    assert same_scope.json()["handoff"]["id"] == native["handoff"]["id"]
    original_post, calls = public.backend.post, []
    async def source_prepare_then_lost_handoff(path, headers, payload, chat):
        calls.append(deepcopy(payload))
        if payload["operation"] == "handoff":
            raise ChatError("chat_timeout", 504, "Tiempo de espera agotado.")
        return await original_post(path, headers, payload, chat)
    monkeypatch.setattr(public.backend, "post", source_prepare_then_lost_handoff)
    response = public.client.post("/api/action/handoff", json={"transaction_reference": public.target,
        "reason": "customer_request", "query_scope_id": public.scopes[1]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["query_id"] == public.scopes[1]
    assert result["state"] == "handoff_unverified"
    assert result.get("handoff", {}).get("id") != native["handoff"]["id"]
    assert [call["operation"] for call in calls] == ["prepare", "handoff", "handoff"]
    assert all(call["queryId"] == public.scopes[1] for call in calls)
    with public.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM action_pending").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0


@pytest.mark.parametrize("resolution", ["DENIED", "NEW_REQUEST"])
@pytest.mark.parametrize("completed", [False, True])
def test_chat_stop_preserves_already_attempted_portal_outcome(joined, monkeypatch, resolution, completed):
    from dispute_workflow.host import RepositoryBank
    from dispute_workflow.runtime import Workflow
    from tests.test_dispute_acceptance import ObservedStages
    prepared = asyncio.run(joined.prepare())
    subject, owner = joined.chat._identity(joined.customer, joined.sid, joined.expiry)
    with joined.chat._connection() as db:
        session = db.execute("SELECT conversation_id FROM chat_sessions WHERE session_id=?", (joined.sid,)).fetchone()
    binding = TrustedBinding(owner=owner, customer_id=joined.customer, session_id=joined.sid,
        conversation_id=session[0], expires_at=joined.expiry)
    graph = joined.backend.workflow_store.load(binding)
    revision = graph["runtime"]["store_revision"]
    graph["turn"].update(turn_id="source-preparation", intent="TRANSACTION_DISPUTE")
    graph["workflow_state"].update(transaction_id=joined.target, candidate_snapshot_hash="owned-candidate-digest",
        policy_decision={"response_mode": "CONFIRM_ACTION"})
    graph = set_pending(graph, {"type": "awaiting_confirmation", "intent": "TRANSACTION_DISPUTE",
        "target_transaction_id": joined.target, "snapshot_id": prepared["snapshot"],
        "snapshot_hash": "owned-candidate-digest", "host_pending_handle": prepared["pending_handle"],
        "request_id": prepared["request_id"]})
    joined.backend.workflow_store.save(binding, graph, expected_revision=revision)
    if completed:
        confirmed = asyncio.run(joined.confirm(prepared["pending_handle"]))
        assert confirmed["state"] == "intake_verified"
    else:
        # This durable marker is committed by the actual confirmation port
        # before any case write; absence of a receipt cannot mean cancellation.
        with joined.bank.service.store.connect() as db:
            db.execute("UPDATE action_pending SET confirmation_state='attempted'")
    current, _ = joined.chat._current_action(joined.sid, owner, joined.expiry)
    joined.chat._advance_action(joined.sid, owner, joined.expiry, current["action_id"], current["revision"],
        {**prepared, "state": "action_unverified"})
    calls, original_post = [], joined.backend.post
    async def observe_only_readback(path, headers, payload, chat):
        calls.append(payload["operation"])
        return await original_post(path, headers, payload, chat)
    monkeypatch.setattr(joined.backend, "post", observe_only_readback)
    stages = ObservedStages(resolution={"resolution_type": resolution, "selected_ref": None},
        generated={"message": "Se devolvieron 999999 USD.", "language": "es", "arquetipos": [],
            "chunk_ids": [], "data_sources": [], "grounding_violation": 0})
    reader = RepositoryBank(joined.bank.public, joined.chat, "mexico", joined.sid, joined.expiry,
        bank_service=joined.bank.service, source_root=joined.bank.source)
    runner = Workflow(stages, reader, joined.backend.workflow_store)
    message = "No quiero continuar con este reclamo." if resolution == "DENIED" else "Ahora quiero consultar otra compra."
    asyncio.run(joined.chat.send(joined.customer, joined.sid, joined.expiry, message, workflow=runner))
    saved = joined.backend.workflow_store.load(binding)
    assert saved["workflow_state"]["policy_decision"]["response_mode"] == ("ACTION_DONE" if completed else "ACTION_UNVERIFIED")
    assert saved["workflow_state"]["action_outcome"] == ("verified" if completed else "unknown")
    assert not saved["runtime"].get("host_cancellation_requested")
    assert calls == ["receipt"]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == int(completed)
        assert db.execute("SELECT count(*) FROM dispute_host_cancelled").fetchone()[0] == 0


@pytest.mark.parametrize("field", ["request_id", "pending_handle"])
def test_same_action_revision_cannot_replace_immutable_preparation_identity(joined, field):
    prepared = asyncio.run(joined.prepare())
    _, owner = joined.chat._identity(joined.customer, joined.sid, joined.expiry)
    current, _ = joined.chat._current_action(joined.sid, owner, joined.expiry)
    changed = {**prepared, "state": "action_unverified",
        field: str(uuid.uuid4()) if field == "request_id" else "z" * 43}
    with pytest.raises(ChatError) as rejected:
        joined.chat._advance_action(joined.sid, owner, joined.expiry,
            current["action_id"], current["revision"], changed)
    assert rejected.value.code == "action_mismatch"
    after, status = joined.chat._current_action(joined.sid, owner, joined.expiry)
    assert after["revision"] == current["revision"]
    assert status["state"] == "pending_confirmation"
    assert status["request_id"] == prepared["request_id"]
    assert status["pending_handle"] == prepared["pending_handle"]
