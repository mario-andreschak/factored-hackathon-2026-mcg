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


def _host_summary(db: sqlite3.Connection) -> dict[str, Any]:
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"host_sources", "host_sessions", "host_actions", "host_cancellations"} <= tables:
        return {"status": "unavailable", "reason": "rebuild_with_host_snapshot_schema"}
    sources = _distribution(db, "SELECT status,count(*) FROM host_sources GROUP BY 1")
    slots = db.execute("SELECT count(*) FROM host_actions").fetchone()[0]
    sessions, expired, revoked = db.execute(
        "SELECT count(*),sum(expired),sum(local_revoked) FROM host_sessions").fetchone()
    states = _distribution(db, "SELECT outcome,count(*) FROM host_actions GROUP BY 1")
    verified = sum(states.get(key, 0) for key in (
        "verified_simulated_intake", "verified_existing_simulated_intake", "verified_handoff_request"))
    prior = db.execute("SELECT sum(retained_prior_receipt),sum(retained_prior_handoff) FROM host_actions").fetchone()
    coverage = db.execute("SELECT sum(rejected_bindings),sum(invalid_sessions) FROM host_sources").fetchone()
    updated = db.execute("SELECT min(updated_at),max(updated_at) FROM host_actions").fetchone()
    created = db.execute("SELECT min(verified_record_created_at),max(verified_record_created_at) FROM host_actions").fetchone()
    cancelled = db.execute("SELECT count(*),min(cancelled_at),max(cancelled_at) FROM host_cancellations").fetchone()
    built = db.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
    return {
        "status": "available" if sources.get("supported") else "unavailable",
        "source": "persisted_frontend_host_projection",
        "grain": "one_latest_action_slot_per_owner_session_expiry; not_lifetime_action_counts",
        "workflow_attribution": "unknown; workflow_intent_outcomes_are_separate",
        "verification": "saved_host_readback_shape_checked; no_live_bank_read_or_recovery",
        "built_at": built[0] if built else None,
        "sources": sources,
        "denominators": {"admitted_session_snapshots": sessions, "current_action_slots": slots,
                         "rejected_binding_source_rows": coverage[0] or 0,
                         "invalid_session_source_rows": coverage[1] or 0},
        "outcomes": states,
        "verified_terminal_slot_rate": _rate(verified, slots),
        "time_coverage": {"action_updated_from": updated[0], "action_updated_through": updated[1],
                          "verified_record_created_from": created[0], "verified_record_created_through": created[1]},
        "retained_prior_evidence_slots": {"receipt": prior[0] or 0, "handoff": prior[1] or 0},
        "recovery": {"slots_with_attempts": db.execute(
            "SELECT count(*) FROM host_actions WHERE recovery_attempts>0").fetchone()[0],
            "exhausted_slots": db.execute(
                "SELECT count(*) FROM host_actions WHERE recovery_exhausted=1").fetchone()[0]},
        "lifecycle": {"expired_session_snapshots": expired or 0, "locally_revoked_session_snapshots": revoked or 0,
                      "revocation_states": _distribution(db,
                          "SELECT revocation_state,count(*) FROM host_sessions GROUP BY 1"),
                      "revocation_source_coverage": _distribution(db,
                          "SELECT revocation_status,count(*) FROM host_sources GROUP BY 1"),
                      "retained_cancelled_handles": cancelled[0],
                      "cancellation_source_coverage": _distribution(db,
                          "SELECT cancellation_status,count(*) FROM host_sources GROUP BY 1"),
                      "cancelled_from": cancelled[1], "cancelled_through": cancelled[2]},
    }


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
            "current_host_snapshot": _host_summary(db),
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
    section("Observación actual del host (separada de la intención del flujo)", summary["current_host_snapshot"])
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
