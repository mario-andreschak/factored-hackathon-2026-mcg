"""Independent regression cases for policy reentry and durable state safety."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from dispute_workflow import state as state_module
from dispute_workflow.policy import decide
from dispute_workflow.state import ConversationStore, StateError, apply_decision, record_tool_result


_spec = importlib.util.spec_from_file_location(
    "dispute_review_helpers", Path(__file__).with_name("test_dispute_policy.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
ready_state = _helpers.ready_state
confirming = _helpers.confirming
NOW = _helpers.NOW
BINDING = _helpers.BINDING


@pytest.mark.parametrize("change", ["target_duplicate", "tool_failure"])
def test_failed_consent_revalidation_revokes_event_before_reentry(change):
    state = confirming(trusted=True)
    original = deepcopy(state["tool_results"]["get_transaction"])
    if change == "target_duplicate":
        state["tool_results"]["get_transaction"]["data_quality_flags"] = ["possible_duplicate_of"]
    else:
        state["tool_results"]["get_transaction"] = {
            "status": "error", "retries_exhausted": True,
            "error": {"code": "data_unavailable", "retryable": False, "message": "unavailable"}}
    decision = decide(state)
    assert decision["response_mode"] in {"HANDOFF", "TOOL_ERROR"}
    applied = apply_decision(state, decision)
    assert applied["workflow_state"]["trusted_confirmation"]["verified"] is False
    assert applied["workflow_state"]["action"]["authorized"] is False
    applied["tool_results"]["get_transaction"] = original
    later = decide(applied)
    assert later["workflow_updates"].get("action", {}).get("authorized") is not True


def test_derived_risk_cache_cannot_override_new_incomplete_coverage():
    state = confirming(trusted=True)
    state = apply_decision(state, decide(state))
    assert state["workflow_state"]["risk_data_complete"] is True
    state["tool_results"]["get_related_complaints"]["report_window"]["coverage_complete"] = False
    decision = decide(state)
    assert decision["response_mode"] == "HANDOFF"
    assert decision["reason_code"] == "missing_evidence"
    assert decision["workflow_updates"]["unrecognized_count_24h"] is None
    assert decision["workflow_updates"]["risk_data_complete"] is False
    assert decision["workflow_updates"].get("action", {}).get("authorized") is not True


def test_each_counter_counts_once_when_three_conditions_occur_in_one_turn():
    state = ready_state()
    state["workflow_state"]["search_criteria_present"] = False
    state = apply_decision(state, decide(state))
    state["workflow_state"]["search_criteria_present"] = True
    state["tool_results"]["search_transactions"].update(match_count=0, candidates=[])
    state = apply_decision(state, decide(state))
    state = apply_decision(state, decide(state))
    state["tool_results"]["get_transaction"] = {"status": "error", "retries_exhausted": True}
    state = apply_decision(state, decide(state))
    state = apply_decision(state, decide(state))
    counters = state["workflow_state"]["counters"]
    assert {key: counters[key] for key in (
        "clarification_attempts", "no_match_attempts", "tool_failures")} == {
            "clarification_attempts": 1, "no_match_attempts": 1, "tool_failures": 1}


def test_nested_canonical_retryable_error_gets_bounded_retries_before_counting_failure():
    state = ready_state()
    result = {"status": "error", "error": {
        "code": "data_unavailable", "retryable": True, "message": "unavailable"}}
    for attempt in range(3):
        state = record_tool_result(state, "get_transaction", result, tool_retries=2)
        decision = decide(state)
        if attempt < 2:
            assert decision["next_step"] == "retry_tool"
            assert state["workflow_state"]["counters"]["tool_failures"] == 0
        else:
            assert decision["reason_code"] == "tool_failure"
            assert decision["workflow_updates"]["counters"]["tool_failures"] == 1


def test_exact_turn_replay_does_not_accept_changed_session_expiry(tmp_path):
    store = ConversationStore(tmp_path / "replay.sqlite")
    state = ready_state()
    store.save_turn(BINDING, "turn-1", state, now=NOW)
    changed = replace(BINDING, expires_at=BINDING.expires_at.replace(hour=6))
    with pytest.raises(StateError, match="session_expiry_changed"):
        store.save_turn(changed, "turn-1", state, now=NOW)


def test_store_closes_connections_before_immediate_directory_removal(tmp_path, monkeypatch):
    connections = []
    connect = state_module.sqlite3.connect

    def tracked_connect(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(state_module.sqlite3, "connect", tracked_connect)
    temporary = TemporaryDirectory(dir=tmp_path)
    directory = Path(temporary.name)
    try:
        store = ConversationStore(directory / "state.sqlite")
        state = ready_state()
        store.save_turn(BINDING, "turn-1", state, now=NOW)
        assert store.load(BINDING, now=NOW) is not None
        assert store.load_turn(BINDING, "turn-1", user_question="cargo", now=NOW) is not None
        for connection in connections:
            with pytest.raises(sqlite3.ProgrammingError, match="closed"):
                connection.execute("SELECT 1")
        temporary.cleanup()
        assert not directory.exists()
    finally:
        # A failing implementation must not leave locked temporary files behind.
        for connection in connections:
            connection.close()
        temporary.cleanup()


@pytest.mark.parametrize("current_intent", ["TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY"])
def test_complaint_selection_routes_to_r18_despite_current_business_intent(current_intent):
    state = ready_state("COMPLAINT_STATUS")
    state["workflow_state"]["candidate_snapshot_hash"] = None
    state["tool_results"]["list_customer_complaints"] = {
        "status": "ok", "coverage_complete": True, "snapshot_id": "complaint-snapshot",
        "match_count": 2, "complaints": [
            {"complaint_id": "CMP-one", "status": "Open"},
            {"complaint_id": "CMP-two", "status": "Escalated"}]}
    state = apply_decision(state, decide(state))
    state["turn"].update(intent=current_intent)
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="2")
    state["tool_results"]["get_complaint"] = {
        "status": "ok", "snapshot_id": "complaint-snapshot",
        "complaint": {"complaint_id": "CMP-two", "status": "Escalated"}}
    decision = decide(state)
    assert decision["rule_ids"] == ["R18"]
    assert decision["response_mode"] == "INFORM"
    assert decision["clear_pending"] is True
