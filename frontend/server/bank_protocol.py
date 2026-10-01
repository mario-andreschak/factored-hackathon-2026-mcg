"""Strict delegated action results; public trimming cannot establish authority."""
from __future__ import annotations

from datetime import datetime

from .action import public_facts, verified_handoff, verified_receipt
from .bank_rpc import BankRPCError


def _utc(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return isinstance(value, str) and len(value) <= 40 and parsed.utcoffset().total_seconds() == 0
    except (AttributeError, TypeError, ValueError, OverflowError):
        return False


def _receipt(value):
    return (isinstance(value, dict) and set(value) == {
        "id", "kind", "simulated", "snapshot", "created_at", "status", "transaction"}
        and _utc(value.get("created_at")) and verified_receipt(value) is not None)


def _handoff(value):
    return (isinstance(value, dict) and set(value) == {
        "id", "reason", "snapshot", "created_at", "facts", "packet", "transaction_currentness", "human_responded"}
        and _utc(value.get("created_at")) and verified_handoff(value) is not None)


def _existing(value, facts):
    return (isinstance(value, dict) and set(value) == {"state", "receipt", "coverage", "source"}
        and value["state"] in {"verified", "not_found", "action_unverified"}
        and value["coverage"] == "sandbox_only" and value["source"] == "sandbox_cases"
        and ((value["state"] == "verified" and _receipt(value["receipt"])
              and value["receipt"]["transaction"] == facts)
             or (value["state"] != "verified" and value["receipt"] is None)))


def _risk(value, decision):
    if (not isinstance(value, dict) or set(value) != {"unrecognized_count_24h", "risk_data_complete", "coverage", "source", "window_start", "window_end"}
            or type(value["risk_data_complete"]) is not bool
            or value["coverage"] != "sandbox_only" or value["source"] != "sandbox_cases"
            or not _utc(value["window_start"]) or not _utc(value["window_end"])):
        return False
    count, complete = value["unrecognized_count_24h"], value["risk_data_complete"]
    if (complete and (type(count) is not int or count < 1)) or (not complete and count is not None):
        return False
    start = datetime.fromisoformat(value["window_start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(value["window_end"].replace("Z", "+00:00"))
    if (end - start).total_seconds() != 86400:
        return False
    return decision != "intake" or complete and count in {1, 2}


def _validate(tool: str, result: object) -> dict:
    """Reject mode flags, extra fields and contradictions before branching/writes."""
    valid = isinstance(result, dict) and result.get("synthetic") is False and result.get("operator_test") is False
    if valid and tool == "prepare_unrecognized_charge":
        valid = set(result) == {"pending_handle", "snapshot", "action", "decision", "reason",
            "transaction", "existing_case", "risk", "synthetic", "operator_test"}
        if valid:
            facts, existing, risk = result["transaction"], result["existing_case"], result["risk"]
            decision, reason = result["decision"], result["reason"]
            valid = (public_facts(facts) is not None and _existing(existing, facts)
                and decision in {"intake", "handoff", "existing_case"}
                and (reason is None or reason in {"missing_evidence", "high_risk", "out_of_policy", "duplicate_review", "action_unverified"})
                and (decision == "existing_case") == (existing["state"] == "verified")
                and (decision == "handoff") == (reason is not None)
                and (existing["state"] != "action_unverified" or decision == "handoff" and reason == "action_unverified")
                and _risk(risk, decision))
    elif valid and tool in {"confirm_simulated_intake", "read_intake_receipt"}:
        valid = (set(result) == {"state", "receipt", "synthetic", "operator_test"}
            and ((result["state"] == "created" and _receipt(result["receipt"]))
                 or (result["state"] == "action_unverified" and result["receipt"] is None)))
    elif valid and tool in {"create_verified_handoff", "read_verified_handoff"}:
        valid = (set(result) == {"state", "handoff", "synthetic", "operator_test"}
                 and result["state"] == "created" and _handoff(result["handoff"]))
    else:
        valid = False
    if not valid:
        raise BankRPCError("bank_invalid_response", possibly_sent=True)
    return result


def validate_action_result(tool: str, result: object) -> dict:
    try:
        return _validate(tool, result)
    except (TypeError, KeyError, ValueError, OverflowError, RecursionError):
        raise BankRPCError("bank_invalid_response", possibly_sent=True) from None
