"""Evidence boundaries: saved readback facts must not become fresh authority."""
from copy import deepcopy
import json

import pytest

from frontend.server.action import (handoff_questions, matches_selected_transaction, project_action_result,
                                    public_facts, render_action)
from frontend.server.chat import ChatService
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected


def existing_case():
    return {"state": "existing_case_verified", "pending_handle": "a" * 43,
            "snapshot": "serving-new", "transaction": action_facts(),
            "target_reference": "txn_" + "b" * 24,
            "receipt": action_receipt(snapshot="original-old")}


def test_existing_case_keeps_original_receipt_and_current_lookup_distinct():
    raw = {**existing_case(), "customer_id": "private-owner", "risk": {"fraud_score": 99}}
    for language in ("es", "pt"):
        result = render_action(raw, language)
        assert result["state"] == "existing_case_verified"
        assert result["receipt"]["status"] == "received"
        assert result["snapshot"] == "serving-new"
        assert result["receipt"]["snapshot"] == "original-old"
        assert "private-owner" not in str(result) and "fraud_score" not in str(result)
        assert "reembolso" in result["message"]
        assert ChatService._verified_terminal(result)
    assert project_action_result(project_action_result(raw)) == project_action_result(raw)


@pytest.mark.parametrize("field,value", [
    ("simulated", False), ("kind", "bank_dispute"), ("status", "resolved"),
    ("created_at", "2026-09-29T15:00:00"), ("snapshot", "../secret")])
def test_valid_case_id_does_not_make_malformed_receipt_verified(field, value):
    raw = existing_case()
    raw["receipt"][field] = value
    result = render_action(raw, "pt")
    assert result["state"] == "prepare_unverified"
    assert "receipt" not in result and "CMP-SBX-abcdefgh" not in result["message"]
    assert not ChatService._verified_terminal(result)


def test_existing_case_requires_exact_current_read_facts_not_only_a_case_id():
    raw = existing_case()
    raw["receipt"]["transaction"]["amount"] = "999.00"
    assert project_action_result(raw)["state"] == "prepare_unverified"
    raw = existing_case()
    del raw["transaction"]
    assert project_action_result(raw)["state"] == "prepare_unverified"


def test_handoff_saved_questions_provenance_and_nested_recovery_roundtrip():
    handoff = action_handoff(snapshot="saved-old", questions=["¿Qué necesitas revisar?", "Qual ajuda precisa?"])
    handoff["transaction_currentness"] = "different_snapshot"
    raw = {"state": "handoff_verified", "handoff": handoff}
    result = project_action_result(raw)
    assert result["handoff"]["unanswered_questions"] == handoff["packet"]["unanswered_questions"]
    assert result["handoff"]["transaction_provenance"]["snapshot"] == "saved-old"
    assert result["handoff"]["transaction_currentness"] == "different_snapshot"
    assert result["handoff"]["human_responded"] is False
    assert "packet" not in result["handoff"]
    assert project_action_result(result) == result
    nested = render_action({"state": "action_unverified", "handoff": raw}, "pt")
    assert nested["state"] == "action_unverified"
    assert nested["handoff"]["handoff"] == result["handoff"]
    assert "HOF-abcdefgh" in nested["message"]
    assert "Ainda não houve resposta" in nested["message"]


@pytest.mark.parametrize("change", [
    "facts", "reason", "questions_alias", "provenance_alias", "provenance_snapshot",
    "provenance_timezone", "human", "questions_missing", "questions_control", "questions_padded", "legacy_packet"])
def test_handoff_conflicting_or_absent_packet_evidence_remains_unverified(change):
    packet = action_handoff(questions=["¿Qué ayuda necesitas?"])
    if change == "facts": packet["facts"]["amount"] = "999.00"
    elif change == "reason": packet["packet"]["reason"] = "high_risk"
    elif change == "questions_alias": packet["unanswered_questions"] = ["Different question"]
    elif change == "provenance_alias": packet["transaction_provenance"] = None
    elif change == "provenance_snapshot": packet["packet"]["transaction_provenance"]["snapshot"] = "other"
    elif change == "provenance_timezone": packet["packet"]["transaction_provenance"]["as_of"] = "2026-09-29T15:00:00-05:00"
    elif change == "human": packet["packet"]["human_responded"] = True
    elif change == "questions_missing": del packet["packet"]["unanswered_questions"]
    elif change == "questions_control": packet["packet"]["unanswered_questions"] = ["One\nTwo"]
    elif change == "questions_padded": packet["packet"]["unanswered_questions"] = [" Question "]
    elif change == "legacy_packet": del packet["packet"]
    result = render_action({"state": "handoff_verified", "handoff": packet}, "es")
    assert result["state"] == "handoff_unverified"
    assert "handoff" not in result and "HOF-abcdefgh" not in result["message"]


