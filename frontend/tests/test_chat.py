"""Meaningful boundary tests for the customer-scoped FLUJO adapter."""
from __future__ import annotations

import asyncio
from contextlib import closing
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

from frontend.server.chat import ChatError, ChatService
from frontend.server.action import render_action


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
                    "pending_handle": "a" * 43, "message": "server result"})
            return self.respond(request)
        enabled._transport = httpx.MockTransport(respond)
        await enabled.send("customer-a", self.session_a, self.expiry, "No reconozco el cargo")
        result = await enabled.action("customer-a", self.session_a, self.expiry,
                                      {"operation": "prepare", "transactionId": "TXN00000001",
                                       "snapshot": "synthetic-build"})
        self.assertEqual(result["state"], "pending_confirmation")
        self.assertNotEqual(self.claims(seen[0])["jti"], self.claims(seen[1])["jti"])
        self.assertEqual(self.claims(seen[1])["sub"], "subject-a")
        with self.assertRaises(ChatError) as foreign:
            await enabled.action("customer-b", self.session_a, self.expiry,
                                 {"operation": "prepare", "transactionId": "TXN00000001",
                                  "snapshot": "synthetic-build"})
        self.assertEqual(foreign.exception.code, "session_mismatch")

    def test_es_pt_fallback_requires_verified_persisted_ids(self):
        handoff = {"state": "handoff_verified", "handoff": {"id": "HOF-" + "a" * 8}}
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
