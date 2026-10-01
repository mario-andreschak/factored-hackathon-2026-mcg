"""Independent release boundaries; all records, stores and transports are fictional.

Passing these scripted probes establishes the named boundaries only. It does not
establish provider understanding, human adjudication, native installation or a
deployed customer path. Required behavior stays asserted when source is incomplete.
"""
from __future__ import annotations

import asyncio
import csv
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import time
from pathlib import Path
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
from gloria_workflow.policy import decide
from gloria_workflow.response import validate_response
from gloria_workflow.retrieval import retrieve_policy
from gloria_workflow.runtime import Workflow
from gloria_workflow.state import ConversationStore
from tests.test_gloria_acceptance import (
    NOW, ObservedBank, ObservedStages, binding, mode, related, transaction,
    canonical_host_receipt, native_host_receipt,
    policy_state, SNAPSHOT,
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


@pytest.mark.parametrize("language,message,chunk_id", [
    ("es", "Puedes confirmar la recepción simulada en el control explícito del portal.", "dispute-03"),
    ("pt", "Você pode confirmar a solicitação simulada no controle explícito do portal.", "dispute-03"),
    ("es", "Puedes solicitar una revisión humana.", "handoff-01"),
    ("pt", "Você pode solicitar uma revisão humana.", "handoff-01"),
])
def test_reviewed_canonical_guidance_with_relevant_citation_remains_usable(language, message, chunk_id):
    inputs = dict(response_mode="INFORM", language=language, clean_query="Consulta del cliente.",
        historic_conversation="", structured_data=dict(status="ok", candidates=[], data_sources=[]),
        workflow_state={}, policy_context=retrieve_policy("TRANSACTION_DISPUTE", human_required=True))
    assert chunk_id in {chunk["chunk_id"] for chunk in inputs["policy_context"]}
    assert validate_response(response(message, language, [chunk_id]), inputs) == []


@pytest.mark.parametrize("language,message", [
    ("es", "Para reclamar, confirma una transferencia en el control explícito del portal."),
    ("pt", "Para reclamar, confirme uma transferência no controle explícito do portal."),
])
def test_reviewed_portal_guidance_cannot_be_repurposed_for_payment_or_transfer(language, message):
    inputs = dict(response_mode="INFORM", language=language, clean_query="Consulta del cliente.",
        historic_conversation="", structured_data=dict(status="ok", candidates=[], data_sources=[]),
        workflow_state={}, policy_context=retrieve_policy("TRANSACTION_DISPUTE"))
    assert validate_response(response(message, language, ["dispute-03"]), inputs)


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


@pytest.mark.parametrize("transplant", ["query_id", "request_id", "pending_handle"])
def test_same_target_snapshot_cannot_share_authority_between_query_capsules(transplant):
    state = policy_state()
    state["runtime"].update(query_scope_id="q_release_A", active_query_id="q_release_A")
    status = native_host_receipt()
    status.update(query_id="q_release_A", request_id=str(uuid.uuid4()), pending_handle="a"*43)
    state["tool_results"]["host_action_status"] = status
    workflow = state["workflow_state"]
    workflow["pending"].update(type="awaiting_confirmation", target_transaction_id=workflow["transaction_id"],
        snapshot_id=SNAPSHOT, snapshot_hash=SNAPSHOT, request_id=status["request_id"],
        host_pending_handle=status["pending_handle"], intent="TRANSACTION_DISPUTE", proposed_action="CREATE_COMPLAINT")
    result_id = status["receipt"]["id"]
    workflow.update(action_attempted=True, action_outcome="verified")
    workflow["action"].update(name="CREATE_COMPLAINT", authorized=True, executed=True,
        verified=True, result_id=result_id, receipt=dict(verified=True, result_id=result_id))
    assert decide(state)["response_mode"] == "ACTION_DONE"
    # All identity/target/snapshot facts stay equal. Only the per-query proof is
    # transplanted: target equality is not a consent or execution event.
    if transplant == "query_id":
        state["runtime"].update(query_scope_id="q_release_B", active_query_id="q_release_B")
    elif transplant == "request_id": workflow["pending"]["request_id"] = str(uuid.uuid4())
    else: workflow["pending"]["host_pending_handle"] = "b"*43
    assert decide(state)["response_mode"] != "ACTION_DONE"


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


def test_replayed_turn_cannot_change_selected_query_scope_before_reads(tmp_path):
    stages, bank = SeparateQueries(), SeparateBank()
    runner = Workflow(stages, bank, ConversationStore(tmp_path / "scope-replay.sqlite"), clock=lambda: NOW)
    state = asyncio.run(runner.run(binding(), QUERY_A + " " + QUERY_B, turn_id="batch"))
    query_id = state["runtime"]["query_scope_order"][0]
    asyncio.run(runner.run(binding(), "Consulta el movimiento seleccionado.", turn_id="resume", query_scope_id=query_id))
    before = (len(stages.calls), len(bank.calls))
    with pytest.raises(ValueError):
        asyncio.run(runner.run(binding(), "Consulta el movimiento seleccionado.", turn_id="resume",
                               query_scope_id=state["runtime"]["query_scope_order"][1]))
    assert (len(stages.calls), len(bank.calls)) == before


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


def rewrite_csv(path, transform, extra_fields=()):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields, rows = list(reader.fieldnames), list(reader)
    rows = transform(rows)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(fields + list(extra_fields))))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture(scope="module")
