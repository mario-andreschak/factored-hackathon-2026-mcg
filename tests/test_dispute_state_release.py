"""Release regressions for current observations and durable receipt lineage."""
from copy import deepcopy
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from dispute_workflow.policy import decide
from dispute_workflow.state import (ConversationStore, StateError, activate_query_scope,
    apply_decision, begin_turn, checkpoint_query_scope, finish_query_batch, new_state,
    set_pending, start_query_batch)


_spec = importlib.util.spec_from_file_location(
    "dispute_release_helpers", Path(__file__).with_name("test_dispute_policy.py"))
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


def _release_batch():
    state = begin_turn(new_state(BINDING, now=NOW), BINDING, turn_id="batch-turn",
        user_question="cargo A y cargo B", now=NOW)
    return start_query_batch(state, [
        {"query_text": "cargo A", "domain": "TRANSACTION_DISPUTE"},
        {"query_text": "cargo B", "domain": "TRANSACTION_INQUIRY"}])


@pytest.mark.parametrize("bad_entry", [[], {}, None, True, 7])
def test_malformed_scope_order_entries_fail_with_safe_state_error(bad_entry):
    state = _release_batch()
    first = state["runtime"]["query_scope_order"][0]
    state["runtime"]["query_scope_order"][0] = bad_entry
    with pytest.raises(StateError):
        activate_query_scope(state, BINDING, first, now=NOW)


@pytest.mark.parametrize("field,value", [
    ("runtime", None), ("runtime", []), ("workflow_state", None),
    ("workflow_state", []), ("turn", None), ("turn", []),
    ("tool_results", []), ("response", []), ("intent", []),
    ("query_index", False)])
def test_malformed_capsule_shape_cannot_escape_as_incidental_python_error(field, value):
    state = _release_batch()
    first = state["runtime"]["query_scope_order"][0]
    state["runtime"]["query_scopes"][first][field] = value
    with pytest.raises(StateError):
        activate_query_scope(state, BINDING, first, now=NOW, fresh=False)


@pytest.mark.parametrize("lineage_name", ["action_lineage", "handoff_lineage", "host_receipt_lineage"])
@pytest.mark.parametrize("tamper", ["sibling_query", "foreign_owner"])
def test_receipt_lineage_cannot_be_copied_to_another_query_or_owner(lineage_name, tamper):
    state = _release_batch()
    first, second = state["runtime"]["query_scope_order"]
    state["runtime"]["query_scopes"][first]["runtime"][lineage_name] = {
        "query_id": second if tamper == "sibling_query" else first,
        "binding_digest": "foreign-owner" if tamper == "foreign_owner" else BINDING.digest(),
        "request_id": "request-A", "target_transaction_id": "TRX-A", "snapshot_id": "snapshot-A"}
    with pytest.raises(StateError, match="query_scope_binding_mismatch"):
        activate_query_scope(state, BINDING, first, now=NOW, fresh=False)


def test_each_query_keeps_only_its_history_after_save_load_and_fresh_resume(tmp_path):
    state = _release_batch()
    first, second = state["runtime"]["query_scope_order"]
    histories = {first: ["user: cargo A", "assistant: respuesta A"],
                 second: ["user: cargo B", "assistant: respuesta B"]}
    for query_id in (first, second):
        state = activate_query_scope(state, BINDING, query_id, now=NOW)
        state["runtime"]["query_history"] = histories[query_id]
        state = checkpoint_query_scope(state)
    state = finish_query_batch(state)
    state["runtime"]["history"] = histories[first] + histories[second]
    store = ConversationStore(tmp_path / "history.sqlite")
    store.save_turn(BINDING, "batch-turn", state, now=NOW)
    restored = store.load(BINDING, now=NOW + timedelta(seconds=1))
    resumed = begin_turn(restored, BINDING, turn_id="reply-turn", user_question="otra respuesta",
                         now=NOW + timedelta(seconds=1))
    for query_id in (first, second):
        active = activate_query_scope(resumed, BINDING, query_id, now=NOW + timedelta(seconds=1))
        assert active["runtime"]["query_history"] == histories[query_id]
        sibling = second if query_id == first else first
        assert not any(item in active["runtime"]["query_history"] for item in histories[sibling])


def test_inactive_pending_uses_original_ttl_and_keeps_uncertain_write_lineage(tmp_path):
    state = _release_batch()
    first, second = state["runtime"]["query_scope_order"]
    for index, query_id in enumerate((first, second)):
        state = activate_query_scope(state, BINDING, query_id, now=NOW)
        state["workflow_state"]["transaction_id"] = f"TRX-{index}"
        state = set_pending(state, {
            "type": "awaiting_confirmation", "intent": "TRANSACTION_DISPUTE",
            "proposed_action": "CREATE_COMPLAINT", "created_turn_id": "batch-turn",
            "target_transaction_id": f"TRX-{index}", "snapshot_id": f"snapshot-{index}",
            "snapshot_hash": f"hash-{index}", "request_id": f"request-{index}",
            "host_pending_handle": f"handle-{index}"}, now=NOW, ttl_seconds=600 if index == 0 else 30)
        if query_id == second:
            state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
            state["workflow_state"]["action"]["idempotency_key"] = "request-1"
        state = checkpoint_query_scope(state)
    state = finish_query_batch(state)
    assert state["runtime"]["active_query_id"] == first
    store = ConversationStore(tmp_path / "sibling-ttl.sqlite", pending_ttl_seconds=40)
    store.save_turn(BINDING, "batch-turn", state, now=NOW + timedelta(seconds=1))
    restored = store.load(BINDING, now=NOW + timedelta(seconds=31))
    scopes = restored["runtime"]["query_scopes"]
    assert scopes[first]["workflow_state"]["pending"]["type"] == "awaiting_confirmation"
    assert scopes[first]["runtime"]["pending_expires_at"] == (NOW + timedelta(seconds=40)).isoformat().replace("+00:00", "Z")
    expired = scopes[second]
    assert expired["workflow_state"]["pending"]["type"] == "none"
    assert expired["workflow_state"]["action_attempted"] is True
    assert expired["workflow_state"]["action_outcome"] == "unknown"
    assert expired["workflow_state"]["action"]["idempotency_key"] == "request-1"
    assert expired["runtime"]["action_lineage"]["request_id"] == "request-1"
    assert expired["runtime"]["action_lineage"]["query_id"] == second


def test_legacy_top_level_consent_and_authorization_expiry_are_revoked_on_load(tmp_path):
    store = ConversationStore(tmp_path / "legacy-consent.sqlite")
    state = _helpers.confirming(trusted=True)
    store.save_turn(BINDING, "turn-1", state, now=NOW)
    # Model a previously serialized version with live authorization metadata.
    with sqlite3.connect(store.path) as connection:
        payload = json.loads(connection.execute("SELECT state_json FROM dispute_conversations").fetchone()[0])
        payload["workflow_state"]["trusted_confirmation"] = deepcopy(state["workflow_state"]["trusted_confirmation"])
        payload["workflow_state"]["action"].update(
            authorized=True, authorization_expires_at=(NOW + timedelta(minutes=10)).isoformat())
        connection.execute("UPDATE dispute_conversations SET state_json=?", (json.dumps(payload),))
    connection.close()
    restored = store.load(BINDING, now=NOW + timedelta(seconds=1))
    assert restored["workflow_state"]["trusted_confirmation"]["verified"] is False
    assert restored["workflow_state"]["action"]["authorized"] is False
    assert restored["workflow_state"]["action"]["authorization_expires_at"] is None
