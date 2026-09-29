"""Meaningful boundary tests for the customer-scoped FLUJO adapter."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
import uuid

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from frontend.server.chat import ChatError, ChatService


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


if __name__ == "__main__":
    unittest.main()