def release_source(tmp_path_factory):
    """A newly generated source and pipeline publication, never organizer files."""
    from pipeline.prototype_fixture import PERSONAS, write_prototype_source
    from pipeline.__main__ import main
    root = tmp_path_factory.mktemp("gloria-release-source")
    source = root / "source"
    write_prototype_source(source)
    # Private source metadata tests a real last-four filter without adding
    # these fictional full numbers to serving rows, prompts or test assertions.
    def products(rows):
        for row in rows:
            row["product_number"] = "4000000000004381" if row["product_type"] == "Tarjeta Crédito" else "1000000000007729"
        return rows
    rewrite_csv(source / "products.csv", products, ["product_number"])
    target = None
    for path in sorted((source / "transactions").rglob("*.csv")):
        def events(rows):
            nonlocal target
            for row in rows: row["amount_usd"] = "12.50"
            if target is None:
                target = next((deepcopy(row) for row in rows if row["customer_id"] == PERSONAS[0].customer_id
                    and row["transaction_type"] == "Purchase" and row["transaction_status"] == "Approved"), None)
                if target:
                    # Canonical duplicate definition does not require matching
                    # merchant or product, only own amount/currency and <=2min.
                    twin = deepcopy(target)
                    twin.update(transaction_id="SYNTH-MX-NEAR-TWIN", product_id=PERSONAS[0].account_id,
                                merchant_name="Fictional Other Merchant")
                    twin["transaction_date"] = (datetime_from_text(target["transaction_date"]) + timedelta(seconds=60)).isoformat(sep=" ")
                    rows.append(twin)
            return rows
        rewrite_csv(path, events)
    for path in (source / "complaints").rglob("*.csv"):
        def complaints(rows):
            for row in rows:
                if row["customer_id"] == PERSONAS[0].customer_id:
                    row.update(status="Open", category="Transactions", subcategory="Cargo no reconocido",
                               resolution_date="", resolution_days="", resolution="",
                               claimed_amount=target["amount"], affected_product_id=target["product_id"])
            return rows
        rewrite_csv(path, complaints)
    assert main(["run", "--source", str(source), "--out", str(root / "data"),
                 "--reports", str(root / "reports")]) == 0
    return SimpleNamespace(root=root, source=source, data=root / "data", person=PERSONAS[0], target=target)


def datetime_from_text(text):
    return datetime.fromisoformat(text)


