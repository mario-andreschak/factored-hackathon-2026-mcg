"""Grounding checks use only fictional, host-owned display facts."""
import copy

import pytest

from gloria_workflow.response import combine_responses, fallback_response, validate_handoff_summary, validate_response
from gloria_workflow.retrieval import retrieve_policy


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


@pytest.mark.parametrize("text, code", [
    ("Tu identificador es CLI-ALICE.", "private_contact_or_identifier"),
    ("Identificador éCLI-ALICE.", "private_contact_or_identifier"),
    ("Identificador CLI-AL\u200bICE.", "private_contact_or_identifier"),
    ("Identificador CUST-ALICE.", "private_contact_or_identifier"),
    ("Identificador CUS-ALICE.", "private_contact_or_identifier"),
    ("Identificador CUSTOMER-ALICE.", "private_contact_or_identifier"),
    ("Email alice@example.test", "private_contact_or_identifier"),
    ("E-mail alice@exam\u200bple.test", "private_contact_or_identifier"),
    (r"Fuente C:\Users\Test\private\data.json", "private_or_implementation_detail"),
    ("s3://internal-bucket/private", "private_or_implementation_detail"),
    (r"Fuente \\internal-server\private\data.json", "private_or_implementation_detail"),
    ("Fonte file:///home/internal/data.json", "private_or_implementation_detail"),
    ("Fuente /private/banking/data.json", "private_or_implementation_detail"),
    ("Token secreto: fictional-value", "credential_disclosure"),
    ("Tu contraseña es fictional-value.", "credential_disclosure"),
    ("Sua senha é fictional-value.", "credential_disclosure"),
    ("PIN: 1234.56", "credential_disclosure"),
    ("Bearer fictional-token", "credential_disclosure"),
    ("Teléfono: +57 300 123 4567", "private_contact_or_document"),
    ("Telefone: 300 123 4567", "private_contact_or_document"),
    ("CPF: 123.456.789-00", "private_contact_or_document"),
    ("Número de cuenta: 1234567890", "private_contact_or_document"),
])
def test_generator_rejects_private_values_and_source_paths_even_in_display_fields(text, code):
    data = inputs()
    data["clean_query"] = data["historic_conversation"] = text
    data["structured_data"]["candidates"][0]["merchant_name"] = text
    data["structured_data"]["candidates"][0]["transaction_city"] = text
    assert code in validate_response(response(text), data)
    assert "No pude completar" in fallback_response(data)["message"]


@pytest.mark.parametrize("key", ["data_sources", "chunk_ids"])
def test_grounded_metadata_cannot_expose_private_source_paths(key):
    value = "s3://internal-bucket/private"
    data = inputs()
    if key == "data_sources":
        data["structured_data"][key] = [value]
    else:
        data["policy_context"] = {"chunks": [{"chunk_id": value, "text": "Política sintética."}]}
    assert "private_or_implementation_detail" in validate_response(response("Consulta disponible.", **{key: [value]}), data)


@pytest.mark.parametrize("label", ["Teléfono", "Telefone", "CPF", "Número de cuenta"])
def test_private_numeric_label_cannot_borrow_amount_authority(label):
    data = inputs()
    data["structured_data"]["candidates"][0]["amount"] = "1234567890"
    assert "private_contact_or_document" in validate_response(response(f"{label}: 1234567890 COP"), data)
    assert validate_response(response("Importe **+1234567890 COP**."), data) == []


@pytest.mark.parametrize("text", [
    "Comercio PIN Store, Bogotá. Importe **1234.56 COP**.",
    "Comercio Central, São Paulo. Fecha **2026-09-29**.",
    "No compartas contraseñas.",
    "Não compartilhe sua senha.",
])
def test_neutral_display_and_secret_sharing_limitations_are_preserved(text):
    assert validate_response(response(text), inputs()) == []


@pytest.mark.parametrize("text", ["Tarjeta de crédito terminada en **8469**.", "Cartão com final **8469**.", "Últimos cuatro dígitos: **8469**."])
def test_only_labeled_known_product_last_four_digits_are_display_facts(text):
    data = inputs()
    data["structured_data"]["candidates"][0]["product_last4"] = "8469"
    assert validate_response(response(text), data) == []
    assert "number_unverified" in validate_response(response(text.replace("8469", "8470")), data)
    assert "number_unverified" in validate_response(response("El plazo es 8469 días."), data)
    assert "credential_disclosure" in validate_response(response("PIN: 8469"), data)


