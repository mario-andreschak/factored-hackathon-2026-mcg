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
from decimal import Decimal
import hashlib
import json
import re
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


@pytest.mark.parametrize("language,claim", [
    ("es", "Ya se está procesando la solicitud."),
    ("es", "Tu solicitud está en proceso."),
    ("pt", "Sua solicitação está em processamento."),
    ("pt", "A solicitação está sendo processada."),
])
def test_present_processing_claim_requires_an_execution_receipt(language, claim):
    prefix = {
        "es": "Responder en este chat no autoriza ni registra la solicitud.",
        "pt": "Responder aqui no chat não faz o registro.",
    }[language]
    inputs = dict(response_mode="CONFIRM_ACTION", language=language,
        clean_query="No reconozco un movimiento propio.", historic_conversation="",
        structured_data=dict(status="ok", candidates=[transaction()], data_sources=["transactions"]),
        workflow_state=dict(transaction_id=transaction()["transaction_id"],
            action=dict(authorized=False, executed=False, verified=False, result_id=None)),
        policy_context=retrieve_policy("TRANSACTION_DISPUTE"))
    assert validate_response(response(prefix, language), inputs) == []
    assert validate_response(response(prefix + " " + claim, language), inputs), \
        "present processing was claimed without any execution or receipt"


@pytest.mark.parametrize("suffix,safe", [
    ("", True),
    ("; o encaminhamento foi realizado.", False),
    (" Um atendente já respondeu.", False),
])
def test_handoff_uncertainty_preserves_the_exact_negative_scope(suffix, safe):
    inputs = dict(response_mode="HANDOFF", language="pt", clean_query="Preciso de revisão humana.",
        historic_conversation="", structured_data=dict(status="ok", candidates=[], data_sources=[]),
        workflow_state=dict(action=dict(authorized=False, executed=False, verified=False, result_id=None),
            handoff=dict(created=False, handoff_id=None)),
        policy_context=retrieve_policy("HUMAN_REQUEST", human_required=True))
    text = "Ainda não posso confirmar que o encaminhamento foi realizado." + suffix
    errors = validate_response(response(text, "pt"), inputs)
    assert (errors == []) is safe, "truthful uncertainty must not grant a completed handoff or human response"


def test_captured_emergency_contact_advice_remains_unsupported():
    inputs = dict(response_mode="HANDOFF", language="pt", clean_query="Estou em perigo agora.",
        historic_conversation="", structured_data=dict(status="ok", candidates=[], data_sources=[]),
        workflow_state=dict(action=dict(authorized=False, executed=False, verified=False, result_id=None),
            handoff=dict(created=False, handoff_id=None)),
        policy_context=retrieve_policy("HUMAN_REQUEST", human_required=True))
    text = "Se o perigo for imediato, procure um local seguro e ligue para o serviço de emergência da sua região."
    assert "unsupported_operation_guidance" in validate_response(response(text, "pt"), inputs)


@pytest.mark.parametrize("detail", [
    "referente à compra de **2026-09-16** no valor de **209944.00 COP**",
    "referente à compra de **209944.00 COP** de **2026-09-16**",
])
def test_verified_receipt_sentence_keeps_its_decimal_amount_and_bound_id(detail):
    target = transaction(amount=209944.00, currency="COP", transaction_date="2026-09-16T12:00:00+00:00")
    action = canonical_host_receipt()["action"]
    inputs = dict(response_mode="ACTION_DONE", language="pt", clean_query="Qual é o estado desta solicitação?",
        historic_conversation="", structured_data=dict(status="ok", candidates=[target], data_sources=["transactions"]),
        workflow_state=dict(transaction_id=target["transaction_id"], action=action),
        policy_context=retrieve_policy("TRANSACTION_DISPUTE"))
    text = (f"A solicitação simulada **{action['result_id']}**, {detail}, "
            "foi registrada e teve o registro verificado no ambiente de teste.")
    assert validate_response(response(text, "pt"), inputs) == [], \
        "a decimal point inside a verified amount must not detach the receipt ID from its sentence"


def test_verified_decimal_receipt_does_not_authorize_a_separate_success_sentence():
    target = transaction(amount=209944.00, currency="COP", transaction_date="2026-09-16T12:00:00+00:00")
    action = canonical_host_receipt()["action"]
    inputs = dict(response_mode="ACTION_DONE", language="pt", clean_query="Qual é o estado desta solicitação?",
        historic_conversation="", structured_data=dict(status="ok", candidates=[target], data_sources=["transactions"]),
        workflow_state=dict(transaction_id=target["transaction_id"], action=action),
        policy_context=retrieve_policy("TRANSACTION_DISPUTE"))
    text = (f"A solicitação simulada **{action['result_id']}**. "
            "A compra de **209944.00 COP** foi registrada no ambiente de teste.")
    assert "action_success_unverified" in validate_response(response(text, "pt"), inputs), \
        "a decimal amount must not join an unrelated success sentence to the preceding receipt ID"


