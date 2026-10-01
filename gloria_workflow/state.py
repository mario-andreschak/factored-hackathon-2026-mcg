"""Canonical internal ChatState and owner-bound durable conversation storage.

Only trusted application code constructs bindings and installs host consent.
Neither this module nor the policy engine executes a banking action.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    _CLIENT_TIMEZONE = ZoneInfo("America/Bogota")
except ZoneInfoNotFoundError:
    # Current Colombian civil time is fixed UTC-5. Windows Python installations
    # need not have a system IANA database; do not depend on the host timezone.
    _CLIENT_TIMEZONE = timezone(timedelta(hours=-5), "America/Bogota")


SLOT_KEYS = ("amount", "currency", "currency_raw", "date_from", "date_to",
             "date_expression", "merchant", "transaction_type", "channel", "city",
             "country", "transaction_id", "complaint_id", "product_hint", "product_last4",
             "amount_is_approximate", "foreign_customer_reference")


class StateError(ValueError):
    """A fixed, non-sensitive state or binding validation failure."""


class RevisionConflict(StateError):
    pass


class ReplayConflict(StateError):
    pass


def utc_now(now: datetime | None = None) -> datetime:
    value = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise StateError("aware_timestamp_required")
    return value.astimezone(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    try:
        if isinstance(value, datetime):
            return utc_now(value)
        if type(value) in (int, float) and math.isfinite(value):
            return datetime.fromtimestamp(value, timezone.utc)
        if isinstance(value, str):
            return utc_now(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except (ValueError, OverflowError, OSError):
        pass
    return None


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class TrustedBinding:
    customer_id: str
    session_id: str
    conversation_id: str
    owner: str
    expires_at: Any
    authenticated: bool = True

    def __post_init__(self) -> None:
        for value in (self.owner, self.customer_id, self.session_id, self.conversation_id):
            if not isinstance(value, str) or not value or len(value) > 512:
                raise StateError("invalid_trusted_binding")
        if type(self.authenticated) is not bool or parse_timestamp(self.expires_at) is None:
            raise StateError("invalid_trusted_binding")

    def key(self) -> tuple[str, str, str, str]:
        return self.owner, self.customer_id, self.session_id, self.conversation_id

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.key(), separators=(",", ":")).encode()).hexdigest()

    def expired(self, now: datetime) -> bool:
        return now >= parse_timestamp(self.expires_at)

    def session(self, now: datetime) -> dict:
        return {"customer_id": self.customer_id, "session_id": self.session_id,
                "conversation_id": self.conversation_id,
                "authenticated": self.authenticated, "expired": self.expired(now)}


def empty_pending() -> dict:
    return {"type": "none", "candidates": [], "proposed_action": None,
            "target_transaction_id": None, "turns_waiting": 0, "created_turn_id": None,
            "intent": None, "candidate_type": "transaction", "snapshot_hash": None,
            "snapshot_id": None, "host_pending_handle": None, "request_id": None}


def empty_confirmation() -> dict:
    return {"verified": False, "source": None, "pending_handle": None, "request_id": None,
            "bound_identity_verified": False, "bound_action_target_snapshot_verified": False,
            "verified_at": None, "expires_at": None}


def empty_workflow() -> dict:
    return {"pending": empty_pending(), "transaction_identified": False,
            "transaction_unique": False, "transaction_id": None,
            "existing_case": {"found": False, "complaint_id": None, "status": None},
            "missing_fields": [], "policy_decision": {},
            "action": {"name": None, "authorized": False, "executed": False,
                       "verified": False, "result_id": None, "error": None,
                       "idempotency_key": None, "authorization_expires_at": None},
            "trusted_confirmation": empty_confirmation(),
            "handoff": {"required": False, "created": False, "handoff_id": None,
                        "reason_code": None},
            "counters": {"clarification_attempts": 0, "no_match_attempts": 0,
                         "tool_failures": 0, "last_counted_turn_id": None},
            "action_attempted": False, "action_outcome": "none",
            "search_criteria_present": False, "complaint_match_count": 0,
            "candidate_snapshot_hash": None, "confirmation_turn_id": None,
            "unrecognized_count_24h": None, "risk_data_complete": False,
            "handoff_attempted": False}


def new_state(binding: TrustedBinding, *, now: datetime | None = None) -> dict:
    current = utc_now(now)
    return {"session": binding.session(current),
            "turn": {"user_question": "", "clean_query": "", "sub_queries": [],
                     "language": "other", "effective_language": "es",
                     "emotional_context": "Neutro", "attack": {"inappropriate": 0, "deceptive": 0},
                     "intent": None, "slots": {key: False if key in (
                         "amount_is_approximate", "foreign_customer_reference") else None
                         for key in SLOT_KEYS},
                     "clarification": {"resolution_type": None, "selected_ref": None},
                     "current_date": current.astimezone(_CLIENT_TIMEZONE).date().isoformat(),
                     "current_timestamp": _iso(current), "turn_id": None,
                     "human_requested": False, "unauthorized_reference": False,
                     "intents": [], "active_query_index": 0,
                     "validation_errors": [], "validation_attempts": 0},
            "workflow_state": empty_workflow(), "tool_results": {}, "trace": [],
            "response": {"message": "", "language": "es", "arquetipos": [],
                         "chunk_ids": [], "data_sources": [], "grounding_violation": 0},
            "runtime": {"node_errors": [], "policy_version": None, "workflow_id": None,
                        "safe_fallback_used": False, "store_revision": 0,
                        "trusted_binding_digest": binding.digest(),
                        "session_expires_at": _iso(parse_timestamp(binding.expires_at)),
                        "pending_created_at": None, "pending_expires_at": None}}


def _assert_session(binding: TrustedBinding, state: dict) -> None:
    session = state.get("session", {})
    if any(session.get(key) != getattr(binding, key)
           for key in ("customer_id", "session_id", "conversation_id")):
        raise StateError("state_binding_mismatch")
    digest = state.get("runtime", {}).get("trusted_binding_digest")
    if digest is not None and digest != binding.digest():
        raise StateError("state_binding_mismatch")


def _merge(destination: dict, patch: dict) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(destination.get(key), dict):
            _merge(destination[key], value)
        else:
            destination[key] = deepcopy(value)


def cancel_pending(state: dict, *, clear_target: bool = False) -> dict:
    result = deepcopy(state)
    workflow = result["workflow_state"]
    workflow["pending"] = empty_pending()
    workflow["trusted_confirmation"] = empty_confirmation()
    workflow["action"]["authorized"] = False
    workflow["action"]["authorization_expires_at"] = None
    result["runtime"]["pending_created_at"] = None
    result["runtime"]["pending_expires_at"] = None
    if clear_target:
        workflow.update(transaction_identified=False, transaction_unique=False,
                        transaction_id=None, candidate_snapshot_hash=None)
        workflow["existing_case"] = {"found": False, "complaint_id": None, "status": None}
    return result


def reset_workflow(state: dict) -> dict:
    """Start a distinct request; uncertain writes must first be recovered by the host."""
    if state["workflow_state"].get("action_outcome") in {"unknown", "executed"}:
        raise StateError("action_recovery_required")
    result = cancel_pending(state, clear_target=True)
    result["workflow_state"] = empty_workflow()
    result["runtime"].pop("tool_attempts", None)
    return result


def expire_pending(state: dict, *, now: datetime | None = None,
                   pending_expiry_turns: int = 2) -> dict:
    current = utc_now(now)
    pending = state["workflow_state"]["pending"]
    expiry = parse_timestamp(state.get("runtime", {}).get("pending_expires_at"))
    created = parse_timestamp(state.get("runtime", {}).get("pending_created_at"))
    expired = (expiry is not None and current >= expiry or
               created is not None and (current - created).total_seconds() >= 600 or
               pending.get("turns_waiting", 0) > pending_expiry_turns)
    if pending.get("type") != "none" and expired:
        result = cancel_pending(state, clear_target=True)
        result["runtime"]["pending_expired"] = True
        return result
    return deepcopy(state)


def begin_turn(state: dict, binding: TrustedBinding, *, turn_id: str,
               user_question: str, now: datetime | None = None,
               pending_expiry_turns: int = 2) -> dict:
    _assert_session(binding, state)
    if not isinstance(turn_id, str) or not turn_id or not isinstance(user_question, str):
        raise StateError("invalid_turn")
    current = utc_now(now)
    result = new_state(binding, now=current)
    result["workflow_state"] = deepcopy(state["workflow_state"])
    result["trace"] = deepcopy(state.get("trace", []))
    for key in ("store_revision", "workflow_id", "policy_version", "pending_created_at",
                "pending_expires_at", "workflow_intent", "history"):
        if key in state.get("runtime", {}):
            result["runtime"][key] = deepcopy(state["runtime"][key])
    result["turn"].update(turn_id=turn_id, user_question=user_question)
    workflow = result["workflow_state"]
    workflow["trusted_confirmation"] = empty_confirmation()
    workflow["action"]["authorized"] = False
    workflow["action"]["authorization_expires_at"] = None
    workflow["transaction_identified"] = False
    workflow["transaction_unique"] = False
    workflow["existing_case"] = {"found": False, "complaint_id": None, "status": None}
    workflow["risk_data_complete"] = False
    workflow["unrecognized_count_24h"] = None
    if workflow["pending"].get("type") != "none" and state["turn"].get("turn_id") != turn_id:
        workflow["pending"]["turns_waiting"] += 1
    if binding.expired(current) or not binding.authenticated:
        return cancel_pending(result, clear_target=True)
    return expire_pending(result, now=current, pending_expiry_turns=pending_expiry_turns)


def set_pending(state: dict, pending: dict, *, now: datetime | None = None,
                ttl_seconds: int = 600) -> dict:
    """Install a trusted preparation/selection projection, without granting consent."""
    if type(ttl_seconds) is not int or not 0 < ttl_seconds <= 600:
        raise StateError("invalid_pending_ttl")
    if pending.get("type") not in {"awaiting_selection", "awaiting_confirmation"}:
        raise StateError("invalid_pending")
    current = utc_now(now)
    result = cancel_pending(state)
    result["workflow_state"]["pending"].update(deepcopy(pending))
    result["runtime"]["pending_created_at"] = _iso(current)
    result["runtime"]["pending_expires_at"] = _iso(datetime.fromtimestamp(
        current.timestamp() + ttl_seconds, timezone.utc))
    return result


def apply_decision(state: dict, decision: dict) -> dict:
    """Apply a pure policy decision. Internal orchestration calls this, never model JSON."""
    result = deepcopy(state)
    _merge(result["workflow_state"], decision.get("workflow_updates", {}))
    result["workflow_state"]["policy_decision"] = {
        key: deepcopy(decision.get(key)) for key in ("response_mode", "rule_ids",
            "requires_confirmation", "requires_human", "reason_code")}
    if decision.get("clear_pending"):
        # Preserve the terminal decision and action evidence while revoking consent.
        result = cancel_pending(result, clear_target=decision.get("clear_target", False))
        if decision.get("response_mode") == "ACTION_DONE":
            result["workflow_state"]["action"]["authorized"] = True
    if decision.get("pending"):
        result = set_pending(result, decision["pending"],
                             now=parse_timestamp(result["turn"]["current_timestamp"]),
                             ttl_seconds=decision.get("pending_ttl_seconds", 600))
    if decision.get("workflow_intent"):
        result["runtime"]["workflow_intent"] = decision["workflow_intent"]
    result["runtime"]["policy_version"] = decision.get("policy_version")
    return result


def record_tool_result(state: dict, name: str, result: dict, *, tool_retries: int = 2) -> dict:
    """Bound retries per call; policy counts exhausted failures once per turn."""
    if not isinstance(name, str) or not name or not isinstance(result, dict):
        raise StateError("invalid_tool_result")
    updated = deepcopy(state)
    attempts = updated["runtime"].setdefault("tool_attempts", {})
    attempts[name] = attempts.get(name, 0) + 1
    if attempts[name] > tool_retries + 1:
        raise StateError("tool_retry_exhausted")
    item = deepcopy(result)
    item["retry_count"] = attempts[name] - 1
    item["retries_exhausted"] = item.get("status") == "error" and attempts[name] >= tool_retries + 1
    updated["tool_results"][name] = item
    return updated


class ConversationStore:
    """SQLite CAS storage partitioned by the complete trusted identity binding.

    The trusted host remains responsible for revocation and authenticating the
    current binding. Store keys are never accepted from model or request text.
    """
    def __init__(self, path: str | Path, *, pending_ttl_seconds: int = 600,
                 pending_expiry_turns: int = 2):
        self.path = Path(path)
        if not 0 < pending_ttl_seconds <= 600 or pending_expiry_turns < 0:
            raise StateError("invalid_pending_ttl")
        self.pending_ttl_seconds = pending_ttl_seconds
        self.pending_expiry_turns = pending_expiry_turns
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS gloria_conversations (
                owner TEXT NOT NULL, customer TEXT NOT NULL, session TEXT NOT NULL,
                conversation TEXT NOT NULL, revision INTEGER NOT NULL, expires REAL NOT NULL,
                state_json TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(owner, customer, session, conversation))""")
            db.execute("""CREATE TABLE IF NOT EXISTS gloria_turns (
                owner TEXT NOT NULL, customer TEXT NOT NULL, session TEXT NOT NULL,
                conversation TEXT NOT NULL, turn_id TEXT NOT NULL,
                input_digest TEXT NOT NULL, state_json TEXT NOT NULL,
                PRIMARY KEY(owner, customer, session, conversation, turn_id))""")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
        return db

    def _loaded(self, binding: TrustedBinding, payload: str, revision: int,
                now: datetime) -> dict:
        state = json.loads(payload)
        _assert_session(binding, state)
        state["session"] = binding.session(now)
        state["runtime"]["store_revision"] = revision
        state["runtime"]["session_expires_at"] = _iso(parse_timestamp(binding.expires_at))
        # Consent is a current host event, never durable chat history.
        state["workflow_state"]["trusted_confirmation"] = empty_confirmation()
        state["workflow_state"]["action"]["authorized"] = False
        if binding.expired(now) or not binding.authenticated:
            return cancel_pending(state, clear_target=True)
        return expire_pending(state, now=now, pending_expiry_turns=self.pending_expiry_turns)

    def load(self, binding: TrustedBinding, *, now: datetime | None = None) -> dict | None:
        current = utc_now(now)
        with self._connect() as db:
            row = db.execute("""SELECT state_json,revision,expires FROM gloria_conversations
                WHERE owner=? AND customer=? AND session=? AND conversation=?""", binding.key()).fetchone()
        if row and row[2] != parse_timestamp(binding.expires_at).timestamp():
            raise StateError("session_expiry_changed")
        return self._loaded(binding, row[0], row[1], current) if row else None

    def _write(self, db: sqlite3.Connection, binding: TrustedBinding, state: dict,
               expected_revision: int | None, current: datetime) -> int:
        _assert_session(binding, state)
        if binding.expired(current) or not binding.authenticated:
            raise StateError("session_not_live")
        row = db.execute("""SELECT revision,expires FROM gloria_conversations
            WHERE owner=? AND customer=? AND session=? AND conversation=?""", binding.key()).fetchone()
        revision = row[0] if row else 0
        expected = state.get("runtime", {}).get("store_revision", 0) if expected_revision is None else expected_revision
        if type(expected) is not int or expected != revision:
            raise RevisionConflict("revision_conflict")
        prepared = expire_pending(state, now=current, pending_expiry_turns=self.pending_expiry_turns)
        # Cap any caller-provided pending TTL to the store policy and absolute 600s.
        created = parse_timestamp(prepared.get("runtime", {}).get("pending_created_at"))
        if prepared["workflow_state"]["pending"].get("type") != "none":
            if created is None:
                prepared["runtime"]["pending_created_at"] = _iso(current)
                created = current
            cap = created.timestamp() + self.pending_ttl_seconds
            expiry = parse_timestamp(prepared["runtime"].get("pending_expires_at"))
            prepared["runtime"]["pending_expires_at"] = _iso(datetime.fromtimestamp(
                min(cap, expiry.timestamp()) if expiry else cap, timezone.utc))
        prepared = expire_pending(prepared, now=current, pending_expiry_turns=self.pending_expiry_turns)
        prepared["workflow_state"]["trusted_confirmation"] = empty_confirmation()
        prepared["workflow_state"]["action"]["authorized"] = False
        prepared["runtime"]["store_revision"] = revision + 1
        payload = json.dumps(prepared, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        expires = parse_timestamp(binding.expires_at).timestamp()
        if row and expires != row[1]:
            raise StateError("session_expiry_changed")
        db.execute("""INSERT INTO gloria_conversations VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(owner,customer,session,conversation) DO UPDATE SET
            revision=excluded.revision,state_json=excluded.state_json,updated=excluded.updated""",
                   (*binding.key(), revision + 1, expires, payload, current.timestamp()))
        return revision + 1

    def save(self, binding: TrustedBinding, state: dict, *, expected_revision: int | None = None,
             now: datetime | None = None) -> int:
        current = utc_now(now)
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._write(db, binding, state, expected_revision, current)

    def save_turn(self, binding: TrustedBinding, turn_id: str, state: dict, *, expected_revision: int | None = None,
                  now: datetime | None = None) -> int:
        """Atomically retain exact turn replay and conversation revision.

        A repeated ID with different input is rejected. An exact replay returns
        its original revision without overwriting more recent conversation state.
        """
        current = utc_now(now)
        _assert_session(binding, state)
        if binding.expired(current) or not binding.authenticated:
            raise StateError("session_not_live")
        turn = state["turn"]
        if not isinstance(turn_id, str) or not turn_id or turn_id != turn.get("turn_id"):
            raise StateError("invalid_turn")
        digest = state.get("runtime", {}).get("input_sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)):
            raise StateError("invalid_input_digest")
        digest = digest or hashlib.sha256(turn["user_question"].encode("utf-8")).hexdigest()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("""SELECT input_digest,state_json FROM gloria_turns
                WHERE owner=? AND customer=? AND session=? AND conversation=? AND turn_id=?""",
                                  (*binding.key(), turn_id)).fetchone()
            if existing:
                if existing[0] != digest:
                    raise ReplayConflict("turn_replay_conflict")
                return json.loads(existing[1])["runtime"]["store_revision"]
            revision = self._write(db, binding, state, expected_revision, current)
            saved = db.execute("""SELECT state_json FROM gloria_conversations
                WHERE owner=? AND customer=? AND session=? AND conversation=?""", binding.key()).fetchone()[0]
            db.execute("INSERT INTO gloria_turns VALUES (?,?,?,?,?,?,?)",
                       (*binding.key(), turn_id, digest, saved))
            return revision

    def load_turn(self, binding: TrustedBinding, turn_id: str, *, user_question: str | None = None,
                  now: datetime | None = None) -> dict | None:
        current = utc_now(now)
        if binding.expired(current) or not binding.authenticated:
            return None
        with self._connect() as db:
            row = db.execute("""SELECT t.input_digest,t.state_json,c.expires FROM gloria_turns t
                JOIN gloria_conversations c USING(owner,customer,session,conversation)
                WHERE t.owner=? AND t.customer=? AND t.session=? AND t.conversation=? AND t.turn_id=?""",
                             (*binding.key(), turn_id)).fetchone()
        if row is None:
            return None
        if row[2] != parse_timestamp(binding.expires_at).timestamp():
            raise StateError("session_expiry_changed")
        if user_question is not None and hashlib.sha256(user_question.encode("utf-8")).hexdigest() != row[0]:
            raise ReplayConflict("turn_replay_conflict")
        revision = json.loads(row[1])["runtime"]["store_revision"]
        return self._loaded(binding, row[1], revision, current)
