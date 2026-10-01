"""Durability, trusted binding, turn replay, lifecycle and retry invariants."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib

import pytest

from dispute_workflow.state import (ConversationStore, ReplayConflict, RevisionConflict, StateError,
    TrustedBinding, apply_decision, begin_turn, cancel_pending, merge_explicit_slots, new_state,
    record_tool_result, reset_workflow, set_pending)
from dispute_workflow.policy import decide


NOW = datetime(2026, 10, 1, 3, 50, tzinfo=timezone.utc)


@pytest.fixture
def binding():
    return TrustedBinding(owner="owner-1", customer_id="customer-1", session_id="session-1",
                          conversation_id="conversation-1", expires_at=NOW + timedelta(hours=1))


def state_for(binding):
    return begin_turn(new_state(binding, now=NOW), binding, turn_id="turn-1", user_question="cargo", now=NOW)


def pending_for(state, kind="awaiting_confirmation"):
    return set_pending(state, {"type": kind, "intent": "TRANSACTION_DISPUTE", "created_turn_id": "turn-1",
        "proposed_action": "CREATE_COMPLAINT", "target_transaction_id": "TRX-one", "snapshot_id": "snapshot-1",
        "snapshot_hash": "hash-1", "host_pending_handle": "host-handle", "request_id": "request-1"}, now=NOW)


def test_canonical_new_state_uses_real_bogota_date_and_exact_slots(binding):
    state = new_state(binding, now=NOW)
    assert state["turn"]["current_date"] == "2026-09-30"
    assert state["session"] == {"authenticated": True, "expired": False, "customer_id": "customer-1",
                                "session_id": "session-1", "conversation_id": "conversation-1"}
    assert "owner" not in state["session"]
    assert len(state["turn"]["slots"]) == 17
    assert state["workflow_state"]["action"]["authorized"] is False


@pytest.mark.parametrize("field,value", [("owner", ""), ("customer_id", None), ("expires_at", None),
                                        ("expires_at", datetime(2026, 10, 1)), ("authenticated", 1)])
def test_invalid_trusted_binding_rejected(binding, field, value):
    with pytest.raises(StateError, match="invalid_trusted_binding"):
        replace(binding, **{field: value})


def test_naive_clock_rejected(binding):
    with pytest.raises(StateError, match="aware_timestamp_required"):
        new_state(binding, now=datetime(2026, 10, 1))


def test_begin_turn_restores_workflow_only_and_clears_consent_and_tools(binding):
    old = pending_for(state_for(binding))
    old["tool_results"] = {"get_transaction": {"status": "ok", "transaction": {"transaction_id": "TRX-old"}}}
    old["workflow_state"]["trusted_confirmation"]["verified"] = True
    old["workflow_state"]["action"].update(authorized=True, idempotency_key="retained-request")
    old["workflow_state"]["counters"]["no_match_attempts"] = 1
    old["runtime"]["history"] = ["sanitized history"]
    old["turn"].update(intent="TRANSACTION_DISPUTE", validation_attempts=1)
    before = deepcopy(old)
    fresh = begin_turn(old, binding, turn_id="turn-2", user_question="sim", now=NOW + timedelta(seconds=1))
    assert fresh["tool_results"] == {}
    assert fresh["turn"]["intent"] is None and fresh["turn"]["validation_attempts"] == 0
    assert fresh["workflow_state"]["trusted_confirmation"]["verified"] is False
    assert fresh["workflow_state"]["action"]["authorized"] is False
    assert fresh["workflow_state"]["action"]["idempotency_key"] == "retained-request"
    assert fresh["workflow_state"]["counters"]["no_match_attempts"] == 1
    assert fresh["runtime"]["history"] == ["sanitized history"]
    assert old == before


def test_begin_turn_cannot_rebind_owner_customer_or_conversation(binding):
    state = state_for(binding)
    for field in ("owner", "customer_id", "conversation_id", "session_id"):
        with pytest.raises(StateError, match="state_binding_mismatch"):
            begin_turn(state, replace(binding, **{field: "other"}), turn_id="next", user_question="cargo", now=NOW)


def test_session_expiry_checked_each_turn_and_invalidates_pending(binding):
    state = pending_for(state_for(binding))
    fresh = begin_turn(state, binding, turn_id="turn-2", user_question="sim", now=NOW + timedelta(hours=1))
    assert fresh["session"]["expired"] is True
    assert fresh["workflow_state"]["pending"]["type"] == "none"


def test_pending_expiry_turn_boundary_and_same_turn_reentry(binding):
    state = pending_for(state_for(binding))
    for i in (2, 3):
        state = begin_turn(state, binding, turn_id=f"turn-{i}", user_question="otro", now=NOW + timedelta(seconds=i))
        assert state["workflow_state"]["pending"]["type"] == "awaiting_confirmation"
        same = begin_turn(state, binding, turn_id=f"turn-{i}", user_question="otro", now=NOW + timedelta(seconds=i))
        assert same["workflow_state"]["pending"]["turns_waiting"] == state["workflow_state"]["pending"]["turns_waiting"]
    state = begin_turn(state, binding, turn_id="turn-4", user_question="otro", now=NOW + timedelta(seconds=4))
    assert state["workflow_state"]["pending"]["type"] == "none"
    assert state["runtime"]["pending_expired"] is True


def test_pending_real_ttl_boundary(binding):
    state = pending_for(state_for(binding))
    live = begin_turn(state, binding, turn_id="turn-2", user_question="sim", now=NOW + timedelta(seconds=599))
    assert live["workflow_state"]["pending"]["type"] == "awaiting_confirmation"
    expired = begin_turn(state, binding, turn_id="turn-2", user_question="sim", now=NOW + timedelta(seconds=600))
    assert expired["workflow_state"]["pending"]["type"] == "none"
    with pytest.raises(StateError, match="invalid_pending_ttl"):
        set_pending(state, {"type": "awaiting_confirmation"}, now=NOW, ttl_seconds=601)


def test_cancellation_keeps_uncertain_action_identity(binding):
    state = pending_for(state_for(binding))
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["workflow_state"]["action"].update(idempotency_key="durable-request", authorized=True)
    cancelled = cancel_pending(state, clear_target=True)
    assert cancelled["workflow_state"]["action_attempted"] is True
    assert cancelled["workflow_state"]["action_outcome"] == "unknown"
    assert cancelled["workflow_state"]["action"]["idempotency_key"] == "durable-request"
    with pytest.raises(StateError, match="action_recovery_required"):
        reset_workflow(cancelled)


def test_new_workflow_resets_counters(binding):
    state = pending_for(state_for(binding))
    state["workflow_state"]["counters"].update(clarification_attempts=2, no_match_attempts=2, tool_failures=2)
    result = reset_workflow(state)
    assert all(result["workflow_state"]["counters"][key] == 0 for key in ("clarification_attempts", "no_match_attempts", "tool_failures"))


def test_verified_completion_starts_fresh_next_turn_without_spurious_uncertainty(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    state = state_for(binding)
    state["workflow_state"].update(action_attempted=True, action_outcome="verified", transaction_id="TRX-one")
    state["workflow_state"]["action"].update(authorized=True, executed=True, verified=True,
                                             result_id="CMP-one", idempotency_key="request-1")
    state["workflow_state"]["counters"]["clarification_attempts"] = 1
    store.save_turn(binding, "turn-1", state, now=NOW)
    loaded = store.load(binding, now=NOW)
    next_turn = begin_turn(loaded, binding, turn_id="turn-2", user_question="hola", now=NOW + timedelta(seconds=5))
    assert next_turn["workflow_state"]["action_attempted"] is False
    assert next_turn["workflow_state"]["action_outcome"] == "none"
    assert next_turn["workflow_state"]["action"]["authorized"] is False
    assert next_turn["workflow_state"]["counters"]["clarification_attempts"] == 0
    assert next_turn["runtime"]["prior_verified_actions"][0]["result_id"] == "CMP-one"
    # Same-turn replay retains receipt facts for a fresh host revalidation,
    # without reconstructing live consent from durable state.
    replay = store.load_turn(binding, "turn-1", now=NOW)
    assert replay["workflow_state"]["action_outcome"] == "verified"
    assert replay["workflow_state"]["action"]["verified"] is True
    assert replay["workflow_state"]["action"]["authorized"] is False


def test_unknown_write_cannot_be_reset_by_starting_new_turn(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    state = pending_for(state_for(binding))
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["workflow_state"]["action"]["idempotency_key"] = "request-unknown"
    store.save(binding, state, now=NOW)
    fresh = begin_turn(store.load(binding, now=NOW), binding, turn_id="turn-2", user_question="hola", now=NOW + timedelta(minutes=11))
    assert fresh["workflow_state"]["pending"]["type"] == "none"
    assert fresh["workflow_state"]["action_outcome"] == "unknown"
    assert fresh["workflow_state"]["action"]["idempotency_key"] == "request-unknown"


def test_tool_retry_bound_separate_from_session_failure_counts(binding):
    state = state_for(binding)
    for attempt in range(3):
        state = record_tool_result(state, "search_transactions", {"status": "error"})
        assert state["tool_results"]["search_transactions"]["retry_count"] == attempt
    assert state["tool_results"]["search_transactions"]["retries_exhausted"] is True
    assert state["workflow_state"]["counters"]["tool_failures"] == 0
    with pytest.raises(StateError, match="tool_retry_exhausted"):
        record_tool_result(state, "search_transactions", {"status": "error"})


def test_sqlite_restart_preserves_workflow_and_counters_but_not_consent(binding, tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ConversationStore(path)
    state = pending_for(state_for(binding))
    state["workflow_state"]["trusted_confirmation"]["verified"] = True
    state["workflow_state"]["action"]["authorized"] = True
    state["workflow_state"]["counters"]["clarification_attempts"] = 1
    assert store.save(binding, state, now=NOW) == 1
    loaded = ConversationStore(path).load(binding, now=NOW + timedelta(seconds=5))
    assert loaded["runtime"]["store_revision"] == 1
    assert loaded["workflow_state"]["pending"]["request_id"] == "request-1"
    assert loaded["workflow_state"]["trusted_confirmation"]["verified"] is False
    assert loaded["workflow_state"]["action"]["authorized"] is False
    assert loaded["workflow_state"]["counters"]["clarification_attempts"] == 1


@pytest.mark.parametrize("field", ["owner", "customer_id", "session_id", "conversation_id"])
def test_sqlite_full_binding_isolates_records(binding, tmp_path, field):
    store = ConversationStore(tmp_path / "state.sqlite3")
    store.save(binding, state_for(binding), now=NOW)
    other = replace(binding, **{field: "other"})
    assert store.load(other, now=NOW) is None
    with pytest.raises(StateError, match="state_binding_mismatch"):
        store.save(other, state_for(binding), now=NOW)


def test_sqlite_cas_rejects_stale_revision(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    state = state_for(binding)
    store.save(binding, state, now=NOW)
    with pytest.raises(RevisionConflict, match="revision_conflict"):
        store.save(binding, state, now=NOW)
    loaded = store.load(binding, now=NOW)
    assert store.save(binding, loaded, now=NOW) == 2


def test_sqlite_concurrent_cas_only_one_wins(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    state = state_for(binding)
    def save_once():
        try:
            return store.save(binding, deepcopy(state), expected_revision=0, now=NOW)
        except RevisionConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: save_once(), range(2)))
    assert sorted(results, key=str) == [1, "conflict"]
    assert store.load(binding, now=NOW)["runtime"]["store_revision"] == 1


def test_sqlite_expiry_cannot_be_extended_by_rebinding(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    store.save(binding, pending_for(state_for(binding)), now=NOW)
    expired = store.load(binding, now=NOW + timedelta(hours=1))
    assert expired["session"]["expired"] is True and expired["workflow_state"]["pending"]["type"] == "none"
    extended = replace(binding, expires_at=NOW + timedelta(hours=2))
    with pytest.raises(StateError, match="session_expiry_changed"):
        store.load(extended, now=NOW)
    with pytest.raises(StateError, match="session_not_live"):
        store.save(binding, expired, now=NOW + timedelta(hours=1))


def test_store_caps_pending_ttl_and_preserves_attempt_recovery(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3", pending_ttl_seconds=30)
    state = pending_for(state_for(binding))
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["workflow_state"]["action"]["idempotency_key"] = "durable-request"
    store.save(binding, state, now=NOW)
    expired = store.load(binding, now=NOW + timedelta(seconds=30))
    assert expired["workflow_state"]["pending"]["type"] == "none"
    assert expired["workflow_state"]["action"]["idempotency_key"] == "durable-request"


def test_atomic_turn_replay_survives_restart_and_conflicts_on_changed_input(binding, tmp_path):
    path = tmp_path / "state.sqlite3"
    store = ConversationStore(path)
    state = state_for(binding)
    state["runtime"]["input_sha256"] = hashlib.sha256(b"message+selection").hexdigest()
    state["response"]["message"] = "respuesta"
    assert store.save_turn(binding, "turn-1", state, now=NOW) == 1
    restarted = ConversationStore(path)
    replay = restarted.load_turn(binding, "turn-1", now=NOW)
    assert replay["response"]["message"] == "respuesta"
    assert restarted.save_turn(binding, "turn-1", state, now=NOW) == 1
    changed = deepcopy(state)
    changed["runtime"]["input_sha256"] = hashlib.sha256(b"different selection").hexdigest()
    with pytest.raises(ReplayConflict, match="turn_replay_conflict"):
        restarted.save_turn(binding, "turn-1", changed, now=NOW)
    assert restarted.load_turn(replace(binding, owner="other"), "turn-1", now=NOW) is None
    assert restarted.load_turn(binding, "turn-1", now=NOW + timedelta(hours=1)) is None


def test_replay_does_not_overwrite_newer_state(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    first = state_for(binding)
    store.save_turn(binding, "turn-1", first, now=NOW)
    second = begin_turn(store.load(binding, now=NOW), binding, turn_id="turn-2", user_question="next", now=NOW)
    second["response"]["message"] = "second"
    assert store.save_turn(binding, "turn-2", second, expected_revision=1, now=NOW) == 2
    assert store.save_turn(binding, "turn-1", first, now=NOW) == 1
    assert store.load(binding, now=NOW)["response"]["message"] == "second"


def test_turn_and_state_commit_atomically_on_cas_conflict(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    first = state_for(binding)
    store.save(binding, first, now=NOW)
    stale = deepcopy(first)
    stale["turn"]["turn_id"] = "not-committed"
    with pytest.raises(RevisionConflict):
        store.save_turn(binding, "not-committed", stale, now=NOW)
    assert store.load_turn(binding, "not-committed", now=NOW) is None


def test_currency_only_reply_keeps_explicit_amount_and_intent_across_restart(binding, tmp_path):
    store = ConversationStore(tmp_path / "state.sqlite3")
    state = state_for(binding)
    state["turn"].update(intent="TRANSACTION_DISPUTE")
    state["turn"]["slots"].update(amount=150, currency_raw="pesos", date_from="2026-09-15", date_to="2026-09-15",
                                    transaction_id="TRX-user-text", amount_is_approximate=True)
    state = apply_decision(state, decide(state))
    assert state["workflow_state"]["pending"]["type"] == "none"
    assert state["runtime"]["field_clarification"]["missing_fields"] == ["currency"]
    store.save(binding, state, now=NOW)
    next_turn = begin_turn(store.load(binding, now=NOW), binding, turn_id="turn-2", user_question="COP", now=NOW)
    assert next_turn["turn"]["slots"]["amount"] is None
    next_turn["turn"]["intent"] = "OOD"  # A classifier's currency-only label is not the ongoing intent.
    merged = merge_explicit_slots(next_turn, {"currency": "COP", "amount": None, "amount_is_approximate": False})
    assert merged["turn"]["intent"] == "TRANSACTION_DISPUTE"
    assert merged["turn"]["slots"]["amount"] == 150
    assert merged["turn"]["slots"]["currency"] == "COP"
    assert merged["turn"]["slots"]["date_from"] == "2026-09-15"
    assert merged["turn"]["slots"]["amount_is_approximate"] is True
    assert merged["turn"]["slots"]["transaction_id"] is None
    assert merged["workflow_state"]["action"]["authorized"] is False


def test_unrelated_new_request_drops_field_context_and_counters(binding):
    state = state_for(binding)
    state["turn"]["intent"] = "TRANSACTION_DISPUTE"
    state["turn"]["slots"].update(amount=150, currency_raw="pesos")
    state = apply_decision(state, decide(state))
    next_turn = begin_turn(state, binding, turn_id="turn-2", user_question="estado de mi reclamo", now=NOW)
    next_turn["turn"]["intent"] = "COMPLAINT_STATUS"
    merged = merge_explicit_slots(next_turn, {"complaint_id": "CMP-new"}, continuing=False)
    assert merged["turn"]["intent"] == "COMPLAINT_STATUS"
    assert merged["turn"]["slots"]["complaint_id"] == "CMP-new"
    assert merged["turn"]["slots"]["amount"] is None
    assert "field_clarification" not in merged["runtime"]
    assert merged["workflow_state"]["counters"]["clarification_attempts"] == 0


@pytest.mark.parametrize("guard", ["human_requested", "unauthorized_reference", "deceptive"])
def test_guarded_field_reply_does_not_restore_previous_slots(binding, guard):
    state = state_for(binding)
    state["turn"]["intent"] = "TRANSACTION_DISPUTE"
    state["turn"]["slots"].update(amount=150, currency_raw="pesos")
    state = apply_decision(state, decide(state))
    next_turn = begin_turn(state, binding, turn_id="turn-2", user_question="COP", now=NOW)
    if guard == "deceptive":
        next_turn["turn"]["attack"]["deceptive"] = 1
    else:
        next_turn["turn"][guard] = True
    merged = merge_explicit_slots(next_turn, {"currency": "COP"})
    assert merged["turn"]["slots"]["amount"] is None
    assert merged["turn"]["intent"] is None
    assert merged["workflow_state"]["action"]["authorized"] is False
