"""Pure, ordered R0--R18 decisions over the canonical internal ChatState.

Returned transitions are instructions for trusted application orchestration,
not capabilities. No function in this module performs I/O to a bank or executes
an action. Trusted identities, ownership reads and consent originate in the host.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta
from functools import lru_cache
import math
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .state import empty_confirmation, empty_pending, parse_timestamp


TRANSACTION_INTENTS = frozenset({"TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY"})
BUSINESS_INTENTS = TRANSACTION_INTENTS | {"COMPLAINT_STATUS", "HUMAN_REQUEST"}
_NUMERIC_CONFIG = {"dispute_window_days", "max_candidates_to_show", "max_clarification_attempts",
                   "max_no_match_attempts", "tool_retries", "pending_expiry_turns",
                   "max_tool_failures", "confirmation_ttl_seconds"}


@lru_cache(maxsize=1)
def load_config() -> dict:
    """Read the canonical policy YAML's scalar/list subset without a dependency.

    This deliberately parses only policy inputs, not arbitrary YAML or prompts.
    Configuration is repository-owned; callers can instead pass a parsed dict.
    """
    text = (Path(__file__).resolve().parents[1] / "config" / "policy_rules.yaml").read_text(encoding="utf-8")
    result: dict = {"high_risk": {}}
    for key in _NUMERIC_CONFIG:
        match = re.search(rf"^{key}:\s*(\d+)\s*$", text, re.M)
        if not match:
            raise ValueError("invalid_policy_configuration")
        result[key] = int(match.group(1))
    version = re.search(r"^version:\s*([\w.\-]+)\s*$", text, re.M)
    result["version"] = version.group(1) if version else "unknown"
    risk = re.search(r"^high_risk:\s*\n((?:[ \t]+[^\n]*\n)+)", text, re.M)
    if risk is None:
        raise ValueError("invalid_policy_configuration")
    for key in ("fraud_score_threshold", "amount_usd_threshold", "unrecognized_count_24h"):
        match = re.search(rf"^\s+{key}:\s*(\d+(?:\.\d+)?)\s*$", risk.group(1), re.M)
        if not match:
            raise ValueError("invalid_policy_configuration")
        result["high_risk"][key] = float(match.group(1))
    for key in ("allowed_transaction_statuses", "open_complaint_statuses"):
        match = re.search(rf"^{key}:\s*\n((?:- [^\n]+\n)+)", text, re.M)
        if not match:
            raise ValueError("invalid_policy_configuration")
        result[key] = [line[2:].strip() for line in match.group(1).splitlines()]
    return result


def _config(overrides: dict | None) -> dict:
    result = deepcopy(load_config())
    if overrides:
        for key, value in overrides.items():
            if key == "high_risk":
                if not isinstance(value, dict):
                    raise ValueError("invalid_policy_configuration")
                result[key].update(value)
            else:
                result[key] = deepcopy(value)
    result.setdefault("risk_evidence_max_age_seconds", result.get("node_timeout_seconds", 20))
    freshness = result["risk_evidence_max_age_seconds"]
    if type(freshness) not in (int, float) or not math.isfinite(freshness) or not 0 <= freshness <= 60:
        raise ValueError("invalid_policy_configuration")
    for key in _NUMERIC_CONFIG:
        if type(result[key]) is not int or result[key] < (0 if key == "tool_retries" else 1):
            raise ValueError("invalid_policy_configuration")
    if result["confirmation_ttl_seconds"] > 600:
        raise ValueError("invalid_policy_configuration")
    for value in result["high_risk"].values():
        if _number(value) is None or value <= 0:
            raise ValueError("invalid_policy_configuration")
    for key in ("allowed_transaction_statuses", "open_complaint_statuses"):
        if not isinstance(result[key], list) or not result[key] or any(not isinstance(x, str) for x in result[key]):
            raise ValueError("invalid_policy_configuration")
    return result


def _number(value: Any) -> float | None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _count(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _decision(config: dict, rule: str, mode: str, reason: str,
              *, next_step: str = "respond", updates: dict | None = None, **extra: Any) -> dict:
    result = {"response_mode": mode, "rule_ids": [rule], "reason_code": reason,
              "requires_confirmation": mode == "CONFIRM_ACTION",
              "requires_human": mode in {"HANDOFF", "ACTION_UNVERIFIED"},
              "next_step": next_step, "policy_version": config["version"],
              "workflow_updates": deepcopy(updates or {})}
    if result["requires_human"]:
        result["workflow_updates"]["handoff"] = {"required": True, "reason_code": reason}
    result.update(extra)
    return result


def _increment(state: dict, key: str) -> tuple[int, dict]:
    counters = deepcopy(state.get("workflow_state", {}).get("counters", {}))
    turn_id = state.get("turn", {}).get("turn_id")
    counted = counters.setdefault("counted_turn_ids", {})
    if turn_id and counted.get(key) != turn_id:
        counters[key] = _count(counters.get(key)) + 1
        counters["last_counted_turn_id"] = turn_id
        counted[key] = turn_id
    return _count(counters.get(key)), counters


def _clarify(state: dict, config: dict, rule: str, reason: str,
             *, missing: list | None = None, pending: dict | None = None,
             next_step: str = "respond", **extra: Any) -> dict:
    count, counters = _increment(state, "clarification_attempts")
    updates = {"counters": counters, "action": {"authorized": False}}
    if missing is not None:
        updates["missing_fields"] = missing
    if count >= config["max_clarification_attempts"]:
        return _decision(config, rule, "HANDOFF", "clarification_exhausted", updates=updates,
                         clear_pending=True)
    return _decision(config, rule, "CLARIFY", reason, next_step=next_step, updates=updates,
                     pending=pending, pending_ttl_seconds=config["confirmation_ttl_seconds"], **extra)


def _current(state: dict) -> tuple[datetime | None, date | None]:
    turn = state.get("turn", {})
    timestamp = parse_timestamp(turn.get("current_timestamp"))
    try:
        current_date = date.fromisoformat(turn.get("current_date", ""))
    except (ValueError, TypeError):
        current_date = None
    return timestamp, current_date


def _pending_expired(state: dict, config: dict, now: datetime | None) -> bool:
    pending = state.get("workflow_state", {}).get("pending", {})
    runtime = state.get("runtime", {})
    expiry = parse_timestamp(runtime.get("pending_expires_at"))
    created = parse_timestamp(runtime.get("pending_created_at"))
    return (_count(pending.get("turns_waiting")) > config["pending_expiry_turns"] or
            expiry is not None and (now is None or now >= expiry) or
            created is not None and (now is None or (now - created).total_seconds() >= config["confirmation_ttl_seconds"]))


def _trusted_consent(state: dict, config: dict, now: datetime | None) -> bool:
    workflow = state.get("workflow_state", {})
    pending = workflow.get("pending", {})
    event = workflow.get("trusted_confirmation", {})
    verified_at = parse_timestamp(event.get("verified_at"))
    expires_at = parse_timestamp(event.get("expires_at"))
    if (now is None or verified_at is None or expires_at is None or
            not verified_at <= now < expires_at or
            (expires_at - verified_at).total_seconds() > config["confirmation_ttl_seconds"] or
            _pending_expired(state, config, now)):
        return False
    return (event.get("verified") is True and event.get("source") == "host_portal" and
            event.get("bound_identity_verified") is True and
            event.get("bound_action_target_snapshot_verified") is True and
            bool(pending.get("host_pending_handle")) and bool(pending.get("request_id")) and
            event.get("pending_handle") == pending.get("host_pending_handle") and
            event.get("request_id") == pending.get("request_id") and
            pending.get("proposed_action") == "CREATE_COMPLAINT" and
            pending.get("intent") == "TRANSACTION_DISPUTE" and
            bool(pending.get("snapshot_id")) and bool(pending.get("snapshot_hash")) and
            pending.get("snapshot_hash") == workflow.get("candidate_snapshot_hash") and
            pending.get("target_transaction_id") == workflow.get("transaction_id") and
            bool(workflow.get("transaction_id")))


def _target(state: dict) -> dict | None:
    workflow = state.get("workflow_state", {})
    result = state.get("tool_results", {}).get("get_transaction", {})
    transaction = result.get("transaction")
    # get_transaction is an owner-filtered trusted adapter result. An optional
    # customer marker is checked too; raw model fields never enter tool_results.
    if (workflow.get("transaction_identified") is not True or
            workflow.get("transaction_unique") is not True or result.get("status") != "ok" or
            not isinstance(transaction, dict) or
            transaction.get("transaction_id") != workflow.get("transaction_id") or
            not workflow.get("transaction_id")):
        return None
    if transaction.get("customer_id") not in (None, state.get("session", {}).get("customer_id")):
        return None
    search_snapshot = state.get("tool_results", {}).get("search_transactions", {}).get("search_context", {}).get("snapshot_id")
    target_snapshot = result.get("snapshot_id", result.get("snapshot"))
    if target_snapshot is not None and search_snapshot is not None and target_snapshot != search_snapshot:
        return None
    return transaction


def _event_date(transaction: dict) -> date | None:
    value = transaction.get("transaction_date", transaction.get("event_date"))
    try:
        if isinstance(value, str):
            return date.fromisoformat(value[:10])
    except ValueError:
        pass
    return None


def _persistent_duplicate(state: dict, transaction: dict) -> bool:
    result = state.get("tool_results", {}).get("get_transaction", {})
    flags = result.get("data_quality_flags", [])
    signals = result.get("risk_signals", {})
    return (bool(transaction.get("possible_duplicate_of")) or
            transaction.get("conflicting_duplicate") is True or
            signals.get("duplicate_signal") == "persistent" or
            signals.get("possible_duplicate_of") not in (None, False, "") or
            signals.get("conflicting_duplicate") is True or
            any(flag in {"possible_duplicate", "possible_duplicate_of", "conflicting_duplicate"} for flag in flags if isinstance(flag, str)))


def _risk(state: dict, config: dict, now: datetime | None) -> tuple[bool, bool, int | None]:
    workflow = state.get("workflow_state", {})
    results = state.get("tool_results", {})
    signals = results.get("get_transaction", {}).get("risk_signals", {})
    fraud = _number(signals.get("fraud_score"))
    if fraud is not None and fraud > 100:
        fraud = None
    usd = _number(signals.get("amount_usd"))
    report = results.get("get_related_complaints", {}).get("report_window", {})
    start, end = parse_timestamp(report.get("window_start")), parse_timestamp(report.get("window_end"))
    prior = report.get("prior_distinct_verified_count")
    covered = (report.get("scope") == "prototype_sandbox_cases" and
               report.get("coverage_complete") is True and type(prior) is int and prior >= 0 and
               now is not None and start is not None and end is not None and
               start == end - timedelta(hours=24) and
               0 <= (now - end).total_seconds() <= config["risk_evidence_max_age_seconds"])
    count = prior + 1 if covered else None
    # A trusted private aggregate is permitted by the canonical contract; its
    # producer attests current ledger generation/window and excludes this target.
    private = results.get("get_related_complaints", {}).get("private_aggregate", {})
    if not report and private.get("coverage_complete") is True and private.get("generation_verified") is True:
        aggregate = private.get("unrecognized_count_24h")
        if (type(aggregate) is int and aggregate >= 1 and private.get("scope") == "prototype_sandbox_cases" and
                now is not None and parse_timestamp(private.get("verified_at")) is not None and
                0 <= (now - parse_timestamp(private["verified_at"])).total_seconds() <= config["risk_evidence_max_age_seconds"]):
            count = aggregate
            covered = True
    thresholds = config["high_risk"]
    high = (fraud is not None and fraud >= thresholds["fraud_score_threshold"] or
            usd is not None and usd >= thresholds["amount_usd_threshold"] or
            count is not None and count >= thresholds["unrecognized_count_24h"])
    return high, covered and fraud is not None and usd is not None, count


def _exact_case(state: dict, transaction: dict, config: dict) -> dict | None:
    related = state.get("tool_results", {}).get("get_related_complaints", {})
    if related.get("status") != "ok" or related.get("duplicate_check") != "exact_open_case":
        return None
    for complaint in related.get("complaints", []):
        if (isinstance(complaint, dict) and complaint.get("complaint_id") and
                complaint.get("transaction_id") == transaction["transaction_id"] and
                complaint.get("linkage", related.get("match_method")) == "exact_sandbox" and
                complaint.get("customer_id") in (None, state["session"].get("customer_id")) and
                complaint.get("status") in config["open_complaint_statuses"]):
            return complaint
    return None


def _selection_pending(state: dict, candidates: list, candidate_type: str, config: dict) -> dict:
    search = state.get("tool_results", {}).get("search_transactions", {})
    workflow = state.get("workflow_state", {})
    pending = empty_pending()
    pending.update(type="awaiting_selection", candidate_type=candidate_type,
                   candidates=deepcopy(candidates[:config["max_candidates_to_show"]]),
                   snapshot_hash=workflow.get("candidate_snapshot_hash"),
                   snapshot_id=search.get("search_context", {}).get("snapshot_id"),
                   intent=state.get("turn", {}).get("intent"),
                   created_turn_id=state.get("turn", {}).get("turn_id"))
    return pending


def _complaint_snapshot(listing: dict) -> str:
    """Fingerprint only an owned, complete trusted list, independent of transactions."""
    if isinstance(listing.get("snapshot_hash"), str) and listing["snapshot_hash"]:
        return listing["snapshot_hash"]
    return hashlib.sha256(json.dumps({"snapshot_id": listing.get("snapshot_id"),
        "complaints": listing.get("complaints", [])}, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def decide(state: dict, config: dict | None = None) -> dict:
    """Return the first applicable rule and an explicit immutable transition.

    ``next_step`` names only reads, retry/recovery, response, or a portal wait.
    ``await_host_confirmation`` never authorizes a write. Even valid R3 emits a
    host status read; the explicit portal route owns execution and receipts.
    """
    cfg = _config(config)
    session = state.get("session", {})
    turn = state.get("turn", {})
    workflow = state.get("workflow_state", {})
    pending = workflow.get("pending", {})
    results = state.get("tool_results", {})
    now, today = _current(state)
    # R0--R2 guard every private read and all terminal action presentation.
    session_expiry = parse_timestamp(state.get("runtime", {}).get("session_expires_at"))
    if (session.get("authenticated") is not True or session.get("expired") is not False or
            session_expiry is not None and (now is None or now >= session_expiry)):
        return _decision(cfg, "R0", "AUTH_REQUIRED", "authentication_required",
                         updates={"action": {"authorized": False}}, clear_pending=True, clear_target=True)
    attack = turn.get("attack", {})
    if attack.get("deceptive") == 1 or attack.get("inappropriate") == 1:
        return _decision(cfg, "R1", "BLOCKED", "unsafe_request",
                         updates={"action": {"authorized": False}}, security_event=True, clear_pending=True)
    slots = turn.get("slots", {})
    if turn.get("unauthorized_reference") is True or slots.get("foreign_customer_reference") is True:
        return _decision(cfg, "R2", "BLOCKED", "unauthorized_reference",
                         updates={"action": {"authorized": False}}, security_event=True, clear_pending=True)
    # An attempted action remains terminal/recoverable even if its UI pending
    # was cleared, expired, or a new model intent has been classified.
    action = workflow.get("action", {})
    outcome = workflow.get("action_outcome")
    if workflow.get("action_attempted") is True or outcome in {"unknown", "executed", "verified", "failed"}:
        if (action.get("authorized") is True and action.get("executed") is True and
                action.get("verified") is True and action.get("result_id")):
            receipt = results.get("create_complaint", {})
            host_receipt = action.get("receipt", {})
            if (receipt.get("status") == "ok" and receipt.get("complaint_id") == action.get("result_id") and receipt.get("executed") is True or
                    host_receipt.get("verified") is True and host_receipt.get("result_id") == action.get("result_id")):
                return _decision(cfg, "R3", "ACTION_DONE", "action_verified", clear_pending=True)
        if outcome == "failed" and action.get("executed") is not True:
            count, counters = _increment(state, "tool_failures")
            return _decision(cfg, "R9", "HANDOFF" if count >= cfg["max_tool_failures"] else "TOOL_ERROR",
                             "tool_failure", updates={"counters": counters, "action": {"authorized": False}})
        return _decision(cfg, "R3", "ACTION_UNVERIFIED", "action_unverified",
                         next_step="recover_action", updates={"action": {"authorized": False}})
    resolution = turn.get("clarification", {}).get("resolution_type")
    expired = _pending_expired(state, cfg, now)
    trusted = pending.get("type") == "awaiting_confirmation" and not expired and _trusted_consent(state, cfg, now)
    if pending.get("type") == "awaiting_confirmation" and resolution == "DENIED" and not trusted:
        return _decision(cfg, "R4", "ACTION_CANCELLED", "customer_cancelled",
                         updates={"trusted_confirmation": empty_confirmation(), "action": {"authorized": False}},
                         clear_pending=True, clear_target=True)
    if (pending.get("type") != "none" or workflow.get("missing_fields")) and resolution == "NEW_REQUEST":
        # The caller redetects intent on this same original message after reset.
        return _decision(cfg, "R5" if pending.get("type") == "awaiting_selection" else "R4",
                         "CLARIFY", "new_request", next_step="detect_intent", clear_pending=True, clear_target=True,
                         reset_workflow=True)
    if pending.get("type") != "none" and expired:
        return _clarify(state, cfg, "R5" if pending.get("type") == "awaiting_selection" else "R3",
                        "pending_expired", missing=["transaction"], clear_pending=True, clear_target=True)
    selected = pending.get("type") == "awaiting_selection" and resolution == "SELECTED"
    if turn.get("human_requested") is True or turn.get("intent") == "HUMAN_REQUEST" or turn.get("emotional_context") == "Emergencia":
        return _decision(cfg, "R8", "HANDOFF", "emergency" if turn.get("emotional_context") == "Emergencia" else "customer_request", clear_pending=trusted)
    if selected:
        ref = turn.get("clarification", {}).get("selected_ref")
        candidate = next((item for item in pending.get("candidates", [])
                          if isinstance(item, dict) and item.get("ref") == ref and ref is not None), None)
        complaint_selection = pending.get("candidate_type", "transaction") == "complaint"
        expected_hash = (state.get("runtime", {}).get("complaint_snapshot_hash") if complaint_selection
                         else workflow.get("candidate_snapshot_hash"))
        if candidate is None or not pending.get("snapshot_hash") or pending.get("snapshot_hash") != expected_hash:
            return _clarify(state, cfg, "R5", "invalid_selection", clear_pending=True, clear_target=True)
        if state.get("runtime", {}).get("node_errors") or any(
                isinstance(value, dict) and value.get("status") == "error" for value in results.values()):
            # R5 continues from R8, including exhausted read failures at R9.
            return _business(state, cfg, trusted=False, now=now, today=today)
        if complaint_selection:
            complaint_id = candidate.get("complaint_id")
            if not complaint_id:
                return _clarify(state, cfg, "R5", "invalid_selection", clear_pending=True)
            complaint = results.get("get_complaint", {})
            current_snapshot = complaint.get("snapshot_id", complaint.get("snapshot"))
            if current_snapshot is not None and current_snapshot != pending.get("snapshot_id"):
                return _clarify(state, cfg, "R5", "snapshot_changed", clear_pending=True)
            if complaint.get("snapshot_hash") is not None and complaint.get("snapshot_hash") != pending.get("snapshot_hash"):
                return _clarify(state, cfg, "R5", "snapshot_changed", clear_pending=True)
            if complaint.get("status") != "ok" or (complaint.get("complaint") or {}).get("complaint_id") != complaint_id:
                return _decision(cfg, "R5", "CLARIFY", "selected_complaint_revalidation",
                                 next_step="read_complaint", selected_complaint_id=complaint_id)
            local = deepcopy(state)
            local["turn"]["intent"] = "COMPLAINT_STATUS"
            result = _complaints(local, cfg)
            result["selection_consumed"] = True
            return result
        else:
            transaction_id = candidate.get("transaction_id")
            reread = results.get("get_transaction", {})
            target = reread.get("transaction") or {}
            snapshot = reread.get("snapshot_id", reread.get("snapshot"))
            if snapshot is not None and pending.get("snapshot_id") != snapshot:
                return _clarify(state, cfg, "R5", "snapshot_changed", clear_pending=True, clear_target=True)
            if isinstance(target, dict) and target.get("customer_id") not in (None, session.get("customer_id")):
                return _decision(cfg, "R9", "TOOL_ERROR", "target_binding_mismatch", clear_pending=True, clear_target=True)
            if reread.get("snapshot_hash") is not None and reread.get("snapshot_hash") != pending.get("snapshot_hash"):
                return _clarify(state, cfg, "R5", "snapshot_changed", clear_pending=True, clear_target=True)
            if (not transaction_id or reread.get("status") != "ok" or target.get("transaction_id") != transaction_id):
                return _decision(cfg, "R5", "CLARIFY", "selected_target_revalidation", next_step="read_target",
                                 selected_transaction_id=transaction_id,
                                 updates={"transaction_id": transaction_id, "transaction_unique": False,
                                          "transaction_identified": False})
            # Continue from R8 using a local canonical projection; caller state
            # and original match_count are deliberately untouched.
            local = deepcopy(state)
            local["workflow_state"].update(transaction_id=transaction_id, transaction_unique=True,
                                           transaction_identified=True)
            local["workflow_state"]["pending"] = empty_pending()
            local["turn"]["intent"] = pending.get("intent") or turn.get("intent")
            result = _business(local, cfg, trusted=False, now=now, today=today)
            result["workflow_updates"].update(transaction_id=transaction_id, transaction_unique=True,
                                               transaction_identified=True, pending=empty_pending())
            result["selection_consumed"] = True
            return result
    if pending.get("type") == "awaiting_confirmation" and not trusted:
        if workflow.get("trusted_confirmation", {}).get("verified") is True:
            return _clarify(state, cfg, "R3", "stale_host_confirmation", clear_pending=True, clear_target=True)
        return _clarify(state, cfg, "R3", "host_confirmation_required", next_step="await_host_confirmation")
    if pending.get("type") == "awaiting_selection" and not selected:
        return _clarify(state, cfg, "R5", "selection_required")
    active = (pending.get("type") != "none" or workflow.get("transaction_id") or workflow.get("missing_fields") or
              state.get("runtime", {}).get("workflow_intent") in BUSINESS_INTENTS or
              state.get("runtime", {}).get("node_errors"))
    if not active and turn.get("intent") in {"GREETING", "PERSONALITY"}:
        return _decision(cfg, "R6", "SMALL_TALK", "small_talk")
    if not active and turn.get("intent") == "OOD":
        return _decision(cfg, "R7", "OUT_OF_SCOPE", "out_of_scope")
    result = _business(state, cfg, trusted=trusted, now=now, today=today)
    if trusted and result["reason_code"] != "host_consent_verified":
        result["clear_pending"] = True
        result["workflow_updates"]["trusted_confirmation"] = empty_confirmation()
        result["workflow_updates"].setdefault("action", {})["authorized"] = False
    return result


def _business(state: dict, cfg: dict, *, trusted: bool, now: datetime | None,
              today: date | None) -> dict:
    turn = state.get("turn", {})
    workflow = state.get("workflow_state", {})
    results = state.get("tool_results", {})
    slots = turn.get("slots", {})
    intent = turn.get("intent")
    if intent not in BUSINESS_INTENTS:
        intent = workflow.get("pending", {}).get("intent") or state.get("runtime", {}).get("workflow_intent") or intent
    if turn.get("human_requested") is True or intent == "HUMAN_REQUEST" or turn.get("emotional_context") == "Emergencia":
        return _decision(cfg, "R8", "HANDOFF", "emergency" if turn.get("emotional_context") == "Emergencia" else "customer_request")
    # R9 includes node failures, not just explicit tool-result envelopes.
    errors = state.get("runtime", {}).get("node_errors", [])
    failed = [(name, result) for name, result in results.items()
              if isinstance(result, dict) and result.get("status") == "error"]
    if errors or failed:
        retry = next(((name, result) for name, result in failed
                      if (result.get("retryable") is True or result.get("error", {}).get("retryable") is True) and result.get("retries_exhausted") is not True and
                      _count(result.get("retry_count")) < cfg["tool_retries"]), None)
        if retry and not errors:
            return _decision(cfg, "R9", "TOOL_ERROR", "tool_retry", next_step="retry_tool", tool_name=retry[0])
        count, counters = _increment(state, "tool_failures")
        return _decision(cfg, "R9", "HANDOFF" if count >= cfg["max_tool_failures"] else "TOOL_ERROR",
                         "tool_failure", updates={"counters": counters, "action": {"authorized": False}})
    if intent == "COMPLAINT_STATUS":
        return _complaints(state, cfg)
    if intent not in TRANSACTION_INTENTS:
        return _decision(cfg, "R7", "OUT_OF_SCOPE", "out_of_scope")
    if slots.get("currency") is None and str(slots.get("currency_raw") or "").strip().casefold() in {"$", "peso", "pesos"}:
        return _clarify(state, cfg, "R10", "ambiguous_currency", missing=["currency"], workflow_intent=intent)
    if workflow.get("search_criteria_present") is not True:
        return _clarify(state, cfg, "R10", "missing_search_criteria", missing=["amount", "date"], workflow_intent=intent)
    search = results.get("search_transactions", {})
    if not search:
        return _decision(cfg, "R10", "CLARIFY", "search_required", next_step="search_transactions", workflow_intent=intent)
    if search.get("status") != "ok":
        return _decision(cfg, "R9", "TOOL_ERROR", "invalid_search_evidence")
    count = search.get("match_count")
    candidates = search.get("candidates")
    if (type(count) is not int or count < 0 or not isinstance(candidates, list) or
            search.get("search_context", {}).get("coverage_complete") is not True or
            count < len(candidates)):
        return _decision(cfg, "R9", "HANDOFF", "missing_evidence")
    if count == 0:
        attempts, counters = _increment(state, "no_match_attempts")
        return _decision(cfg, "R11", "HANDOFF" if attempts >= cfg["max_no_match_attempts"] else "NO_MATCH",
                         "no_match_exhausted" if attempts >= cfg["max_no_match_attempts"] else "no_match",
                         updates={"counters": counters}, workflow_intent=intent)
    target = _target(state)
    if count > 1 and target is None:
        if count > cfg["max_candidates_to_show"]:
            return _clarify(state, cfg, "R12", "filter_required", missing=["additional_filter"], workflow_intent=intent)
        if len(candidates) != count or not workflow.get("candidate_snapshot_hash"):
            return _decision(cfg, "R12", "HANDOFF", "missing_evidence")
        pending = _selection_pending(state, candidates, "transaction", cfg)
        return _clarify(state, cfg, "R12", "multiple_transactions", pending=pending, workflow_intent=intent)
    if target is None:
        return _decision(cfg, "R12", "CLARIFY", "target_revalidation_required", next_step="read_target",
                         selected_transaction_id=workflow.get("transaction_id") or (candidates[0].get("transaction_id") if candidates else None))
    if _persistent_duplicate(state, target):
        return _decision(cfg, "R12", "HANDOFF", "duplicate_review")
    event = _event_date(target)
    if intent == "TRANSACTION_INQUIRY":
        if event is None or today is None or event > today:
            return _decision(cfg, "R13", "HANDOFF", "missing_evidence")
        return _decision(cfg, "R13", "INFORM", "transaction_observed")
    status = target.get("transaction_status", target.get("status"))
    missing = [key for key in ("transaction_date", "amount", "currency", "transaction_status")
               if (event is None if key == "transaction_date" else
                   status in (None, "") if key == "transaction_status" else target.get(key) in (None, ""))]
    if missing:
        return _clarify(state, cfg, "R14", "missing_transaction_fields", missing=missing, workflow_intent=intent)
    if today is None or event > today:
        return _decision(cfg, "R14", "HANDOFF", "missing_evidence", clear_pending=trusted)
    if (today - event).days > cfg["dispute_window_days"] or status not in cfg["allowed_transaction_statuses"]:
        return _decision(cfg, "R14", "OUT_OF_POLICY", "out_of_policy", offer_handoff=True, clear_pending=trusted)
    related = results.get("get_related_complaints", {})
    if not related:
        return _decision(cfg, "R15", "CLARIFY", "duplicate_check_required", next_step="read_related_complaints")
    case = _exact_case(state, target, cfg)
    if case:
        return _decision(cfg, "R15", "INFORM_EXISTING_CASE", "exact_open_case",
                         updates={"existing_case": {"found": True, "complaint_id": case["complaint_id"], "status": case["status"]}},
                         clear_pending=trusted)
    if related.get("status") != "ok" or related.get("duplicate_check") != "clear_in_snapshot":
        return _decision(cfg, "R15", "HANDOFF", "missing_evidence", clear_pending=trusted)
    high, complete, count24 = _risk(state, cfg, now)
    risk_updates = {"unrecognized_count_24h": count24, "risk_data_complete": complete}
    if high:
        return _decision(cfg, "R16", "HANDOFF", "high_risk", updates=risk_updates, clear_pending=trusted)
    if not complete:
        return _decision(cfg, "R16", "HANDOFF", "missing_evidence", updates=risk_updates, clear_pending=trusted)
    if trusted:
        pending = workflow["pending"]
        snapshot = results.get("get_transaction", {}).get("snapshot_id", results.get("get_transaction", {}).get("snapshot"))
        if snapshot != pending.get("snapshot_id"):
            return _decision(cfg, "R3", "HANDOFF", "missing_evidence", clear_pending=True, clear_target=True)
        # Portal execution remains host-only. This decision consumes no chat
        # consent and does not expose any bank write transition.
        return _decision(cfg, "R3", "CONFIRM_ACTION", "host_consent_verified", next_step="read_host_action_status",
                         updates={**risk_updates, "action": {"authorized": True, "name": "CREATE_COMPLAINT",
                             "idempotency_key": pending["request_id"],
                             "authorization_expires_at": workflow["trusted_confirmation"]["expires_at"]}})
    pending = empty_pending()
    pending.update(type="awaiting_confirmation", proposed_action="CREATE_COMPLAINT",
                   target_transaction_id=target["transaction_id"], intent=intent,
                   created_turn_id=turn.get("turn_id"), snapshot_hash=workflow.get("candidate_snapshot_hash"),
                   snapshot_id=search.get("search_context", {}).get("snapshot_id"))
    if not pending["snapshot_id"] or not pending["snapshot_hash"]:
        return _decision(cfg, "R17", "HANDOFF", "missing_evidence")
    return _decision(cfg, "R17", "CONFIRM_ACTION", "portal_confirmation_required", next_step="await_host_confirmation",
                     updates={**risk_updates, "action": {"authorized": False}}, pending=pending,
                     pending_ttl_seconds=cfg["confirmation_ttl_seconds"], workflow_intent=intent)


def _complaints(state: dict, cfg: dict) -> dict:
    results = state.get("tool_results", {})
    turn = state.get("turn", {})
    pending = state.get("workflow_state", {}).get("pending", {})
    complaint_id = turn.get("slots", {}).get("complaint_id")
    if pending.get("candidate_type") == "complaint" and turn.get("clarification", {}).get("resolution_type") == "SELECTED":
        ref = turn["clarification"].get("selected_ref")
        candidate = next((x for x in pending.get("candidates", []) if x.get("ref") == ref), {})
        complaint_id = candidate.get("complaint_id")
    if complaint_id:
        reread = results.get("get_complaint", {})
        if not reread:
            return _decision(cfg, "R18", "CLARIFY", "complaint_read_required", next_step="read_complaint", selected_complaint_id=complaint_id)
        complaint = reread.get("complaint")
        if (reread.get("status") != "ok" or not isinstance(complaint, dict) or
                complaint.get("complaint_id") != complaint_id or
                complaint.get("customer_id") not in (None, state["session"].get("customer_id"))):
            return _decision(cfg, "R18", "NO_MATCH", "complaint_not_found")
        return _decision(cfg, "R18", "INFORM", "complaint_observed", clear_pending=True)
    listing = results.get("list_customer_complaints", {})
    if not listing:
        return _decision(cfg, "R18", "CLARIFY", "complaint_list_required", next_step="list_complaints")
    count, complaints = listing.get("match_count"), listing.get("complaints")
    if (listing.get("status") != "ok" or type(count) is not int or count < 0 or
            not isinstance(complaints, list) or count != len(complaints) or
            listing.get("coverage_complete") is not True):
        return _decision(cfg, "R18", "HANDOFF", "missing_evidence")
    if count == 0:
        return _decision(cfg, "R18", "NO_MATCH", "complaint_not_found")
    if count == 1:
        # A complete owned list is sufficient to show its observed status;
        # an explicit selected ID always takes the reread branch above.
        return _decision(cfg, "R18", "INFORM", "complaint_observed")
    if count > cfg["max_candidates_to_show"]:
        return _clarify(state, cfg, "R18", "filter_required", missing=["additional_filter"])
    candidates = [{"ref": str(i + 1), "complaint_id": item.get("complaint_id"),
                   "label": item.get("label", item.get("status", ""))}
                  for i, item in enumerate(complaints)]
    pending = _selection_pending(state, candidates, "complaint", cfg)
    digest = _complaint_snapshot(listing)
    pending.update(snapshot_hash=digest, snapshot_id=listing.get("snapshot_id") or listing.get("snapshot_hash") or digest,
                   intent="COMPLAINT_STATUS")
    return _clarify(state, cfg, "R18", "multiple_complaints", pending=pending, workflow_intent="COMPLAINT_STATUS",
                    complaint_snapshot_hash=digest)
