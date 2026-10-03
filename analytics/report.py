"""Agent performance indicators computed from the analytics database."""
from __future__ import annotations

from contextlib import closing
import math
from pathlib import Path
import sqlite3
from typing import Any


_HANDOFF_OUTCOMES = ("handoff", "handoff_required")


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _distribution(db: sqlite3.Connection, sql: str, *args) -> dict[str, int]:
    return {str(key): count for key, count in db.execute(sql, args)}


def summarize(db_path: Path) -> dict[str, Any]:
    with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)) as db:
        conversations = db.execute("SELECT count(*) FROM conversations").fetchone()[0]
        workflow_conversations = db.execute("""SELECT count(*) FROM conversations c WHERE EXISTS
            (SELECT 1 FROM turns t WHERE t.conversation_id=c.conversation_id AND t.source='workflow')""").fetchone()[0]
        handed_off = db.execute(f"""SELECT count(*) FROM conversations
            WHERE outcome IN ({','.join('?' for _ in _HANDOFF_OUTCOMES)})""", _HANDOFF_OUTCOMES).fetchone()[0]
        turns = db.execute("SELECT count(*) FROM turns WHERE source='workflow'").fetchone()[0]
        rates = db.execute("""SELECT sum(safe_fallback_used), sum(grounding_violation),
            sum(attack_deceptive>0 OR attack_inappropriate>0), sum(node_errors!='[]'),
            sum(human_requested), sum(response_mode='CLARIFY') FROM turns WHERE source='workflow'""").fetchone()
        turn_counts = [row[0] for row in db.execute("SELECT n_turns FROM conversations")]
        identify = [row[0] for row in db.execute(
            "SELECT turns_to_identify FROM conversations WHERE turns_to_identify IS NOT NULL")]
        nodes = {}
        for node, kind in db.execute("SELECT DISTINCT node,kind FROM node_calls WHERE kind!='barrier' ORDER BY node"):
            latencies = [row[0] for row in db.execute(
                "SELECT latency_ms FROM node_calls WHERE node=? AND latency_ms IS NOT NULL", (node,))]
            calls, errors, retried = db.execute("""SELECT count(*), sum(status='error'), sum(coalesce(attempts,1)>1)
                FROM node_calls WHERE node=?""", (node,)).fetchone()
            nodes[node] = {"kind": kind, "calls": calls, "error_rate": _rate(errors or 0, calls),
                           "retry_rate": _rate(retried or 0, calls) if kind == "tool" else None,
                           "p50_ms": _percentile(latencies, 0.5), "p95_ms": _percentile(latencies, 0.95)}
        feedback = db.execute("""SELECT count(*), sum(rating=1), sum(rating=-1) FROM feedback""").fetchone()
        return {
            "volume": {"conversations": conversations, "workflow_conversations": workflow_conversations,
                       "workflow_turns": turns,
                       "transcript_only_turns": db.execute(
                           "SELECT count(*) FROM turns WHERE source='transcript'").fetchone()[0]},
            "outcomes": _distribution(db, "SELECT outcome,count(*) FROM conversations GROUP BY 1 ORDER BY 2 DESC"),
            "containment_rate": _rate(workflow_conversations - handed_off, workflow_conversations),
            "handoff_reasons": _distribution(db, """SELECT handoff_reason,count(*) FROM turns
                WHERE handoff_required=1 GROUP BY 1 ORDER BY 2 DESC"""),
            "turns_per_conversation": {"p50": _percentile(turn_counts, 0.5), "p95": _percentile(turn_counts, 0.95)},
            "turns_to_identify_transaction": {"conversations": len(identify), "p50": _percentile(identify, 0.5),
                                              "p95": _percentile(identify, 0.95)},
            "turn_rates": {"clarify": _rate(rates[5] or 0, turns), "safe_fallback": _rate(rates[0] or 0, turns),
                           "grounding_violation": _rate(rates[1] or 0, turns),
                           "attack_detected": _rate(rates[2] or 0, turns),
                           "node_error": _rate(rates[3] or 0, turns), "human_requested": _rate(rates[4] or 0, turns)},
            "response_modes": _distribution(db, """SELECT response_mode,count(*) FROM turns
                WHERE source='workflow' GROUP BY 1 ORDER BY 2 DESC"""),
            "intents": _distribution(db, """SELECT intent,count(*) FROM turns
                WHERE source='workflow' GROUP BY 1 ORDER BY 2 DESC"""),
            "emotional_context_outcomes": {
                f"{emotion}|{outcome}": count for emotion, outcome, count in db.execute("""
                    SELECT t.emotional_context, c.outcome, count(DISTINCT c.conversation_id)
                    FROM turns t JOIN conversations c USING(conversation_id)
                    WHERE t.emotional_context IS NOT NULL GROUP BY 1,2 ORDER BY 3 DESC""")},
            "error_codes": _distribution(db, """SELECT node || ':' || error_code, count(*) FROM node_calls
                WHERE error_code IS NOT NULL GROUP BY 1 ORDER BY 2 DESC"""),
            "nodes": nodes,
            "feedback": {"total": feedback[0], "positive": feedback[1] or 0, "negative": feedback[2] or 0,
                         "labels": _distribution(db, """SELECT label,count(*) FROM feedback
                             WHERE label IS NOT NULL GROUP BY 1 ORDER BY 2 DESC""")},
        }


def render(summary: dict[str, Any]) -> str:
    lines = []

    def section(title: str, values: dict[str, Any]):
        lines.append(f"\n## {title}")
        if not values:
            lines.append("  (sin datos)")
        for key, value in values.items():
            lines.append(f"  {key}: {value}")

    section("Volumen", summary["volume"])
    lines.append(f"\nTasa de contención (sin handoff): {summary['containment_rate']}")
    section("Resultado por conversación", summary["outcomes"])
    section("Motivos de handoff (turnos)", summary["handoff_reasons"])
    section("Turnos por conversación", summary["turns_per_conversation"])
    section("Turnos hasta identificar la transacción", summary["turns_to_identify_transaction"])
    section("Tasas por turno", summary["turn_rates"])
    section("Modos de respuesta", summary["response_modes"])
    section("Intenciones", summary["intents"])
    section("Contexto emocional | resultado", summary["emotional_context_outcomes"])
    section("Errores por nodo", summary["error_codes"])
    section("Nodos (llamadas, error, p50/p95 ms)", {
        node: f"{data['kind']} n={data['calls']} error={data['error_rate']} "
              f"retry={data['retry_rate']} p50={data['p50_ms']} p95={data['p95_ms']}"
        for node, data in summary["nodes"].items()})
    section("Feedback", {key: value for key, value in summary["feedback"].items() if key != "labels"})
    section("Etiquetas de feedback", summary["feedback"]["labels"])
    return "\n".join(lines).lstrip("\n")
