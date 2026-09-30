"""Deterministic ES/PT customer text derived only from verified server state."""
from __future__ import annotations

import re


def render_action(result: dict, language: str) -> dict:
    if language not in {"es", "pt"} or not isinstance(result, dict):
        raise ValueError("invalid action response")
    state = result.get("state")
    texts = {
        "es": {
            "pending": "Confirma si deseas registrar una recepción simulada para este cargo. No es un reembolso ni una resolución bancaria.",
            "receipt": "Recepción simulada registrada y verificada. Folio: {id}. No se ha resuelto una disputa ni emitido un reembolso.",
            "handoff": "Se creó y verificó una solicitud de revisión humana. Folio: {id}. Aún no hay respuesta de una persona.",
            "handoff_unverified": "Se requiere revisión humana, pero no se pudo verificar que la solicitud se haya creado.",
            "action_unverified": "No se pudo verificar si se registró la recepción simulada. No vuelvas a confirmarla automáticamente.",
        },
        "pt": {
            "pending": "Confirme se deseja registrar uma solicitação simulada para esta cobrança. Isto não é reembolso nem resolução bancária.",
            "receipt": "Solicitação simulada registrada e verificada. Protocolo: {id}. Nenhuma disputa foi resolvida e não houve reembolso.",
            "handoff": "Uma solicitação de atendimento humano foi criada e verificada. Protocolo: {id}. Ainda não houve resposta de uma pessoa.",
            "handoff_unverified": "É necessário atendimento humano, mas não foi possível verificar a criação da solicitação.",
            "action_unverified": "Não foi possível verificar se a solicitação simulada foi registrada. Não a confirme novamente automaticamente.",
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
    elif state == "intake_verified":
        receipt = result.get("receipt")
        receipt_id = receipt.get("id") if isinstance(receipt, dict) else None
        if not isinstance(receipt_id, str) or not re.fullmatch(r"CMP-SBX-[A-Za-z0-9_-]{8}", receipt_id):
            raise ValueError("unverified receipt")
        message = texts["receipt"].format(id=receipt_id)
    elif state == "handoff_verified":
        message = texts["handoff"].format(id=handoff_id) if verified_handoff else texts["handoff_unverified"]
    elif state == "action_unverified":
        message = texts["action_unverified"]
        message += " " + (texts["handoff"].format(id=handoff_id)
                          if verified_handoff else texts["handoff_unverified"])
    else:
        message = texts["handoff_unverified"]
    return {**result, "language": language, "message": message}
