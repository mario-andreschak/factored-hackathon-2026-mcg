"""Durable direct-bank revocation and local denial, with isolated recording fakes."""
from __future__ import annotations

import asyncio
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

import pytest
from fastapi.testclient import TestClient

from frontend.server.bank_rpc import BankRPCError
from frontend.server.chat import ChatError, ChatService
from frontend.server.app import COOKIE, create_app
from frontend.server.language import LanguageResult
from frontend.server.state import State
from frontend.tests.direct_host_fixtures import (
    RecordingBank, RecordingLanguage, attach_direct_fakes, make_direct_config,
)
from frontend.tests.test_api import invite_settings, login, settings as dataset_settings


class RevocationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.config = make_direct_config(self.root / "generated-authority")
        self.bank, self.language = RecordingBank(), RecordingLanguage()
        self.service = self.make_service()
        self.session = str(uuid.uuid4())
        self.expiry = int(time.time()) + 3600

    def tearDown(self):
        self.directory.cleanup()

    def make_service(self, config=None):
        service = ChatService(self.config if config is None else config, self.root)
        attach_direct_fakes(service, bank=self.bank, language=self.language)
        return service

    def force_due(self):
        with self.service._connection() as db:
            db.execute("UPDATE pending_revocations SET next_attempt_at=0 WHERE session_id=?", (self.session,))

    def queue_row(self):
        with self.service._connection() as db:
            return dict(db.execute("SELECT * FROM pending_revocations WHERE session_id=?", (self.session,)).fetchone())

    async def test_failed_delivery_persists_and_retries_after_restart_with_fresh_host_operation(self):
        delivered = asyncio.Event()
        async def bank_revoke(context):
            if len(self.bank.revocations) == 1:
                raise BankRPCError("bank_http_error", possibly_sent=True)
            delivered.set()
        self.bank.revoke_handler = bank_revoke
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
        self.assertEqual(self.service.revocation_diagnostics()["pending"], 1)
        with self.assertRaises(ChatError) as denied:
            await self.service.send("customer-a", self.session, self.expiry, "Hola")
        self.assertEqual(denied.exception.code, "session_expired")
        restarted = self.make_service()
        self.force_due()
        stop = asyncio.Event()
        retry = asyncio.create_task(restarted.retry_pending_loop(stop, poll_seconds=0.05))
        try:
            await asyncio.wait_for(delivered.wait(), 10)
        finally:
            stop.set()
            await asyncio.wait_for(retry, 10)
        diagnostics = restarted.revocation_diagnostics()
        self.assertEqual((diagnostics["pending"], diagnostics["confirmed"], diagnostics["retrying"]), (0, 1, 0))
        self.assertEqual(len(self.bank.revocations), 2)
        first, second = self.bank.revocations
        self.assertEqual((first.subject, first.session_id, first.conversation_id, first.session_expires),
                         (second.subject, second.session_id, second.conversation_id, second.session_expires))
        self.assertNotEqual(first.operation_id, second.operation_id)
        self.assertNotEqual(first.session_id, self.session)
        self.assertEqual(self.bank.calls, [])
        self.assertEqual(self.language.calls, [])
        for private in (self.session, "subject-a", "customer-a", self.config["bank"]["service_token"]):
            self.assertNotIn(private, str(diagnostics))

    async def test_lost_success_response_retries_idempotently(self):
        bank_revocations = set()
        async def bank_revoke(context):
            bank_revocations.add((context.subject, context.session_id))
            if len(self.bank.revocations) == 1:
                raise BankRPCError("bank_timeout", possibly_sent=True)
        self.bank.revoke_handler = bank_revoke
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
        self.assertEqual(len(bank_revocations), 1)
        self.force_due()
        self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
        self.assertEqual(len(bank_revocations), 1)
        self.assertNotEqual(self.bank.revocations[0].operation_id, self.bank.revocations[1].operation_id)
        self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "confirmed")
        self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
        self.assertEqual(len(self.bank.revocations), 2)

    async def test_failed_revoke_of_admitted_chat_still_suppresses_reply_then_recovers(self):
        admitted, release = asyncio.Event(), asyncio.Event()
        async def delayed_language(text, language, facts, conversation):
            admitted.set()
            await release.wait()
            return LanguageResult("Late private reply", "ask_selection", conversation, True)
        async def bank_revoke(context):
            if len(self.bank.revocations) == 1:
                raise BankRPCError("bank_http_error", possibly_sent=True)
        self.language.handler, self.bank.revoke_handler = delayed_language, bank_revoke
        pending = asyncio.create_task(self.service.send("customer-a", self.session, self.expiry, "Hola"))
        try:
            await asyncio.wait_for(admitted.wait(), 10)
            self.assertEqual(self.service.queue_revoke("customer-a", self.session, self.expiry), "pending")
            self.assertEqual(await self.service.attempt_revoke(self.session), "pending")
            release.set()
            with self.assertRaises(ChatError) as denied:
                await asyncio.wait_for(pending, 10)
            self.assertEqual(denied.exception.code, "session_expired")
            with self.assertRaises(ChatError):
                self.service.history("customer-a", self.session, self.expiry)
            self.force_due()
            self.assertEqual(await self.service.attempt_revoke(self.session), "confirmed")
            self.assertEqual(len(self.bank.revocations), 2)
            with self.service._connection() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0], 0)
        finally:
            release.set()
            if not pending.done():
                pending.cancel()
                await asyncio.gather(pending, return_exceptions=True)

    async def test_expiry_is_operator_visible_and_never_misreported_as_confirmed(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        expired = int(time.time()) - 1
        with self.service._connection() as db:
            db.execute("UPDATE pending_revocations SET expires=? WHERE session_id=?", (expired, self.session))
            db.execute("UPDATE chat_sessions SET expires=? WHERE session_id=?", (expired, self.session))
        self.assertEqual(await self.service.attempt_revoke(self.session), "expired_unconfirmed")
        diagnostics = self.service.revocation_diagnostics()
        self.assertEqual((diagnostics["pending"], diagnostics["confirmed"], diagnostics["expired_unconfirmed"]), (0, 0, 1))
        self.assertEqual(diagnostics["last_error_code"], "revoke_session_expired")
        self.assertEqual(self.bank.revocations, [])

    async def test_queue_storage_failure_rolls_back_local_marker_and_intent(self):
        with self.service._connection() as db:
            db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
                BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.queue_revoke("customer-a", self.session, self.expiry)
        with self.service._connection() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0], 0)
        self.assertEqual(self.bank.revocations, [])

    async def test_concurrent_attempts_share_a_lease_and_send_once(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def bank_revoke(context):
            started.set()
            await release.wait()
        self.bank.revoke_handler = bank_revoke
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        first = asyncio.create_task(self.service.attempt_revoke(self.session))
        try:
            await asyncio.wait_for(started.wait(), 10)
            self.assertEqual(await self.make_service().attempt_revoke(self.session), "pending")
            release.set()
            self.assertEqual(await asyncio.wait_for(first, 10), "confirmed")
            self.assertEqual(len(self.bank.revocations), 1)
        finally:
            release.set()
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)

    async def test_late_exact_acknowledgement_overrides_expired_lease(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def bank_revoke(context):
            started.set()
            await release.wait()
        self.bank.revoke_handler = bank_revoke
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        delivery = asyncio.create_task(self.service.attempt_revoke(self.session))
        try:
            await asyncio.wait_for(started.wait(), 10)
            with self.service._connection() as db:
                db.execute("""UPDATE pending_revocations SET lease_token='new-lease',lease_until=0,
                    state='expired_unconfirmed' WHERE session_id=?""", (self.session,))
            release.set()
            self.assertEqual(await asyncio.wait_for(delivery, 10), "confirmed")
            self.assertEqual(self.service.revocation_diagnostics()["confirmed"], 1)
            self.assertEqual(len(self.bank.revocations), 1)
        finally:
            release.set()
            if not delivery.done():
                delivery.cancel()
                await asyncio.gather(delivery, return_exceptions=True)

    async def test_direct_host_revoked_marker_is_reenqueued_safely(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        with self.service._connection() as db:
            db.execute("DELETE FROM pending_revocations")
        restored = self.make_service()
        self.assertEqual(restored.revocation_diagnostics()["pending"], 1)
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")
        self.assertEqual(self.bank.revocations[0].subject, "subject-a")

    async def test_reordered_approved_subjects_and_language_flow_preserve_bank_revoke(self):
        await self.service.send("customer-a", self.session, self.expiry, "Hola")
        with self.service._connection() as db:
            old = dict(db.execute("SELECT * FROM chat_sessions WHERE session_id=?", (self.session,)).fetchone())
        reordered = deepcopy(self.config)
        reordered["principal_customers"] = dict(reversed(list(self.config["principal_customers"].items())))
        reordered["language"]["flow_id"] = str(uuid.uuid4())
        restarted = self.make_service(reordered)
        self.assertEqual(len(restarted.history("customer-a", self.session, self.expiry)["messages"]), 2)
        self.assertEqual(restarted.queue_revoke("customer-a", self.session, self.expiry), "pending")
        self.assertEqual(await restarted.attempt_revoke(self.session), "confirmed")
        self.assertEqual(self.bank.revocations[0].subject, "subject-a")
        self.assertEqual(self.bank.revocations[0].conversation_id, old["bank_context_id"])
        self.assertEqual(len(self.language.calls), 1)

    async def test_missing_configuration_keeps_queue_visible_until_restored(self):
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        disabled = self.make_service({})
        self.assertFalse(disabled.revocation_diagnostics()["configured"])
        self.assertEqual(disabled.revocation_diagnostics()["pending"], 1)
        self.assertEqual(await disabled.attempt_revoke(self.session), "pending")
        self.assertEqual(disabled.revocation_diagnostics()["last_error_code"], "revoke_configuration_unavailable")
        restored = self.make_service()
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")

    async def test_admitted_work_can_be_revoked_during_config_loss_and_retried_after_restore(self):
        admitted, release = asyncio.Event(), asyncio.Event()
        async def delayed_language(text, language, facts, conversation):
            admitted.set()
            await release.wait()
            return LanguageResult("Late reply", "ask_selection", conversation, True)
        self.language.handler = delayed_language
        in_flight = asyncio.create_task(self.service.send("customer-a", self.session, self.expiry, "Hola"))
        try:
            await asyncio.wait_for(admitted.wait(), 10)
            with self.service._connection() as db:
                row = db.execute("SELECT subject,customer_id FROM chat_sessions WHERE session_id=?", (self.session,)).fetchone()
            self.assertEqual(tuple(row), ("subject-a", "customer-a"))
            no_config = self.make_service({})
            self.assertTrue(no_config.has_active_session(self.session, self.expiry))
            self.assertEqual(no_config.admitted_customer(self.session, self.expiry), "customer-a")
            self.assertEqual(no_config.queue_revoke("customer-a", self.session, self.expiry), "pending")
            self.assertFalse(no_config.has_active_session(self.session, self.expiry))
            self.assertIsNone(no_config.admitted_customer(self.session, self.expiry))
            self.assertEqual(await no_config.attempt_revoke(self.session), "pending")
            self.assertEqual(no_config.revocation_diagnostics()["last_error_code"], "revoke_configuration_unavailable")
            release.set()
            with self.assertRaises(ChatError) as denied:
                await asyncio.wait_for(in_flight, 10)
            self.assertEqual(denied.exception.code, "session_expired")
            restored = self.make_service()
            self.force_due()
            self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")
            self.assertEqual(self.bank.revocations[0].subject, "subject-a")
            self.assertEqual(restored.revocation_diagnostics()["pending"], 0)
        finally:
            release.set()
            if not in_flight.done():
                in_flight.cancel()
                await asyncio.gather(in_flight, return_exceptions=True)

    async def test_preupgrade_worker_owner_only_state_is_rejected_without_transplant(self):
        legacy = self.root / "old-worker-state"
        legacy.mkdir()
        path = legacy / "frontend-chat.sqlite3"
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE chat_sessions (session_id TEXT,owner TEXT,expires INTEGER,revoked INTEGER)")
            db.execute("INSERT INTO chat_sessions VALUES (?,?,?,1)", (self.session, "old-worker-owner", self.expiry))
            db.commit()
        before = path.read_bytes()
        for config in ({}, self.config):
            with self.subTest(configured=bool(config)):
                with self.assertRaisesRegex(RuntimeError, "Legacy worker-bound state"):
                    ChatService(config, legacy)
                self.assertEqual(path.read_bytes(), before)
        with closing(sqlite3.connect(path)) as db:
            self.assertEqual(db.execute("SELECT * FROM chat_sessions").fetchall(), [(self.session, "old-worker-owner", self.expiry, 1)])
            self.assertEqual(db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall(), [("chat_sessions",)])
        self.assertEqual(self.bank.revocations, [])

    async def test_changed_bank_authority_rejects_reuse_until_original_policy_returns(self):
        await self.service.send("customer-a", self.session, self.expiry, "Hola")
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        original = self.queue_row()
        other = make_direct_config(self.root / "different-generated-authority")
        variants = {}
        for field, value in (("issuer", "different-bank-host"), ("base_url", "https://banking-mcp:8443"),
                             ("ca_file", other["bank"]["ca_file"])):
            changed = deepcopy(self.config)
            changed["bank"][field] = value
            variants[field] = changed
        changed = deepcopy(self.config)
        changed["namespace"] = "different-bank-namespace"
        variants["namespace"] = changed
        changed = deepcopy(self.config)
        changed["principal_customers"]["subject-a"] = "customer-b"
        variants["customer"] = changed
        for authority, changed in variants.items():
            with self.subTest(authority=authority):
                with self.assertRaisesRegex(RuntimeError, "Bank authority policy changed"):
                    ChatService(changed, self.root)
                self.assertEqual(self.queue_row(), original)
                self.assertEqual(self.bank.revocations, [])
        restored = self.make_service()
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")

    async def test_signer_key_or_kid_rotation_requires_reconciliation_before_old_revoke(self):
        await self.service.send("customer-a", self.session, self.expiry, "Hola")
        self.service.queue_revoke("customer-a", self.session, self.expiry)
        original = self.queue_row()
        other = make_direct_config(self.root / "rotated-generated-authority")
        for field, value in (("signing_key_file", other["bank"]["signing_key_file"]), ("kid", "rotated-bank-key")):
            changed = deepcopy(self.config)
            changed["bank"][field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(RuntimeError, "Bank authority policy changed"):
                    ChatService(changed, self.root)
                self.assertEqual(self.queue_row(), original)
                self.assertEqual(self.bank.revocations, [])
        restored = self.make_service()
        self.force_due()
        self.assertEqual(await restored.attempt_revoke(self.session), "confirmed")
        self.assertEqual(self.bank.revocations[0].subject, "subject-a")


def _api_with_chat(dataset_settings, tmp_path):
    chat = make_direct_config(tmp_path / "generated-api-authority", principal_customers={"subject-a": "private-customer-co"})
    return replace(dataset_settings, chat=chat)


@contextmanager
def _client_with_fakes(configured, *, bank=None, language=None):
    bank = bank if bank is not None else RecordingBank()
    language = language if language is not None else RecordingLanguage()
    def construct(config, state_dir):
        service = ChatService(config, state_dir)
        attach_direct_fakes(service, bank=bank, language=language)
        return service
    # Inject before lifespan startup so persisted retry work never reaches TLS
    # or an actual companion. This patches only the constructor test seam.
    with patch("frontend.server.chat.ChatService", side_effect=construct):
        with TestClient(create_app(configured)) as client:
            yield client


def test_api_logout_reports_durable_pending_and_deletes_browser_session(dataset_settings, tmp_path):
    bank = RecordingBank()
    async def unavailable(context):
        raise BankRPCError("bank_unreachable", possibly_sent=True)
    bank.revoke_handler = unavailable
    with _client_with_fakes(_api_with_chat(dataset_settings, tmp_path), bank=bank) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        service = client.app.state.chat_service
        response = client.post("/api/auth/logout", json={})
        assert response.status_code == 204 and response.headers["X-Banking-Revoke"] == "pending"
        assert client.cookies.get(COOKIE) is None and client.get("/api/auth/me").status_code == 401
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        assert client.get("/healthz").json()["chat_revocations"]["pending"] == 1
        with service._connection() as db:
            marker = db.execute("SELECT s.revoked,p.state FROM chat_sessions s JOIN pending_revocations p USING(session_id)").fetchone()
        assert tuple(marker) == (1, "pending")
        assert bank.calls == [] and bank.revocations


def test_api_logout_storage_failure_is_explicit_and_still_revokes_cookie(dataset_settings, tmp_path):
    bank = RecordingBank()
    with _client_with_fakes(_api_with_chat(dataset_settings, tmp_path), bank=bank) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        service = client.app.state.chat_service
        with service._connection() as db:
            db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
                BEGIN SELECT RAISE(ABORT,'fixture write failure'); END""")
        response = client.post("/api/auth/logout", json={})
        assert response.status_code == 503 and response.headers["X-Banking-Revoke"] == "persist_failed"
        assert client.cookies.get(COOKIE) is None and client.get("/api/auth/me").status_code == 401
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        with service._connection() as db:
            assert db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0] == 0
        assert bank.revocations == []


def _admit_api_session(configured):
    with _client_with_fakes(configured) as client:
        assert login(client).status_code == 200
        cookie = client.cookies.get(COOKIE)
        assert client.post("/api/chat/messages", json={"message": "Hola"}).status_code == 200
        current = client.app.state.bank_state.session(cookie)
        assert client.app.state.chat_service.has_active_session(current.id, current.expires_at)
    return cookie, current


def test_auth_rotation_without_signer_queues_but_fails_before_deleting_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    with _client_with_fakes(configured) as same_policy:
        same_policy.cookies.set(COOKIE, cookie)
        assert same_policy.get("/api/auth/me").status_code == 200
        assert same_policy.app.state.chat_service.has_active_session(current.id, current.expires_at)
        assert same_policy.get("/healthz").json()["chat_revocations"]["pending"] == 0
    with pytest.raises(RuntimeError):
        with _client_with_fakes(invite_settings(dataset_settings)):
            pass
    assert State(configured.state_dir).session(cookie) == current
    service = ChatService({}, configured.state_dir)
    diagnostics = service.revocation_diagnostics()
    assert diagnostics["pending"] == 1 and diagnostics["confirmed"] == 0
    with service._connection() as db:
        row = db.execute("SELECT s.revoked,p.state,p.subject FROM chat_sessions s JOIN pending_revocations p USING(session_id) WHERE s.session_id=?", (current.id,)).fetchone()
    assert tuple(row) == (1, "pending", "subject-a")


def test_configured_demo_code_rotation_queues_and_removes_old_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    bank = RecordingBank()
    async def unavailable(context):
        raise BankRPCError("bank_unreachable", possibly_sent=False)
    bank.revoke_handler = unavailable
    rotated = replace(configured, demo_code="new-private-demo-code")
    with _client_with_fakes(rotated, bank=bank) as client:
        client.cookies.set(COOKIE, cookie)
        assert client.get("/api/auth/me").status_code == 401
        assert client.app.state.chat_service.has_active_session(current.id, current.expires_at) is False
        assert client.get("/healthz").json()["chat_revocations"]["pending"] == 1
        assert client.post("/api/auth/login", json={"profile": "colombia", "code": "new-private-demo-code"}).status_code == 200
    assert State(configured.state_dir).session(cookie) is None
    assert bank.revocations and bank.calls == []


def test_auth_rotation_queue_failure_aborts_startup_before_deleting_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    service = ChatService(configured.chat, configured.state_dir)
    with service._connection() as db:
        db.execute("""CREATE TRIGGER reject_revoke BEFORE INSERT ON pending_revocations
            BEGIN SELECT RAISE(ABORT,'fixture queue failure'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        with _client_with_fakes(invite_settings(dataset_settings)):
            pass
    assert State(configured.state_dir).session(cookie) == current
    with service._connection() as db:
        row = db.execute("SELECT revoked FROM chat_sessions WHERE session_id=?", (current.id,)).fetchone()
        assert row[0] == 0 and db.execute("SELECT COUNT(*) FROM pending_revocations").fetchone()[0] == 0


def test_invite_preview_rejects_prior_chat_volume_even_without_active_cookie(dataset_settings, tmp_path):
    configured = _api_with_chat(dataset_settings, tmp_path)
    cookie, current = _admit_api_session(configured)
    State(configured.state_dir).delete_session(current)
    assert State(configured.state_dir).session(cookie) is None
    assert ChatService({}, configured.state_dir).has_any_session()
    with pytest.raises(RuntimeError):
        with _client_with_fakes(invite_settings(dataset_settings)):
            pass


if __name__ == "__main__":
    unittest.main()