def test_verified_public_receipt_id_is_not_a_private_cli_suffix():
    data = verified_handoff(inputs("HANDOFF"))
    data["workflow_state"]["handoff"].update(handoff_id="HOF-CLI-ALICE", receipt={"verified": True, "handoff_id": "HOF-CLI-ALICE"})
    result = fallback_response(data)
    assert "**HOF-CLI-ALICE**" in result["message"]
    assert validate_response(result, data) == []


@pytest.mark.parametrize("mode, projection, field, identifier", [
    ("HANDOFF", "handoff", "handoff_id", "HOF-atendeu"),
    ("ACTION_DONE", "action", "result_id", "CMP-encaminhei"),
])
def test_receipt_suffix_cannot_be_read_as_an_action_or_human_service_claim(mode, projection, field, identifier):
    data = verified_handoff(inputs(mode)) if projection == "handoff" else verified_action(inputs(mode))
    data["workflow_state"][projection].update({field: identifier, "receipt": {"verified": True, field: identifier}})
    result = fallback_response(data)
    assert f"**{identifier}**" in result["message"]
    assert validate_response(result, data) == []


@pytest.mark.parametrize("language, text", [
    ("es", "Tu caso ya está en manos de un asesor."),
    ("es", "Ya estás con un asesor."),
    ("es", "Un asesor te atenderá pronto."),
    ("es", "Tu caso está siendo atendido por un asesor."),
    ("es", "Ya asignamos tu solicitud a un asesor."),
    ("es", "Ya estás conectado con atención humana."),
    ("es", "Te contactarán cuando terminen la revisión."),
    ("pt", "Seu caso já está nas mãos de um atendente."),
    ("pt", "Um atendente já recebeu seu caso."),
    ("pt", "Um atendente vai responder em breve."),
    ("pt", "Seu caso está sendo analisado por um atendente."),
    ("pt", "Entrarão em contato após a análise."),
])
@pytest.mark.parametrize("receipt", [False, True])
def test_local_handoff_receipt_never_proves_human_service(language, text, receipt):
    data = inputs("HANDOFF", language)
    if receipt:
        verified_handoff(data)
        text += " Referencia **HOF-Fixture_1**."
    assert "human_service_unverified" in validate_response(response(text, language), data)
    # Narrative permits omission of a verified result ID; it must not suppress
    # unsupported pickup/assignment/response claims along with that omission.
    candidate = narrative(request_summary="Cliente de habla española solicita revisión. " + text, customer_language=language)
    if language == "pt":
        candidate["request_summary"] = candidate["request_summary"].replace("española", "portuguesa")
    assert "human_service_unverified" in validate_handoff_summary(candidate, data)


@pytest.mark.parametrize("language, text", [
    ("es", "La derivación ya está confirmada."),
    ("es", "Tu solicitud se ha derivado a atención humana."),
    ("pt", "O encaminhamento já está confirmado."),
    ("pt", "A solicitação foi encaminhada para atendimento humano."),
    ("es", "La derivación quedó creada."),
    ("pt", "O encaminhamento foi registrado."),
])
def test_created_handoff_claim_requires_matching_reread_and_visible_id(language, text):
    data = inputs("HANDOFF", language)
    assert "handoff_success_unverified" in validate_response(response(text, language), data)
    verified_handoff(data)
    assert "handoff_success_unverified" in validate_response(response(text, language), data)
    assert validate_response(response(text.rstrip(".") + " **HOF-Fixture_1**.", language), data) == []


@pytest.mark.parametrize("language, text", [
    ("es", "El reclamo fue registrado y fue derivado con **HOF-Fixture_1**."),
    ("es", "El reclamo fue registrado, y derivé a atención humana con **HOF-Fixture_1**."),
    ("pt", "A reclamação foi registrada e foi encaminhada com **HOF-Fixture_1**."),
    ("pt", "A reclamação foi registrada, e encaminhei para atendimento humano com **HOF-Fixture_1**."),
])
def test_handoff_receipt_cannot_authorize_complaint_creation_in_same_sentence(language, text):
    data = verified_handoff(inputs("HANDOFF", language))
    assert "action_success_unverified" in validate_response(response(text, language), data)
    candidate = narrative(request_summary="Cliente de habla española solicita revisión. " + text, customer_language=language)
    if language == "pt":
        candidate["request_summary"] = candidate["request_summary"].replace("española", "portuguesa")
    assert "action_success_unverified" in validate_handoff_summary(candidate, data)


