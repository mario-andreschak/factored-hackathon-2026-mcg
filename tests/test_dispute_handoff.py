"""Private human packets preserve exact query lineage and native evidence."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json

import pytest

from dispute_workflow.handoff import HandoffError, assemble_handoff_packet
from dispute_workflow.state import (
    TrustedBinding, activate_query_scope, begin_turn, new_state, start_query_batch,
)


NOW = datetime(2026, 10, 1, 4, 0, tzinfo=timezone.utc)
BINDING = TrustedBinding(
    customer_id="CLI-private-handoff-owner", session_id="handoff-session",
    conversation_id="handoff-conversation", owner="handoff-owner",
    expires_at=NOW + timedelta(hours=1),
)
TARGET = "txn_" + "a" * 24
DISPLAY_REFERENCE = "txn_" + "b" * 12
HANDOFF_ID = "HOF-Test0001"
REQUEST_ID = "4a1398d4-c605-4203-8b6a-6e26876348e5"
SNAPSHOT = "snapshot-original"
SNAPSHOT_HASH = "original-candidate-hash"


def narrative(language="es"):
    description = {"es": "habla española", "pt": "habla portuguesa", "other": "otro idioma"}[language]
    return {
        "request_summary": f"Cliente de {description} solicita revisar una compra que afirma no reconocer.",
        "customer_language": language,
        "customer_stated_claims": ["El cliente afirma no reconocer una compra."],
        "suggested_open_questions": ["¿Qué necesita revisar?"],
    }


def handoff_fixture(*, general=False, scoped=True, language="es"):
    state = begin_turn(new_state(BINDING, now=NOW), BINDING,
        turn_id="handoff-turn", user_question="Quiero atención humana.", now=NOW)
    if scoped:
        state = start_query_batch(state, [
            {"query_text": "Revisar mi cargo", "domain": "TRANSACTION_DISPUTE"},
            {"query_text": "Consultar otro cargo", "domain": "TRANSACTION_INQUIRY"},
        ])
        state = activate_query_scope(state, BINDING,
            state["runtime"]["query_scope_order"][0], now=NOW)
    state["turn"].update(language=language,
        effective_language="pt" if language == "pt" else "es",
        clean_query="Quiero atención humana.")
    reason = "customer_request"
    workflow = state["workflow_state"]
    workflow["policy_decision"] = {
        "response_mode": "HANDOFF", "reason_code": reason, "rule_ids": ["R8"],
        "requires_human": True, "requires_confirmation": False,
    }
    workflow["handoff"].update(required=True, created=True,
        handoff_id=HANDOFF_ID, reason_code=reason,
        receipt={"verified": True, "handoff_id": HANDOFF_ID})
    facts = {} if general else {
        "transaction_reference": DISPLAY_REFERENCE,
        "transaction_date": "2026-09-16T08:30:00",
        "process_date": "2026-09-16", "amount": "100.00", "currency": "USD",
        "status": "Approved", "merchant": "Tienda propia",
        "transaction_type": "Purchase", "channel": "POS", "product": "Debit",
    }
    provenance = None if general else {
        "source": "owned_serving_snapshot", "snapshot": SNAPSHOT,
        "as_of": NOW.isoformat(),
    }
    native = {
        "id": HANDOFF_ID, "reason": reason,
        "snapshot": None if general else SNAPSHOT, "created_at": NOW.isoformat(),
        "facts": facts, "human_responded": False,
        "transaction_currentness": "not_applicable" if general else "same_snapshot",
        "packet": {
            "schema": "banking-sandbox-handoff/v1",
            "transaction": None if general else deepcopy(facts),
            "transaction_provenance": provenance, "reason": reason,
            "unanswered_questions": ["¿Qué aspecto necesita revisar?"],
            "human_responded": False,
        },
    }
    if not general:
        workflow.update(transaction_id=TARGET, transaction_identified=True,
            transaction_unique=True, candidate_snapshot_hash=SNAPSHOT_HASH)
        state["tool_results"]["get_transaction"] = {
            "status": "ok", "snapshot_id": SNAPSHOT,
            "transaction": {
                "transaction_id": TARGET, "customer_id": BINDING.customer_id,
                **{key: value for key, value in facts.items() if key != "transaction_reference"},
            },
        }
    state["runtime"]["handoff_lineage"] = {
        "query_id": state["runtime"].get("active_query_id"),
        "binding_digest": BINDING.digest(), "handoff_id": HANDOFF_ID,
        "request_id": REQUEST_ID,
        "host_pending_handle": None if general else "A" * 40,
        "target_transaction_id": None if general else TARGET,
        "snapshot_id": None if general else SNAPSHOT,
        "snapshot_hash": None if general else SNAPSHOT_HASH,
    }
    state["runtime"]["handoff_narrative"] = narrative(language)
    return state, native


def fact_values(packet):
    return {item["field"]: item["value"] for item in packet["verified_facts"]}


@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("general", [False, True])
def test_targeted_and_general_packets_use_only_verified_native_facts(general, scoped):
    state, native = handoff_fixture(general=general, scoped=scoped)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["schema"] == "dispute-human-handoff/v1"
    assert packet["handoff_id"] == HANDOFF_ID
    assert packet["query_id"] == state["runtime"].get("active_query_id")
    assert packet["binding_digest"] == BINDING.digest()
    assert packet["target_transaction_id"] == (None if general else TARGET)
    assert packet["snapshot_id"] == native["snapshot"]
    assert packet["reason_code"] == "customer_request"
    assert packet["rule_ids"] == ["R8"]
    assert packet["human_responded"] is False
    assert fact_values(packet) == native["facts"]
    assert all(isinstance(item["source"], str) and item["source"] for item in packet["verified_facts"])
    assert any(item["id"] == HANDOFF_ID for item in packet["evidence"])
    assert packet["native_handoff"]["packet"] == native["packet"]
    assert packet["native_handoff"]["facts"] == native["facts"]
    assert packet["customer_stated_claims"] == narrative()["customer_stated_claims"]
    assert 0 <= len(packet["open_questions"]) <= 4


@pytest.mark.parametrize("field,value", [
    ("handoff_id", "HOF-Other001"), ("request_id", "not-a-uuid"),
    ("binding_digest", "foreign-digest"), ("query_id", "q_" + "c" * 32),
    ("target_transaction_id", "txn_" + "c" * 24),
    ("target_transaction_id", DISPLAY_REFERENCE),
    ("snapshot_id", "different-snapshot"), ("snapshot_hash", "different-hash"),
])
def test_every_required_lineage_dimension_is_checked(field, value):
    state, native = handoff_fixture()
    state["runtime"]["handoff_lineage"][field] = value
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("field", [
    "query_id", "binding_digest", "handoff_id", "request_id",
    "target_transaction_id", "snapshot_id", "snapshot_hash",
])
def test_missing_required_lineage_never_proves_a_handoff(field):
    state, native = handoff_fixture()
    del state["runtime"]["handoff_lineage"][field]
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


def test_missing_lineage_does_not_fall_back_to_workflow_success_flags():
    state, native = handoff_fixture()
    del state["runtime"]["handoff_lineage"]
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


def test_same_target_and_snapshot_do_not_allow_sibling_packet_transplant():
    state, native = handoff_fixture()
    first, second = state["runtime"]["query_scope_order"]
    assert state["runtime"]["handoff_lineage"]["query_id"] == first
    state["runtime"]["active_query_id"] = second
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("field", ["owner", "customer_id", "session_id", "conversation_id", "expires_at"])
def test_packet_binding_must_match_current_trusted_session(field):
    state, native = handoff_fixture()
    value = NOW + timedelta(hours=2) if field == "expires_at" else "foreign-binding-value"
    foreign = replace(BINDING, **{field: value})
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=foreign)


@pytest.mark.parametrize("field,value", [("authenticated", False), ("expired", True)])
def test_invalid_live_session_never_assembles_private_packet(field, value):
    state, native = handoff_fixture()
    state["session"][field] = value
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


def test_expired_binding_is_checked_against_current_query_frame_clock():
    state, native = handoff_fixture()
    # A stale persisted session marker cannot override the trusted expiry.
    state["turn"]["current_timestamp"] = (NOW + timedelta(hours=2)).isoformat()
    assert state["session"]["expired"] is False
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("field", ["target_transaction_id", "snapshot_id", "snapshot_hash"])
def test_general_handoff_cannot_carry_transaction_lineage(field):
    state, native = handoff_fixture(general=True)
    state["runtime"]["handoff_lineage"][field] = "unexpected-target-evidence"
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


def test_general_native_packet_cannot_be_attributed_to_a_selected_target():
    state, native = handoff_fixture(general=True)
    state["workflow_state"].update(transaction_id=TARGET, transaction_identified=True,
        transaction_unique=True, candidate_snapshot_hash=SNAPSHOT_HASH)
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("mutation", [
    "schema", "missing_facts", "contradictory_transaction", "contradictory_reason",
    "human_responded", "bad_provenance", "conflicting_alias", "missing_packet",
])
def test_malformed_or_contradictory_native_packet_fails_closed(mutation):
    state, native = handoff_fixture()
    if mutation == "schema": native["packet"]["schema"] = "untrusted/v0"
    elif mutation == "missing_facts": del native["facts"]["transaction_reference"]
    elif mutation == "contradictory_transaction": native["packet"]["transaction"]["amount"] = "999.00"
    elif mutation == "contradictory_reason": native["packet"]["reason"] = "high_risk"
    elif mutation == "human_responded": native["human_responded"] = True
    elif mutation == "bad_provenance": native["packet"]["transaction_provenance"]["snapshot"] = "other"
    elif mutation == "conflicting_alias": native["unanswered_questions"] = ["¿Otra pregunta?"]
    elif mutation == "missing_packet": del native["packet"]
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("location", ["decision", "handoff"])
def test_native_reason_must_match_applied_policy_and_handoff_reason(location):
    state, native = handoff_fixture()
    field = "policy_decision" if location == "decision" else "handoff"
    state["workflow_state"][field]["reason_code"] = "high_risk"
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("rules", [[], ["invented_rule"], "R8", [True]])
def test_missing_or_malformed_policy_rule_evidence_is_rejected(rules):
    state, native = handoff_fixture()
    state["workflow_state"]["policy_decision"]["rule_ids"] = rules
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


@pytest.mark.parametrize("language", ["es", "pt", "other"])
def test_original_customer_language_survives_spanish_narration(language):
    state, native = handoff_fixture(language=language)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["customer_language"] == language
    assert packet["request_summary"] == narrative(language)["request_summary"]


def test_effective_spanish_cannot_overwrite_original_other_language():
    state, native = handoff_fixture(language="other")
    state["runtime"]["handoff_narrative"] = narrative("es")
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["customer_language"] == "other"
    assert packet["customer_stated_claims"] == []
    assert packet["request_summary"] != narrative("es")["request_summary"]


@pytest.mark.parametrize("injected", [
    {"reason_code": "high_risk"}, {"rule_ids": ["R16"]},
    {"verified_facts": [{"field": "amount", "value": "999.00", "source": "model"}]},
    {"actions_taken": [{"action": "CREATE_COMPLAINT", "result": "CMP-SBX-Forged00"}]},
    {"evidence": [{"source": "model", "id": "CMP-SBX-Forged00"}]},
    {"risk_signals": {"fraud_score": 99}}, {"customer_id": BINDING.customer_id},
])
def test_narrative_never_supplies_authority_fields(injected):
    state, native = handoff_fixture()
    state["runtime"]["handoff_narrative"].update(injected)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["reason_code"] == "customer_request"
    assert packet["rule_ids"] == ["R8"]
    assert fact_values(packet) == native["facts"]
    assert "Forged00" not in json.dumps(packet)
    assert "customer_id" not in packet
    assert "risk_signals" not in packet or packet["risk_signals"] == {}
    assert packet["customer_stated_claims"] == []


@pytest.mark.parametrize("bad_narrative", [
    None, {"request_summary": "Invented"},
    narrative() | {"request_summary": "Cliente de habla española: persona@example.test."},
    narrative() | {"request_summary": "Cliente de habla española afirma una compra de 99999.99 EUR."},
    narrative() | {"customer_stated_claims": ["Existe fraude probado en este cargo."]},
    narrative() | {"request_summary": "Cliente de habla española solicita revisar. El reclamo fue registrado."},
])
def test_invalid_optional_narrative_uses_safe_fallback_without_fabricated_claims(bad_narrative):
    state, native = handoff_fixture()
    state["runtime"]["handoff_narrative"] = deepcopy(bad_narrative)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert isinstance(packet["request_summary"], str) and packet["request_summary"]
    assert packet["customer_language"] == "es"
    assert packet["customer_stated_claims"] == []
    assert fact_values(packet) == native["facts"]
    assert all(text not in packet["request_summary"] for text in ("persona@example.test", "99999.99", "fue registrado", "Invented"))


def test_questions_are_bounded_filtered_and_do_not_rewrite_saved_native_packet():
    state, native = handoff_fixture()
    native_questions = [
        "¿Qué aspecto necesita revisar?", "¿Cuál es su contraseña?",
        "¿Cuál es su correo electrónico?", "¿Qué información falta?",
        "¿Qué aspecto necesita revisar?", "¿Qué desea aclarar?",
    ]
    native["packet"]["unanswered_questions"] = deepcopy(native_questions)
    state["runtime"]["handoff_narrative"]["suggested_open_questions"] = [
        "¿Qué desea aclarar?", "¿Qué necesita revisar?", "¿Qué detalle le preocupa?",
    ]
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert 0 < len(packet["open_questions"]) <= 4
    assert len(set(packet["open_questions"])) == len(packet["open_questions"])
    assert not any("contraseña" in item or "correo" in item for item in packet["open_questions"])
    assert packet["native_handoff"]["packet"]["unanswered_questions"] == native_questions
    assert native["packet"]["unanswered_questions"] == native_questions


@pytest.mark.parametrize("currentness", ["different_snapshot", "unknown"])
def test_changed_currentness_preserves_original_historical_facts_and_provenance(currentness):
    state, native = handoff_fixture()
    native["transaction_currentness"] = currentness
    state["tool_results"]["get_transaction"]["snapshot_id"] = "snapshot-new"
    state["tool_results"]["get_transaction"]["transaction"]["amount"] = "999.00"
    state["tool_results"]["get_transaction"]["risk_signals"] = {"fraud_score": 99, "is_fraud": True}
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert fact_values(packet) == native["facts"]
    assert packet["native_handoff"]["packet"]["transaction_provenance"] == native["packet"]["transaction_provenance"]
    assert packet["native_handoff"]["transaction_currentness"] == currentness
    assert "risk_signals" not in packet or packet["risk_signals"] == {}


@pytest.mark.parametrize("mismatch", ["failed_read", "owner", "target", "snapshot"])
def test_risk_from_an_unmatched_or_failed_read_never_enters_private_packet(mismatch):
    state, native = handoff_fixture()
    read = state["tool_results"]["get_transaction"]
    read["risk_signals"] = {"fraud_score": 99, "is_fraud": True, "amount_usd": 100}
    if mismatch == "failed_read": read["status"] = "error"
    elif mismatch == "owner": read["transaction"]["customer_id"] = "foreign-customer"
    elif mismatch == "target": read["transaction"]["transaction_id"] = "txn_" + "c" * 24
    elif mismatch == "snapshot": read["snapshot_id"] = "snapshot-other"
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert "risk_signals" not in packet or packet["risk_signals"] == {}


def add_matching_risk(state):
    state["tool_results"]["get_transaction"]["risk_signals"] = {
        "fraud_score": 70, "amount_usd": 100, "is_fraud": False,
        "customer_secret": "risk-private-sentinel",
    }


def test_matching_owned_snapshot_risk_is_private_and_allowlisted():
    state, native = handoff_fixture()
    add_matching_risk(state)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["risk_signals"] == {"fraud_score": 70, "amount_usd": 100, "is_fraud": False}
    assert "risk-private-sentinel" not in json.dumps(packet)
    assert all("fraud" not in str(item["field"]) for item in packet["verified_facts"])
    assert "fraud" not in json.dumps({key: packet[key] for key in ("request_summary", "customer_stated_claims", "open_questions")})


@pytest.mark.parametrize("timestamp_field", ["observed_at", "verified_at"])
@pytest.mark.parametrize("age", [-1, 21])
def test_optional_risk_timestamp_must_be_recent_and_not_in_the_future(timestamp_field, age):
    state, native = handoff_fixture()
    add_matching_risk(state)
    state["tool_results"]["get_transaction"][timestamp_field] = (NOW - timedelta(seconds=age)).isoformat()
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert "risk_signals" not in packet or packet["risk_signals"] == {}


def report_window(state, *, age=0, complete=True):
    end = NOW - timedelta(seconds=age)
    state["tool_results"]["get_related_complaints"] = {
        "status": "ok", "report_window": {
            "scope": "prototype_sandbox_cases", "coverage_complete": complete,
            "window_start": (end - timedelta(hours=24)).isoformat(),
            "window_end": end.isoformat(), "prior_distinct_verified_count": 2,
        },
    }


def test_report_count_comes_from_current_complete_window_not_cached_workflow_value():
    state, native = handoff_fixture()
    add_matching_risk(state)
    state["workflow_state"].update(unrecognized_count_24h=99, risk_data_complete=True)
    report_window(state)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["risk_signals"]["unrecognized_count_24h"] == 3
    assert "99" not in json.dumps(packet["risk_signals"])


@pytest.mark.parametrize("kind", ["absent", "incomplete", "stale", "future", "wrong_scope", "wrong_span"])
def test_uncorroborated_cached_report_count_never_enters_human_packet(kind):
    state, native = handoff_fixture()
    add_matching_risk(state)
    state["workflow_state"].update(unrecognized_count_24h=99, risk_data_complete=True)
    if kind != "absent":
        report_window(state, age=21 if kind == "stale" else -1 if kind == "future" else 0,
            complete=kind != "incomplete")
        report = state["tool_results"]["get_related_complaints"]["report_window"]
        if kind == "wrong_scope": report["scope"] = "other_customer_cases"
        if kind == "wrong_span": report["window_start"] = NOW.isoformat()
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet.get("risk_signals", {}).get("unrecognized_count_24h") is None


def test_unverified_action_flags_and_trace_strings_cannot_become_completed_actions():
    state, native = handoff_fixture()
    state["workflow_state"]["policy_decision"].update(response_mode="ACTION_UNVERIFIED", reason_code="action_unverified")
    state["workflow_state"]["handoff"]["reason_code"] = "action_unverified"
    native["reason"] = native["packet"]["reason"] = "action_unverified"
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["workflow_state"]["action"].update(name="CREATE_COMPLAINT", executed=True,
        verified=False, result_id="CMP-SBX-Forged00")
    state["trace"] = [{"node": "create_complaint", "result": "success", "complaint_id": "CMP-SBX-Forged00"}]
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert packet["reason_code"] == "action_unverified"
    assert "CMP-SBX-Forged00" not in json.dumps(packet)
    assert state["workflow_state"]["action_outcome"] == "unknown"
    assert state["workflow_state"]["action"]["verified"] is False


def test_output_is_an_allowlisted_deep_copy_of_private_evidence():
    state, native = handoff_fixture()
    native.update(customer_id=BINDING.customer_id, risk_signals={"fraud_score": 99},
        actions_taken=[{"action": "forged", "result": "forged"}], secret="sentinel-private")
    original_state, original_native = deepcopy(state), deepcopy(native)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert state == original_state and native == original_native
    assert all(key not in packet["native_handoff"] for key in ("customer_id", "risk_signals", "actions_taken", "secret"))
    narrative_json = json.dumps({key: packet[key] for key in ("request_summary", "customer_stated_claims", "open_questions")})
    assert all(value not in narrative_json for value in (BINDING.customer_id, BINDING.owner, REQUEST_ID, "A" * 40))
    packet["native_handoff"]["packet"]["transaction"]["amount"] = "777.00"
    packet["rule_ids"].append("R16")
    assert state == original_state and native == original_native


@pytest.mark.parametrize("field", ["query_id", "target_transaction_id", "snapshot_id", "snapshot_hash"])
def test_general_handoff_requires_explicit_nullable_lineage_fields(field):
    state, native = handoff_fixture(general=True, scoped=False)
    del state["runtime"]["handoff_lineage"][field]
    with pytest.raises(HandoffError):
        assemble_handoff_packet(state, native, binding=BINDING)


def test_error_report_cannot_supply_a_count_even_with_a_complete_window():
    state, native = handoff_fixture()
    add_matching_risk(state)
    report_window(state)
    state["tool_results"]["get_related_complaints"]["status"] = "error"
    assert "unrecognized_count_24h" not in assemble_handoff_packet(state, native, binding=BINDING)["risk_signals"]


def test_every_supplied_risk_timestamp_must_agree_with_freshness():
    state, native = handoff_fixture()
    add_matching_risk(state)
    state["tool_results"]["get_transaction"].update(verified_at=NOW.isoformat(), observed_at="invalid")
    assert "risk_signals" not in assemble_handoff_packet(state, native, binding=BINDING)


def intake_fixture():
    state, native = handoff_fixture()
    lineage = deepcopy(state["runtime"]["handoff_lineage"])
    state["runtime"]["action_lineage"] = lineage
    rid = "CMP-SBX-Case0001"
    state["workflow_state"].update(action_attempted=True, action_outcome="unknown")
    state["tool_results"]["host_action_status"] = {
        "status": "ok", "state": "intake_verified", "verified": True, "binding_verified": True,
        "binding": {**dict(zip(("owner", "customer_id", "session_id", "conversation_id"), BINDING.key())),
                    "expires_at": BINDING.expires_at.isoformat()},
        "query_id": lineage["query_id"], "request_id": lineage["request_id"],
        "pending_handle": lineage["host_pending_handle"], "target_reference": TARGET,
        "snapshot": SNAPSHOT, "snapshot_hash": SNAPSHOT_HASH,
        "receipt": {"id": rid, "kind": "simulated_intake", "simulated": True, "status": "received",
                    "snapshot": SNAPSHOT, "created_at": NOW.isoformat(), "transaction": deepcopy(native["facts"])},
        "action": {"name": "CREATE_COMPLAINT", "authorized": True, "executed": True, "verified": True,
                   "result_id": rid, "receipt": {"verified": True, "result_id": rid}},
    }
    return state, native


@pytest.mark.parametrize("conflict", ["lineage_snapshot", "lineage_hash", "status_snapshot", "status_hash",
                                     "canonical_id", "canonical_amount", "error_envelope", "null_action",
                                     "null_canonical_receipt", "canonical_reference", "canonical_action_reference"])
def test_every_intake_representation_must_match_before_becoming_verified_handoff_evidence(conflict):
    state, native = intake_fixture()
    before = deepcopy(state)
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert any(item["source"] == "sandbox_cases" for item in packet["evidence"])
    assert state == before
    status = state["tool_results"]["host_action_status"]
    if conflict == "lineage_snapshot": state["runtime"]["action_lineage"]["snapshot_id"] = "other"
    elif conflict == "lineage_hash": state["runtime"]["action_lineage"]["snapshot_hash"] = "other"
    elif conflict == "status_snapshot": status["snapshot"] = "other"
    elif conflict == "status_hash": status["snapshot_hash"] = "other"
    elif conflict == "canonical_id": status["action"]["result_id"] = "CMP-SBX-Other001"
    elif conflict == "error_envelope": status["status"] = "error"
    elif conflict == "null_action": status["action"] = None
    elif conflict == "null_canonical_receipt": status["action"]["receipt"] = None
    elif conflict in {"canonical_reference", "canonical_action_reference"}:
        projection = status["action"] if conflict == "canonical_action_reference" else status["action"]["receipt"]
        projection["transaction"] = deepcopy(native["facts"])
        projection["transaction"]["transaction_reference"] = "txn_" + "f" * 12
    else:
        status["action"]["receipt"]["transaction"] = deepcopy(native["facts"])
        status["action"]["receipt"]["transaction"]["amount"] = "999.00"
    packet = assemble_handoff_packet(state, native, binding=BINDING)
    assert all(item["source"] != "sandbox_cases" for item in packet["evidence"])
    assert not any(item["action"] == "CREATE_COMPLAINT" and item["result"].get("verified") is True
                   for item in packet["actions_taken"] if isinstance(item["result"], dict))
