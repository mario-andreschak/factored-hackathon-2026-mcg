"""Canonical internal ChatState and owner-bound durable conversation storage.

Only trusted application code constructs bindings and installs host consent.
Neither this module nor the policy engine executes a banking action.
"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import uuid
from typing import Any, Iterator
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

_SCOPE_RUNTIME = frozenset({"pending_created_at", "pending_expires_at", "pending_expired", "workflow_intent",
    "complaint_snapshot_hash", "field_clarification", "action_lineage", "handoff_lineage",
    "host_receipt_lineage", "prior_verified_actions", "prior_verified_handoffs", "policy_version",
    "node_errors", "auxiliary_errors", "safe_fallback_used", "handoff_narrative",
    "host_cancellation_requested", "tool_attempts", "query_history"})
_BATCH_RUNTIME = frozenset({"query_scopes", "query_scope_order", "query_batch_id",
    "active_query_id", "query_results", "query_projection", "shared_node_errors", "host_cancellation_queue"})
_DOMAINS = frozenset({"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS",
    "HUMAN_REQUEST", "GREETING", "PERSONALITY", "OOD"})


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


def _remember_action_lineage(state: dict) -> None:
    """Capture trusted preparation before its conversational projection disappears."""
    runtime, workflow = state["runtime"], state["workflow_state"]
    pending = workflow.get("pending", {})
    if not all(pending.get(key) for key in ("request_id", "host_pending_handle",
            "target_transaction_id", "snapshot_id", "snapshot_hash")):
        return
    prior = runtime.get("action_lineage", {})
    if (workflow.get("action_attempted") is True and prior.get("request_id") and
            (any(prior.get(key) != pending.get(key) for key in ("request_id", "host_pending_handle",
                "target_transaction_id", "snapshot_id", "snapshot_hash")) or
             prior.get("query_id") != runtime.get("active_query_id") or
             prior.get("binding_digest") != runtime.get("trusted_binding_digest"))):
        raise StateError("action_lineage_conflict")
    lineage = {key: deepcopy(pending.get(key)) for key in ("request_id", "host_pending_handle",
        "target_transaction_id", "snapshot_id", "snapshot_hash", "created_turn_id")}
    lineage.update(query_id=runtime.get("active_query_id"), binding_digest=runtime.get("trusted_binding_digest"),
                   invalidated=bool(prior.get("invalidated") and prior.get("request_id") == pending["request_id"]))
    runtime["action_lineage"] = lineage


def cancel_pending(state: dict, *, clear_target: bool = False) -> dict:
    result = deepcopy(state)
    _remember_action_lineage(result)
    workflow = result["workflow_state"]
    prior_pending = workflow.get("pending", {})
    if prior_pending.get("type") == "awaiting_confirmation" or prior_pending.get("host_pending_handle"):
        result["runtime"]["host_cancellation_requested"] = {
            "query_id": result["runtime"].get("active_query_id"),
            "prior_pending_handle": prior_pending.get("host_pending_handle"),
            "request_id": prior_pending.get("request_id"),
            "prior_target_transaction_id": prior_pending.get("target_transaction_id"),
            "prior_snapshot_id": prior_pending.get("snapshot_id"),
            "prior_snapshot_hash": prior_pending.get("snapshot_hash"), "reason": "pending_cleared"}
    workflow["pending"] = empty_pending()
    workflow["trusted_confirmation"] = empty_confirmation()
    workflow["action"]["authorized"] = False
    workflow["action"]["authorization_expires_at"] = None
    if result["runtime"].get("action_lineage"):
        result["runtime"]["action_lineage"]["invalidated"] = True
    result["runtime"]["pending_created_at"] = None
    result["runtime"]["pending_expires_at"] = None
    if clear_target:
        workflow.update(transaction_identified=False, transaction_unique=False,
                        transaction_id=None, candidate_snapshot_hash=None)
        workflow["existing_case"] = {"found": False, "complaint_id": None, "status": None}
        result["runtime"].pop("field_clarification", None)
    return result


def reset_workflow(state: dict) -> dict:
    """Start a distinct request; uncertain writes must first be recovered by the host."""
    workflow = state["workflow_state"]
    action = workflow.get("action", {})
    outcome = workflow.get("action_outcome")
    verified_done = outcome == "verified" and action.get("executed") is True and action.get("verified") is True and action.get("result_id")
    confirmed_no_write = outcome == "failed" and action.get("executed") is not True
    if outcome in {"unknown", "executed"} or workflow.get("action_attempted") is True and not (verified_done or confirmed_no_write):
        raise StateError("action_recovery_required")
    result = cancel_pending(state, clear_target=True)
    result["workflow_state"] = empty_workflow()
    result["runtime"].pop("tool_attempts", None)
    result["runtime"].pop("workflow_intent", None)
    result["runtime"].pop("complaint_snapshot_hash", None)
    result["runtime"].pop("field_clarification", None)
    result["runtime"].pop("action_lineage", None)
    result["runtime"].pop("handoff_lineage", None)
    result["runtime"].pop("host_receipt_lineage", None)
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
        if result["runtime"].get("host_cancellation_requested"):
            result["runtime"]["host_cancellation_requested"]["reason"] = "pending_expired"
        return result
    return deepcopy(state)


def begin_turn(state: dict, binding: TrustedBinding, *, turn_id: str,
               user_question: str, now: datetime | None = None,
               pending_expiry_turns: int = 2, _advance_scopes: bool = True) -> dict:
    _assert_session(binding, state)
    if not isinstance(turn_id, str) or not turn_id or not isinstance(user_question, str):
        raise StateError("invalid_turn")
    current = utc_now(now)
    result = new_state(binding, now=current)
    result["workflow_state"] = deepcopy(state["workflow_state"])
    result["trace"] = deepcopy(state.get("trace", []))
    for key in ("store_revision", "workflow_id", "policy_version", "pending_created_at",
                "pending_expires_at", "workflow_intent", "history", "prior_verified_actions",
                "complaint_snapshot_hash", "field_clarification", "action_lineage", "handoff_lineage",
                "prior_verified_handoffs", "host_receipt_lineage", "session_tool_failures",
                "query_history", "host_cancellation_requested", "pending_expired"):
        if key in state.get("runtime", {}):
            result["runtime"][key] = deepcopy(state["runtime"][key])
    for key in _BATCH_RUNTIME - {"shared_node_errors"}:
        if key in state.get("runtime", {}):
            result["runtime"][key] = deepcopy(state["runtime"][key])
    result["turn"].update(turn_id=turn_id, user_question=user_question)
    workflow = result["workflow_state"]
    _remember_action_lineage(result)
    prior_action = workflow.get("action", {})
    if (state["turn"].get("turn_id") != turn_id and workflow.get("action_outcome") == "verified" and
            prior_action.get("executed") is True and prior_action.get("verified") is True and
            prior_action.get("result_id")):
        # Completion ends this request. Keep a private audit, never use that old
        # receipt as current ownership/duplicate/risk evidence for a new target.
        audits = result["runtime"].get("prior_verified_actions", [])
        lineage = result["runtime"].get("action_lineage", {})
        audits.append({"turn_id": state["turn"].get("turn_id"), "result_id": prior_action["result_id"],
                       "idempotency_key": prior_action.get("idempotency_key") or lineage.get("request_id"),
                       "transaction_id": workflow.get("transaction_id") or lineage.get("target_transaction_id"),
                       "snapshot_id": workflow.get("pending", {}).get("snapshot_id") or lineage.get("snapshot_id"),
                       "query_id": lineage.get("query_id"), "host_pending_handle": lineage.get("host_pending_handle")})
        result = reset_workflow(result)
        result["runtime"]["prior_verified_actions"] = audits[-20:]
        workflow = result["workflow_state"]
    previous_handoff = workflow.get("handoff", {})
    if previous_handoff.get("created") is True and previous_handoff.get("handoff_id"):
        audits = result["runtime"].get("prior_verified_handoffs", [])
        audits.append({"query_id": result["runtime"].get("active_query_id"),
            "turn_id": state["turn"].get("turn_id"), "handoff_id": previous_handoff["handoff_id"],
            "reason_code": previous_handoff.get("reason_code"),
            "transaction_id": workflow.get("transaction_id")})
        result["runtime"]["prior_verified_handoffs"] = audits[-20:]
    workflow["handoff"] = {"required": False, "created": False, "handoff_id": None, "reason_code": None}
    workflow["trusted_confirmation"] = empty_confirmation()
    workflow["action"]["authorized"] = False
    workflow["action"]["authorization_expires_at"] = None
    workflow["transaction_identified"] = False
    workflow["transaction_unique"] = False
    workflow["existing_case"] = {"found": False, "complaint_id": None, "status": None}
    workflow["risk_data_complete"] = False
    workflow["unrecognized_count_24h"] = None
    if _advance_scopes and result["runtime"].get("query_scopes"):
        result = _advance_query_scopes(result, binding, turn_id=turn_id, user_question=user_question,
                                       now=current, pending_expiry_turns=pending_expiry_turns)
        workflow = result["workflow_state"]
    if workflow["pending"].get("type") != "none" and state["turn"].get("turn_id") != turn_id:
        workflow["pending"]["turns_waiting"] += 1
    if binding.expired(current) or not binding.authenticated:
        return cancel_pending(result, clear_target=True)
    return expire_pending(result, now=current, pending_expiry_turns=pending_expiry_turns)


def merge_explicit_slots(state: dict, extracted_slots: dict, *, continuing: bool = True) -> dict:
    """Merge an explicitly continuing field reply without restoring capabilities.

    The runtime decides topic continuity. Historical target IDs and foreign
    references are excluded; fresh IDs still require trusted owner-scoped reads.
    Guard flags always prevent using historical fields or business intent.
    """
    if not isinstance(extracted_slots, dict) or any(key not in SLOT_KEYS for key in extracted_slots):
        raise StateError("invalid_extracted_slots")
    result = deepcopy(state)
    turn = result["turn"]
    metadata = result.get("runtime", {}).get("field_clarification", {})
    previous_intent = metadata.get("intent")
    current_intent = turn.get("intent")
    attack = turn.get("attack", {})
    guarded = (turn.get("human_requested") is True or turn.get("unauthorized_reference") is True or
               extracted_slots.get("foreign_customer_reference") is True or
               attack.get("deceptive") == 1 or attack.get("inappropriate") == 1)
    business = {"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "COMPLAINT_STATUS", "HUMAN_REQUEST"}
    retain = (continuing and not guarded and previous_intent in business and
              current_intent != "HUMAN_REQUEST" and
              (current_intent == previous_intent or current_intent not in business) and
              turn.get("clarification", {}).get("resolution_type") != "NEW_REQUEST")
    slots = {key: False if key in ("amount_is_approximate", "foreign_customer_reference") else None for key in SLOT_KEYS}
    if retain:
        for key, value in metadata.get("slots", {}).items():
            if key in SLOT_KEYS and key not in {"transaction_id", "complaint_id", "foreign_customer_reference"}:
                slots[key] = deepcopy(value)
        turn["intent"] = previous_intent
    for key, value in extracted_slots.items():
        if value is not None:
            if retain and key == "amount_is_approximate" and extracted_slots.get("amount") is None:
                continue
            slots[key] = deepcopy(value)
    turn["slots"] = slots
    if not retain:
        result["runtime"].pop("field_clarification", None)
        if metadata and not guarded and (not continuing or
                turn.get("clarification", {}).get("resolution_type") == "NEW_REQUEST" or
                current_intent in business and current_intent != previous_intent):
            result = reset_workflow(result)
    return result


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
    query_id = result["runtime"].get("active_query_id")
    if query_id is not None:
        if pending.get("query_id") not in (None, query_id):
            raise StateError("query_scope_binding_mismatch")
        result["workflow_state"]["pending"]["query_id"] = query_id
    result["runtime"]["pending_created_at"] = _iso(current)
    result["runtime"]["pending_expires_at"] = _iso(datetime.fromtimestamp(
        current.timestamp() + ttl_seconds, timezone.utc))
    return result


def apply_decision(state: dict, decision: dict) -> dict:
    """Apply a pure policy decision. Internal orchestration calls this, never model JSON."""
    result = deepcopy(state)
    if decision.get("reset_workflow"):
        result = reset_workflow(result)
    _merge(result["workflow_state"], decision.get("workflow_updates", {}))
    result["workflow_state"]["policy_decision"] = {
        key: deepcopy(decision.get(key)) for key in ("response_mode", "rule_ids",
            "requires_confirmation", "requires_human", "reason_code")}
    if decision.get("clear_pending"):
        # Preserve the terminal decision and action evidence while revoking consent.
        result = cancel_pending(result, clear_target=decision.get("clear_target", False))
        if decision.get("response_mode") == "ACTION_DONE":
            result["workflow_state"]["action"]["authorized"] = True
            result["runtime"].pop("host_cancellation_requested", None)
        elif result["runtime"].get("host_cancellation_requested"):
            result["runtime"]["host_cancellation_requested"]["reason"] = decision.get("reason_code", "pending_cleared")
    if decision.get("pending"):
        result = set_pending(result, decision["pending"],
                             now=parse_timestamp(result["turn"]["current_timestamp"]),
                             ttl_seconds=decision.get("pending_ttl_seconds", 600))
    if decision.get("workflow_intent"):
        result["runtime"]["workflow_intent"] = decision["workflow_intent"]
    if decision.get("complaint_snapshot_hash"):
        result["runtime"]["complaint_snapshot_hash"] = decision["complaint_snapshot_hash"]
    fields = decision.get("workflow_updates", {}).get("missing_fields")
    if (decision.get("response_mode") == "CLARIFY" and fields and
            result["workflow_state"]["pending"].get("type") == "none"):
        slots = {key: deepcopy(value) for key, value in result["turn"]["slots"].items()
                 if key in SLOT_KEYS and key not in {"transaction_id", "complaint_id", "foreign_customer_reference"} and
                 value is not None}
        result["runtime"]["field_clarification"] = {
            "intent": decision.get("workflow_intent") or result["turn"].get("intent"),
            "slots": slots, "missing_fields": deepcopy(fields)}
    elif decision.get("response_mode") != "CLARIFY":
        result["runtime"].pop("field_clarification", None)
        if decision.get("response_mode") in {"CONFIRM_ACTION", "INFORM", "INFORM_EXISTING_CASE", "ACTION_DONE"}:
            result["workflow_state"]["missing_fields"] = []
    result["runtime"]["policy_version"] = decision.get("policy_version")
    failures = result["workflow_state"].get("counters", {}).get("tool_failures", 0)
    result["runtime"]["session_tool_failures"] = max(result["runtime"].get("session_tool_failures", 0), failures)
    return result


def _scope_map(state: dict) -> tuple[dict, list]:
    runtime = state.get("runtime", {})
    if "query_scopes" not in runtime and "query_scope_order" not in runtime:
        return {}, []
    scopes = runtime.get("query_scopes", {})
    order = runtime.get("query_scope_order", [])
    if (not isinstance(scopes, dict) or not isinstance(order, list) or len(scopes) > 8 or
            len(order) != len(scopes) or any(not isinstance(item, str) for item in order)):
        raise StateError("invalid_query_scopes")
    if len(set(order)) != len(order) or set(order) != set(scopes):
        raise StateError("invalid_query_scopes")
    for index, query_id in enumerate(order):
        capsule = scopes[query_id]
        if (not isinstance(query_id, str) or not re.fullmatch(r"q_[a-f0-9]{32}", query_id) or
                not isinstance(capsule, dict) or capsule.get("query_id") != query_id or
                type(capsule.get("query_index")) is not int or capsule.get("query_index") != index or
                capsule.get("binding_digest") != runtime.get("trusted_binding_digest") or
                not isinstance(capsule.get("intent"), str) or capsule.get("intent") not in _DOMAINS or
                not isinstance(capsule.get("query_text"), str) or
                any(not isinstance(capsule.get(key), dict) for key in
                    ("runtime", "workflow_state", "turn", "tool_results", "response")) or
                any(key in capsule.get("runtime", {}) for key in _BATCH_RUNTIME)):
            raise StateError("query_scope_binding_mismatch")
        workflow = capsule["workflow_state"]
        if any(not isinstance(workflow.get(key), dict) for key in ("pending", "action", "trusted_confirmation", "handoff", "counters")):
            raise StateError("invalid_query_scopes")
        pending_id = workflow["pending"].get("query_id")
        if pending_id is not None and pending_id != query_id:
            raise StateError("query_scope_binding_mismatch")
        for key in ("action_lineage", "handoff_lineage", "host_receipt_lineage"):
            lineage = capsule["runtime"].get(key, {})
            if (not isinstance(lineage, dict) or lineage and
                    (lineage.get("query_id") != query_id or lineage.get("binding_digest") != capsule["binding_digest"])):
                raise StateError("query_scope_binding_mismatch")
    active = runtime.get("active_query_id")
    if active is not None and (not isinstance(active, str) or active not in scopes):
        raise StateError("invalid_query_scope")
    return scopes, order


def _unresolved(capsule: dict) -> bool:
    workflow = capsule.get("workflow_state", {})
    mode = workflow.get("policy_decision", {}).get("response_mode")
    return (workflow.get("pending", {}).get("type") not in (None, "none") or
        mode == "CLARIFY" and bool(workflow.get("missing_fields")) or
        workflow.get("action_outcome") in {"unknown", "executed"} or
        workflow.get("action_attempted") is True and workflow.get("action_outcome") not in {"verified", "failed"} or
        workflow.get("handoff", {}).get("required") is True and workflow.get("handoff", {}).get("created") is not True)


def start_query_batch(state: dict, intents: list[dict], *, batch_id: str | None = None) -> dict:
    """Allocate independent server-owned capsules for a bounded ordered classifier result.

    The model supplies only query text/domain. IDs, owner binding and capability
    lineage are allocated here, never taken from that output.
    """
    if not isinstance(intents, list) or not 1 <= len(intents) <= 8:
        raise StateError("invalid_query_batch")
    for intent in intents:
        if (not isinstance(intent, dict) or set(intent) != {"query_text", "domain"} or
                intent.get("domain") not in _DOMAINS or not isinstance(intent.get("query_text"), str) or
                not intent["query_text"] or len(intent["query_text"]) > 12000):
            raise StateError("invalid_query_batch")
    if batch_id is not None and (not isinstance(batch_id, str) or not batch_id or len(batch_id) > 128):
        raise StateError("invalid_query_batch")
    result = deepcopy(state)
    scopes, _ = _scope_map(result)
    if any(_unresolved(capsule) for capsule in scopes.values()) or _unresolved(result):
        raise StateError("unresolved_query_batch")
    runtime = result["runtime"]
    # A new batch can retire every old capsule. Its unacknowledged revocations
    # must remain visible to the trusted host even when their query is retired.
    queue = deepcopy(runtime.get("host_cancellation_queue", []))
    if not isinstance(queue, list) or any(not isinstance(signal, dict) for signal in queue):
        raise StateError("invalid_host_cancellations")
    for signal in [runtime.get("host_cancellation_requested")] + [
            capsule["runtime"].get("host_cancellation_requested") for capsule in scopes.values()]:
        if isinstance(signal, dict) and signal not in queue:
            queue.append(deepcopy(signal))
    if queue:
        runtime["host_cancellation_queue"] = queue
    runtime.update(query_scopes={}, query_scope_order=[], query_batch_id=batch_id or uuid.uuid4().hex,
                   active_query_id=None, query_results=[], query_projection=True,
                   shared_node_errors=deepcopy(runtime.get("node_errors", [])))
    result["turn"]["intents"] = deepcopy(intents)
    for index, intent in enumerate(intents):
        query_id = "q_" + uuid.uuid4().hex
        runtime["query_scope_order"].append(query_id)
        runtime["query_scopes"][query_id] = {
            "query_id": query_id, "binding_digest": runtime["trusted_binding_digest"],
            "query_index": index, "query_text": intent["query_text"], "intent": intent["domain"],
            "turn": {"turn_id": None}, "workflow_state": empty_workflow(), "tool_results": {},
            "response": {}, "runtime": {"pending_created_at": None, "pending_expires_at": None}}
    return result


def _capsule_frame(parent: dict, capsule: dict, binding: TrustedBinding, now: datetime) -> dict:
    frame = new_state(binding, now=now)
    frame["turn"].update(deepcopy(capsule.get("turn", {})))
    frame["workflow_state"] = deepcopy(capsule["workflow_state"])
    frame["tool_results"] = deepcopy(capsule.get("tool_results", {}))
    frame["response"] = deepcopy(capsule.get("response", {}))
    frame["runtime"].update({key: deepcopy(value) for key, value in capsule.get("runtime", {}).items()
                             if key in _SCOPE_RUNTIME})
    frame["runtime"]["active_query_id"] = capsule["query_id"]
    return frame


def _snapshot_capsule(capsule: dict, frame: dict) -> dict:
    result = {key: deepcopy(capsule[key]) for key in ("query_id", "binding_digest", "query_index", "query_text", "intent")}
    result.update(turn=deepcopy(frame["turn"]), workflow_state=deepcopy(frame["workflow_state"]),
                  tool_results=deepcopy(frame.get("tool_results", {})), response=deepcopy(frame.get("response", {})),
                  runtime={key: deepcopy(value) for key, value in frame["runtime"].items() if key in _SCOPE_RUNTIME})
    return result


def activate_query_scope(state: dict, binding: TrustedBinding, query_id: str, *, now: datetime | None = None,
                         fresh: bool = True, query_text: str | None = None) -> dict:
    """Project one owner-bound capsule; fresh activation clears current evidence.

    ``fresh=False`` restores replay facts for a new trusted host readback. It
    still revokes consent and authorization; it never verifies a receipt itself.
    """
    _assert_session(binding, state)
    scopes, _ = _scope_map(state)
    if query_id not in scopes:
        raise StateError("invalid_query_scope")
    if query_text is not None and (not isinstance(query_text, str) or len(query_text) > 12000):
        raise StateError("invalid_query_text")
    current = utc_now(now)
    capsule = scopes[query_id]
    result = _capsule_frame(state, capsule, binding, current)
    if fresh:
        result = begin_turn(result, binding, turn_id=state["turn"]["turn_id"],
                            user_question=state["turn"]["user_question"], now=current, _advance_scopes=False)
        for key in ("language", "effective_language", "emotional_context", "attack", "human_requested",
                    "unauthorized_reference", "intents"):
            result["turn"][key] = deepcopy(state["turn"][key])
        result["runtime"]["node_errors"] = deepcopy(state["runtime"].get("shared_node_errors", []))
    else:
        result["workflow_state"]["trusted_confirmation"] = empty_confirmation()
        result["workflow_state"]["action"]["authorized"] = False
        result["workflow_state"]["action"]["authorization_expires_at"] = None
        clock = new_state(binding, now=current)["turn"]
        result["turn"].update(current_date=clock["current_date"], current_timestamp=clock["current_timestamp"])
        result = expire_pending(result, now=current)
    result["turn"].update(active_query_index=capsule["query_index"], intent=capsule["intent"],
                          clean_query=query_text if query_text is not None else capsule["query_text"])
    # Restore batch container and shared operational metadata only outside the
    # capsule. A capsule never recursively stores other queries or their tools.
    for key in ("store_revision", "workflow_id", "history", "input_sha256", "session_tool_failures"):
        if key in state["runtime"]:
            result["runtime"][key] = deepcopy(state["runtime"][key])
    for key in _BATCH_RUNTIME:
        if key in state["runtime"]:
            result["runtime"][key] = deepcopy(state["runtime"][key])
    result["runtime"].update(active_query_id=query_id, query_projection=False)
    result["trace"] = deepcopy(state.get("trace", []))
    result["workflow_state"]["counters"]["tool_failures"] = max(
        result["workflow_state"]["counters"].get("tool_failures", 0), result["runtime"].get("session_tool_failures", 0))
    pending = result["workflow_state"]["pending"]
    if pending.get("type") != "none":
        if pending.get("query_id") not in (None, query_id):
            raise StateError("query_scope_binding_mismatch")
        pending["query_id"] = query_id
    return result


def checkpoint_query_scope(state: dict) -> dict:
    """Save the active canonical view into its own capsule, preserving siblings."""
    scopes, _ = _scope_map(state)
    query_id = state.get("runtime", {}).get("active_query_id")
    if query_id is None:
        return deepcopy(state)
    if state["turn"].get("active_query_index") != scopes[query_id]["query_index"]:
        raise StateError("query_scope_binding_mismatch")
    result = deepcopy(state)
    pending = result["workflow_state"]["pending"]
    if pending.get("type") != "none":
        if pending.get("query_id") not in (None, query_id):
            raise StateError("query_scope_binding_mismatch")
        pending["query_id"] = query_id
    _remember_action_lineage(result)
    result["runtime"]["query_scopes"][query_id] = _snapshot_capsule(scopes[query_id], result)
    result["runtime"]["session_tool_failures"] = max(result["runtime"].get("session_tool_failures", 0),
        result["workflow_state"]["counters"].get("tool_failures", 0))
    return result


def finish_query_batch(state: dict) -> dict:
    """Project the first unresolved scope and expose ordered response observations."""
    result = checkpoint_query_scope(state) if not state.get("runtime", {}).get("query_projection") else deepcopy(state)
    original_turn = deepcopy(result["turn"])
    scopes, order = _scope_map(result)
    observations = [{"query_id": query_id, "query_index": scopes[query_id]["query_index"],
        "response": deepcopy(scopes[query_id].get("response", {})),
        "policy_decision": deepcopy(scopes[query_id]["workflow_state"].get("policy_decision", {}))} for query_id in order]
    chosen = next((query_id for query_id in order if _unresolved(scopes[query_id])), order[-1] if order else None)
    if chosen is not None:
        capsule = scopes[chosen]
        result["turn"] = deepcopy(capsule["turn"])
        result["workflow_state"] = deepcopy(capsule["workflow_state"])
        result["tool_results"] = deepcopy(capsule.get("tool_results", {}))
        result["response"] = deepcopy(capsule.get("response", {}))
        for key in _SCOPE_RUNTIME:
            result["runtime"].pop(key, None)
        result["runtime"].update(deepcopy(capsule.get("runtime", {})))
    for key in ("turn_id", "user_question", "intents", "language", "effective_language", "current_date", "current_timestamp"):
        if key in original_turn:
            result["turn"][key] = deepcopy(original_turn[key])
    result["runtime"].update(active_query_id=chosen, query_results=observations, query_projection=True)
    return result


def _advance_query_scopes(state: dict, binding: TrustedBinding, *, turn_id: str,
                          user_question: str, now: datetime, pending_expiry_turns: int) -> dict:
    result = deepcopy(state)
    scopes, order = _scope_map(result)
    for query_id in order:
        frame = _capsule_frame(result, scopes[query_id], binding, now)
        frame = begin_turn(frame, binding, turn_id=turn_id, user_question=user_question,
                           now=now, pending_expiry_turns=pending_expiry_turns, _advance_scopes=False)
        result["runtime"]["query_scopes"][query_id] = _snapshot_capsule(scopes[query_id], frame)
    return result


def _sanitize_query_scopes(state: dict, binding: TrustedBinding, now: datetime,
                            *, pending_expiry_turns: int, pending_ttl_seconds: int | None = None) -> dict:
    result = deepcopy(state)
    scopes, order = _scope_map(result)
    for query_id in order:
        frame = _capsule_frame(result, scopes[query_id], binding, now)
        _remember_action_lineage(frame)
        frame["workflow_state"]["trusted_confirmation"] = empty_confirmation()
        frame["workflow_state"]["action"]["authorized"] = False
        frame["workflow_state"]["action"]["authorization_expires_at"] = None
        pending = frame["workflow_state"]["pending"]
        if pending_ttl_seconds is not None and pending.get("type") != "none":
            created = parse_timestamp(frame["runtime"].get("pending_created_at")) or now
            expiry = parse_timestamp(frame["runtime"].get("pending_expires_at"))
            cap = created + timedelta(seconds=pending_ttl_seconds)
            frame["runtime"].update(pending_created_at=_iso(created), pending_expires_at=_iso(min(cap, expiry) if expiry else cap))
        frame = (cancel_pending(frame, clear_target=True) if binding.expired(now) or not binding.authenticated
                 else expire_pending(frame, now=now, pending_expiry_turns=pending_expiry_turns))
        result["runtime"]["query_scopes"][query_id] = _snapshot_capsule(scopes[query_id], frame)
    return result


def record_tool_result(state: dict, name: str, result: dict, *, tool_retries: int = 2) -> dict:
    """Bound retries per call; policy counts exhausted failures once per turn."""
    if not isinstance(name, str) or not name or not isinstance(result, dict):
        raise StateError("invalid_tool_result")
    if type(tool_retries) is not int or tool_retries < 0:
        raise StateError("invalid_tool_retries")
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

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=10)
        try:
            db.execute("PRAGMA busy_timeout=10000")
            with db:
                yield db
        finally:
            db.close()

    def _loaded(self, binding: TrustedBinding, payload: str, revision: int,
                now: datetime) -> dict:
        state = json.loads(payload)
        _assert_session(binding, state)
        state["session"] = binding.session(now)
        state["runtime"]["store_revision"] = revision
        state["runtime"]["session_expires_at"] = _iso(parse_timestamp(binding.expires_at))
        state = _sanitize_query_scopes(state, binding, now, pending_expiry_turns=self.pending_expiry_turns,
                                       pending_ttl_seconds=self.pending_ttl_seconds)
        if state["workflow_state"]["pending"].get("type") != "none":
            created = parse_timestamp(state["runtime"].get("pending_created_at")) or now
            expiry = parse_timestamp(state["runtime"].get("pending_expires_at"))
            cap = created + timedelta(seconds=self.pending_ttl_seconds)
            state["runtime"].update(pending_created_at=_iso(created),
                                   pending_expires_at=_iso(min(cap, expiry) if expiry else cap))
        # Consent is a current host event, never durable chat history.
        state["workflow_state"]["trusted_confirmation"] = empty_confirmation()
        state["workflow_state"]["action"]["authorized"] = False
        state["workflow_state"]["action"]["authorization_expires_at"] = None
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
        prepared = (checkpoint_query_scope(state) if state.get("runtime", {}).get("query_scopes") and
                    not state["runtime"].get("query_projection") else deepcopy(state))
        _remember_action_lineage(prepared)
        prepared = _sanitize_query_scopes(prepared, binding, current,
            pending_expiry_turns=self.pending_expiry_turns, pending_ttl_seconds=self.pending_ttl_seconds)
        prepared = expire_pending(prepared, now=current, pending_expiry_turns=self.pending_expiry_turns)
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
        prepared["workflow_state"]["action"]["authorization_expires_at"] = None
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
            session = db.execute("""SELECT expires FROM gloria_conversations
                WHERE owner=? AND customer=? AND session=? AND conversation=?""", binding.key()).fetchone()
            if session and session[0] != parse_timestamp(binding.expires_at).timestamp():
                raise StateError("session_expiry_changed")
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