@pytest.fixture
def complete_reads(release_source, tmp_path):
    from banking_mcp.config import Config
    from banking_mcp.security import Principal
    from banking_mcp.service import Service
    from frontend.server.config import Settings
    from frontend.server.repository import Repository
    from frontend.server.state import State
    from gloria_workflow.bank_read import OwnedBankReads
    source = release_source
    signer = Ed25519PrivateKey.generate()
    public = signer.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    service = Service(Config(data_dir=source.data, state_db=tmp_path / "bank.sqlite",
        service_token="fictional-release-token-"*3, public_keys={"release": public},
        principal_customers={"release-subject": source.person.customer_id,
                            "other-release-subject": "SYNTH-CO-001"},
        sandbox_report_coverage_start=int(NOW.timestamp())-90000))
    service.store.attest_sandbox_coverage(int(NOW.timestamp())-90000, "synthetic:release-complete-empty-ledger")
    public_state = State(tmp_path / "public-state")
    settings = Settings(data_dir=source.data, state_dir=tmp_path / "public-state", static_dir=tmp_path / "static",
        demo_code="fictional-code", profiles={source.person.profile: dict(customer_id=source.person.customer_id)})
    repository = Repository(settings, public_state)
    principal = Principal("release-subject", source.person.customer_id, "release-session", "release-conversation", int(time.time())+3600)
    reads = OwnedBankReads(service, repository, principal, source_root=source.source, clock=lambda: NOW.timestamp())
    ref = repository.reference("txn", principal.customer, source.target["transaction_id"])
    yield SimpleNamespace(reads=reads, service=service, repository=repository, principal=principal,
                          source=source, reference=ref, snapshot=service.repository.snapshot().id)
    service.close()


def read(port, name, **args):
    return asyncio.run(port.read(name, args))


def test_complete_profile_uses_owned_source_product_details(complete_reads):
    result = read(complete_reads.reads, "get_customer_profile")
    assert result["status"] == "ok"
    assert result["first_name"] == complete_reads.source.person.alias
    assert len(result["products"]) == 2
    for product in result["products"]:
        assert {"product_id", "product_type", "currency", "product_status", "product_last4"} <= product.keys()
    assert {product["product_last4"] for product in result["products"]} == {"4381", "7729"}


@pytest.mark.parametrize("slots", [
    dict(city="Ciudad de México"), dict(country="México"),
    dict(product_hint="Tarjeta Crédito"), dict(product_last4="4381"),
    dict(city="Ciudad de México", country="México", product_hint="Tarjeta Crédito", product_last4="4381"),
])
def test_actual_source_bank_honors_location_and_product_filters(complete_reads, slots):
    slots.update(transaction_id=complete_reads.reference,
                 date_from=complete_reads.source.target["transaction_date"][:10],
                 date_to=complete_reads.source.target["transaction_date"][:10])
    result = read(complete_reads.reads, "search_transactions", slots=slots)
    assert result["status"] == "ok"
    assert result["match_count"] == 1
    assert result["candidates"][0]["transaction_id"] == complete_reads.reference
    assert result["search_context"]["coverage_complete"] is True
    assert result["search_context"]["snapshot_id"] == complete_reads.snapshot
    assert result["snapshot_hash"] != complete_reads.snapshot


def test_authoritative_near_duplicate_does_not_require_same_product_or_merchant(complete_reads):
    result = read(complete_reads.reads, "get_transaction", transaction_id=complete_reads.reference,
                  snapshot_id=complete_reads.snapshot)
    assert result["status"] == "ok" and result["source_verified"] is True
    expected = complete_reads.repository.reference("txn", complete_reads.principal.customer, "SYNTH-MX-NEAR-TWIN")
    assert expected in repr(result["transaction"].get("possible_duplicate_of")), "target lost its canonical duplicate signal"
    assert "possible_duplicate" in result["data_quality_flags"]


def test_historical_status_is_owned_and_never_repaired_to_exact_transaction_link(complete_reads):
    listed = read(complete_reads.reads, "list_customer_complaints")
    assert listed["status"] == "ok" and listed["coverage_complete"] is True
    assert listed["match_count"] == 1
    case = listed["complaints"][0]
    assert case["complaint_id"] == "SYNTH-MX-OLD-CASE" and case["status"] == "Open"
    assert case["transaction_id"] is None and case["linkage"] == "unknown"
    exact = read(complete_reads.reads, "get_complaint", complaint_id=case["complaint_id"], snapshot_hash=listed["snapshot_hash"])
    assert exact["status"] == "ok" and exact["complaint"]["transaction_id"] is None
    foreign = read(complete_reads.reads, "get_complaint", complaint_id="SYNTH-CO-OLD-CASE")
    absent = read(complete_reads.reads, "get_complaint", complaint_id="SYNTH-ABSENT-CASE")
    assert foreign == absent
    assert foreign["status"] == "error"
    related_result = read(complete_reads.reads, "get_related_complaints", transaction_id=complete_reads.reference)
    assert related_result["status"] == "ok"
    assert related_result["complaints"] == []
    assert related_result["duplicate_check"] == "historical_uncertain"
    assert related_result["historical_candidates"][0]["linkage"] == "unknown"
    assert related_result["report_window"]["prior_distinct_verified_count"] == 0
    assert related_result["report_window"]["coverage_complete"] is True