def test_unverified_state_cannot_publish_handoff_facts_or_ids():
    result = render_action({"state": "handoff_unverified", "handoff": action_handoff()}, "pt")
    assert "handoff" not in result and "HOF-abcdefgh" not in str(result)


@pytest.mark.parametrize("value", [{}, [], None, 123])
def test_malformed_discriminants_cannot_raise_or_publish_verified_evidence(value):
    result = render_action({"state": value, "reason": value, "receipt": action_receipt()}, "pt")
    assert result["state"] == "action_unverified" and "receipt" not in result
    assert not ChatService._verified_terminal({"state": value, "receipt": action_receipt()})
    packet = action_handoff()
    packet["reason"] = value
    result = render_action({"state": "handoff_verified", "handoff": packet}, "es")
    assert result["state"] == "handoff_unverified" and "handoff" not in result


def test_question_contract_accepts_normal_es_pt_and_rejects_control_or_surrogate_text():
    from frontend.server.app import HandoffActionBody
    from pydantic import ValidationError
    questions = ["Quiero hablar con alguien", "Como posso acompanhar a revisão?"]
    assert handoff_questions(questions) == questions
    assert HandoffActionBody(reason="customer_request", unanswered_questions=questions).unanswered_questions == questions
    padded = ["  Quiero hablar con alguien  ", " Como posso acompanhar a revisão? "]
    assert handoff_questions(padded) is None
    assert HandoffActionBody(reason="customer_request", unanswered_questions=padded).unanswered_questions == questions
    for questions in (["Bad\x00text"], ["Bad\x1btext"], ["One\nTwo"], ["One\rTwo"], ["Bad\ud800text"],
                      [" "], ["Question"] * 9, ["x" * 241]):
        assert handoff_questions(questions) is None
        with pytest.raises(ValidationError):
            HandoffActionBody(reason="customer_request", unanswered_questions=questions)


def test_general_handoff_has_no_transaction_and_explicit_empty_saved_questions():
    raw = {"state": "handoff_verified", "handoff": action_handoff(snapshot=None)}
    result = project_action_result(raw)
    assert result["handoff"]["facts"] == {}
    assert result["handoff"]["transaction_provenance"] is None
    assert result["handoff"]["transaction_currentness"] == "not_applicable"
    assert result["handoff"]["unanswered_questions"] == []


def test_saved_general_row_cannot_verify_an_unbound_transaction_packet():
    result = {"state": "handoff_verified", "handoff": action_handoff(),
              "request_id": "123e4567-e89b-42d3-a456-426614174000",
              "reason": "customer_request", "unanswered_questions": ["Qual o próximo passo?"]}
    result["handoff"]["packet"]["unanswered_questions"] = result["unanswered_questions"]
    projected = ChatService._action_result({"result_json": json.dumps(result), "target_reference": None})
    assert projected == {"state": "handoff_unverified", "request_id": result["request_id"],
                         "reason": result["reason"], "unanswered_questions": result["unanswered_questions"]}


