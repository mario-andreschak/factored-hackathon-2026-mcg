"""Offline agent analytics: projection, outcomes, privacy and read-only sources."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3

import pytest

from analytics.__main__ import main
from analytics.extract import add_feedback, build, discover
from analytics.report import summarize
from gloria_workflow.state import ConversationStore, TrustedBinding, begin_turn, new_state


NOW = datetime(2026, 10, 1, 15, 0, tzinfo=timezone.utc)
SECRET_VALUES = ("customer-secret-1", "customer-secret-2", "session-secret-1", "session-secret-2",
                 "no reconozco 87500", "87500", "Tienda General", "TRX-0003Y34IMGRAAKKVVQHR")


def _binding(index):
    return TrustedBinding(owner=f"owner-{index}", customer_id=f"customer-secret-{index}",
                          session_id=f"session-secret-{index}", conversation_id=f"conversation-{index}",
                          expires_at=NOW + timedelta(hours=1))


def _turn(store, binding, turn_id, *, minutes, previous=None, revision=0, **changes):
    now = NOW + timedelta(minutes=minutes)
    base = previous if previous is not None else new_state(binding, now=now)
    state = begin_turn(base, binding, turn_id=turn_id, user_question="no reconozco 87500", now=now)
    turn, workflow = state["turn"], state["workflow_state"]
    turn.update(intent="TRANSACTION_DISPUTE", language="es", effective_language="es",
                emotional_context=changes.pop("emotion", "Neutro"))
    turn["slots"].update(amount=87500, merchant="Tienda General")
    workflow["policy_decision"] = {"response_mode": changes.pop("mode"), "rule_ids": changes.pop("rules", ["R1"]),
                                   "requires_confirmation": False, "requires_human": False,
                                   "reason_code": changes.pop("reason", None)}
    for key, value in changes.pop("workflow", {}).items():
        workflow[key] = value
    state["trace"] += changes.pop("trace", [])
    state["tool_results"].update(changes.pop("tool_results", {}))
    state["runtime"]["node_errors"] += changes.pop("node_errors", [])
    state["runtime"]["safe_fallback_used"] = changes.pop("fallback", False)
    state["response"].update(message="respuesta", data_sources=["transactions"])
    assert not changes
    store.save_turn(binding, turn_id, state, expected_revision=revision, now=now)
    return store.load(binding, now=now)


@pytest.fixture
def state_dir(tmp_path):
    store = ConversationStore(tmp_path / "gloria-workflow.sqlite3")
    first = _binding(1)
    loaded = _turn(store, first, "turn-a1", minutes=0, mode="CLARIFY",
        workflow={"missing_fields": ["date_from"]},
        trace=[{"node": "detect_context", "turn_id": "turn-a1", "latency_ms": 900, "model": "m"},
               {"node": "slot_extraction", "turn_id": "turn-a1", "latency_ms": 1500, "model": "m"},
               {"node": "search_transactions", "turn_id": "turn-a1", "latency_ms": 40, "attempts": 2},
               {"node": "merge_parallel", "turn_id": "turn-a1", "branches": []}],
        tool_results={"search_transactions": {"status": "ok", "candidates": [{"transaction_id": "TRX-0003Y34IMGRAAKKVVQHR"}]}},
        node_errors=[{"node": "slot_extraction", "code": "schema_invalid"}])
    _turn(store, first, "turn-a2", minutes=1, previous=loaded, revision=1, mode="ACTION_DONE", rules=["R3"],
        workflow={"transaction_identified": True, "transaction_id": "TRX-0003Y34IMGRAAKKVVQHR",
                  "action_outcome": "verified",
                  "action": {"name": "CREATE_COMPLAINT", "authorized": True, "executed": True, "verified": True,
                             "result_id": "CMP-1", "error": None, "idempotency_key": None,
                             "authorization_expires_at": None}},
        trace=[{"node": "generator", "turn_id": "turn-a2", "latency_ms": 2100, "model": "m"}])
    _turn(store, _binding(2), "turn-b1", minutes=2, mode="HANDOFF", reason="high_risk", emotion="Frustración",
        workflow={"handoff": {"required": True, "created": True, "handoff_id": "H-1", "reason_code": "high_risk"}},
        trace=[{"node": "search_transactions", "turn_id": "turn-b1", "latency_ms": 20000, "attempts": 3}],
        tool_results={"search_transactions": {"status": "error", "code": "tool_unavailable"}},
        node_errors=[{"node": "search_transactions", "code": "tool_unavailable", "exhausted": True}], fallback=True)

    with closing(sqlite3.connect(tmp_path / "frontend-chat.sqlite3")) as db, db:
        db.execute("""CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
            expires INTEGER NOT NULL, conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
            active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0, subject TEXT, customer_id TEXT)""")
        db.execute("""CREATE TABLE chat_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            operation TEXT NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL, selection_json TEXT,
            UNIQUE(session_id, operation, role))""")
        db.executemany("INSERT INTO chat_sessions(session_id,owner,expires,conversation_id,customer_id) VALUES (?,?,?,?,?)",
            [("session-secret-1", "owner-1", 0, "conversation-1", "customer-secret-1"),
             ("session-secret-3", "owner-3", 0, "conversation-3", "customer-secret-1")])
        db.executemany("INSERT INTO chat_messages(session_id,operation,role,text) VALUES (?,?,?,?)",
            [("session-secret-1", "turn-a1", "user", "no reconozco 87500"),
             ("session-secret-1", "turn-a1", "assistant", "¿En qué fecha?"),
             ("session-secret-3", "op-flujo", "user", "hola"),
             ("session-secret-3", "op-flujo", "assistant", "Hola, ¿en qué te ayudo?")])
    return tmp_path


def _built(state_dir, tmp_path_factory):
    out = tmp_path_factory.mktemp("analytics") / "agent-analytics.sqlite3"
    workflow, chat = discover(state_dir)
    counts = build(out, workflow_dbs=workflow, chat_dbs=chat, now=NOW)
    return out, counts


def _rows(out, sql, *args):
    with closing(sqlite3.connect(out)) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, args)]


def test_discovers_sources_and_projects_each_turn(state_dir, tmp_path_factory):
    assert [path.name for path in discover(state_dir)[0]] == ["gloria-workflow.sqlite3"]
    out, counts = _built(state_dir, tmp_path_factory)
    assert counts == {"turns": 4, "conversations": 3, "node_calls": 6, "skipped_states": 0}
    turn = _rows(out, "SELECT * FROM turns WHERE turn_id='turn-a1'")[0]
    assert turn["source"] == "workflow" and turn["turn_index"] == 1
    assert turn["response_mode"] == "CLARIFY" and turn["intent"] == "TRANSACTION_DISPUTE"
    assert json.loads(turn["slots_present"]) == ["amount", "merchant"]
    assert json.loads(turn["missing_fields"]) == ["date_from"]
    assert json.loads(turn["node_errors"]) == ["slot_extraction:schema_invalid"]
    assert turn["user_chars"] == len("no reconozco 87500") and turn["reply_chars"] == len("¿En qué fecha?")
    assert turn["node_latency_ms"] == 900 + 1500 + 40


def test_trace_is_attributed_only_to_its_own_turn(state_dir, tmp_path_factory):
    out, _ = _built(state_dir, tmp_path_factory)
    calls = _rows(out, "SELECT turn_id,node,kind,status,error_code,attempts FROM node_calls ORDER BY turn_id,seq")
    assert [(call["turn_id"], call["node"]) for call in calls if call["turn_id"] == "turn-a2"] == [("turn-a2", "generator")]
    by_node = {(call["turn_id"], call["node"]): call for call in calls}
    assert by_node[("turn-a1", "slot_extraction")]["status"] == "error"
    assert by_node[("turn-a1", "detect_context")]["status"] == "ok"
    assert by_node[("turn-a1", "search_transactions")] == {"turn_id": "turn-a1", "node": "search_transactions",
        "kind": "tool", "status": "ok", "error_code": None, "attempts": 2}
    assert by_node[("turn-a1", "merge_parallel")]["kind"] == "barrier"
    assert by_node[("turn-b1", "search_transactions")]["error_code"] == "tool_unavailable"


def test_conversation_outcomes(state_dir, tmp_path_factory):
    out, _ = _built(state_dir, tmp_path_factory)
    conversations = {row["conversation_id"]: row for row in _rows(out, "SELECT * FROM conversations")}
    assert conversations["conversation-1"]["outcome"] == "action_verified"
    assert conversations["conversation-1"]["n_turns"] == 2
    assert conversations["conversation-1"]["turns_to_identify"] == 2
    assert conversations["conversation-1"]["clarify_turns"] == 1
    assert conversations["conversation-2"]["outcome"] == "handoff"
    assert conversations["conversation-2"]["handoff_reason"] == "high_risk"
    assert conversations["conversation-2"]["any_fallback"] == 1
    assert conversations["conversation-3"]["outcome"] == "transcript_only"
    # One pseudonym per customer across conversations, unlinkable without the key file.
    assert conversations["conversation-1"]["customer_ref"] == conversations["conversation-3"]["customer_ref"]
    assert conversations["conversation-1"]["customer_ref"] != conversations["conversation-2"]["customer_ref"]


def test_output_contains_no_content_or_raw_identity(state_dir, tmp_path_factory):
    out, _ = _built(state_dir, tmp_path_factory)
    with closing(sqlite3.connect(out)) as db:
        dump = "\n".join(db.iterdump())
    for value in SECRET_VALUES:
        assert value not in dump
    assert hashlib.sha256(b"customer-secret-1").hexdigest()[:20] not in dump
    assert out.with_suffix(".key").exists()


def test_sources_are_unchanged_and_output_must_be_separate(state_dir, tmp_path_factory):
    before = {path.name: path.read_bytes() for path in state_dir.glob("*.sqlite3")}
    _built(state_dir, tmp_path_factory)
    assert {path.name: path.read_bytes() for path in state_dir.glob("*.sqlite3")} == before
    with pytest.raises(ValueError):
        build(state_dir / "gloria-workflow.sqlite3", workflow_dbs=[state_dir / "gloria-workflow.sqlite3"])


def test_rebuild_is_idempotent_and_keeps_feedback(state_dir, tmp_path_factory):
    out, _ = _built(state_dir, tmp_path_factory)
    add_feedback(out, source="reviewer", turn_id="turn-a1", rating=-1, label="slot_missed", now=NOW)
    workflow, chat = discover(state_dir)
    build(out, workflow_dbs=workflow, chat_dbs=chat, now=NOW)
    assert _rows(out, "SELECT count(*) AS n FROM turns")[0]["n"] == 4
    assert _rows(out, "SELECT turn_id,rating,label FROM feedback") == [
        {"turn_id": "turn-a1", "rating": -1, "label": "slot_missed"}]


def test_report_indicators(state_dir, tmp_path_factory):
    out, _ = _built(state_dir, tmp_path_factory)
    add_feedback(out, source="customer", conversation_id="conversation-1", rating=1, now=NOW)
    summary = summarize(out)
    assert summary["volume"] == {"conversations": 3, "workflow_conversations": 2, "workflow_turns": 3,
                                 "transcript_only_turns": 1}
    assert summary["containment_rate"] == 0.5
    assert summary["outcomes"] == {"action_verified": 1, "handoff": 1, "transcript_only": 1}
    assert summary["handoff_reasons"] == {"high_risk": 1}
    assert summary["turn_rates"]["clarify"] == round(1 / 3, 4)
    assert summary["nodes"]["search_transactions"]["retry_rate"] == 1.0
    assert summary["nodes"]["search_transactions"]["error_rate"] == 0.5
    assert summary["error_codes"] == {"search_transactions:tool_unavailable": 1,
                                      "slot_extraction:schema_invalid": 1}
    assert summary["feedback"]["positive"] == 1


def test_cli_build_report_and_feedback(state_dir, tmp_path, capsys):
    out = tmp_path / "cli" / "agent-analytics.sqlite3"
    assert main(["build", "--state-dir", str(state_dir), "--out", str(out)]) == 0
    assert json.loads(capsys.readouterr().out)["turns"] == 4
    assert main(["feedback", "--db", str(out), "--turn", "turn-b1", "--label", "handoff_correct"]) == 0
    capsys.readouterr()
    assert main(["report", "--db", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Tasa de contención (sin handoff): 0.5" in text and "handoff_correct: 1" in text


@pytest.mark.parametrize("last,expected", [
    ({"response_mode": "CONFIRM_ACTION", "pending_type": "awaiting_confirmation"}, "awaiting_confirmation"),
    ({"response_mode": "CLARIFY", "pending_type": "awaiting_selection"}, "abandoned_pending"),
    ({"response_mode": "TOOL_ERROR", "pending_type": "none"}, "tool_error"),
    ({"response_mode": "OUT_OF_SCOPE", "pending_type": "none"}, "out_of_scope"),
    ({"response_mode": "CLARIFY", "pending_type": "none"}, "abandoned_clarify"),
])
def test_outcome_of_last_turn(last, expected):
    from analytics.extract import conversation_record
    turn = {"turn_id": "t", "turn_index": 1, "source": "workflow", "node_errors": "[]", **last}
    assert conversation_record("c", [turn])["outcome"] == expected