@pytest.mark.parametrize("source_name", ["customers.csv", "products.csv", "transaction", "complaint"])
def test_pinned_source_mutation_cannot_reuse_ingestion_validation(complete_reads, source_name):
    source = complete_reads.source.source
    path = (source / source_name if source_name.endswith(".csv") else
            next((source / ("transactions" if source_name == "transaction" else "complaints")).rglob("*.csv")))
    if source_name == "transaction":
        path = next(p for p in (source / "transactions").rglob("*.csv") if complete_reads.source.target["transaction_id"] in p.read_text(encoding="utf-8"))
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"\n")
        name = "get_related_complaints" if source_name == "complaint" else "get_transaction"
        result = read(complete_reads.reads, name, transaction_id=complete_reads.reference)
        assert result["status"] == "error"
        assert result.get("source_verified") is not True
        assert result.get("risk_data_complete") is not True
    finally:
        path.write_bytes(original)


def test_unattested_ledger_does_not_mean_zero_prior_reports(complete_reads):
    with complete_reads.service.store.connect() as db: db.execute("DELETE FROM sandbox_coverage")
    result = read(complete_reads.reads, "get_related_complaints", transaction_id=complete_reads.reference)
    assert result["status"] == "ok"
    assert result["report_window"]["coverage_complete"] is False
    assert result["report_window"]["prior_distinct_verified_count"] is None


@pytest.mark.parametrize("selector", ["customer_id", "owner", "session_id", "conversation_id", "principal"])
def test_actual_read_port_rejects_model_supplied_identity_before_data_access(complete_reads, selector):
    result = read(complete_reads.reads, "get_customer_profile", **{selector: "other-fictional-owner"})
    assert result == dict(status="error", code="authorization_denied")


def test_complete_search_count_is_not_the_five_candidate_display_limit(complete_reads):
    result = read(complete_reads.reads, "search_transactions", slots={})
    assert result["status"] == "ok"
    assert result["match_count"] > 5
    assert len(result["candidates"]) == 5
    assert result["search_context"]["coverage_complete"] is True
    # All references resolve inside the owner and disclosed candidate snapshot.
    for candidate in result["candidates"]:
        target = read(complete_reads.reads, "get_transaction", transaction_id=candidate["transaction_id"],
                      snapshot_id=result["search_context"]["snapshot_id"])
        assert target["status"] == "ok"
        assert target["transaction"]["transaction_id"] == candidate["transaction_id"]


def test_foreign_and_absent_transaction_references_are_indistinguishable(complete_reads):
    foreign = complete_reads.repository.reference("txn", "SYNTH-CO-001", "SYNTH-CO-UNRECOGNIZED")
    missing = complete_reads.repository.reference("txn", complete_reads.principal.customer, "SYNTH-MISSING")
    a = read(complete_reads.reads, "get_transaction", transaction_id=foreign)
    b = read(complete_reads.reads, "get_transaction", transaction_id=missing)
    assert a == b and a["status"] == "error"


def test_exact_read_requires_the_disclosed_build_not_candidate_digest(complete_reads):
    result = read(complete_reads.reads, "get_transaction", transaction_id=complete_reads.reference,
                  snapshot_id="different-build")
    assert result == dict(status="error", code="snapshot_changed")


def save_prior_receipt(port, *, case_id, raw_target, created_at, owner=None, receipt=True):
    snapshot, row = port.service.repository.owned_transaction_id(port.principal, raw_target, port.snapshot)
    facts = port.service.repository._visible(row, snapshot)
    proof = dict(id=case_id, kind="simulated_intake", simulated=True, status="received",
        snapshot=port.snapshot, created_at=datetime.fromtimestamp(created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
        transaction=facts)
    with port.service.store.connect() as db:
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)", (case_id, owner or port.principal.customer,
            raw_target, "simulated_intake", port.snapshot, created_at, json.dumps(facts)))
        if receipt: db.execute("INSERT INTO sandbox_case_receipts VALUES (?,?)", (case_id, json.dumps(proof)))


