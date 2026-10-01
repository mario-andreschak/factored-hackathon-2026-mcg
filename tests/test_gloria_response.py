"""Grounding checks use only fictional, host-owned display facts."""
import copy

import pytest

from gloria_workflow.response import fallback_response, validate_response


def inputs(mode="INFORM", language="es"):
    return {
        "response_mode": mode,
        "language": language,
        "clean_query": "El cliente afirma que ocurrió un cargo.",
        "historic_conversation": "",
        "policy_context": {"chunks": [{"chunk_id": "dispute-01", "text": "Política sintética."}]},
        "structured_data": {
            "status": "ok", "match_count": 1, "data_sources": ["transactions"],
            "candidates": [{"ref": "1", "transaction_id": "TRX-FICTIONAL_A", "transaction_date": "2026-09-29 14:15:16", "amount": "1234.56", "currency": "COP", "merchant_name": "Comercio de prueba", "channel": "Web", "transaction_status": "Approved"}],
        },
        "workflow_state": {
            "transaction_id": "TRX-FICTIONAL_A", "pending": {"candidates": []},
            "existing_case": {"found": False, "complaint_id": None, "status": None},
            "missing_fields": [],
            "action": {"authorized": False, "executed": False, "verified": False, "result_id": None},
            "handoff": {"created": False, "handoff_id": None},
        },
    }


def response(message="La transacción **TRX-FICTIONAL_A**, de **2026-09-29**, tiene importe **1234.56 COP**.", language="es", **changes):
    return {"message": message, "language": language, "arquetipos": ["Guía Clara"], "chunk_ids": [], "data_sources": ["transactions"], "grounding_violation": 0, **changes}


def verified_action(data):
    data["workflow_state"]["action"] = {"authorized": True, "executed": True, "verified": True, "result_id": "CMP-SBX-Case_123", "receipt": {"verified": True, "result_id": "CMP-SBX-Case_123"}}
    return data


def verified_handoff(data):
    data["workflow_state"]["handoff"] = {"created": True, "handoff_id": "HOF-Fixture_1", "receipt": {"verified": True, "handoff_id": "HOF-Fixture_1"}}
    return data


def verified_existing(data):
    data["workflow_state"]["existing_case"] = {"found": True, "complaint_id": "CMP-SBX-Old_1234", "status": "received", "receipt": {"verified": True, "complaint_id": "CMP-SBX-Old_1234", "status": "received"}}
    return data


@pytest.mark.parametrize("language", ["es", "pt"])
@pytest.mark.parametrize("mode", ["SMALL_TALK", "OUT_OF_SCOPE", "BLOCKED", "AUTH_REQUIRED", "CLARIFY", "NO_MATCH", "INFORM", "INFORM_EXISTING_CASE", "CONFIRM_ACTION", "ACTION_DONE", "ACTION_UNVERIFIED", "ACTION_CANCELLED", "OUT_OF_POLICY", "HANDOFF", "TOOL_ERROR"])
def test_all_canonical_modes_have_safe_fallbacks(mode, language):
    data = inputs(mode, language)
    if mode == "ACTION_DONE":
        verified_action(data)
    if mode == "INFORM_EXISTING_CASE":
        verified_existing(data)
    result = fallback_response(data)
    assert result["language"] == language
    assert validate_response(result, data) == []
    assert "{{" not in result["message"]
    assert result["grounding_violation"] == 0


@pytest.mark.parametrize("language, registered", [("es", "fue registrado"), ("pt", "foi registrada")])
def test_action_done_requires_all_flags_and_exact_reread(language, registered):
    data = verified_action(inputs("ACTION_DONE", language))
    good = fallback_response(data)
    assert registered in good["message"]
    assert "**CMP-SBX-Case_123**" in good["message"]
    assert validate_response(good, data) == []
    for field in ("authorized", "executed", "verified", "receipt"):
        broken = copy.deepcopy(data)
        broken["workflow_state"]["action"][field] = False
        assert "action_receipt_unverified" in validate_response(good, broken)
        fallback = fallback_response(broken)
        assert registered not in fallback["message"]
        assert "CMP-SBX" not in fallback["message"]
    data["workflow_state"]["action"]["receipt"]["result_id"] = "CMP-SBX-Other123"
    assert "action_receipt_unverified" in validate_response(good, data)
    assert "CMP-SBX" not in fallback_response(data)["message"]