@pytest.mark.parametrize("extra_contact,safe", [("", True),
    (" Ligue para o serviço de emergência local.", False)])
def test_captured_human_request_restatement_does_not_grant_contact_guidance(extra_contact, safe):
    inputs = dict(response_mode="HANDOFF", language="pt",
        clean_query="É uma emergência. Estou em perigo agora e preciso falar com um atendente humano.",
        historic_conversation="", structured_data=dict(status="ok", candidates=[], data_sources=[]),
        workflow_state=dict(action=dict(authorized=False, executed=False, verified=False, result_id=None),
            handoff=dict(required=True, created=False, handoff_id=None, reason_code="emergency"),
            policy_decision=dict(response_mode="HANDOFF", reason_code="emergency")),
        policy_context=retrieve_policy("HUMAN_REQUEST", human_required=True))
    text = ("Entendo que é uma emergência e que você precisa falar com um atendente humano. "
            "Sua solicitação precisa de atendimento humano, mas ainda não posso confirmar o encaminhamento."
            + extra_contact)
    errors = validate_response(response(text, "pt"), inputs)
    assert (errors == []) is safe, "restating the customer's human request must not grant unsourced contact instructions"
    if not safe:
        assert "unsupported_operation_guidance" in errors


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
    from gloria_workflow.state import (TrustedBinding, new_state, begin_turn,
                                      start_query_batch, activate_query_scope)
    trusted = TrustedBinding(**binding())
    base = begin_turn(new_state(trusted, now=NOW), trusted, turn_id="scoped-proof",
                      user_question="Dos solicitudes sobre el mismo movimiento.", now=NOW)
    base = start_query_batch(base, [dict(query_text="Primera solicitud", domain="TRANSACTION_DISPUTE"),
                                   dict(query_text="Segunda solicitud", domain="TRANSACTION_DISPUTE")])
    query_a, query_b = base["runtime"]["query_scope_order"]
    state = activate_query_scope(base, trusted, query_a, now=NOW)
    facts = policy_state()
    state["workflow_state"], state["tool_results"] = deepcopy(facts["workflow_state"]), deepcopy(facts["tool_results"])
    state["tool_results"]["get_transaction"].update(snapshot_id=SNAPSHOT, snapshot_hash=SNAPSHOT)
    state["runtime"]["query_scope_id"] = query_a
    status = native_host_receipt()
    status.update(query_id=query_a, request_id=str(uuid.uuid4()), pending_handle="a"*43)
    state["tool_results"]["host_action_status"] = status
    workflow = state["workflow_state"]
    workflow["pending"].update(type="awaiting_confirmation", target_transaction_id=workflow["transaction_id"],
        snapshot_id=SNAPSHOT, snapshot_hash=SNAPSHOT, request_id=status["request_id"],
        host_pending_handle=status["pending_handle"], intent="TRANSACTION_DISPUTE", proposed_action="CREATE_COMPLAINT",
        query_id=query_a)
    result_id = status["receipt"]["id"]
    workflow.update(action_attempted=True, action_outcome="verified")
    workflow["action"].update(name="CREATE_COMPLAINT", authorized=True, executed=True,
        verified=True, result_id=result_id, receipt=dict(verified=True, result_id=result_id))
    assert decide(state)["response_mode"] == "ACTION_DONE"
    # All identity/target/snapshot facts stay equal. Only the per-query proof is
    # transplanted: target equality is not a consent or execution event.
    if transplant == "query_id":
        sibling = activate_query_scope(base, trusted, query_b, now=NOW)
        sibling["workflow_state"], sibling["tool_results"] = deepcopy(workflow), deepcopy(state["tool_results"])
        sibling["workflow_state"]["pending"]["query_id"] = query_b
        sibling["runtime"]["query_scope_id"] = query_b
        state = sibling
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
            if query == QUERY_A:
                self.slots = dict(amount=25.50, currency="USD", merchant="Fictional Orchid", transaction_id=TARGET_A)
            elif query == QUERY_B:
                self.slots = dict(amount=84, currency="EUR", merchant="Fictional Cedar", transaction_id=TARGET_B)
            else:
                # The original-text extraction is an ownership-only barrier.
                # Deliberately poisonous blended slots must never reach a query.
                assert query == QUERY_A + " " + QUERY_B
                self.slots = dict(amount=999, currency="JPY", transaction_id="TRX-GLOBAL_GUARD")
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
    assert extracts == [QUERY_A, QUERY_B, QUERY_A + " " + QUERY_B]
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
    capsules = [state["runtime"]["query_scopes"][query_id] for query_id in state["runtime"]["query_scope_order"]]
    assert capsules[0]["workflow_state"]["pending"]["target_transaction_id"] == TARGET_A
    assert capsules[0]["workflow_state"]["pending"]["query_id"] == capsules[0]["query_id"]
    assert capsules[1]["workflow_state"]["pending"]["type"] == "none"


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


