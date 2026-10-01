"""Assemble private human-review packets from independently verified host evidence.

The bank host must establish query/request/target ownership and stamp
``runtime.handoff_lineage`` before calling. Native display references are never
treated as workflow target identities. This module performs no bank writes.
"""
from __future__ import annotations

from copy import deepcopy
import math
import re
import uuid

from frontend.server.action import verified_handoff, verified_receipt
from .policy import _receipt_facts_match, _risk, load_config
from .prompts import build_stage_inputs
from .response import validate_handoff_summary
from .state import StateError, TrustedBinding, _assert_session, _scope_map, parse_timestamp


class HandoffError(ValueError):
    """Fixed error codes contain no customer data or capability values."""


def _fallback(language):
    description = {"es": "de habla española", "pt": "de habla portuguesa", "other": "de otro idioma"}[language]
    return {"request_summary": f"Cliente {description} solicita revisión humana.",
            "customer_language": language, "customer_stated_claims": [], "suggested_open_questions": []}


def _narrative(state, native, binding):
    language = state["turn"].get("language")
    language = language if language in {"es", "pt", "other"} else "other"
    fallback = _fallback(language)
    # Risk and stale action flags never become narrative inputs. The saved native
    # facts are the only factual authority for this packet's original snapshot.
    inputs = build_stage_inputs("generate_handoff_summary", state, language=language,
        historic_conversation="", structured_data={"status": "ok", "transaction": native["facts"],
            "data_sources": ["owned_serving_snapshot"]},
        workflow_state={"policy_decision": state["workflow_state"].get("policy_decision", {})})
    candidate = state["runtime"].get("handoff_narrative")
    private_ids = binding.key()

    def valid(value):
        if not isinstance(value, dict) or validate_handoff_summary(value, inputs):
            return False
        texts = [value["request_summary"], *value["customer_stated_claims"], *value["suggested_open_questions"]]
        return not any(identifier in text for text in texts for identifier in private_ids if len(identifier) >= 4)

    narrative = deepcopy(candidate) if valid(candidate) else fallback
    questions = []
    facts = native["facts"]
    repeated = {"amount": r"\b(?:monto|importe|valor|cu[aá]nto)\b",
        "currency": r"\b(?:moneda|moeda|currency)\b", "transaction_date": r"\b(?:fecha|data|cu[aá]ndo)\b",
        "merchant": r"\b(?:comercio|establecimiento|loja|merchant)\b",
        "channel": r"\b(?:canal|channel)\b", "product": r"\b(?:producto|produto)\b",
        "status": r"\bestado\b.*\b(?:cargo|compra|movimiento|transacci[oó]n)\b"}
    for question in native["unanswered_questions"] + narrative["suggested_open_questions"]:
        check = {**fallback, "suggested_open_questions": [question]}
        if (not valid(check) or any(facts.get(field) not in (None, "") and re.search(pattern, question, re.I)
                                   for field, pattern in repeated.items())):
            continue
        if question not in questions:
            questions.append(question)
        if len(questions) == 4:
            break
    return narrative, questions


