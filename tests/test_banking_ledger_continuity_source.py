"""Corrected-source components only: TEMP fictional SQLite and fake Repository.

Config/JWT boundaries are replaced BEFORE source execution; JWT use and
Authorizer construction are forbidden. No Service, transport, SDK, network,
worker, shared DB, actual token verification or operator restore is exercised.
Changes are injected only after a connection has committed and CLOSED.
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import time
import types
import uuid
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[1] / "banking_mcp"
OTHER = "b" * 64


@pytest.fixture
def component(monkeypatch):
    package_name = "_banking_ledger_continuity_components"
    package = types.ModuleType(package_name)
    package.__path__ = []
    monkeypatch.setitem(sys.modules, package_name, package)

    def forbidden(*_args, **_kwargs):
        pytest.fail("JWT/Authorizer runtime is outside this component lane")

    def module(name, **values):
        value = types.ModuleType(name)
        value.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, value)

    module(package_name + ".config", Config=object)
    module("jwt", decode=forbidden, get_unverified_header=forbidden, PyJWTError=ValueError)
    # Deterministic binding callback only, not RFC8785/cryptographic acceptance.
    module("rfc8785", dumps=lambda value: json.dumps(value, sort_keys=True,
        separators=(",", ":")).encode())

    def load(name):
        spec = importlib.util.spec_from_file_location(package_name + "." + name, SOURCE / (name + ".py"))
        value = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, value)
        spec.loader.exec_module(value)
        return value

    security = load("security")
    monkeypatch.setattr(security.Authorizer, "__init__", forbidden)
    actions = load("actions")
    return SimpleNamespace(security=security, Actions=actions.Actions)


class FakeRepository:
    def __init__(self, root):
        self.info = SimpleNamespace(id="fictional-continuity", build=root / "fictional-continuity")
        self.info.build.mkdir()
        (self.info.build / "snapshot.json").write_text(json.dumps({
            "source_fingerprint": "fictional-continuity-source"}), encoding="utf-8")
        self.row = {"transaction_date": datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2),
                    "transaction_status": "Approved"}
        self.on_owned = None
        self.on_snapshot = None

    def owned_transaction_id(self, principal, transaction_id, build):
        assert (principal.customer, transaction_id, build) == ("fictional-customer", "fictional-charge", self.info.id)
        if self.on_owned:
            callback, self.on_owned = self.on_owned, None
            callback()
        return self.info, self.row.copy()

    def _visible(self, row, snapshot):
        return {"transaction_reference": "txn_012345abcdef", "merchant": "Fictional store",
                "amount": "12.50", "currency": "MXN", "status": row["transaction_status"]}

    def assert_current_snapshot(self, expected):
        assert expected == self.info.id

    def snapshot(self):
        if self.on_snapshot:
            callback, self.on_snapshot = self.on_snapshot, None
            callback()
        return self.info


@pytest.fixture
def bank(component, tmp_path):
    security = component.security

    class ObservedStore(security.StateStore):
        """Observers run outside the real connection, gate and transaction."""
        @contextmanager
        def connect(self):
            statements = []

            class Connection:
                def __init__(self, db):
                    self.db = db

                def __getattr__(self, name):
                    return getattr(self.db, name)

                def execute(self, statement, args=()):
                    statements.append(statement)
                    return self.db.execute(statement, args)

            with super().connect() as db:
                yield Connection(db)
            hook = getattr(self, "after_close", None)
            if hook and hook[0](statements):
                self.after_close = None
                hook[1]()

    store = ObservedStore(tmp_path / "fictional-state.db", ledger_continuity_approved=True)
    with store.connect() as db:
        generation = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0]
    owner = security.Principal("fictional-subject", "fictional-customer", "fictional-session",
                               "fictional-conversation", int(time.time()) + 60, generation)
    repo = FakeRepository(tmp_path)
    evidence = tmp_path / "fictional-evidence.json"
    evidence.write_text(json.dumps({"build_id": repo.info.id,
        "source_fingerprint": "fictional-continuity-source", "transactions": {
            "fictional-charge": {"historical_complaints": "clear_in_snapshot", "duplicate_signal": "clear",
                                 "fraud_score": 0, "amount_usd": 12.50}}}), encoding="utf-8")
    coverage_start = int(time.time()) - 90000
    store.attest_sandbox_coverage(coverage_start, "synthetic:continuity-component-only")

    def actions(selected_store):
        return component.Actions(selected_store, repo, coverage_start, evidence, "fictional-secret" * 3)

    return SimpleNamespace(store=store, owner=owner, repo=repo, actions=actions(store),
        make_actions=actions, security=security, root=tmp_path)


def prepare(bank):
    return bank.actions.prepare(bank.owner, "fictional-charge", bank.repo.info.id, str(uuid.uuid4()))


def rotate(bank):
    with bank.store.connect() as db:
        db.execute("UPDATE sandbox_ledger_identity SET generation=? WHERE id=1", (OTHER,))


def state(bank):
    with bank.store.connect() as db:
        return {table: db.execute("SELECT * FROM " + table).fetchall() for table in (
            "sandbox_ledger_identity", "sandbox_coverage", "sessions", "replays", "revoked", "capabilities",
            "action_pending", "sandbox_cases", "sandbox_case_receipts", "sandbox_handoffs")}


@pytest.mark.parametrize("generation", [None, "", "a" * 63, "a" * 65, "A" * 64, "g" * 64, OTHER, 1])
@pytest.mark.parametrize("revocation", [False, True])
def test_generation_denied_before_session_replay_or_revoke_mutation(bank, generation, revocation):
    before = state(bank)
    principal = replace(bank.owner, ledger_generation=generation)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.store.admit(principal, "fictional-jti", revocation=revocation)
    assert state(bank) == before


def test_binding_retains_generation_and_old_capability_fails_after_rotation(bank):
    old_binding = bank.owner.binding()
    token = bank.store.put("selection", bank.owner, {"fictional": True})
    rotate(bank)
    current = replace(bank.owner, ledger_generation=OTHER)
    assert current.binding() != old_binding
    with pytest.raises(bank.security.BankError, match="^reference_unavailable$"):
        bank.store.get(token, "selection", current)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.store.get(token, "selection", bank.owner)


def test_prepare_rotation_between_closed_admission_and_writer_denies(bank):
    bank.repo.on_owned = lambda: rotate(bank)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        prepare(bank)
    assert not state(bank)["action_pending"]


def test_confirm_rotation_after_attempt_commit_keeps_uncertainty_without_case(bank):
    pending = prepare(bank)
    bank.store.after_close = (lambda statements: any("SET confirmation_state='attempted'" in s for s in statements),
                              lambda: rotate(bank))
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.actions.confirm(bank.owner, pending["pending_handle"], True)
    saved = state(bank)
    assert saved["action_pending"][0][-1] == "attempted"
    assert not saved["sandbox_cases"] and not saved["sandbox_case_receipts"]


def test_final_fence_rejects_rotation_after_prepare_commit(bank):
    bank.store.after_close = (lambda statements: any("INSERT INTO action_pending" in s for s in statements),
                              lambda: rotate(bank))
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        prepare(bank)
    assert len(state(bank)["action_pending"]) == 1
    assert not state(bank)["sandbox_cases"]


def test_positive_approved_case_independent_receipt_and_restart(bank):
    bank.store.admit(bank.owner, "fictional-admission")
    pending = prepare(bank)
    assert pending["decision"] == "intake"
    confirmed = bank.actions.confirm(bank.owner, pending["pending_handle"], True)
    assert confirmed["state"] == "created" and confirmed["receipt"]["simulated"] is True
    restarted = bank.security.StateStore(bank.store.path, ledger_continuity_approved=True)
    actions = bank.make_actions(restarted)
    assert actions.receipt(bank.owner, pending["pending_handle"]) == confirmed
    assert actions.local_case_status(bank.owner, "fictional-charge", bank.repo.info.id)["receipt"] == confirmed["receipt"]
    saved = state(bank)
    assert len(saved["sandbox_cases"]) == len(saved["sandbox_case_receipts"]) == 1


def test_quarantine_blocks_actions_reads_and_admission_with_no_mutation(bank):
    pending = prepare(bank)
    handoff = bank.actions.handoff(bank.owner, "customer_request", None, str(uuid.uuid4()))
    quarantined = bank.security.StateStore(bank.store.path)  # safe default False
    actions = bank.make_actions(quarantined)
    before = state(bank)
    callbacks = [lambda: quarantined.admit(bank.owner, "quarantined-jti"),
        lambda: actions.prepare(bank.owner, "fictional-charge", bank.repo.info.id, str(uuid.uuid4())),
        lambda: actions.confirm(bank.owner, pending["pending_handle"], True),
        lambda: actions.receipt(bank.owner, pending["pending_handle"]),
        lambda: actions.local_case_status(bank.owner, "fictional-charge", bank.repo.info.id),
        lambda: actions.handoff(bank.owner, "customer_request", None, str(uuid.uuid4())),
        lambda: actions.read_handoff(bank.owner, handoff["handoff"]["id"]),
        lambda: quarantined.put("selection", bank.owner, {}),
        lambda: quarantined.assert_current(bank.owner)]
    for callback in callbacks:
        with pytest.raises(bank.security.BankError, match="^action_unverified$"):
            callback()
        assert state(bank) == before


def test_same_generation_older_attested_backup_cannot_clear_external_quarantine(bank):
    backup_path = bank.root / "fictional-earlier-backup.db"
    with sqlite3.connect(bank.store.path) as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    pending = prepare(bank)
    bank.actions.confirm(bank.owner, pending["pending_handle"], True)
    # All connections are closed. Copy the older fictional DB into the target
    # via SQLite backup; external approval is independently OFF at reopen.
    with sqlite3.connect(backup_path) as source, sqlite3.connect(bank.store.path) as restored:
        source.backup(restored)
    quarantined = bank.security.StateStore(bank.store.path, ledger_continuity_approved=False)
    actions = bank.make_actions(quarantined)
    before = state(bank)
    assert before["sandbox_ledger_identity"][0][1] == bank.owner.ledger_generation
    assert before["sandbox_coverage"] and not before["sandbox_cases"]
    with pytest.raises(bank.security.BankError, match="^action_unverified$"):
        actions.prepare(bank.owner, "fictional-charge", bank.repo.info.id, str(uuid.uuid4()))
    with pytest.raises(bank.security.BankError, match="^action_unverified$"):
        actions.local_case_status(bank.owner, "fictional-charge", bank.repo.info.id)
    assert state(bank) == before


def test_matching_revoke_allowed_during_quarantine_without_session_adoption(bank):
    quarantined = bank.security.StateStore(bank.store.path)
    quarantined.admit(bank.owner, "fictional-revoke", revocation=True)
    saved = state(bank)
    assert saved["revoked"] == [(bank.owner.session,)]
    assert not saved["sessions"]
    assert saved["replays"] == [("fictional-revoke", bank.owner.expires)]
    # Repeated deny with a new JTI is idempotent; approval remains OFF.
    quarantined.admit(bank.owner, "fictional-revoke-second", revocation=True)
    assert state(bank)["revoked"] == [(bank.owner.session,)]
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        quarantined.assert_current(bank.owner)


@pytest.mark.parametrize("identity", [None, "X" * 64, "bad"])
def test_damaged_existing_identity_is_not_regenerated_or_attested(bank, identity):
    with bank.store.connect() as db:
        if identity is None:
            db.execute("DELETE FROM sandbox_ledger_identity")
        else:
            db.execute("UPDATE sandbox_ledger_identity SET generation=? WHERE id=1", (identity,))
    before = state(bank)
    reopened = bank.security.StateStore(bank.store.path, ledger_continuity_approved=True)
    assert state(bank) == before
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        reopened.admit(bank.owner, "identity-damaged")
    with pytest.raises(bank.security.BankError, match="^risk_data_unavailable$"):
        reopened.attest_sandbox_coverage(int(time.time()) - 90000, "synthetic:damaged-identity")
    assert state(bank) == before


def test_replay_collision_rolls_back_session_binding_in_same_transaction(bank):
    bank.store.admit(bank.owner, "already-consumed")
    before = state(bank)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.store.admit(replace(bank.owner, session="must-not-persist"), "already-consumed")
    assert state(bank) == before


def test_mismatched_revoke_during_quarantine_does_not_mutate_replacement(bank):
    rotate(bank)
    quarantined = bank.security.StateStore(bank.store.path)
    before = state(bank)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        quarantined.admit(bank.owner, "old-generation-revoke", revocation=True)
    assert state(bank) == before


def test_raw_mutation_helpers_cannot_bypass_delegated_generation(bank):
    before = state(bank)
    callbacks = [lambda: bank.store.bind_session(replace(bank.owner, ledger_generation=OTHER)),
        lambda: bank.store.consume("raw-jti", bank.owner.expires),
        lambda: bank.store.revoke(bank.owner.session),
        lambda: bank.store.revoke(bank.owner.session, principal=replace(bank.owner, ledger_generation=OTHER))]
    for callback in callbacks:
        with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
            callback()
        assert state(bank) == before


def test_readback_final_fence_after_closed_transaction(bank):
    pending = prepare(bank)
    bank.actions.confirm(bank.owner, pending["pending_handle"], True)
    bank.store.after_close = (lambda statements: any("FROM sandbox_cases c" in s for s in statements),
                              lambda: rotate(bank))
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.actions.receipt(bank.owner, pending["pending_handle"])


def test_handoff_currentness_final_fence_after_repository_callback(bank):
    pending = prepare(bank)
    handoff = bank.actions.handoff(bank.owner, "customer_request", pending["pending_handle"], str(uuid.uuid4()))
    bank.repo.on_snapshot = lambda: rotate(bank)
    with pytest.raises(bank.security.BankError, match="^authorization_denied$"):
        bank.actions.read_handoff(bank.owner, handoff["handoff"]["id"])
