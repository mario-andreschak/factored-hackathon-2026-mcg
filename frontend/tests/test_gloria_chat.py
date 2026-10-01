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

from frontend.server.gloria_chat import ChatError, GloriaChatService as ChatService
from frontend.server.chat import ChatService as DirectChatService
from frontend.tests.direct_host_fixtures import make_direct_config
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


class GloriaChatIdentityTests(unittest.IsolatedAsyncioTestCase):
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

    def database_dump(self, directory):
        with closing(sqlite3.connect(directory / "frontend-chat.sqlite3")) as db:
            return tuple(db.iterdump())

    async def test_direct_service_cannot_reinterpret_retained_gloria_admission(self):
        self.service._transport = httpx.MockTransport(self.respond)
        await self.service.send("customer-a", self.session_a, self.expiry, "Consulta el movimiento")
        before = self.database_dump(self.root)
        direct_config = make_direct_config(self.root / "direct-config")
        with self.assertRaisesRegex(RuntimeError, "Legacy worker-bound state"):
            DirectChatService(direct_config, self.root)
        self.assertEqual(self.database_dump(self.root), before)

    async def test_gloria_service_cannot_reinterpret_direct_ledger_authority(self):
        directory = self.root / "direct-state"
        DirectChatService(make_direct_config(self.root / "direct-config"), directory)
        before = self.database_dump(directory)
        with self.assertRaisesRegex(RuntimeError, "isolated Gloria state"):
            ChatService(self.config, directory)
        self.assertEqual(self.database_dump(directory), before)

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


def test_gloria_auth_fingerprint_pins_ledger_without_rotating_for_model_changes(tmp_path):
    from dataclasses import replace
    from frontend.server.config import Settings

    config = {"mode": "gloria-host/v1", "ledger_generation": "a" * 64, "model": "flow-Gloria"}
    settings = Settings(data_dir=tmp_path, state_dir=tmp_path / "state", static_dir=tmp_path / "static", chat=config)
    current = settings.auth_fingerprint()
    changed_ledger = replace(settings, chat={**config, "ledger_generation": "b" * 64})
    changed_model = replace(settings, chat={**config, "model": "flow-OtherLanguageContext"})
    assert changed_ledger.auth_fingerprint() != current
    assert changed_model.auth_fingerprint() == current