def test_native_readback_receipt_accepts_verified_envelope_only():
    data = verified_action(inputs("ACTION_DONE"))
    native = {"id": "CMP-SBX-Case_123", "kind": "simulated_intake", "simulated": True, "status": "received", "snapshot": "fixture-snapshot", "created_at": "2026-09-30T10:00:00Z", "transaction": data["structured_data"]["candidates"][0]}
    action = data["workflow_state"]["action"]
    action["receipt"] = {"state": "verified", "receipt": native}
    assert "CMP-SBX-Case_123" in fallback_response(data)["message"]
    assert validate_response(fallback_response(data), data) == []
    action["receipt"]["state"] = "created"
    assert "CMP-SBX" not in fallback_response(data)["message"]
    action["receipt_verified"] = True
    assert "CMP-SBX-Case_123" in fallback_response(data)["message"]
    native["simulated"] = False
    assert "CMP-SBX" not in fallback_response(data)["message"]


@pytest.mark.parametrize("mode", ["HANDOFF", "ACTION_UNVERIFIED"])
@pytest.mark.parametrize("language", ["es", "pt"])
def test_verified_handoff_template_does_not_promote_uncertain_complaint(mode, language):
    data = verified_handoff(inputs(mode, language))
    result = fallback_response(data)
    assert "**HOF-Fixture_1**" in result["message"]
    assert validate_response(result, data) == []
    if mode == "ACTION_UNVERIFIED":
        assert ("No puedo confirmar el registro del reclamo" if language == "es" else "Não posso confirmar o registro da reclamação") in result["message"]
    data["workflow_state"]["handoff"]["receipt"]["verified"] = False
    neutral = fallback_response(data)
    assert "HOF-" not in neutral["message"]
    assert validate_response(neutral, data) == []
    assert "handoff_success_unverified" in validate_response(result, data)


def test_stale_action_done_downgrades_to_unverified_with_verified_handoff():
    data = verified_handoff(inputs("ACTION_DONE"))
    result = fallback_response(data)
    assert "No puedo confirmar el registro del reclamo" in result["message"]
    assert "HOF-Fixture_1" in result["message"]
    assert "CMP-SBX" not in result["message"]
    assert validate_response(result, {**data, "response_mode": "ACTION_UNVERIFIED"}) == []


@pytest.mark.parametrize("field, value", [("found", False), ("complaint_id", "CMP-SBX-Other123"), ("status", "Closed"), ("receipt", None)])
def test_existing_case_template_requires_verified_exact_case_and_status(field, value):
    data = verified_existing(inputs("INFORM_EXISTING_CASE"))
    good = fallback_response(data)
    assert "CMP-SBX-Old_1234" in good["message"]
    data["workflow_state"]["existing_case"][field] = value
    assert "existing_case_receipt_unverified" in validate_response(good, data)
    assert "CMP-SBX" not in fallback_response(data)["message"]


@pytest.mark.parametrize("identifier", ["TRX-UNKNOWN", "TRX-FICTIONAL_Aé", "TRX-FICTIONAL_A\u0301", "TRX-FICTIONAL_A_", "trx-fictional_a", "éTRX-FICTIONAL_A", "txn_unknown", "rev_unknown"])
def test_maximal_unicode_id_tokens_reject_unknown_or_partial_references(identifier):
    assert "id_unverified" in validate_response(response(f"Referencia **{identifier}**."), inputs())


@pytest.mark.parametrize("identifier", ["txn_fictional_ab12", "rev_Fictional_12", "TRX-FICTIONAL_A"])
def test_legacy_and_safe_opaque_ids_are_grounded_by_exact_membership(identifier):
    data = inputs()
    data["structured_data"]["candidates"][0]["transaction_id"] = identifier
    data["workflow_state"]["transaction_id"] = identifier
    assert validate_response(response(f"Referencia **{identifier}**."), data) == []