def live_native_binding(**updates):
    result = binding()
    result["expires_at"] = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    result.update(updates)
    return result


def native_admissions(directory):
    location = directory / "admissions.json"
    return json.loads(location.read_text(encoding="utf-8")) if location.exists() else []


def test_native_port_returns_validated_workflow_result_and_private_selection(tmp_path):
    from scripts.native_gloria_qualification import NativeGloriaPort
    selected, trusted = dict(reference="txn_" + "c"*24), live_native_binding()
    expected = dict(response=response("Respuesta validada."))
    observed = []

    class ControlledWorkflow:
        async def run(self, identity, message, **options):
            records = native_admissions(tmp_path)
            assert len(records) == 1 and records[0]["mode"] == "language_only"
            observed.append((deepcopy(identity), message, deepcopy(options), records[0]))
            identity["owner"] = "mutated-local-copy"
            options["selection"]["reference"] = "mutated-local-copy"
            return expected

    port = NativeGloriaPort(lambda model: ControlledWorkflow(), "http://127.0.0.1:4200", tmp_path)
    result = asyncio.run(port.run(trusted, "Consulta propia.", turn_id="native-valid", selection=selected))
    assert result is expected
    assert observed[0][:3] == (trusted, "Consulta propia.", dict(turn_id="native-valid", selection=selected))
    assert observed[0][3]["conversation"] == trusted["conversation_id"]
    assert "selection" not in observed[0][3]
    assert native_admissions(tmp_path) == []


@pytest.mark.parametrize("failure", ["factory", "workflow"])
def test_native_port_failure_removes_only_its_own_admission(tmp_path, failure):
    from scripts.native_gloria_qualification import NativeGloriaPort
    sibling = dict(stageToken="fictional-sibling-stage", owner="fictional-sibling-owner")
    (tmp_path / "admissions.json").write_text(json.dumps([sibling]), encoding="utf-8")

    class FailingWorkflow:
        async def run(self, *args, **kwargs):
            assert len(native_admissions(tmp_path)) == 2
            raise RuntimeError("fictional workflow failure")

    def factory(model):
        assert len(native_admissions(tmp_path)) == 2
        if failure == "factory": raise RuntimeError("fictional factory failure")
        return FailingWorkflow()

    port = NativeGloriaPort(factory, "http://127.0.0.1:4200", tmp_path)
    with pytest.raises(RuntimeError):
        asyncio.run(port.run(live_native_binding(), "Consulta propia.", turn_id="native-failure"))
    assert native_admissions(tmp_path) == [sibling]


def test_native_port_cancellation_keeps_concurrent_sibling_identity_and_admission(tmp_path):
    from scripts.native_gloria_qualification import NativeGloriaPort
    from gloria_workflow.state import TrustedBinding
    identities = [live_native_binding(), live_native_binding(owner="second-fictional-owner",
                  session_id="second-session", conversation_id="second-conversation")]

    async def scenario():
        entered = [asyncio.Event(), asyncio.Event()]
        finish = asyncio.Event()

        class ControlledWorkflow:
            async def run(self, identity, message, **options):
                index = int(message)
                entered[index].set()
                await finish.wait()
                return dict(response=response("Respuesta propia."))

        port = NativeGloriaPort(lambda model: ControlledWorkflow(), "http://127.0.0.1:4200", tmp_path)
        tasks = [asyncio.create_task(port.run(identity, str(index), turn_id="native-"+str(index)))
                 for index, identity in enumerate(identities)]
        await asyncio.wait_for(asyncio.gather(*(event.wait() for event in entered)), timeout=2)
        records = native_admissions(tmp_path)
        assert len(records) == 2
        assert len({item["stageToken"] for item in records}) == 2
        expected_sibling = next(item for item in records if item["turnId"] == "native-1")
        assert {item["owner"] for item in records} == {TrustedBinding(**identity).owner for identity in identities}
        assert {item["conversation"] for item in records} == {identity["conversation_id"] for identity in identities}
        tasks[0].cancel()
        with pytest.raises(asyncio.CancelledError): await tasks[0]
        assert native_admissions(tmp_path) == [expected_sibling]
        finish.set()
        await tasks[1]
        assert native_admissions(tmp_path) == []

    asyncio.run(scenario())


