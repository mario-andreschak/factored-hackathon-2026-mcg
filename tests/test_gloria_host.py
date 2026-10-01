"""Joined host authority checks for optional Gloria application injection."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest

from frontend.server.chat import ChatService, ChatError
from frontend.tests.action_fixtures import action_receipt
from gloria_workflow.host import RepositoryBank
from gloria_workflow.model import FlujoModel
from gloria_workflow.tool import make_run_turn_tool, create_mcp_server


@pytest.fixture
def admitted(tmp_path):
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "signer.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    service = ChatService({"base_url": "http://flujo:4200", "model": "flow-Banking_Customer", "execution_token": "private-fixture-execution-token", "frontend_signing_key_file": str(key_path), "frontend_kid": "fixture", "frontend_issuer": "fixture", "frontend_audience": "flujo-banking-ingress", "principal_customers": {"subject-a": "customer-a", "subject-b": "customer-b"}}, tmp_path)
    service._transport = httpx.MockTransport(lambda _: pytest.fail("Gloria must not run the old consolidated flow"))
    return service, str(uuid.uuid4()), int(time.time()) + 3600


class TrustedWorkflowSpy:
    def __init__(self): self.calls = []
    async def run(self, binding, message, **kwargs):
        self.calls.append((dict(binding), message, kwargs))
        return {"response": {"message": "Necesito identificar el movimiento."}, "workflow_state": {"pending": {"type": "none"}}}


def test_gloria_send_reuses_host_admission_lock_and_public_transcript(admitted):
    service, sid, expiry = admitted
    runner = TrustedWorkflowSpy()
    output = asyncio.run(service.send("customer-a", sid, expiry, "private appended selection context", display_message="No reconozco esta compra.", workflow=runner))
    assert output["mode"] == "gloria"
    assert runner.calls[0][1] == "No reconozco esta compra."
    binding = runner.calls[0][0]
    assert binding["customer_id"] == "customer-a" and binding["session_id"] == sid
    assert binding["owner"] == service._owner_for_subject("subject-a")
    uuid.UUID(binding["conversation_id"])
    asyncio.run(service.send("customer-a", sid, expiry, "¿Qué dato necesitas?", workflow=runner))
    assert runner.calls[1][0] == binding
    history = service.history("customer-a", sid, expiry)
    assert "private appended" not in repr(history)
    assert len(history["messages"]) == 4


def test_customer_rebinding_is_rejected_before_workflow(admitted):
    service, sid, expiry = admitted
    runner = TrustedWorkflowSpy()
    asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=runner))
    with pytest.raises(ChatError):
        asyncio.run(service.send("customer-b", sid, expiry, "hola", workflow=runner))
    assert len(runner.calls) == 1


def test_revocation_during_workflow_blocks_response_and_transcript(admitted):
    service, sid, expiry = admitted
    class Revoking(TrustedWorkflowSpy):
        async def run(self, *args, **kwargs):
            result = await super().run(*args, **kwargs)
            service.queue_revoke("customer-a", sid, expiry)
            return result
    with pytest.raises(ChatError) as error:
        asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=Revoking()))
    assert error.value.code == "session_expired"
    with service._connection() as db:
        assert db.execute("SELECT count(*) FROM chat_messages").fetchone()[0] == 0
        assert db.execute("SELECT active_id FROM chat_sessions WHERE session_id=?", (sid,)).fetchone()[0] is None


@pytest.mark.parametrize("matching_conversation", [False, True])
def test_receipt_read_requires_exact_durable_conversation(admitted, matching_conversation):
    service, sid, expiry = admitted
    runner = TrustedWorkflowSpy()
    asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=runner))
    binding = runner.calls[0][0]
    with service._connection() as db:
        db.execute("INSERT INTO action_status(session_id,owner,expires,result_json,updated_at,prepare_conversation_id) VALUES (?,?,?,?,?,?)", (sid,binding["owner"],expiry,'{}',int(time.time()),binding["conversation_id"] if matching_conversation else str(uuid.uuid4())))
    async def status(*_): return {"state": "intake_verified", "target_reference": "txn_" + "a"*24, "receipt": action_receipt()}
    service.action_status = status
    repo = SimpleNamespace(profile_customer=lambda _: "customer-a")
    bank = RepositoryBank(repo, service, "fixture-profile", sid, expiry)
    bank.bind_context(binding)
    output = asyncio.run(bank.read("host_action_status", {}))
    assert output["binding_verified"] is matching_conversation
    assert output["binding"] == binding


def test_registered_gloria_tool_rejects_model_rewritten_turn():
    runner = TrustedWorkflowSpy()
    tool = make_run_turn_tool(runner, {"owner": "host-only"}, "original", "turn-a")
    with pytest.raises(ValueError, match="original turn"):
        asyncio.run(tool("model rewritten"))
    assert runner.calls == []
    server = create_mcp_server(runner, {"owner": "host-only"}, "original", "turn-a")
    tools = asyncio.run(server.list_tools())
    assert [item.name for item in tools] == ["gloria_run_turn"]
    schema = tools[0].inputSchema
    assert set(schema["properties"]) == {"message"}


def test_direct_model_port_has_no_tools_persistence_or_banking_assertion():
    seen = []
    def respond(request):
        seen.append(request)
        return httpx.Response(200,json={"choices":[{"message":{"content":"{}"}}],"usage":{"prompt_tokens":5,"completion_tokens":1}})
    model = FlujoModel("http://127.0.0.1:43420", "model-fixture", transport=httpx.MockTransport(respond))
    assert asyncio.run(model("detect_context","system","sanitized user")) == "{}"
    payload = json.loads(seen[0].content)
    assert set(payload) == {"model","messages","stream","temperature","max_tokens"}
    assert "X-Flujo-User-Assertion" not in seen[0].headers
    assert [m["role"] for m in payload["messages"]] == ["system","user"]


@pytest.mark.parametrize("endpoint",["http://example.com","https://name:pass@example.com","https://example.com/path"])
def test_direct_model_rejects_unapproved_endpoint_shape(endpoint):
    with pytest.raises(ValueError): FlujoModel(endpoint,"model-fixture")


def test_repository_default_window_uses_owned_latest_event(admitted):
    service, sid, expiry = admitted
    asyncio.run(service.send("customer-a",sid,expiry,"hola",workflow=TrustedWorkflowSpy()))
    def row(ref,day):
        return dict(reference=ref,occurred_at=day+"T12:00:00",process_date=day,
                    amount=25,currency="USD",status="Approved",type="Purchase")
    rows=[row("txn_"+"a"*24,"2026-06-01"),row("txn_"+"b"*24,"2026-09-01")]
    repo=SimpleNamespace(profile_customer=lambda _:"customer-a",
        overview=lambda *_,**__:dict(transactions=rows,products=[],metadata=dict(build_id="fictional",next_offset=None)))
    bank=RepositoryBank(repo,service,"fixture-profile",sid,expiry)
    result=asyncio.run(bank.read("search_transactions",dict(slots=dict(amount=25,currency="USD"))))
    assert result["match_count"] == 1
    assert result["candidates"][0]["transaction_id"] == "txn_"+"b"*24
    assert result["search_context"]["date_to"] == "2026-09-01"
    assert result["search_context"]["date_from"] == "2026-06-04"


def test_repository_search_rejects_snapshot_change_between_pages(admitted):
    service, sid, expiry = admitted
    asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=TrustedWorkflowSpy()))
    def overview(*_, offset=0):
        return dict(transactions=[], products=[], metadata=dict(
            build_id="first-snapshot" if offset == 0 else "changed-snapshot",
            next_offset=500 if offset == 0 else None))
    repo = SimpleNamespace(profile_customer=lambda _: "customer-a", overview=overview)
    bank = RepositoryBank(repo, service, "fixture-profile", sid, expiry)
    result = asyncio.run(bank.read("search_transactions", dict(slots=dict(currency="USD"))))
    assert result == dict(status="error", code="snapshot_changed")


@pytest.mark.parametrize("slots,expected", [
    ({"transaction_type": "Withdrawal"}, 0),
    ({"channel": "ATM"}, 0),
    ({"transaction_type": "Purchase", "channel": "POS"}, 1),
])
def test_repository_type_and_channel_filters_cannot_select_wrong_sole_candidate(admitted, slots, expected):
    service, sid, expiry = admitted
    asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=TrustedWorkflowSpy()))
    row = dict(reference="txn_" + "a" * 24, occurred_at="2026-09-01T12:00:00",
               process_date="2026-09-01", amount=25, currency="USD", status="Approved",
               type="Purchase", channel="POS")
    repo = SimpleNamespace(profile_customer=lambda _: "customer-a",
        overview=lambda *_, **__: dict(transactions=[row], products=[],
            metadata=dict(build_id="fictional", next_offset=None)))
    bank = RepositoryBank(repo, service, "fixture-profile", sid, expiry)
    result = asyncio.run(bank.read("search_transactions", {"slots": {"amount": 25, "currency": "USD", **slots}}))
    assert result["status"] == "ok"
    assert result["match_count"] == expected
    assert len(result["candidates"]) == expected


@pytest.mark.parametrize("field,value", [("city", "Bogotá"), ("country", "Colombia"),
                                         ("product_hint", "tarjeta"), ("product_last4", "1234")])
def test_repository_unsupported_filters_fail_before_search(admitted, field, value):
    service, sid, expiry = admitted
    asyncio.run(service.send("customer-a", sid, expiry, "hola", workflow=TrustedWorkflowSpy()))
    repo = SimpleNamespace(profile_customer=lambda _: "customer-a",
                           overview=lambda *_, **__: pytest.fail("unsupported filter must precede bank search"))
    bank = RepositoryBank(repo, service, "fixture-profile", sid, expiry)
    result = asyncio.run(bank.read("search_transactions", {"slots": {field: value}}))
    assert result == {"status": "error", "code": "unsupported_filter", "fields": [field]}
