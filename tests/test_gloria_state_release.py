"""Release regressions for current observations and durable receipt lineage."""
from copy import deepcopy
from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest

from gloria_workflow.policy import decide
from gloria_workflow.state import ConversationStore, apply_decision, begin_turn


_spec = importlib.util.spec_from_file_location(
    "gloria_release_helpers", Path(__file__).with_name("test_gloria_policy.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
NOW = _helpers.NOW
BINDING = _helpers.BINDING


@pytest.mark.parametrize("new_request", ["human", "emergency", "business"])
def test_prior_verified_handoff_is_not_current_evidence_for_new_request(new_request):
    prior = _helpers.ready_state()
    prior["runtime"]["active_query_id"] = "query-prior"
    prior["workflow_state"]["handoff"].update(
        required=True, created=True, handoff_id="HOF-abcdefgh", reason_code="high_risk",
        receipt={"verified": True, "handoff_id": "HOF-abcdefgh"})
    state = begin_turn(prior, BINDING, turn_id="turn-new", user_question="otra pregunta",
                       now=NOW + timedelta(seconds=5))
    if new_request == "human":
        state["turn"].update(intent="HUMAN_REQUEST", human_requested=True)
    elif new_request == "emergency":
        state["turn"].update(intent="TRANSACTION_DISPUTE", emotional_context="Emergencia")
    else:
        ready = _helpers.ready_state("TRANSACTION_INQUIRY")
        state["turn"].update(intent="TRANSACTION_INQUIRY")
        state["workflow_state"].update(
            transaction_id="TRX-one", transaction_identified=True,
            transaction_unique=True, search_criteria_present=True,
            candidate_snapshot_hash="hash-1")
        state["tool_results"] = deepcopy(ready["tool_results"])
    state = apply_decision(state, decide(state))
    current = state["workflow_state"]["handoff"]
    assert current["created"] is False
    assert current["handoff_id"] is None
    assert current.get("receipt", {}).get("verified") is not True
    assert state["workflow_state"]["handoff_attempted"] is False
    if new_request == "business":
        assert current["required"] is False
        assert state["workflow_state"]["policy_decision"]["response_mode"] == "INFORM"
    else:
        assert current["required"] is True
    audits = state["runtime"].get("prior_verified_handoffs", [])
    assert any(item.get("handoff_id") == "HOF-abcdefgh" for item in audits)


def _completed_action():
    state = _helpers.confirming()
    state["runtime"]["active_query_id"] = "query-action"
    state["workflow_state"].update(action_attempted=True, action_outcome="verified")
    state["workflow_state"]["action"].update(
        name="CREATE_COMPLAINT", authorized=True, executed=True, verified=True,
        result_id="CMP-SBX-abcdefgh",
        receipt={"verified": True, "result_id": "CMP-SBX-abcdefgh"})
    pending = deepcopy(state["workflow_state"]["pending"])
    decision = decide(state)
    assert decision["response_mode"] == "ACTION_DONE"
    return apply_decision(state, decision), pending


def test_action_done_pending_cleanup_preserves_exact_action_lineage():
    state, pending = _completed_action()
    assert state["workflow_state"]["pending"]["type"] == "none"
    lineage = state["runtime"]["action_lineage"]
    assert lineage["query_id"] == "query-action"
    assert lineage["request_id"] == pending["request_id"]
    assert lineage["host_pending_handle"] == pending["host_pending_handle"]
    assert lineage["target_transaction_id"] == "TRX-one"
    assert lineage["snapshot_id"] == pending["snapshot_id"]
    assert lineage["snapshot_hash"] == pending["snapshot_hash"]
    assert lineage["binding_digest"] == BINDING.digest()


@pytest.mark.parametrize("restore", ["conversation", "exact_turn"])
def test_action_lineage_survives_storage_and_next_turn_archive(tmp_path, restore):
    state, pending = _completed_action()
    store = ConversationStore(tmp_path / "lineage.sqlite")
    store.save_turn(BINDING, "turn-1", state, now=NOW + timedelta(seconds=1))
    if restore == "conversation":
        loaded = store.load(BINDING, now=NOW + timedelta(seconds=2))
    else:
        loaded = store.load_turn(BINDING, "turn-1", now=NOW + timedelta(seconds=2))
    assert loaded["runtime"]["action_lineage"] == state["runtime"]["action_lineage"]
    assert loaded["workflow_state"]["action"]["authorized"] is False
    assert loaded["workflow_state"]["trusted_confirmation"]["verified"] is False
    next_state = begin_turn(loaded, BINDING, turn_id="turn-new", user_question="otro cargo",
                            now=NOW + timedelta(seconds=3))
    assert next_state["workflow_state"]["action_attempted"] is False
    assert next_state["workflow_state"]["action"]["verified"] is False
    audits = next_state["runtime"]["prior_verified_actions"]
    assert audits[-1]["result_id"] == "CMP-SBX-abcdefgh"
    assert audits[-1]["idempotency_key"] == pending["request_id"]
    assert audits[-1]["transaction_id"] == "TRX-one"
    assert audits[-1]["snapshot_id"] == pending["snapshot_id"]
