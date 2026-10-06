"""Build a metadata-only analytics database from Savia transaction dispute operational state.

Sources are opened read-only. The output keeps categories, counts, flags and
durations; it never copies message text, slot values, amounts, merchants,
transaction or complaint identifiers. Customer and session identifiers are
replaced by an HMAC pseudonym whose key lives beside the output, never in it.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Iterable

from .host import SCHEMA as HOST_SCHEMA, snapshots


SCHEMA_VERSION = "2"

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS turns (
    turn_id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK(source IN ('workflow','transcript')),
    conversation_id TEXT, session_ref TEXT, customer_ref TEXT,
    ts TEXT, turn_index INTEGER,
    language TEXT, effective_language TEXT, emotional_context TEXT,
    intent TEXT, n_intents INTEGER, n_sub_queries INTEGER, n_query_scopes INTEGER,
    attack_deceptive INTEGER, attack_inappropriate INTEGER,
    human_requested INTEGER, unauthorized_reference INTEGER,
    slots_present TEXT, clarification_type TEXT,
    pending_type TEXT, pending_candidates INTEGER, turns_waiting INTEGER,
    response_mode TEXT, rule_ids TEXT, reason_code TEXT,
    requires_confirmation INTEGER, requires_human INTEGER,
    transaction_identified INTEGER, transaction_unique INTEGER,
    existing_case_found INTEGER, missing_fields TEXT,
    action_name TEXT, action_attempted INTEGER, action_executed INTEGER,
    action_verified INTEGER, action_outcome TEXT,
    handoff_required INTEGER, handoff_created INTEGER, handoff_reason TEXT,
    clarification_attempts INTEGER, no_match_attempts INTEGER, tool_failures INTEGER,
    grounding_violation INTEGER, safe_fallback_used INTEGER, validation_attempts INTEGER,
    data_sources TEXT, node_errors TEXT, node_latency_ms INTEGER,
    user_chars INTEGER, reply_chars INTEGER, policy_version TEXT
);
CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation_id, turn_index);
CREATE TABLE IF NOT EXISTS node_calls (
    turn_id TEXT NOT NULL, seq INTEGER NOT NULL, node TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('model_stage','tool','policy_retrieval','barrier')),
    latency_ms INTEGER, attempts INTEGER, model TEXT, status TEXT, error_code TEXT,
    PRIMARY KEY(turn_id, seq)
);
CREATE INDEX IF NOT EXISTS node_calls_node ON node_calls(node);
CREATE TABLE IF NOT EXISTS conversations (
    conversation_id TEXT PRIMARY KEY, session_ref TEXT, customer_ref TEXT,
    started_at TEXT, ended_at TEXT, n_turns INTEGER NOT NULL,
    languages TEXT, intents TEXT, final_response_mode TEXT, outcome TEXT NOT NULL,
    handoff_reason TEXT, turns_to_identify INTEGER, clarify_turns INTEGER,
    any_fallback INTEGER, any_attack INTEGER, any_node_error INTEGER
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_id TEXT, conversation_id TEXT,
    source TEXT NOT NULL CHECK(source IN ('customer','reviewer')),
    rating INTEGER CHECK(rating IS NULL OR rating IN (-1, 0, 1)),
    label TEXT, created_at TEXT NOT NULL,
    CHECK(turn_id IS NOT NULL OR conversation_id IS NOT NULL)
);
""" + HOST_SCHEMA

_BARRIERS = frozenset({"merge_parallel", "query_preflight_barrier"})
_INFORMED = frozenset({"INFORM", "INFORM_EXISTING_CASE", "COMPLAINT_STATUS", "SMALL_TALK"})
_TERMINAL = {"NO_MATCH": "no_match", "OUT_OF_SCOPE": "out_of_scope", "OUT_OF_POLICY": "out_of_policy",
             "TOOL_ERROR": "tool_error", "ACTION_UNVERIFIED": "action_unverified",
             "ACTION_CANCELLED": "cancelled"}