def test_prior_receipt_is_exact_readonly_evidence_bound_to_authoritative_row_target():
    reference, other = "txn_" + "a" * 24, "txn_" + "b" * 24
    result = {"state": "prepare_unverified", "target_reference": reference,
              "prior_receipt": {"target_reference": reference, "receipt": action_receipt(snapshot="original-old")}}
    projected = project_action_result(result)
    assert projected == result and project_action_result(projected) == projected
    assert not ChatService._verified_terminal(projected)
    for language, expected in (("es", "recepción simulada anterior sigue verificada"),
                               ("pt", "solicitação simulada anterior continua verificada")):
        rendered = render_action(projected, language)
        assert expected in rendered["message"]
        assert "preparación del seguimiento" in rendered["message"] if language == "es" else "preparação do acompanhamento" in rendered["message"]
    assert "prior_receipt" not in project_action_result({**result, "target_reference": other})
    assert "prior_receipt" not in ChatService._action_result({
        "result_json": json.dumps(result), "target_reference": other})
    invalid = deepcopy(result)
    invalid["prior_receipt"]["receipt"]["status"] = "resolved"
    assert "prior_receipt" not in project_action_result(invalid)
    # Earlier proof cannot stand in for a new terminal receipt.
    assert not ChatService._verified_terminal({**result, "state": "intake_verified"})


def test_prior_general_handoff_is_strict_readonly_evidence_and_never_terminal_authority():
    raw = {"state": "handoff_unverified", "prior_handoff": {
        "target_reference": None, "handoff": action_handoff(snapshot=None, questions=["Qual ajuda precisa?"])}}
    result = project_action_result(raw)
    assert result["prior_handoff"]["handoff"]["unanswered_questions"] == ["Qual ajuda precisa?"]
    assert project_action_result(result) == result
    assert not ChatService._verified_terminal(result)
    assert not ChatService._verified_terminal({**result, "state": "handoff_verified"})
    assert "prior_handoff" not in project_action_result({**raw, "target_reference": "txn_" + "a" * 24})
    invalid = deepcopy(raw)
    invalid["prior_handoff"]["handoff"] = action_handoff()
    assert "prior_handoff" not in project_action_result(invalid)
    assert "prior_handoff" not in ChatService._action_result({
        "result_json": json.dumps(raw), "target_reference": "txn_" + "b" * 24})


def test_pending_requires_complete_saved_charge_and_snapshot():
    raw = {"state": "pending_confirmation", "pending_handle": "a" * 43,
           "snapshot": "selected-build", "transaction": action_facts()}
    assert ChatService._safe_prepare_result(raw, "selected-build")["state"] == "pending_confirmation"
    assert ChatService._safe_prepare_result(raw, "different-build")["state"] == "prepare_unverified"
    for field in ("snapshot", "transaction", "pending_handle"):
        invalid = deepcopy(raw)
        del invalid[field]
        assert ChatService._safe_prepare_result(invalid)["state"] == "prepare_unverified"


def test_display_comparison_ignores_unrelated_refs_but_rejects_changed_charge_fields():
    selected = action_selected(reference="txn_" + "b" * 24)
    facts = action_facts()
    assert matches_selected_transaction(facts, selected)
    for field, value in {"amount": 151, "currency": "USD", "status": "Reversed",
                         "merchant": "Another merchant", "type": "Purchase",
                         "occurred_at": "2026-06-18T12:00:00", "process_date": "2026-06-18",
                         "channel": "Branch", "product": "Tarjeta Crédito"}.items():
        assert not matches_selected_transaction(facts, {**selected, field: value})
    for field in ("transaction_type", "channel", "product"):
        assert public_facts({**facts, field: ""}) is not None
    for amount in ("1E2", "NaN", "Infinity", " 150.00", "1.000"):
        assert public_facts({**facts, "amount": amount}) is None


def test_display_comparison_uses_mcp_bounds_for_owned_display_fields():
    selected = action_selected(merchant="Merchant " + "x" * 200, type="T" * 100,
                               channel="C" * 100, product="P" * 100)
    facts = action_facts({**selected, "merchant": selected["merchant"][:160], "type": selected["type"][:80],
                         "channel": selected["channel"][:80], "product": selected["product"][:80]})
    assert matches_selected_transaction(facts, selected)
    assert not matches_selected_transaction(facts, {**selected, "merchant": "Other " + selected["merchant"]})
    assert not matches_selected_transaction(facts, {**selected, "amount": 999})
    for merchant in (None, ""):
        empty = {**selected, "merchant": merchant, "type": None, "channel": None, "product": None}
        facts = action_facts({**empty, "merchant": None, "type": "", "channel": "", "product": ""})
        assert matches_selected_transaction(facts, empty)
    assert not matches_selected_transaction(facts, {**empty, "merchant": 123})
