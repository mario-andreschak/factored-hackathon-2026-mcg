"""Durable direct-host banking boundaries, separate from generic language."""
from __future__ import annotations

import asyncio
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import uuid

import httpx

from frontend.server.action import render_action
from frontend.server.bank_rpc import BankContext, BankRPCError
from frontend.server.chat import ChatError, ChatService
from frontend.server.language import GenericLanguageClient, LanguageConfig, LanguageResult, MinimizedFacts, render_guidance
from frontend.server.review import review_reference
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected
from frontend.tests.direct_host_fixtures import attach_direct_fakes, make_direct_config

_REQUEST_ID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"
_REF_A, _REF_B = "txn_" + "a" * 24, "txn_" + "b" * 24
_FLAGS = {"synthetic": False, "operator_test": False}


def test_review_reference_accepts_only_saved_random_action_ids():
    action_id = "123e4567-e89b-42d3-a456-426614174000"
    expected = "rev_" + hashlib.sha256(("savia-demo-review-v1:" + action_id).encode("ascii")).hexdigest()[:24]
    assert review_reference(action_id) == expected
    assert review_reference(action_id) == expected
    assert review_reference("a" * 32) == "rev_" + hashlib.sha256(
        ("savia-demo-review-v1:" + "a" * 32).encode("ascii")).hexdigest()[:24]
    for invalid in [None, "", "subject-a", _REF_A, action_id.upper(),
                    "123e4567-e89b-12d3-a456-426614174000", "A" * 32]:
        assert review_reference(invalid) is None


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = make_direct_config(self.root / "generated-config", action_enabled=True)
        self.state_root = self.root / "state"
        self.service = ChatService(self.config, self.state_root)
        self.bank, self.language = attach_direct_fakes(self.service)
        self.expiry = int(time.time()) + 3600
        self.session_a, self.session_b = str(uuid.uuid4()), str(uuid.uuid4())

    def tearDown(self):
        self.directory.cleanup()

    def restart(self, *, config=None):
        service = ChatService(config or self.config, self.state_root)
        attach_direct_fakes(service, bank=self.bank, language=self.language)
        return service

    def fresh(self, name):
        service = ChatService(self.config, self.root / name)
        bank, language = attach_direct_fakes(service)
        return service, bank, language

    async def prepare(self, service=None, *, target=_REF_A, transaction="private-a", snapshot="test",
                      selected=None, customer="customer-a", session=None, request_id=None):
        operation = {"operation": "prepare", "transactionId": transaction, "snapshot": snapshot}
        if request_id is not None:
            operation["requestId"] = request_id
        return await (service or self.service).action(customer, session or self.session_a, self.expiry,
            operation, target_reference=target, expected_transaction=selected or action_selected())

    async def confirm(self, prepared, service=None, *, target=_REF_A, selected=None,
                      snapshot="test", confirmed=True):
        return await (service or self.service).action("customer-a", self.session_a, self.expiry,
            {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": confirmed},
            target_reference=target, expected_snapshot=snapshot,
            expected_transaction=selected or action_selected())

    def action_row(self, service=None):
        with (service or self.service)._connection() as db:
            row = db.execute("SELECT * FROM action_status WHERE session_id=?", (self.session_a,)).fetchone()
            return dict(row) if row else None

    def session_row(self, service=None):
        with (service or self.service)._connection() as db:
            return dict(db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (self.session_a,)).fetchone())

    def update_action(self, service=None, **fields):
        # Field names are constant test source, never browser input.
        with (service or self.service)._connection() as db:
            db.execute("UPDATE action_status SET " + ",".join(name + "=?" for name in fields)
                       + " WHERE session_id=?", (*fields.values(), self.session_a))

    def uncertain(self, prepared, service=None):
        service = service or self.service
        service._remember_action(self.session_a, service._owner_for_subject("subject-a"), self.expiry,
            {"state": "action_unverified", "pending_handle": prepared["pending_handle"]})

    def policy_prepare(self, arguments, *, reason="missing_evidence"):
        raw = self.bank.answer("prepare_unrecognized_charge", arguments)
        raw.update(decision="handoff", reason=reason)
        raw["risk"].update(unrecognized_count_24h=3 if reason == "high_risk" else None,
                           risk_data_complete=reason == "high_risk")
        return raw

    async def test_first_action_is_direct_and_bank_context_is_server_bound(self):
        browser_id = str(uuid.uuid4())
        result = await self.prepare(request_id=browser_id, snapshot="synthetic-build")
        self.assertEqual(result["state"], "pending_confirmation")
        self.assertEqual(self.language.calls, [])
        tool, arguments, context = self.bank.calls[0]
        self.assertEqual(tool, "prepare_unrecognized_charge")
        self.assertEqual(set(arguments), {"transaction_id", "snapshot", "request_id"})
        self.assertEqual((arguments["transaction_id"], arguments["snapshot"]), ("private-a", "synthetic-build"))
        self.assertEqual(arguments["request_id"], result["request_id"])
        self.assertNotEqual(arguments["request_id"], browser_id)
        self.assertIs(type(context), BankContext)
        self.assertEqual(context.subject, "subject-a")
        expected_session = hashlib.sha256(json.dumps(["direct-host-v1", self.config["namespace"],
            self.config["bank"]["issuer"], self.session_a], separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(context.session_id, expected_session)
        self.assertEqual(context.conversation_id, self.session_row()["bank_context_id"])
        self.assertIsNone(self.session_row()["conversation_id"])
        self.assertEqual((context.host_revision, context.session_expires), (self.config["host_revision"], self.expiry))
        self.assertRegex(context.operation_id, _REQUEST_ID_PATTERN)
        self.assertEqual(context.ledger_generation, self.config["ledger_generation"])
        self.assertNotIn(_REF_A, json.dumps(arguments))
        with self.assertRaises(ChatError) as foreign:
            await self.prepare(customer="customer-b")
        self.assertEqual(foreign.exception.code, "session_mismatch")
        self.assertEqual(len(self.bank.calls), 1)

    async def test_action_status_recovers_receipt_from_persisted_attempt(self):
        prepared = await self.prepare(snapshot="synthetic-build")
        self.assertEqual((await self.service.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")
        self.uncertain(prepared)
        self.bank.receipt = action_receipt(snapshot="synthetic-build")
        reloaded = self.restart()
        recovered = await reloaded.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual((recovered["state"], recovered["receipt"]["id"]), ("intake_verified", "CMP-SBX-abcdefgh"))
        self.assertEqual([tool for tool, _, _ in self.bank.calls], ["prepare_unrecognized_charge", "read_intake_receipt"])
        self.assertEqual(self.bank.calls[-1][1], {"pending_handle": prepared["pending_handle"]})
        before = len(self.bank.calls)
        self.assertEqual(await reloaded.action_status("customer-a", self.session_a, self.expiry), recovered)
        self.assertEqual(len(self.bank.calls), before)

    async def test_lost_prepare_recovers_exact_reserved_identity_after_restart(self):
        async def lost(tool, arguments, context):
            self.bank.answer(tool, arguments)  # Fake commit before controlled delivery failure.
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        uncertain = await self.prepare(snapshot="synthetic-build")
        self.assertEqual(uncertain["state"], "prepare_unverified")
        original = self.bank.calls[0]
        saved = self.action_row()
        self.assertEqual(saved["prepare_transaction_id"], "private-a")
        self.assertEqual(json.loads(saved["prepare_expected_json"]), action_selected())
        self.bank.call_handler = None
        restarted = self.restart()
        with self.assertRaises(ChatError):
            await restarted.action_status("customer-b", self.session_a, self.expiry)
        with self.assertRaises(ChatError) as blocked:
            await self.prepare(restarted, target=_REF_B, transaction="private-b")
        self.assertEqual(blocked.exception.code, "action_in_progress")
        recovered = await restarted.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["state"], "pending_confirmation")
        self.assertEqual(recovered["request_id"], uncertain["request_id"])
        self.assertEqual(recovered["target_reference"], _REF_A)
        replay = self.bank.calls[-1]
        self.assertEqual(replay[:2], original[:2])
        self.assertEqual(replay[2].conversation_id, original[2].conversation_id)
        self.assertEqual(replay[2].session_id, original[2].session_id)
        self.assertNotEqual(replay[2].operation_id, original[2].operation_id)
        cleared = self.action_row(restarted)
        for field in ("prepare_transaction_id", "prepare_snapshot", "prepare_conversation_id", "prepare_expected_json"):
            self.assertIsNone(cleared[field])
        self.assertEqual(self.language.calls, [])

    async def test_crashed_prepare_waits_for_stale_and_unadmitted_busy_does_not_exhaust(self):
        async def crash(tool, arguments, context):
            raise asyncio.CancelledError()
        self.bank.call_handler = crash
        with self.assertRaises(asyncio.CancelledError):
            await self.prepare()
        restarted = self.restart()
        self.assertEqual((await restarted.action_status("customer-a", self.session_a, self.expiry))["state"], "preparing")
        self.assertEqual(len(self.bank.calls), 1)
        self.update_action(restarted, updated_at=int(time.time()) - 60)
        async def busy(tool, arguments, context):
            raise BankRPCError("server_busy", possibly_sent=False)
        self.bank.call_handler = busy
        self.assertEqual((await restarted.action_status("customer-a", self.session_a, self.expiry))["state"], "preparing")
        self.assertEqual(self.action_row(restarted)["prepare_recovery_attempts"], 0)
        self.update_action(restarted, prepare_recovery_after=0)
        self.bank.call_handler = None
        recovered = await restarted.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["state"], "pending_confirmation")
        self.assertEqual(self.bank.calls[0][1], self.bank.calls[-1][1])

    async def test_lost_policy_handoff_recovery_cannot_overwrite_later_target(self):
        started, release = asyncio.Event(), asyncio.Event()
        count = 0
        async def handler(tool, arguments, context):
            nonlocal count
            if tool == "prepare_unrecognized_charge" and arguments["transaction_id"] == "private-a":
                count += 1
                if count == 1:
                    self.policy_prepare(arguments)
                    raise BankRPCError("bank_timeout", possibly_sent=True)
                if count == 2:
                    started.set()
                    await release.wait()
                self.bank.pending_handle = "a" * 43
                return self.policy_prepare(arguments)
            if tool == "prepare_unrecognized_charge":
                self.bank.pending_handle = "b" * 43
            return self.bank.answer(tool, arguments)
        self.bank.call_handler = handler
        await self.prepare()
        late = asyncio.create_task(self.service.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(started.wait(), 5)
        self.update_action(prepare_recovery_after=0)
        first = await self.service.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(first["state"], "handoff_verified")
        next_action = await self.prepare(target=_REF_B, transaction="private-b")
        release.set()
        self.assertEqual(await late, next_action)
        self.assertEqual((await self.service.action_status("customer-a", self.session_a, self.expiry))["target_reference"], _REF_B)
        old_prepares = [args for tool, args, _ in self.bank.calls
                        if tool == "prepare_unrecognized_charge" and args["transaction_id"] == "private-a"]
        self.assertTrue(all(args == old_prepares[0] for args in old_prepares))

    async def test_expired_prepare_recovery_remains_locked_and_has_public_review_reference(self):
        async def lost(tool, arguments, context):
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        await self.prepare()
        row = self.action_row()
        self.update_action(prepare_recovery_deadline=int(time.time()) - 1)
        status = await self.service.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual((status["state"], status["recovery_exhausted"]), ("prepare_unverified", True))
        self.assertEqual(status["review_reference"], review_reference(row["action_id"]))
        for private in ("private-a", "subject-a", "customer-a", self.session_a,
                        row["action_id"], row["prepare_conversation_id"]):
            self.assertNotIn(private, json.dumps(status))
        restarted = self.restart()
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), status)
        with self.assertRaises(ChatError):
            await restarted.action_status("customer-b", self.session_a, self.expiry)
        with self.assertRaises(ChatError) as blocked:
            await restarted.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(blocked.exception.code, "action_in_progress")
        self.assertEqual(len(self.bank.calls), 1)

    async def test_unresolved_prepare_blocks_another_target_before_bank_call(self):
        prepared = await self.prepare()
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain):
                if uncertain:
                    self.uncertain(prepared)
                with self.assertRaises(ChatError) as blocked:
                    await self.prepare(target=_REF_B, transaction="private-b")
                self.assertEqual(blocked.exception.code, "action_in_progress")
                self.assertEqual(self.action_row()["target_reference"], _REF_A)
        self.assertEqual(len(self.bank.calls), 1)
        self.assertNotIn(_REF_A, json.dumps(self.bank.calls[0][1]))

    async def test_late_receipt_cannot_replace_new_prepare(self):
        prepared = await self.prepare()
        self.uncertain(prepared)
        self.bank.receipt = action_receipt()
        started, release = asyncio.Event(), asyncio.Event()
        reads = 0
        async def handler(tool, arguments, context):
            nonlocal reads
            if tool == "read_intake_receipt":
                reads += 1
                reply = self.bank.answer(tool, arguments)
                if reads == 1:
                    started.set()
                    await release.wait()
                return reply
            self.bank.pending_handle = "b" * 43
            return self.bank.answer(tool, arguments)
        self.bank.call_handler = handler
        late = asyncio.create_task(self.service.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(started.wait(), 5)
        recovered = await self.service.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["state"], "intake_verified")
        next_action = await self.prepare(target=_REF_B, transaction="private-b")
        release.set()
        self.assertEqual(await late, next_action)
        self.assertEqual(self.action_row()["target_reference"], _REF_B)

    async def test_inflight_status_cannot_return_saved_action_after_local_revocation(self):
        prepared = await self.prepare()
        self.uncertain(prepared)
        self.bank.receipt = action_receipt()
        started, release = asyncio.Event(), asyncio.Event()
        async def handler(tool, arguments, context):
            started.set()
            await release.wait()
            return self.bank.answer(tool, arguments)
        self.bank.call_handler = handler
        status = asyncio.create_task(self.service.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(started.wait(), 5)
        self.service.queue_revoke("customer-a", self.session_a, self.expiry)
        release.set()
        with self.assertRaises(ChatError) as revoked:
            await status
        self.assertEqual(revoked.exception.status_code, 401)
        self.assertEqual(json.loads(self.action_row()["result_json"])["state"], "action_unverified")

    async def test_general_handoff_and_guarded_prepare_have_durable_status(self):
        result = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(result["state"], "handoff_verified")
        self.assertNotIn("target_reference", result)
        self.assertEqual(result["handoff"]["facts"], {})
        self.assertEqual([tool for tool, _, _ in self.bank.calls], ["create_verified_handoff", "read_verified_handoff"])
        self.assertEqual(await self.restart().action_status("customer-a", self.session_a, self.expiry), result)
        for operation in [
                {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
                {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": False}]:
            with self.assertRaises(ChatError):
                await self.service.action("customer-a", self.session_a, self.expiry, operation)
        self.assertEqual(len(self.bank.calls), 2)

    async def test_definitive_pre_admission_busy_restores_previous_action_without_retry(self):
        async def busy(tool, arguments, context):
            raise BankRPCError("server_busy", possibly_sent=False)
        self.bank.call_handler = busy
        with self.assertRaises(ChatError) as rejected:
            await self.prepare()
        self.assertEqual(rejected.exception.code, "chat_busy")
        self.assertEqual(await self.service.action_status("customer-a", self.session_a, self.expiry), {"state": "none"})
        self.assertEqual(len(self.bank.calls), 1)
        self.bank.call_handler = None
        prepared = await self.prepare()
        original_action = self.action_row()["action_id"]
        self.bank.call_handler = busy
        with self.assertRaises(ChatError):
            await self.confirm(prepared)
        self.assertEqual((await self.service.action_status("customer-a", self.session_a, self.expiry)), prepared)
        with self.assertRaises(ChatError):
            await self.service.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request"},
                target_reference=_REF_A)
        self.assertEqual(await self.service.action_status("customer-a", self.session_a, self.expiry), prepared)
        self.assertEqual(self.action_row()["action_id"], original_action)
        self.assertEqual(len(self.bank.calls), 4)
        self.bank.call_handler = None
        handed = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request"},
            target_reference=_REF_A)
        self.assertEqual(handed["state"], "handoff_verified")

    async def test_followup_busy_after_admitted_prepare_cannot_roll_back_unknown_write(self):
        async def handler(tool, arguments, context):
            if tool == "prepare_unrecognized_charge":
                return self.policy_prepare(arguments)
            raise BankRPCError("server_busy", possibly_sent=False)
        self.bank.call_handler = handler
        result = await self.prepare()
        self.assertEqual(result["state"], "handoff_unverified")
        self.assertEqual(result["reason"], "missing_evidence")
        self.assertIsNotNone(self.action_row())
        with self.assertRaises(ChatError) as blocked:
            await self.prepare(target=_REF_B, transaction="private-b")
        self.assertEqual(blocked.exception.code, "action_in_progress")
        self.assertEqual([tool for tool, _, _ in self.bank.calls], ["prepare_unrecognized_charge", "create_verified_handoff"])

    async def test_lost_general_handoff_reuses_saved_id_and_reason_after_restart(self):
        async def lost(tool, arguments, context):
            self.bank.answer(tool, arguments)
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        uncertain = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(uncertain["state"], "handoff_unverified")
        self.assertRegex(uncertain["request_id"], _REQUEST_ID_PATTERN)
        original_args = self.bank.calls[0][1]
        restarted = self.restart()
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), uncertain)
        for operation in [
                {"operation": "handoff", "reason": "customer_request", "requestId": str(uuid.uuid4())},
                {"operation": "handoff", "reason": "emergency", "requestId": uncertain["request_id"]}]:
            with self.assertRaises(ChatError) as changed:
                await restarted.action("customer-a", self.session_a, self.expiry, operation)
            self.assertEqual(changed.exception.code, "action_in_progress")
        self.assertEqual(len(self.bank.calls), 1)
        self.bank.call_handler = None
        verified = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": uncertain["reason"], "requestId": uncertain["request_id"]})
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(self.bank.calls[1][1], original_args)
        self.assertEqual([tool for tool, _, _ in self.bank.calls],
                         ["create_verified_handoff", "create_verified_handoff", "read_verified_handoff"])

    async def test_policy_handoff_unverified_preserves_exact_recovery_tuple(self):
        for reason in ("high_risk", "missing_evidence"):
            with self.subTest(reason=reason):
                service, bank, _ = self.fresh(reason)
                async def handler(tool, arguments, context):
                    raw = bank.answer(tool, arguments)
                    if tool == "prepare_unrecognized_charge":
                        raw.update(decision="handoff", reason=reason)
                        raw["risk"].update(unrecognized_count_24h=3 if reason == "high_risk" else None,
                                           risk_data_complete=reason == "high_risk")
                        return raw
                    raise BankRPCError("bank_timeout", possibly_sent=True)
                bank.call_handler = handler
                uncertain = await self.prepare(service)
                self.assertEqual((uncertain["state"], uncertain["reason"]), ("handoff_unverified", reason))
                self.assertEqual((uncertain["target_reference"], uncertain["pending_handle"]), (_REF_A, "a" * 43))
                self.assertRegex(uncertain["request_id"], _REQUEST_ID_PATTERN)
                restarted = ChatService(self.config, self.root / reason)
                attach_direct_fakes(restarted, bank=bank)
                self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), uncertain)
                for changed in [
                        {"reason": "customer_request", "requestId": uncertain["request_id"]},
                        {"reason": reason, "requestId": str(uuid.uuid4())}]:
                    with self.assertRaises(ChatError) as mismatch:
                        await restarted.action("customer-a", self.session_a, self.expiry,
                            {"operation": "handoff", "pendingHandle": "a" * 43, **changed}, target_reference=_REF_A)
                    self.assertEqual(mismatch.exception.code, "action_mismatch")
                before = len(bank.calls)
                bank.call_handler = None
                verified = await restarted.action("customer-a", self.session_a, self.expiry,
                    {"operation": "handoff", "pendingHandle": "a" * 43,
                     "reason": reason, "requestId": uncertain["request_id"]}, target_reference=_REF_A)
                self.assertEqual(verified["state"], "handoff_verified")
                self.assertEqual(len(bank.calls), before + 2)
                self.assertEqual(bank.calls[-2][1], bank.calls[1][1])

    async def test_confirm_policy_denial_requires_explicit_handoff_and_preserves_handle(self):
        prepared = await self.prepare()
        async def policy(tool, arguments, context):
            if tool == "confirm_simulated_intake":
                raise BankRPCError("handoff_required", possibly_sent=True)
            return self.bank.answer(tool, arguments)
        self.bank.call_handler = policy
        uncertain = await self.confirm(prepared)
        self.assertEqual((uncertain["state"], uncertain["reason"]), ("handoff_unverified", "high_risk"))
        self.assertNotIn("request_id", uncertain)
        self.assertEqual([tool for tool, _, _ in self.bank.calls],
            ["prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt"])
        verified = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "high_risk"},
            target_reference=_REF_A)
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(self.bank.calls[-2][1],
            {"pending_handle": prepared["pending_handle"], "reason": "high_risk", "unanswered_questions": []})
        self.assertEqual(sum(tool == "confirm_simulated_intake" for tool, _, _ in self.bank.calls), 1)

    async def test_lost_confirm_does_not_guess_a_second_handoff_reason(self):
        prepared = await self.prepare()
        async def lost(tool, arguments, context):
            if tool == "confirm_simulated_intake":
                raise BankRPCError("bank_timeout", possibly_sent=True)
            self.assertEqual(tool, "read_intake_receipt")
            return self.bank.answer(tool, arguments)
        self.bank.call_handler = lost
        uncertain = await self.confirm(prepared)
        self.assertEqual(uncertain["state"], "action_unverified")
        self.assertNotIn("handoff", uncertain)
        with self.assertRaises(ChatError) as denied:
            await self.service.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request", "pendingHandle": prepared["pending_handle"]},
                target_reference=_REF_A)
        self.assertEqual(denied.exception.code, "action_in_progress")
        self.assertEqual([tool for tool, _, _ in self.bank.calls],
            ["prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt"])

    async def test_lost_confirm_recovers_only_receipt_without_repeating_consent(self):
        prepared = await self.prepare()
        async def lost(tool, arguments, context):
            answer = self.bank.answer(tool, arguments)
            if tool == "confirm_simulated_intake":
                raise BankRPCError("bank_timeout", possibly_sent=True)
            return answer
        self.bank.call_handler = lost
        verified = await self.confirm(prepared)
        self.assertEqual(verified["state"], "intake_verified")
        self.assertEqual(self.bank.calls[1][1], {"pending_handle": prepared["pending_handle"], "confirmed": True})
        self.assertEqual([tool for tool, _, _ in self.bank.calls],
            ["prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt"])
        self.assertEqual(await self.confirm(prepared), verified)
        self.assertEqual(len(self.bank.calls), 3)

    async def test_existing_case_origin_survives_restart_and_only_explicit_handoff_writes(self):
        self.bank.receipt = action_receipt(snapshot="original-old")
        async def existing(tool, arguments, context):
            raw = self.bank.answer(tool, arguments)
            if tool == "prepare_unrecognized_charge":
                raw["decision"] = "existing_case"
                raw["existing_case"].update(state="verified", receipt=deepcopy(self.bank.receipt))
            return raw
        self.bank.call_handler = existing
        result = await self.prepare()
        self.assertEqual(result["state"], "existing_case_verified")
        self.assertEqual((result["snapshot"], result["receipt"]["snapshot"]), ("test", "original-old"))
        with self.assertRaises(ChatError) as blocked:
            await self.confirm(result)
        self.assertEqual(blocked.exception.code, "action_in_progress")
        restarted = self.restart()
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), result)
        questions = ["¿Qué opciones de revisión tengo?"]
        handed = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": result["pending_handle"], "reason": "customer_request",
             "unansweredQuestions": questions}, target_reference=_REF_A)
        self.assertEqual(handed["state"], "handoff_verified")
        self.assertEqual(handed["handoff"]["unanswered_questions"], questions)
        self.assertEqual(self.bank.calls[-2][1]["request_id"], result["request_id"])
        self.assertEqual([tool for tool, _, _ in self.bank.calls],
            ["prepare_unrecognized_charge", "read_intake_receipt", "create_verified_handoff", "read_verified_handoff"])
        self.assertEqual(await self.restart().action_status("customer-a", self.session_a, self.expiry), handed)

    async def test_pending_consent_rejects_changed_owned_snapshot_or_charge_before_bank_call(self):
        prepared = await self.prepare()
        for snapshot, selected, target in [
                ("different", action_selected(), _REF_A),
                ("test", action_selected(amount=999), _REF_A),
                ("test", action_selected(), _REF_B)]:
            with self.subTest(snapshot=snapshot, selected=selected, target=target):
                with self.assertRaises(ChatError) as mismatch:
                    await self.confirm(prepared, snapshot=snapshot, selected=selected, target=target)
                self.assertEqual(mismatch.exception.code, "action_mismatch")
        for value in (False, None, 1, "true"):
            with self.subTest(confirmed=value):
                with self.assertRaises(ChatError) as consent:
                    await self.confirm(prepared, confirmed=value)
                self.assertEqual(consent.exception.code, "confirmation_required")
        self.assertEqual(len(self.bank.calls), 1)
        self.assertEqual(await self.service.action_status("customer-a", self.session_a, self.expiry), prepared)

    async def test_prepare_rejects_owned_process_date_channel_and_product_drift(self):
        for field, changed in [("process_date", "2026-06-18"), ("channel", "Other"), ("product", "Different")]:
            with self.subTest(field=field):
                service, bank, _ = self.fresh("prepare-" + field)
                expected = action_selected(**{field: changed})
                result = await self.prepare(service, selected=expected)
                self.assertEqual(result["state"], "prepare_unverified")
                self.assertEqual([tool for tool, _, _ in bank.calls], ["prepare_unrecognized_charge"])
                self.assertEqual(self.action_row(service)["target_reference"], _REF_A)
                with self.assertRaises(ChatError):
                    await self.prepare(service, target=_REF_B, transaction="private-b")
                self.assertEqual(len(bank.calls), 1)

    async def test_confirm_rejects_owned_process_date_channel_and_product_drift_before_write(self):
        prepared = await self.prepare()
        original = self.action_row()
        for field, changed in [("process_date", "2026-06-18"), ("channel", "Other"), ("product", "Different")]:
            with self.subTest(field=field):
                with self.assertRaises(ChatError) as mismatch:
                    await self.confirm(prepared, selected=action_selected(**{field: changed}))
                self.assertEqual(mismatch.exception.code, "action_mismatch")
                self.assertEqual(self.action_row(), original)
        self.assertEqual([tool for tool, _, _ in self.bank.calls], ["prepare_unrecognized_charge"])

    async def test_valid_receipt_for_another_selected_charge_cannot_resolve_prepare(self):
        async def wrong(tool, arguments, context):
            raw = self.bank.answer(tool, arguments)
            if tool == "prepare_unrecognized_charge":
                # Internally valid raw packet, but for another owned display row.
                raw["transaction"] = action_facts(action_selected(amount=999))
                receipt = action_receipt(selected=action_selected(amount=999))
                raw["decision"] = "existing_case"
                raw["existing_case"].update(state="verified", receipt=receipt)
                self.bank.receipt = receipt
            return raw
        self.bank.call_handler = wrong
        result = await self.prepare()
        self.assertEqual(result["state"], "prepare_unverified")
        self.assertNotIn("receipt", result)
        self.assertEqual([tool for tool, _, _ in self.bank.calls], ["prepare_unrecognized_charge"])

    async def test_wrong_receipt_or_handoff_readback_remains_locked_under_original_target(self):
        for kind in ("receipt", "handoff"):
            with self.subTest(kind=kind):
                service, bank, _ = self.fresh("wrong-" + kind)
                prepared = await self.prepare(service)
                async def wrong(tool, arguments, context):
                    if tool in {"confirm_simulated_intake", "read_intake_receipt"}:
                        return {**_FLAGS, "state": "created", "receipt": action_receipt(snapshot="different")}
                    if tool in {"create_verified_handoff", "read_verified_handoff"}:
                        return {**_FLAGS, "state": "created", "handoff": action_handoff(snapshot="different")}
                    self.fail("Unexpected write or re-prepare")
                bank.call_handler = wrong
                if kind == "receipt":
                    result = await self.confirm(prepared, service)
                    self.assertEqual(result["state"], "action_unverified")
                    self.assertNotIn("receipt", result)
                else:
                    result = await service.action("customer-a", self.session_a, self.expiry,
                        {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request"},
                        target_reference=_REF_A)
                    self.assertEqual(result["state"], "handoff_unverified")
                    self.assertNotIn("handoff", result)
                self.assertEqual(result["target_reference"], _REF_A)
                with self.assertRaises(ChatError) as blocked:
                    await self.prepare(service, target=_REF_B, transaction="private-b")
                self.assertEqual(blocked.exception.code, "action_in_progress")
                self.assertEqual(len(bank.calls), 3)

    async def test_lost_handoff_questions_are_frozen_across_restart_and_changed_retry_rejected(self):
        prepared = await self.prepare()
        questions = ["¿Qué documentos necesito?", "Qual o próximo passo?"]
        async def lost(tool, arguments, context):
            self.bank.answer(tool, arguments)
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        uncertain = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request",
             "unansweredQuestions": ["  " + question + "  " for question in questions]}, target_reference=_REF_A)
        self.assertEqual(uncertain["unanswered_questions"], questions)
        original_args = self.bank.calls[1][1]
        self.assertEqual(original_args["unanswered_questions"], questions)
        self.assertNotIn("unansweredQuestions", original_args)
        restarted = self.restart()
        for change in [{"unansweredQuestions": ["Otra pregunta"]}, {"requestId": str(uuid.uuid4())}, {"reason": "emergency"}]:
            with self.subTest(change=change):
                with self.assertRaises(ChatError) as mismatch:
                    await restarted.action("customer-a", self.session_a, self.expiry,
                        {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request", **change},
                        target_reference=_REF_A)
                self.assertEqual(mismatch.exception.code, "action_mismatch")
        self.assertEqual(len(self.bank.calls), 2)
        self.bank.call_handler = None
        verified = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "customer_request"},
            target_reference=_REF_A)
        self.assertEqual(verified["handoff"]["unanswered_questions"], questions)
        self.assertEqual(self.bank.calls[-2][1], original_args)

    async def test_verified_receipt_survives_uncertain_followup_only_for_same_owned_charge(self):
        prepared = await self.prepare()
        verified = await self.confirm(prepared)
        original_receipt = deepcopy(verified["receipt"])
        async def lost(tool, arguments, context):
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        uncertain = await self.prepare()
        self.assertEqual(uncertain["state"], "prepare_unverified")
        self.assertEqual(uncertain["prior_receipt"], {"target_reference": _REF_A, "receipt": original_receipt})
        self.update_action(prepare_recovery_deadline=int(time.time()) - 1)
        restarted = self.restart()
        status = await restarted.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(status["prior_receipt"]["receipt"], original_receipt)
        for language in ("es", "pt"):
            copy = render_action(status, language)["message"]
            self.assertIn("preparación" if language == "es" else "preparação", copy)
            self.assertIn("verificada" if language == "es" else "verificada", copy)
        with self.assertRaises(ChatError):
            await self.prepare(restarted, target=_REF_B, transaction="private-b")
        self.assertEqual(sum(tool == "confirm_simulated_intake" for tool, _, _ in self.bank.calls), 1)
        with self.assertRaises(ChatError):
            await restarted.action_status("customer-b", self.session_a, self.expiry)
        malformed = json.loads(self.action_row()["result_json"])
        malformed["target_reference"] = _REF_B
        malformed["prior_receipt"]["target_reference"] = _REF_B
        self.update_action(result_json=json.dumps(malformed))
        self.assertNotIn("prior_receipt", await restarted.action_status("customer-a", self.session_a, self.expiry))
        service, bank, _ = self.fresh("different-followup")
        other = await self.prepare(service)
        await self.confirm(other, service)
        bank.call_handler = lost
        different = await self.prepare(service, target=_REF_B, transaction="private-b")
        self.assertNotIn("prior_receipt", different)

    async def test_new_general_handoff_retains_prior_proof_without_unlocking_uncertain_request(self):
        old = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": ["Qual o próximo passo?"]})
        async def lost(tool, arguments, context):
            raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.call_handler = lost
        current = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": ["¿Qué documento falta?"]})
        self.assertEqual(current["state"], "handoff_unverified")
        self.assertNotEqual(current["request_id"], old["request_id"])
        self.assertEqual(current["prior_handoff"], {"target_reference": None, "handoff": old["handoff"]})
        restarted = self.restart()
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), current)
        before = len(self.bank.calls)
        with self.assertRaises(ChatError):
            await self.prepare(restarted)
        with self.assertRaises(ChatError):
            await restarted.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request", "requestId": old["request_id"]})
        self.assertEqual(len(self.bank.calls), before)
        self.bank.call_handler = None
        resolved = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": current["request_id"]})
        self.assertEqual(resolved["handoff"]["unanswered_questions"], ["¿Qué documento falta?"])
        self.assertEqual(self.bank.calls[-2][1]["request_id"], current["request_id"])
        self.assertEqual(resolved["prior_handoff"], current["prior_handoff"])

    async def test_general_handoff_rejects_charged_packet_and_only_general_readback_unlocks(self):
        async def charged(tool, arguments, context):
            return {**_FLAGS, "state": "created", "handoff": action_handoff()}
        self.bank.call_handler = charged
        uncertain = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(uncertain["state"], "handoff_unverified")
        self.assertNotIn("handoff", uncertain)
        self.assertEqual(await self.restart().action_status("customer-a", self.session_a, self.expiry), uncertain)
        with self.assertRaises(ChatError):
            await self.prepare()
        self.bank.call_handler = None
        verified = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": uncertain["request_id"]})
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(verified["handoff"]["facts"], {})
        self.assertIsNone(verified["handoff"]["snapshot"])
        self.assertIsNone(verified["handoff"]["transaction_provenance"])
        self.assertEqual(verified["handoff"]["transaction_currentness"], "not_applicable")

    async def test_verified_general_handoff_replay_preserves_packet_and_row_after_restart(self):
        questions = ["Qual o próximo passo?"]
        verified = await self.service.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": questions})
        restarted = self.restart()
        original = self.action_row()
        before = len(self.bank.calls)
        for extra in [{}, {"unansweredQuestions": questions}, {"unansweredQuestions": ["  " + questions[0] + "  "]}]:
            replay = await restarted.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request", "requestId": verified["request_id"], **extra})
            self.assertEqual(replay, verified)
            self.assertEqual(self.action_row(restarted), original)
        for change in [{"unansweredQuestions": []}, {"unansweredQuestions": ["Otra pregunta"]}, {"reason": "emergency"}]:
            with self.assertRaises(ChatError) as mismatch:
                await restarted.action("customer-a", self.session_a, self.expiry,
                    {"operation": "handoff", "reason": "customer_request", "requestId": verified["request_id"], **change})
            self.assertEqual(mismatch.exception.code, "action_mismatch")
            self.assertEqual(self.action_row(restarted), original)
        self.assertEqual(len(self.bank.calls), before)

    def test_es_pt_fallback_requires_verified_persisted_ids(self):
        handoff = {"state": "handoff_verified", "handoff": action_handoff("HOF-" + "a" * 8)}
        for language, label in [("es", "Folio"), ("pt", "Protocolo")]:
            named = render_action(handoff, language)
            self.assertIn(label, named["message"])
            self.assertIn(handoff["handoff"]["id"], named["message"])
            uncertain = render_action({"state": "action_unverified", "handoff": handoff}, language)
            self.assertIn(handoff["handoff"]["id"], uncertain["message"])
            self.assertIn("No se pudo verificar" if language == "es" else "Não foi possível verificar", uncertain["message"])
            unverified = render_action({"state": "handoff_unverified", "handoff": handoff["handoff"]}, language)
            self.assertNotIn(handoff["handoff"]["id"], unverified["message"])

    async def test_bank_operation_contexts_are_fresh_and_language_conversation_is_separate(self):
        prepared = await self.prepare()
        first_bank_context = self.bank.calls[0][2]
        await self.service.send("customer-a", self.session_a, self.expiry, "Mis movimientos")
        await self.service.send("customer-a", self.session_a, self.expiry, "Y el último")
        await self.service.send("customer-b", self.session_b, self.expiry, "Mis movimientos")
        first, second, foreign = self.language.calls
        self.assertEqual(first["conversation_id"], second["conversation_id"])
        self.assertNotEqual(first["conversation_id"], foreign["conversation_id"])
        self.assertNotEqual(first["conversation_id"], first_bank_context.conversation_id)
        verified = await self.confirm(prepared)
        self.assertEqual(verified["state"], "intake_verified")
        contexts = [context for _, _, context in self.bank.calls]
        self.assertEqual(contexts[1].operation_id, contexts[2].operation_id)
        self.assertNotEqual(contexts[0].operation_id, contexts[1].operation_id)
        self.assertTrue(all(context.conversation_id == first_bank_context.conversation_id for context in contexts))
        self.assertEqual(self.session_row()["conversation_id"], first["conversation_id"])
        self.assertIn(first_bank_context.conversation_id, first["forbidden_values"])
        self.assertIn(prepared["pending_handle"], first["forbidden_values"])
        self.assertIn(prepared["request_id"], first["forbidden_values"])
        self.assertIn(self.config["bank"]["service_token"], first["forbidden_values"])
        self.assertNotIn("private-a", first["user_text"])

    async def test_same_session_cannot_change_owner_or_expiry(self):
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        original = self.session_row()
        for customer, expiry in [("customer-b", self.expiry), ("customer-a", self.expiry + 1)]:
            with self.assertRaises(ChatError) as mismatch:
                await self.service.send(customer, self.session_a, expiry, "Hola")
            self.assertEqual(mismatch.exception.code, "session_mismatch")
        self.assertEqual(self.session_row(), original)
        self.assertEqual(len(self.language.calls), 1)
        self.assertEqual(self.bank.calls, [])

    async def test_restart_preserves_independent_owned_conversations(self):
        prepared = await self.prepare()
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        original = self.session_row()
        restarted = self.restart()
        await restarted.send("customer-a", self.session_a, self.expiry, "Continúa")
        after = self.session_row(restarted)
        self.assertEqual(after["conversation_id"], original["conversation_id"])
        self.assertEqual(after["bank_context_id"], original["bank_context_id"])
        self.assertEqual(self.language.calls[-1]["conversation_id"], original["conversation_id"])
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), prepared)
        self.assertEqual(len(self.bank.calls), 1)

    async def test_logout_suppresses_inflight_language_reply_and_durably_denies_new_turn(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(text, language, facts, conversation):
            started.set()
            await release.wait()
            return LanguageResult("untrusted prose", "ask_selection", conversation, True)
        self.language.handler = delayed
        current = asyncio.create_task(self.service.send("customer-a", self.session_a, self.expiry, "Hola"))
        await asyncio.wait_for(started.wait(), 5)
        await self.service.revoke("customer-a", self.session_a, self.expiry)
        release.set()
        with self.assertRaises(ChatError) as expired:
            await current
        self.assertEqual(expired.exception.code, "session_expired")
        restarted = self.restart()
        with self.assertRaises(ChatError):
            await restarted.send("customer-a", self.session_a, self.expiry, "Otra consulta")
        self.assertEqual(len(self.language.calls), 1)
        self.assertEqual(len(self.bank.revocations), 1)
        self.assertEqual(self.session_row()["revoked"], 1)
        with self.service._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)

    async def test_redirects_and_worker_errors_do_not_expose_secrets_or_retry(self):
        for status in (302, 401, 429, 500):
            with self.subTest(status=status):
                service, bank, _ = self.fresh("language-error-" + str(status))
                requests = []
                secret = self.config["language"]["service_token"]
                def rejected(request):
                    requests.append(request)
                    return httpx.Response(status, headers={"Location": "https://untrusted.example"}, json={"error": secret})
                service._language = GenericLanguageClient(LanguageConfig(**self.config["language"]),
                    transport=httpx.MockTransport(rejected))
                result = await service.send("customer-a", self.session_a, self.expiry, "Hola")
                self.assertEqual(result["guidance"], "unavailable")
                self.assertFalse(result["banking_authority"])
                self.assertNotIn(secret, json.dumps(result))
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].url.path, "/v1/chat/completions")
                self.assertNotIn("X-Flujo-User-Assertion", requests[0].headers)
                self.assertNotIn(self.config["bank"]["service_token"], requests[0].content.decode())
                self.assertEqual(bank.calls, [])

    async def test_foreign_language_conversation_is_rejected_and_cannot_change_bank_binding(self):
        prepared = await self.prepare()
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        original_session, original_action = self.session_row(), self.action_row()
        original_history = self.service.history("customer-a", self.session_a, self.expiry)["messages"]
        async def foreign(text, language, facts, conversation):
            return LanguageResult("Foreign answer", "ask_selection", str(uuid.uuid4()), True)
        self.language.handler = foreign
        with self.assertRaises(ChatError) as caught:
            await self.service.send("customer-a", self.session_a, self.expiry, "Otra consulta")
        self.assertEqual(caught.exception.code, "chat_invalid_response")
        self.assertEqual(self.session_row()["conversation_id"], original_session["conversation_id"])
        self.assertEqual(self.session_row()["bank_context_id"], original_session["bank_context_id"])
        self.assertEqual(self.action_row(), original_action)
        self.assertEqual(self.service.history("customer-a", self.session_a, self.expiry)["messages"], original_history)
        self.assertEqual(await self.service.action_status("customer-a", self.session_a, self.expiry), prepared)

    async def test_disabled_legacy_config_and_unmapped_customers_fail_before_any_upstream(self):
        for label, config in [
                ("disabled", {}),
                ("legacy-ingress", {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
                    "execution_token": "generated-old-token", "principal_customers": {"subject-a": "customer-a"}}),
                ("invalid-bank-url", {**self.config, "bank": {**self.config["bank"], "base_url": "http://banking-mcp:8000"}})]:
            service = ChatService(config, self.root / label)
            bank, language = attach_direct_fakes(service)
            self.assertFalse(service.status("customer-a")["available"])
            with self.assertRaises(ChatError):
                await service.send("customer-a", self.session_a, self.expiry, "Hola")
            self.assertEqual((bank.calls, language.calls), ([], []))
        with self.assertRaises(ChatError):
            await self.service.send("foreign-customer", self.session_a, self.expiry, "Hola")
        disabled_actions = ChatService({**self.config, "action_enabled": False}, self.root / "read-only")
        bank, language = attach_direct_fakes(disabled_actions)
        with self.assertRaises(ChatError) as unavailable:
            await self.prepare(disabled_actions)
        self.assertEqual(unavailable.exception.code, "action_unavailable")
        self.assertEqual((bank.calls, language.calls), ([], []))

    async def test_generic_language_total_deadline_bounds_transport_without_retry(self):
        requests = []
        async def delayed(request):
            requests.append(request)
            await asyncio.sleep(1)
            self.fail("The generic request should be cancelled at its fixed deadline")
        self.service._language = GenericLanguageClient(LanguageConfig(**{**self.config["language"], "timeout_seconds": 0.01}),
            transport=httpx.MockTransport(delayed))
        result = await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        self.assertEqual(result["guidance"], "unavailable")
        self.assertEqual(len(requests), 1)
        self.assertEqual(self.bank.calls, [])
        self.assertFalse(self.service.history("customer-a", self.session_a, self.expiry)["active"])

    async def test_expired_sessions_and_invalid_messages_never_call_either_upstream(self):
        for expiry in [int(time.time()) - 1, int(time.time()) + 9 * 3600]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, expiry, "Hola")
            self.assertEqual(caught.exception.code, "session_expired")
        for message in ["   ", "a" * 4097, "😀" * 3500]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, self.expiry, message)
            self.assertEqual(caught.exception.code, "invalid_message")
        for fields in [{"language": "en"}, {"facts": {"amount": "150.00"}}]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, self.expiry, "Hola", **fields)
            self.assertEqual(caught.exception.code, "invalid_message")
        self.assertEqual((self.bank.calls, self.language.calls), ([], []))

    async def test_public_history_is_durable_and_excludes_private_model_context(self):
        selection = {"reference": _REF_A, "occurred_at": "2026-06-17T12:00:00", "type": "Purchase",
                     "amount": 42.5, "currency": "COP", "status": "Approved"}
        facts = MinimizedFacts("2026-06-17", "42.50", "COP", None, "approved")
        async def guidance(text, language, facts, conversation):
            return LanguageResult("private-model-prose must never be shown", "explain_selected", conversation, True)
        self.language.handler = guidance
        normalized_request = "¿Puedes explicar el movimiento que seleccioné?"
        result = await self.service.send("customer-a", self.session_a, self.expiry, normalized_request,
            display_message="Consulta este cargo", selection=selection, facts=facts)
        expected = [{"role": "user", "text": "Consulta este cargo", "selection": selection},
                    {"role": "assistant", "text": render_guidance("explain_selected", "es", facts)}]
        self.assertEqual(result["reply"], expected[1]["text"])
        history = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(history["messages"], expected)
        self.assertFalse(history["active"])
        restarted = self.restart()
        self.assertEqual(restarted.history("customer-a", self.session_a, self.expiry)["messages"], expected)
        raw = json.dumps(history)
        for private in [normalized_request, "private-model-prose", "subject-a", "customer-a", self.session_a,
                        self.config["bank"]["service_token"], self.config["language"]["service_token"],
                        "conversation_id", "X-Flujo-User-Assertion", "PRIVATE KEY"]:
            self.assertNotIn(private, raw)
        await restarted.send("customer-a", self.session_a, self.expiry, "Continúa", facts=facts)
        self.assertEqual(len(restarted.history("customer-a", self.session_a, self.expiry)["messages"]), 4)
        self.assertEqual(self.bank.calls, [])

    async def test_history_rejects_foreign_expired_revoked_identity_and_new_session_is_empty(self):
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        for customer, expiry in [("customer-b", self.expiry), ("customer-a", self.expiry + 1),
                                 ("customer-a", int(time.time()) - 1)]:
            with self.assertRaises(ChatError) as caught:
                self.service.history(customer, self.session_a, expiry)
            self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(self.service.history("customer-a", self.session_b, self.expiry)["messages"], [])
        disabled = ChatService({}, self.root / "disabled-history")
        self.assertEqual(disabled.history("customer-a", self.session_a, self.expiry),
                         {"available": False, "messages": [], "active": False})
        await self.service.revoke("customer-a", self.session_a, self.expiry)
        with self.assertRaises(ChatError):
            self.service.history("customer-a", self.session_a, self.expiry)

    async def test_action_enabled_does_not_imply_ledger_continuity_approval(self):
        config = deepcopy(self.config)
        config.pop("ledger_continuity_approved")
        service = ChatService(config, self.root / "unapproved-ledger")
        bank, language = attach_direct_fakes(service)
        self.assertTrue(service.status("customer-a")["available"])
        self.assertFalse(service.status("customer-a")["sandbox_intake_available"])
        with self.assertRaises(ChatError) as blocked:
            await self.prepare(service)
        self.assertEqual(blocked.exception.code, "action_unverified")
        with service._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM action_status").fetchone()[0], 0)
        self.assertEqual((bank.calls, bank.revocations, language.calls), ([], [], []))

    async def test_active_history_does_not_store_uncompleted_or_failed_turns(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def delayed(text, language, facts, conversation):
            started.set()
            await release.wait()
            return LanguageResult("unused prose", "ask_selection", conversation, True)
        self.language.handler = delayed
        operation = asyncio.create_task(self.service.send("customer-a", self.session_a, self.expiry, "Hola"))
        try:
            await asyncio.wait_for(started.wait(), 5)
            pending = self.service.history("customer-a", self.session_a, self.expiry)
            self.assertTrue(pending["active"])
            self.assertEqual(pending["messages"], [])
            with self.assertRaises(ChatError) as busy:
                await self.prepare()
            self.assertEqual(busy.exception.code, "chat_busy")
            self.assertEqual(self.bank.calls, [])
        finally:
            release.set()
            # Surface an early send failure and drain the fake on every path.
            await asyncio.wait_for(operation, 5)
        completed = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertFalse(completed["active"])
        self.assertEqual(len(completed["messages"]), 2)
        async def invalid(text, language, facts, conversation):
            return LanguageResult("not trusted", "ask_selection", str(uuid.uuid4()), True)
        self.language.handler = invalid
        with self.assertRaises(ChatError):
            await self.service.send("customer-a", self.session_a, self.expiry, "Consulta fallida")
        self.assertEqual(self.service.history("customer-a", self.session_a, self.expiry)["messages"], completed["messages"])
        self.assertFalse(self.service.history("customer-a", self.session_a, self.expiry)["active"])

    async def test_legacy_worker_volume_is_rejected_without_reset_or_import(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        old_conversation = str(uuid.uuid4())
        legacy_path = legacy / "frontend-chat.sqlite3"
        with closing(sqlite3.connect(legacy_path)) as db:
            db.execute("""CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                expires INTEGER NOT NULL, conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0)""")
            db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)",
                (self.session_a, "legacy-worker-owner", self.expiry, old_conversation, 0, "legacy-job", self.expiry))
            db.commit()
            before_schema = db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall()
            before_rows = db.execute("SELECT * FROM chat_sessions").fetchall()
        with self.assertRaisesRegex(RuntimeError, "Legacy worker-bound state"):
            ChatService(self.config, legacy)
        with closing(sqlite3.connect(legacy_path)) as db:
            self.assertEqual(db.execute("SELECT name,sql FROM sqlite_master ORDER BY name").fetchall(), before_schema)
            self.assertEqual(db.execute("SELECT * FROM chat_sessions").fetchall(), before_rows)
        self.assertEqual((self.bank.calls, self.language.calls), ([], []))

    async def test_public_selection_rejects_private_fields_and_invalid_amount(self):
        selection = {"reference": _REF_A, "occurred_at": "2026-06-17T12:00:00", "type": "Purchase",
                     "amount": 42.5, "currency": "COP", "status": "Approved"}
        for invalid in [{**selection, "customer_id": "private-customer"}, {**selection, "amount": float("nan")},
                        {**selection, "reference": "upstream-handle"}, {**selection, "amount": True}]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, self.expiry, "Hola", selection=invalid)
            self.assertEqual(caught.exception.code, "invalid_selection")
        self.assertEqual((self.bank.calls, self.language.calls), ([], []))

    async def test_transcript_pair_is_atomic_and_reserved_language_context_survives_storage_failure(self):
        with self.service._connection() as db:
            db.execute("""CREATE TRIGGER reject_assistant BEFORE INSERT ON chat_messages
                WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        history = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(history["messages"], [])
        self.assertFalse(history["active"])
        row = self.session_row()
        self.assertEqual(row["conversation_id"], self.language.calls[0]["conversation_id"])
        self.assertNotEqual(row["conversation_id"], row["bank_context_id"])
        self.assertEqual(self.bank.calls, [])
        with self.service._connection() as db:
            db.execute("DROP TRIGGER reject_assistant")
        restarted = self.restart()
        await restarted.send("customer-a", self.session_a, self.expiry, "Continúa")
        self.assertEqual(self.language.calls[-1]["conversation_id"], row["conversation_id"])
        self.assertEqual(len(restarted.history("customer-a", self.session_a, self.expiry)["messages"]), 2)

    async def test_history_rechecks_expiry_after_storage_read(self):
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        clock = iter([self.expiry - 1, self.expiry])
        with patch("frontend.server.chat.time", SimpleNamespace(time=lambda: next(clock))):
            with self.assertRaises(ChatError) as caught:
                self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(caught.exception.code, "session_expired")

    async def test_bank_authority_rotation_requires_isolated_state_and_preserves_saved_rows(self):
        prepared = await self.prepare()
        original_action, original_session = self.action_row(), self.session_row()
        other = make_direct_config(self.root / "other-authority", action_enabled=True)
        for key, changed in [("issuer", "different-bank-host"), ("base_url", "https://other-bank:8000"),
                ("kid", "different-kid"), ("signing_key_file", other["bank"]["signing_key_file"]),
                ("ca_file", other["bank"]["ca_file"])]:
            with self.subTest(key=key):
                config = {**self.config, "bank": {**self.config["bank"], key: changed}}
                with self.assertRaisesRegex(RuntimeError, "Bank authority policy changed"):
                    ChatService(config, self.state_root)
                self.assertEqual(self.action_row(), original_action)
                self.assertEqual(self.session_row(), original_session)
        self.assertEqual(await self.restart().action_status("customer-a", self.session_a, self.expiry), prepared)
        self.assertEqual(len(self.bank.calls), 1)

    async def test_generic_flow_change_resets_only_language_context_and_preserves_bank_state(self):
        prepared = await self.prepare()
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        original_session, original_action = self.session_row(), self.action_row()
        config = {**self.config, "language": {**self.config["language"],
            "flow_id": "123e4567-e89b-42d3-a456-426614174101", "flow_name": "New_Generic_Guidance"}}
        restarted = self.restart(config=config)
        result = await restarted.send("customer-a", self.session_a, self.expiry, "Continúa")
        self.assertTrue(result["language_context_reset"])
        changed = self.session_row(restarted)
        self.assertNotEqual(changed["conversation_id"], original_session["conversation_id"])
        self.assertEqual(changed["bank_context_id"], original_session["bank_context_id"])
        self.assertEqual(changed["owner"], original_session["owner"])
        self.assertEqual(self.action_row(restarted), original_action)
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), prepared)
        self.assertEqual(len(restarted.history("customer-a", self.session_a, self.expiry)["messages"]), 4)
        self.assertEqual(len(self.bank.calls), 1)


if __name__ == "__main__":
    unittest.main()
