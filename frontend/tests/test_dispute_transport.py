"""Meaningful boundary tests for the customer-scoped FLUJO adapter."""
from __future__ import annotations

import asyncio
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from frontend.server.chat import ChatError
from frontend.server.dispute_chat import DisputeChatService as ChatService
from frontend.tests.action_fixtures import action_facts, action_handoff, action_receipt, action_selected
from frontend.server.action import render_action
from frontend.server.review import review_reference

_REQUEST_ID_PATTERN = r"^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$"


def test_review_reference_accepts_only_saved_random_action_ids():
    action_id = "123e4567-e89b-42d3-a456-426614174000"
    expected = "rev_" + hashlib.sha256(
        ("savia-demo-review-v1:" + action_id).encode("ascii")).hexdigest()[:24]
    assert review_reference(action_id) == expected
    assert review_reference(action_id) == expected
    assert review_reference("a" * 32) == "rev_" + hashlib.sha256(
        ("savia-demo-review-v1:" + "a" * 32).encode("ascii")).hexdigest()[:24]
    for invalid in [None, "", "subject-a", "txn_" + "a" * 24,
                    action_id.upper(), "123e4567-e89b-12d3-a456-426614174000", "A" * 32]:
        assert review_reference(invalid) is None


class ChatServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.signer = Ed25519PrivateKey.generate()
        key_file = self.root / "signer.pem"
        key_file.write_bytes(self.signer.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.config = {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
            "execution_token": "only-the-server-knows-this-token",
            "frontend_signing_key_file": str(key_file), "frontend_kid": "approved-front",
            "frontend_issuer": "approved-frontend", "frontend_audience": "flujo-banking-ingress",
            "principal_customers": {"subject-a": "customer-a", "subject-b": "customer-b"}}
        self.service = ChatService(self.config, self.root)
        self.expiry = int(time.time()) + 3600
        self.session_a = str(uuid.uuid4())
        self.session_b = str(uuid.uuid4())
        self.requests = []

    def tearDown(self):
        self.directory.cleanup()

    def respond(self, request):
        payload = json.loads(request.content)
        self.requests.append((request, payload))
        if request.url.path.endswith("revoke"):
            return httpx.Response(200, json={"revoked": True})
        conversation = payload["metadata"].get("conversationId", str(uuid.uuid4()))
        return httpx.Response(200, json={"conversation_id": conversation, "status": "completed",
            "choices": [{"message": {"role": "assistant", "content": "Consulta verificada."}}],
            "messages": [{"role": "tool", "content": "private-tool-evidence"}]})

    def claims(self, request):
        return jwt.decode(request.headers["X-Flujo-User-Assertion"], self.signer.public_key(),
            algorithms=["EdDSA"], issuer="approved-frontend", audience="flujo-banking-ingress")

    async def test_fresh_action_status_is_empty_without_admitting_chat_or_bank_call(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "fresh")
        enabled._transport = httpx.MockTransport(self.respond)
        self.assertEqual(await enabled.action_status("customer-a", self.session_a, self.expiry), {"state": "none"})
        self.assertEqual(enabled.history("customer-a", self.session_a, self.expiry)["messages"], [])
        self.assertEqual(self.requests, [])
        with enabled._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0], 0)


    async def test_action_requires_inquiry_and_sends_fresh_bound_assertion(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        with self.assertRaises(ChatError) as missing:
            await enabled.action("customer-a", self.session_a, self.expiry,
                                 {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(missing.exception.code, "inquiry_required")
        seen = []
        def respond(request):
            seen.append(request)
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                self.assertEqual(body["operation"], "prepare")
                self.assertRegex(body["conversationId"], r"^[a-f0-9-]{36}$")
                return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                    "pending_handle": "a" * 43, "message": "server result"})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        result = await enabled.action("customer-a", self.session_a, self.expiry,
                                      {"operation": "prepare", "transactionId": "TXN00000001",
                                       "snapshot": "synthetic-build"},
                                      target_reference="txn_" + "a" * 24)
        self.assertEqual(result["state"], "pending_confirmation")
        self.assertNotEqual(self.claims(seen[0])["jti"], self.claims(seen[1])["jti"])
        self.assertEqual(self.claims(seen[1])["sub"], "subject-a")
        with self.assertRaises(ChatError) as foreign:
            await enabled.action("customer-b", self.session_a, self.expiry,
                                 {"operation": "prepare", "transactionId": "TXN00000001",
                                  "snapshot": "synthetic-build"},
                                 target_reference="txn_" + "a" * 24)
        self.assertEqual(foreign.exception.code, "session_mismatch")

    async def test_action_status_recovers_receipt_from_persisted_attempt(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        seen = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                seen.append(body["operation"])
                if body["operation"] == "prepare":
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": "a" * 43})
                return httpx.Response(200, json={"state": "intake_verified",
                    "receipt": action_receipt(snapshot="synthetic-build")})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        await enabled.action("customer-a", self.session_a, self.expiry,
                             {"operation": "prepare", "transactionId": "TXN00000001",
                              "snapshot": "synthetic-build"},
                             target_reference="txn_" + "a" * 24)
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")
        self.assertEqual(seen, ["prepare"])
        owner = enabled._owner_for_subject("subject-a")
        enabled._remember_action(self.session_a, owner, self.expiry,
                                 {"state": "action_unverified", "pending_handle": "a" * 43})
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        recovered = await reloaded.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["receipt"]["id"], "CMP-SBX-abcdefgh")
        self.assertEqual(seen, ["prepare", "receipt"])
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "intake_verified")
        with self.assertRaises(ChatError):
            await reloaded.action_status("customer-b", self.session_a, self.expiry)
        with reloaded._connection() as db:
            db.execute("UPDATE chat_sessions SET revoked=1 WHERE session_id=?", (self.session_a,))
        with self.assertRaises(ChatError):
            await reloaded.action_status("customer-a", self.session_a, self.expiry)

    async def test_lost_prepare_response_recovers_original_pending_identity_after_restart(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if body["operation"] == "prepare":
                    if len(writes) == 1:
                        raise httpx.ReadTimeout("response lost after original pending commit")
                    self.assertEqual(body, writes[0])
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": "a" * 43})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        browser_id = "123e4567-e89b-42d3-a456-426614174000"
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test",
             "requestId": browser_id}, target_reference=reference)
        self.assertEqual((uncertain["state"], uncertain["target_reference"]),
                         ("prepare_unverified", reference))
        self.assertRegex(uncertain["request_id"], _REQUEST_ID_PATTERN)
        self.assertNotEqual(uncertain["request_id"], browser_id)
        self.assertEqual(writes[0]["requestId"], uncertain["request_id"])
        self.assertNotIn("private-a", json.dumps(uncertain))
        with enabled._connection() as db:
            row = db.execute("SELECT * FROM action_status WHERE session_id=?", (self.session_a,)).fetchone()
            self.assertEqual((row["prepare_transaction_id"], row["prepare_snapshot"]),
                             ("private-a", "test"))
            self.assertEqual(row["prepare_conversation_id"], writes[0]["conversationId"])
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        with self.assertRaises(ChatError) as foreign:
            await reloaded.action_status("customer-b", self.session_a, self.expiry)
        self.assertEqual(foreign.exception.status_code, 401)
        with self.assertRaises(ChatError) as overlap:
            await reloaded.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
                target_reference="txn_" + "b" * 24)
        self.assertEqual(overlap.exception.code, "action_in_progress")
        self.assertEqual(len(writes), 1)
        recovered = await reloaded.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual((recovered["state"], recovered["pending_handle"],
                          recovered["target_reference"], recovered["request_id"]),
                         ("pending_confirmation", "a" * 43, reference, uncertain["request_id"]))
        self.assertEqual(len(writes), 2)
        with reloaded._connection() as db:
            row = db.execute("SELECT * FROM action_status WHERE session_id=?", (self.session_a,)).fetchone()
            self.assertIsNone(row["prepare_transaction_id"])
            self.assertIsNone(row["prepare_snapshot"])
            self.assertIsNone(row["prepare_conversation_id"])

    async def test_crashed_preparing_replays_only_after_stale_and_429_does_not_exhaust(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if len(writes) == 1:
                    raise asyncio.CancelledError()
                if len(writes) == 2:
                    return httpx.Response(429, json={"error": "busy"})
                self.assertEqual(body, writes[0])
                return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                    "pending_handle": "a" * 43})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        with self.assertRaises(asyncio.CancelledError):
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
                target_reference="txn_" + "a" * 24)
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "preparing")
        self.assertEqual(len(writes), 1)
        with reloaded._connection() as db:
            db.execute("UPDATE action_status SET updated_at=? WHERE session_id=?",
                       (int(time.time()) - 60, self.session_a))
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "preparing")
        with reloaded._connection() as db:
            row = db.execute("SELECT prepare_recovery_attempts FROM action_status WHERE session_id=?",
                             (self.session_a,)).fetchone()
            self.assertEqual(row["prepare_recovery_attempts"], 0)
            db.execute("UPDATE action_status SET prepare_recovery_after=0 WHERE session_id=?",
                       (self.session_a,))
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")
        self.assertEqual(len(writes), 3)

    async def test_lost_policy_handoff_recovery_cannot_overwrite_later_target(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        replay_started, release_replay = asyncio.Event(), asyncio.Event()
        async def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if len(writes) == 1:
                    raise httpx.ReadTimeout("response lost after HOF commit")
                if len(writes) == 2:
                    replay_started.set()
                    await release_replay.wait()
                if body["transactionId"] == "private-a":
                    self.assertEqual(body, writes[0])
                    return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                        "pending_handle": "a" * 43,
                        "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
                return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                    "pending_handle": "b" * 43})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        first_ref, second_ref = "txn_" + "a" * 24, "txn_" + "b" * 24
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=first_ref)
        self.assertEqual(uncertain["state"], "prepare_unverified")
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        late = asyncio.create_task(reloaded.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(replay_started.wait(), 2)
        with reloaded._connection() as db:
            db.execute("UPDATE action_status SET prepare_recovery_after=0 WHERE session_id=?",
                       (self.session_a,))
        verified = await reloaded.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual((verified["state"], verified["target_reference"], verified["handoff"]["id"]),
                         ("handoff_verified", first_ref, "HOF-abcdefgh"))
        second = await reloaded.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
            target_reference=second_ref)
        release_replay.set()
        self.assertEqual(await asyncio.wait_for(late, 2), second)
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry)), second)
        self.assertEqual(len(writes), 4)

    async def test_expired_prepare_recovery_stays_locked_and_explains_limit(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                writes.append(json.loads(request.content))
                raise httpx.ReadTimeout("prepare response lost")
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference="txn_" + "a" * 24)
        with enabled._connection() as db:
            row = db.execute("SELECT action_id,prepare_conversation_id FROM action_status WHERE session_id=?",
                             (self.session_a,)).fetchone()
            db.execute("UPDATE action_status SET prepare_recovery_deadline=? WHERE session_id=?",
                       (int(time.time()) - 1, self.session_a))
        status = await enabled.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual((status["state"], status["recovery_exhausted"]),
                         ("prepare_unverified", True))
        self.assertEqual(status["review_reference"], review_reference(row["action_id"]))
        self.assertRegex(status["review_reference"], r"^rev_[a-f0-9]{24}$")
        public = json.dumps(status)
        for private in ("private-a", "subject-a", "customer-a", self.session_a,
                        row["action_id"], row["prepare_conversation_id"]):
            self.assertNotIn(private, public)
        self.assertEqual(len(writes), 1)
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["review_reference"],
                         status["review_reference"])
        with self.assertRaises(ChatError):
            await reloaded.action_status("customer-b", self.session_a, self.expiry)
        self.assertEqual(len(writes), 1)
        with self.assertRaises(ChatError) as blocked:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(blocked.exception.code, "action_in_progress")

    async def test_unresolved_prepare_blocks_another_target_before_upstream(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        action_calls = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                action_calls.append(json.loads(request.content))
                return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                    "pending_handle": "a" * 43})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        first_ref, second_ref = "txn_" + "a" * 24, "txn_" + "b" * 24
        first = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=first_ref)
        self.assertEqual(first["target_reference"], first_ref)
        with self.assertRaises(ChatError) as overlap:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
                target_reference=second_ref)
        self.assertEqual((overlap.exception.code, overlap.exception.status_code), ("action_in_progress", 409))
        self.assertEqual(len(action_calls), 1)
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["target_reference"],
                         first_ref)
        self.assertNotIn(first_ref, json.dumps(action_calls))
        owner = enabled._owner_for_subject("subject-a")
        enabled._remember_action(self.session_a, owner, self.expiry,
                                 {"state": "action_unverified", "pending_handle": "a" * 43})
        with self.assertRaises(ChatError) as uncertain_overlap:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
                target_reference=second_ref)
        self.assertEqual(uncertain_overlap.exception.code, "action_in_progress")
        self.assertEqual(len(action_calls), 1)
        with enabled._connection() as db:
            row = db.execute("SELECT result_json,target_reference FROM action_status WHERE session_id=?",
                             (self.session_a,)).fetchone()
        self.assertEqual(row["target_reference"], first_ref)
        self.assertEqual(json.loads(row["result_json"])["pending_handle"], "a" * 43)

    async def test_late_receipt_cannot_replace_new_prepare(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        first_receipt_started, release_first_receipt = asyncio.Event(), asyncio.Event()
        receipt_count = 0
        prepare_count = 0
        async def respond(request):
            nonlocal receipt_count, prepare_count
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                if body["operation"] == "prepare":
                    prepare_count += 1
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": ("a" if prepare_count == 1 else "b") * 43})
                if body["operation"] == "receipt":
                    receipt_count += 1
                    if receipt_count == 1:
                        first_receipt_started.set()
                        await release_first_receipt.wait()
                    return httpx.Response(200, json={"state": "intake_verified",
                        "receipt": action_receipt()})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        first_ref, second_ref = "txn_" + "a" * 24, "txn_" + "b" * 24
        await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=first_ref)
        owner = enabled._owner_for_subject("subject-a")
        enabled._remember_action(self.session_a, owner, self.expiry,
                                 {"state": "action_unverified", "pending_handle": "a" * 43})
        late = asyncio.create_task(enabled.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(first_receipt_started.wait(), 2)
        recovered = await enabled.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["target_reference"], first_ref)
        self.assertEqual(recovered["state"], "intake_verified")
        second = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
            target_reference=second_ref)
        release_first_receipt.set()
        delayed_result = await asyncio.wait_for(late, 2)
        self.assertEqual(delayed_result["target_reference"], second_ref)
        self.assertEqual(delayed_result["pending_handle"], "b" * 43)
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry)), second)
        self.assertEqual((prepare_count, receipt_count), (2, 2))

    async def test_inflight_status_cannot_return_saved_action_after_local_revocation(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        receipt_started, release_receipt = asyncio.Event(), asyncio.Event()
        async def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                if body["operation"] == "prepare":
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": "a" * 43})
                receipt_started.set()
                await release_receipt.wait()
                return httpx.Response(200, json={"state": "intake_verified",
                    "receipt": action_receipt()})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference="txn_" + "a" * 24)
        owner = enabled._owner_for_subject("subject-a")
        enabled._remember_action(self.session_a, owner, self.expiry,
                                 {"state": "action_unverified", "pending_handle": "a" * 43})
        pending_status = asyncio.create_task(enabled.action_status("customer-a", self.session_a, self.expiry))
        await asyncio.wait_for(receipt_started.wait(), 2)
        with enabled._connection() as db:
            db.execute("UPDATE chat_sessions SET revoked=1 WHERE session_id=?", (self.session_a,))
        release_receipt.set()
        with self.assertRaises(ChatError) as denied:
            await asyncio.wait_for(pending_status, 2)
        self.assertEqual(denied.exception.status_code, 401)

    async def test_general_handoff_and_guarded_prepare_keep_durable_status(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        operations = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                operations.append(body["operation"])
                if body["operation"] == "handoff":
                    return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                        "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
                return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                    "handoff": action_handoff("HOF-ijklmnop")})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Necesito ayuda")
        general = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request",
             "requestId": "123e4567-e89b-42d3-a456-426614174000"})
        self.assertEqual(general["state"], "handoff_verified")
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["handoff"],
                         general["handoff"])
        reference = "txn_" + "a" * 24
        guarded = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=reference)
        self.assertEqual(guarded["state"], "handoff_verified")
        self.assertEqual(guarded["target_reference"], reference)
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry)), guarded)
        self.assertEqual(operations, ["handoff", "prepare"])

    async def test_pre_admission_429_restores_previous_action_without_retrying(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        counts = {"prepare": 0, "confirm": 0, "handoff": 0}
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                kind = body["operation"]
                counts[kind] += 1
                if (kind == "prepare" and counts[kind] == 1 or
                        kind == "confirm" and counts[kind] == 1 or
                        kind == "handoff" and counts[kind] in {1, 3}):
                    return httpx.Response(429, json={"error": "banking_busy"})
                if kind == "prepare":
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": ("a" if counts[kind] == 2 else "b") * 43})
                if kind == "confirm":
                    return httpx.Response(200, json={"state": "intake_verified",
                        "receipt": action_receipt()})
                return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                    "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Necesito ayuda")
        first_ref, second_ref = "txn_" + "a" * 24, "txn_" + "b" * 24
        prepare_a = {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"}
        with self.assertRaises(ChatError) as rejected:
            await enabled.action("customer-a", self.session_a, self.expiry, prepare_a,
                                 target_reference=first_ref)
        self.assertEqual(rejected.exception.code, "chat_busy")
        self.assertEqual(await enabled.action_status("customer-a", self.session_a, self.expiry),
                         {"state": "none"})
        prepared = await enabled.action("customer-a", self.session_a, self.expiry, prepare_a,
                                        target_reference=first_ref)
        confirm_a = {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": True}
        with self.assertRaises(ChatError) as rejected:
            await enabled.action("customer-a", self.session_a, self.expiry, confirm_a,
                                 target_reference=first_ref)
        self.assertEqual(rejected.exception.code, "chat_busy")
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")
        verified = await enabled.action("customer-a", self.session_a, self.expiry, confirm_a,
                                        target_reference=first_ref)
        self.assertEqual(verified["state"], "intake_verified")
        general = {"operation": "handoff", "reason": "customer_request"}
        with self.assertRaises(ChatError) as rejected:
            await enabled.action("customer-a", self.session_a, self.expiry, general)
        self.assertEqual(rejected.exception.code, "chat_busy")
        self.assertEqual(await enabled.action_status("customer-a", self.session_a, self.expiry), verified)
        self.assertEqual((await enabled.action("customer-a", self.session_a, self.expiry, general))["state"],
                         "handoff_verified")
        second = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
            target_reference=second_ref)
        with self.assertRaises(ChatError) as rejected:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request",
                 "pendingHandle": second["pending_handle"]}, target_reference=second_ref)
        self.assertEqual(rejected.exception.code, "chat_busy")
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")
        self.assertEqual(counts, {"prepare": 3, "confirm": 2, "handoff": 3})

    async def test_lost_general_handoff_reuses_persisted_id_and_reason_after_restart(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if len(writes) <= 2:
                    # Both the first response and bounded in-request replay
                    # are lost after the worker may have committed the HOF.
                    raise httpx.ReadTimeout("response lost")
                if len(writes) == 3:
                    return httpx.Response(429, json={"error": "banking_busy"})
                return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                    "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Necesito ayuda")
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
                                         {"operation": "handoff", "reason": "customer_request"})
        self.assertEqual(uncertain["state"], "handoff_unverified")
        self.assertRegex(uncertain["request_id"], _REQUEST_ID_PATTERN)
        self.assertEqual(uncertain["reason"], "customer_request")
        self.assertEqual(writes[0]["requestId"], writes[1]["requestId"])
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        recovered = await reloaded.action_status("customer-a", self.session_a, self.expiry)
        self.assertEqual(recovered["request_id"], uncertain["request_id"])
        with self.assertRaises(ChatError) as changed:
            await reloaded.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request", "requestId": str(uuid.uuid4())})
        self.assertEqual(changed.exception.code, "action_in_progress")
        self.assertEqual(len(writes), 2)
        with self.assertRaises(ChatError) as busy:
            await reloaded.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": recovered["reason"],
                 "requestId": recovered["request_id"]})
        self.assertEqual(busy.exception.code, "chat_busy")
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry))["request_id"],
                         uncertain["request_id"])
        verified = await reloaded.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": recovered["reason"],
             "requestId": recovered["request_id"]})
        self.assertEqual(verified["handoff"]["id"], "HOF-abcdefgh")
        self.assertEqual(writes[2]["requestId"], writes[0]["requestId"])
        self.assertEqual(writes[3]["requestId"], writes[0]["requestId"])
        self.assertEqual(writes[3]["reason"], writes[0]["reason"])
        self.assertEqual((await reloaded.action_status("customer-a", self.session_a, self.expiry)), verified)

    async def test_policy_handoff_unverified_retains_exact_recovery_tuple(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if body["operation"] == "prepare":
                    return httpx.Response(200, json={"state": "handoff_unverified",
                        "snapshot": body["snapshot"], "transaction": action_facts(),
                        "reason": body["transactionId"].removeprefix("private-"),
                        "pending_handle": "a" * 43})
                return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                    "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        reference = "txn_" + "a" * 24
        for customer, session_id, reason in [
                ("customer-a", self.session_a, "high_risk"),
                ("customer-b", self.session_b, "missing_evidence")]:
            await enabled.send(customer, session_id, self.expiry, "No reconozco el cargo")
            uncertain = await enabled.action(customer, session_id, self.expiry,
                {"operation": "prepare", "transactionId": "private-" + reason,
                 "snapshot": "test"}, target_reference=reference)
            self.assertEqual(uncertain["state"], "handoff_unverified")
            self.assertEqual(uncertain["reason"], reason)
            self.assertEqual(uncertain["target_reference"], reference)
            self.assertEqual(uncertain["pending_handle"], "a" * 43)
            self.assertRegex(uncertain["request_id"], _REQUEST_ID_PATTERN)
            reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
            reloaded._transport = httpx.MockTransport(respond)
            self.assertEqual((await reloaded.action_status(customer, session_id, self.expiry))["request_id"],
                             uncertain["request_id"])
            with self.assertRaises(ChatError) as changed:
                await reloaded.action(customer, session_id, self.expiry,
                    {"operation": "handoff", "reason": "customer_request",
                     "pendingHandle": "a" * 43, "requestId": uncertain["request_id"]},
                    target_reference=reference)
            self.assertEqual(changed.exception.code, "action_mismatch")
            with self.assertRaises(ChatError) as changed:
                await reloaded.action(customer, session_id, self.expiry,
                    {"operation": "handoff", "reason": reason,
                     "pendingHandle": "a" * 43, "requestId": str(uuid.uuid4())},
                    target_reference=reference)
            self.assertEqual(changed.exception.code, "action_mismatch")
            before_retry = len(writes)
            verified = await reloaded.action(customer, session_id, self.expiry,
                {"operation": "handoff", "reason": reason,
                 "pendingHandle": "a" * 43, "requestId": uncertain["request_id"]},
                target_reference=reference)
            self.assertEqual(verified["state"], "handoff_verified")
            self.assertEqual(len(writes), before_retry + 1)
            self.assertEqual(writes[-1]["requestId"], writes[-2]["requestId"])
            self.assertEqual(writes[-1]["reason"], reason)

    async def test_confirm_policy_handoff_retry_preserves_handle_reason_dedup(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if body["operation"] == "prepare":
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": "a" * 43})
                if body["operation"] == "confirm":
                    return httpx.Response(200, json={"state": "handoff_unverified",
                        "reason": "high_risk"})
                return httpx.Response(200, json={"state": "handoff_verified",
                    **({"snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts()} if json.loads(request.content)["operation"] == "prepare" else {}),
                    "handoff": action_handoff(reason=body.get("reason", "customer_request"),
                            snapshot="test" if body.get("pendingHandle") or body["operation"] == "prepare" else None)})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        prepared = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=reference)
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": True},
            target_reference=reference)
        self.assertEqual((uncertain["state"], uncertain["reason"]), ("handoff_unverified", "high_risk"))
        self.assertEqual(uncertain["request_id"], prepared["request_id"])
        verified = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "high_risk"},
            target_reference=reference)
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(verified["request_id"], prepared["request_id"])
        self.assertEqual(writes[-1]["requestId"], prepared["request_id"])
        self.assertEqual(writes[-1]["pendingHandle"], prepared["pending_handle"])
        before_replay = len(writes)
        replayed = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": prepared["pending_handle"], "reason": "high_risk"},
            target_reference=reference)
        self.assertEqual(replayed["handoff"]["id"], verified["handoff"]["id"])
        self.assertEqual(replayed["request_id"], prepared["request_id"])
        self.assertEqual(len(writes), before_replay)

    async def test_lost_confirm_does_not_guess_a_second_handoff_reason(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path == "/v1/banking/action":
                body = json.loads(request.content)
                writes.append(body)
                if body["operation"] == "prepare":
                    return httpx.Response(200, json={"state": "pending_confirmation",
                    "snapshot": json.loads(request.content)["snapshot"], "transaction": action_facts(),
                        "pending_handle": "a" * 43})
                if body["operation"] == "confirm":
                    # FLUJO may already have created a high-risk HOF here.
                    raise httpx.ReadTimeout("policy response lost")
                if body["operation"] == "receipt":
                    return httpx.Response(200, json={"state": "action_unverified"})
                self.fail("A guessed handoff would use a different idempotency key")
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        prepared = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=reference)
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "confirm", "pendingHandle": prepared["pending_handle"], "confirmed": True},
            target_reference=reference)
        self.assertEqual(uncertain["state"], "action_unverified")
        self.assertNotIn("handoff", uncertain)
        self.assertEqual([body["operation"] for body in writes], ["prepare", "confirm", "receipt"])
        with self.assertRaises(ChatError) as denied:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": "customer_request",
                 "pendingHandle": prepared["pending_handle"]}, target_reference=reference)
        self.assertEqual(denied.exception.code, "action_in_progress")
        self.assertEqual(len(writes), 3)

    async def test_existing_case_origin_survives_restart_and_only_explicit_handoff_writes(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        questions = ["¿Qué opciones de revisión tengo?"]
        def respond(request):
            if request.url.path != "/v1/banking/action":
                return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            if body["operation"] == "prepare":
                return httpx.Response(200, json={"state": "existing_case_verified", "pending_handle": "a" * 43,
                    "snapshot": body["snapshot"], "transaction": action_facts(),
                    "receipt": action_receipt(snapshot="original-old")})
            self.assertEqual(body["operation"], "handoff")
            return httpx.Response(200, json={"state": "handoff_verified", "handoff": action_handoff(
                reason=body["reason"], questions=body["unanswered_questions"])})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        existing = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"}, target_reference=reference)
        self.assertEqual(existing["state"], "existing_case_verified")
        self.assertEqual(existing["snapshot"], "test")
        self.assertEqual(existing["receipt"]["snapshot"], "original-old")
        with self.assertRaises(ChatError) as blocked:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True}, target_reference=reference)
        self.assertEqual(blocked.exception.code, "action_in_progress")
        reloaded = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        reloaded._transport = httpx.MockTransport(respond)
        self.assertEqual(await reloaded.action_status("customer-a", self.session_a, self.expiry), existing)
        handed = await reloaded.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "pendingHandle": "a" * 43, "reason": "customer_request",
             "unansweredQuestions": questions}, target_reference=reference)
        self.assertEqual(handed["state"], "handoff_verified")
        self.assertEqual(handed["handoff"]["unanswered_questions"], questions)
        restarted = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), handed)
        self.assertEqual([body["operation"] for body in writes], ["prepare", "handoff"])
        self.assertEqual(writes[-1]["requestId"], existing["request_id"])

    async def test_pending_consent_rejects_changed_owned_snapshot_or_charge_before_upstream(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            return httpx.Response(200, json={"state": "pending_confirmation", "pending_handle": "a" * 43,
                "snapshot": body["snapshot"], "transaction": action_facts()})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"}, target_reference=reference)
        for context in ({"expected_snapshot": "changed-build"},
                        {"expected_transaction": action_selected(amount=999)}):
            with self.assertRaises(ChatError) as blocked:
                await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True},
                    target_reference=reference, **context)
            self.assertEqual(blocked.exception.code, "action_mismatch")
        self.assertEqual(len(writes), 1)
        self.assertEqual((await enabled.action_status("customer-a", self.session_a, self.expiry))["state"],
                         "pending_confirmation")

    async def test_prepare_rejects_owned_process_date_channel_and_product_drift(self):
        for field, changed in {"process_date": "2026-06-18", "channel": "Branch", "product": "Tarjeta Crédito"}.items():
            with self.subTest(field=field):
                enabled = ChatService({**self.config, "action_enabled": True}, self.root / field)
                writes = []
                def respond(request):
                    if request.url.path != "/v1/banking/action": return self.respond(request)
                    body = json.loads(request.content)
                    writes.append(body)
                    self.assertEqual(body["operation"], "prepare")
                    return httpx.Response(200, json={"state": "pending_confirmation", "pending_handle": "a" * 43,
                        "snapshot": body["snapshot"], "transaction": action_facts(action_selected(**{field: changed}))})
                enabled._transport = httpx.MockTransport(respond)
                await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
                reference = "txn_" + "a" * 24
                prepared = await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
                    target_reference=reference, expected_snapshot="test", expected_transaction=action_selected())
                self.assertEqual(prepared["state"], "prepare_unverified")
                self.assertNotIn("pending_handle", prepared)
                with self.assertRaises(ChatError) as blocked:
                    await enabled.action("customer-a", self.session_a, self.expiry,
                        {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True},
                        target_reference=reference, expected_snapshot="test", expected_transaction=action_selected())
                self.assertEqual(blocked.exception.code, "action_mismatch")
                self.assertEqual(len(writes), 1)

    async def test_confirm_rejects_owned_process_date_channel_and_product_drift_before_post(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            self.assertEqual(body["operation"], "prepare")
            return httpx.Response(200, json={"state": "pending_confirmation", "pending_handle": "a" * 43,
                "snapshot": body["snapshot"], "transaction": action_facts()})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        prepared = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
            target_reference=reference, expected_snapshot="test", expected_transaction=action_selected())
        self.assertEqual(prepared["state"], "pending_confirmation")
        with enabled._connection() as db:
            original_row = dict(db.execute("SELECT * FROM action_status WHERE session_id=?", (self.session_a,)).fetchone())
        for field, changed in {"process_date": "2026-06-18", "channel": "Branch", "product": "Tarjeta Crédito"}.items():
            with self.subTest(field=field):
                with self.assertRaises(ChatError) as blocked:
                    await enabled.action("customer-a", self.session_a, self.expiry,
                        {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True},
                        target_reference=reference, expected_snapshot="test",
                        expected_transaction=action_selected(**{field: changed}))
                self.assertEqual(blocked.exception.code, "action_mismatch")
                self.assertEqual(len(writes), 1)
                with enabled._connection() as db:
                    self.assertEqual(dict(db.execute("SELECT * FROM action_status WHERE session_id=?", (self.session_a,)).fetchone()), original_row)

    async def test_valid_receipt_for_different_selected_charge_cannot_resolve_prepare(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        receipt = action_receipt(snapshot="original-old")
        receipt["transaction"]["amount"] = "999.00"
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            return httpx.Response(200, json={"state": "existing_case_verified", "pending_handle": "a" * 43,
                "snapshot": body["snapshot"], "transaction": receipt["transaction"], "receipt": receipt})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        reference = "txn_" + "a" * 24
        rejected = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"}, target_reference=reference,
            expected_snapshot="test", expected_transaction=action_selected())
        self.assertEqual(rejected["state"], "prepare_unverified")
        self.assertNotIn("receipt", rejected)
        with self.assertRaises(ChatError) as locked:
            await enabled.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
                target_reference="txn_" + "b" * 24)
        self.assertEqual(locked.exception.code, "action_in_progress")

    async def test_wrong_receipt_or_handoff_readback_stays_locked_under_original_target(self):
        for terminal in ("receipt", "handoff"):
            with self.subTest(terminal=terminal):
                enabled = ChatService({**self.config, "action_enabled": True}, self.root / terminal)
                def respond(request):
                    if request.url.path != "/v1/banking/action": return self.respond(request)
                    body = json.loads(request.content)
                    if body["operation"] == "prepare":
                        return httpx.Response(200, json={"state": "pending_confirmation", "pending_handle": "a" * 43,
                            "snapshot": "test", "transaction": action_facts()})
                    if terminal == "receipt":
                        return httpx.Response(200, json={"state": "intake_verified",
                            "receipt": action_receipt(snapshot="another-build")})
                    return httpx.Response(200, json={"state": "handoff_verified",
                        "handoff": action_handoff(snapshot="another-build")})
                enabled._transport = httpx.MockTransport(respond)
                await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
                reference = "txn_" + "a" * 24
                await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"}, target_reference=reference)
                operation = ({"operation": "confirm", "confirmed": True} if terminal == "receipt" else
                             {"operation": "handoff", "reason": "customer_request"})
                result = await enabled.action("customer-a", self.session_a, self.expiry,
                    {**operation, "pendingHandle": "a" * 43}, target_reference=reference)
                self.assertEqual(result["state"], "action_unverified" if terminal == "receipt" else "handoff_unverified")
                self.assertNotIn(terminal, result)
                self.assertEqual(result["target_reference"], reference)
                with self.assertRaises(ChatError):
                    await enabled.action("customer-a", self.session_a, self.expiry,
                        {"operation": "prepare", "transactionId": "private-b", "snapshot": "test"},
                        target_reference="txn_" + "b" * 24)

    async def test_lost_handoff_questions_are_frozen_across_restart_and_changed_retry_rejected(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        questions = ["Qual o próximo passo?"]
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            if len(writes) <= 2: raise httpx.ReadTimeout("response lost after packet commit")
            return httpx.Response(200, json={"state": "handoff_verified", "handoff": action_handoff(
                snapshot=None, reason=body["reason"], questions=body["unanswered_questions"])})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Quero uma pessoa")
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": questions})
        self.assertEqual(uncertain["unanswered_questions"], questions)
        self.assertEqual(writes[0], writes[1])
        restarted = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        restarted._transport = httpx.MockTransport(respond)
        with self.assertRaises(ChatError) as changed:
            await restarted.action("customer-a", self.session_a, self.expiry,
                {"operation": "handoff", "reason": uncertain["reason"], "requestId": uncertain["request_id"],
                 "unansweredQuestions": ["Another question"]})
        self.assertEqual(changed.exception.code, "action_mismatch")
        self.assertEqual(len(writes), 2)
        recovered = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": uncertain["reason"], "requestId": uncertain["request_id"]})
        self.assertEqual(writes[0], writes[-1])
        self.assertEqual(recovered["handoff"]["unanswered_questions"], questions)
        self.assertEqual((await restarted.action_status("customer-a", self.session_a, self.expiry)), recovered)

    async def test_verified_receipt_survives_uncertain_followup_only_for_same_owned_charge(self):
        original_ref, other_ref = "txn_" + "a" * 24, "txn_" + "b" * 24
        for reference in (original_ref, other_ref):
            with self.subTest(reference=reference):
                enabled = ChatService({**self.config, "action_enabled": True}, self.root / reference)
                writes = []
                def respond(request):
                    if request.url.path != "/v1/banking/action": return self.respond(request)
                    body = json.loads(request.content)
                    writes.append(body)
                    if body["operation"] == "confirm":
                        return httpx.Response(200, json={"state": "intake_verified", "receipt": action_receipt(snapshot="old-build")})
                    self.assertEqual(body["operation"], "prepare")
                    if len(writes) == 1:
                        return httpx.Response(200, json={"state": "pending_confirmation", "pending_handle": "a" * 43,
                            "snapshot": "old-build", "transaction": action_facts()})
                    raise httpx.ReadTimeout("followup prepare response lost")
                enabled._transport = httpx.MockTransport(respond)
                await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
                await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "prepare", "transactionId": "private-a", "snapshot": "old-build"},
                    target_reference=original_ref, expected_transaction=action_selected())
                intake = await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True},
                    target_reference=original_ref, expected_transaction=action_selected())
                self.assertEqual(intake["state"], "intake_verified")
                uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
                    {"operation": "prepare", "transactionId": "private-a" if reference == original_ref else "private-b",
                     "snapshot": "new-build"}, target_reference=reference, expected_transaction=action_selected())
                self.assertEqual(uncertain["state"], "prepare_unverified")
                if reference == original_ref:
                    self.assertEqual(uncertain["prior_receipt"], {"target_reference": original_ref, "receipt": intake["receipt"]})
                    self.assertEqual(uncertain["prior_receipt"]["receipt"]["snapshot"], "old-build")
                else:
                    self.assertNotIn("prior_receipt", uncertain)
                restarted = ChatService({**self.config, "action_enabled": True}, self.root / reference)
                restarted._transport = httpx.MockTransport(respond)
                recovered = await restarted.action_status("customer-a", self.session_a, self.expiry)
                self.assertEqual(recovered.get("prior_receipt"), uncertain.get("prior_receipt"))
                self.assertEqual(recovered["state"], "prepare_unverified")
                with self.assertRaises(ChatError) as no_confirm:
                    await restarted.action("customer-a", self.session_a, self.expiry,
                        {"operation": "confirm", "pendingHandle": "a" * 43, "confirmed": True},
                        target_reference=reference, expected_transaction=action_selected())
                self.assertEqual(no_confirm.exception.code, "action_mismatch")
                with self.assertRaises(ChatError) as locked:
                    await restarted.action("customer-a", self.session_a, self.expiry,
                        {"operation": "prepare", "transactionId": "private-new", "snapshot": "new-build"},
                        target_reference=other_ref if reference == original_ref else original_ref)
                self.assertEqual(locked.exception.code, "action_in_progress")
                self.assertEqual([body["operation"] for body in writes].count("confirm"), 1)
                self.assertTrue(all(body == writes[2] for body in writes[2:]))

    async def test_new_general_handoff_retains_prior_proof_without_unlocking_uncertain_request(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        old_id, new_id = str(uuid.uuid4()), str(uuid.uuid4())
        old_questions, new_questions = ["Qual ajuda precisa?"], ["Como posso acompanhar?"]
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            if 2 <= len(writes) <= 3:
                raise httpx.ReadTimeout("new handoff response lost")
            return httpx.Response(200, json={"state": "handoff_verified", "handoff": action_handoff(
                "HOF-abcdefgh" if body["requestId"] == old_id else "HOF-ijklmnop", snapshot=None,
                reason=body["reason"], questions=body["unanswered_questions"])})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Quero uma pessoa")
        old = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": old_id,
             "unansweredQuestions": old_questions})
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": new_id,
             "unansweredQuestions": new_questions})
        self.assertEqual(uncertain["state"], "handoff_unverified")
        self.assertEqual(uncertain["request_id"], new_id)
        self.assertEqual(uncertain["unanswered_questions"], new_questions)
        self.assertEqual(uncertain["prior_handoff"], {"target_reference": None, "handoff": old["handoff"]})
        restarted = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        restarted._transport = httpx.MockTransport(respond)
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), uncertain)
        for blocked_id in (old_id, str(uuid.uuid4())):
            with self.assertRaises(ChatError) as locked:
                await restarted.action("customer-a", self.session_a, self.expiry,
                    {"operation": "handoff", "reason": "customer_request", "requestId": blocked_id})
            self.assertEqual(locked.exception.code, "action_in_progress")
        self.assertEqual(len(writes), 3)
        verified = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": new_id})
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(verified["handoff"]["id"], "HOF-ijklmnop")
        self.assertEqual(verified["handoff"]["unanswered_questions"], new_questions)
        self.assertEqual(verified["prior_handoff"], uncertain["prior_handoff"])
        self.assertEqual(writes[1], writes[2])
        self.assertEqual(writes[1], writes[3])
        replay = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": new_id})
        self.assertEqual(replay, verified)
        self.assertEqual(len(writes), 4)

    async def test_general_handoff_rejects_charged_packet_and_only_valid_general_readback_unlocks(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        questions = ["Qual o próximo passo?"]
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            return httpx.Response(200, json={"state": "handoff_verified", "handoff": action_handoff(
                snapshot="unbound-charge" if len(writes) == 1 else None,
                reason=body["reason"], questions=body["unanswered_questions"])})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Quero uma pessoa")
        uncertain = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "unansweredQuestions": questions})
        self.assertEqual(uncertain["state"], "handoff_unverified")
        self.assertNotIn("handoff", uncertain)
        self.assertEqual(uncertain["unanswered_questions"], questions)
        restarted = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        restarted._transport = httpx.MockTransport(respond)
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), uncertain)
        with self.assertRaises(ChatError) as locked:
            await restarted.action("customer-a", self.session_a, self.expiry,
                {"operation": "prepare", "transactionId": "private-a", "snapshot": "test"},
                target_reference="txn_" + "a" * 24)
        self.assertEqual(locked.exception.code, "action_in_progress")
        self.assertEqual(len(writes), 1)
        verified = await restarted.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": uncertain["reason"], "requestId": uncertain["request_id"]})
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(verified["handoff"]["facts"], {})
        self.assertIsNone(verified["handoff"]["snapshot"])
        self.assertIsNone(verified["handoff"]["transaction_provenance"])
        self.assertEqual(verified["handoff"]["transaction_currentness"], "not_applicable")
        self.assertEqual(writes[0], writes[1])

    async def test_verified_general_handoff_replay_preserves_packet_and_row_after_restart(self):
        enabled = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        questions = ["Qual o próximo passo?"]
        request_id = str(uuid.uuid4())
        writes = []
        def respond(request):
            if request.url.path != "/v1/banking/action": return self.respond(request)
            body = json.loads(request.content)
            writes.append(body)
            return httpx.Response(200, json={"state": "handoff_verified", "handoff": action_handoff(
                snapshot=None, reason=body["reason"], questions=body["unanswered_questions"])})
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "Quero uma pessoa")
        verified = await enabled.action("customer-a", self.session_a, self.expiry,
            {"operation": "handoff", "reason": "customer_request", "requestId": request_id,
             "unansweredQuestions": ["  Qual o próximo passo?  "]})
        self.assertEqual(verified["state"], "handoff_verified")
        self.assertEqual(verified["handoff"]["unanswered_questions"], questions)
        with enabled._connection() as db:
            original_row = dict(db.execute("SELECT * FROM action_status WHERE session_id=?",
                                           (self.session_a,)).fetchone())
        restarted = ChatService({**self.config, "action_enabled": True}, self.root / "actions")
        restarted._transport = httpx.MockTransport(respond)
        self.assertEqual(writes[0]["unanswered_questions"], questions)
        for supplied in ({}, {"unansweredQuestions": questions},
                         {"unansweredQuestions": ["  Qual o próximo passo?  "]}):
            with self.subTest(supplied=supplied):
                replayed = await restarted.action("customer-a", self.session_a, self.expiry,
                    {"operation": "handoff", "reason": "customer_request", "requestId": request_id, **supplied})
                self.assertEqual(replayed, verified)
                self.assertEqual(len(writes), 1)
                with restarted._connection() as db:
                    replayed_row = dict(db.execute("SELECT * FROM action_status WHERE session_id=?",
                                                  (self.session_a,)).fetchone())
                self.assertEqual(replayed_row, original_row)
        for changed in ({"unansweredQuestions": []}, {"unansweredQuestions": ["Outra pergunta?"]},
                        {"reason": "clarification_exhausted"}):
            with self.subTest(changed=changed):
                with self.assertRaises(ChatError) as rejected:
                    await restarted.action("customer-a", self.session_a, self.expiry,
                        {"operation": "handoff", "reason": "customer_request", "requestId": request_id, **changed})
                self.assertEqual((rejected.exception.code, rejected.exception.status_code), ("action_mismatch", 409))
                self.assertEqual(len(writes), 1)
                with restarted._connection() as db:
                    rejected_row = dict(db.execute("SELECT * FROM action_status WHERE session_id=?",
                                                  (self.session_a,)).fetchone())
                self.assertEqual(rejected_row, original_row)
        self.assertEqual(await restarted.action_status("customer-a", self.session_a, self.expiry), verified)

    def test_es_pt_fallback_requires_verified_persisted_ids(self):
        handoff = {"state": "handoff_verified", "handoff": action_handoff("HOF-" + "a" * 8)}
        for language, id_label in [("es", "Folio"), ("pt", "Protocolo")]:
            named = render_action(handoff, language)
            self.assertIn(id_label, named["message"])
            self.assertIn(handoff["handoff"]["id"], named["message"])
            uncertain = render_action({"state": "action_unverified", "handoff": handoff}, language)
            self.assertIn(handoff["handoff"]["id"], uncertain["message"])
            self.assertIn("No se pudo verificar" if language == "es" else "Não foi possível verificar",
                          uncertain["message"])
            unverified = render_action({"state": "handoff_unverified", "handoff": handoff["handoff"]}, language)
            self.assertNotIn(handoff["handoff"]["id"], unverified["message"])

    async def test_assertions_are_fresh_and_conversations_are_server_bound(self):
        self.service._transport = httpx.MockTransport(self.respond)
        first = await self.service.send("customer-a", self.session_a, self.expiry, "Mis movimientos")
        second = await self.service.send("customer-a", self.session_a, self.expiry, "Y el último")
        await self.service.send("customer-b", self.session_b, self.expiry, "Mis movimientos")
        claims = [self.claims(request) for request, _ in self.requests]
        self.assertEqual([value["sub"] for value in claims], ["subject-a", "subject-a", "subject-b"])
        self.assertEqual(len({value["jti"] for value in claims}), 3)
        self.assertTrue(all(value["exp"] - value["iat"] == 120 for value in claims))
        self.assertTrue(all(value["session_exp"] == self.expiry for value in claims))
        self.assertTrue(all(value["scope"] == ["bank:read"] for value in claims))
        self.assertNotIn("conversationId", self.requests[0][1]["metadata"])
        self.assertIn("conversationId", self.requests[1][1]["metadata"])
        self.assertNotIn("conversationId", self.requests[2][1]["metadata"])
        self.assertEqual(self.requests[0][1]["model"], "flow-Banking_Customer")
        self.assertEqual(first, second)
        self.assertEqual(set(first), {"reply", "status", "mode"})
        self.assertNotIn("private-tool-evidence", json.dumps(first))
        self.assertNotIn(self.config["execution_token"], json.dumps(first))
        self.assertEqual(jwt.get_unverified_header(self.requests[0][0].headers["X-Flujo-User-Assertion"]),
                         {"alg": "EdDSA", "kid": "approved-front", "typ": "flujo-ingress+jwt"})

    async def test_same_session_cannot_change_owner_or_expiry(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        for customer, expiry in [("customer-b", self.expiry), ("customer-a", self.expiry + 1)]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send(customer, self.session_a, expiry, "Hola")
            self.assertEqual(caught.exception.code, "session_mismatch")
        self.assertEqual(len(self.requests), 1)

    async def test_restart_retains_owned_conversation(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        reloaded = ChatService(self.config, self.root)
        reloaded._transport = httpx.MockTransport(self.respond)
        await reloaded.send("customer-a", self.session_a, self.expiry, "Continúa")
        self.assertIn("conversationId", self.requests[-1][1]["metadata"])

    async def test_logout_suppresses_inflight_reply_and_durably_denies_new_turn(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed(request):
            if request.url.path.endswith("revoke"):
                return self.respond(request)
            started.set()
            await release.wait()
            return self.respond(request)

        self.service._transport = httpx.MockTransport(delayed)
        current = asyncio.create_task(self.service.send("customer-a", self.session_a, self.expiry, "Hola"))
        await started.wait()
        with self.assertRaises(ChatError) as busy:
            await self.service.send("customer-a", self.session_a, self.expiry, "Segundo")
        self.assertEqual(busy.exception.code, "chat_busy")
        await self.service.revoke("customer-a", self.session_a, self.expiry)
        release.set()
        with self.assertRaises(ChatError) as expired:
            await current
        self.assertEqual(expired.exception.code, "session_expired")
        reloaded = ChatService(self.config, self.root)
        with self.assertRaises(ChatError):
            await reloaded.send("customer-a", self.session_a, self.expiry, "Hola otra vez")

    async def test_redirects_and_upstream_errors_do_not_expose_secrets_or_retry(self):
        def rejected(request):
            self.requests.append((request, {}))
            return httpx.Response(302, headers={"Location": "https://untrusted.example"},
                                  json={"error": self.config["execution_token"]})
        self.service._transport = httpx.MockTransport(rejected)
        with self.assertRaises(ChatError) as caught:
            await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        self.assertEqual(caught.exception.status_code, 502)
        self.assertNotIn(self.config["execution_token"], str(caught.exception))
        self.assertEqual(len(self.requests), 1)

    async def test_foreign_upstream_conversation_is_rejected(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        def foreign(request):
            return httpx.Response(200, json={"conversation_id": str(uuid.uuid4()), "status": "completed",
                "choices": [{"message": {"role": "assistant", "content": "Foreign answer"}}]})
        self.service._transport = httpx.MockTransport(foreign)
        with self.assertRaises(ChatError) as caught:
            await self.service.send("customer-a", self.session_a, self.expiry, "Otra consulta")
        self.assertEqual(caught.exception.code, "chat_invalid_response")

    async def test_disabled_config_and_unmapped_customers_fail_before_network(self):
        disabled = ChatService({}, self.root / "disabled")
        self.assertFalse(disabled.status("customer-a")["available"])
        self.assertFalse(self.service.status("foreign-customer")["available"])
        with self.assertRaises(ChatError):
            await self.service.send("foreign-customer", self.session_a, self.expiry, "Hola")
        untrusted = ChatService({**self.config, "base_url": "http://untrusted.example"}, self.root / "untrusted")
        self.assertFalse(untrusted.status("customer-a")["available"])

    async def test_total_deadline_bounds_transport_and_does_not_retry(self):
        async def delayed(request):
            self.requests.append((request, {}))
            await asyncio.sleep(1)
            return httpx.Response(200, json={"revoked": True})
        self.service._transport = httpx.MockTransport(delayed)
        with self.assertRaises(ChatError) as caught:
            await self.service._post("/v1/banking/session/revoke",
                self.service._headers("subject-a", self.session_a, self.expiry), {}, timeout_seconds=0.01)
        self.assertEqual(caught.exception.code, "chat_timeout")
        self.assertEqual(len(self.requests), 1)

    async def test_expired_sessions_and_invalid_messages_never_call_upstream(self):
        self.service._transport = httpx.MockTransport(self.respond)
        for expiry in [int(time.time()) - 1, int(time.time()) + 9 * 3600]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, expiry, "Hola")
            self.assertEqual(caught.exception.code, "session_expired")
        for message in ["   ", "a" * 4097, "😀" * 3500]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, self.expiry, message)
            self.assertEqual(caught.exception.code, "invalid_message")
        self.assertEqual(self.requests, [])

    async def test_public_history_is_durable_and_excludes_private_model_context(self):
        self.service._transport = httpx.MockTransport(self.respond)
        selection = {"reference": "txn_" + "a" * 24, "occurred_at": "2026-06-17T12:00:00",
                     "type": "Purchase", "amount": 42.50, "currency": "COP", "status": "Approved"}
        await self.service.send("customer-a", self.session_a, self.expiry,
                                "Consulta este cargo\n\nserver-added-private-facts",
                                display_message="Consulta este cargo", selection=selection)
        expected = [{"role": "user", "text": "Consulta este cargo", "selection": selection},
                    {"role": "assistant", "text": "Consulta verificada."}]
        history = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(history["messages"], expected)
        self.assertFalse(history["active"])
        reloaded = ChatService(self.config, self.root)
        self.assertEqual(reloaded.history("customer-a", self.session_a, self.expiry)["messages"], expected)
        raw = json.dumps(history)
        for private in ["server-added-private-facts", "private-tool-evidence", "subject-a", "customer-a",
                        self.config["execution_token"], "conversation_id", "X-Flujo-User-Assertion", "PRIVATE KEY"]:
            self.assertNotIn(private, raw)
        reloaded._transport = httpx.MockTransport(self.respond)
        await reloaded.send("customer-a", self.session_a, self.expiry, "Continúa")
        self.assertIn("conversationId", self.requests[-1][1]["metadata"])
        self.assertEqual(len(reloaded.history("customer-a", self.session_a, self.expiry)["messages"]), 4)

    async def test_history_rejects_foreign_expired_revoked_identity_and_new_session_is_empty(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        for customer, expiry in [("customer-b", self.expiry), ("customer-a", self.expiry + 1),
                                 ("customer-a", int(time.time()) - 1)]:
            with self.assertRaises(ChatError) as caught:
                self.service.history(customer, self.session_a, expiry)
            self.assertEqual(caught.exception.status_code, 401)
        fresh = self.service.history("customer-a", self.session_b, self.expiry)
        self.assertEqual(fresh["messages"], [])
        disabled = ChatService({}, self.root / "disabled-history")
        self.assertEqual(disabled.history("customer-a", self.session_a, self.expiry),
                         {"available": False, "messages": [], "active": False})
        await self.service.revoke("customer-a", self.session_a, self.expiry)
        with self.assertRaises(ChatError):
            self.service.history("customer-a", self.session_a, self.expiry)

    async def test_active_history_does_not_store_uncompleted_or_failed_turns(self):
        started = asyncio.Event()
        release = asyncio.Event()
        async def delayed(request):
            started.set()
            await release.wait()
            return self.respond(request)
        self.service._transport = httpx.MockTransport(delayed)
        operation = asyncio.create_task(self.service.send("customer-a", self.session_a, self.expiry, "Hola"))
        await started.wait()
        pending = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertTrue(pending["active"])
        self.assertEqual(pending["messages"], [])
        release.set()
        await operation
        completed = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertFalse(completed["active"])
        self.assertEqual(len(completed["messages"]), 2)
        self.service._transport = httpx.MockTransport(lambda _: httpx.Response(500, json={"error": "private-error"}))
        with self.assertRaises(ChatError):
            await self.service.send("customer-a", self.session_a, self.expiry, "Consulta fallida")
        self.assertEqual(self.service.history("customer-a", self.session_a, self.expiry)["messages"], completed["messages"])
        self.assertFalse(self.service.history("customer-a", self.session_a, self.expiry)["active"])

    async def test_legacy_hidden_conversation_is_reset_once_and_new_history_survives_restart(self):
        legacy = self.root / "legacy"
        legacy.mkdir()
        _, owner = self.service._identity("customer-a", self.session_a, self.expiry)
        old_conversation = str(uuid.uuid4())
        with closing(sqlite3.connect(legacy / "frontend-chat.sqlite3")) as db:
            db.execute("""CREATE TABLE chat_sessions (session_id TEXT PRIMARY KEY, owner TEXT NOT NULL,
                expires INTEGER NOT NULL, conversation_id TEXT, revoked INTEGER NOT NULL DEFAULT 0,
                active_id TEXT, active_until INTEGER NOT NULL DEFAULT 0)""")
            db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)",
                       (self.session_a, owner, self.expiry, old_conversation, 0, "legacy-job", self.expiry))
            db.commit()
        migrated = ChatService(self.config, legacy)
        self.assertEqual(migrated.history("customer-a", self.session_a, self.expiry)["messages"], [])
        self.assertFalse(migrated.history("customer-a", self.session_a, self.expiry)["active"])
        migrated._transport = httpx.MockTransport(self.respond)
        await migrated.send("customer-a", self.session_a, self.expiry, "Una conversación visible")
        self.assertNotIn("conversationId", self.requests[-1][1]["metadata"])
        restored = ChatService(self.config, legacy)
        self.assertEqual(len(restored.history("customer-a", self.session_a, self.expiry)["messages"]), 2)
        restored._transport = httpx.MockTransport(self.respond)
        await restored.send("customer-a", self.session_a, self.expiry, "Continúa")
        self.assertNotEqual(self.requests[-1][1]["metadata"]["conversationId"], old_conversation)
        self.assertEqual(len(restored.history("customer-a", self.session_a, self.expiry)["messages"]), 4)

    async def test_public_selection_schema_rejects_private_fields_and_invalid_amount(self):
        self.service._transport = httpx.MockTransport(self.respond)
        selection = {"reference": "txn_" + "a" * 24, "occurred_at": "2026-06-17T12:00:00",
                     "type": "Purchase", "amount": 42.50, "currency": "COP", "status": "Approved"}
        for invalid in [{**selection, "customer_id": "private-customer"}, {**selection, "amount": float("nan")},
                        {**selection, "reference": "upstream-handle"}]:
            with self.assertRaises(ChatError) as caught:
                await self.service.send("customer-a", self.session_a, self.expiry, "Hola", selection=invalid)
            self.assertEqual(caught.exception.code, "invalid_selection")
        self.assertEqual(self.requests, [])

    async def test_transcript_pair_and_conversation_roll_back_together_on_storage_failure(self):
        self.service._transport = httpx.MockTransport(self.respond)
        with self.service._connection() as db:
            db.execute("""CREATE TRIGGER reject_assistant BEFORE INSERT ON chat_messages
                WHEN NEW.role='assistant' BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        history = self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(history["messages"], [])
        self.assertFalse(history["active"])
        with self.service._connection() as db:
            conversation = db.execute("SELECT conversation_id FROM chat_sessions WHERE session_id=?",
                                      (self.session_a,)).fetchone()[0]
        self.assertIsNone(conversation)

    async def test_history_rechecks_expiry_after_storage_read(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Hola")
        with patch("frontend.server.chat.time.time", side_effect=[self.expiry - 1, self.expiry]):
            with self.assertRaises(ChatError) as caught:
                self.service.history("customer-a", self.session_a, self.expiry)
        self.assertEqual(caught.exception.code, "session_expired")


if __name__ == "__main__":
    unittest.main()