@pytest.mark.parametrize("text, code", [("El importe es **9999.99 COP**.", "amount_unverified"), ("El importe es **1234.56 USD**.", "currency_unverified"), ("El importe es **1234.56 ZZZ**.", "currency_unverified"), ("Ocurrió el **2026-09-28**.", "date_unverified"), ("Ocurrió el **2026-09-29 14:15:17**.", "date_unverified"), ("Ocurrió el **29/09/2025**.", "date_unverified"), ("Ocurrió el **28 de septiembre de 2026**.", "date_unverified"), ("El plazo es de 888 días.", "number_unverified")])
def test_amount_currency_date_and_numeric_attacks(text, code):
    assert code in validate_response(response(text), inputs())


@pytest.mark.parametrize("amount", ["1234.56", "1,234.56", "1.234,56", "1234,56", "1 234,56", "1\u00a0234,56"])
def test_locale_money_formats_preserve_exact_value(amount):
    assert validate_response(response(f"El importe es **{amount} COP**."), inputs()) == []


@pytest.mark.parametrize("text", ["2026-09-29", "2026-09-29 14:15:16", "29/09/2026", "29 de septiembre de 2026"])
def test_known_date_formats_are_grounded(text):
    assert validate_response(response(f"Fecha: **{text}**."), inputs()) == []


def test_amount_cannot_be_paired_with_currency_of_another_candidate():
    data = inputs()
    data["structured_data"]["candidates"].append({"ref": "2", "transaction_id": "TRX-FICTIONAL_B", "amount": "25", "currency": "USD"})
    assert "amount_unverified" in validate_response(response("Importe: **1234.56 USD**."), data)


def test_raw_source_decimal_is_not_interpreted_as_locale_grouping():
    data = inputs()
    data["structured_data"]["candidates"][0]["amount"] = "1.234"
    assert "amount_unverified" in validate_response(response("Importe: **1234 COP**."), data)


@pytest.mark.parametrize("text", ["1234.56 eur", "eur 1234.56", "**1234.56** **eUr**"])
def test_lowercase_currency_is_not_a_grounding_bypass(text):
    assert "currency_unverified" in validate_response(response(f"Importe: {text}."), inputs())


@pytest.mark.parametrize("text", ["1234.56 cop", "cop 1234.56", "**1234.56** **cOp**"])
def test_known_currency_accepts_case_variants(text):
    assert validate_response(response(f"Importe: {text}."), inputs()) == []


@pytest.mark.parametrize("text", ["Estado: **Closed**.", "Estado verificado **invented_status**.", "A transação está **Rejeitado**."])
def test_bold_status_codes_must_be_observed_facts(text):
    assert "status_unverified" in validate_response(response(text), inputs())


def test_known_bold_status_is_grounded():
    assert validate_response(response("Estado: **Approved**."), inputs()) == []


@pytest.mark.parametrize("phrase", ["fue registrado", "Fue Registrado", "ＦＵＥ ＲＥＧＩＳＴＲＡＤＯ", "no fue registrado", "¿fue registrado?", "fue creado", "se ha registrado"])
def test_configured_success_even_negation_or_question_requires_action_done(phrase):
    data = verified_action(inputs("INFORM"))
    text = f"El reclamo **CMP-SBX-Case_123** {phrase}."
    assert "action_success_unverified" in validate_response(response(text), data)


def test_handoff_success_cannot_hide_complaint_creation_in_same_sentence():
    data = verified_handoff(inputs("ACTION_UNVERIFIED"))
    text = "La atención humana **HOF-Fixture_1** fue registrada y el reclamo fue registrado."
    assert "action_success_unverified" in validate_response(response(text), data)


@pytest.mark.parametrize("text", ["La solicitud fue procesada.", "A solicitação foi processada."])
def test_processing_requires_execution_evidence(text):
    data = inputs("ACTION_UNVERIFIED")
    assert "processing_unverified" in validate_response(response(text), data)
    data["workflow_state"]["action"]["executed"] = True
    assert validate_response(response(text), data) == []