@pytest.mark.parametrize("language, text", [
    ("es", "El reclamo **CMP-SBX-Case_123** fue registrado y fue derivado a atención humana."),
    ("pt", "A reclamação **CMP-SBX-Case_123** foi registrada e foi encaminhada para atendimento humano."),
])
def test_action_receipt_cannot_authorize_handoff_in_same_sentence(language, text):
    data = verified_action(inputs("ACTION_DONE", language))
    assert "handoff_success_unverified" in validate_response(response(text, language), data)
    candidate = narrative(request_summary="Cliente de habla española solicita revisión. " + text, customer_language=language)
    if language == "pt":
        candidate["request_summary"] = candidate["request_summary"].replace("española", "portuguesa")
    assert "handoff_success_unverified" in validate_handoff_summary(candidate, data)


@pytest.mark.parametrize("language, text", [
    ("es", "El reclamo **CMP-SBX-Case_123** fue registrado, y necesita atención humana."),
    ("pt", "A reclamação **CMP-SBX-Case_123** foi registrada e precisa de atendimento humano."),
])
def test_verified_action_can_describe_required_review_without_created_handoff(language, text):
    data = verified_action(inputs("ACTION_DONE", language))
    data["policy_context"] = retrieve_policy("HUMAN_REQUEST", human_required=True)
    assert validate_response(response(text, language, chunk_ids=["handoff-01"]), data) == []


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


@pytest.mark.parametrize("language,text", [
    ("es", "Ya se está procesando la solicitud."),
    ("es", "Tu solicitud está en proceso."),
    ("es", "La solicitud está siendo procesada."),
    ("es", "Estamos procesando el reclamo."),
    ("es", "Tu solicitud simulada ya está en procesamiento."),
    ("pt", "A solicitação está sendo processada."),
    ("pt", "Já está processando a solicitação."),
    ("pt", "Estamos processando a solicitação."),
    ("pt", "Sua solicitação está em processamento."),
    ("pt", "Seu pedido já está em processo."),
])
@pytest.mark.parametrize("prefix", ["", "Responder en este chat no autoriza ni registra la solicitud. "])
def test_present_processing_claims_require_execution_even_after_true_limitation(language, text, prefix):
    data = inputs("CONFIRM_ACTION", language)
    data.update(clean_query=text, historic_conversation=text)
    assert "processing_unverified" in validate_response(response(prefix + text, language), data)


@pytest.mark.parametrize("language,text", [
    ("es", "Tu solicitud **CMP-SBX-Case_123** está en proceso."),
    ("pt", "Sua solicitação **CMP-SBX-Case_123** está em processamento."),
])
def test_completed_execution_receipt_does_not_prove_current_processing(language, text):
    data = verified_action(inputs("ACTION_DONE", language))
    assert "processing_unverified" in validate_response(response(text, language), data)


@pytest.mark.parametrize("language,text", [
    ("es", "No puedo confirmar el procesamiento de la solicitud."),
    ("pt", "Não posso confirmar o processamento da solicitação."),
])
def test_processing_uncertainty_does_not_assert_an_active_operation(language, text):
    assert validate_response(response(text, language), inputs("ACTION_UNVERIFIED", language)) == []


@pytest.mark.parametrize("language,text", [
    ("pt", "Sinto muito que você esteja em perigo. Sua situação precisa de atendimento humano. Ainda não posso confirmar que o encaminhamento foi realizado."),
    ("es", "Tu solicitud necesita atención humana. Aún no puedo confirmar que la derivación fue realizada."),
])
def test_native_handoff_uncertainty_does_not_assert_completion(language, text):
    assert validate_response(response(text, language), inputs("HANDOFF", language)) == []


@pytest.mark.parametrize("suffix", [
    " e o encaminhamento foi realizado.",
    ". O encaminhamento foi realizado.",
    "; o encaminhamento foi realizado.",
    ", mas o encaminhamento foi realizado.",
])
def test_negative_handoff_uncertainty_cannot_launder_completion(suffix):
    text = "Ainda não posso confirmar que o encaminhamento foi realizado" + suffix
    assert "handoff_success_unverified" in validate_response(response(text, "pt"), inputs("HANDOFF", "pt"))


def test_native_emergency_contact_advice_remains_unsupported_after_handoff_uncertainty():
    text = (
        "Sinto muito que você esteja em perigo. Você precisa de atendimento humano, "
        "mas ainda não posso confirmar o encaminhamento. Se o perigo for imediato, "
        "procure um local seguro e ligue para o serviço de emergência da sua região."
    )
    assert "unsupported_operation_guidance" in validate_response(response(text, "pt"), inputs("HANDOFF", "pt"))


@pytest.mark.parametrize("language,text", [
    ("es", "La solicitud **CMP-SBX-Case_123** fue procesada y su registro fue verificado."),
    ("pt", "A solicitação **CMP-SBX-Case_123** foi processada e seu registro foi verificado."),
])
def test_grounded_action_done_preserves_factual_processing_with_receipt(language, text):
    data = verified_action(inputs("ACTION_DONE", language))
    assert validate_response(response(text, language), data) == []
    data["workflow_state"]["action"]["executed"] = False
    errors = validate_response(response(text, language), data)
    assert {"action_receipt_unverified", "processing_unverified"} <= set(errors)


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


