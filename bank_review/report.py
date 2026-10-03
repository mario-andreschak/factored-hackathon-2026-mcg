"""Bounded metadata projection; banking evidence and reviewer decisions stay separate."""
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from analytics.extract import SCHEMA_VERSION


ASSETS = Path(__file__).parent / "assets"
FIELDS = (
    "turn_id", "conversation_id", "ts", "language", "effective_language", "intent",
    "response_mode", "rule_ids", "reason_code", "policy_version", "source",
    "handoff_required", "handoff_created", "human_requested", "action_verified",
    "grounding_violation", "safe_fallback_used", "node_errors", "node_latency_ms",
)


def signals(row):
    flags = []
    if row.get("grounding_violation") == 1:
        flags.append("Grounding flag")
    if row.get("response_mode") == "ACTION_UNVERIFIED":
        flags.append("Uncertain action")
    if row.get("node_errors") not in (None, "[]", "", []):
        flags.append("Node error")
    if row.get("handoff_required") == 1 or row.get("human_requested") == 1:
        flags.append("Human review requested")
    if row.get("safe_fallback_used") == 1:
        flags.append("Fallback used")
    if row.get("response_mode") == "CLARIFY":
        flags.append("Clarification")
    return flags


def read_analytics(path, limit=500):
    if type(limit) is not int or not 1 <= limit <= 5000:
        raise ValueError("review limit must be between 1 and 5000")
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("BEGIN")  # all counts and selected turns share one read snapshot
        meta = dict(db.execute("SELECT key,value FROM meta"))
        if meta.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("unsupported analytics schema; rebuild with the current analytics package")
        total = db.execute("SELECT count(*) FROM turns").fetchone()[0]
        # Review signals first; this is a bounded sample, not a bank incident/SLA queue.
        rows = [dict(row) for row in db.execute(f"""
            SELECT {','.join(FIELDS)} FROM turns ORDER BY
            coalesce(grounding_violation,0) DESC,
            (response_mode='ACTION_UNVERIFIED') DESC,
            coalesce(handoff_required,0) DESC, ts DESC, turn_id LIMIT ?
        """, (limit,))]
        languages = dict(db.execute("SELECT coalesce(effective_language,language,'unknown'),count(*) FROM turns GROUP BY 1"))
        modes = dict(db.execute("SELECT coalesce(response_mode,'unknown'),count(*) FROM turns GROUP BY 1"))
    for row in rows:
        row["signals"] = signals(row)
    return {
        "schema": "bank-review/v1", "origin": "private_analytics_projection",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analytics_built_at": meta.get("built_at"), "total_turns": total,
        "languages": languages, "response_modes": modes, "rows": rows,
        "comparison": None,
    }


def demo_packet():
    examples = [
        ("es", "INFORM", [], "Consulta sobre un cargo", "¿Qué es este cargo?", "Se muestran los datos disponibles del cargo seleccionado; el comercio no consta en la fuente."),
        ("pt", "HANDOFF", ["Human review requested"], "Pedido de atendimento humano", "Quero falar com uma pessoa.", "Foi solicitada revisão humana. Ainda não há confirmação de atendimento por uma pessoa."),
        ("es", "ACTION_UNVERIFIED", ["Uncertain action"], "Confirmación con resultado incierto", "Ya confirmé. ¿Se recibió?", "No se ha podido verificar el resultado. No repetiremos la solicitud mientras se revisa."),
        ("pt", "CLARIFY", ["Clarification"], "Dois possíveis lançamentos", "Não reconheço essa compra.", "Há dois possíveis lançamentos. Escolha qual deseja consultar antes de continuar."),
        ("es", "TOOL_ERROR", ["Node error"], "La consulta no respondió", "¿Puedes revisar el movimiento?", "La consulta falló. No puedo confirmar los datos ni el estado de una solicitud."),
        ("pt", "INFORM", ["Fallback used"], "Resposta de contingência", "Qual é o próximo passo?", "Não foi possível obter uma resposta validada. Use o canal de atendimento indicado pelo banco."),
        ("es", "HANDOFF", ["Human review requested"], "Paquete marcado en el flujo", "Necesito ayuda de un asesor.", "El flujo marcó una derivación; ese dato por sí solo no acredita recepción por el banco."),
        ("pt", "INFORM", ["Grounding flag"], "Recomendação sem suporte", "O que faço agora?", "Bloqueie o cartão imediatamente. [Exemplo de conselho sem suporte para revisão.]"),
    ]
    rows = []
    for index, (lang, mode, flags, title, request, reply) in enumerate(examples, 1):
        rows.append({
            "turn_id": f"fictional-turn-{index:02}", "conversation_id": f"fictional-conversation-{index:02}",
            "ts": None, "language": lang, "effective_language": lang, "intent": "charge_review",
            "response_mode": mode, "rule_ids": "[]", "reason_code": None,
            "policy_version": "illustrative-rubric-v1", "source": "fictional_walkthrough",
            "handoff_required": 1 if mode == "HANDOFF" else 0,
            "handoff_created": 1 if index == 7 else None, "human_requested": 1 if mode == "HANDOFF" else 0,
            "action_verified": None, "grounding_violation": 1 if index == 8 else 0,
            "safe_fallback_used": 1 if index == 6 else 0,
            "node_errors": '["illustrative_read_error"]' if index == 5 else "[]",
            "node_latency_ms": None, "signals": flags, "title": title,
            "demo_request": request, "demo_reply": reply,
        })
    return {
        "schema": "bank-review/v1", "origin": "fictional_walkthrough",
        "generated_at": None, "analytics_built_at": None, "total_turns": len(rows),
        "languages": {"es": 4, "pt": 4},
        "response_modes": {mode: sum(row["response_mode"] == mode for row in rows) for mode in sorted({r["response_mode"] for r in rows})},
        "rows": rows, "comparison": None,
    }


def build_page(packet):
    # JSON is data in an inert script. Escape HTML delimiters even inside quoted values.
    payload = json.dumps(packet, ensure_ascii=True, allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (ASSETS / "page.html").read_text(encoding="utf-8")
    return template.replace("/* BANK_REVIEW_CSS */", (ASSETS / "style.css").read_text(encoding="utf-8")).replace(
        "/* BANK_REVIEW_JS */", (ASSETS / "app.js").read_text(encoding="utf-8")).replace("BANK_REVIEW_DATA", payload)
