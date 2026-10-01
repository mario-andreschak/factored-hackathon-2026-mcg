"""Independent release boundaries; all records, stores and transports are fictional.

Passing these scripted probes establishes the named boundaries only. It does not
establish provider understanding, human adjudication, native installation or a
deployed customer path. Required behavior stays asserted when source is incomplete.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
import json
import time
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import httpx
import pytest
from pydantic import ValidationError

from frontend.server.chat import ChatError, ChatService
from frontend.server.app import ConfirmActionBody
from frontend.tests.action_fixtures import action_facts, action_receipt, action_selected
from gloria_workflow.host import RepositoryBank
from gloria_workflow.response import validate_response
from gloria_workflow.runtime import Workflow
from gloria_workflow.state import ConversationStore
from tests.test_gloria_acceptance import (
    NOW, ObservedBank, ObservedStages, binding, mode, related, transaction,
    canonical_host_receipt, native_host_receipt,
)


def response(message, language="es", chunks=()):
    return dict(message=message, language=language, arquetipos=[],
                chunk_ids=list(chunks), data_sources=[], grounding_violation=0)


@pytest.mark.parametrize("language,message", [
    ("es", "Puedes bloquear tu tarjeta por precaución."),
    ("pt", "Você pode bloquear seu cartão por precaução."),
    ("es", "Si prefieres, cambia tu clave para prevenir otra compra."),
    ("pt", "Se preferir, altere sua senha para prevenir outra compra."),
])
@pytest.mark.parametrize("cite_unrelated", [False, True])
def test_recommendations_require_support_not_merely_a_valid_chunk_id(language, message, cite_unrelated):
    inputs = dict(response_mode="INFORM", language=language,
        clean_query="Consulta sobre un movimiento propio.", historic_conversation="",
        structured_data=dict(status="ok", candidates=[transaction()], data_sources=["transactions"]),
        workflow_state=dict(transaction_id=transaction()["transaction_id"]),
        policy_context=dict(chunks=[dict(chunk_id="release-observed-facts",
            source="fictional-policy.md", text="Se pueden comunicar fecha, importe y estado del movimiento propio verificado.")]))
    candidate = response(message, language, ["release-observed-facts"] if cite_unrelated else [])
    assert validate_response(candidate, inputs), "conditional advice without policy support was accepted"


@pytest.mark.parametrize("language,message", [
    ("es", "Si lo deseas, bloquea tu tarjeta por precaución."),
    ("pt", "Se desejar, bloqueie seu cartão por precaução."),
])
def test_repeated_unreviewed_advice_uses_bounded_repair_then_safe_fallback(tmp_path, language, message):
    stages = ObservedStages(intent="TRANSACTION_INQUIRY", language=language,
                            generated=response(message, language))
    runner = Workflow(stages, ObservedBank(), ConversationStore(tmp_path / "advice.sqlite"), clock=lambda: NOW)
    state = asyncio.run(runner.run(binding(), "¿Dónde fue la compra de 25.50 USD?", turn_id="advice"))
    assert mode(state) == "INFORM"
    assert state["runtime"]["safe_fallback_used"] is True
    assert len([call for call in stages.calls if call[0] == "generate"]) == 2
    assert state["response"]["message"] != message
    assert state["response"]["language"] == language


@pytest.mark.parametrize("conflict", ["identifier", "amount", "snapshot"])
def test_contradictory_canonical_and_native_receipts_never_verify_each_other(tmp_path, conflict):
    host = canonical_host_receipt()
    native = native_host_receipt()["receipt"]
    if conflict == "identifier": native["id"] = "CMP-SBX-Conflict"
    if conflict == "amount": native["transaction"]["amount"] = "999.00"
    if conflict == "snapshot": native["snapshot"] = "contradictory-snapshot"
    host["receipt"] = native
    bank = ObservedBank(host_status=host)
    runner = Workflow(ObservedStages(), bank, ConversationStore(tmp_path / "mixed-proof.sqlite"), clock=lambda: NOW)
    state = asyncio.run(runner.run(binding(), "No reconozco esta compra de 25.50 USD.", turn_id="mixed-proof"))
    assert mode(state) != "ACTION_DONE"
    assert not state["workflow_state"]["action"]["verified"]
    assert native["id"] not in state["response"]["message"]


def test_new_target_after_verified_terminal_does_not_inherit_prior_receipt(tmp_path):
    bank = ObservedBank(host_status=native_host_receipt())
    stages = ObservedStages()
    store_path = tmp_path / "terminal.sqlite"
    runner = Workflow(stages, bank, ConversationStore(store_path), clock=lambda: NOW)
    first = asyncio.run(runner.run(binding(), "No reconozco esta compra de 25.50 USD.", turn_id="first"))
    assert mode(first) == "ACTION_DONE"
    other = transaction(transaction_id="TRX-RELEASE_OTHER", amount=84, currency="EUR")
    bank.candidates = [other]
    bank.host_status = dict(status="ok", state="none")
    stages.intent = "TRANSACTION_INQUIRY"
    stages.slots = dict(transaction_id=other["transaction_id"], amount=84, currency="EUR")
    restarted = Workflow(stages, bank, ConversationStore(store_path), clock=lambda: NOW)
    second = asyncio.run(restarted.run(binding(), "Ahora consulta el movimiento de 84 EUR.", turn_id="second"))
    assert mode(second) == "INFORM"
    assert second["workflow_state"]["transaction_id"] == other["transaction_id"]
    assert not second["workflow_state"]["action"]["verified"]
    assert first["workflow_state"]["action"]["result_id"] not in repr(second["response"])


QUERY_A = "No reconozco la compra de 25.50 USD en Fictional Orchid."
QUERY_B = "¿Cuál es el estado de la compra de 84.00 EUR en Fictional Cedar?"
TARGET_A = "TRX-RELEASE_A"
TARGET_B = "TRX-RELEASE_B"


class SeparateQueries(ObservedStages):
    async def run(self, stage, inputs, *, correction=None):
        if stage == "rewrite_decompose":
            self.calls.append((stage, deepcopy(inputs)))
            return dict(clean_query=inputs["user_question"], sub_queries=[
                dict(query_text=QUERY_A), dict(query_text=QUERY_B)])
        if stage == "detect_intent":
            self.calls.append((stage, deepcopy(inputs)))
            return dict(intents=[dict(query_text=QUERY_A, domain="TRANSACTION_DISPUTE"),
                                 dict(query_text=QUERY_B, domain="TRANSACTION_INQUIRY")])
        if stage == "extract_slots":
            query = inputs["clean_query"]
            self.slots = (dict(amount=25.50, currency="USD", merchant="Fictional Orchid", transaction_id=TARGET_A)
                          if query == QUERY_A else
                          dict(amount=84, currency="EUR", merchant="Fictional Cedar", transaction_id=TARGET_B))
        return await super().run(stage, inputs, correction=correction)


class SeparateBank(ObservedBank):
    def __init__(self):
        super().__init__(candidates=[transaction(transaction_id=TARGET_A, merchant_name="Fictional Orchid"),
            transaction(transaction_id=TARGET_B, amount=84, currency="EUR", merchant_name="Fictional Cedar")])

    async def read(self, name, args):
        if name == "search_transactions":
            self.calls.append((name, deepcopy(args)))
            target = args["slots"].get("transaction_id")
            rows = [deepcopy(row) for row in self.candidates if row["transaction_id"] == target]
            return dict(status="ok", match_count=len(rows), candidates=rows,
                snapshot_hash="candidate-digest-" + str(target), risk_signals={}, data_quality_flags=[],
                search_context=dict(date_from="2026-09-01", date_to="2026-09-30", date_basis="event_date",
                    snapshot_id="snapshot-" + str(target), used_snapshot_default=False, coverage_complete=True))
        result = await super().read(name, args)
        if name == "get_transaction" and result["status"] == "ok":
            result.update(snapshot_id="snapshot-" + args["transaction_id"], snapshot_hash="snapshot-" + args["transaction_id"])
        return result


@pytest.mark.parametrize("language", ["es", "pt"])
def test_multiquery_targets_snapshots_and_pending_are_independent(tmp_path, language):
    stages, bank = SeparateQueries(language=language), SeparateBank()
    runner = Workflow(stages, bank, ConversationStore(tmp_path / "multi.sqlite"), clock=lambda: NOW)
    state = asyncio.run(runner.run(binding(), QUERY_A + " " + QUERY_B, turn_id="multi"))
    assert not any(error.get("code") == "multiple_queries_need_separate_turns" for error in state["runtime"]["node_errors"])
    extracts = [inputs["clean_query"] for name, inputs in stages.calls if name == "extract_slots"]
    assert extracts == [QUERY_A, QUERY_B]
    searches = [args["slots"] for name, args in bank.calls if name == "search_transactions"]
    assert [(s["transaction_id"], s["amount"], s["currency"]) for s in searches] == [(TARGET_A, 25.50, "USD"), (TARGET_B, 84, "EUR")]
    rereads = [args for name, args in bank.calls if name == "get_transaction"]
    assert [(a["transaction_id"], a["snapshot_id"]) for a in rereads] == [(TARGET_A, "snapshot-"+TARGET_A), (TARGET_B, "snapshot-"+TARGET_B)]
    generated = [inputs for name, inputs in stages.calls if name == "generate"]
    assert len(generated) == 2
    assert [inputs["response_mode"] for inputs in generated] == ["CONFIRM_ACTION", "INFORM"]
    for target, inputs in zip((TARGET_A, TARGET_B), generated):
        assert inputs["workflow_state"]["transaction_id"] == target
        assert inputs["structured_data"]["transaction"]["transaction_id"] == target
        other = TARGET_B if target == TARGET_A else TARGET_A
        assert other not in repr(inputs["structured_data"])
        assert not inputs["workflow_state"]["action"]["authorized"]
    assert generated[0]["workflow_state"]["pending"]["target_transaction_id"] == TARGET_A
    assert generated[1]["workflow_state"]["pending"]["type"] == "none"


@pytest.fixture
def joined(tmp_path):
    key = Ed25519PrivateKey.generate()
    key_path = tmp_path / "signer.pem"
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    config = dict(base_url="http://flujo:4200", model="flow-Banking_Customer",
        execution_token="fictional-execution-token", frontend_signing_key_file=str(key_path),
        frontend_kid="release", frontend_issuer="release", frontend_audience="flujo-banking-ingress",
        principal_customers={"release-subject": "release-customer"}, action_enabled=True)
    service = ChatService(config, tmp_path / "chat")
    sid, expiry = str(uuid.uuid4()), int(time.time()) + 3600
    selected = action_selected(occurred_at=(NOW-timedelta(days=10)).replace(tzinfo=None).isoformat(),
        process_date=(NOW-timedelta(days=10)).date().isoformat(), amount=25.5, currency="USD",
        type="Purchase", merchant="Fictional Orchid", product="Credit Card", channel="POS")
    reference, snapshot = "txn_" + "a"*24, "release-snapshot"
    row = transaction(transaction_id=reference, transaction_date=selected["occurred_at"],
        process_date=selected["process_date"], merchant_name=selected["merchant"], product=selected["product"])
    port = SimpleNamespace(profile_customer=lambda _: "release-customer")
    host_bank = RepositoryBank(port, service, "fictional-profile", sid, expiry)
    requests = []
    receipt = action_receipt("CMP-SBX-Release1", snapshot=snapshot, selected=selected)
    def transport(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/v1/banking/action"
        if payload["operation"] == "prepare":
            return httpx.Response(200, json=dict(state="pending_confirmation", snapshot=snapshot,
                transaction=action_facts(selected), pending_handle="a"*43))
        if payload["operation"] in {"confirm", "receipt"}:
            if payload["operation"] == "confirm": assert payload["confirmed"] is True
            return httpx.Response(200, json=dict(state="intake_verified", receipt=deepcopy(receipt)))
        pytest.fail("unexpected upstream operation")
    service._transport = httpx.MockTransport(transport)
    class JoinedBank(ObservedBank):
        def bind_context(self, context): host_bank.bind_context(context)
        async def read(self, name, args):
            if name == "host_action_status":
                self.calls.append((name, deepcopy(args)))
                return await host_bank.read(name, args)
            result = await super().read(name, args)
            if name == "search_transactions": result["search_context"]["snapshot_id"] = snapshot
            if name == "get_transaction": result.update(snapshot_id=snapshot, snapshot_hash=snapshot)
            return result
    bank = JoinedBank(candidates=[row])
    stages = ObservedStages(slots=dict(transaction_id=reference))
    store = ConversationStore(tmp_path / "workflow.sqlite")
    runner = Workflow(stages, bank, store, clock=lambda: NOW)
    async def send(message):
        return await service.send("release-customer", sid, expiry, message, workflow=runner)
    async def prepare():
        return await service.action("release-customer", sid, expiry,
            dict(operation="prepare", transactionId="fictional-source-id", snapshot=snapshot),
            target_reference=reference, expected_transaction=selected)
    async def confirm(handle, consent=True):
        return await service.action("release-customer", sid, expiry,
            dict(operation="confirm", pendingHandle=handle, confirmed=consent),
            target_reference=reference, expected_snapshot=snapshot, expected_transaction=selected)
    return SimpleNamespace(service=service, config=config, sid=sid, expiry=expiry, runner=runner,
        stages=stages, bank=bank, store=store, send=send, prepare=prepare, confirm=confirm,
        requests=requests, receipt=receipt, tmp_path=tmp_path)


@pytest.mark.parametrize("resolution,message", [
    ("DENIED", "No quiero continuar con este reclamo."),
    ("NEW_REQUEST", "Ahora quiero consultar otra compra."),
])
def test_chat_cancellation_or_new_request_revokes_prepared_portal_handle(joined, resolution, message):
    asyncio.run(joined.send("No reconozco esta compra de 25.50 USD."))
    pending = asyncio.run(joined.prepare())
    assert pending["state"] == "pending_confirmation"
    joined.stages.resolution = dict(resolution_type=resolution, selected_ref=None)
    asyncio.run(joined.send(message))
    before = len(joined.requests)
    with pytest.raises(ChatError):
        asyncio.run(joined.confirm(pending["pending_handle"]))
    assert len(joined.requests) == before, "revoked consent reached the upstream confirm operation"


def test_portal_false_consent_never_passes_public_request_validation(joined):
    asyncio.run(joined.send("No reconozco esta compra de 25.50 USD."))
    pending = asyncio.run(joined.prepare())
    before = len(joined.requests)
    with pytest.raises(ValidationError):
        ConfirmActionBody(transaction_reference="txn_" + "a"*24,
                          pending_handle=pending["pending_handle"], confirmed=False)
    assert len(joined.requests) == before


def test_verified_portal_receipt_is_joined_to_same_conversation_after_restart(joined):
    asyncio.run(joined.send("No reconozco esta compra de 25.50 USD."))
    pending = asyncio.run(joined.prepare())
    done = asyncio.run(joined.confirm(pending["pending_handle"]))
    assert done["state"] == "intake_verified"
    old = joined.service
    restarted = ChatService(joined.config, joined.tmp_path / "chat")
    restarted._transport = old._transport
    joined.service.__dict__.update(restarted.__dict__)
    result = asyncio.run(joined.send("¿Cuál es el estado de esta solicitud?"))
    assert "CMP-SBX-Release1" in result["reply"]
    assert not [p for p in joined.requests if p["operation"] == "confirm"][1:]


def test_revoked_session_cannot_recover_receipt_or_confirm_after_restart(joined):
    asyncio.run(joined.send("No reconozco esta compra de 25.50 USD."))
    pending = asyncio.run(joined.prepare())
    joined.service.queue_revoke("release-customer", joined.sid, joined.expiry)
    restarted = ChatService(joined.config, joined.tmp_path / "chat")
    restarted._transport = joined.service._transport
    before = len(joined.requests)
    with pytest.raises(ChatError): asyncio.run(restarted.action_status("release-customer", joined.sid, joined.expiry))
    with pytest.raises(ChatError):
        asyncio.run(restarted.action("release-customer", joined.sid, joined.expiry,
            dict(operation="confirm", pendingHandle=pending["pending_handle"], confirmed=True)))
    assert len(joined.requests) == before
