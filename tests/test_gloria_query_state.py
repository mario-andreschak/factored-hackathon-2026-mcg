"""Independent query lifecycle remains bound, durable, and free of shared authority."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from gloria_workflow.state import (ConversationStore, StateError, TrustedBinding, activate_query_scope,
    begin_turn, checkpoint_query_scope, finish_query_batch, new_state, set_pending, start_query_batch)


NOW = datetime(2026, 10, 1, 5, 40, tzinfo=timezone.utc)
BINDING = TrustedBinding(owner="owner", customer_id="customer", session_id="session", conversation_id="conversation",
                         expires_at=NOW + timedelta(hours=1))


def batch():
    state = begin_turn(new_state(BINDING, now=NOW), BINDING, turn_id="turn-1", user_question="cargo A y consulta B", now=NOW)
    state["runtime"]["input_sha256"] = "a" * 64
    return start_query_batch(state, [{"query_text": "cargo A", "domain": "TRANSACTION_DISPUTE"},
                                    {"query_text": "consulta B", "domain": "TRANSACTION_INQUIRY"}])


def populate_two_pending():
    state = batch()
    first, second = state["runtime"]["query_scope_order"]
    for index, query_id in enumerate((first, second), 1):
        state = activate_query_scope(state, BINDING, query_id, now=NOW)
        state["workflow_state"].update(transaction_id=f"TRX-{index}", transaction_unique=True, transaction_identified=True)
        state["tool_results"] = {"get_transaction": {"status": "ok", "transaction": {"transaction_id": f"TRX-{index}"}}}
        state = set_pending(state, {"type": "awaiting_confirmation", "intent": "TRANSACTION_DISPUTE",
            "target_transaction_id": f"TRX-{index}", "snapshot_id": f"snapshot-{index}", "snapshot_hash": f"hash-{index}",
            "host_pending_handle": f"handle-{index}", "request_id": f"request-{index}",
            "candidates": [{"ref": "1", "transaction_id": f"TRX-{index}"}]}, now=NOW)
        state["response"] = {"message": f"response-{index}", "language": "es"}
        state = checkpoint_query_scope(state)
    return finish_query_batch(state)


def test_independent_queries_clear_tools_target_consent_and_call_retries():
    state = batch()
    first, second = state["runtime"]["query_scope_order"]
    state = activate_query_scope(state, BINDING, first, now=NOW)
    state["workflow_state"].update(transaction_id="TRX-A", transaction_unique=True)
    state["workflow_state"]["action"]["authorized"] = True
    state["tool_results"] = {"get_transaction": {"status": "ok", "transaction": {"transaction_id": "TRX-A"}}}
    state["runtime"]["tool_attempts"] = {"get_transaction": 3}
    state = checkpoint_query_scope(state)
    state = activate_query_scope(state, BINDING, second, now=NOW)
    assert state["turn"]["clean_query"] == "consulta B"
    assert state["turn"]["active_query_index"] == 1
    assert state["workflow_state"]["transaction_id"] is None
    assert state["workflow_state"]["action"]["authorized"] is False
    assert state["tool_results"] == {} and "tool_attempts" not in state["runtime"]
    assert state["runtime"]["query_scopes"][first]["workflow_state"]["transaction_id"] == "TRX-A"


def test_finish_projects_first_unresolved_and_observations_have_no_authority():
    state = populate_two_pending()
    first, second = state["runtime"]["query_scope_order"]
    assert state["runtime"]["active_query_id"] == first
    assert state["workflow_state"]["pending"]["query_id"] == first
    assert state["workflow_state"]["pending"]["request_id"] == "request-1"
    assert state["runtime"]["query_scopes"][second]["workflow_state"]["pending"]["request_id"] == "request-2"
    assert state["turn"]["user_question"] == "cargo A y consulta B"
    assert state["runtime"]["input_sha256"] == "a" * 64
    assert [item["response"]["message"] for item in state["runtime"]["query_results"]] == ["response-1", "response-2"]
    assert all(set(item) == {"query_id", "query_index", "response", "policy_decision"}
               for item in state["runtime"]["query_results"])
    assert all("query_scopes" not in capsule["runtime"] for capsule in state["runtime"]["query_scopes"].values())


def test_store_recursively_strips_live_consent_and_preserves_each_pending(tmp_path):
    state = populate_two_pending()
    for capsule in state["runtime"]["query_scopes"].values():
        capsule["workflow_state"]["trusted_confirmation"]["verified"] = True
        capsule["workflow_state"]["action"]["authorized"] = True
    path = tmp_path / "scopes.sqlite"
    ConversationStore(path).save_turn(BINDING, "turn-1", state, now=NOW)
    restored = ConversationStore(path).load_turn(BINDING, "turn-1", now=NOW)
    for index, capsule in enumerate(restored["runtime"]["query_scopes"].values(), 1):
        assert capsule["workflow_state"]["trusted_confirmation"]["verified"] is False
        assert capsule["workflow_state"]["action"]["authorized"] is False
        assert capsule["workflow_state"]["pending"]["request_id"] == f"request-{index}"
        assert capsule["runtime"]["action_lineage"]["query_id"] == capsule["query_id"]


def test_pending_turns_advance_once_for_every_capsule_and_activation_does_not_double_count():
    state = populate_two_pending()
    first = state["runtime"]["query_scope_order"][0]
    state = begin_turn(state, BINDING, turn_id="turn-2", user_question="sim", now=NOW + timedelta(seconds=1))
    assert all(cap["workflow_state"]["pending"]["turns_waiting"] == 1 for cap in state["runtime"]["query_scopes"].values())
    active = activate_query_scope(state, BINDING, first, now=NOW + timedelta(seconds=1), query_text="sim")
    assert active["workflow_state"]["pending"]["turns_waiting"] == 1
    assert active["turn"]["clean_query"] == "sim"
    assert active["runtime"]["query_scopes"][first]["query_text"] == "cargo A"


def test_inactive_pending_expiry_retains_uncertain_original_request(tmp_path):
    state = populate_two_pending()
    second = state["runtime"]["query_scope_order"][1]
    capsule = state["runtime"]["query_scopes"][second]
    capsule["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    capsule["workflow_state"]["action"]["idempotency_key"] = "request-2"
    store = ConversationStore(tmp_path / "state.sqlite", pending_ttl_seconds=30)
    store.save(BINDING, state, now=NOW)
    expired = store.load(BINDING, now=NOW + timedelta(seconds=30))
    assert all(cap["workflow_state"]["pending"]["type"] == "none" for cap in expired["runtime"]["query_scopes"].values())
    uncertain = expired["runtime"]["query_scopes"][second]
    assert uncertain["workflow_state"]["action_outcome"] == "unknown"
    assert uncertain["runtime"]["action_lineage"]["request_id"] == "request-2"


def test_capsule_cannot_be_transplanted_to_another_owner_or_snapshot():
    state = batch()
    first = state["runtime"]["query_scope_order"][0]
    foreign = new_state(replace(BINDING, owner="foreign"), now=NOW)
    foreign["runtime"].update(query_scopes=deepcopy(state["runtime"]["query_scopes"]),
                               query_scope_order=deepcopy(state["runtime"]["query_scope_order"]))
    with pytest.raises(StateError, match="query_scope_binding_mismatch"):
        activate_query_scope(foreign, replace(BINDING, owner="foreign"), first, now=NOW)
    state["runtime"]["query_scopes"][first]["workflow_state"]["pending"].update(type="awaiting_selection", query_id="q_" + "b" * 32)
    with pytest.raises(StateError, match="query_scope_binding_mismatch"):
        activate_query_scope(state, BINDING, first, now=NOW)


def test_start_cannot_discard_unresolved_requests_and_model_cannot_supply_ids():
    state = populate_two_pending()
    with pytest.raises(StateError, match="unresolved_query_batch"):
        start_query_batch(state, [{"query_text": "new request", "domain": "TRANSACTION_INQUIRY"}])
    with pytest.raises(StateError, match="invalid_query_batch"):
        start_query_batch(batch(), [{"query_text": "x", "domain": "TRANSACTION_INQUIRY", "query_id": "model-id"}])
