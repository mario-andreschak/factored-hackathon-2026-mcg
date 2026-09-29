"""Durable FLUJO revoke delivery, including lost acknowledgements and in-flight work."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

from frontend.server.chat import ChatError, ChatService
from frontend.server.app import COOKIE, create_app
from frontend.server.state import State
from frontend.tests.test_api import invite_settings, login, settings as dataset_settings


class RevocationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.signer = Ed25519PrivateKey.generate()
        key_file = self.root / "signer.pem"
        key_file.write_bytes(self.signer.private_bytes(serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        self.config = {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
            "execution_token": "server-only-execution-token", "frontend_signing_key_file": str(key_file),
            "frontend_kid": "approved-front", "frontend_issuer": "approved-frontend",
            "frontend_audience": "flujo-banking-ingress", "principal_customers": {"subject-a": "customer-a"}}
        self.service = ChatService(self.config, self.root)
        self.session = str(uuid.uuid4())
        self.expiry = int(time.time()) + 3600

    def tearDown(self):
        self.directory.cleanup()

    def claims(self, request):
        return jwt.decode(request.headers["X-Flujo-User-Assertion"], self.signer.public_key(),
            algorithms=["EdDSA"], issuer="approved-frontend", audience="flujo-banking-ingress")

    def force_due(self):
        with self.service._connection() as db:
            db.execute("UPDATE pending_revocations SET next_attempt_at=0 WHERE session_id=?", (self.session,))

    async def test_failed_delivery_persists_and_retries_after_restart_with_fresh_assertion(self):
        attempts = []
        delivered = asyncio.Event()

        def worker(request):
            attempts.append(request)
            if len(attempts) == 1:
                return httpx.Response(503, json={"private": self.config["execution_token"]})
            delivered.set()
            return httpx.Response(200, json={"revoked": True})

        self.service._transport = httpx.MockTransport(worker)
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
        self.assertEqual(self.service.revocation_diagnostics()["pending"], 1)
        with self.assertRaises(ChatError) as denied:
            await self.service.send("customer-a", self.session, self.expiry, "Hola")
        self.assertEqual(denied.exception.code, "session_expired")

        restarted = ChatService(self.config, self.root)
        restarted._transport = httpx.MockTransport(worker)
        stop = asyncio.Event()
        retry = asyncio.create_task(restarted.retry_pending_loop(stop, poll_seconds=0.05))
        try:
            await asyncio.wait_for(delivered.wait(), timeout=5)
            for _ in range(20):
                if restarted.revocation_diagnostics()["confirmed"] == 1:
                    break
                await asyncio.sleep(0.01)
        finally:
            stop.set()
            await retry
        diagnostics = restarted.revocation_diagnostics()
        self.assertEqual((diagnostics["pending"], diagnostics["confirmed"]), (0, 1))
        self.assertEqual(diagnostics["retrying"], 0)
        self.assertEqual(len(attempts), 2)
        first, second = [self.claims(request) for request in attempts]
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertEqual(first["sub"], second["sub"])
        self.assertNotEqual(first["jti"], second["jti"])
        self.assertEqual({request.url.path for request in attempts}, {"/v1/banking/session/revoke"})
        exposed = str(diagnostics)
        for private in [self.session, "subject-a", "customer-a", self.config["execution_token"]]:
            self.assertNotIn(private, exposed)

    async def test_lost_success_response_retries_idempotently(self):
        worker_revocations = set()
        requests = []

        def worker(request):
            requests.append(request)
            identity = (self.claims(request)["sub"], self.claims(request)["session_id"])
            worker_revocations.add(identity)
            if len(requests) == 1:
                raise httpx.ReadTimeout("acknowledgement lost")
            return httpx.Response(200, json={"revoked": True})

        self.service._transport = httpx.MockTransport(worker)
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
        self.assertEqual(len(worker_revocations), 1)
        self.force_due()
        self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
        self.assertEqual(len(worker_revocations), 1)
        self.assertNotEqual(self.claims(requests[0])["jti"], self.claims(requests[1])["jti"])
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "confirmed")
        self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
        self.assertEqual(len(requests), 2)

    async def test_failed_revoke_of_admitted_chat_still_suppresses_reply_then_recovers(self):
        admitted = asyncio.Event()
        release = asyncio.Event()
        revoke_attempts = 0

        async def worker(request):
            nonlocal revoke_attempts
            if request.url.path.endswith("revoke"):
                revoke_attempts += 1
                return httpx.Response(503 if revoke_attempts == 1 else 200,
                                      json={"revoked": True} if revoke_attempts > 1 else {})
            admitted.set()
            await release.wait()
            return httpx.Response(200, json={"conversation_id": str(uuid.uuid4()), "status": "completed",
                "choices": [{"message": {"role": "assistant", "content": "Late private reply"}}]})

        self.service._transport = httpx.MockTransport(worker)
        pending_chat = asyncio.create_task(self.service.send("customer-a", self.session, self.expiry, "Hola"))
        await asyncio.wait_for(admitted.wait(), timeout=2)
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
        release.set()
        with self.assertRaises(ChatError) as denied:
            await pending_chat
        self.assertEqual(denied.exception.code, "session_expired")
        with self.assertRaises(ChatError):
            self.service.history("customer-a", self.session, self.expiry)
        self.force_due()
        self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
        self.assertEqual(revoke_attempts, 2)
        with self.service._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)

    async def test_expiry_is_operator_visible_and_never_misreported_as_confirmed(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        with patch("frontend.server.chat.time.time", return_value=self.expiry + 1):
            self.assertEqual(await self.service.attempt_revoke(self.session), "expired_unconfirmed")
            diagnostics = self.service.revocation_diagnostics()
        self.assertEqual(diagnostics["pending"], 0)
        self.assertEqual(diagnostics["confirmed"], 0)
        self.assertEqual(diagnostics["expired_unconfirmed"], 1)
        self.assertEqual(diagnostics["last_error_code"], "revoke_session_expired")

    async def test_queue_storage_failure_rolls_back_local_marker_and_intent(self):
        with self.service._connection() as db:
            db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
                BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.queue_revoke("customer-a", self.session, self.expiry)
        with self.service._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0], 0)

    async def test_concurrent_attempts_share_a_lease_and_send_once(self):
        started = asyncio.Event()
        release = asyncio.Event()
        requests = []

        async def worker(request):
            requests.append(request)
            started.set()
            await release.wait()
            return httpx.Response(200, json={"revoked": True})

        self.service._transport = httpx.MockTransport(worker)
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        first = asyncio.create_task(self.service.attempt_revoke(self.session))
        await asyncio.wait_for(started.wait(), timeout=2)
        self.assertEqual(await ChatService(self.config, self.root).attempt_revoke(self.session), "pending")
        release.set()
        self.assertEqual(await first, "confirmed")
        self.assertEqual(len(requests), 1)

    async def test_late_exact_acknowledgement_overrides_expired_lease(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        claimed = self.service._claim_revoke(self.session)
        self.assertIsInstance(claimed, tuple)
        _, lease = claimed
        with self.service._connection() as db:
            db.execute("""UPDATE pending_revocations SET lease_token='new-lease',lease_until=0,
                state='expired_unconfirmed' WHERE session_id=?""", (self.session,))
        self.assertEqual(self.service._finish_revoke(self.session, lease, confirmed=True), "confirmed")
        self.assertEqual(self.service.revocation_diagnostics()["confirmed"], 1)

    async def test_legacy_local_revoked_marker_is_reenqueued_safely(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        with self.service._connection() as db:
            db.execute("DELETE FROM pending_revocations")
        restored = ChatService(self.config, self.root)
        self.assertEqual(restored.revocation_diagnostics()["pending"], 1)
        restored._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"revoked": True}))
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")

    async def test_reordered_approved_subjects_preserve_existing_session_revoke(self):
        def chat_reply(_):
            return httpx.Response(200, json={"conversation_id": str(uuid.uuid4()), "status": "completed",
                "choices": [{"message": {"role": "assistant", "content": "Visible reply"}}]})

        self.service._transport = httpx.MockTransport(chat_reply)
        await self.service.send("customer-a", self.session, self.expiry, "Hola")
        reordered = {**self.config, "principal_customers": {
            "subject-new": "customer-a", "subject-a": "customer-a"}}
        restarted = ChatService(reordered, self.root)
        self.assertEqual(len(restarted.history("customer-a", self.session, self.expiry)["messages"]), 2)
        requests = []

        def worker(request):
            requests.append(request)
            return httpx.Response(200, json={"revoked": True})

        restarted._transport = httpx.MockTransport(worker)
        self.assertEqual(restarted.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await restarted.attempt_revoke(self.session), "confirmed")
        self.assertEqual(self.claims(requests[0])["sub"], "subject-a")

    async def test_missing_configuration_keeps_queue_visible_until_restored(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        disabled = ChatService({}, self.root)
        self.assertFalse(disabled.revocation_diagnostics()["configured"])
        self.assertEqual(disabled.revocation_diagnostics()["pending"], 1)
        self.assertEqual(await disabled.attempt_revoke(self.session), "pending")
        self.assertEqual(disabled.revocation_diagnostics()["last_error_code"],
                         "revoke_configuration_unavailable")
        restored = ChatService(self.config, self.root)
        restored._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"revoked": True}))
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")

    async def test_admitted_work_can_be_revoked_during_config_loss_and_retried_after_restore(self):
        admitted = asyncio.Event()
        release = asyncio.Event()

        async def worker(request):
            admitted.set()
            await release.wait()
            return httpx.Response(200, json={"conversation_id": str(uuid.uuid4()), "status": "completed",
                "choices": [{"message": {"role": "assistant", "content": "Late reply"}}]})

        self.service._transport = httpx.MockTransport(worker)
        in_flight = asyncio.create_task(self.service.send("customer-a", self.session, self.expiry, "Hola"))
        await asyncio.wait_for(admitted.wait(), timeout=2)
        with self.service._connection() as db:
            stored = db.execute("SELECT subject,customer_id FROM chat_sessions WHERE session_id=?",
                                (self.session,)).fetchone()
        self.assertEqual(tuple(stored), ("subject-a", "customer-a"))

        no_config = ChatService({}, self.root)
        self.assertTrue(no_config.has_active_session(self.session, self.expiry))
        self.assertEqual(no_config.admitted_customer(self.session, self.expiry), "customer-a")
        self.assertEqual(no_config.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertFalse(no_config.has_active_session(self.session, self.expiry))
        self.assertIsNone(no_config.admitted_customer(self.session, self.expiry))
        self.assertEqual(await no_config.attempt_revoke(self.session), "pending")
        self.assertEqual(no_config.revocation_diagnostics()["last_error_code"],
                         "revoke_configuration_unavailable")
        release.set()
        with self.assertRaises(ChatError) as denied:
            await in_flight
        self.assertEqual(denied.exception.code, "session_expired")

        restored = ChatService(self.config, self.root)
        requests = []

        def revoke_worker(request):
            requests.append(request)
            return httpx.Response(200, json={"revoked": True})

        restored._transport = httpx.MockTransport(revoke_worker)
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")
        self.assertEqual(self.claims(requests[0])["sub"], "subject-a")
        self.assertEqual(restored.revocation_diagnostics()["pending"], 0)

    async def test_preupgrade_owner_only_marker_is_visible_then_resolved_after_config_restore(self):
        _, owner = self.service._identity("customer-a", self.session, self.expiry)
        with self.service._connection() as db:
            db.execute("INSERT INTO chat_sessions(session_id,owner,expires) VALUES (?,?,?)",
                       (self.session, owner, self.expiry))
        no_config = ChatService({}, self.root)
        self.assertEqual(no_config.queue_revoke("customer-a", self.session, self.expiry), "unresolved")
        diagnostics = no_config.revocation_diagnostics()
        self.assertEqual((diagnostics["unresolved"], diagnostics["pending"]), (1, 0))
        with patch("frontend.server.chat.time.time", return_value=self.expiry + 1):
            expired = no_config.revocation_diagnostics()
        self.assertEqual((expired["unresolved"], expired["legacy_expired_unknown"]), (0, 1))
        restored = ChatService(self.config, self.root)
        diagnostics = restored.revocation_diagnostics()
        self.assertEqual((diagnostics["unresolved"], diagnostics["pending"]), (0, 1))
        restored._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"revoked": True}))
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")

    async def test_subject_reassignment_cannot_revoke_under_a_different_customer(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        reassigned = ChatService({**self.config, "principal_customers": {
            "subject-a": "customer-b"}}, self.root)
        requests = []
        reassigned._transport = httpx.MockTransport(lambda request: requests.append(request) or
                                                    httpx.Response(200, json={"revoked": True}))
        self.assertEqual(await reassigned.attempt_revoke(self.session), "pending")
        self.assertEqual(requests, [])
        self.assertEqual(reassigned.revocation_diagnostics()["last_error_code"],
                         "revoke_configuration_unavailable")
        restored = ChatService(self.config, self.root)
        restored._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"revoked": True}))
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")


def _api_with_chat(dataset_settings, tmp_path):
    signer = Ed25519PrivateKey.generate()
    key_file = tmp_path / "api-signer.pem"
    key_file.write_bytes(signer.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    chat = {"base_url": "http://flujo:4200", "model": "flow-Banking_Customer",
        "execution_token": "server-only-execution-token", "frontend_signing_key_file": str(key_file),
        "frontend_kid": "approved-front", "frontend_issuer": "approved-frontend",
        "frontend_audience": "flujo-banking-ingress",
        "principal_customers": {"subject-a": "private-customer-co"}}
    return replace(dataset_settings, chat=chat)


def test_api_logout_reports_durable_pending_and_deletes_browser_session(dataset_settings, tmp_path):
    with TestClient(create_app(_api_with_chat(dataset_settings, tmp_path))) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        service = client.app.state.chat_service
        service._transport = httpx.MockTransport(lambda _: httpx.Response(503, json={}))
        response = client.post("/api/auth/logout", json={})
        assert response.status_code == 204
        assert response.headers["X-Banking-Revoke"] == "pending"
        assert client.cookies.get(COOKIE) is None
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/healthz").json()["chat_revocations"]["pending"] == 1
        with service._connection() as db:
            marker = db.execute("""SELECT s.revoked,p.state FROM chat_sessions s
                JOIN pending_revocations p USING(session_id)""").fetchone()
        assert tuple(marker) == (1, "pending")


def test_api_logout_storage_failure_is_explicit_and_still_revokes_cookie(dataset_settings, tmp_path):
    with TestClient(create_app(_api_with_chat(dataset_settings, tmp_path))) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        service = client.app.state.chat_service
        with service._connection() as db:
            db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
                BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        response = client.post("/api/auth/logout", json={})
        assert response.status_code == 503
        assert response.headers["X-Banking-Revoke"] == "persist_failed"
        assert client.cookies.get(COOKIE) is None
        assert client.get("/api/auth/me").status_code == 401
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        with service._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0] == 0


def _admit_api_session(configured_settings):
    with TestClient(create_app(configured_settings)) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        service = client.app.state.chat_service
        service._transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
            "conversation_id": str(uuid.uuid4()), "status": "completed",
            "choices": [{"message": {"role": "assistant", "content": "Visible reply"}}]}))
        assert client.post("/api/chat/messages", json={"message": "Hola"}).status_code == 200
        current = client.app.state.bank_state.session(cookie)
        assert service.has_active_session(current.id, current.expires_at)
    return cookie, current


def test_auth_rotation_without_signer_queues_but_fails_before_deleting_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    # A normal restart has no policy delta and must preserve the chat binding.
    with TestClient(create_app(configured)) as same_policy:
        same_policy.cookies.set(COOKIE, cookie)
        assert same_policy.get("/api/auth/me").status_code == 200
        assert same_policy.app.state.chat_service.has_active_session(current.id, current.expires_at)
        assert same_policy.get("/healthz").json()["chat_revocations"]["pending"] == 0

    # A reused invite volume cannot sign revocation. Preserve the old bank
    # session, record the intent, and require an isolated volume or old signer.
    invite = invite_settings(dataset_settings)
    with pytest.raises(RuntimeError):
        with TestClient(create_app(invite)):
            pass
    assert State(configured.state_dir).session(cookie) == current
    service = ChatService({}, configured.state_dir)
    diagnostics = service.revocation_diagnostics()
    assert diagnostics["pending"] == 1 and diagnostics["confirmed"] == 0
    with service._connection() as db:
        row = db.execute("""SELECT s.revoked,p.state,p.subject FROM chat_sessions s
            JOIN pending_revocations p USING(session_id) WHERE s.session_id=?""",
            (current.id,)).fetchone()
    assert tuple(row) == (1, "pending", "subject-a")


def test_configured_demo_code_rotation_queues_and_removes_old_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    rotated = replace(configured, demo_code="new-private-demo-code")

    async def worker_unavailable(_self, path, _headers, _payload, **_kwargs):
        assert path == "/v1/banking/session/revoke"
        return {"revoked": False}

    with patch.object(ChatService, "_post", worker_unavailable):
        with TestClient(create_app(rotated)) as client:
            client.cookies.set(COOKIE, cookie)
            assert client.get("/api/auth/me").status_code == 401
            assert client.app.state.chat_service.has_active_session(current.id, current.expires_at) is False
            assert client.get("/healthz").json()["chat_revocations"]["pending"] == 1
            assert client.post("/api/auth/login", json={"profile": "colombia", "code": "new-private-demo-code"}).status_code == 200
    assert State(configured.state_dir).session(cookie) is None


def test_auth_rotation_queue_failure_aborts_startup_before_deleting_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    service = ChatService(configured.chat, configured.state_dir)
    with service._connection() as db:
        db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
            BEGIN SELECT RAISE(ABORT,'fixture queue failure'); END""")
    invite = invite_settings(dataset_settings)
    with pytest.raises(sqlite3.IntegrityError):
        with TestClient(create_app(invite)):
            pass
    # The auth policy cannot silently clear an admitted worker session when
    # the durable queue is unavailable.
    assert State(configured.state_dir).session(cookie) == current
    with service._connection() as db:
        row = db.execute("SELECT revoked FROM chat_sessions WHERE session_id=?", (current.id,)).fetchone()
        assert row[0] == 0
        assert db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0] == 0


def test_invite_preview_rejects_prior_chat_volume_even_without_active_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    State(configured.state_dir).delete_session(current)
    assert State(configured.state_dir).session(cookie) is None
    assert ChatService({}, configured.state_dir).has_any_session()
    invite = invite_settings(dataset_settings)
    with pytest.raises(RuntimeError):
        with TestClient(create_app(invite)):
            pass


if __name__ == "__main__":
    unittest.main()