@pytest.mark.parametrize("text", ["COP9999", "usd1234.56", "ZZZ1234.56", "1234.56e9 COP"])
def test_compact_and_exponent_money_notation_does_not_hide_invention(text):
    assert {"amount_unverified", "currency_unverified"}.intersection(validate_response(response(text), inputs()))


@pytest.mark.parametrize("text", ["COP1234.56", "cop1234.56", "1.23456e3 COP"])
def test_known_compact_and_exponent_money_notation(text):
    assert validate_response(response(text), inputs()) == []


def test_currency_like_tokens_inside_exact_known_id_are_not_money():
    data = inputs()
    data["workflow_state"]["transaction_id"] = "TRX-USD123-COP"
    assert validate_response(response("**TRX-USD123-COP**"), data) == []


def narrative(**changes):
    return {"request_summary": "Cliente de habla española solicita revisar una compra que afirma no reconocer.", "customer_language": "es", "customer_stated_claims": ["El cliente afirma no reconocer una compra."], "suggested_open_questions": ["¿Qué necesita revisar?"], **changes}


def test_canonical_handoff_narrative_passes_without_action_or_result_id():
    assert validate_handoff_summary(narrative(), inputs()) == []
    data = verified_action(inputs())
    assert validate_handoff_summary(narrative(), data) == []
    assert validate_handoff_summary(narrative(request_summary="Cliente de habla española solicita revisión. El reclamo fue registrado en el entorno de prueba."), data) == []


def test_canonical_portuguese_customer_keeps_spanish_narrative():
    data = inputs(language="pt")
    candidate = narrative(request_summary="Cliente de habla portuguesa solicita revisar una compra que afirma no reconocer.", customer_language="pt")
    assert validate_handoff_summary(candidate, data) == []
    candidate["customer_language"] = "es"
    assert "customer_language_mismatch" in validate_handoff_summary(candidate, data)


@pytest.mark.parametrize("text, code", [("El cliente afirma que la compra costó 7777.77 COP.", "amount_unverified"), ("El cliente afirma que ocurrió el 2025-01-01.", "date_unverified"), ("El cliente afirma que tiene TRX-INVENTED.", "id_unverified"), ("El cliente afirma que tiene txn_invented.", "id_unverified"), ("El cliente afirma que tiene rev_invented.", "id_unverified")])
def test_handoff_claims_do_not_promote_unverified_chat_facts(text, code):
    data = inputs()
    data["clean_query"] = text
    data["historic_conversation"] = text
    assert code in validate_handoff_summary(narrative(customer_stated_claims=[text]), data)


@pytest.mark.parametrize("field", ["request_summary", "customer_stated_claims", "suggested_open_questions"])
@pytest.mark.parametrize("text", ["CLI-PRIVATE123", "éCLI-PRIVATE123", "persona@example.test", "+57 300 123 4567", "contraseña bancaria", "CVV", "código de verificación"])
def test_handoff_never_contains_private_contact_identifiers_or_credentials(field, text):
    candidate = narrative()
    candidate[field] = text if field == "request_summary" else [text + ("?" if field == "suggested_open_questions" else "")]
    assert "handoff_private_or_credentials" in validate_handoff_summary(candidate, inputs())


@pytest.mark.parametrize("question", ["¿Cuál es su teléfono?", "¿Cuál es su correo electrónico?", "¿Cuál es su número de tarjeta?", "¿Cuál es su contraseña?", "¿Cuál es su PIN?", "¿Cuál es su OTP?", "¿Cuál es su documento de identidad?"])
def test_handoff_questions_cannot_request_private_values(question):
    errors = validate_handoff_summary(narrative(suggested_open_questions=[question]), inputs())
    assert {"handoff_private_or_credentials", "handoff_private_contact_request"}.intersection(errors)


@pytest.mark.parametrize("text", ["curl http://example.test", "C:/Users/private/file", "s3://private-bucket/record", "powershell", "```secret```"])
def test_handoff_cannot_emit_commands_source_paths_or_private_urls(text):
    assert "handoff_implementation_detail" in validate_handoff_summary(narrative(suggested_open_questions=[text + "?"]), inputs())


