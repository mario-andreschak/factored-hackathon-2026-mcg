"""Query capabilities remain independent even for identical source transactions."""
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest

from gloria_workflow.policy import decide
from gloria_workflow.state import (activate_query_scope, apply_decision, begin_turn,
    checkpoint_query_scope, reset_workflow, start_query_batch, StateError)
_spec = importlib.util.spec_from_file_location("gloria_query_helpers", Path(__file__).with_name("test_gloria_policy.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
BINDING, NOW, confirming, ready_state = _helpers.BINDING, _helpers.NOW, _helpers.confirming, _helpers.ready_state


def scoped_ready():
    state = ready_state()
    state = start_query_batch(state, [{"query_text": "cargo A", "domain": "TRANSACTION_DISPUTE"},
                                     {"query_text": "cargo B", "domain": "TRANSACTION_DISPUTE"}])
    first, second = state["runtime"]["query_scope_order"]
    state = activate_query_scope(state, BINDING, first, now=NOW)
    ready = ready_state()
    for key in ("workflow_state", "tool_results"):
        state[key] = deepcopy(ready[key])
    state["turn"].update(intent="TRANSACTION_DISPUTE", slots=deepcopy(ready["turn"]["slots"]))
    return state, first, second


def scoped_confirmation():
    state, first, second = scoped_ready()
    state = confirming(state, trusted=True)
    state["workflow_state"]["trusted_confirmation"]["query_id"] = first
    state = checkpoint_query_scope(state)
    return state, first, second


def scoped_done(*, native=False):
    state, first, second = scoped_confirmation()
    lineage = state["runtime"]["action_lineage"]
    result_id = "CMP-SBX-Test0001"
    action = {"name": "CREATE_COMPLAINT", "authorized": True, "executed": True,
              "verified": True, "result_id": result_id,
              "receipt": {"verified": True, "result_id": result_id}}
    state["workflow_state"].update(action=deepcopy(action), action_attempted=True, action_outcome="verified")
    status = {"status": "ok", "state": "intake_verified", "binding_verified": True, "query_id": first,
              "binding": {"owner": BINDING.owner, "customer_id": BINDING.customer_id,
                          "session_id": BINDING.session_id, "conversation_id": BINDING.conversation_id,
                          "expires_at": BINDING.expires_at.isoformat()},
              "request_id": lineage["request_id"], "pending_handle": lineage["host_pending_handle"],
              "target_reference": lineage["target_transaction_id"], "snapshot": lineage["snapshot_id"],
              "action": deepcopy(action)}
    if native:
        target = state["tool_results"]["get_transaction"]["transaction"]
        status["receipt"] = {"id": result_id, "kind": "simulated_intake", "simulated": True,
            "status": "received", "snapshot": lineage["snapshot_id"], "created_at": NOW.isoformat(),
            "transaction": {"transaction_reference": "txn_" + "a" * 12,
                            "amount": str(target["amount"]), "currency": target["currency"],
                            "transaction_date": target["transaction_date"], "status": target["status"],
                            "process_date": "2026-09-16", "merchant": None,
                            "transaction_type": "", "channel": "", "product": ""}}
    state["tool_results"]["host_action_status"] = status
    return state, first, second


def test_exact_query_consent_requests_only_host_read_and_exact_receipt_completes():
    state, _, _ = scoped_confirmation()
    decision = decide(state)
    assert decision["reason_code"] == "host_consent_verified"
    assert decision["next_step"] == "read_host_action_status"
    state, _, _ = scoped_done()
    assert decide(state)["response_mode"] == "ACTION_DONE"
    state, _, _ = scoped_done(native=True)
    assert decide(state)["response_mode"] == "ACTION_DONE"
    del state["tool_results"]["host_action_status"]["action"]
    assert decide(state)["response_mode"] == "ACTION_DONE"


@pytest.mark.parametrize("record", ["pending", "trusted_confirmation"])
def test_sibling_consent_or_pending_cannot_be_consumed(record):
    state, _, second = scoped_confirmation()
    state["workflow_state"][record]["query_id"] = second
    decision = decide(state)
    assert decision["reason_code"] != "host_consent_verified"
    assert decision["workflow_updates"].get("action", {}).get("authorized") is not True


@pytest.mark.parametrize("field,value", [
    ("query_id", "q_" + "a" * 32), ("request_id", "sibling-request"),
    ("pending_handle", "sibling-handle"), ("target_reference", "TRX-other"),
    ("snapshot", "snapshot-other"), ("snapshot_hash", "hash-other"), ("binding_verified", False),
    ("status", "error"), ("verified", False),
])
def test_receipt_query_request_handle_target_and_snapshot_each_bind_independently(field, value):
    state, _, _ = scoped_done()
    state["tool_results"]["host_action_status"][field] = value
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("field", ["owner", "customer_id", "session_id", "conversation_id", "expires_at"])
def test_receipt_binding_must_match_current_server_session(field):
    state, _, _ = scoped_done()
    state["tool_results"]["host_action_status"]["binding"][field] = "foreign"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("field", ["query_id", "binding_digest"])
def test_pure_policy_rejects_an_inconsistent_active_capsule_before_store_validation(field):
    state, first, _ = scoped_done()
    state["runtime"]["query_scopes"][first][field] = "foreign"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


def test_same_target_and_snapshot_do_not_make_sibling_receipt_an_execution_proof():
    state, first, second = scoped_done()
    original = deepcopy(state)
    state = checkpoint_query_scope(state)
    state = activate_query_scope(state, BINDING, second, now=NOW)
    # Identical own target and source snapshot, plus copied success facts. The
    # fresh query still has no request/portal-handle lineage of its own.
    state["workflow_state"] = deepcopy(original["workflow_state"])
    state["workflow_state"]["pending"] = {"type": "none"}
    state["tool_results"] = deepcopy(original["tool_results"])
    state["tool_results"]["host_action_status"]["query_id"] = second
    assert "action_lineage" not in state["runtime"]
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"
    state["runtime"]["action_lineage"] = deepcopy(original["runtime"]["action_lineage"])
    assert state["runtime"]["action_lineage"]["query_id"] == first
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("field,value", [
    ("id", "CMP-SBX-Other001"), ("snapshot", "other-snapshot"), ("amount", "999"),
    ("currency", "COP"), ("status", "Denied"), ("transaction_date", "2026-09-16"),
])
def test_mixed_native_canonical_receipt_contradictions_never_complete(field, value):
    state, _, _ = scoped_done(native=True)
    receipt = state["tool_results"]["host_action_status"]["receipt"]
    (receipt if field in {"id", "snapshot"} else receipt["transaction"])[field] = value
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


def test_malformed_native_receipt_cannot_be_rescued_by_valid_canonical_receipt():
    state, _, _ = scoped_done(native=True)
    del state["tool_results"]["host_action_status"]["receipt"]["transaction"]["transaction_reference"]
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("field", ["action", "receipt"])
def test_explicitly_null_receipt_representation_cannot_be_rescued_by_another(field):
    state, _, _ = scoped_done(native=True)
    state["tool_results"]["host_action_status"][field] = None
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("projection", ["action", "receipt"])
def test_native_display_reference_contradiction_between_receipt_projections_rejects_completion(projection):
    state, _, _ = scoped_done(native=True)
    status = state["tool_results"]["host_action_status"]
    canonical = status["action"] if projection == "action" else status["action"]["receipt"]
    canonical["transaction"] = deepcopy(status["receipt"]["transaction"])
    assert decide(state)["response_mode"] == "ACTION_DONE"
    canonical["transaction"]["transaction_reference"] = "txn_" + "b" * 12
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("projection", ["action", "receipt"])
@pytest.mark.parametrize("conflict", ["amount", "snapshot", "target_reference"])
def test_native_receipt_does_not_rescue_contradictory_optional_canonical_facts(projection, conflict):
    state, _, _ = scoped_done(native=True)
    status = state["tool_results"]["host_action_status"]
    canonical = status["action"] if projection == "action" else status["action"]["receipt"]
    canonical["transaction"] = deepcopy(status["receipt"]["transaction"])
    assert decide(state)["response_mode"] == "ACTION_DONE"
    if conflict == "amount": canonical["transaction"]["amount"] = "999"
    else: canonical[conflict] = "contradictory"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


def test_native_receipt_preserves_source_calendar_timestamp_semantics():
    state, _, _ = scoped_done(native=True)
    status = state["tool_results"]["host_action_status"]
    date = "2026-09-15T08:30:00"
    status["receipt"]["transaction"]["transaction_date"] = date
    state["tool_results"]["get_transaction"]["transaction"]["transaction_date"] = date
    assert decide(state)["response_mode"] == "ACTION_DONE"
    status["receipt"]["transaction"]["transaction_date"] = date + "+00:00"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("field", ["request_id", "host_pending_handle", "target_transaction_id", "snapshot_id", "snapshot_hash"])
def test_attempted_request_lineage_is_immutable_even_with_same_request_uuid(field):
    state, _, _ = scoped_confirmation()
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["workflow_state"]["pending"][field] = "changed"
    with pytest.raises(StateError, match="action_lineage_conflict"):
        checkpoint_query_scope(state)


@pytest.mark.parametrize("mutation", ["missing_read", "stale_target", "changed_hash", "changed_snapshot"])
def test_cached_success_flags_cannot_replace_fresh_owned_receipt_evidence(mutation):
    state, _, _ = scoped_done()
    if mutation == "missing_read":
        del state["tool_results"]["host_action_status"]
    elif mutation == "stale_target":
        state["workflow_state"]["transaction_identified"] = False
    elif mutation == "changed_hash":
        state["workflow_state"]["candidate_snapshot_hash"] = "new-hash"
    else:
        state["tool_results"]["get_transaction"]["snapshot_id"] = "new-snapshot"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


def test_reference_one_can_select_only_the_current_querys_snapshot():
    state, first, second = scoped_ready()
    state["workflow_state"]["pending"].update(type="awaiting_selection", query_id=second,
        candidates=[{"ref": "1", "transaction_id": "TRX-one"}], snapshot_id="snapshot-1", snapshot_hash="hash-1")
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="1")
    decision = decide(state)
    assert state["runtime"]["active_query_id"] == first
    assert decision["response_mode"] == "HANDOFF"
    assert decision.get("selection_consumed") is not True


def test_global_failure_limit_survives_query_boundary_and_workflow_reset():
    state, first, second = scoped_ready()
    state["runtime"]["node_errors"] = [{"node": "extract_slots", "code": "timeout"}]
    state = apply_decision(state, decide(state, {"max_tool_failures": 2}))
    assert state["runtime"]["session_tool_failures"] == 1
    state = checkpoint_query_scope(state)
    state = activate_query_scope(state, BINDING, second, now=NOW)
    state["runtime"]["node_errors"] = [{"node": "extract_slots", "code": "timeout"}]
    decision = decide(state, {"max_tool_failures": 2})
    assert decision["response_mode"] == "HANDOFF"
    state = apply_decision(state, decision)
    assert decide(state, {"max_tool_failures": 2})["workflow_updates"]["counters"]["tool_failures"] == 2
    state = reset_workflow(state)
    state = begin_turn(state, BINDING, turn_id="turn-2", user_question="cargo", now=NOW + timedelta(seconds=1))
    state["runtime"]["node_errors"] = [{"node": "extract_slots", "code": "timeout"}]
    assert decide(state, {"max_tool_failures": 3})["response_mode"] == "HANDOFF"


def test_auxiliary_summary_failure_keeps_business_route_and_real_failure_still_counts():
    state, _, _ = scoped_ready()
    state["runtime"]["node_errors"] = [{"node": "generate_handoff_summary", "code": "timeout"}]
    assert decide(state)["response_mode"] == "CONFIRM_ACTION"
    assert state["workflow_state"]["counters"]["tool_failures"] == 0
    state["runtime"]["node_errors"].append({"node": "extract_slots", "code": "timeout"})
    assert decide(state)["reason_code"] == "tool_failure"


def test_second_serial_query_uses_its_actual_clock_for_report_freshness():
    state, _, second = scoped_ready()
    prior = deepcopy(state)
    state = checkpoint_query_scope(state)
    state = activate_query_scope(state, BINDING, second, now=NOW + timedelta(seconds=21))
    state["workflow_state"], state["tool_results"] = deepcopy(prior["workflow_state"]), deepcopy(prior["tool_results"])
    state["turn"]["intent"] = "TRANSACTION_DISPUTE"
    assert decide(state)["response_mode"] == "HANDOFF"
    assert decide(state)["reason_code"] == "missing_evidence"