def test_native_port_expired_binding_never_registers_or_calls_factory(tmp_path):
    from scripts.native_gloria_qualification import NativeGloriaPort
    sibling = dict(stageToken="fictional-sibling-stage", owner="fictional-sibling-owner")
    location = tmp_path / "admissions.json"
    location.write_text(json.dumps([sibling]), encoding="utf-8")
    before = location.read_bytes()
    calls = []
    port = NativeGloriaPort(lambda model: calls.append(model), "http://127.0.0.1:4200", tmp_path)
    identity = live_native_binding(expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
    with pytest.raises(ValueError): asyncio.run(port.run(identity, "Consulta propia.", turn_id="expired"))
    assert calls == [] and location.read_bytes() == before


def test_native_port_restart_recovers_abandoned_admission_writer(tmp_path):
    from scripts.native_gloria_qualification import NativeGloriaPort
    # This is the exact abandoned artifact after the previous process crashes
    # immediately after opening the marker. No active host owns the fixture.
    (tmp_path / ".admissions-host.lock").write_bytes(b"")

    class ControlledWorkflow:
        async def run(self, *args, **kwargs):
            return dict(response=response("Respuesta propia."))

    restarted = NativeGloriaPort(lambda model: ControlledWorkflow(), "http://127.0.0.1:4200", tmp_path)
    result = asyncio.run(restarted.run(live_native_binding(), "Consulta propia.", turn_id="restart"))
    assert result["response"]["message"] == "Respuesta propia."
    assert native_admissions(tmp_path) == []


@pytest.fixture(scope="module")
def qualification_fixture(tmp_path_factory):
    from scripts.qualify_gloria_app import build_fixture
    return build_fixture(tmp_path_factory.mktemp("joined-qualification") / "private")


def qualification_model_transport(fixture, authority):
    """Script canonical stage text through the actual model HTTP client."""
    from gloria_workflow.prompts import StageAdapters
    specs = StageAdapters(lambda *args: None).specs
    calls = []

    def transport(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions" and body["model"] == "model-gloria-native-model"
        token = request.headers["Authorization"].removeprefix("Bearer ")
        record = next(item for item in native_admissions(authority) if item["stageToken"] == token)
        assert record["mode"] == "language_only" and record["expires"] > time.time()*1000
        system = body["messages"][0]["content"]
        stage = next(name for name, spec in specs.items() if system.startswith(spec.system))
        message = record["message"]
        language = "pt" if message.startswith(("Não", "Qual", "É")) else "es"
        emergency = message.startswith("É uma emergência")
        target = fixture.targets["colombia" if "COP" in message else "mexico"]
        if stage == "rewrite_decompose":
            output = dict(clean_query=message, sub_queries=[dict(query_text=message)])
        elif stage == "detect_attack": output = dict(inappropriate=0, deceptive=0)
        elif stage == "detect_context":
            output = dict(language=language, emotional_context="Emergencia" if emergency else "Neutro")
        elif stage == "detect_intent":
            output = dict(intents=[dict(query_text=message, domain="HUMAN_REQUEST" if
                "humano" in message or "emergência" in message else "TRANSACTION_DISPUTE")])
        elif stage == "extract_slots":
            output = {key: None for key in ("amount", "currency", "currency_raw", "date_from", "date_to",
                "date_expression", "merchant", "transaction_type", "channel", "city", "country",
                "transaction_id", "complaint_id", "product_hint", "product_last4")}
            output.update(amount=float(target["amount"]), currency=target["currency"],
                date_from=target["transaction_date"][:10], date_to=target["transaction_date"][:10],
                amount_is_approximate=False, foreign_customer_reference=False)
        elif stage == "resolve_clarification": output = dict(resolution_type="UNCLEAR", selected_ref=None)
        elif stage == "generate_handoff_summary":
            output = dict(request_summary="El cliente solicita revisión.", customer_language=language,
                          customer_stated_claims=[], suggested_open_questions=[])
        elif stage == "generate":
            fields = dict(re.findall(r"\[([a-z_]+)\]\s*\n(.*?)(?=\n\s*\[[a-z_]+\]|\Z)", body["messages"][1]["content"], re.S))
            response_mode = json.loads(fields["response_mode"])
            language = json.loads(fields["language"])
            if response_mode == "ACTION_DONE":
                workflow = json.loads(fields["workflow_state"])
                case_id = workflow["action"]["result_id"]
                text = (f"Se verificó la recepción simulada del reclamo **{case_id}**." if language == "es" else
                        f"A solicitação simulada da reclamação **{case_id}** foi verificada.")
                output = response(text, language)
            elif response_mode == "CONFIRM_ACTION":
                text = ("Puedes confirmar la recepción simulada en el control explícito del portal." if language == "es" else
                        "Você pode confirmar a solicitação simulada no controle explícito do portal.")
                output = response(text, language, ["dispute-03"])
            elif response_mode == "HANDOFF":
                text = ("La solicitud requiere revisión humana. Aún no hay respuesta de una persona." if language == "es" else
                        "A solicitação precisa de revisão humana. Ainda não houve resposta de uma pessoa.")
                output = response(text, language)
            else: pytest.fail("unexpected mode in scripted qualifier generator")
        else: pytest.fail("unexpected scripted canonical stage")
        calls.append((stage, record["turnId"]))
        return httpx.Response(200, json=dict(model=fixture.service_token, id="chatcmpl-fictional",
            choices=[dict(finish_reason="stop", message=dict(role="assistant", content=json.dumps(output, ensure_ascii=False)))]))
    return httpx.MockTransport(transport), calls


def test_joined_qualifier_real_http_native_port_with_scripted_model_is_private_and_offline(qualification_fixture, tmp_path):
    from scripts.qualify_gloria_app import run_qualification
    fixture = qualification_fixture
    authority = tmp_path / "authority"
    authority.mkdir()
    (authority / "admissions.json").write_text("[]", encoding="utf-8")
    (authority / "native-profile.json").write_text('{"synthetic":true}', encoding="utf-8")
    previous_captures = set((fixture.root / "private-stage-outputs").glob("*.json"))
    transport, calls = qualification_model_transport(fixture, authority)
    report = run_qualification(fixture, "http://127.0.0.1:4200", authority, model_transport=transport,
                              request_timeout_seconds=20, native_timeout_seconds=2)
    assert report["passed"] is True, [(case["scenario"], case.get("failure_code"),
        [(attempt["step"], attempt.get("http_status")) for attempt in case["attempts"] if not attempt["passed"]]) for case in report["results"]]
    assert report["scenario_count"] == report["passed_scenarios"] == 4
    assert report["execution_mode"] == "scripted_offline" and report["human_adjudicated"] is False
    assert report["native_execution_verified"] is False and report["native_port_invoked"] is False
    assert report["model_call_observed"] is True and report["model_attempt_count"] == len(calls)
    assert report["usage"]["total_tokens"] is None and report["usage"]["cost_usd"] is None
    assert report["source_stable"] is True
    assert report["application_sources_before"] == report["application_sources_after"]
    assert "contracts/state_schema.md" in report["application_sources_before"]
    assert "pipeline/contracts.yaml" in report["application_sources_before"]
    assert native_admissions(authority) == []
    captures = set((fixture.root / "private-stage-outputs").glob("*.json")) - previous_captures
    assert len(captures) == len(calls)
    assert all(set(json.loads(path.read_text())) == {"stage", "output"} for path in captures)
    assert all("output" not in digest for case in report["results"] for attempt in case["attempts"]
               for turn in attempt["workflow_turns"] for digest in turn["stage_output_hashes"])
    public = json.dumps(report)
    for private_value in [fixture.demo_code, fixture.service_token, fixture.execution_token,
            fixture.public_key, fixture.signer.read_text(), *fixture.subject_customers,
            *fixture.subject_customers.values(), *(row["transaction_id"] for row in fixture.targets.values())]:
        assert private_value not in public
    for case in report["results"]:
        for attempt in case["attempts"]:
            assert "body" not in attempt and "reply" not in attempt and "cookies" not in attempt


def test_qualifier_provider_metadata_cannot_serialize_raw_identity_or_nonfinite_metrics():
    from scripts.qualify_gloria_app import _safe_observations
    private = "fictional-private-session-id"
    observed = _safe_observations(SimpleNamespace(observations=[dict(stage=private, status=private,
        model=private, response_model=private, response_id_kind=private, cost_usd=float("inf"),
        latency_ms=float("nan"), prompt_tokens=None)]))
    assert private not in json.dumps(observed)
    assert observed[0].get("stage") is None and observed[0].get("model") is None
    assert observed[0].get("status") is None and observed[0].get("cost_usd") is None
    assert observed[0].get("latency_ms") is None and observed[0].get("prompt_tokens") is None


def test_qualifier_private_capture_preserves_exact_stage_result_without_public_text(qualification_fixture):
    from scripts.qualify_gloria_app import CapturedModel
    observed = []
    output = '{"message":"Fictional private model text."}'
    async def source(stage, system, user):
        observed.append((stage, system, user))
        return output
    model = CapturedModel(source, qualification_fixture)
    assert asyncio.run(model("generate", "exact canonical system", "exact safe input")) == output
    assert observed == [("generate", "exact canonical system", "exact safe input")]
    assert model.captures == [dict(stage="generate", output_hmac_sha256=qualification_fixture.hash_id(output))]
    assert output not in json.dumps(model.captures)


def test_qualifier_rejects_changed_generated_source_before_application_admission(qualification_fixture, tmp_path):
    from scripts.qualify_gloria_app import build_application
    path = next(qualification_fixture.source.rglob("*.csv"))
    original = path.read_bytes()
    try:
        path.write_bytes(original+b"\n")
        with pytest.raises(ValueError, match="changed before application admission"):
            build_application(qualification_fixture, "http://127.0.0.1:4200", tmp_path / "uninstalled-authority",
                              instance="mutated-source", records=[])
    finally: path.write_bytes(original)


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
                    usd = deepcopy(target)
                    usd.update(transaction_id="SYNTH-MX-USD-PROBE", amount="143.50", currency="USD",
                        transaction_date=(NOW-timedelta(days=10)).replace(tzinfo=None).isoformat(sep=" "),
                        process_date=(NOW-timedelta(days=10)).date().isoformat(), merchant_name="Fictional USD Merchant")
                    rows.append(usd)
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
    rate_rows = set()
    for path in (source.source / "transactions").rglob("*.csv"):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rate_rows.update((row["transaction_date"][:10], row["currency"]) for row in csv.DictReader(stream))
    # These declared fictional rates exercise source lookup, never market prices.
    rates = tmp_path / "event-rates.csv"
    rates.write_text("date,currency,usd_rate\n" + "".join(
        f"{day},{currency},{'0.0001' if currency == 'COP' else '0.05'}\n" for day, currency in sorted(rate_rows)), encoding="utf-8")
    service = Service(Config(data_dir=source.data, state_db=tmp_path / "bank.sqlite",
        service_token="fictional-release-token-"*3, public_keys={"release": public},
        principal_customers={"release-subject": source.person.customer_id,
                            "other-release-subject": "SYNTH-CO-001"},
        event_rates_file=rates, event_rates_sha256=hashlib.sha256(rates.read_bytes()).hexdigest(),
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


def configure_rates(port, content):
    from banking_mcp.config import Config
    values = port.service.config.model_dump()
    values.update(event_rates_file=None, event_rates_sha256=None)
    if content is not None:
        location = port.service.store.path.parent / "independent-rates.csv"
        location.write_bytes(content)
        values.update(event_rates_file=location, event_rates_sha256=hashlib.sha256(content).hexdigest())
    port.service.config = Config(**values)


def test_nonusd_risk_uses_exact_event_date_rate_and_preserves_native_display(complete_reads):
    day = complete_reads.source.target["transaction_date"][:10]
    tomorrow = (datetime.fromisoformat(day)+timedelta(days=1)).date().isoformat()
    currency = complete_reads.source.target["currency"]
    configure_rates(complete_reads, f"date,currency,usd_rate\n{day},{currency},0.05\n{tomorrow},{currency},9\n2026-09-30,{currency},8\n".encode())
    result = read(complete_reads.reads, "get_transaction", transaction_id=complete_reads.reference)
    expected = abs(Decimal(complete_reads.source.target["amount"]))*Decimal("0.05")
    assert result["status"] == "ok" and result["source_verified"] is True
    assert result["risk_data_complete"] is True
    assert result["risk_signals"]["amount_usd"] == pytest.approx(float(expected))
    assert result["risk_signals"]["amount_usd"] != float(complete_reads.source.target["amount_usd"])
    assert result["risk_signals"]["amount_usd_provenance"] == dict(source="pinned_event_rates", date=day,
        currency=currency, rates_sha256=complete_reads.service.config.event_rates_sha256)
    assert Decimal(str(result["transaction"]["amount"])) == Decimal(complete_reads.source.target["amount"])
    assert result["transaction"]["currency"] == currency
    assert "amount_usd" not in result["transaction"]


@pytest.mark.parametrize("corruption", ["absent", "missing_file", "wrong_date", "wrong_currency", "hash", "duplicate",
    "header", "bad_date", "zero", "negative", "nan", "infinity", "overflow", "unrelated_bad_row", "oversized"])
def test_missing_or_invalid_event_rate_cannot_use_observed_source_usd(complete_reads, corruption):
    day, currency = (complete_reads.source.target[key] for key in ("transaction_date", "currency"))
    day = day[:10]
    content = f"date,currency,usd_rate\n{day},{currency},0.05\n"
    if corruption == "wrong_date": content = content.replace(day, "2026-01-01")
    elif corruption == "wrong_currency": content = content.replace(currency, "EUR")
    elif corruption == "duplicate": content += f"{day},{currency},0.05\n"
    elif corruption == "header": content = content.replace("date,currency,usd_rate", "currency,date,usd_rate")
    elif corruption == "bad_date": content = content.replace(day, "2026-02-30")
    elif corruption in {"zero", "negative", "nan", "infinity", "overflow"}:
        content = content.replace("0.05", {"zero":"0", "negative":"-1", "nan":"NaN", "infinity":"Infinity", "overflow":"1e1000000"}[corruption])
    elif corruption == "unrelated_bad_row": content += "2026-01-01,EUR,-1\n"
    elif corruption == "oversized": content += " "*(4*1024*1024)
    configure_rates(complete_reads, None if corruption == "absent" else content.encode())
    if corruption == "missing_file": complete_reads.service.config.event_rates_file.unlink()
    elif corruption == "hash":
        path = complete_reads.service.config.event_rates_file
        path.write_bytes(path.read_bytes()+b"\n")
    result = read(complete_reads.reads, "get_transaction", transaction_id=complete_reads.reference)
    assert result["status"] == "ok" and result["source_verified"] is True
    assert result["risk_data_complete"] is False
    assert result["risk_signals"]["amount_usd"] is None
    assert result["risk_signals"]["amount_usd_provenance"] == dict(source="unavailable", date=day, currency=currency)
    assert result["transaction"]["currency"] == currency


@pytest.mark.parametrize("rate_source", ["absent", "corrupt"])
def test_source_verified_usd_uses_native_amount_without_fx_lookup(complete_reads, rate_source):
    configure_rates(complete_reads, None if rate_source == "absent" else b"malformed unrelated FX file")
    reference = complete_reads.repository.reference("txn", complete_reads.principal.customer, "SYNTH-MX-USD-PROBE")
    result = read(complete_reads.reads, "get_transaction", transaction_id=reference)
    assert result["status"] == "ok" and result["source_verified"] is True
    assert result["risk_data_complete"] is True
    assert result["risk_signals"]["amount_usd"] == 143.50
    assert result["risk_signals"]["amount_usd_provenance"] == dict(source="exact_usd",
        date=(NOW-timedelta(days=10)).date().isoformat(), currency="USD")
    assert result["transaction"]["amount"] == "143.50" and result["transaction"]["currency"] == "USD"


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
    dict(product_hint="cartão"), dict(product_hint="cartão de crédito"),
    dict(product_hint="tarjeta de crédito"),
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


@pytest.mark.parametrize("hint", ["conta", "cartão de débito", "Fictional Absent Product"])
def test_product_hint_cannot_be_ignored_when_it_conflicts_with_owned_credit_card(complete_reads, hint):
    result = read(complete_reads.reads, "search_transactions", slots=dict(transaction_id=complete_reads.reference,
        date_from=complete_reads.source.target["transaction_date"][:10],
        date_to=complete_reads.source.target["transaction_date"][:10], product_hint=hint))
    assert result["status"] == "ok" and result["match_count"] == 0 and result["candidates"] == []


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


@pytest.mark.parametrize("missing_fx", [False, True])
@pytest.mark.parametrize("language,message,followup", [
    ("es", "No reconozco la compra de mi tarjeta de 2026-09-12.", "¿Cuál es el estado de esta solicitud?"),
    ("pt", "Não reconheço a compra do meu cartão de 2026-09-12.", "Qual é o estado desta solicitação?"),
])
def test_actual_frontend_workflow_source_and_portal_receipt_join(complete_reads, tmp_path, language, message, followup, missing_fx):
    from fastapi.testclient import TestClient
    from frontend.server.app import create_app
    from frontend.server.config import Settings
    from gloria_workflow.action_host import BankingActionHost
    from gloria_workflow.host import GloriaHostFactory
    from tests.test_gloria_acceptance import ScriptedModel
    raw_target, customer = "SYNTH-CO-TX-014", "SYNTH-CO-001"
    bank = complete_reads.service
    if missing_fx: configure_rates(complete_reads, None)
    # This owner has complete closed history and no invented exact-case link.
    snapshot = bank.repository.snapshot()
    from banking_mcp.security import Principal
    principal = Principal("other-release-subject", customer, "fixture-session", "fixture-conversation", int(time.time())+3600)
    _, raw = bank.repository.owned_transaction_id(principal, raw_target, snapshot.id)
    slots = {key: None for key in ("amount", "currency", "currency_raw", "date_from", "date_to",
        "date_expression", "merchant", "transaction_type", "channel", "city", "country", "transaction_id",
        "complaint_id", "product_hint", "product_last4")}
    slots.update(amount=float(raw["amount"]), currency=raw["currency"], date_from="2026-09-12", date_to="2026-09-12",
                 amount_is_approximate=False, foreign_customer_reference=False)
    model = ScriptedModel(message, language=language, raw_overrides={
        "extract_slots": json.dumps(slots),
        "resolve_clarification": json.dumps(dict(resolution_type="UNCLEAR", selected_ref=None))})
    factory = GloriaHostFactory(model, tmp_path / "joined-workflow.sqlite", bank_service=bank,
                                source_root=complete_reads.source.source)
    backend = BankingActionHost(bank, factory.store, source_root=complete_reads.source.source)
    key = Ed25519PrivateKey.generate()
    signer = tmp_path / "joined-signer.pem"
    signer.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()))
    config = dict(base_url="http://flujo:4200", model="flow-Gloria",
        execution_token="fictional-joined-execution", frontend_signing_key_file=str(signer),
        frontend_kid="release", frontend_issuer="release", frontend_audience="flujo-banking-ingress",
        principal_customers=dict(bank.config.principal_customers), action_enabled=True)
    settings = Settings(data_dir=complete_reads.source.data, state_dir=tmp_path / "joined-frontend",
        static_dir=tmp_path / "dist", demo_code="fictional-release-code", chat=config,
        profiles={"mexico": dict(customer_id="SYNTH-MX-001"), "colombia": dict(customer_id=customer),
                  "argentina": dict(customer_id="SYNTH-AR-001")})
    app = create_app(settings, gloria_factory=factory, bank_backend=backend)
    with TestClient(app) as client:
        app.state.chat_service._transport = httpx.MockTransport(lambda _: pytest.fail("joined path attempted network transport"))
        assert client.post("/api/auth/login", json=dict(profile="colombia", code=settings.demo_code)).status_code == 200
        reference = app.state.repository.reference("txn", customer, raw_target)
        inquiry = client.post("/api/chat", json=dict(message=message, transaction_reference=reference))
        assert inquiry.status_code == 200, inquiry.text
        assert inquiry.json()["mode"] == "gloria"
        with factory.store._connect() as db:
            saved = json.loads(db.execute("SELECT state_json FROM gloria_conversations").fetchone()[0])
        assert mode(saved) == ("HANDOFF" if missing_fx else "CONFIRM_ACTION")
        assert complete_reads.service.config.event_rates_sha256 is None or all(
            complete_reads.service.config.event_rates_sha256 not in user for _, _, user in model.calls)
        prepared = client.post("/api/action/prepare", json=dict(transaction_reference=reference, language=language))
        if missing_fx:
            assert saved["workflow_state"]["policy_decision"]["reason_code"] == "missing_evidence"
            assert prepared.status_code == 200, prepared.text
            assert prepared.json()["state"] == "handoff_verified"
            assert prepared.json()["reason"] == "missing_evidence"
            assert prepared.json()["handoff"]["human_responded"] is False
            assert "receipt" not in prepared.json()
            with bank.store.connect() as db:
                assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0
                assert db.execute("SELECT count(*) FROM action_pending WHERE decision='intake' AND confirmation_state='prepared'").fetchone()[0] == 0
            return
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()["state"] == "pending_confirmation", prepared.json()
        pending = prepared.json()["pending_handle"]
        rejected = client.post("/api/action/confirm", json=dict(transaction_reference=reference,
            pending_handle=pending, confirmed=False, language=language))
        assert rejected.status_code == 422
        confirmed = client.post("/api/action/confirm", json=dict(transaction_reference=reference,
            pending_handle=pending, confirmed=True, language=language))
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["state"] == "intake_verified", confirmed.json()
        receipt = confirmed.json()["receipt"]
        assert receipt["simulated"] is True and receipt["snapshot"] == snapshot.id
        assert receipt["transaction"]["amount"] == f'{raw["amount"]:.2f}'
        model.message = followup
        report = client.post("/api/chat", json=dict(message=followup))
        assert report.status_code == 200, report.text
        assert receipt["id"] in report.json()["reply"]
        assert ("reclamo" if language == "es" else "reclamação") in report.json()["reply"].casefold()
        with bank.store.connect() as db:
            assert db.execute("SELECT count(*) FROM sandbox_cases WHERE customer=?", (customer,)).fetchone()[0] == 1
        replay = client.post("/api/action/confirm", json=dict(transaction_reference=reference,
            pending_handle=pending, confirmed=True, language=language))
        assert replay.status_code == 200 and replay.json()["receipt"] == receipt
        with bank.store.connect() as db:
            assert db.execute("SELECT count(*) FROM sandbox_cases WHERE customer=?", (customer,)).fetchone()[0] == 1
