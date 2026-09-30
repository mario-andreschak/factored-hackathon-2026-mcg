"""Pure delegated-result boundaries. Recording fakes are not ledger proof."""
from __future__ import annotations

from copy import deepcopy
import time
import unittest
import uuid

from frontend.server.bank_controller import BankController
from frontend.server.bank_rpc import BankContext, BankRPCError
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected


HANDLE = "a" * 43
SNAPSHOT = "test"


def delegated(value):
    return {**deepcopy(value), "synthetic": False, "operator_test": False}


def risk(*, complete=True, count=1):
    return {"unrecognized_count_24h": count, "risk_data_complete": complete,
            "coverage": "sandbox_only", "source": "sandbox_cases",
            "window_start": "2026-09-28T15:00:00Z", "window_end": "2026-09-29T15:00:00Z"}


def prepare_result(*, decision="intake", reason=None, existing_state="not_found", receipt=None):
    return delegated({"action": "simulated_intake", "decision": decision, "reason": reason,
        "snapshot": SNAPSHOT, "transaction": action_facts(), "pending_handle": HANDLE,
        "existing_case": {"state": existing_state, "receipt": deepcopy(receipt),
                          "coverage": "sandbox_only", "source": "sandbox_cases"},
        "risk": risk(complete=decision == "intake", count=1 if decision == "intake" else None)})


def receipt_result(receipt=None, *, absent=False):
    return delegated({"state": "action_unverified" if absent else "created",
                      "receipt": None if absent else deepcopy(receipt or action_receipt())})


def handoff_result(packet=None):
    return delegated({"state": "created", "handoff": deepcopy(packet or action_handoff())})


class RecordingRPC:
    def __init__(self):
        self.calls = []
        self.answers = {"prepare_unrecognized_charge": prepare_result(),
                        "confirm_simulated_intake": receipt_result(),
                        "read_intake_receipt": receipt_result()}
        self.saved_handoff = None
        self.handler = None

    async def call(self, tool, args, context, *, timeout_seconds=45):
        self.calls.append((tool, deepcopy(args), context, timeout_seconds))
        if self.handler is not None:
            result = self.handler(tool, args, context)
            if result is not None:
                return deepcopy(result)
        if tool == "create_verified_handoff":
            self.saved_handoff = action_handoff(reason=args["reason"],
                snapshot=SNAPSHOT if args.get("pending_handle") else None,
                questions=args["unanswered_questions"])
            return handoff_result(self.saved_handoff)
        if tool == "read_verified_handoff":
            if self.saved_handoff is None:
                raise AssertionError("Read must follow an authored creation result")
            return handoff_result(self.saved_handoff)
        result = self.answers[tool]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)


class BankControllerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.rpc = RecordingRPC()
        self.controller = BankController(self.rpc)
        self.context = BankContext("fixture-subject", "fixture-bank-session", "fixture-bank-conversation",
            str(uuid.uuid4()), "a" * 40, int(time.time()) + 3600)
        self.request_id = str(uuid.uuid4())

    def prepare_payload(self, **changes):
        return {"operation": "prepare", "transactionId": "private-owned-charge", "snapshot": SNAPSHOT,
                "requestId": self.request_id, "expected_transaction": action_selected(), **changes}

    def confirm_payload(self, **changes):
        return {"operation": "confirm", "pendingHandle": HANDLE, "confirmed": True, **changes}

    def handoff_payload(self, *, general=False, **changes):
        return {"operation": "handoff", "reason": "customer_request", "requestId": self.request_id,
                "unanswered_questions": ["¿Cuál es el próximo paso?", "Qual ajuda precisa?"],
                **({} if general else {"pendingHandle": HANDLE, "expected_transaction": action_facts(),
                                       "expected_snapshot": SNAPSHOT}), **changes}

    def tools(self):
        return [tool for tool, _, _, _ in self.rpc.calls]

    async def test_valid_intake_is_pending_and_does_not_confirm_or_handoff(self):
        result = await self.controller.execute(self.prepare_payload(), self.context)
        self.assertEqual(result, {"state": "pending_confirmation", "pending_handle": HANDLE,
                                  "snapshot": SNAPSHOT, "transaction": action_facts()})
        self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])
        tool, args, context, timeout = self.rpc.calls[0]
        self.assertEqual(args, {"transaction_id": "private-owned-charge", "snapshot": SNAPSHOT,
                               "request_id": self.request_id})
        self.assertIs(context, self.context)
        self.assertEqual(timeout, 45)

    async def test_mode_flags_must_be_explicit_false_before_any_followup(self):
        for field in ["synthetic", "operator_test"]:
            for value in [True, 0, None, "false", "omitted"]:
                with self.subTest(field=field, value=value):
                    self.rpc.calls.clear()
                    raw = prepare_result(decision="handoff", reason="missing_evidence")
                    if value == "omitted":
                        raw.pop(field)
                    else:
                        raw[field] = value
                    self.rpc.answers["prepare_unrecognized_charge"] = raw
                    with self.assertRaises(BankRPCError) as error:
                        await self.controller.execute(self.prepare_payload(), self.context)
                    self.assertEqual(error.exception.code, "bank_invalid_response")
                    self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])

    async def test_contradictory_prepare_fields_never_trigger_followup_hof(self):
        cases = []
        for decision, reason, state, receipt in [
            ("intake", "high_risk", "not_found", None),
            ("handoff", None, "not_found", None),
            ("existing_case", None, "not_found", None),
            ("intake", None, "verified", action_receipt()),
            ("handoff", "missing_evidence", "verified", action_receipt()),
            ("handoff", "missing_evidence", "action_unverified", None),
        ]:
            cases.append(prepare_result(decision=decision, reason=reason, existing_state=state, receipt=receipt))
        foreign = prepare_result(decision="existing_case", existing_state="verified", receipt=action_receipt())
        foreign["existing_case"]["receipt"]["transaction"]["amount"] = "151.00"
        cases.append(foreign)
        for index, raw in enumerate(cases):
            with self.subTest(case=index):
                self.rpc.calls.clear()
                self.rpc.answers["prepare_unrecognized_charge"] = raw
                with self.assertRaises(BankRPCError) as error:
                    await self.controller.execute(self.prepare_payload(), self.context)
                self.assertEqual(error.exception.code, "bank_invalid_response")
                self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])

    async def test_impossible_intake_risk_is_rejected_without_followup(self):
        cases = [risk(complete=False, count=None), risk(complete=True, count=None),
                 risk(complete=True, count=-1), risk(complete=True, count=0),
                 risk(complete=True, count=3), risk(complete=True, count=True),
                 {**risk(), "window_start": "2026-09-30T15:00:00Z"},
                 {**risk(), "window_end": "2026-09-29T16:00:00Z"},
                 {**risk(), "coverage": "bank_wide"}, {**risk(), "source": "model_guess"}]
        for index, item in enumerate(cases):
            with self.subTest(case=index):
                self.rpc.calls.clear()
                raw = prepare_result()
                raw["risk"] = item
                self.rpc.answers["prepare_unrecognized_charge"] = raw
                with self.assertRaises(BankRPCError) as error:
                    await self.controller.execute(self.prepare_payload(), self.context)
                self.assertEqual(error.exception.code, "bank_invalid_response")
                self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])

    async def test_unhashable_or_extra_raw_fields_fail_with_fixed_protocol_error(self):
        for field, value in [("decision", []), ("reason", []), ("action", "live_dispute"),
                             ("pending_handle", "invalid"), ("snapshot", "../other"),
                             ("extra_private_field", "unreviewed")]:
            with self.subTest(field=field):
                self.rpc.calls.clear()
                raw = prepare_result(decision="handoff", reason="missing_evidence")
                raw[field] = value
                self.rpc.answers["prepare_unrecognized_charge"] = raw
                try:
                    result = await self.controller.execute(self.prepare_payload(), self.context)
                except BankRPCError as error:
                    self.assertEqual(error.code, "bank_invalid_response")
                else:
                    self.assertEqual(result["state"], "prepare_unverified")
                self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])
        raw = prepare_result()
        raw["existing_case"]["state"] = []
        self.rpc.answers["prepare_unrecognized_charge"] = raw
        with self.assertRaises(BankRPCError) as error:
            await self.controller.execute(self.prepare_payload(), self.context)
        self.assertEqual(error.exception.code, "bank_invalid_response")

    async def test_snapshot_or_owned_selected_facts_mismatch_never_writes_hof(self):
        for changes in [{"snapshot": "other-build"}, {"expected_transaction": action_selected(amount=999)},
                        {"expected_transaction": action_selected(process_date="2026-06-18")},
                        {"expected_transaction": action_selected(channel="Other")},
                        {"expected_transaction": action_selected(product="Other")},
                        {"expected_transaction": None}]:
            with self.subTest(fields=list(changes)):
                self.rpc.calls.clear()
                raw = prepare_result(decision="handoff", reason="missing_evidence")
                if "snapshot" in changes:
                    raw["snapshot"] = changes["snapshot"]
                    payload = self.prepare_payload()
                else:
                    payload = self.prepare_payload(**changes)
                self.rpc.answers["prepare_unrecognized_charge"] = raw
                result = await self.controller.execute(payload, self.context)
                self.assertEqual(result["state"], "prepare_unverified")
                self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])

    async def test_verified_policy_handoff_has_explicit_independent_packet_read(self):
        self.rpc.answers["prepare_unrecognized_charge"] = prepare_result(decision="handoff", reason="missing_evidence")
        result = await self.controller.execute(self.prepare_payload(), self.context)
        self.assertEqual(result["state"], "handoff_verified")
        self.assertEqual(result["handoff"]["unanswered_questions"], [])
        self.assertEqual(result["handoff"]["reason"], "missing_evidence")
        self.assertEqual(self.tools(), ["prepare_unrecognized_charge", "create_verified_handoff", "read_verified_handoff"])
        self.assertEqual(self.rpc.calls[1][1], {"reason": "missing_evidence", "pending_handle": HANDLE,
                                              "request_id": self.request_id, "unanswered_questions": []})
        self.assertEqual(self.rpc.calls[2][1], {"handoff_id": result["handoff"]["id"]})

    async def test_verified_existing_case_preserves_origin_and_reads_without_confirm(self):
        old = action_receipt(snapshot="original-build")
        self.rpc.answers["prepare_unrecognized_charge"] = prepare_result(decision="existing_case",
            existing_state="verified", receipt=old)
        self.rpc.answers["read_intake_receipt"] = receipt_result(old)
        result = await self.controller.execute(self.prepare_payload(), self.context)
        self.assertEqual(result["state"], "existing_case_verified")
        self.assertEqual(result["snapshot"], SNAPSHOT)
        self.assertEqual(result["receipt"], old)
        self.assertEqual(self.tools(), ["prepare_unrecognized_charge", "read_intake_receipt"])
        self.assertEqual(self.rpc.calls[1][1], {"pending_handle": HANDLE})

    async def test_existing_case_readback_mismatch_absence_or_loss_stays_unverified(self):
        old = action_receipt(snapshot="original-build")
        for read in [receipt_result(absent=True), receipt_result(action_receipt(snapshot="wrong-origin")),
                     receipt_result(action_receipt(receipt_id="CMP-SBX-another_", snapshot="original-build")),
                     BankRPCError("bank_unreachable", possibly_sent=True)]:
            with self.subTest(kind=type(read).__name__):
                self.rpc.calls.clear()
                self.rpc.answers["prepare_unrecognized_charge"] = prepare_result(decision="existing_case",
                    existing_state="verified", receipt=old)
                self.rpc.answers["read_intake_receipt"] = read
                result = await self.controller.execute(self.prepare_payload(), self.context)
                self.assertEqual(result["state"], "prepare_unverified")
                self.assertNotIn("receipt", result)
                self.assertEqual(self.tools(), ["prepare_unrecognized_charge", "read_intake_receipt"])

    async def test_confirmation_is_explicit_true_and_never_language_truthiness(self):
        for value in [False, None, 1, "true", "sí", "sim"]:
            with self.subTest(value=value):
                with self.assertRaises(BankRPCError) as error:
                    await self.controller.execute(self.confirm_payload(confirmed=value), self.context)
                self.assertEqual(error.exception.code, "confirmation_required")
                self.assertFalse(error.exception.possibly_sent)
        self.assertEqual(self.rpc.calls, [])

    async def test_successful_confirm_requires_independent_receipt_read(self):
        result = await self.controller.execute(self.confirm_payload(), self.context)
        self.assertEqual(result, {"state": "intake_verified", "receipt": action_receipt()})
        self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])
        self.assertEqual(self.rpc.calls[0][1], {"pending_handle": HANDLE, "confirmed": True})
        self.assertEqual(self.rpc.calls[1][1], {"pending_handle": HANDLE})
        self.assertEqual(self.rpc.calls[1][3], 20)

    async def test_confirmation_loss_recovers_receipt_without_hof_or_reconfirmation(self):
        self.rpc.answers["confirm_simulated_intake"] = BankRPCError("bank_unreachable", possibly_sent=True)
        result = await self.controller.execute(self.confirm_payload(), self.context)
        self.assertEqual(result["state"], "intake_verified")
        self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])
        self.rpc.calls.clear()
        self.rpc.answers["read_intake_receipt"] = receipt_result(absent=True)
        result = await self.controller.execute(self.confirm_payload(), self.context)
        self.assertEqual(result, {"state": "action_unverified"})
        self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])

    async def test_confirm_and_receipt_losses_stay_uncertain_without_extra_writes(self):
        self.rpc.answers["confirm_simulated_intake"] = BankRPCError("bank_timeout", possibly_sent=True)
        self.rpc.answers["read_intake_receipt"] = BankRPCError("bank_timeout", possibly_sent=True)
        result = await self.controller.execute(self.confirm_payload(), self.context)
        self.assertEqual(result, {"state": "action_unverified"})
        self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])

    async def test_busy_after_prepare_commit_is_not_workflow_pre_admission(self):
        expected = ["prepare_unrecognized_charge", "create_verified_handoff", "read_verified_handoff"]
        for failure_tool, calls in [("create_verified_handoff", expected[:2]),
                                    ("read_verified_handoff", expected)]:
            with self.subTest(failure_tool=failure_tool):
                self.rpc.calls.clear()
                self.rpc.answers["prepare_unrecognized_charge"] = prepare_result(decision="handoff", reason="missing_evidence")
                def busy(tool, args, context):
                    if tool == failure_tool:
                        raise BankRPCError("server_busy", possibly_sent=False)
                self.rpc.handler = busy
                try:
                    result = await self.controller.execute(self.prepare_payload(), self.context)
                except BankRPCError as error:
                    # Busy applies only to the failed subcall; the earlier
                    # durable prepare forbids rolling back the host intent.
                    self.assertEqual(error.code, "server_busy")
                    self.assertTrue(error.possibly_sent)
                else:
                    self.assertIn(result["state"], {"prepare_unverified", "handoff_unverified"})
                self.assertEqual(self.tools(), calls)

    async def test_busy_receipt_after_confirm_does_not_reconfirm_or_create_hof(self):
        self.rpc.answers["read_intake_receipt"] = BankRPCError("server_busy", possibly_sent=False)
        result = await self.controller.execute(self.confirm_payload(), self.context)
        self.assertEqual(result, {"state": "action_unverified"})
        self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])

    async def test_busy_first_dispatch_remains_definitive_pre_admission(self):
        self.rpc.answers["prepare_unrecognized_charge"] = BankRPCError("server_busy", possibly_sent=False)
        with self.assertRaises(BankRPCError) as error:
            await self.controller.execute(self.prepare_payload(), self.context)
        self.assertEqual(error.exception.code, "server_busy")
        self.assertFalse(error.exception.possibly_sent)
        self.assertEqual(self.tools(), ["prepare_unrecognized_charge"])

    async def test_confirm_policy_denial_only_offers_explicit_handoff(self):
        for code, reason in [("risk_data_unavailable", "missing_evidence"),
                             ("handoff_required", "high_risk"), ("snapshot_changed", "missing_evidence")]:
            with self.subTest(code=code):
                self.rpc.calls.clear()
                self.rpc.answers["confirm_simulated_intake"] = BankRPCError(code, possibly_sent=True)
                self.rpc.answers["read_intake_receipt"] = receipt_result(absent=True)
                result = await self.controller.execute(self.confirm_payload(), self.context)
                self.assertEqual(result, {"state": "handoff_unverified", "reason": reason})
                self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])

    async def test_currentness_may_change_but_saved_hof_packet_must_remain_identical(self):
        def changed_currentness(tool, args, context):
            if tool == "read_verified_handoff":
                packet = deepcopy(self.rpc.saved_handoff)
                packet["transaction_currentness"] = "different_snapshot"
                return handoff_result(packet)
        self.rpc.handler = changed_currentness
        result = await self.controller.execute(self.handoff_payload(), self.context)
        self.assertEqual(result["state"], "handoff_verified")
        self.assertEqual(result["handoff"]["transaction_currentness"], "different_snapshot")
        self.assertEqual(result["handoff"]["unanswered_questions"], self.handoff_payload()["unanswered_questions"])
        self.assertEqual(self.tools(), ["create_verified_handoff", "read_verified_handoff"])

    async def test_whole_hof_readback_drift_is_unverified(self):
        def change_question(packet):
            packet["packet"]["unanswered_questions"] = ["Different question"]
        def change_provenance(packet):
            packet["packet"]["transaction_provenance"]["as_of"] = "2026-09-29T15:00:01Z"
        def change_id(packet):
            packet["id"] = "HOF-another_"
        def change_created_at(packet):
            packet["created_at"] = "2026-09-29T15:00:01Z"
        def change_facts(packet):
            packet["facts"]["amount"] = "151.00"
            packet["packet"]["transaction"]["amount"] = "151.00"
        def change_reason(packet):
            packet["reason"] = packet["packet"]["reason"] = "emergency"
        for mutate in [change_question, change_provenance, change_id, change_created_at, change_facts, change_reason]:
            with self.subTest(mutation=mutate.__name__):
                self.rpc.calls.clear()
                def drift(tool, args, context):
                    if tool == "read_verified_handoff":
                        changed = deepcopy(self.rpc.saved_handoff)
                        mutate(changed)
                        return handoff_result(changed)
                self.rpc.handler = drift
                result = await self.controller.execute(self.handoff_payload(), self.context)
                self.assertEqual(result, {"state": "handoff_unverified", "reason": "customer_request"})
                self.assertEqual(self.tools(), ["create_verified_handoff", "read_verified_handoff"])

    async def test_flattened_hof_or_wrong_mode_flags_never_establish_saved_packet(self):
        for mutation in ["flattened", "synthetic", "operator_test", "human_responded"]:
            with self.subTest(mutation=mutation):
                self.rpc.calls.clear()
                def bad_created(tool, args, context):
                    if tool == "create_verified_handoff":
                        packet = action_handoff(questions=args["unanswered_questions"])
                        raw = handoff_result(packet)
                        if mutation == "flattened":
                            saved = raw["handoff"].pop("packet")
                            raw["handoff"].update(unanswered_questions=saved["unanswered_questions"],
                                                   transaction_provenance=saved["transaction_provenance"])
                        elif mutation == "human_responded":
                            raw["handoff"]["human_responded"] = True
                        else:
                            raw[mutation] = True
                        return raw
                self.rpc.handler = bad_created
                result = await self.controller.execute(self.handoff_payload(), self.context)
                self.assertEqual(result["state"], "handoff_unverified")
                self.assertEqual(self.tools(), ["create_verified_handoff"])

    async def test_general_hof_has_no_charge_facts_snapshot_or_provenance(self):
        result = await self.controller.execute(self.handoff_payload(general=True), self.context)
        self.assertEqual(result["state"], "handoff_verified")
        self.assertEqual(result["handoff"]["facts"], {})
        self.assertIsNone(result["handoff"]["snapshot"])
        self.assertIsNone(result["handoff"]["transaction_provenance"])
        self.assertEqual(result["handoff"]["transaction_currentness"], "not_applicable")
        self.rpc.calls.clear()
        def charged_general(tool, args, context):
            if tool == "create_verified_handoff":
                self.rpc.saved_handoff = action_handoff(questions=args["unanswered_questions"])
                return handoff_result(self.rpc.saved_handoff)
        self.rpc.handler = charged_general
        result = await self.controller.execute(self.handoff_payload(general=True), self.context)
        self.assertEqual(result["state"], "handoff_unverified")
        self.assertEqual(self.tools(), ["create_verified_handoff", "read_verified_handoff"])

    async def test_hof_questions_are_bounded_canonical_plain_caller_data(self):
        for questions in [[" Changed "], ["a\x00"], ["a\x1b"], ["a\n"], ["\ud800"], ["a" * 241], ["a"] * 9]:
            with self.subTest(kind=len(questions)), self.assertRaises(BankRPCError) as error:
                await self.controller.execute(self.handoff_payload(unanswered_questions=questions), self.context)
            self.assertEqual(error.exception.code, "invalid_arguments")
        self.assertEqual(self.rpc.calls, [])

    async def test_mode_flags_on_confirm_and_receipt_cannot_prove_terminal(self):
        for tool in ["confirm_simulated_intake", "read_intake_receipt"]:
            with self.subTest(tool=tool):
                self.rpc.calls.clear()
                self.rpc.answers["confirm_simulated_intake"] = receipt_result()
                self.rpc.answers["read_intake_receipt"] = receipt_result(absent=True)
                raw = receipt_result()
                raw["operator_test"] = True
                self.rpc.answers[tool] = raw
                result = await self.controller.execute(self.confirm_payload(), self.context)
                self.assertEqual(result["state"], "action_unverified")
                self.assertEqual(self.tools(), ["confirm_simulated_intake", "read_intake_receipt"])

    async def test_before_call_is_rechecked_at_each_followup_and_after_results(self):
        expected = ["prepare_unrecognized_charge", "create_verified_handoff", "read_verified_handoff"]
        for denied_at, observed in [(1, []), (2, expected[:1]), (3, expected[:1]),
                                    (4, expected[:2]), (5, expected[:2]), (6, expected)]:
            with self.subTest(denied_at=denied_at):
                self.rpc.calls.clear()
                self.rpc.answers["prepare_unrecognized_charge"] = prepare_result(decision="handoff", reason="missing_evidence")
                checks = 0
                def guard():
                    nonlocal checks
                    checks += 1
                    if checks == denied_at:
                        raise BankRPCError("authorization_denied", possibly_sent=False)
                controller = BankController(self.rpc, guard)
                with self.assertRaises(BankRPCError) as error:
                    await controller.execute(self.prepare_payload(), self.context)
                self.assertEqual(error.exception.code, "authorization_denied")
                self.assertEqual(self.tools(), observed)

    async def test_hof_or_confirm_admission_failure_does_not_dispatch_readback(self):
        for payload in [self.handoff_payload(), self.confirm_payload()]:
            with self.subTest(operation=payload["operation"]):
                self.rpc.calls.clear()
                def guard():
                    raise BankRPCError("authorization_denied")
                with self.assertRaises(BankRPCError):
                    await BankController(self.rpc, guard).execute(payload, self.context)
                self.assertEqual(self.rpc.calls, [])
