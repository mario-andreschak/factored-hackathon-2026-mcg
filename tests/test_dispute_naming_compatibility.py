"""Retained identity, replay and cancellation history survive the workflow rename."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

from banking_mcp.security import BankError, StateStore
from dispute_workflow.action_host import BankingActionHost
from dispute_workflow.bank_read import pin_bank_generation
from dispute_workflow.state import (ConversationStore, RevisionConflict, StateError,
                                    TrustedBinding, begin_turn, new_state, set_pending)
from frontend.server.config import Settings
from frontend.server.dispute_chat import DisputeChatService
from scripts.run_dispute import workflow_state_path
from tests.test_dispute_action_host import general_handoff, joined
from tests.test_dispute_bank_read import bank, dataset


NOW = datetime(2026, 10, 1, 15, tzinfo=timezone.utc)


def database_dump(path):
    with sqlite3.connect(path) as db:
        return tuple(db.iterdump())


def fixture_bank(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = root / "ledger.sqlite3"
    store = StateStore(path, ledger_continuity_approved=True)
    return SimpleNamespace(store=store, config=SimpleNamespace(
        mode="delegated", ledger_continuity_approved=True, state_db=path))


def write_pin(service, *, legacy=True, **changes):
    with service.store.connect() as db:
        generation = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()[0]
    name = "gloria" if legacy else "dispute"
    pin = service.config.state_db.parent / f"{name}-bank-generation.json"
    value = dict(schema=f"{name}-bank-generation/v1", ledger_file=service.config.state_db.name,
                 ledger_generation=generation)
    value.update(changes)
    pin.write_text(json.dumps(value), encoding="utf-8")
    pin.chmod(0o600)
    return pin, generation


def test_legacy_conversations_keep_pending_and_replay_without_restoring_consent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    binding = TrustedBinding("customer", "session", "conversation", "owner", NOW + timedelta(hours=1))
    store = ConversationStore(path)
    state = begin_turn(new_state(binding, now=NOW), binding, turn_id="one", user_question="cargo", now=NOW)
    state = set_pending(state, dict(type="awaiting_confirmation", intent="TRANSACTION_DISPUTE",
        target_transaction_id="txn-fictional", snapshot_id="snapshot", snapshot_hash="hash",
        host_pending_handle="pending-handle", request_id="request", created_turn_id="one"), now=NOW)
    store.save_turn(binding, "one", state, now=NOW)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE dispute_conversations RENAME TO gloria_conversations")
        db.execute("ALTER TABLE dispute_turns RENAME TO gloria_turns")
        before = db.execute("SELECT state_json FROM gloria_conversations").fetchone()[0]
    restarted = ConversationStore(path)
    loaded = restarted.load(binding, now=NOW + timedelta(seconds=1))
    replay = restarted.load_turn(binding, "one", now=NOW + timedelta(seconds=1))
    assert loaded["runtime"]["store_revision"] == 1
    assert loaded["workflow_state"]["pending"]["request_id"] == "request"
    assert replay["workflow_state"]["pending"] == loaded["workflow_state"]["pending"]
    assert replay["workflow_state"]["action"]["authorized"] is False
    with pytest.raises(RevisionConflict):
        restarted.save(binding, state, now=NOW)
    assert restarted.load(replace(binding, owner="other"), now=NOW) is None
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT state_json FROM dispute_conversations").fetchone()[0] == before
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'gloria_%'").fetchone()


@pytest.mark.parametrize("collision", ["dispute_conversations", "dispute_turns"])
def test_mixed_conversation_names_fail_before_mutating_history(tmp_path, collision):
    path = tmp_path / "state.sqlite3"
    ConversationStore(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE dispute_conversations RENAME TO gloria_conversations")
        db.execute("ALTER TABLE dispute_turns RENAME TO gloria_turns")
        db.execute(f"CREATE TABLE {collision}(value TEXT)")
    before = database_dump(path)
    with pytest.raises(StateError, match="ambiguous_legacy_workflow_state"):
        ConversationStore(path)
    assert database_dump(path) == before


def test_failed_second_table_rename_rolls_back_first_table(tmp_path):
    path = tmp_path / "state.sqlite3"
    ConversationStore(path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE dispute_conversations RENAME TO gloria_conversations")
        db.execute("ALTER TABLE dispute_turns RENAME TO gloria_turns")
        db.execute("CREATE VIEW dispute_turns AS SELECT 1")
    before = database_dump(path)
    with pytest.raises(sqlite3.OperationalError):
        ConversationStore(path)
    assert database_dump(path) == before


def test_legacy_action_tables_keep_cancellation_and_receipt_rows(tmp_path):
    service = fixture_bank(tmp_path / "bank")
    pin_bank_generation(service)
    workflow = ConversationStore(tmp_path / "workflow.sqlite3")
    BankingActionHost(service, workflow)
    pairs = (("dispute_host_actions", "gloria_host_actions"),
             ("dispute_host_cancelled", "gloria_host_cancelled"),
             ("dispute_handoff_packets", "gloria_handoff_packets"))
    with service.store.connect() as db:
        db.execute("INSERT INTO dispute_host_actions VALUES ('binding','request','query','handle','target','snapshot','handoff')")
        db.execute("INSERT INTO dispute_host_cancelled VALUES ('binding','handle','query',123)")
        db.execute("INSERT INTO dispute_handoff_packets VALUES ('binding','handoff','query','request','saved-packet')")
        expected = {current: db.execute(f"SELECT * FROM {current}").fetchall() for current, _ in pairs}
        for current, old in pairs:
            db.execute(f"ALTER TABLE {current} RENAME TO {old}")
        db.execute("DROP INDEX dispute_host_pending")
        db.execute("CREATE UNIQUE INDEX gloria_host_pending ON gloria_host_actions(binding,pending_hash) WHERE pending_hash IS NOT NULL")
    BankingActionHost(service, workflow)
    with service.store.connect() as db:
        for current, _ in pairs:
            assert db.execute(f"SELECT * FROM {current}").fetchall() == expected[current]
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO dispute_host_actions VALUES ('binding','another','query','handle','target','snapshot',NULL)")
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name LIKE 'gloria_%'").fetchone()


def test_legacy_and_current_action_names_cannot_be_merged(tmp_path):
    service = fixture_bank(tmp_path / "bank")
    pin_bank_generation(service)
    workflow = ConversationStore(tmp_path / "workflow.sqlite3")
    BankingActionHost(service, workflow)
    with service.store.connect() as db:
        db.execute("ALTER TABLE dispute_host_cancelled RENAME TO gloria_host_cancelled")
    before = database_dump(service.config.state_db)
    with pytest.raises(StateError, match="ambiguous_legacy_workflow_state"):
        BankingActionHost(service, workflow)
    assert database_dump(service.config.state_db) == before


def test_retained_legacy_pin_is_validated_in_place(tmp_path):
    service = fixture_bank(tmp_path / "bank")
    pin, generation = write_pin(service)
    before = pin.read_bytes()
    (pin.parent / "gloria-workflow.sqlite3").touch()
    assert pin_bank_generation(service) == generation
    assert pin.read_bytes() == before
    assert not pin.with_name("dispute-bank-generation.json").exists()


@pytest.mark.parametrize("changes", [dict(schema="dispute-bank-generation/v1"),
    dict(ledger_generation="f" * 64), dict(ledger_file="other-ledger.sqlite3"), dict(extra="unexpected")])
def test_legacy_pin_rename_does_not_relax_exact_identity_validation(tmp_path, changes):
    service = fixture_bank(tmp_path / "bank")
    pin, _ = write_pin(service, **changes)
    before = pin.read_bytes()
    with pytest.raises(BankError, match="authorization_denied"):
        pin_bank_generation(service)
    assert pin.read_bytes() == before
    assert not pin.with_name("dispute-bank-generation.json").exists()


def test_two_generation_pins_require_explicit_reconciliation(tmp_path):
    service = fixture_bank(tmp_path / "bank")
    write_pin(service)
    write_pin(service, legacy=False)
    with pytest.raises(BankError, match="authorization_denied"):
        pin_bank_generation(service)


@pytest.mark.parametrize("retained", ["gloria-workflow.sqlite3", "gloria_host_actions", "gloria_host_cancelled",
                                     "gloria_handoff_packets"])
def test_missing_pin_cannot_adopt_new_generation_beside_legacy_history(tmp_path, retained):
    service = fixture_bank(tmp_path / "bank")
    if retained.endswith("sqlite3"):
        (service.config.state_db.parent / retained).touch()
    else:
        with service.store.connect() as db:
            db.execute(f"CREATE TABLE {retained}(value TEXT)")
            db.execute(f"INSERT INTO {retained} VALUES ('retained')")
    with pytest.raises(BankError, match="action_unverified"):
        pin_bank_generation(service)
    assert not (service.config.state_db.parent / "dispute-bank-generation.json").exists()


def test_default_database_path_reuses_legacy_file_and_rejects_two_histories(tmp_path):
    current, legacy = tmp_path / "dispute-workflow.sqlite3", tmp_path / "gloria-workflow.sqlite3"
    assert workflow_state_path(tmp_path) == current
    legacy.write_bytes(b"retained")
    assert workflow_state_path(tmp_path) == legacy
    current.write_bytes(b"independent")
    with pytest.raises(ValueError, match="explicit reconciliation"):
        workflow_state_path(tmp_path)
    assert legacy.read_bytes() == b"retained" and current.read_bytes() == b"independent"


def test_renamed_mode_preserves_original_cookie_fingerprint_and_ledger_isolation(tmp_path):
    settings = Settings(tmp_path, tmp_path / "state", tmp_path / "static", demo_code="fictional",
        chat=dict(mode="gloria-host/v1", namespace="bank", ledger_generation="a" * 64))
    old_policy = dict(auth_mode="demo", bank_host_mode="gloria-host/v1", bank_namespace="bank",
        bank_ledger_generation="a" * 64, demo_code_digest=hashlib.sha256(b"fictional").hexdigest())
    original = hashlib.sha256(json.dumps(old_policy, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    renamed = replace(settings, chat={**settings.chat, "mode": "dispute-host/v1"})
    assert settings.auth_fingerprint() == renamed.auth_fingerprint() == original
    assert replace(renamed, chat={**renamed.chat, "ledger_generation": "b" * 64}).auth_fingerprint() != original
    assert replace(renamed, chat={**renamed.chat, "namespace": "other"}).auth_fingerprint() != original


@pytest.mark.parametrize("old,new", [("flow-Gloria", "flow-Dispute"),
    ("flow-gloria_workflow_bridge", "flow-dispute_workflow_bridge")])
def test_renamed_default_graph_preserves_exact_admission_owner(old, new):
    chat = DisputeChatService.__new__(DisputeChatService)
    chat._issuer, chat._model = "fictional-issuer", new
    original = hashlib.sha256(json.dumps([chat._issuer, "subject", old], separators=(",", ":")).encode()).hexdigest()
    assert chat._owner_for_subject("subject") == original
    chat._model = "flow-independent-graph"
    assert chat._owner_for_subject("subject") != original


@pytest.mark.parametrize("corruption", [None, "binding", "query", "receipt"])
def test_retained_legacy_handoff_schema_requires_same_binding_and_receipt(joined, corruption):
    result, payload, headers = general_handoff(joined)
    with joined.bank.service.store.connect() as db:
        packet = json.loads(db.execute("SELECT packet_json FROM dispute_handoff_packets").fetchone()[0])
        packet["schema"] = "gloria-human-handoff/v1"
        if corruption == "binding":
            packet["binding_digest"] = "f" * 64
        elif corruption == "query":
            packet["query_id"] = "unrelated-query"
        elif corruption == "receipt":
            packet["native_handoff"]["id"] = "unrelated-handoff"
        db.execute("UPDATE dispute_handoff_packets SET packet_json=?", (json.dumps(packet),))
    replay = asyncio.run(joined.backend.post("/v1/banking/action", headers, payload, joined.chat))
    assert replay == ({"state": "action_unverified"} if corruption else
                      {"state": "handoff_verified", "handoff": result["handoff"]})
