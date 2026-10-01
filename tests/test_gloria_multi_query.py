"""Independent fictional observations for scoped multi-request conversations."""
from copy import deepcopy
import asyncio

import pytest

from gloria_workflow.state import TrustedBinding
from tests.test_gloria_acceptance import (
    NOW, SNAPSHOT, TRANSACTION_ID, OTHER_TRANSACTION_ID, ObservedStages,
    ObservedBank, binding, transaction, workflow, run_workflow, canonical_host_receipt,
    native_host_receipt, COMPLAINT_ID,
    policy_state,
)


FIRST = "No reconozco la compra de 25.50 USD."
SECOND = "Quiero información sobre la compra de 77 USD."
ORIGINAL = FIRST + " " + SECOND


class MultiStages(ObservedStages):
    def __init__(self, *, queries=None, domains=None, slot_changes=None, **kwargs):
        # Exercise the real canonical fallback instead of a content-free fake
        # generator that would hide whether both independent facts survive.
        kwargs.setdefault("generated", {"message": "El importe es 999999 USD.", "language": "pt" if kwargs.get("language") == "pt" else "es", "arquetipos": [], "chunk_ids": [], "data_sources": [], "grounding_violation": 0})
        super().__init__(**kwargs)
        self.queries = queries or [FIRST, SECOND]
        self.domains = domains or ["TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY"]
        self.slot_changes = slot_changes or {}

    async def run(self, stage, inputs, *, correction=None):
        if stage == "rewrite_decompose" and inputs["user_question"] == " ".join(self.queries):
            self.calls.append((stage, deepcopy(inputs)))
            return {"clean_query": inputs["user_question"], "sub_queries": [{"query_text": q} for q in self.queries]}
        if stage == "detect_intent":
            self.calls.append((stage, deepcopy(inputs)))
            return {"intents": [{"query_text": q, "domain": self.domains[self.queries.index(q)] if q in self.queries else self.intent} for q in inputs["queries"]]}
        if stage == "extract_slots":
            result = await super().run(stage, inputs, correction=correction)
            query = inputs["clean_query"]
            if query == SECOND:
                result["amount"] = 77
            result.update(self.slot_changes.get(query, {}))
            return result
        return await super().run(stage, inputs, correction=correction)


class ScopedBank(ObservedBank):
    def __init__(self, **kwargs):
        kwargs.setdefault("candidates", [transaction(), transaction(transaction_id=OTHER_TRANSACTION_ID, amount=77, ref="2", merchant_name="Fictional Coral Store")])
        super().__init__(**kwargs)
        self.receipt_scope_id = None

    async def read(self, name, args):
        if name == "search_transactions":
            self.calls.append((name, deepcopy(args)))
            slots = args["slots"]
            candidates = [r for r in self.candidates if (slots.get("amount") is None or r["amount"] == slots["amount"]) and (slots.get("transaction_id") is None or r["transaction_id"] == slots["transaction_id"])]
            return {"status": "ok", "match_count": len(candidates), "candidates": deepcopy(candidates), "snapshot_hash": SNAPSHOT,
                    "search_context": {"coverage_complete": True, "snapshot_id": SNAPSHOT, "used_snapshot_default": False}}
        result = await super().read(name, args)
        if name == "host_action_status" and result.get("state") in {"intake_verified", "action_unverified", "handoff_verified", "pending_confirmation"}:
            if self.receipt_scope_id is None:
                self.receipt_scope_id = args.get("query_id")
            result["query_id"] = self.receipt_scope_id
            result.setdefault("request_id", "fictional-request-" + str(self.receipt_scope_id))
            result.setdefault("pending_handle", "fictional-handle-" + str(self.receipt_scope_id))
            result.setdefault("snapshot_hash", SNAPSHOT)
        return result


def capsule_states(state):
    scopes = state["runtime"]["query_scopes"]
    order = state["runtime"]["query_scope_order"]
    return [scopes[key] for key in order]