def test_handoff_completed_action_and_handoff_claims_require_receipts():
    action = narrative(request_summary="Cliente de habla española solicita revisión. El reclamo fue registrado.")
    assert "action_success_unverified" in validate_handoff_summary(action, inputs())
    assert validate_handoff_summary(action, verified_action(inputs())) == []
    handoff = narrative(request_summary="Cliente de habla española solicita revisión. La atención humana fue registrada.")
    assert "handoff_success_unverified" in validate_handoff_summary(handoff, inputs())
    assert validate_handoff_summary(handoff, verified_handoff(inputs())) == []


def test_handoff_claims_require_explicit_customer_attribution():
    assert "customer_claim_not_attributed" in validate_handoff_summary(narrative(customer_stated_claims=["Ocurrió fraude en la transacción."]), inputs())
    assert validate_handoff_summary(narrative(customer_stated_claims=["Según el cliente, no reconoce la compra."]), inputs()) == []


def test_handoff_narrative_schema_sentence_and_question_limits():
    assert validate_handoff_summary(None, inputs()) == ["handoff_schema"]
    assert "handoff_schema" in validate_handoff_summary(narrative(extra="not allowed"), inputs())
    assert "customer_language_mismatch" in validate_handoff_summary(narrative(customer_language=[]), inputs())
    assert "request_summary_sentence_limit" in validate_handoff_summary(narrative(request_summary="Cliente de habla española. Solicita revisión. No reconoce la compra. Necesita atención."), inputs())
    assert "suggested_open_questions_limit" in validate_handoff_summary(narrative(suggested_open_questions=["¿Qué necesita revisar?"] * 5), inputs())
    assert "question_format" in validate_handoff_summary(narrative(suggested_open_questions=["¿Qué necesita revisar? ¿Qué ocurrió?"]), inputs())
    assert "customer_language_description_missing" in validate_handoff_summary(narrative(request_summary="Cliente solicita revisar una compra."), inputs())


def test_handoff_verified_display_amounts_and_dates_remain_available():
    candidate = narrative(request_summary="Cliente de habla española solicita revisar **TRX-FICTIONAL_A**, de **2026-09-29**, por **1234.56 COP**.")
    assert validate_handoff_summary(candidate, inputs()) == []


@pytest.mark.parametrize("language, text", [
    ("pt", "Entendo a urgência. É necessária atenção humana, mas ainda não posso confirmar o encaminhamento. Se possível, bloqueie o cartão pelo canal oficial do emissor."),
    ("es", "Bloquea la tarjeta por el canal oficial del emisor."),
    ("pt", "Você pode bloquear seu cartão por precaução."),
    ("es", "Puedes bloquear tu tarjeta por precaución."),
    ("es", "Te recomiendo suspender temporalmente tu tarjeta."),
    ("pt", "Pode ser prudente solicitar o bloqueio preventivo do cartão."),
    ("es", "Conviene que la tarjeta quede inhabilitada."),
    ("pt", "Mantenha o cartão desabilitado."),
    ("es", "Pausa tu tarjeta."),
    ("es", "Coloca tu tarjeta en pausa."),
    ("pt", "Desligue o cartão."),
    ("pt", "Interrompa as compras."),
    ("es", "Detén los cargos."),
    ("es", "Si deseas, solicita la devolución del cargo a tu banco."),
    ("es", "Quisiera que solicites reembolso."),
    ("pt", "Não posso garantir reembolso, mas você pode pedir estorno ao emissor."),
    ("pt", "O estorno é possível."),
    ("es", "Comunícate con tu banco a través de sus canales oficiales."),
    ("pt", "Entre em contato com a central do emissor por um canal oficial."),
    ("es", "Habla con tu banco."),
    ("pt", "Fale com o emissor."),
    ("pt", "Abra uma nova contestação no aplicativo do banco."),
    ("es", "Presenta una denuncia y cancela los pagos recurrentes."),
    ("es", "Cancela la tarjeta."),
    ("pt", "Cancele o cartão."),
    ("es", "Cambia tu contraseña y elimina la tarjeta de la aplicación."),
    ("pt", "Altere sua senha e remova o cartão do aplicativo."),
    ("es", "Transfiere el saldo a otra cuenta."),
    ("pt", "Realize um novo pagamento."),
    ("es", "La política indica «bloquea la tarjeta»."),
    ("pt", "Vou encaminhar sua solicitação para atendimento humano."),
])
def test_unsourced_operations_and_advice_are_rejected_in_es_pt(language, text):
    data = inputs("HANDOFF", language)
    data["policy_context"] = retrieve_policy("HUMAN_REQUEST", human_required=True)
    result = response(text, language, chunk_ids=["handoff-01"])
    errors = validate_response(result, data)
    assert {"unsupported_operation_guidance", "recommendation_unverified"}.intersection(errors)


