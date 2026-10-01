"""Real generated-source inquiry/action join; no network or model provider."""
import asyncio
import json
import time
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from frontend.server.chat import ChatError
from frontend.server.dispute_chat import DisputeChatService as ChatService
from dispute_workflow.action_host import BankingActionHost
from dispute_workflow.state import ConversationStore, TrustedBinding, new_state
from tests.test_dispute_bank_read import dataset, bank


@pytest.fixture
def joined(bank, tmp_path):
    key = Ed25519PrivateKey.generate()
    signer = tmp_path / "frontend-signer.pem"
    signer.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    store = ConversationStore(tmp_path / "workflow.sqlite")
    backend = BankingActionHost(bank.service, store, source_root=bank.source)
    backend.bind_repository(bank.public)
    config = dict(base_url="http://flujo:4200", model="flow-Dispute",
        execution_token="synthetic-private-execution", frontend_signing_key_file=str(signer),
        frontend_kid="fixture", frontend_issuer="fixture", frontend_audience="flujo-banking-ingress",
        principal_customers=dict(bank.service.config.principal_customers), action_enabled=True)
    chat = ChatService(config, tmp_path / "chat", bank_backend=backend)
    sid, expiry = str(uuid.uuid4()), int(time.time()) + 3600
    target = bank.public.reference("txn", bank.principal.customer, "TXN00000043")
    class Inquiry:
        async def run(self, context, message, **kwargs):
            binding = TrustedBinding(**context)
            state = new_state(binding)
            state["workflow_state"]["transaction_id"] = target
            state["response"]["message"] = "Movimiento verificado."
            store.save(binding, state)
            return state
    asyncio.run(chat.send(bank.principal.customer, sid, expiry, "Consulta", workflow=Inquiry()))
    raw = "TXN00000043"
    async def prepare():
        return await chat.action(bank.principal.customer, sid, expiry,
            dict(operation="prepare", transactionId=raw, snapshot=bank.snapshot.id), target_reference=target)
    async def confirm(handle, scope=None):
        return await chat.action(bank.principal.customer, sid, expiry,
            dict(operation="confirm", pendingHandle=handle, confirmed=True), target_reference=target,
            query_scope_id=scope)
    return SimpleNamespace(bank=bank, chat=chat, backend=backend, prepare=prepare, confirm=confirm,
        customer=bank.principal.customer, sid=sid, expiry=expiry, config=config, target=target, root=tmp_path)


def test_fresh_source_intake_receipt_survives_frontend_and_bank_restart(joined):
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation", pending
    result = asyncio.run(joined.confirm(pending["pending_handle"]))
    assert result["state"] == "intake_verified", result
    with joined.chat._connection() as db:
        row = db.execute("SELECT action_conversation_id,prepare_conversation_id FROM action_status").fetchone()
    assert row["action_conversation_id"] and row["prepare_conversation_id"] is None
    restarted = ChatService(joined.config, joined.root / "chat", bank_backend=joined.backend)
    observed = asyncio.run(restarted.action_status(joined.customer, joined.sid, joined.expiry))
    assert observed["receipt"] == result["receipt"]
    assert asyncio.run(joined.confirm(pending["pending_handle"]))["receipt"] == result["receipt"]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1


def test_cancellation_denies_prepared_handle_at_both_services(joined):
    pending = asyncio.run(joined.prepare())
    assert joined.chat.cancel_pending(joined.customer, joined.sid, joined.expiry,
        handle=pending["pending_handle"])
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM dispute_host_cancelled").fetchone()[0] == 1


def test_attempted_write_cannot_be_deleted_by_cancellation(joined):
    pending = asyncio.run(joined.prepare())
    with joined.bank.service.store.connect() as db:
        db.execute("UPDATE action_pending SET confirmation_state='attempted'")
    assert not joined.chat.cancel_pending(joined.customer, joined.sid, joined.expiry,
        handle=pending["pending_handle"])
    assert asyncio.run(joined.chat.action_status(joined.customer, joined.sid, joined.expiry))["pending_handle"] == pending["pending_handle"]


def test_source_mutation_between_prepare_and_confirm_never_writes(joined):
    pending = asyncio.run(joined.prepare())
    row = next(row for row in joined.bank.rows if row["transaction_id"] == "TXN00000043")
    path = joined.bank.source / row["_source_file"]
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0


def test_foreign_query_cannot_confirm_current_handle(joined):
    pending = asyncio.run(joined.prepare())
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"], "q_" + "f" * 32))


def general_handoff(joined):
    request = str(uuid.uuid4())
    result = asyncio.run(joined.chat.action(joined.customer, joined.sid, joined.expiry,
        dict(operation="handoff", reason="customer_request", requestId=request)))
    assert result["state"] == "handoff_verified", result
    with joined.chat._connection() as db:
        conversation = db.execute("SELECT conversation_id FROM chat_sessions").fetchone()[0]
    payload = dict(operation="handoff", reason="customer_request", requestId=request,
        conversationId=conversation, unanswered_questions=[])
    subject, _ = joined.chat._identity(joined.customer, joined.sid, joined.expiry)
    return result, payload, joined.chat._headers(subject, joined.sid, joined.expiry)


def test_canonical_human_packet_is_durable_private_and_replayed_once(joined):
    result, payload, headers = general_handoff(joined)
    with joined.bank.service.store.connect() as db:
        packet = json.loads(db.execute("SELECT packet_json FROM dispute_handoff_packets").fetchone()[0])
    assert packet["schema"] == "dispute-human-handoff/v1"
    assert packet["handoff_id"] == result["handoff"]["id"]
    assert packet["rule_ids"] == ["R8"] and packet["reason_code"] == "customer_request"
    assert packet["human_responded"] is False and packet["target_transaction_id"] is None
    assert packet["native_handoff"]["packet"]["human_responded"] is False
    assert len(packet["open_questions"]) <= 4 and packet["request_summary"]
    assert "binding_digest" not in result["handoff"] and "risk_signals" not in result["handoff"]
    replay = asyncio.run(joined.backend.post("/v1/banking/action", headers, payload, joined.chat))
    assert replay["handoff"] == result["handoff"]
    with joined.bank.service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM dispute_handoff_packets").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0


@pytest.mark.parametrize("corruption", ["malformed", "foreign_binding"])
def test_handoff_replay_cannot_promote_corrupt_canonical_packet(joined, corruption):
    _, payload, headers = general_handoff(joined)
    with joined.bank.service.store.connect() as db:
        packet = json.loads(db.execute("SELECT packet_json FROM dispute_handoff_packets").fetchone()[0])
        packet["binding_digest"] = "f" * 64
        db.execute("UPDATE dispute_handoff_packets SET packet_json=?",
            ("broken" if corruption == "malformed" else json.dumps(packet),))
    result = asyncio.run(joined.backend.post("/v1/banking/action", headers, payload, joined.chat))
    assert result == {"state": "action_unverified"}