def assemble_handoff_packet(state: dict, native: dict, *, binding: TrustedBinding) -> dict:
    """Return a complete internal packet without promoting any action/UI state.

    The trusted host's lineage must include query_id, binding_digest, request_id,
    handoff_id, target_transaction_id, snapshot_id and snapshot_hash. General
    review uses null target/snapshot/hash. Bank readback remains authoritative;
    this result still requires durable host persistence and independent readback.
    """
    try:
        _assert_session(binding, state)
        scopes, _ = _scope_map(state)
        runtime, workflow, turn = state["runtime"], state["workflow_state"], state["turn"]
        now = parse_timestamp(turn.get("current_timestamp"))
        if (runtime.get("trusted_binding_digest") != binding.digest() or
                parse_timestamp(runtime.get("session_expires_at")) != parse_timestamp(binding.expires_at) or
                not binding.authenticated or state["session"].get("authenticated") is not True or
                state["session"].get("expired") is not False or now is None or binding.expired(now)):
            raise HandoffError("handoff_binding_mismatch")
        query_id = runtime.get("active_query_id") if scopes else None
        if scopes and (query_id not in scopes or turn.get("active_query_index") != scopes[query_id]["query_index"]):
            raise HandoffError("handoff_query_mismatch")
        lineage = runtime.get("handoff_lineage", {})
        required = {"query_id", "binding_digest", "handoff_id", "request_id", "target_transaction_id", "snapshot_id", "snapshot_hash"}
        if (not isinstance(lineage, dict) or not required <= lineage.keys() or lineage.get("binding_digest") != binding.digest() or
                lineage.get("query_id") != query_id or not isinstance(lineage.get("request_id"), str) or
                str(uuid.UUID(lineage["request_id"])) != lineage["request_id"]):
            raise HandoffError("handoff_lineage_mismatch")
        if ("host_pending_handle" in lineage and lineage["host_pending_handle"] is not None and
                (not isinstance(lineage["host_pending_handle"], str) or not lineage["host_pending_handle"])):
            raise HandoffError("handoff_lineage_mismatch")
        checked = verified_handoff(native)
        if not checked or not isinstance(native.get("packet"), dict):
            raise HandoffError("invalid_native_handoff")
        if lineage.get("handoff_id") != checked["id"] or lineage.get("snapshot_id") != checked["snapshot"]:
            raise HandoffError("handoff_lineage_mismatch")
        decision = workflow.get("policy_decision", {})
        rules = decision.get("rule_ids")
        if (decision.get("reason_code") != checked["reason"] or
                workflow.get("handoff", {}).get("reason_code") not in (None, checked["reason"]) or
                not isinstance(rules, list) or not rules or len(rules) > 19 or
                any(not isinstance(rule, str) or not re.fullmatch(r"R(?:[0-9]|1[0-8])", rule) for rule in rules)):
            raise HandoffError("handoff_reason_mismatch")
        target = lineage.get("target_transaction_id")
        pending = workflow.get("pending", {})
        if checked["snapshot"] is None:
            if target is not None or lineage.get("snapshot_hash") is not None or workflow.get("transaction_id"):
                raise HandoffError("handoff_target_mismatch")
        elif (not isinstance(target, str) or not target or target != workflow.get("transaction_id") or
              not isinstance(lineage.get("snapshot_hash"), str) or not lineage["snapshot_hash"]):
            raise HandoffError("handoff_target_mismatch")
        if checked["transaction_currentness"] == "same_snapshot":
            expected_hash = pending.get("snapshot_hash") if pending.get("snapshot_id") == checked["snapshot"] else workflow.get("candidate_snapshot_hash")
            if expected_hash != lineage.get("snapshot_hash"):
                raise HandoffError("handoff_snapshot_mismatch")
        for key, expected in (("query_id", query_id), ("binding_digest", binding.digest()),
                              ("target_transaction_id", target), ("handoff_id", checked["id"])):
            if key in native and native[key] != expected:
                raise HandoffError("handoff_lineage_mismatch")
        narrative, questions = _narrative(state, checked, binding)
        facts = [{"field": field, "value": deepcopy(value), "source": "owned_serving_snapshot"}
                 for field, value in checked["facts"].items()]
        evidence = [{"source": "sandbox_handoffs", "id": checked["id"]}]
        if checked["snapshot"]:
            evidence.append({"source": "owned_serving_snapshot", "id": checked["snapshot"]})
        actions = [{"action": "create_verified_handoff", "result": {"handoff_id": checked["id"], "verified": True,
                                                                    "human_responded": False}}]
        tools = state.get("tool_results", {})
        reread = tools.get("get_transaction", {})
        row = reread.get("transaction", {})
        owned_read = (checked["transaction_currentness"] == "same_snapshot" and target and
            reread.get("status") == "ok" and isinstance(row, dict) and row.get("transaction_id") == target and
            row.get("customer_id") in (None, binding.customer_id) and
            reread.get("snapshot_id", reread.get("snapshot")) == checked["snapshot"] and
            _receipt_facts_match(checked["facts"], row))
        for key in ("verified_at", "observed_at"):
            if key in reread:
                observed = parse_timestamp(reread[key])
                owned_read = owned_read and observed is not None and 0 <= (now - observed).total_seconds() <= 20
        risk = {}
        if owned_read:
            actions.append({"action": "get_transaction", "result": "owned_snapshot_verified"})
            signals = reread.get("risk_signals", {})
            if isinstance(signals, dict):
                for key, maximum in (("fraud_score", 100), ("amount_usd", math.inf)):
                    value = signals.get(key)
                    if type(value) in (int, float) and math.isfinite(value) and 0 <= value <= maximum:
                        risk[key] = value
                fraud = signals.get("is_fraud", row.get("is_fraud"))
                if type(fraud) is bool:
                    risk["is_fraud"] = fraud
            related = tools.get("get_related_complaints", {})
            if isinstance(related, dict) and related.get("status") == "ok":
                try:
                    _, _, count = _risk(state, {**load_config(), "risk_evidence_max_age_seconds": 20}, now)
                except (ValueError, TypeError, AttributeError):
                    count = None
                if count is not None:
                    risk["unrecognized_count_24h"] = count
        # Cached action flags and narrative claims never establish an intake.
        status = tools.get("host_action_status", {})
        receipt = verified_receipt(status.get("receipt")) if isinstance(status, dict) else None
        action_lineage = runtime.get("action_lineage", {})
        proof = status.get("binding", {}) if isinstance(status, dict) else {}
        canonical = status.get("action") if isinstance(status, dict) else None
        canonical_ok = True
        if "action" in status:
            canonical_receipt = canonical.get("receipt", {}) if isinstance(canonical, dict) else {}
            canonical_ok = bool(receipt and isinstance(canonical, dict) and isinstance(canonical_receipt, dict) and
                canonical.get("name") == "CREATE_COMPLAINT" and canonical.get("result_id") == receipt["id"] and
                all(canonical.get(key) is True for key in ("authorized", "executed", "verified")) and
                canonical_receipt.get("verified") is True and canonical_receipt.get("result_id") == receipt["id"])
            if canonical_ok:
                for projection in (canonical, canonical_receipt):
                    for key, expected in (("snapshot", checked["snapshot"]), ("snapshot_id", checked["snapshot"]),
                        ("snapshot_hash", lineage["snapshot_hash"]), ("transaction_id", target),
                        ("target_reference", target), ("target_transaction_id", target)):
                        if key in projection and projection[key] != expected:
                            canonical_ok = False
                    if "transaction" in projection and not _receipt_facts_match(projection["transaction"], checked["facts"]):
                        canonical_ok = False
        if (receipt and status.get("status") == "ok" and status.get("state") == "intake_verified" and
                canonical_ok and status.get("verified", True) is True and status.get("binding_verified") is True and status.get("query_id") == query_id and
                isinstance(proof, dict) and all(proof.get(key) == getattr(binding, key) for key in
                    ("owner", "customer_id", "session_id", "conversation_id")) and
                parse_timestamp(proof.get("expires_at")) == parse_timestamp(binding.expires_at) and
                action_lineage.get("query_id") == query_id and action_lineage.get("binding_digest") == binding.digest() and
                action_lineage.get("request_id") and action_lineage.get("request_id") == status.get("request_id") and
                action_lineage.get("host_pending_handle") and action_lineage.get("host_pending_handle") == status.get("pending_handle") and
                action_lineage.get("target_transaction_id") == target and status.get("target_reference") == target and
                action_lineage.get("snapshot_id") == checked["snapshot"] and action_lineage.get("snapshot_hash") == lineage["snapshot_hash"] and
                status.get("snapshot") == checked["snapshot"] and status.get("snapshot_hash", lineage["snapshot_hash"]) == lineage["snapshot_hash"] and
                receipt["snapshot"] == checked["snapshot"] and receipt["transaction"] == checked["facts"]):
            actions.append({"action": "CREATE_COMPLAINT", "result": {"verified": True, "result_id": receipt["id"]}})
            evidence.append({"source": "sandbox_cases", "id": receipt["id"]})
        elif workflow.get("action_attempted") is True:
            actions.append({"action": "CREATE_COMPLAINT", "result": {"verified": False, "outcome": "unverified"}})
        native_projection = deepcopy(checked)
        native_projection["packet"] = deepcopy(native["packet"])
        result = {"schema": "gloria-human-handoff/v1", "handoff_id": checked["id"],
            "created_at": checked["created_at"], "reason_code": checked["reason"], "rule_ids": list(dict.fromkeys(rules)),
            "query_id": query_id, "binding_digest": binding.digest(), "target_transaction_id": target,
            "snapshot_id": checked["snapshot"], "request_summary": narrative["request_summary"],
            "customer_language": narrative["customer_language"], "verified_facts": facts,
            "customer_stated_claims": deepcopy(narrative["customer_stated_claims"]), "actions_taken": actions,
            "evidence": evidence, "open_questions": questions, "human_responded": False,
            "native_handoff": native_projection}
        if risk:
            result["risk_signals"] = risk
        return result
    except HandoffError:
        raise
    except (StateError, ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise HandoffError("handoff_evidence_invalid") from None