@pytest.mark.parametrize("text", ["Blo**queie** o cartão.", "__Bloqueie__ o cartão.", "Blo\u200bqueie o cartão.", "Não bloqueie o cartão.", "¿Debo bloquear la tarjeta?", "No es necesario bloquear tu tarjeta."])
def test_markup_invisibility_questions_and_negation_do_not_launder_advice(text):
    assert "unsupported_operation_guidance" in validate_response(response(text), inputs("HANDOFF"))


@pytest.mark.parametrize("language, text", [
    ("es", "No puedo bloquear tarjetas."),
    ("pt", "Não posso bloquear cartões."),
    ("es", "No puedo garantizar un reembolso."),
    ("pt", "Não posso garantir um estorno."),
    ("es", "No puedo bloquear tarjetas ni garantizar devolución."),
    ("pt", "Não posso bloquear cartões nem garantir reembolso."),
    ("es", "El asistente no determina fraude ni garantiza bloqueo o reembolso."),
])
def test_capability_limitations_remain_safe(language, text):
    assert validate_response(response(text, language), inputs("HANDOFF", language)) == []


@pytest.mark.parametrize("text", [
    "Una respuesta en el chat no autoriza ni registra la solicitud.",
    "El chat no autoriza ni registra la solicitud.",
    "Responder en este chat no autoriza ni registra la solicitud.",
])
def test_explicit_negative_chat_scope_does_not_request_intake(text):
    assert validate_response(response(text), inputs("CONFIRM_ACTION")) == []


@pytest.mark.parametrize("suffix", [
    " y responde con sí.",
    ". Responde con sí para registrar la solicitud.",
    "; usa el chat para registrar la solicitud.",
    ", pero registra la solicitud en este chat.",
    ". Confirma la transferencia en el portal.",
])
def test_negative_chat_scope_cannot_launder_added_operation(suffix):
    text = "Responder en este chat no autoriza ni registra la solicitud" + suffix
    errors = validate_response(response(text), inputs("CONFIRM_ACTION"))
    assert {"unsupported_operation_guidance", "recommendation_unverified"}.intersection(errors)


@pytest.mark.parametrize("language, text", [
    ("es", "Si deseas registrar una solicitud simulada, usa el control de confirmación del portal. Responder en este chat no autoriza ni registra la solicitud."),
    ("pt", "Se quiser registrar uma solicitação simulada, use o controle de confirmação do portal. Responder aqui no chat não faz o registro."),
])
def test_bilingual_optional_portal_intake_requires_no_chat_authority(language, text):
    data = inputs("CONFIRM_ACTION", language)
    assert validate_response(response(text, language), data) == []
    assert not any(data["workflow_state"]["action"][key] for key in ("authorized", "executed", "verified"))


def test_native_confirmation_preserves_source_timestamp_and_known_product_suffix():
    data = inputs("CONFIRM_ACTION")
    data["structured_data"]["candidates"][0].update(
        transaction_id="txn_9b24bf867ab09efac917e05d", transaction_date="2026-09-16 18:25:00",
        amount="954.58", currency="MXN", merchant_name="Mercado Origen", product_last4="4381",
    )
    data["workflow_state"]["transaction_id"] = "txn_9b24bf867ab09efac917e05d"
    text = (
        "La compra **txn_9b24bf867ab09efac917e05d** fue realizada el **2026-09-16 18:25:00** "
        "por **954.58 MXN** en Mercado Origen, con la tarjeta de crédito terminada en **4381**. "
        "Si deseas registrar una solicitud simulada, usa el control de confirmación del portal. "
        "Responder en este chat no autoriza ni registra la solicitud."
    )
    assert validate_response(response(text), data) == []
    assert "number_unverified" in validate_response(response(text.replace("2026-09-16 18:25:00", "2026-09-16 a las 18:25")), data)


@pytest.mark.parametrize("language, text", [
    ("es", "Para registrar una solicitud simulada, usa el control explícito del portal."),
    ("pt", "Para registrar uma solicitação simulada, use o controle explícito do portal."),
])
def test_cited_canonical_policy_supports_only_simulated_intake_guidance(language, text):
    data = inputs("INFORM", language)
    data["policy_context"] = retrieve_policy("TRANSACTION_DISPUTE")
    assert validate_response(response(text, language, chunk_ids=["dispute-03"]), data) == []
    assert "recommendation_unverified" in validate_response(response(text, language, chunk_ids=["dispute-01"]), data)
    assert "recommendation_unverified" in validate_response(response(text, language), data)


