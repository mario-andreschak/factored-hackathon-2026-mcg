"""Deterministic ES/PT customer text derived only from verified server state."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re


_RECEIPT = re.compile(r"^CMP-SBX-[A-Za-z0-9_-]{8}$")
_HANDOFF = re.compile(r"^HOF-[A-Za-z0-9_-]{8}$")
_SNAPSHOT = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_REASONS = frozenset({"high_risk", "missing_evidence", "out_of_policy", "emergency",
                     "action_unverified", "customer_request", "clarification_exhausted",
                     "duplicate_review", "no_match_exhausted", "tool_failure"})
_FACT_LIMITS = {"transaction_reference": 16, "transaction_date": 40, "process_date": 10,
                "amount": 64, "currency": 8, "status": 80, "merchant": 160,
                "transaction_type": 80, "channel": 80, "product": 80}


def handoff_questions(value: object) -> list[str] | None:
    if (not isinstance(value, list) or len(value) > 8
            or any(not isinstance(q, str) or not q or q != q.strip() or len(q) > 240
                   or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in q)
                   for q in value)):
        return None
    return list(value)


def normalize_handoff_questions(value: object) -> list[str] | None:
    """Canonicalize new request text, never saved packet evidence."""
    if (not isinstance(value, list) or len(value) > 8
            or any(not isinstance(q, str)
                   or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in q)
                   for q in value)):
        return None
    return handoff_questions([q.strip() for q in value])


def _timestamp(value: object, *, aware: bool = False) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= 40:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return not aware or parsed.utcoffset() is not None
    except (ValueError, TypeError):
        return False


def public_facts(value: object) -> dict | None:
    """Copy only the bounded MCP public transaction shape."""
    if not isinstance(value, dict) or set(value) != set(_FACT_LIMITS):
        return None
    for field, limit in _FACT_LIMITS.items():
        item = value[field]
        if field == "merchant" and item is None:
            continue
        minimum = 0 if field in {"transaction_type", "channel", "product"} else 1
        if not isinstance(item, str) or not minimum <= len(item) <= limit:
            return None
    if (not re.fullmatch(r"txn_[a-f0-9]{12}", value["transaction_reference"])
            or not _timestamp(value["transaction_date"])
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["process_date"])
            or not re.fullmatch(r"[A-Z]{3}", value["currency"])
            or not re.fullmatch(r"-?(?:0|[1-9]\d{0,15})(?:\.\d{1,2})?", value["amount"])):
        return None
    try:
        date.fromisoformat(value["process_date"])
        if not Decimal(value["amount"]).is_finite():
            return None
    except (ValueError, TypeError, InvalidOperation):
        return None
    return {field: value[field] for field in _FACT_LIMITS}


def verified_receipt(value: object) -> dict | None:
    """Validate the saved receipt, whose snapshot is its original record."""
    if not isinstance(value, dict):
        return None
    facts = public_facts(value.get("transaction"))
    snapshot = value.get("snapshot")
    if (not isinstance(value.get("id"), str) or not _RECEIPT.fullmatch(value["id"])
            or value.get("kind") != "simulated_intake" or value.get("simulated") is not True
            or value.get("status") != "received"
            or not isinstance(snapshot, str) or not _SNAPSHOT.fullmatch(snapshot)
            or not _timestamp(value.get("created_at"), aware=True) or facts is None):
        return None
    return {"id": value["id"], "kind": "simulated_intake", "simulated": True,
            "status": "received", "snapshot": snapshot, "created_at": value["created_at"], "transaction": facts}


def verified_handoff(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    snapshot = value.get("snapshot")
    facts = public_facts(value.get("facts"))
    general = snapshot is None and value.get("facts") == {}
    if (not isinstance(value.get("id"), str) or not _HANDOFF.fullmatch(value["id"])
            or not isinstance(value.get("reason"), str) or value["reason"] not in _REASONS
            or value.get("human_responded") is not False
            or not _timestamp(value.get("created_at"), aware=True)
            or (not general and (facts is None or not isinstance(snapshot, str)
                                 or not _SNAPSHOT.fullmatch(snapshot)))):
        return None
    packet = {"id": value["id"], "reason": value["reason"], "snapshot": snapshot,
              "created_at": value["created_at"], "facts": {} if general else facts,
              "human_responded": False}
    saved = value.get("packet")
    if "packet" in value and not isinstance(saved, dict):
        return None
    if isinstance(saved, dict):
        if (set(saved) != {"schema", "transaction", "transaction_provenance", "reason",
                           "unanswered_questions", "human_responded"}
                or saved.get("schema") != "banking-sandbox-handoff/v1"
                or saved.get("reason") != packet["reason"] or saved.get("human_responded") is not False
                or saved.get("transaction") != (None if general else facts)):
            return None
        for alias in ("transaction_provenance", "unanswered_questions"):
            if alias in value and value[alias] != saved.get(alias):
                return None
    else:
        # Frontend storage retains only this flattened public projection.
        # Neither legacy IDs nor a packet with absent questions proves evidence.
        saved = value
    questions = saved.get("unanswered_questions")
    if handoff_questions(questions) is None:
        return None
    provenance = saved.get("transaction_provenance")
    currentness = value.get("transaction_currentness")
    if general:
        if provenance is not None or currentness != "not_applicable":
            return None
    elif (not isinstance(provenance, dict) or set(provenance) != {"source", "snapshot", "as_of"}
          or provenance.get("source") != "owned_serving_snapshot" or provenance.get("snapshot") != snapshot
          or not _timestamp(provenance.get("as_of"), aware=True)
          or datetime.fromisoformat(provenance["as_of"].replace("Z", "+00:00")).utcoffset().total_seconds() != 0
          or currentness not in {"same_snapshot", "different_snapshot", "unknown"}):
        return None
    packet.update(unanswered_questions=list(questions),
                  transaction_provenance=dict(provenance) if provenance is not None else None,
                  transaction_currentness=currentness)
    return packet


def matches_selected_transaction(facts: object, selected: object) -> bool:
    """Compare host-resolved display fields, never unrelated opaque references."""
    facts = public_facts(facts)
    if facts is None or not isinstance(selected, dict) or "channel" not in selected:
        return False
    try:
        if (isinstance(selected.get("amount"), bool)
                or Decimal(str(selected["amount"])) != Decimal(facts["amount"])
                or datetime.fromisoformat(selected["occurred_at"].replace("Z", "+00:00"))
                    != datetime.fromisoformat(facts["transaction_date"].replace("Z", "+00:00"))):
            return False
    except (KeyError, ValueError, TypeError, AttributeError, InvalidOperation):
        return False
    merchant, transaction_type, channel = selected.get("merchant"), selected.get("type"), selected.get("channel")
    product = selected.get("product")
    if any(value is not None and not isinstance(value, str) for value in (merchant, transaction_type, channel, product)):
        return False
    # Apply the same public display bounds as MCP Repository._visible to the
    # privately resolved owner row; the raw target identity remains server-only.
    return (selected.get("currency") == facts["currency"]
            and selected.get("status") == facts["status"]
            and selected.get("process_date") == facts["process_date"]
            and ((merchant or "")[:160] or None) == facts["merchant"]
            and (transaction_type or "")[:80] == facts["transaction_type"]
            and (channel or "")[:80] == facts["channel"]
            and ("product" not in selected or (product or "")[:80] == facts["product"]))


def project_action_result(result: dict) -> dict:
    """Only host readback states can supply public receipt/handoff evidence."""
    state = result.get("state")
    if not isinstance(state, str) or state not in {"none", "preparing", "prepare_unverified",
            "pending_confirmation", "intake_verified", "existing_case_verified",
            "handoff_verified", "handoff_unverified", "action_unverified"}:
        state = "action_unverified"
    public = {"state": state}
    for key, pattern in {
            "pending_handle": r"[A-Za-z0-9_-]{32,64}",
            "request_id": r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}",
            "target_reference": r"txn_[a-f0-9]{24}",
            "review_reference": r"rev_[a-f0-9]{24}"}.items():
        if isinstance(result.get(key), str) and re.fullmatch(pattern, result[key]):
            public[key] = result[key]
    if isinstance(result.get("reason"), str) and result["reason"] in _REASONS:
        public["reason"] = result["reason"]
    if result.get("recovery_exhausted") is True:
        public["recovery_exhausted"] = True
    if handoff_questions(result.get("unanswered_questions")) is not None:
        public["unanswered_questions"] = list(result["unanswered_questions"])
    snapshot = result.get("snapshot")
    facts = public_facts(result.get("transaction"))
    if isinstance(snapshot, str) and _SNAPSHOT.fullmatch(snapshot) and facts is not None:
        public.update(snapshot=snapshot, transaction=facts)
    if state == "pending_confirmation":
        if "pending_handle" not in public or "snapshot" not in public or "transaction" not in public:
            public["state"] = "prepare_unverified"
    elif state in {"intake_verified", "existing_case_verified"}:
        receipt = verified_receipt(result.get("receipt"))
        if receipt and (state != "existing_case_verified" or (
                "snapshot" in public and public.get("transaction") == receipt["transaction"])):
            public["receipt"] = receipt
        else:
            public["state"] = "prepare_unverified" if state == "existing_case_verified" else "action_unverified"
    elif state == "handoff_verified":
        packet = verified_handoff(result.get("handoff"))
        if packet:
            public["handoff"] = packet
        else:
            public["state"] = "handoff_unverified"
    elif state == "action_unverified" and isinstance(result.get("handoff"), dict):
        nested = project_action_result(result["handoff"])
        public["handoff"] = nested if nested.get("state") == "handoff_verified" else {"state": "handoff_unverified"}
    prior_receipt = result.get("prior_receipt")
    if (isinstance(prior_receipt, dict) and set(prior_receipt) == {"target_reference", "receipt"}
            and "target_reference" in public
            and prior_receipt.get("target_reference") == public["target_reference"]):
        receipt = verified_receipt(prior_receipt.get("receipt"))
        if receipt:
            public["prior_receipt"] = {"target_reference": public["target_reference"], "receipt": receipt}
    prior_handoff = result.get("prior_handoff")
    if (isinstance(prior_handoff, dict) and set(prior_handoff) == {"target_reference", "handoff"}
            and prior_handoff.get("target_reference") is None and "target_reference" not in public):
        packet = verified_handoff(prior_handoff.get("handoff"))
        if packet and packet["snapshot"] is None:
            public["prior_handoff"] = {"target_reference": None, "handoff": packet}
    return public


def render_action(result: dict, language: str) -> dict:
    if language not in {"es", "pt"} or not isinstance(result, dict):
        raise ValueError("invalid action response")
    result = project_action_result(result)
    state = result.get("state")
    texts = {
        "es": {
            "pending": "Confirma si deseas registrar una recepción simulada para este cargo. No es un reembolso ni una resolución bancaria.",
            "receipt": "Recepción simulada registrada y verificada. Folio: {id}. No se ha resuelto una disputa ni emitido un reembolso.",
            "existing": "Ya existe una recepción simulada registrada para este cargo. Folio: {id}. No se registró otra recepción; esto no es una resolución bancaria ni un reembolso.",
            "handoff": "Se guardó y verificó una solicitud de revisión humana. Folio: {id}. Aún no hay respuesta de una persona.",
            "handoff_unverified": "Se requiere revisión humana, pero no se pudo verificar que la solicitud se haya creado.",
            "action_unverified": "No se pudo verificar si se registró la recepción simulada. No vuelvas a confirmarla automáticamente.",
            "followup_unverified": "No se pudo verificar la preparación del seguimiento. La recepción simulada anterior sigue verificada. La nueva solicitud continúa sin resolver y bloqueada.",
            "followup_preparing": "Se está verificando la preparación del seguimiento. La recepción simulada anterior sigue verificada. La nueva solicitud continúa bloqueada.",
        },
        "pt": {
            "pending": "Confirme se deseja registrar uma solicitação simulada para esta cobrança. Isto não é reembolso nem resolução bancária.",
            "receipt": "Solicitação simulada registrada e verificada. Protocolo: {id}. Nenhuma disputa foi resolvida e não houve reembolso.",
            "existing": "Já existe uma solicitação simulada registrada para esta cobrança. Protocolo: {id}. Nenhuma outra solicitação foi registrada; isto não é uma resolução bancária nem reembolso.",
            "handoff": "Uma solicitação de análise humana foi salva e verificada. Protocolo: {id}. Ainda não houve resposta de uma pessoa.",
            "handoff_unverified": "É necessário atendimento humano, mas não foi possível verificar a criação da solicitação.",
            "action_unverified": "Não foi possível verificar se a solicitação simulada foi registrada. Não a confirme novamente automaticamente.",
            "followup_unverified": "Não foi possível verificar a preparação do acompanhamento. A solicitação simulada anterior continua verificada. A nova solicitação permanece sem resolução e bloqueada.",
            "followup_preparing": "A preparação do acompanhamento está sendo verificada. A solicitação simulada anterior continua verificada. A nova solicitação permanece bloqueada.",
        },
    }[language]
    handoff = result.get("handoff")
    handoff_state = handoff if state == "action_unverified" and isinstance(handoff, dict) else result
    packet = handoff_state.get("handoff") if isinstance(handoff_state, dict) else None
    handoff_id = packet.get("id") if isinstance(packet, dict) else None
    verified_handoff = (handoff_state.get("state") == "handoff_verified"
                        and isinstance(handoff_id, str)
                        and re.fullmatch(r"HOF-[A-Za-z0-9_-]{8}", handoff_id))
    if state == "pending_confirmation":
        message = texts["pending"]
    elif state in {"intake_verified", "existing_case_verified"}:
        receipt = result.get("receipt")
        receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
        if not isinstance(receipt_id, str) or not re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", receipt_id):
            raise ValueError("unverified receipt")
        message = texts["existing" if state == "existing_case_verified" else "receipt"].format(id=receipt_id)
    elif state == "handoff_verified":
        message = texts["handoff"].format(id=handoff_id) if verified_handoff else texts["handoff_unverified"]
    elif state == "action_unverified":
        message = texts["action_unverified"]
        message += " " + (texts["handoff"].format(id=handoff_id)
                          if verified_handoff else texts["handoff_unverified"])
    elif state in {"preparing", "prepare_unverified"} and result.get("prior_receipt"):
        message = texts["followup_preparing" if state == "preparing" else "followup_unverified"]
    else:
        message = texts["handoff_unverified"]
    return {**result, "language": language, "message": message}
