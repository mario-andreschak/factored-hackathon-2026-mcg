"""Retained RC action state cannot confer authority on the standalone bridge."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import os
from types import SimpleNamespace
import time
import uuid

from fastapi import FastAPI
import pytest

from banking_mcp.config import Config
from banking_mcp.security import Principal
from banking_mcp.service import Service
from dispute_workflow.action_host import BankingActionHost
from dispute_workflow.host import DisputeHostFactory
from dispute_workflow.state import TrustedBinding
from frontend.server.chat import ChatError
from frontend.server.config import Settings
from frontend.server.dispute_chat import DisputeChatService
from frontend.server.repository import Repository
from frontend.server.state import State
from scripts.qualify_dispute_app import build_fixture
from standalone.savia_whatsapp.runtime import enforce_readonly_bank_authority, install_readonly_bank_authority


@pytest.fixture
def retained_bank(tmp_path):
    """Only new generated fiction; actual RC bank, admission and action adapter."""
    old_umask = os.umask(0o077) if os.name == "posix" else None
    bank = None
    try:
        fixture = build_fixture(tmp_path / "fiction")
        state = fixture.root / "instance"
        coverage = int(fixture.created_at.timestamp()) - 172800
        bank = Service(Config(data_dir=fixture.data, state_db=state / "bank.sqlite3",
            service_token=fixture.service_token, public_keys={"qualification": fixture.public_key},
            principal_customers=fixture.subject_customers, sandbox_report_coverage_start=coverage,
            event_rates_file=fixture.rates, event_rates_sha256=fixture.rates_sha256,
            ledger_continuity_approved=True))

        async def forbidden_model(*args, **kwargs):
            pytest.fail("Read-only authority regression must never contact a model/provider")

        factory = DisputeHostFactory(forbidden_model, state / "dispute-workflow.sqlite3",
                                     bank_service=bank, source_root=fixture.source)
        backend = BankingActionHost(bank, factory.store, source_root=fixture.source)
        config = {"mode": "dispute-host/v1", "base_url": "http://127.0.0.1:1", "model": "flow-Dispute",
                  "execution_token": fixture.execution_token, "frontend_signing_key_file": str(fixture.signer),
                  "frontend_kid": "qualification", "frontend_issuer": "qualification",
                  "frontend_audience": "flujo-banking-ingress", "principal_customers": fixture.subject_customers,
                  "action_enabled": True, "ledger_generation": factory.ledger_generation}
        settings = Settings(data_dir=fixture.data, state_dir=state, static_dir=fixture.root / "static",
                            profiles=fixture.profiles, chat=config)
        repository = Repository(settings, State(state))
        backend.bind_repository(repository)
        bank.store.attest_sandbox_coverage(coverage, "synthetic:readonly-authority-regression")
        chat = DisputeChatService(config, state, bank_backend=backend)
        profile, subject = "mexico", "qualification-mexico"
        customer = fixture.subject_customers[subject]
        sid, conversation, expires = str(uuid.uuid4()), str(uuid.uuid4()), int(time.time()) + 3600
        owner = chat._owner_for_subject(subject)
        with chat._connection() as db:
            db.execute("""INSERT INTO chat_sessions
                (session_id,owner,expires,conversation_id,subject,customer_id) VALUES (?,?,?,?,?,?)""",
                (sid, owner, expires, conversation, subject, customer))
        principal = Principal(subject, customer, sid, conversation, expires, factory.ledger_generation)
        bank.store.bind_session(principal)
        binding = TrustedBinding(owner=owner, customer_id=customer, session_id=sid,
                                 conversation_id=conversation, expires_at=expires)
        workflow = factory(repository, chat, profile, sid, expires)
        workflow.bank.bind_context(binding)
        target = fixture.targets[profile]["transaction_id"]
        snapshot = repository.snapshot().build.name
        reference = repository.reference("txn", customer, target)
        app = FastAPI()
        app.state.chat_service = chat
        yield SimpleNamespace(fixture=fixture, bank=bank, backend=backend, chat=chat, app=app,
                              workflow=workflow, principal=principal, owner=owner, customer=customer,
                              sid=sid, expires=expires, conversation=conversation,
                              target=target, snapshot=snapshot, reference=reference)
    finally:
        if bank is not None:
            bank.close()
        if old_umask is not None:
            os.umask(old_umask)


def bank_dump(value):
    with value.bank.store.connect() as db:
        return tuple(db.iterdump())


def frontend_dump(value):
    with value.chat._connection() as db:
        return tuple(db.iterdump())


def seed_recovery(value, state):
    with value.chat._connection() as db:
        db.execute("DELETE FROM action_status WHERE session_id=?", (value.sid,))
    request = str(uuid.uuid4())
    value.chat._reserve_action(value.sid, value.owner, value.expires, value.reference,
        {"state": state, "request_id": request}, prepare_transaction_id=value.target,
        prepare_snapshot=value.snapshot, prepare_conversation_id=value.conversation)
    with value.chat._connection() as db:
        db.execute("UPDATE action_status SET updated_at=?,prepare_recovery_deadline=? WHERE session_id=?",
                   (int(time.time()) - 120, int(time.time()) + 600, value.sid))


def test_retained_prepare_recovery_has_no_bank_authority_even_if_action_flag_is_reenabled(retained_bank):
    value = retained_bank

    async def run():
        for state in ("preparing", "prepare_unverified"):
            seed_recovery(value, state)
            enforce_readonly_bank_authority(value.app)
            bank_before, frontend_before = bank_dump(value), frontend_dump(value)
            assert value.chat.status(value.customer)["read_only"] is True
            # Ordinary workflow host_action_status uses this real service method.
            with pytest.raises(ChatError) as disabled:
                await value.chat.action_status(value.customer, value.sid, value.expires)
            assert disabled.value.code == "action_unavailable"
            assert frontend_dump(value) == frontend_before
            assert bank_dump(value) == bank_before

            # Prove the separate backend restriction, rather than relying solely
            # on the flag: this eligible replay reaches real _post after its CAS
            # recovery claim, but cannot reach BankingActionHost's bank actions.
            value.chat._action_enabled = True
            with pytest.raises(ChatError) as blocked:
                await value.chat.action_status(value.customer, value.sid, value.expires)
            assert blocked.value.code == "action_unavailable"
            assert blocked.value.status_code == 403
            with value.chat._connection() as db:
                assert db.execute("SELECT prepare_recovery_attempts FROM action_status WHERE session_id=?",
                                  (value.sid,)).fetchone()[0] == 1
            assert bank_dump(value) == bank_before
    asyncio.run(run())


def test_retained_real_pending_cancellation_preserves_bank_and_frontend_rows(retained_bank):
    value = retained_bank
    request = str(uuid.uuid4())
    # Author a genuine pending operation in fresh synthetic test state, before
    # imposing the standalone boundary. No personal ledger is involved.
    prepared = value.bank.actions.prepare(value.principal, value.target, value.snapshot, request)
    value.backend._record(value.principal, request, None, handle=prepared["pending_handle"],
                          target=value.target, snapshot=value.snapshot)
    value.chat._reserve_action(value.sid, value.owner, value.expires, value.reference,
        {"state": "pending_confirmation", "request_id": request, "pending_handle": prepared["pending_handle"],
         "snapshot": prepared["snapshot"], "transaction": prepared["transaction"]},
        prepare_conversation_id=value.conversation)
    with value.chat._connection() as db:
        row = db.execute("SELECT * FROM action_status WHERE session_id=?", (value.sid,)).fetchone()
        assert value.chat._action_result(row)["state"] == "pending_confirmation"
    enforce_readonly_bank_authority(value.app)
    bank_before, frontend_before = bank_dump(value), frontend_dump(value)
    # This is the stock chat cancellation path, which does not check the flag.
    assert value.chat.cancel_pending(value.customer, value.sid, value.expires,
                                     handle=prepared["pending_handle"]) is False
    assert bank_dump(value) == bank_before
    assert frontend_dump(value) == frontend_before
    with value.bank.store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM dispute_host_cancelled").fetchone()[0] == 0
        assert db.execute("SELECT expires FROM action_pending").fetchone()[0] > int(time.time())


def test_real_source_read_and_session_revocation_survive_lifespan_guard(retained_bank):
    value = retained_bank
    pin = value.fixture.root / "instance/dispute-bank-generation.json"
    pin_before = hashlib.sha256(pin.read_bytes()).hexdigest()

    @asynccontextmanager
    async def original(app):
        yield

    value.app.router.lifespan_context = original
    install_readonly_bank_authority(value.app)

    async def run():
        async with value.app.router.lifespan_context(value.app):
            assert value.chat.status(value.customer)["read_only"] is True
            before = bank_dump(value)
            profile = await value.workflow.bank.read("get_customer_profile", {})
            assert profile["status"] == "ok" and profile["products"]
            assert bank_dump(value) == before
            assert await value.chat.revoke(value.customer, value.sid, value.expires) == "confirmed"
            assert value.bank.store.is_revoked(value.sid)
            with value.bank.store.connect() as db:
                assert db.execute("SELECT COUNT(*) FROM sandbox_cases").fetchone()[0] == 0
                assert db.execute("SELECT COUNT(*) FROM action_pending").fetchone()[0] == 0
    asyncio.run(run())
    assert hashlib.sha256(pin.read_bytes()).hexdigest() == pin_before