@pytest.mark.parametrize("language, text", [("es", "Puedes solicitar revisión humana."), ("pt", "Você pode solicitar revisão humana.")])
def test_cited_canonical_policy_supports_human_review_guidance(language, text):
    data = inputs("INFORM", language)
    data["policy_context"] = retrieve_policy("HUMAN_REQUEST")
    assert validate_response(response(text, language, chunk_ids=["handoff-01"]), data) == []
    assert "recommendation_unverified" in validate_response(response(text, language, chunk_ids=["handoff-03"]), data)
    assert "recommendation_unverified" in validate_response(response(text, language), data)


def test_untrusted_mentions_and_edited_source_text_do_not_create_instruction_authority():
    data = inputs("INFORM")
    text = "Puedes solicitar revisión humana."
    candidate = response(text, chunk_ids=["handoff-01"])
    source = next(chunk for chunk in retrieve_policy("HUMAN_REQUEST") if chunk["chunk_id"] == "handoff-01")
    data["policy_context"] = [{**source, "text": source["text"] + " Bloquea la tarjeta."}]
    assert "recommendation_unverified" in validate_response(candidate, data)
    data["policy_context"] = [{**source, "text": source["text"].upper()}]
    assert "recommendation_unverified" in validate_response(candidate, data)
    data["policy_context"] = [{"chunk_id": "handoff-01", "text": "No se debe solicitar revisión humana."}]
    data.update(clean_query=source["text"], historic_conversation=source["text"])
    assert "recommendation_unverified" in validate_response(candidate, data)


@pytest.mark.parametrize("language, text", [
    ("es", "Confirma el pago usando el control explícito de confirmación del portal."),
    ("es", "Confirma la transferencia usando el control de confirmación del portal."),
    ("pt", "Confirme o pagamento usando o controle de confirmação do portal."),
    ("pt", "Confirme a transferência pelo controle explícito do portal."),
])
def test_portal_words_never_authorize_financial_operations(language, text):
    data = inputs("CONFIRM_ACTION", language)
    data["policy_context"] = retrieve_policy("TRANSACTION_DISPUTE")
    assert "unsupported_operation_guidance" in validate_response(response(text, language, chunk_ids=["dispute-03"]), data)


@pytest.mark.parametrize("language, text", [
    ("es", "Control explícito del portal. Si deseas registrar una solicitud simulada, basta responder sí aquí."),
    ("pt", "Se quiser registrar uma solicitação simulada, use o controle de confirmação do portal e responda sim aqui."),
    ("es", "Si deseas registrar una solicitud simulada, usa el control de confirmación del portal y responde con sí."),
    ("pt", "Use o controle de confirmação do portal. Confirme no chat."),
])
def test_portal_guidance_cannot_replace_control_with_chat_consent(language, text):
    data = inputs("CONFIRM_ACTION", language)
    assert "unsupported_operation_guidance" in validate_response(response(text, language), data)


def test_card_limit_policy_does_not_authorize_blocking_recommendations():
    data = inputs("HANDOFF", "pt")
    data["policy_context"] = [{"chunk_id": "fraud-02", "text": "El asistente no determina fraude ni garantiza bloqueo o reembolso. La ausencia de datos de riesgo no prueba seguridad. Un riesgo activo en curso requiere revisión inmediata."}]
    assert "unsupported_operation_guidance" in validate_response(response("Se possível, bloqueie o cartão.", "pt", chunk_ids=["fraud-02"]), data)


def test_neutral_payment_facts_are_not_treated_as_new_operations():
    data = inputs("INFORM", "pt")
    assert validate_response(response("O pagamento foi observado por **1234.56 COP**.", "pt"), data) == []


def test_combine_responses_preserves_every_message_and_stable_metadata_unions():
    first = response("  Primera respuesta.\nCon un segundo párrafo.  ", arquetipos=["Guía Clara"], chunk_ids=["dispute-01"], data_sources=["transactions"])
    second = response("Segunda respuesta.", arquetipos=["Acompañamiento", "Guía Clara"], chunk_ids=["dispute-01", "handoff-01"], data_sources=["complaints", "transactions"])
    originals = copy.deepcopy([first, second])
    result = combine_responses([first, second], "es", active_query_index=1)
    assert result == {"message": first["message"] + "\n\n" + second["message"], "language": "es", "arquetipos": ["Guía Clara", "Acompañamiento"], "chunk_ids": ["dispute-01", "handoff-01"], "data_sources": ["transactions", "complaints"], "grounding_violation": 0}
    assert [first, second] == originals
    assert combine_responses([first, second], "es", active_query_index=0) == result


@pytest.mark.parametrize("changes", [
    {"extra": "private extra field"}, {"language": "pt"}, {"message": ""}, {"message": None},
    {"grounding_violation": 1}, {"grounding_violation": True}, {"arquetipos": ["Invented"]},
    {"chunk_ids": "not a list"}, {"data_sources": [None]}, {"arquetipos": [{}]},
])
def test_composition_fails_closed_on_invalid_or_mixed_language_parts(changes):
    with pytest.raises(ValueError, match="^invalid_response_part$"):
        combine_responses([response(), response(**changes)], "es")


