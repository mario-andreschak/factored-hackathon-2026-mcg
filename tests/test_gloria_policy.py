"""Rule routes exercise the actual canonical state, with precedence overlaps."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from gloria_workflow.policy import decide, load_config
from gloria_workflow.state import TrustedBinding, apply_decision, begin_turn, new_state, set_pending


NOW = datetime(2026, 10, 1, 3, 50, tzinfo=timezone.utc)
BINDING = TrustedBinding(customer_id="CUST-private", session_id="session-1", conversation_id="conversation-1",
                         owner="owner-1", expires_at=NOW + timedelta(hours=1))


def ready_state(intent="TRANSACTION_DISPUTE"):
    state = begin_turn(new_state(BINDING, now=NOW), BINDING, turn_id="turn-1", user_question="cargo", now=NOW)
    state["turn"].update(intent=intent, language="es", effective_language="es")
    state["turn"]["slots"].update(amount=100, currency="USD")
    state["workflow_state"].update(search_criteria_present=True, transaction_id="TRX-one",
                                  transaction_identified=True, transaction_unique=True,
                                  candidate_snapshot_hash="hash-1")
    state["tool_results"] = {
        "search_transactions": {"status": "ok", "match_count": 1,
                                "candidates": [{"ref": "1", "transaction_id": "TRX-one", "label": "cargo"}],
                                "search_context": {"coverage_complete": True, "snapshot_id": "snapshot-1"}},
        "get_transaction": {"status": "ok", "snapshot_id": "snapshot-1",
                            "transaction": {"transaction_id": "TRX-one", "transaction_date": "2026-09-15",
                                            "amount": 100, "currency": "USD", "status": "Approved"},
                            "risk_signals": {"fraud_score": 20, "amount_usd": 100}, "data_quality_flags": []},
        "get_related_complaints": {"status": "ok", "complaints": [], "duplicate_check": "clear_in_snapshot",
                                   "match_method": "exact_sandbox", "report_window": {
                                       "scope": "prototype_sandbox_cases", "coverage_complete": True,
                                       "window_start": (NOW - timedelta(hours=24)).isoformat(),
                                       "window_end": NOW.isoformat(), "prior_distinct_verified_count": 0}}}
    return state


def confirming(state=None, *, trusted=False):
    state = ready_state() if state is None else deepcopy(state)
    state = apply_decision(state, decide(state))
    pending = state["workflow_state"]["pending"]
    pending.update(host_pending_handle="host-handle", request_id="4a1398d4-c605-4203-8b6a-6e26876348e5")
    if trusted:
        state["workflow_state"]["trusted_confirmation"].update(
            verified=True, source="host_portal", pending_handle=pending["host_pending_handle"],
            request_id=pending["request_id"], bound_identity_verified=True,
            bound_action_target_snapshot_verified=True, verified_at=NOW.isoformat(),
            expires_at=(NOW + timedelta(minutes=10)).isoformat())
    return state


def exact_case(state):
    related = state["tool_results"]["get_related_complaints"]
    related.update(duplicate_check="exact_open_case", complaints=[{
        "complaint_id": "CMP-one", "transaction_id": "TRX-one", "status": "Open", "linkage": "exact_sandbox"}])


@pytest.mark.parametrize("rule", [f"R{i}" for i in range(19)])
def test_every_canonical_rule_has_a_real_route(rule):
    state = ready_state()
    expected = {
        "R0": "AUTH_REQUIRED", "R1": "BLOCKED", "R2": "BLOCKED", "R3": "CONFIRM_ACTION",
        "R4": "ACTION_CANCELLED", "R5": "CLARIFY", "R6": "SMALL_TALK", "R7": "OUT_OF_SCOPE",
        "R8": "HANDOFF", "R9": "TOOL_ERROR", "R10": "CLARIFY", "R11": "NO_MATCH",
        "R12": "CLARIFY", "R13": "INFORM", "R14": "OUT_OF_POLICY", "R15": "INFORM_EXISTING_CASE",
        "R16": "HANDOFF", "R17": "CONFIRM_ACTION", "R18": "INFORM"}[rule]
    if rule == "R0":
        state["session"]["authenticated"] = False
    elif rule == "R1":
        state["turn"]["attack"]["deceptive"] = 1
    elif rule == "R2":
        state["turn"]["unauthorized_reference"] = True
    elif rule == "R3":
        state = confirming(trusted=True)
    elif rule == "R4":
        state = confirming()
        state["turn"]["clarification"]["resolution_type"] = "DENIED"
    elif rule == "R5":
        state["workflow_state"]["pending"].update(type="awaiting_selection", intent="TRANSACTION_DISPUTE",
            candidates=[{"ref": "2", "transaction_id": "TRX-two"}], snapshot_hash="hash-1", snapshot_id="snapshot-1")
        state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="2")
    elif rule in {"R6", "R7"}:
        state = new_state(BINDING, now=NOW)
        state["turn"]["intent"] = "GREETING" if rule == "R6" else "OOD"
    elif rule == "R8":
        state["turn"]["human_requested"] = True
    elif rule == "R9":
        state["runtime"]["node_errors"] = [{"node": "read", "code": "tool_error"}]
    elif rule == "R10":
        state["workflow_state"]["search_criteria_present"] = False
    elif rule == "R11":
        state["tool_results"]["search_transactions"].update(match_count=0, candidates=[])
    elif rule == "R12":
        state["workflow_state"].update(transaction_unique=False, transaction_identified=False)
        state["tool_results"]["search_transactions"].update(match_count=2, candidates=[
            {"ref": "1", "transaction_id": "TRX-one"}, {"ref": "2", "transaction_id": "TRX-two"}])
    elif rule == "R13":
        state["turn"]["intent"] = "TRANSACTION_INQUIRY"
    elif rule == "R14":
        state["tool_results"]["get_transaction"]["transaction"]["transaction_date"] = "2026-01-01"
    elif rule == "R15":
        exact_case(state)
    elif rule == "R16":
        state["tool_results"]["get_transaction"]["risk_signals"]["fraud_score"] = 70
    elif rule == "R18":
        state["turn"]["intent"] = "COMPLAINT_STATUS"
        state["tool_results"]["list_customer_complaints"] = {"status": "ok", "coverage_complete": True,
            "match_count": 1, "complaints": [{"complaint_id": "CMP-one", "status": "Open"}]}
    before = deepcopy(state)
    result = decide(state)
    assert result["rule_ids"] == [rule]
    assert result["response_mode"] == expected
    assert isinstance(result["reason_code"], str) and result["reason_code"]
    assert state == before, "decide must be pure"


@pytest.mark.parametrize("guard", ["R0", "R1", "R2"])
def test_guards_precede_live_consent_and_verified_receipts(guard):
    state = confirming(trusted=True)
    state["workflow_state"].update(action_attempted=True, action_outcome="verified")
    state["workflow_state"]["action"].update(authorized=True, executed=True, verified=True, result_id="CMP-one")
    state["tool_results"]["create_complaint"] = {"status": "ok", "complaint_id": "CMP-one", "executed": True}
    if guard == "R0":
        state["session"]["expired"] = True
    elif guard == "R1":
        state["turn"]["attack"]["inappropriate"] = 1
    else:
        state["turn"]["slots"]["foreign_customer_reference"] = True
    assert decide(state)["rule_ids"] == [guard]


def test_guard_precedence_overlaps():
    state = ready_state()
    state["session"]["authenticated"] = False
    state["turn"]["attack"]["deceptive"] = 1
    state["turn"]["unauthorized_reference"] = True
    assert decide(state)["rule_ids"] == ["R0"]
    state["session"]["authenticated"] = True
    assert decide(state)["rule_ids"] == ["R1"]
    state["turn"]["attack"]["deceptive"] = 0
    assert decide(state)["rule_ids"] == ["R2"]


@pytest.mark.parametrize("text,resolution", [("sí", "CONFIRMED"), ("sim", "CONFIRMED"), ("confirmar", "UNCLEAR")])
def test_chat_confirmation_never_authorizes(text, resolution):
    state = confirming()
    state["turn"]["user_question"] = text
    state["turn"]["clarification"]["resolution_type"] = resolution
    result = decide(state)
    applied = apply_decision(state, result)
    assert result["next_step"] == "await_host_confirmation"
    assert applied["workflow_state"]["action"]["authorized"] is False
    assert result["reason_code"] == "host_confirmation_required"


@pytest.mark.parametrize("field,value", [
    ("source", "chat"), ("verified", False), ("bound_identity_verified", False),
    ("bound_action_target_snapshot_verified", False), ("request_id", "different"),
    ("pending_handle", "different"), ("verified_at", None),
    ("expires_at", NOW.isoformat()),
    ("expires_at", (NOW + timedelta(minutes=11)).isoformat())])
def test_incomplete_or_stale_host_event_never_authorizes(field, value):
    state = confirming(trusted=True)
    state["workflow_state"]["trusted_confirmation"][field] = value
    result = decide(state)
    assert result["reason_code"] in {"host_confirmation_required", "stale_host_confirmation"}
    assert result["workflow_updates"]["action"]["authorized"] is False


def test_trusted_consent_revalidates_current_risk_and_policy():
    state = confirming(trusted=True)
    state["tool_results"]["get_transaction"]["risk_signals"]["fraud_score"] = 80
    result = decide(state)
    assert result["rule_ids"] == ["R16"] and result["clear_pending"]
    state = confirming(trusted=True)
    state["tool_results"]["get_transaction"]["transaction"]["status"] = "Declined"
    assert decide(state)["rule_ids"] == ["R14"]


def test_verified_terminal_action_preserves_audit_on_apply():
    state = ready_state()
    state["workflow_state"].update(action_attempted=True, action_outcome="verified")
    state["workflow_state"]["action"].update(authorized=True, executed=True, verified=True, result_id="CMP-one")
    state["tool_results"]["create_complaint"] = {"status": "ok", "complaint_id": "CMP-one", "executed": True}
    result = decide(state)
    assert result["response_mode"] == "ACTION_DONE"
    assert apply_decision(state, result)["workflow_state"]["action"]["authorized"] is True
    state["tool_results"]["create_complaint"]["complaint_id"] = "CMP-other"
    assert decide(state)["response_mode"] == "ACTION_UNVERIFIED"


@pytest.mark.parametrize("outcome", ["unknown", "executed"])
def test_attempted_uncertain_action_remains_terminal_after_pending_cleanup(outcome):
    state = ready_state()
    state["workflow_state"].update(action_attempted=True, action_outcome=outcome)
    state["workflow_state"]["pending"]["type"] = "none"
    state["workflow_state"]["search_criteria_present"] = False
    state["turn"]["intent"] = "GREETING"
    result = decide(state)
    assert result["response_mode"] == "ACTION_UNVERIFIED"
    assert result["next_step"] == "recover_action" and result["requires_human"]


def test_cancel_revokes_pending_without_erasing_attempt_identity():
    state = confirming()
    state["workflow_state"]["action"]["idempotency_key"] = "request-retained"
    state["turn"]["clarification"]["resolution_type"] = "DENIED"
    applied = apply_decision(state, decide(state))
    assert applied["workflow_state"]["pending"]["type"] == "none"
    assert applied["workflow_state"]["action"]["idempotency_key"] == "request-retained"
    assert applied["workflow_state"]["action"]["authorized"] is False


def test_selection_rereads_target_preserves_match_count_and_cannot_confirm():
    state = ready_state()
    state["tool_results"]["search_transactions"].update(match_count=2, candidates=[
        {"ref": "1", "transaction_id": "TRX-one"}, {"ref": "2", "transaction_id": "TRX-two"}])
    state["workflow_state"].update(transaction_unique=False, transaction_identified=False)
    state = apply_decision(state, decide(state))
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="1")
    result = decide(state)
    applied = apply_decision(state, result)
    assert result["rule_ids"] == ["R17"]
    assert applied["tool_results"]["search_transactions"]["match_count"] == 2
    assert applied["workflow_state"]["action"]["authorized"] is False
    assert applied["workflow_state"]["pending"]["type"] == "awaiting_confirmation"


def test_duplicate_after_selection_directly_hands_off():
    state = ready_state()
    state["tool_results"]["search_transactions"]["match_count"] = 2
    state["tool_results"]["get_transaction"]["data_quality_flags"] = ["possible_duplicate_of"]
    result = decide(state)
    assert result["rule_ids"] == ["R12"] and result["reason_code"] == "duplicate_review"


@pytest.mark.parametrize("choice", ["missing", "9", None])
def test_invalid_snapshot_reference_never_selects(choice):
    state = ready_state()
    state["workflow_state"]["pending"].update(type="awaiting_selection", candidates=[{"ref": "1", "transaction_id": "TRX-one"}],
                                               snapshot_hash="hash-1", snapshot_id="snapshot-1")
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref=choice)
    result = decide(state)
    assert result["rule_ids"] == ["R5"] and result["reason_code"] == "invalid_selection"
    assert result["clear_pending"]


def test_snapshot_change_invalidates_selection():
    state = ready_state()
    state["workflow_state"]["pending"].update(type="awaiting_selection", candidates=[{"ref": "1", "transaction_id": "TRX-one"}],
                                               snapshot_hash="hash-1", snapshot_id="old-snapshot")
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="1")
    assert decide(state, {"max_clarification_attempts": 3})["reason_code"] == "snapshot_changed"


def test_human_request_precedes_tools_search_and_invalid_selection():
    state = ready_state()
    state["turn"]["human_requested"] = True
    state["runtime"]["node_errors"] = [{"code": "failure"}]
    state["workflow_state"]["search_criteria_present"] = False
    assert decide(state)["rule_ids"] == ["R8"]
    state["workflow_state"]["pending"].update(type="awaiting_selection", candidates=[])
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="bad")
    assert decide(state)["rule_ids"] == ["R8"]


def test_small_talk_cannot_hide_active_business():
    state = ready_state()
    state["runtime"]["workflow_intent"] = "TRANSACTION_DISPUTE"
    state["turn"]["intent"] = "GREETING"
    assert decide(state)["rule_ids"] == ["R17"]


def test_currency_ambiguity_before_search():
    state = ready_state()
    state["turn"]["slots"].update(currency=None, currency_raw="pesos")
    assert decide(state)["workflow_updates"]["missing_fields"] == ["currency"]


def test_counter_reentry_and_exhaustion_are_bounded():
    state = ready_state()
    state["workflow_state"]["search_criteria_present"] = False
    first = apply_decision(state, decide(state))
    second = apply_decision(first, decide(first))
    assert second["workflow_state"]["counters"]["clarification_attempts"] == 1
    second["turn"]["turn_id"] = "turn-2"
    result = decide(second)
    assert result["response_mode"] == "HANDOFF" and result["reason_code"] == "clarification_exhausted"


@pytest.mark.parametrize("key,rule,reason", [("no_match_attempts", "R11", "no_match_exhausted"),
                                           ("tool_failures", "R9", "tool_failure")])
def test_session_failure_counter_threshold(key, rule, reason):
    state = ready_state()
    state["workflow_state"]["counters"][key] = 1
    if key == "no_match_attempts":
        state["tool_results"]["search_transactions"].update(match_count=0, candidates=[])
    else:
        state["tool_results"]["get_transaction"] = {"status": "error", "retries_exhausted": True}
    result = decide(state)
    assert result["rule_ids"] == [rule] and result["response_mode"] == "HANDOFF"
    assert result["reason_code"] == reason


def test_incomplete_search_cannot_infer_zero_or_unique():
    state = ready_state()
    state["tool_results"]["search_transactions"]["search_context"]["coverage_complete"] = False
    state["tool_results"]["search_transactions"].update(match_count=0, candidates=[])
    assert decide(state)["reason_code"] == "missing_evidence"


@pytest.mark.parametrize("intent,expected_rule", [("TRANSACTION_INQUIRY", "R13"), ("TRANSACTION_DISPUTE", "R14")])
def test_future_event_never_claimed_or_intaken(intent, expected_rule):
    state = ready_state(intent)
    state["tool_results"]["get_transaction"]["transaction"].update(transaction_date="2026-10-01", process_date="2026-09-01")
    result = decide(state)
    assert result["rule_ids"] == [expected_rule]
    assert result["response_mode"] == "HANDOFF" and result["reason_code"] == "missing_evidence"


@pytest.mark.parametrize("age,mode", [(120, "CONFIRM_ACTION"), (121, "OUT_OF_POLICY")])
def test_dispute_window_boundary_uses_real_event_date(age, mode):
    state = ready_state()
    today = datetime.fromisoformat(state["turn"]["current_date"]).date()
    state["tool_results"]["get_transaction"]["transaction"]["transaction_date"] = (today - timedelta(days=age)).isoformat()
    assert decide(state)["response_mode"] == mode


def test_r14_temporal_status_precedes_exact_case_r15_and_risk_r16():
    state = ready_state()
    exact_case(state)
    state["tool_results"]["get_transaction"]["risk_signals"]["fraud_score"] = 90
    state["tool_results"]["get_transaction"]["transaction"]["status"] = "Declined"
    result = decide(state)
    assert result["rule_ids"] == ["R14"] and result["offer_handoff"]
    assert result["requires_human"] is False
    state["tool_results"]["get_transaction"]["transaction"]["status"] = "Approved"
    assert decide(state)["rule_ids"] == ["R15"]


def test_historical_case_and_unlinked_exact_label_do_not_clear_write():
    state = ready_state()
    related = state["tool_results"]["get_related_complaints"]
    related.update(duplicate_check="historical_uncertain", complaints=[{"complaint_id": "CMP-old", "transaction_id": None}])
    assert decide(state)["reason_code"] == "missing_evidence"
    related["duplicate_check"] = "exact_open_case"
    assert decide(state)["response_mode"] == "HANDOFF"


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), -1, "0"])
def test_invalid_risk_never_becomes_low(value):
    state = ready_state()
    state["tool_results"]["get_transaction"]["risk_signals"]["fraud_score"] = value
    assert decide(state)["reason_code"] == "missing_evidence"


def test_high_signal_wins_when_other_risk_missing():
    state = ready_state()
    state["tool_results"]["get_transaction"]["risk_signals"].update(fraud_score=70, amount_usd=None)
    state["tool_results"]["get_related_complaints"]["report_window"]["coverage_complete"] = False
    assert decide(state)["reason_code"] == "high_risk"


def test_24h_count_requires_current_coverage_and_includes_distinct_current():
    state = ready_state()
    window = state["tool_results"]["get_related_complaints"]["report_window"]
    window["prior_distinct_verified_count"] = 2
    result = decide(state)
    assert result["reason_code"] == "high_risk"
    assert result["workflow_updates"]["unrecognized_count_24h"] == 3
    window["coverage_complete"] = False
    result = decide(state)
    assert result["reason_code"] == "missing_evidence" and result["workflow_updates"]["unrecognized_count_24h"] is None


def test_complaint_status_independent_of_transaction_matching():
    state = ready_state("COMPLAINT_STATUS")
    state["tool_results"]["search_transactions"].update(match_count=0, candidates=[])
    state["tool_results"]["list_customer_complaints"] = {"status": "ok", "match_count": 2, "coverage_complete": True,
        "complaints": [{"complaint_id": "CMP-one", "status": "Open"}, {"complaint_id": "CMP-two", "status": "Escalated"}]}
    result = decide(state)
    assert result["rule_ids"] == ["R18"] and result["pending"]["candidate_type"] == "complaint"
    applied = apply_decision(state, result)
    applied["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="2")
    applied["tool_results"]["get_complaint"] = {"status": "ok", "complaint": {"complaint_id": "CMP-two", "status": "Escalated"}}
    assert decide(applied)["response_mode"] == "INFORM"


def test_complaint_selection_has_its_own_snapshot_and_no_transaction_requirements():
    state = begin_turn(new_state(BINDING, now=NOW), BINDING, turn_id="turn-1", user_question="reclamos", now=NOW)
    state["turn"]["intent"] = "COMPLAINT_STATUS"
    state["tool_results"]["list_customer_complaints"] = {"status": "ok", "match_count": 2, "coverage_complete": True,
        "snapshot_id": "complaint-snapshot-1", "complaints": [{"complaint_id": "CMP-one", "status": "Open"},
                                                                  {"complaint_id": "CMP-two", "status": "Escalated"}]}
    result = decide(state)
    assert result["pending"]["snapshot_id"] == "complaint-snapshot-1"
    assert result["complaint_snapshot_hash"] == result["pending"]["snapshot_hash"]
    state = apply_decision(state, result)
    state = begin_turn(state, BINDING, turn_id="turn-2", user_question="el segundo", now=NOW + timedelta(seconds=1))
    state["turn"].update(intent="COMPLAINT_STATUS")
    state["turn"]["clarification"].update(resolution_type="SELECTED", selected_ref="2")
    state["tool_results"]["get_complaint"] = {"status": "ok", "snapshot_id": "complaint-snapshot-1",
                                              "complaint": {"complaint_id": "CMP-two", "status": "Escalated"}}
    assert decide(state)["response_mode"] == "INFORM"
    state["tool_results"]["get_complaint"]["snapshot_id"] = "complaint-snapshot-2"
    assert decide(state, {"max_clarification_attempts": 3})["reason_code"] == "snapshot_changed"


def test_new_request_clears_pending_target_and_resets_workflow_counters():
    state = confirming()
    state["workflow_state"]["counters"].update(clarification_attempts=1, no_match_attempts=1)
    state["turn"]["clarification"]["resolution_type"] = "NEW_REQUEST"
    result = decide(state)
    applied = apply_decision(state, result)
    assert result["next_step"] == "detect_intent"
    assert applied["workflow_state"]["pending"]["type"] == "none"
    assert applied["workflow_state"]["transaction_id"] is None
    assert applied["workflow_state"]["counters"]["clarification_attempts"] == 0


def test_canonical_transaction_status_has_precedence_over_compatibility_alias():
    state = ready_state()
    target = state["tool_results"]["get_transaction"]["transaction"]
    target.update(transaction_status="Declined", status="Approved")
    assert decide(state)["rule_ids"] == ["R14"]
    target["transaction_status"] = "Approved"
    target.pop("status")
    assert decide(state)["rule_ids"] == ["R17"]


def test_empty_incomplete_complaint_list_does_not_claim_no_cases():
    state = ready_state("COMPLAINT_STATUS")
    state["tool_results"]["list_customer_complaints"] = {"status": "ok", "match_count": 0, "complaints": [], "coverage_complete": False}
    assert decide(state)["reason_code"] == "missing_evidence"


def test_canonical_config_and_no_write_transition():
    assert load_config()["dispute_window_days"] == 120
    assert decide(ready_state())["next_step"] == "await_host_confirmation"
    assert decide(confirming(trusted=True))["next_step"] == "read_host_action_status"
    with pytest.raises(ValueError, match="invalid_policy_configuration"):
        decide(ready_state(), {"confirmation_ttl_seconds": 601})