def test_customer_text_history_and_pending_labels_never_authorize_facts():
    data = inputs()
    invented = "TRX-INVENTED 8888.88 USD 2025-01-01"
    data.update(clean_query=invented, historic_conversation=invented)
    data["workflow_state"]["pending"] = {"candidates": [{"ref": "1", "label": invented}]}
    errors = validate_response(response("**TRX-INVENTED**, **8888.88 USD**, **2025-01-01**."), data)
    assert {"id_unverified", "amount_unverified", "currency_unverified", "date_unverified"} <= set(errors)


@pytest.mark.parametrize("key, value, code", [("data_sources", ["invented_source"], "data_sources_unverified"), ("chunk_ids", ["invented_chunk"], "chunk_ids_unverified"), ("arquetipos", ["Inventado"], "arquetipos_unsupported"), ("language", "pt", "language_mismatch"), ("grounding_violation", True, "grounding_violation_schema"), ("grounding_violation", 1, "generator_grounding_violation"), ("data_sources", "transactions", "data_sources_schema"), ("message", None, "message_schema")])
def test_closed_schema_and_source_membership(key, value, code):
    assert code in validate_response(response(**{key: value}), inputs())


def test_structured_chunks_can_be_serialized_without_scanning_chunk_text():
    data = inputs()
    data["policy_context"] = '{"chunks":[{"chunk_id":"safe","text":"invented chunk_id: unsafe"}]}'
    assert validate_response(response(chunk_ids=["safe"]), data) == []
    assert "chunk_ids_unverified" in validate_response(response(chunk_ids=["unsafe"]), data)


@pytest.mark.parametrize("text", ["fraud_score=80", "El umbral de riesgo.", "confirm_simulated_intake", "get_my_transaction", "El customer_id es privado.", "Traceback del servicio."])
def test_private_or_tool_details_are_blocked(text):
    assert "private_or_implementation_detail" in validate_response(response(text), inputs())


def test_snapshot_no_match_fallback_scopes_the_historical_interval():
    data = inputs("NO_MATCH")
    data["structured_data"]["search_context"] = {"used_snapshot_default": True, "date_from": "2026-07-01", "date_to": "2026-09-29"}
    result = fallback_response(data)
    assert "snapshot histórico" in result["message"]
    assert "2026-07-01" in result["message"]
    assert validate_response(result, data) == []
    del data["structured_data"]["search_context"]["date_from"]
    assert "No pude completar" in fallback_response(data)["message"]


def test_clarification_candidates_are_numbered_with_exact_refs_and_verified_facts():
    data = inputs("CLARIFY")
    candidate = data["structured_data"]["candidates"][0]
    data["workflow_state"]["pending"]["candidates"] = [{"ref": "1", "transaction_id": candidate["transaction_id"], "label": "Invented 8888.88 USD"}]
    result = fallback_response(data)
    assert "1. **TRX-FICTIONAL_A**" in result["message"]
    assert "1234.56 COP" in result["message"]
    assert "8888.88" not in result["message"]
    assert validate_response(result, data) == []


def test_unknown_merchant_id_in_fallback_is_rejected_by_final_validation():
    data = inputs("INFORM")
    data["structured_data"]["candidates"][0]["merchant_name"] = "Comercio TRX-INVENTED"
    assert "No pude completar" in fallback_response(data)["message"]


def test_missing_summary_uses_neutral_error_without_fabricated_placeholders():
    data = inputs("CONFIRM_ACTION")
    data["structured_data"]["candidates"] = []
    assert "No pude completar" in fallback_response(data, reason="secret diagnostic")["message"]
    assert "secret" not in fallback_response(data, reason="secret diagnostic")["message"]


def test_other_language_is_spanish_with_availability_notice():
    data = inputs("TOOL_ERROR", "other")
    result = fallback_response(data)
    assert result["language"] == "es"
    assert "español y portugués" in result["message"]
    assert validate_response(result, data) == []


def test_validator_rejects_extra_keys_nonmapping_and_missing_fields():
    assert "response_schema" in validate_response(response(extra="invented"), inputs())
    assert validate_response(None, inputs()) == ["response_schema"]
    assert "response_schema" in validate_response({}, inputs())