@pytest.mark.parametrize("parts, language, index", [([], "es", 0), (None, "es", 0), ([response()], "other", 0), ([response()], "es", -1), ([response()], "es", 1), ([response()], "es", True), ([response()], "es", "0")])
def test_composition_validates_container_language_and_active_index(parts, language, index):
    with pytest.raises(ValueError, match="^invalid_response_composition$"):
        combine_responses(parts, language, index)


def test_composition_does_not_pool_facts_or_rewrite_already_grounded_queries():
    first_data, second_data = inputs(), inputs()
    second_data["structured_data"]["candidates"][0].update(transaction_id="TRX-FICTIONAL_B", amount="25", currency="USD")
    second_data["workflow_state"]["transaction_id"] = "TRX-FICTIONAL_B"
    first = response("**TRX-FICTIONAL_A**: **1234.56 COP**.")
    second = response("**TRX-FICTIONAL_B**: **25 USD**.")
    assert validate_response(first, first_data) == []
    assert validate_response(second, second_data) == []
    result = combine_responses([first, second], "es")
    assert result["message"] == "**TRX-FICTIONAL_A**: **1234.56 COP**.\n\n**TRX-FICTIONAL_B**: **25 USD**."
    assert "id_unverified" in validate_response(second, first_data)


@pytest.mark.parametrize("language, text, citation", [
    ("es", "Puedes confirmar la recepción simulada en el control explícito del portal.", "dispute-03"),
    ("pt", "Você pode confirmar a solicitação simulada no controle explícito do portal.", "dispute-03"),
    ("es", "Puedes solicitar una revisión humana.", "handoff-01"),
    ("pt", "Você pode solicitar uma revisão humana.", "handoff-01"),
])
def test_exact_independent_evaluator_source_supported_guidance(language, text, citation):
    data = inputs("INFORM", language)
    data["policy_context"] = retrieve_policy("TRANSACTION_DISPUTE", human_required=True)
    assert validate_response(response(text, language, chunk_ids=[citation]), data) == []
    assert "recommendation_unverified" in validate_response(response(text, language, chunk_ids=["dispute-01"]), data)


@pytest.mark.parametrize("language, text", [("es", "Para reclamar, confirma una transferencia en el control explícito del portal."), ("pt", "Para reclamar, confirme uma transferência no controle explícito do portal.")])
def test_exact_independent_evaluator_banking_operation_substitution(language, text):
    data = inputs("INFORM", language)
    data["policy_context"] = retrieve_policy("TRANSACTION_DISPUTE", human_required=True)
    assert "unsupported_operation_guidance" in validate_response(response(text, language, chunk_ids=["dispute-03"]), data)


@pytest.mark.parametrize("language, text", [("es", "Envíame tu contraseña."), ("es", "Dame tu PIN."), ("es", "Comparte tu código de verificación."), ("pt", "Envie sua senha."), ("pt", "Informe seu PIN."), ("pt", "Compartilhe seu OTP.")])
def test_customer_credentials_cannot_be_requested(language, text):
    assert "credential_request" in validate_response(response(text, language), inputs("HANDOFF", language))


@pytest.mark.parametrize("language, text", [("es", "No compartas contraseñas."), ("pt", "Não compartilhe sua senha.")])
def test_safe_credential_sharing_limitations_are_preserved(language, text):
    assert validate_response(response(text, language), inputs("HANDOFF", language)) == []


def test_negative_sharing_clause_does_not_launder_secret_collection():
    data = inputs("HANDOFF", "pt")
    assert "credential_request" in validate_response(response("Não compartilhe sua senha e envie seu PIN.", "pt"), data)


@pytest.mark.parametrize("parts", [[response("a" * 6000), response("b" * 6000)], [response(chunk_ids=[f"first-{i}" for i in range(30)]), response(chunk_ids=["last"])]])
def test_composition_rejects_aggregate_overflow_without_truncating_or_dropping_citations(parts):
    original = copy.deepcopy(parts)
    with pytest.raises(ValueError, match="^response_composition_overflow$"):
        combine_responses(parts, "es")
    assert parts == original


def test_composition_caps_parts_and_metadata_string_lengths():
    with pytest.raises(ValueError, match="^invalid_response_composition$"):
        combine_responses([response()] * 9, "es")
    with pytest.raises(ValueError, match="^invalid_response_part$"):
        combine_responses([response(chunk_ids=["a" * 161])], "es")