def test_prior_report_window_counts_only_distinct_releasable_owned_receipts(complete_reads):
    now = NOW.timestamp()
    target = complete_reads.source.target["transaction_id"]
    save_prior_receipt(complete_reads, case_id="CMP-SBX-Rel00001", raw_target="SYNTH-MX-NEAR-TWIN", created_at=now-86400)
    save_prior_receipt(complete_reads, case_id="CMP-SBX-Rel00002", raw_target=target, created_at=now-1)
    save_prior_receipt(complete_reads, case_id="CMP-SBX-Rel00003", raw_target="SYNTH-MX-TX-001", created_at=now,
                       receipt=False)
    result = read(complete_reads.reads, "get_related_complaints", transaction_id=complete_reads.reference)
    assert result["status"] == "ok"
    assert result["report_window"]["coverage_complete"] is True
    assert result["report_window"]["prior_distinct_verified_count"] == 1
    assert result["duplicate_check"] == "exact_open_case"
    assert result["complaints"][0]["complaint_id"] == "CMP-SBX-Rel00002"
    assert result["complaints"][0]["transaction_id"] == complete_reads.reference
    assert result["complaints"][0]["linkage"] == "exact_sandbox"


def test_corrupt_in_window_receipt_never_becomes_complete_zero_risk(complete_reads):
    save_prior_receipt(complete_reads, case_id="CMP-SBX-Rel00001", raw_target="SYNTH-MX-NEAR-TWIN",
                       created_at=NOW.timestamp()-1, receipt=False)
    result = read(complete_reads.reads, "get_related_complaints", transaction_id=complete_reads.reference)
    assert result["status"] == "ok"
    assert result["report_window"]["coverage_complete"] is False
    assert result["report_window"]["prior_distinct_verified_count"] is None


def test_expired_workflow_pending_cannot_confirm_older_portal_handle_after_restart(joined):
    asyncio.run(joined.send("No reconozco esta compra de 25.50 USD."))
    pending = asyncio.run(joined.prepare())
    # The application may have a shorter pending TTL than the banking handle.
    joined.runner.store = ConversationStore(joined.tmp_path / "workflow.sqlite", pending_ttl_seconds=1)
    joined.runner.clock = lambda: NOW + timedelta(seconds=2)
    restarted = ChatService(joined.config, joined.tmp_path / "chat")
    restarted._transport = joined.service._transport
    joined.service.__dict__.update(restarted.__dict__)
    # A chat turn lets the host observe expiration through the real store/runtime.
    asyncio.run(joined.send("¿Sigue pendiente la solicitud?"))
    before = len(joined.requests)
    with pytest.raises(ChatError): asyncio.run(joined.confirm(pending["pending_handle"]))
    assert len(joined.requests) == before


def test_native_tool_closure_keeps_selection_and_identity_in_trusted_context():
    from gloria_workflow.tool import create_mcp_server
    class Recorder:
        def __init__(self): self.calls = []
        async def run(self, context, message, **kwargs):
            self.calls.append((deepcopy(context), message, deepcopy(kwargs)))
            return dict(response=dict(message="Respuesta verificada.", language="es"),
                workflow_state=dict(policy_decision=dict(rule_ids=["R13"])), turn=dict(turn_id="same-turn"))
    selection = ChatService._selection(dict(reference="txn_"+"a"*24,
        occurred_at=NOW.isoformat(), type="Purchase", amount=25.50, currency="USD", status="Approved"))
    context, runner = binding(), Recorder()
    # Selection is an already validated host value, never an extra model argument.
    server = create_mcp_server(runner, context, "original", "same-turn", selection=selection)
    context["customer_id"] = "mutated-foreign-owner"
    selection["reference"] = "txn_"+"b"*24
    tools = asyncio.run(server.list_tools())
    assert [item.name for item in tools] == ["gloria_run_turn"]
    assert set(tools[0].inputSchema["properties"]) == {"message"}
    asyncio.run(server.call_tool("gloria_run_turn", dict(message="original")))
    assert runner.calls[0][0]["customer_id"] == binding()["customer_id"]
    assert runner.calls[0][2]["selection"]["reference"] == "txn_"+"a"*24