def test_two_independent_queries_keep_targets_and_pending_separate(tmp_path):
    runner, stages, bank = workflow(tmp_path, MultiStages(), ScopedBank())
    result = run_workflow(runner, ORIGINAL, turn_id="multi-1")
    first, second = capsule_states(result)
    assert first["workflow_state"]["transaction_id"] == TRANSACTION_ID
    assert second["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    assert first["workflow_state"]["pending"]["type"] == "awaiting_confirmation"
    assert second["workflow_state"]["pending"]["type"] == "none"
    assert first["workflow_state"]["policy_decision"]["response_mode"] == "CONFIRM_ACTION"
    assert second["workflow_state"]["policy_decision"]["response_mode"] == "INFORM"
    assert len({item["query_id"] for item in (first, second)}) == 2
    assert result["workflow_state"]["transaction_id"] == TRANSACTION_ID
    for _, inputs in [call for call in stages.calls if call[0] == "generate"]:
        facts = str(inputs["structured_data"])
        assert not (TRANSACTION_ID in facts and OTHER_TRANSACTION_ID in facts)
    assert "25.5" in result["response"]["message"] and "77" in result["response"]["message"]
    assert all(name in bank.reads for name, _ in bank.calls)


def test_every_query_ownership_preflight_finishes_before_private_reads(tmp_path):
    stages = MultiStages(slot_changes={SECOND: {"foreign_customer_reference": True}})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    result = run_workflow(runner, ORIGINAL)
    assert result["workflow_state"]["policy_decision"]["response_mode"] == "BLOCKED"
    assert bank.calls == []
    assert len([call for call in stages.calls if call[0] == "extract_slots"]) == 3


@pytest.mark.parametrize("original_guard", ["human", "emergency", "attack", "expired"])
def test_original_turn_guards_dominate_all_subqueries(tmp_path, original_guard):
    stages = MultiStages(emotion="Emergencia" if original_guard == "emergency" else "Neutro")
    message = ORIGINAL
    trusted = binding()
    if original_guard == "human":
        message += " Quiero hablar con una persona."
        stages.queries = [FIRST, SECOND, "Quiero hablar con una persona."]
        stages.domains = ["TRANSACTION_DISPUTE", "TRANSACTION_INQUIRY", "HUMAN_REQUEST"]
    if original_guard == "expired":
        trusted["expires_at"] = NOW.timestamp()
    if original_guard == "attack":
        async def attack_run(stage, inputs, *, correction=None):
            if stage == "detect_attack":
                return {"deceptive": 1, "inappropriate": 0}
            return await MultiStages.run(stages, stage, inputs, correction=correction)
        stages.run = attack_run
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    result = asyncio.run(runner.run(trusted, message))
    assert bank.calls == []
    expected = "AUTH_REQUIRED" if original_guard == "expired" else "BLOCKED" if original_guard == "attack" else "HANDOFF"
    assert result["workflow_state"]["policy_decision"]["response_mode"] == expected


def test_one_query_receipt_never_authorizes_another_query(tmp_path):
    stages = MultiStages(domains=["TRANSACTION_DISPUTE", "TRANSACTION_DISPUTE"])
    runner, _, bank = workflow(tmp_path, stages, ScopedBank(host_status=canonical_host_receipt()))
    result = run_workflow(runner, ORIGINAL)
    first, second = capsule_states(result)
    assert first["workflow_state"]["action"]["verified"] is True
    assert second["workflow_state"]["action"]["verified"] is False
    assert second["workflow_state"]["action"]["result_id"] is None
    assert second["workflow_state"]["policy_decision"]["response_mode"] == "CONFIRM_ACTION"
    assert all(name in bank.reads for name, _ in bank.calls)


def test_unbounded_decomposition_fails_closed_before_any_read(tmp_path):
    queries = [f"Consulta independiente {i}" for i in range(9)]
    runner, _, bank = workflow(tmp_path, MultiStages(queries=queries, domains=["TRANSACTION_INQUIRY"] * 9), ScopedBank())
    result = run_workflow(runner, " ".join(queries))
    assert bank.calls == []
    assert result["workflow_state"]["policy_decision"]["response_mode"] in {"TOOL_ERROR", "HANDOFF"}


def test_portal_result_is_read_even_when_confirmation_reply_is_unclear(tmp_path):
    runner, stages, bank = workflow(tmp_path, MultiStages(), ScopedBank())
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    query_id = first["runtime"]["query_scope_order"][0]
    bank.host_status = canonical_host_receipt()
    after = run_workflow(runner, "¿Ya quedó?", turn_id="readback", query_scope_id=query_id)
    first_scope, second_scope = capsule_states(after)
    assert first_scope["workflow_state"]["policy_decision"]["response_mode"] == "ACTION_DONE"
    assert first_scope["workflow_state"]["action"]["result_id"] == COMPLAINT_ID
    assert second_scope["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    assert COMPLAINT_ID in after["response"]["message"]


def test_two_pending_queries_need_an_explicit_owned_scope(tmp_path):
    runner, stages, bank = workflow(tmp_path, MultiStages(domains=["TRANSACTION_DISPUTE"] * 2), ScopedBank())
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    before = len(bank.calls)
    answer = run_workflow(runner, "sí", turn_id="ambiguous")
    assert answer["runtime"]["query_scope_required"] is True
    assert len(bank.calls) == before
    assert all(scope["workflow_state"]["action"]["verified"] is False for scope in capsule_states(answer))
    before_stages = len(stages.calls)
    with pytest.raises(ValueError, match="invalid query scope"):
        run_workflow(runner, "sí", query_scope_id="q_not_owned")
    assert len(bank.calls) == before and len(stages.calls) == before_stages


def test_scoped_confirmation_never_switches_to_another_extracted_target(tmp_path):
    stages = MultiStages(domains=["TRANSACTION_DISPUTE"] * 2,
        resolution={"resolution_type": "CONFIRMED", "selected_ref": None})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    second_id = first["runtime"]["query_scope_order"][1]
    # The scripted reply mistakenly repeats the first amount. The existing
    # portal target still controls a confirmation's readonly evidence scope.
    result = run_workflow(runner, "sí", turn_id="scoped", query_scope_id=second_id)
    first_scope, second_scope = capsule_states(result)
    assert first_scope["workflow_state"]["transaction_id"] == TRANSACTION_ID
    assert second_scope["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    assert second_scope["workflow_state"]["pending"]["target_transaction_id"] == OTHER_TRANSACTION_ID
    assert not second_scope["workflow_state"]["action"]["authorized"]


@pytest.mark.parametrize("contradiction", ["id", "amount", "snapshot"])
def test_mixed_receipt_representations_must_agree(tmp_path, contradiction):
    status = canonical_host_receipt()
    status["receipt"] = native_host_receipt()["receipt"]
    if contradiction == "id": status["receipt"]["id"] = "CMP-SBX-Other001"
    elif contradiction == "amount": status["receipt"]["transaction"]["amount"] = "88.88"
    else: status["receipt"]["snapshot"] = "different-snapshot"
    runner, _, bank = workflow(tmp_path, bank=ObservedBank(host_status=status))
    result = run_workflow(runner, FIRST)
    assert result["workflow_state"]["policy_decision"]["response_mode"] == "ACTION_UNVERIFIED"
    assert not result["workflow_state"]["action"]["verified"]
    assert COMPLAINT_ID not in result["response"]["message"]


def test_combined_replay_rechecks_success_in_a_nonactive_query(tmp_path):
    runner, stages, bank = workflow(tmp_path, MultiStages(), ScopedBank(host_status=canonical_host_receipt()))
    first = run_workflow(runner, ORIGINAL, turn_id="replay")
    assert COMPLAINT_ID in first["response"]["message"]
    before_stages = len(stages.calls)
    before_reads = len(bank.calls)
    bank.host_status = {"status": "ok", "state": "none", "binding_verified": True, "binding": binding()}
    replay = run_workflow(runner, ORIGINAL, turn_id="replay")
    assert COMPLAINT_ID not in replay["response"]["message"]
    assert capsule_states(replay)[0]["workflow_state"]["policy_decision"]["response_mode"] == "ACTION_UNVERIFIED"
    assert len(stages.calls) == before_stages
    assert any(name == "host_action_status" for name, _ in bank.calls[before_reads:])
    revision = replay["runtime"]["store_revision"]
    with pytest.raises(ValueError, match="replay mismatch"):
        run_workflow(runner, "Cuerpo diferente", turn_id="replay")
    assert runner.store.load(TrustedBinding(**binding()), now=NOW)["runtime"]["store_revision"] == revision


def test_currency_reply_resumes_only_the_scope_missing_currency(tmp_path):
    stages = MultiStages(slot_changes={FIRST: {"currency": None, "currency_raw": "pesos"}})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    first_scope, second_scope = capsule_states(first)
    assert first_scope["workflow_state"]["missing_fields"] == ["currency"]
    query_id = first_scope["query_id"]
    stages.intent = "OOD"
    result = run_workflow(runner, "USD", turn_id="currency", query_scope_id=query_id)
    first_scope, second_scope = capsule_states(result)
    assert first_scope["turn"]["slots"]["amount"] == 25.50
    assert first_scope["turn"]["slots"]["currency"] == "USD"
    assert first_scope["workflow_state"]["policy_decision"]["response_mode"] == "CONFIRM_ACTION"
    assert second_scope["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    followup_inputs = [inputs for stage, inputs in stages.calls if stage == "generate"][-2:]
    assert all(OTHER_TRANSACTION_ID not in inputs["historic_conversation"] for inputs in followup_inputs)


def test_unrelated_currency_mention_clears_only_prior_field_context(tmp_path):
    stages = MultiStages(slot_changes={FIRST: {"currency": None, "currency_raw": "pesos"}})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    stages.intent = "OOD"
    before = len(bank.calls)
    result = run_workflow(runner, "Ahora quiero saber mi saldo en USD.", turn_id="new-topic", query_scope_id=first["runtime"]["query_scope_order"][0])
    first_scope, second_scope = capsule_states(result)
    assert first_scope["workflow_state"]["policy_decision"]["response_mode"] == "OUT_OF_SCOPE"
    assert "field_clarification" not in first_scope["runtime"]
    assert first_scope["workflow_state"]["transaction_id"] is None
    assert second_scope["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    assert len(bank.calls) == before


def test_selected_candidate_stays_in_its_query_scope(tmp_path):
    extra = transaction(transaction_id="TRX-ACCEPTANCE103", ref="2", merchant_name="Fictional Violet Store")
    bank = ScopedBank(candidates=[transaction(), extra, transaction(transaction_id=OTHER_TRANSACTION_ID, ref="3", amount=77)])
    stages = MultiStages(resolution={"resolution_type": "SELECTED", "selected_ref": "2"})
    runner, _, _ = workflow(tmp_path, stages, bank)
    first = run_workflow(runner, ORIGINAL, turn_id="initial")
    assert capsule_states(first)[0]["workflow_state"]["pending"]["type"] == "awaiting_selection"
    result = run_workflow(runner, "2", turn_id="selected", query_scope_id=first["runtime"]["query_scope_order"][0])
    first_scope, second_scope = capsule_states(result)
    assert first_scope["workflow_state"]["transaction_id"] == "TRX-ACCEPTANCE103"
    assert second_scope["workflow_state"]["transaction_id"] == OTHER_TRANSACTION_ID
    assert first_scope["tool_results"]["search_transactions"]["match_count"] == 2


def test_one_snapshot_failure_does_not_clear_a_sibling_target(tmp_path):
    bank = ScopedBank()
    actual_read = bank.read
    async def failed_second_target(name, args):
        if name == "get_transaction" and args["transaction_id"] == OTHER_TRANSACTION_ID:
            bank.calls.append((name, deepcopy(args)))
            return {"status": "error", "code": "snapshot_changed"}
        return await actual_read(name, args)
    bank.read = failed_second_target
    runner, _, _ = workflow(tmp_path, MultiStages(), bank)
    result = run_workflow(runner, ORIGINAL)
    first_scope, second_scope = capsule_states(result)
    assert first_scope["workflow_state"]["transaction_id"] == TRANSACTION_ID
    assert first_scope["workflow_state"]["pending"]["type"] == "awaiting_confirmation"
    assert second_scope["workflow_state"]["transaction_id"] is None
    assert second_scope["workflow_state"]["pending"]["type"] == "none"
    assert second_scope["workflow_state"]["policy_decision"]["response_mode"] in {"TOOL_ERROR", "HANDOFF"}


def test_original_ownership_extraction_cannot_be_dropped_by_decomposition(tmp_path):
    stages = MultiStages(slot_changes={ORIGINAL: {"foreign_customer_reference": True}})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    result = run_workflow(runner, ORIGINAL)
    assert result["workflow_state"]["policy_decision"]["response_mode"] == "BLOCKED"
    assert bank.calls == []


@pytest.mark.parametrize("language", ["es", "pt"])
def test_preprocessing_is_once_per_turn_and_generation_has_one_repair_per_scope(tmp_path, language):
    runner, stages, _ = workflow(tmp_path, MultiStages(language=language), ScopedBank())
    result = run_workflow(runner, ORIGINAL)
    for stage in ("rewrite_decompose", "detect_attack", "detect_context", "detect_intent"):
        assert sum(name == stage for name, _ in stages.calls) == 1
    assert sum(name == "extract_slots" for name, _ in stages.calls) == 3
    assert sum(name == "generate" for name, _ in stages.calls) == 4
    assert result["response"]["language"] == language
    assert all(scope["turn"]["language"] == language for scope in capsule_states(result))


@pytest.mark.parametrize("conflict", ["status_verified", "handoff_target", "receipt_snapshot"])
def test_canonical_handoff_rejects_explicit_contradictory_proof(tmp_path, conflict):
    runner, _, _ = workflow(tmp_path)
    state = policy_state()
    state["tool_results"]["get_transaction"]["snapshot_id"] = SNAPSHOT
    status = canonical_host_receipt(unknown=True, handoff=True)
    if conflict == "status_verified":
        status["verified"] = False
    elif conflict == "handoff_target":
        status["handoff"]["target_reference"] = OTHER_TRANSACTION_ID
    else:
        status["handoff"]["receipt"]["snapshot"] = "another-serving-build"
    runner._host_evidence(state, status, TrustedBinding(**binding()))
    assert state["workflow_state"]["handoff"]["created"] is False
    assert state["workflow_state"]["handoff"]["handoff_id"] is None


def test_canonical_handoff_accepts_absent_optional_projection_fields(tmp_path):
    runner, _, _ = workflow(tmp_path)
    state = policy_state()
    state["tool_results"]["get_transaction"]["snapshot_id"] = SNAPSHOT
    runner._host_evidence(state, canonical_host_receipt(unknown=True, handoff=True), TrustedBinding(**binding()))
    assert state["workflow_state"]["handoff"]["created"] is True


def test_pending_untouched_sibling_keeps_its_own_nonempty_prompt(tmp_path):
    stages = MultiStages(domains=["TRANSACTION_DISPUTE"] * 2,
        resolution={"resolution_type": "CONFIRMED", "selected_ref": None})
    runner, _, bank = workflow(tmp_path, stages, ScopedBank())
    initial = run_workflow(runner, ORIGINAL, turn_id="two-pending")
    original_first = capsule_states(initial)[0]
    before = len(stages.calls)
    result = run_workflow(runner, "sí", turn_id="continue-second",
        query_scope_id=initial["runtime"]["query_scope_order"][1])
    first, second = capsule_states(result)
    assert first["response"]["message"].strip()
    assert "25.5" in first["response"]["message"]
    assert "77" not in first["response"]["message"]
    assert "Consulta 1:\n\n" not in result["response"]["message"]
    assert first["workflow_state"]["pending"]["target_transaction_id"] == original_first["workflow_state"]["pending"]["target_transaction_id"]
    assert first["workflow_state"]["pending"].get("confirmed") is not True
    assert first["workflow_state"]["trusted_confirmation"]["verified"] is False
    assert first["workflow_state"]["action"]["authorized"] is False
    assert first["tool_results"] == {}
    assert sum(name == "generate" for name, _ in stages.calls[before:]) <= 2
    assert all(name in bank.reads for name, _ in bank.calls)