TURN_COLUMNS = (
    "turn_id", "source", "conversation_id", "session_ref", "customer_ref", "ts", "turn_index",
    "language", "effective_language", "emotional_context", "intent", "n_intents", "n_sub_queries",
    "n_query_scopes", "attack_deceptive", "attack_inappropriate", "human_requested",
    "unauthorized_reference", "slots_present", "clarification_type", "pending_type",
    "pending_candidates", "turns_waiting", "response_mode", "rule_ids", "reason_code",
    "requires_confirmation", "requires_human", "transaction_identified", "transaction_unique",
    "existing_case_found", "missing_fields", "action_name", "action_attempted", "action_executed",
    "action_verified", "action_outcome", "handoff_required", "handoff_created", "handoff_reason",
    "clarification_attempts", "no_match_attempts", "tool_failures", "grounding_violation",
    "safe_fallback_used", "validation_attempts", "data_sources", "node_errors", "node_latency_ms",
    "user_chars", "reply_chars", "policy_version")


class Pseudonymizer:
    """Installation-local HMAC; the key file is never written to the output."""

    def __init__(self, key_path: Path):
        if not key_path.exists():
            key_path.parent.mkdir(parents=True, exist_ok=True)
            key_path.write_text(secrets.token_hex(32), encoding="ascii")
        self._key = bytes.fromhex(key_path.read_text(encoding="ascii").strip())

    def __call__(self, kind: str, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return hmac.new(self._key, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:20]


def _readonly(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    db.row_factory = sqlite3.Row
    return db


def _tables(path: Path) -> set[str]:
    try:
        with closing(_readonly(path)) as db:
            return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.DatabaseError:
        return set()


_WORKFLOW_TABLES = ("dispute_turns", "gloria_turns")


def _workflow_table(tables: set[str]) -> str | None:
    return next((table for table in _WORKFLOW_TABLES if table in tables), None)


def discover(state_dir: Path) -> tuple[list[Path], list[Path]]:
    """Find current or legacy workflow stores and chat stores."""
    workflow, chat = [], []
    for path in sorted(Path(state_dir).glob("*.sqlite3")):
        tables = _tables(path)
        if _workflow_table(tables):
            workflow.append(path)
        if "chat_messages" in tables:
            chat.append(path)
    return workflow, chat


def _flag(value: Any) -> int | None:
    if value is None:
        return None
    return 1 if value is True or (type(value) in (int, float) and value > 0) else 0


def _int(value: Any) -> int | None:
    return value if type(value) is int else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _names(values: Any) -> str | None:
    if not isinstance(values, list):
        return None
    return json.dumps(sorted({item for item in values if isinstance(item, str)}))


def _node_kind(entry: dict) -> str:
    node = entry.get("node")
    if node in _BARRIERS:
        return "barrier"
    if node == "retrieve_policy":
        return "policy_retrieval"
    return "tool" if "attempts" in entry else "model_stage"


def turn_record(state: dict, turn_id: str) -> tuple[dict, list[dict]]:
    """Project one persisted ChatState onto allowlisted, non-content columns."""
    turn = state.get("turn") or {}
    workflow = state.get("workflow_state") or {}
    runtime = state.get("runtime") or {}
    response = state.get("response") or {}
    pending = workflow.get("pending") or {}
    decision = workflow.get("policy_decision") or {}
    action = workflow.get("action") or {}
    handoff = workflow.get("handoff") or {}
    counters = workflow.get("counters") or {}
    attack = turn.get("attack") or {}
    slots = turn.get("slots") or {}
    errors = [item for item in runtime.get("node_errors") or [] if isinstance(item, dict)]
    error_by_node = {}
    for item in errors:
        error_by_node.setdefault(item.get("node"), item.get("code"))
    tool_results = state.get("tool_results") or {}
    calls = []
    for entry in state.get("trace") or []:
        if not isinstance(entry, dict) or entry.get("turn_id") != turn_id or not _text(entry.get("node")):
            continue
        node, kind = entry["node"], _node_kind(entry)
        status, code = None, None
        if kind == "tool":
            result = tool_results.get(node) if isinstance(tool_results.get(node), dict) else {}
            status = _text(result.get("status"))
            code = _text(result.get("code")) if status == "error" else None
        elif kind != "barrier":
            code = _text(error_by_node.get(node))
            status = "error" if code else "ok"
        calls.append({"seq": len(calls), "node": node, "kind": kind,
                      "latency_ms": _int(entry.get("latency_ms")), "attempts": _int(entry.get("attempts")),
                      "model": _text(entry.get("model")), "status": status, "error_code": code})
    latencies = [call["latency_ms"] for call in calls if call["latency_ms"] is not None]
    scopes = runtime.get("query_scopes")
    record = {
        "turn_id": turn_id, "source": "workflow", "ts": _text(turn.get("current_timestamp")),
        "language": _text(turn.get("language")), "effective_language": _text(turn.get("effective_language")),
        "emotional_context": _text(turn.get("emotional_context")), "intent": _text(turn.get("intent")),
        "n_intents": len(turn["intents"]) if isinstance(turn.get("intents"), list) else None,
        "n_sub_queries": len(turn["sub_queries"]) if isinstance(turn.get("sub_queries"), list) else None,
        "n_query_scopes": len(scopes) if isinstance(scopes, dict) else 0,
        "attack_deceptive": _flag(attack.get("deceptive")),
        "attack_inappropriate": _flag(attack.get("inappropriate")),
        "human_requested": _flag(turn.get("human_requested")),
        "unauthorized_reference": _flag(turn.get("unauthorized_reference")),
        # Which fields the customer supplied, never their values.
        "slots_present": json.dumps(sorted(key for key, value in slots.items()
                                           if value is not None and value is not False)),
        "clarification_type": _text((turn.get("clarification") or {}).get("resolution_type")),
        "pending_type": _text(pending.get("type")),
        "pending_candidates": len(pending["candidates"]) if isinstance(pending.get("candidates"), list) else None,
        "turns_waiting": _int(pending.get("turns_waiting")),
        "response_mode": _text(decision.get("response_mode")),
        "rule_ids": _names(decision.get("rule_ids")),
        "reason_code": _text(decision.get("reason_code")),
        "requires_confirmation": _flag(decision.get("requires_confirmation")),
        "requires_human": _flag(decision.get("requires_human")),
        "transaction_identified": _flag(workflow.get("transaction_identified")),
        "transaction_unique": _flag(workflow.get("transaction_unique")),
        "existing_case_found": _flag((workflow.get("existing_case") or {}).get("found")),
        "missing_fields": _names(workflow.get("missing_fields")),
        "action_name": _text(action.get("name")), "action_attempted": _flag(workflow.get("action_attempted")),
        "action_executed": _flag(action.get("executed")), "action_verified": _flag(action.get("verified")),
        "action_outcome": _text(workflow.get("action_outcome")),
        "handoff_required": _flag(handoff.get("required")), "handoff_created": _flag(handoff.get("created")),
        "handoff_reason": _text(handoff.get("reason_code")),
        "clarification_attempts": _int(counters.get("clarification_attempts")),
        "no_match_attempts": _int(counters.get("no_match_attempts")),
        "tool_failures": _int(counters.get("tool_failures")),
        "grounding_violation": _flag(response.get("grounding_violation")),
        "safe_fallback_used": _flag(runtime.get("safe_fallback_used")),
        "validation_attempts": _int(turn.get("validation_attempts")),
        "data_sources": _names(response.get("data_sources")),
        "node_errors": json.dumps(sorted({f"{item.get('node')}:{item.get('code')}" for item in errors})),
        # Nodes can run in parallel; this is work time, not wall-clock time.
        "node_latency_ms": sum(latencies) if latencies else None,
        "policy_version": _text(runtime.get("policy_version")),
    }
    return record, calls


def _outcome(turns: list[dict]) -> tuple[str, str | None]:
    reasons = [turn["handoff_reason"] for turn in turns if turn.get("handoff_required") and turn.get("handoff_reason")]
    if any(turn.get("action_verified") or turn.get("action_outcome") == "verified" for turn in turns):
        return "action_verified", None
    if any(turn.get("handoff_created") for turn in turns):
        return "handoff", reasons[-1] if reasons else None
    if any(turn.get("handoff_required") for turn in turns):
        return "handoff_required", reasons[-1] if reasons else None
    last = turns[-1]
    if last.get("source") == "transcript":
        return "transcript_only", None
    if last.get("pending_type") == "awaiting_confirmation":
        # Consent happens in the portal, outside chat; the chat ends here.
        return "awaiting_confirmation", None
    if last.get("pending_type") not in (None, "none"):
        return "abandoned_pending", None
    if any(turn.get("response_mode") == "BLOCKED" for turn in turns):
        return "blocked", None
    if last.get("response_mode") in _TERMINAL:
        return _TERMINAL[last["response_mode"]], None
    if last.get("response_mode") in _INFORMED:
        return "informed", None
    if last.get("response_mode") == "CLARIFY":
        return "abandoned_clarify", None
    return "other", None


def conversation_record(conversation_id: str, turns: list[dict]) -> dict:
    turns = sorted(turns, key=lambda turn: (turn.get("turn_index") or 0))
    outcome, reason = _outcome(turns)
    identified = next((turn["turn_index"] for turn in turns if turn.get("transaction_identified")), None)
    return {
        "conversation_id": conversation_id, "session_ref": turns[0].get("session_ref"),
        "customer_ref": turns[0].get("customer_ref"),
        "started_at": turns[0].get("ts"), "ended_at": turns[-1].get("ts"), "n_turns": len(turns),
        "languages": json.dumps(sorted({turn["effective_language"] for turn in turns if turn.get("effective_language")})),
        "intents": json.dumps(sorted({turn["intent"] for turn in turns if turn.get("intent")})),
        "final_response_mode": turns[-1].get("response_mode"), "outcome": outcome, "handoff_reason": reason,
        "turns_to_identify": identified,
        "clarify_turns": sum(1 for turn in turns if turn.get("response_mode") == "CLARIFY"),
        "any_fallback": int(any(turn.get("safe_fallback_used") for turn in turns)),
        "any_attack": int(any(turn.get("attack_deceptive") or turn.get("attack_inappropriate") for turn in turns)),
        "any_node_error": int(any(turn.get("node_errors") not in (None, "[]") for turn in turns)),
    }


def _workflow_rows(path: Path) -> Iterable[sqlite3.Row]:
    with closing(_readonly(path)) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        table = _workflow_table(tables)
        if table is None:
            raise ValueError(f"no transaction dispute turn table found in {path}")
        # The table name comes only from the fixed allowlist above.
        yield from db.execute(f"SELECT customer,session,conversation,turn_id,state_json FROM {table}")


def _chat_rows(path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    """Return per-operation message sizes and per-session identity, never text."""
    operations: dict[str, dict] = {}
    sessions: dict[str, dict] = {}
    with closing(_readonly(path)) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(chat_sessions)")}
        if columns:
            customer = "customer_id" if "customer_id" in columns else "NULL"
            for row in db.execute(f"SELECT session_id,conversation_id,{customer} AS customer_id FROM chat_sessions"):
                sessions[row["session_id"]] = dict(row)
        for row in db.execute("SELECT session_id,operation,role,length(text) AS chars,id FROM chat_messages ORDER BY id"):
            entry = operations.setdefault(row["operation"], {"session_id": row["session_id"], "order": row["id"]})
            entry["user_chars" if row["role"] == "user" else "reply_chars"] = row["chars"]
    return operations, sessions


def build(out_path: Path, *, workflow_dbs: Iterable[Path] = (), chat_dbs: Iterable[Path] = (),
          key_path: Path | None = None, now: datetime | None = None) -> dict[str, int]:
    """Rebuild derived tables from the given sources; reviewer feedback is kept."""
    out_path = Path(out_path).resolve()
    workflow_dbs = sorted({Path(path).resolve() for path in workflow_dbs})
    chat_dbs = sorted({Path(path).resolve() for path in chat_dbs})
    if out_path in workflow_dbs or out_path in chat_dbs:
        raise ValueError("the analytics output must be a separate database")
    pseudonym = Pseudonymizer(key_path or out_path.with_suffix(".key"))
    built_at = now or datetime.now(timezone.utc)
    host_tables = snapshots(chat_dbs, pseudonym, built_at)
    operations: dict[str, dict] = {}
    sessions: dict[str, dict] = {}
    for path in chat_dbs:
        found_operations, found_sessions = _chat_rows(path)
        operations.update(found_operations)
        sessions.update(found_sessions)

    turns: dict[str, dict] = {}
    calls: dict[str, list[dict]] = {}
    skipped = 0
    for path in workflow_dbs:
        for row in _workflow_rows(path):
            try:
                state = json.loads(row["state_json"])
                record, node_calls = turn_record(state, row["turn_id"])
            except (ValueError, TypeError, AttributeError):
                skipped += 1
                continue
            record.update(conversation_id=row["conversation"], session_ref=pseudonym("session", row["session"]),
                          customer_ref=pseudonym("customer", row["customer"]))
            turns[row["turn_id"]] = record
            calls[row["turn_id"]] = node_calls
    for operation, entry in operations.items():
        record = turns.get(operation)
        if record is None:
            # Transcript-only turn, e.g. a FLUJO-mode chat without transaction dispute workflow state.
            session = sessions.get(entry["session_id"], {})
            record = turns[operation] = {
                "turn_id": operation, "source": "transcript",
                "conversation_id": session.get("conversation_id") or f"session:{pseudonym('session', entry['session_id'])}",
                "session_ref": pseudonym("session", entry["session_id"]),
                "customer_ref": pseudonym("customer", session.get("customer_id")), "_order": entry["order"]}
        record["user_chars"] = entry.get("user_chars")
        record["reply_chars"] = entry.get("reply_chars")
        # Message order breaks ties between turns stamped in the same instant.
        record["_order"] = entry["order"]

    by_conversation: dict[str, list[dict]] = {}
    for record in turns.values():
        by_conversation.setdefault(record["conversation_id"], []).append(record)
    for items in by_conversation.values():
        items.sort(key=lambda item: (item.get("ts") or "", item.get("_order") or 0, item["turn_id"]))
        for index, item in enumerate(items, start=1):
            item["turn_index"] = index

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(out_path, timeout=10)) as db, db:
        db.executescript(SCHEMA)
        db.execute("DELETE FROM node_calls")
        db.execute("DELETE FROM turns")
        db.execute("DELETE FROM conversations")
        for table, records in zip(("host_sources", "host_sessions", "host_actions", "host_cancellations"), host_tables):
            db.execute(f"DELETE FROM {table}")
            columns = tuple(row[1] for row in db.execute(f"PRAGMA table_info({table})"))
            db.executemany(f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                           [tuple(record.get(column) for column in columns) for record in records])
        placeholders = ",".join("?" for _ in TURN_COLUMNS)
        db.executemany(f"INSERT INTO turns({','.join(TURN_COLUMNS)}) VALUES ({placeholders})",
                       [tuple(record.get(column) for column in TURN_COLUMNS) for record in turns.values()])
        db.executemany("""INSERT INTO node_calls(turn_id,seq,node,kind,latency_ms,attempts,model,status,error_code)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            [(turn_id, call["seq"], call["node"], call["kind"], call["latency_ms"], call["attempts"],
              call["model"], call["status"], call["error_code"])
             for turn_id, items in calls.items() for call in items])
        conversations = [conversation_record(key, items) for key, items in by_conversation.items()]
        if conversations:
            columns = tuple(conversations[0])
            db.executemany(f"INSERT INTO conversations({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                           [tuple(item[column] for column in columns) for item in conversations])
        built = built_at.isoformat().replace("+00:00", "Z")
        db.executemany("INSERT INTO meta VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       [("schema_version", SCHEMA_VERSION), ("built_at", built)])
    return {"turns": len(turns), "conversations": len(by_conversation),
            "node_calls": sum(len(items) for items in calls.values()), "skipped_states": skipped}


def add_feedback(out_path: Path, *, source: str, turn_id: str | None = None,
                 conversation_id: str | None = None, rating: int | None = None,
                 label: str | None = None, now: datetime | None = None) -> int:
    """Record a customer or reviewer judgement; it survives later rebuilds."""
    if label is not None and (not label.strip() or len(label) > 120):
        raise ValueError("label must be 1-120 characters")
    created = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    with closing(sqlite3.connect(Path(out_path), timeout=10)) as db, db:
        db.executescript(SCHEMA)
        cursor = db.execute("""INSERT INTO feedback(turn_id,conversation_id,source,rating,label,created_at)
            VALUES (?,?,?,?,?,?)""", (turn_id, conversation_id, source, rating, label, created))
        return cursor.lastrowid
