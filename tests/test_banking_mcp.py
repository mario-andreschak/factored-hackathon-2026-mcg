"""Only synthetic data and signing keys. No source credentials or model calls."""
from __future__ import annotations

import json
import csv
import io
import multiprocessing
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from starlette.testclient import TestClient

from banking_mcp.config import Config
from banking_mcp.security import ASSERTION_META, TOKEN_TYPE, BankError, StateStore, arguments_digest
from banking_mcp.server import create_http_app
from banking_mcp.service import Service
from pipeline.__main__ import main
from pipeline.fixture import cid, write_base
from tests.banking_authority_fixtures import ledger_generation, principal_for


ACTION_TEST_NOW = datetime(2026, 9, 29, 12, tzinfo=timezone.utc).timestamp()
ACTION_TEST_WALL_ORIGIN = time.time()


def fixed_action_clock(service, wall_origin=ACTION_TEST_WALL_ORIGIN):
    # The synthetic transactions are dated June 1-2, 2026. Keep action
    # eligibility deterministic while authentication still uses wall time.
    service.actions.clock = lambda: ACTION_TEST_NOW + (time.time() - wall_origin)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("bank-dataset")
    write_base(root / "src")
    assert main(["run", "--source", str(root / "src"), "--out", str(root / "out"),
                 "--reports", str(root / "reports")]) == 0
    return root


@pytest.fixture
def bank(dataset, tmp_path):
    key = Ed25519PrivateKey.generate()
    evidence_file = tmp_path / "synthetic-evidence.json"
    config = Config(data_dir=dataset / "out", state_db=tmp_path / "state.db", service_token="x" * 48,
                    public_keys={"test": key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()},
                    principal_customers={"alice": cid(3), "bob": cid(4)},
                    synthetic_evidence_file=evidence_file, ledger_continuity_approved=True)
    service = Service(config)
    fixed_action_clock(service)
    snapshot = service.repository.snapshot()
    manifest = json.loads((snapshot.build / "snapshot.json").read_text())
    targets = {target for subject in ("alice", "bob")
               for target in owned_action_target((service, key), subject)[1]}
    evidence_file.write_text(json.dumps({"build_id": snapshot.id,
        "source_fingerprint": manifest["source_fingerprint"],
        "transactions": {target: {"historical_complaints": "clear_in_snapshot",
                                 "duplicate_signal": "clear", "fraud_score": 0,
                                 "amount_usd": 10} for target in targets}}))
    yield service, key
    service.close()


def assertion(bank, tool_name, args, subject="alice", **overrides):
    service, key = bank
    now = int(time.time())
    claims = {"iss": service.config.issuer, "aud": service.config.audience, "sub": subject,
              "iat": now, "nbf": now, "exp": now + 60, "jti": str(uuid.uuid4()),
              "session_id": "session-" + subject, "conversation_id": "conversation-" + subject,
              "run_id": str(uuid.uuid4()), "graph_revision": "v1", "tool": tool_name,
              "scope": ["bank:read"], "args_sha256": arguments_digest(args),
              "ledger_generation": ledger_generation(service.store), **overrides}
    return {ASSERTION_META: jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "test", "typ": TOKEN_TYPE})}


def call(bank, tool="list_my_transactions", args=None, subject="alice", **claims):
    args = args or {}
    return bank[0].execute(tool, args, assertion(bank, tool, args, subject, **claims))


def action_call(bank, tool, args, subject="alice"):
    from banking_mcp.service import SCOPES
    if tool == "prepare_unrecognized_charge" and "request_id" not in args:
        args = {**args, "request_id": str(uuid.uuid4())}
    return call(bank, tool, args, subject, scope=[SCOPES[tool]])


def owned_action_target(bank, subject="alice"):
    service = bank[0]
    customer = service.config.principal_customers[subject]
    principal = principal_for(service.store, subject, customer, "session-" + subject,
                          "conversation-" + subject, int(time.time()) + 60)
    snapshot = service.repository.snapshot()
    rows = service.repository._rows(snapshot, principal, "transaction_status='Approved'", [], 20)
    return snapshot.id, [r["transaction_id"] for r in rows]


def _confirm_in_process(config_json, handle, ready, barrier, results, wall_origin):
    service = Service(Config.model_validate_json(config_json))
    fixed_action_clock(service, wall_origin)
    principal = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60)
    try:
        ready.wait(timeout=15)
        barrier.wait(timeout=15)
        results.put(service.actions.confirm(principal, handle, True)["state"])
    except BankError as exc:
        results.put(exc.code)
    except Exception as exc:
        results.put(type(exc).__name__)
    finally:
        service.close()


def _handoff_in_process(config_json, request_id, ready, barrier, results, wall_origin):
    service = Service(Config.model_validate_json(config_json))
    fixed_action_clock(service, wall_origin)
    principal = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60)
    try:
        ready.wait(timeout=15)
        barrier.wait(timeout=15)
        results.put(service.actions.handoff(principal, "customer_request", None, request_id)["state"])
    except BankError as exc:
        results.put(exc.code)
    finally:
        service.close()


def _prepare_in_process(config_json, transaction_id, build, request_id, barrier, results, wall_origin):
    service = Service(Config.model_validate_json(config_json))
    fixed_action_clock(service, wall_origin)
    principal = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60)
    try:
        barrier.wait(timeout=15)
        results.put(service.actions.prepare(principal, transaction_id, build, request_id))
    except BankError as exc:
        results.put({"error": exc.code})
    finally:
        service.close()


def authority_state(store):
    with store.connect() as db:
        return {table: db.execute("SELECT * FROM " + table).fetchall() for table in (
            "sandbox_ledger_identity", "sandbox_coverage", "sessions", "replays", "revoked",
            "capabilities", "action_pending", "sandbox_cases", "sandbox_case_receipts", "sandbox_handoffs")}


@pytest.mark.parametrize("generation", ["omitted", None, "", "A" * 64, "d" * 63, "g" * 64, "different"])
@pytest.mark.parametrize("revocation", [False, True])
def test_signed_missing_malformed_or_foreign_generation_denies_without_mutation(bank, generation, revocation, monkeypatch):
    service, key = bank
    tool, scope, token_type = (("revoke_session", "bank:revoke", "bank-revoke+jwt") if revocation else
                               ("list_my_transactions", "bank:read", TOKEN_TYPE))
    claims = jwt.decode(assertion(bank, tool, {}, scope=[scope])[ASSERTION_META], options={"verify_signature": False})
    if generation == "omitted":
        claims.pop("ledger_generation")
    elif generation == "different":
        current = claims["ledger_generation"]
        claims["ledger_generation"] = ("0" if current[0] != "0" else "1") + current[1:]
    else:
        claims["ledger_generation"] = generation
    token = jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "test", "typ": token_type})
    before = authority_state(service.store)
    monkeypatch.setattr(service.repository, "list_transactions", lambda *_: pytest.fail("denied authority touched dataset"))
    with pytest.raises(BankError, match="^authorization_denied$"):
        if revocation:
            service.auth.revoke_assertion(token)
        else:
            service.execute(tool, {}, {ASSERTION_META: token})
    assert authority_state(service.store) == before


def test_missing_continuity_approval_denies_signed_admission_but_allows_matching_revocation(bank, monkeypatch):
    service, key = bank
    config_values = json.loads(service.config.model_dump_json())
    config_values.pop("ledger_continuity_approved")
    quarantined = Service(Config.model_validate(config_values))
    assert quarantined.config.ledger_continuity_approved is False
    try:
        before = authority_state(quarantined.store)
        monkeypatch.setattr(quarantined.repository, "list_transactions", lambda *_: pytest.fail("quarantine touched dataset"))
        with pytest.raises(BankError, match="^action_unverified$"):
            call((quarantined, key))
        assert authority_state(quarantined.store) == before
        quarantined.auth.revoke_assertion(revoke_token((quarantined, key)))
        after = authority_state(quarantined.store)
        assert after["revoked"] == [("session-alice",)]
        assert not after["sessions"] and len(after["replays"]) == 1
        assert {name: rows for name, rows in after.items() if name not in {"revoked", "replays"}} == {
            name: rows for name, rows in before.items() if name not in {"revoked", "replays"}}
    finally:
        quarantined.close()


def test_simulated_intake_requires_coverage_confirmation_and_readback(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    service.actions.coverage_start = int(service.actions.clock()) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:bank-test-ledger")
    pending = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})
    assert pending["decision"] == "intake"
    assert pending["risk"]["unrecognized_count_24h"] == 1
    assert pending["risk"]["risk_data_complete"] is True
    assert pending["risk"]["source"] == "sandbox_cases"
    args = {"pending_handle": pending["pending_handle"], "confirmed": True}
    first = action_call(bank, "confirm_simulated_intake", args)
    again = action_call(bank, "confirm_simulated_intake", args)
    assert first == again
    assert first["state"] == "created" and first["receipt"]["simulated"] is True
    assert action_call(bank, "read_intake_receipt", {"pending_handle": pending["pending_handle"]}) == first
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        db.execute("UPDATE action_pending SET snapshot='another-build'")
    assert action_call(bank, "read_intake_receipt", {"pending_handle": pending["pending_handle"]})["state"] == "action_unverified"
    with pytest.raises(BankError, match="reference_unavailable"):
        action_call(bank, "read_intake_receipt", {"pending_handle": pending["pending_handle"]}, "bob")


def test_action_missing_coverage_and_verified_handoff(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    pending = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})
    assert pending["decision"] == "handoff"
    assert pending["reason"] == "missing_evidence"
    assert pending["risk"]["unrecognized_count_24h"] is None
    with pytest.raises(BankError, match="handoff_required"):
        action_call(bank, "confirm_simulated_intake",
                    {"pending_handle": pending["pending_handle"], "confirmed": True})
    handoff = action_call(bank, "create_verified_handoff",
                          {"pending_handle": pending["pending_handle"], "reason": "missing_evidence"})
    assert handoff["state"] == "created" and handoff["handoff"]["human_responded"] is False
    assert action_call(bank, "read_verified_handoff",
                       {"handoff_id": handoff["handoff"]["id"]}) == handoff
    assert action_call(bank, "create_verified_handoff",
                       {"pending_handle": pending["pending_handle"], "reason": "missing_evidence"}) == handoff


def test_no_target_handoffs_are_distinct_and_retryable(bank):
    first_args = {"reason": "customer_request", "request_id": str(uuid.uuid4())}
    second_args = {"reason": "customer_request", "request_id": str(uuid.uuid4())}
    first = action_call(bank, "create_verified_handoff", first_args)
    second = action_call(bank, "create_verified_handoff", second_args)
    assert first["handoff"]["id"] != second["handoff"]["id"]
    assert first["handoff"]["facts"] == second["handoff"]["facts"] == {}
    assert action_call(bank, "create_verified_handoff", first_args) == first
    with pytest.raises(BankError, match="invalid_arguments"):
        action_call(bank, "create_verified_handoff", {"reason": "customer_request"})


def test_prepare_request_replays_after_lost_response_and_restart(bank):
    service, key = bank
    build, targets = owned_action_target(bank)
    request_id = str(uuid.uuid4())
    args = {"transaction_id": targets[0], "snapshot": build, "request_id": request_id}
    original = action_call(bank, "prepare_unrecognized_charge", args)
    restarted = Service(service.config)
    fixed_action_clock(restarted)
    try:
        assert action_call((restarted, key), "prepare_unrecognized_charge", args) == original
        with pytest.raises(BankError, match="invalid_arguments"):
            action_call((restarted, key), "prepare_unrecognized_charge",
                        {**args, "transaction_id": targets[1]})
        with pytest.raises(BankError, match="invalid_arguments"):
            action_call((restarted, key), "prepare_unrecognized_charge", {**args, "snapshot": "other-build"})
        with restarted.store.connect() as db:
            assert db.execute("SELECT count(*) FROM action_pending WHERE request_key IS NOT NULL").fetchone()[0] == 1
            db.execute("UPDATE action_pending SET expires=0 WHERE request_key IS NOT NULL")
        with pytest.raises(BankError, match="reference_unavailable"):
            action_call((restarted, key), "prepare_unrecognized_charge", args)
    finally:
        restarted.close()


def test_prepare_same_request_serializes_across_processes_and_scopes_binding(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    request_id = str(uuid.uuid4())
    ctx = multiprocessing.get_context("spawn")
    barrier, results = ctx.Barrier(2), ctx.Queue()
    children = [ctx.Process(target=_prepare_in_process,
                args=(service.config.model_dump_json(), targets[0], build, request_id, barrier, results,
                      ACTION_TEST_WALL_ORIGIN))
                for _ in range(2)]
    for child in children:
        child.start()
    for child in children:
        child.join(25)
        assert child.exitcode == 0
    first, second = (results.get(timeout=2) for _ in children)
    assert first == second and len(first["pending_handle"]) == 43
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM action_pending WHERE request_key IS NOT NULL").fetchone()[0] == 1
    different_session = principal_for(service.store, "alice", cid(3), "session-other", "conversation-alice", int(time.time()) + 60)
    different_conversation = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-other", int(time.time()) + 60)
    for principal in (different_session, different_conversation):
        assert service.actions.prepare(principal, targets[0], build, request_id)["pending_handle"] != first["pending_handle"]
    foreign = principal_for(service.store, "bob", cid(4), "session-bob", "conversation-bob", int(time.time()) + 60)
    with pytest.raises(BankError, match="reference_unavailable"):
        service.actions.prepare(foreign, targets[0], build, request_id)
    with pytest.raises(BankError, match="invalid_arguments"):
        service.actions.prepare(different_session, targets[0], build, str(uuid.uuid1()))


def test_prepare_denies_expired_and_revoked_bindings_before_insert(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    with pytest.raises(BankError, match="invalid_arguments"):
        call(bank, "prepare_unrecognized_charge", {"transaction_id": targets[0], "snapshot": build},
             scope=["bank:prepare"])
    expired = principal_for(service.store, "alice", cid(3), "session-expired", "conversation-alice", int(time.time()) - 1)
    with pytest.raises(BankError, match="authorization_denied"):
        service.actions.prepare(expired, targets[0], build, str(uuid.uuid4()))
    service.store.revoke("session-alice", principal=principal_for(
        service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60))
    revoked = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60)
    with pytest.raises(BankError, match="authorization_denied"):
        service.actions.prepare(revoked, targets[0], build, str(uuid.uuid4()))
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM action_pending").fetchone()[0] == 0


def test_selected_handoff_lost_response_reuses_logical_request(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    request_id = str(uuid.uuid4())
    first_pending = action_call(bank, "prepare_unrecognized_charge",
                                {"transaction_id": targets[0], "snapshot": build})["pending_handle"]
    first = action_call(bank, "create_verified_handoff", {"pending_handle": first_pending,
                        "reason": "customer_request", "request_id": request_id})
    retry_pending = action_call(bank, "prepare_unrecognized_charge",
                                {"transaction_id": targets[0], "snapshot": build})["pending_handle"]
    replay = action_call(bank, "create_verified_handoff", {"pending_handle": retry_pending,
                         "reason": "customer_request", "request_id": request_id})
    assert replay == first
    other_pending = action_call(bank, "prepare_unrecognized_charge",
                                {"transaction_id": targets[1], "snapshot": build})["pending_handle"]
    with pytest.raises(BankError, match="invalid_arguments"):
        action_call(bank, "create_verified_handoff", {"pending_handle": other_pending,
                    "reason": "customer_request", "request_id": request_id})
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 1


def test_revocation_winning_handoff_writer_prevents_packet(bank):
    service = bank[0]
    ctx = multiprocessing.get_context("spawn")
    ready, barrier, results = ctx.Barrier(2), ctx.Barrier(2), ctx.Queue()
    child = ctx.Process(target=_handoff_in_process,
                        args=(service.config.model_dump_json(), str(uuid.uuid4()), ready, barrier, results,
                              ACTION_TEST_WALL_ORIGIN))
    child.start()
    ready.wait(timeout=15)
    with service.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        barrier.wait(timeout=15)
        db.execute("INSERT INTO revoked(session) VALUES (?)", ("session-alice",))
        time.sleep(0.2)
    child.join(25)
    assert child.exitcode == 0 and results.get(timeout=2) == "authorization_denied"
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_handoffs").fetchone()[0] == 0


def test_sandbox_coverage_requires_same_persisted_ledger_generation(bank, tmp_path):
    service = bank[0]
    build, targets = owned_action_target(bank)
    start = int(service.actions.clock()) - 90000
    service.actions.coverage_start = start
    service.store.attest_sandbox_coverage(start, "synthetic:verified-empty-ledger")
    complete = action_call(bank, "prepare_unrecognized_charge",
                           {"transaction_id": targets[0], "snapshot": build})
    assert complete["decision"] == "intake" and complete["risk"]["unrecognized_count_24h"] == 1
    reset = Service(service.config.model_copy(update={"state_db": tmp_path / "replacement.db",
        "sandbox_report_coverage_start": start})), bank[1]
    fixed_action_clock(reset[0])
    replaced = action_call(reset, "prepare_unrecognized_charge",
                           {"transaction_id": targets[0], "snapshot": build})
    assert replaced["decision"] == "handoff" and replaced["reason"] == "missing_evidence"
    assert replaced["risk"]["unrecognized_count_24h"] is None
    with service.store.connect() as db:
        db.execute("UPDATE sandbox_coverage SET generation='corrupt'")
    corrupt = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})
    assert corrupt["decision"] == "handoff" and corrupt["risk"]["unrecognized_count_24h"] is None


def test_missing_or_high_synthetic_signals_never_clear_intake(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    start = int(service.actions.clock()) - 90000
    service.actions.coverage_start = start
    service.store.attest_sandbox_coverage(start, "synthetic:signals-ledger")
    evidence_file = service.actions.evidence_file
    service.actions.evidence_file = None
    missing = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})
    assert missing["reason"] == "missing_evidence" and missing["decision"] == "handoff"
    service.actions.evidence_file = evidence_file
    data = json.loads(evidence_file.read_text())
    data["transactions"][targets[0]]["fraud_score"] = 75
    evidence_file.write_text(json.dumps(data))
    high = action_call(bank, "prepare_unrecognized_charge",
                       {"transaction_id": targets[0], "snapshot": build})
    assert high["reason"] == "high_risk" and high["decision"] == "handoff"


def test_action_risk_threshold_and_duplicate_report(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    assert len(set(targets)) >= 3
    service.actions.coverage_start = int(service.actions.clock()) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:bank-test-ledger")
    decisions = []
    for target in targets[:2]:
        pending = action_call(bank, "prepare_unrecognized_charge",
                              {"transaction_id": target, "snapshot": build})
        assert pending["decision"] == "intake"
        assert action_call(bank, "confirm_simulated_intake",
                           {"pending_handle": pending["pending_handle"], "confirmed": True})["state"] == "created"
        decisions.append(pending)
    decisions.append(action_call(bank, "prepare_unrecognized_charge",
                                 {"transaction_id": targets[2], "snapshot": build}))
    assert [p["decision"] for p in decisions] == ["intake", "intake", "handoff"]
    assert decisions[2]["reason"] == "high_risk"
    duplicate = action_call(bank, "prepare_unrecognized_charge",
                            {"transaction_id": targets[0], "snapshot": build})
    assert duplicate["risk"]["unrecognized_count_24h"] == 2
    assert duplicate["decision"] == "existing_case" and duplicate["reason"] is None
    assert duplicate["existing_case"]["state"] == "verified"
    assert duplicate["existing_case"]["receipt"]["status"] == "received"
    assert action_call(bank, "read_intake_receipt", {
        "pending_handle": duplicate["pending_handle"]})["receipt"] == duplicate["existing_case"]["receipt"]
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 2
    with pytest.raises(BankError, match="handoff_required"):
        action_call(bank, "confirm_simulated_intake",
                    {"pending_handle": decisions[2]["pending_handle"], "confirmed": True})


def test_action_foreign_target_and_snapshot_swap_denied(bank):
    build, targets = owned_action_target(bank, "bob")
    bank[0].actions.coverage_start = int(bank[0].actions.clock()) - 90000
    bank[0].store.attest_sandbox_coverage(bank[0].actions.coverage_start, "synthetic:bank-test-ledger")
    with pytest.raises(BankError, match="reference_unavailable"):
        action_call(bank, "prepare_unrecognized_charge",
                    {"transaction_id": targets[0], "snapshot": build}, "alice")
    with pytest.raises(BankError, match="snapshot_changed"):
        action_call(bank, "prepare_unrecognized_charge",
                    {"transaction_id": targets[0], "snapshot": "other-build"}, "bob")


def test_action_concurrent_confirmation_and_expired_pending_readback(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    service.actions.coverage_start = int(service.actions.clock()) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:bank-test-ledger")
    pending = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})["pending_handle"]
    args = {"pending_handle": pending, "confirmed": True}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: action_call(bank, "confirm_simulated_intake", args), range(2)))
    assert results[0] == results[1]
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 1
        db.execute("UPDATE action_pending SET expires=0")
    assert action_call(bank, "read_intake_receipt", {"pending_handle": pending}) == results[0]
    with pytest.raises(BankError, match="reference_unavailable"):
        action_call(bank, "confirm_simulated_intake", args)


def test_cross_process_distinct_confirmations_serialize_r16_threshold(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    start = int(service.actions.clock()) - 90000
    service.actions.coverage_start = start
    service.store.attest_sandbox_coverage(start, "synthetic:cross-process-ledger")
    prior = action_call(bank, "prepare_unrecognized_charge",
                        {"transaction_id": targets[0], "snapshot": build})
    action_call(bank, "confirm_simulated_intake", {"pending_handle": prior["pending_handle"], "confirmed": True})
    pending = [action_call(bank, "prepare_unrecognized_charge",
                           {"transaction_id": target, "snapshot": build}) for target in targets[1:3]]
    assert all(item["decision"] == "intake" for item in pending)
    ctx = multiprocessing.get_context("spawn")
    ready, barrier, results = ctx.Barrier(3), ctx.Barrier(3), ctx.Queue()
    config_json = service.config.model_copy(update={"sandbox_report_coverage_start": start}).model_dump_json()
    children = [ctx.Process(target=_confirm_in_process,
                            args=(config_json, item["pending_handle"], ready, barrier, results,
                                  ACTION_TEST_WALL_ORIGIN)) for item in pending]
    for child in children:
        child.start()
    ready.wait(timeout=15)
    # Hold the writer while both children enter confirm. On the old path both
    # captured a stale upper window bound before acquiring the writer, then
    # each excluded the other's later case and incorrectly created two cases.
    with service.store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        barrier.wait(timeout=15)
        time.sleep(0.3)
    for child in children:
        child.join(25)
        assert child.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in children) == ["created", "handoff_required"]
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 2


def test_revoke_winning_during_target_recheck_prevents_case_insert(bank, monkeypatch):
    service = bank[0]
    build, targets = owned_action_target(bank)
    start = int(service.actions.clock()) - 90000
    service.actions.coverage_start = start
    service.store.attest_sandbox_coverage(start, "synthetic:revoke-race-ledger")
    pending = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[0], "snapshot": build})
    principal = principal_for(service.store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60)
    entered, release = threading.Event(), threading.Event()
    original = service.repository.owned_transaction_id
    def held(*args):
        entered.set()
        assert release.wait(10)
        return original(*args)
    monkeypatch.setattr(service.repository, "owned_transaction_id", held)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(service.actions.confirm, principal, pending["pending_handle"], True)
        assert entered.wait(10)
        service.store.revoke("session-alice", principal=principal)
        release.set()
        with pytest.raises(BankError, match="authorization_denied"):
            future.result(timeout=10)
    with service.store.connect() as db:
        assert db.execute("SELECT count(*) FROM sandbox_cases").fetchone()[0] == 0


def test_action_r16_utc_window_lower_boundary_and_incomplete_ledger(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    assert len(set(targets)) >= 3
    frozen = service.actions.clock()
    service.actions.clock = lambda: frozen
    service.actions.coverage_start = int(frozen - 90000)
    service.store.attest_sandbox_coverage(service.actions.coverage_start, "synthetic:bank-test-ledger")
    customer = service.config.principal_customers["alice"]
    principal = principal_for(service.store, "alice", customer, "session-alice",
                              "conversation-alice", int(time.time()) + 60)
    with service.store.connect() as db:
        for index, created_at in enumerate([frozen - 86400, frozen - 86400 - 0.001]):
            snapshot, row = service.repository.owned_transaction_id(principal, targets[index], build)
            facts = service.repository._visible(row, snapshot)
            case_id = f"CMP-SBX-TEST{index:04d}"
            db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)",
                (case_id, customer, targets[index], "simulated_intake", build, created_at, json.dumps(facts)))
            receipt = {"id": case_id, "kind": "simulated_intake", "simulated": True,
                       "snapshot": build, "created_at": datetime.fromtimestamp(created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
                       "status": "received", "transaction": facts}
            db.execute("INSERT INTO sandbox_case_receipts VALUES (?,?)", (case_id, json.dumps(receipt)))
    prepared = action_call(bank, "prepare_unrecognized_charge",
                           {"transaction_id": targets[2], "snapshot": build})
    assert prepared["risk"]["unrecognized_count_24h"] == 2
    assert prepared["decision"] == "intake"
    with service.store.connect() as db:
        db.execute("UPDATE sandbox_cases SET created_at=? WHERE transaction_id=?",
                   (frozen - 86400 + 0.001, targets[1]))
        receipt = json.loads(db.execute("SELECT receipt_json FROM sandbox_case_receipts WHERE case_id='CMP-SBX-TEST0001'").fetchone()[0])
        receipt["created_at"] = datetime.fromtimestamp(frozen - 86400 + 0.001, timezone.utc).isoformat().replace("+00:00", "Z")
        db.execute("UPDATE sandbox_case_receipts SET receipt_json=? WHERE case_id='CMP-SBX-TEST0001'", (json.dumps(receipt),))
    threshold = action_call(bank, "prepare_unrecognized_charge",
                            {"transaction_id": targets[2], "snapshot": build})
    assert threshold["risk"]["unrecognized_count_24h"] == 3
    assert threshold["decision"] == "handoff" and threshold["reason"] == "high_risk"
    service.actions.coverage_start = int(frozen - 3600)
    unavailable = action_call(bank, "prepare_unrecognized_charge",
                              {"transaction_id": targets[2], "snapshot": build})
    assert unavailable["risk"]["unrecognized_count_24h"] is None
    assert unavailable["reason"] == "missing_evidence"


def test_action_age_boundary_routes_day_121_to_handoff(bank):
    service = bank[0]
    build, targets = owned_action_target(bank)
    boundary = datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp()
    service.actions.clock = lambda: boundary
    service.actions.coverage_start = int(boundary) - 90000
    service.store.attest_sandbox_coverage(service.actions.coverage_start,
                                           "synthetic:age-boundary-ledger")
    within = action_call(bank, "prepare_unrecognized_charge",
                         {"transaction_id": targets[0], "snapshot": build})
    expired = action_call(bank, "prepare_unrecognized_charge",
                          {"transaction_id": targets[1], "snapshot": build})
    assert within["transaction"]["transaction_date"].startswith("2026-06-02")
    assert within["decision"] == "intake" and within["reason"] is None
    assert expired["transaction"]["transaction_date"].startswith("2026-06-01")
    assert expired["decision"] == "handoff" and expired["reason"] == "out_of_policy"


def test_operator_mode_cannot_invoke_or_advertise_action_tools(operator):
    with pytest.raises(BankError, match="authorization_denied"):
        operator.execute("prepare_unrecognized_charge", {"transaction_id": "forged", "snapshot": "build"})


def test_missing_principal_denied_before_data_access(bank, monkeypatch):
    monkeypatch.setattr(bank[0].repository, "snapshot", lambda: pytest.fail("dataset was touched"))
    with pytest.raises(BankError, match="authorization_required"):
        bank[0].execute("list_my_transactions", {})


@pytest.mark.parametrize("overrides", [
    {"aud": "other-server"}, {"iss": "browser"}, {"scope": ["bank:write"]},
    {"tool": "get_my_transaction"}, {"exp": 0}, {"exp": int(time.time()) + 3600},
    {"sub": "unknown"}, {"iat": "123"}, {"jti": ""},
])
def test_invalid_claims_denied(bank, overrides):
    with pytest.raises(BankError, match="authorization_denied"):
        bank[0].execute("list_my_transactions", {}, assertion(bank, "list_my_transactions", {}, **overrides))


def test_unsigned_and_unknown_keys_denied(bank):
    for token in (jwt.encode({"sub": "alice"}, "", algorithm="none"),
                  jwt.encode({"sub": "alice"}, Ed25519PrivateKey.generate(), algorithm="EdDSA",
                             headers={"kid": "unknown", "typ": TOKEN_TYPE})):
        with pytest.raises(BankError, match="authorization_denied"):
            bank[0].execute("list_my_transactions", {}, {ASSERTION_META: token})


def test_arguments_bound_and_assertion_not_reusable(bank):
    meta = assertion(bank, "list_my_transactions", {"limit": 1})
    with pytest.raises(BankError, match="authorization_denied"):
        bank[0].execute("list_my_transactions", {"limit": 2}, meta)
    assert len(bank[0].execute("list_my_transactions", {"limit": 1}, meta)["transactions"]) == 1
    with pytest.raises(BankError, match="authorization_denied"):
        bank[0].execute("list_my_transactions", {"limit": 1}, meta)


@pytest.mark.parametrize("args", [{"customer_id": ""}, {"customer_id": 3}, {"customer_id": None},
                                 {"limit": 100}, {"limit": "1"},
                                 {"bucket": "other"}, {"start_date": "2026-02-31"}])
def test_strict_business_schema(bank, args):
    with pytest.raises(BankError, match="invalid_arguments|authorization_denied"):
        call(bank, args=args)


@pytest.fixture
def operator(dataset, tmp_path):
    service = Service(Config(mode="operator-test", data_dir=dataset / "out", state_db=tmp_path / "operator.db",
                             service_token="y" * 48, approved_customers={cid(3), cid(4)}))
    yield service
    service.close()


@pytest.mark.parametrize("args", [
    {}, {"conversation_id": "test-thread"}, {"customer_id": cid(3)},
    {"customer_id": cid(999), "conversation_id": "test-thread"},
    {"customer_id": cid(3), "conversation_id": "@current.conversation.id"},
    {"customer_id": cid(3), "conversation_id": "${unresolved}"},
    {"customer_id": cid(3), "conversation_id": "thread with spaces"},
    {"customer_id": cid(3), "conversation_id": ""},
])
def test_operator_requires_approved_selection_and_resolved_correlation(operator, monkeypatch, args):
    monkeypatch.setattr(operator.repository, "snapshot", lambda: pytest.fail("unauthorized dataset read"))
    with pytest.raises(BankError, match="authorization_denied"):
        operator.execute("list_my_transactions", args)


def test_explicit_operator_config_and_unchanged_demo_guard(bank):
    base = dict(data_dir=bank[0].config.data_dir, state_db=bank[0].config.state_db, service_token="z" * 48)
    for values in ({"mode": "operator-test"}, {"mode": "operator-test", "approved_customers": {" "}},
                   {"mode": "delegated", "approved_customers": {cid(3)}},
                   {"mode": "synthetic-demo", "demo_customer": cid(3), "approved_customers": {cid(3)}}):
        with pytest.raises(ValueError):
            Config(**base, **values)
    # A provided selector does not allow the real server to fall back to operator access.
    with pytest.raises(BankError, match="authorization_required"):
        bank[0].execute("list_my_transactions", {"customer_id": cid(3), "conversation_id": "thread"})


@pytest.mark.parametrize("args", [{"customer_id": cid(4)}, {"conversation_id": "conversation-bob"}])
def test_bound_foreign_selector_or_correlation_denied_before_lookup(bank, monkeypatch, args):
    monkeypatch.setattr(bank[0].repository, "snapshot", lambda: pytest.fail("foreign selector reached lookup"))
    with pytest.raises(BankError, match="authorization_denied"):
        call(bank, args=args)


def test_bound_optional_selector_matches_verified_identity(bank):
    omitted = call(bank)["transactions"]
    selected = call(bank, args={"customer_id": cid(3), "conversation_id": "conversation-alice"})["transactions"]
    assert [r["transaction_reference"] for r in omitted] == [r["transaction_reference"] for r in selected]
    args = {"selection_handle": selected[0]["selection_handle"], "customer_id": cid(3)}
    assert call(bank, "get_my_transaction", args)["transaction"]


def test_operator_customer_switch_and_foreign_thread_handles(operator):
    context = {"customer_id": cid(3), "conversation_id": "slack-" + "a" * 48}
    first = operator.execute("list_my_transactions", {**context, "limit": 1})
    assert first["synthetic"] and first["operator_test"]
    assert first["next_cursor"]
    handle = first["transactions"][0]["selection_handle"]
    for foreign in ({**context, "customer_id": cid(4)}, {**context, "conversation_id": "slack-" + "b" * 48}):
        for tool, extra in (("get_my_transaction", {"selection_handle": handle}),
                            ("list_my_transactions", {"cursor": first["next_cursor"]})):
            with pytest.raises(BankError, match="reference_unavailable"):
                operator.execute(tool, {**foreign, **extra})
    assert operator.execute("get_my_transaction", {**context, "selection_handle": handle})["transaction"]
    assert operator.execute("list_my_transactions", {**context, "customer_id": cid(4)})["transactions"]


def test_operator_parallel_context_does_not_mix_handles(operator):
    def one(i):
        context = {"customer_id": cid(3 if i % 2 == 0 else 4), "conversation_id": f"thread-{i}"}
        listed = operator.execute("list_my_transactions", {**context, "limit": 1})
        row = listed["transactions"][0]
        found = operator.execute("get_my_transaction", {**context, "selection_handle": row["selection_handle"]})
        assert found["transaction"]["transaction_reference"] == row["transaction_reference"]
        with pytest.raises(BankError, match="reference_unavailable"):
            operator.execute("get_my_transaction", {**context, "conversation_id": f"foreign-{i}",
                                                    "selection_handle": row["selection_handle"]})
        return row["transaction_reference"]
    with ThreadPoolExecutor(max_workers=16) as pool:
        references = list(pool.map(one, range(100)))
    assert len(set(references[::2])) == len(set(references[1::2])) == 1
    assert references[0] != references[1]


def test_missing_published_bucket_is_not_empty_history(bank, tmp_path):
    import shutil
    from pipeline.common import bucket_for
    copied = tmp_path / "copied"
    shutil.copytree(bank[0].config.data_dir, copied)
    service = Service(bank[0].config.model_copy(update={"data_dir": copied, "state_db": tmp_path / "copy.db"}))
    try:
        assert call((service, bank[1]))["transactions"]
        bucket = service.repository.snapshot().gold / f"bucket={bucket_for(cid(3))}"
        # Even a loaded snapshot must detect files disappearing underneath it.
        shutil.rmtree(bucket)
        with pytest.raises(BankError, match="dataset_unavailable"):
            call((service, bank[1]))
        service.repository._snapshot = None
        assert not service.execute("banking_status", {})["dataset_ready"]
    finally:
        service.close()


def test_legacy_snapshot_without_file_inventory_fails_closed(bank, tmp_path):
    import shutil
    copied = tmp_path / "legacy"
    shutil.copytree(bank[0].config.data_dir, copied)
    service = Service(bank[0].config.model_copy(update={"data_dir": copied, "state_db": tmp_path / "legacy.db"}))
    try:
        build = copied / "builds" / (copied / "CURRENT").read_text().strip()
        manifest = json.loads((build / "snapshot.json").read_text())
        manifest.pop("gold_files")
        (build / "snapshot.json").write_text(json.dumps(manifest))
        with pytest.raises(BankError, match="dataset_unavailable"):
            call((service, bank[1]))
    finally:
        service.close()


def test_repository_shutdown_closes_connection(bank):
    bank[0].close()
    bank[0].close()
    assert bank[0].repository.con is None
    assert not bank[0].execute("banking_status", {})["dataset_ready"]


def test_operator_stdio_selector_contract_and_concurrent_handles(operator, tmp_path):
    import asyncio
    import sys
    from pathlib import Path
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    config = tmp_path / "operator.json"
    config.write_text(operator.config.model_dump_json())

    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "banking_mcp", "serve", "--config", str(config)],
            cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = {tool.name: tool.inputSchema for tool in (await client.list_tools()).tools}
                assert set(tools) == {"banking_status", "list_my_transactions", "get_my_transaction"}
                for name in ("list_my_transactions", "get_my_transaction"):
                    assert {"customer_id", "conversation_id"} <= set(tools[name]["properties"])
                    assert "customer_id" not in tools[name].get("required", [])
                    assert tools[name]["properties"]["customer_id"]["type"] == "string"
                status = await client.call_tool("banking_status", {})
                assert status.structuredContent["customer_selection_required"]
                denied = await client.call_tool("list_my_transactions", {})
                assert denied.isError and denied.structuredContent["error"] == "authorization_denied"

                async def one(i):
                    context = {"customer_id": cid(3 if i % 2 == 0 else 4), "conversation_id": f"slack-{i:048x}"}
                    listed = await client.call_tool("list_my_transactions", {**context, "limit": 1})
                    assert not listed.isError
                    row = listed.structuredContent["transactions"][0]
                    found = await client.call_tool("get_my_transaction", {**context, "selection_handle": row["selection_handle"]})
                    assert not found.isError
                    assert found.structuredContent["transaction"]["transaction_reference"] == row["transaction_reference"]
                    foreign = await client.call_tool("get_my_transaction", {**context,
                        "conversation_id": f"other-{i}", "selection_handle": row["selection_handle"]})
                    assert foreign.isError and foreign.structuredContent["error"] == "reference_unavailable"
                    return row["transaction_reference"]

                refs = await asyncio.gather(*(one(i) for i in range(20)))
                assert refs[0] != refs[1]
                assert len(set(refs[::2])) == len(set(refs[1::2])) == 1
    anyio.run(exercise)


def test_bounded_queue_rejects_overflow_and_expired_authority(bank, monkeypatch):
    import asyncio
    import threading
    import anyio
    service = Service(bank[0].config.model_copy(update={"max_active_reads": 1, "max_queued_reads": 1}))
    active, release = threading.Event(), threading.Event()
    reads = []
    original = service.repository.list_transactions

    def delayed(*args):
        reads.append(args[0].customer)
        active.set()
        assert release.wait(5), "test did not release blocked read"
        return original(*args)

    monkeypatch.setattr(service.repository, "list_transactions", delayed)
    meta_a = assertion(bank, "list_my_transactions", {})
    meta_b = assertion(bank, "list_my_transactions", {}, subject="bob")
    now = int(time.time())

    async def exercise():
        first = asyncio.create_task(service.call("list_my_transactions", {}, meta_a))
        second = None
        try:
            async with asyncio.timeout(5):
                while not active.is_set():
                    await asyncio.sleep(0.01)
            second = asyncio.create_task(service.call("list_my_transactions", {}, meta_b))
            await asyncio.sleep(0)
            with pytest.raises(BankError, match="server_busy"):
                await service.call("list_my_transactions", {}, meta_b)
            # The queue cannot turn old signed authority into a fresh customer read.
            monkeypatch.setattr("banking_mcp.security.time.time", lambda: now + 61)
            release.set()
            for task in (first, second):
                with pytest.raises(BankError, match="authorization_denied"):
                    await task
            assert len(reads) == 1
            assert service._pending == 0
        finally:
            release.set()
            await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
    try:
        anyio.run(exercise)
    finally:
        service.close()


def test_revoke_before_and_after_read(bank, monkeypatch):
    original = bank[0].repository.list_transactions
    def revoke_during(*args, **kwargs):
        result = original(*args, **kwargs)
        bank[0].store.revoke("session-alice", principal=principal_for(
            bank[0].store, "alice", cid(3), "session-alice", "conversation-alice", int(time.time()) + 60))
        return result
    monkeypatch.setattr(bank[0].repository, "list_transactions", revoke_during)
    with pytest.raises(BankError, match="authorization_denied"):
        call(bank)
    monkeypatch.setattr(bank[0].repository, "snapshot", lambda: pytest.fail("revoked access touched dataset"))
    with pytest.raises(BankError, match="authorization_denied"):
        call(bank)


def test_session_cannot_rebind_to_another_subject_after_restart(bank):
    service, key = bank
    call(bank)
    reopened = Service(service.config)
    with pytest.raises(BankError, match="authorization_denied"):
        call((reopened, key), subject="bob", session_id="session-alice")


def revoke_token(bank, **overrides):
    meta = assertion(bank, "revoke_session", {}, scope=["bank:revoke"], **overrides)
    claims = jwt.decode(meta[ASSERTION_META], options={"verify_signature": False})
    return jwt.encode(claims, bank[1], algorithm="EdDSA", headers={"kid": "test", "typ": "bank-revoke+jwt"})


def test_http_revocation_requires_separate_typed_signed_authority(bank, monkeypatch):
    service, _ = bank
    with TestClient(create_http_app(service)) as client:
        url = "/internal/revoke"
        auth = {"Authorization": "Bearer " + service.config.service_token}
        token = revoke_token(bank)
        assert client.post(url, json={"assertion": token}).status_code == 401
        read_token = assertion(bank, "list_my_transactions", {})[ASSERTION_META]
        assert client.post(url, headers=auth, json={"assertion": read_token}).status_code == 403
        assert client.post(url, headers=auth, json={"assertion": token, "session_id": "session-bob"}).status_code == 403
        assert client.post(url, headers=auth, json={"assertion": token}).status_code == 200
        assert client.post(url, headers=auth, json={"assertion": token}).status_code == 403
        assert client.post(url, headers=auth, json={"assertion": revoke_token(bank)}).status_code == 200
    reopened = Service(service.config)
    monkeypatch.setattr(reopened.repository, "snapshot", lambda: pytest.fail("revoked access touched dataset"))
    with pytest.raises(BankError, match="authorization_denied"):
        call((reopened, bank[1]))


def test_revocation_cannot_target_another_subjects_session(bank):
    call(bank, subject="bob")
    with pytest.raises(BankError, match="authorization_denied"):
        bank[0].auth.revoke_assertion(revoke_token(bank, session_id="session-bob"))
    assert not bank[0].store.is_revoked("session-bob")


def test_output_minimized_and_cross_customer_handle_denied(bank):
    result = call(bank)
    assert not result["synthetic"]  # delegated mode is exercised with a synthetic fixture
    row = result["transactions"][0]
    forbidden = {"customer_id", "product_id", "transaction_id", "is_fraud", "fraud_score",
                 "_source_file", "_row_hash", "source_key", "audit"}
    assert forbidden.isdisjoint(row)
    with pytest.raises(BankError, match="reference_unavailable"):
        call(bank, "get_my_transaction", {"selection_handle": row["selection_handle"]}, "bob")
    selected = call(bank, "get_my_transaction", {"selection_handle": row["selection_handle"]})
    assert selected["transaction"]["transaction_reference"] == row["transaction_reference"]
    with pytest.raises(BankError, match="reference_unavailable"):
        call(bank, "get_my_transaction", {"selection_handle": row["selection_handle"]},
             session_id="other-session")


def test_cursor_paging_and_foreign_cursor_denied(bank):
    result = call(bank, args={"limit": 1})
    assert result["next_cursor"]
    second = call(bank, args={"limit": 1, "cursor": result["next_cursor"]})
    assert second["transactions"][0]["transaction_reference"] != result["transactions"][0]["transaction_reference"]
    with pytest.raises(BankError, match="reference_unavailable"):
        call(bank, args={"cursor": result["next_cursor"]}, subject="bob")
    with pytest.raises(BankError, match="invalid_date_window"):
        call(bank, args={"start_date": "2025-01-01", "end_date": "2026-06-02"})


def test_pinned_lineage_and_owner_recheck(bank):
    snapshot = bank[0].repository.snapshot()
    assert (snapshot.build / "snapshot.json").is_file()
    assert "customers.csv" in snapshot.objects
    snapshot.products["PRD000003"] = (cid(4), "other")
    try:
        with pytest.raises(BankError, match="data_quality_error"):
            call(bank)
    finally:
        snapshot.products["PRD000003"] = (cid(3), "product_type_x")


def test_500_interleaved_reads_preserve_customer_isolation(bank):
    expected = {subject: {r["transaction_reference"] for r in call(bank, subject=subject)["transactions"]}
                for subject in ("alice", "bob")}
    assert expected["alice"].isdisjoint(expected["bob"])
    def one(i):
        subject = "alice" if i % 2 == 0 else "bob"
        result = call(bank, args={"limit": 1}, subject=subject)
        return all(r["transaction_reference"] in expected[subject] for r in result["transactions"])
    with ThreadPoolExecutor(max_workers=16) as pool:
        assert all(pool.map(one, range(500)))


def test_concurrent_replay_consumption_across_store_instances_has_one_winner(tmp_path):
    import threading
    path = tmp_path / "shared.db"
    stores = [StateStore(path, ledger_continuity_approved=True) for _ in range(16)]
    principal = principal_for(stores[0], "alice", cid(3), "session-alice", "conversation-alice",
                              int(time.time()) + 60)
    start = threading.Barrier(len(stores))

    def one(store):
        start.wait(timeout=10)
        try:
            store.consume("same-jti", principal.expires, principal=principal)
            return True
        except BankError as exc:
            assert exc.code == "authorization_denied"
            return False

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        assert sum(pool.map(one, stores)) == 1
    # A fresh store cannot replay the winner either.
    with pytest.raises(BankError, match="authorization_denied"):
        StateStore(path, ledger_continuity_approved=True).consume(
            "same-jti", principal.expires, principal=principal)


def test_concurrent_session_binding_and_revocation_across_store_instances(tmp_path):
    import threading
    path = tmp_path / "shared.db"
    stores = [StateStore(path, ledger_continuity_approved=True) for _ in range(16)]
    start = threading.Barrier(len(stores))

    def one(i):
        subject = "alice" if i % 2 == 0 else "bob"
        principal = principal_for(stores[i], subject, cid(3 if i % 2 == 0 else 4), "shared-session",
                              f"conversation-{subject}", int(time.time()) + 60)
        start.wait(timeout=10)
        try:
            stores[i].bind_session(principal)
            return subject
        except BankError as exc:
            assert exc.code == "authorization_denied"
            return None

    with ThreadPoolExecutor(max_workers=len(stores)) as pool:
        accepted = [subject for subject in pool.map(one, range(len(stores))) if subject]
    assert len(accepted) == 8 and len(set(accepted)) == 1
    subject = accepted[0]
    principal = principal_for(stores[0], subject, cid(3 if subject == "alice" else 4),
                              "shared-session", f"conversation-{subject}", int(time.time()) + 60)
    stores[0].revoke("shared-session", principal=principal)
    assert all(store.is_revoked("shared-session") for store in stores)
    assert StateStore(path).is_revoked("shared-session")


def test_external_sqlite_writer_contention_does_not_drop_replay_or_revocation(tmp_path):
    import sqlite3
    import threading
    path = tmp_path / "shared.db"
    store = StateStore(path, ledger_continuity_approved=True)
    principal = principal_for(store, "alice", cid(3), "contended-session", "conversation-alice",
                              int(time.time()) + 60)
    started = threading.Event()

    def consume_and_revoke():
        started.set()
        store.consume("contended-jti", principal.expires, principal=principal)
        store.revoke("contended-session", principal=principal)

    # A raw connection is outside our process gate, like the private revoke CLI.
    external = sqlite3.connect(path)
    try:
        external.execute("BEGIN IMMEDIATE")
        external.execute("INSERT INTO revoked VALUES (?)", ("external-session",))
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(consume_and_revoke)
            try:
                assert started.wait(5)
                assert not future.done()
            finally:
                external.commit()
            future.result(timeout=10)
    finally:
        external.close()
    assert store.is_revoked("external-session") and store.is_revoked("contended-session")
    with pytest.raises(BankError, match="authorization_denied"):
        store.consume("contended-jti", principal.expires, principal=principal)


def test_authority_expiring_during_state_wait_is_denied(bank, monkeypatch):
    now = int(time.time())
    principal = principal_for(bank[0].store, "alice", cid(3), "session-alice", "conversation-alice", now + 60)

    from contextlib import contextmanager
    connect = bank[0].store.connect
    @contextmanager
    def delayed_connection():
        with connect() as db:
            # Authority now reads revocation within the SQLite transaction.
            # Model a wait ending after expiry at that actual boundary.
            monkeypatch.setattr("banking_mcp.security.time.time", lambda: now + 61)
            yield db

    monkeypatch.setattr(bank[0].store, "connect", delayed_connection)
    with pytest.raises(BankError, match="authorization_denied"):
        bank[0].auth.assert_current(principal)


def test_http_service_bearer_and_mcp_request_metadata(bank):
    headers = {"Authorization": "Bearer " + bank[0].config.service_token,
               "Accept": "application/json, text/event-stream"}
    with TestClient(create_http_app(bank[0]), base_url="http://127.0.0.1:43421") as client:
        assert client.post("/mcp", json={}).status_code == 401
        init = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {},
                       "clientInfo": {"name": "bank-test", "version": "1"}}})
        assert init.status_code == 200, init.text
        assert set(init.json()["result"]["capabilities"]) <= {"tools", "experimental"}
        request = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                   "params": {"name": "list_my_transactions", "arguments": {}}}
        denied = client.post("/mcp", headers=headers, json=request).json()["result"]
        assert denied["isError"] and denied["structuredContent"]["error"] == "authorization_required"
        request["params"]["_meta"] = assertion(bank, "list_my_transactions", {})
        result = client.post("/mcp", headers=headers, json=request).json()["result"]
        assert not result.get("isError") and result["structuredContent"]["transactions"]
        assert client.get("/mcp", headers=headers).status_code == 405


def test_synthetic_mode_cannot_use_an_unmarked_real_dataset(bank):
    with pytest.raises(ValueError):
        Config(mode="synthetic-demo", data_dir=bank[0].config.data_dir,
               state_db=bank[0].config.state_db, service_token="x" * 48, demo_customer=cid(3))


def test_replay_and_handles_survive_server_restart(bank):
    meta = assertion(bank, "list_my_transactions", {})
    result = bank[0].execute("list_my_transactions", {}, meta)
    restarted = Service(bank[0].config), bank[1]
    with pytest.raises(BankError, match="authorization_denied"):
        restarted[0].execute("list_my_transactions", {}, meta)
    handle = result["transactions"][0]["selection_handle"]
    assert call(restarted, "get_my_transaction", {"selection_handle": handle})["transaction"]


def test_changed_snapshot_invalidates_selection_and_cursor(bank):
    result = call(bank, args={"limit": 1})
    snapshot = bank[0].repository.snapshot()
    old_id = snapshot.id
    # Simulate publication without mutating the module's shared fixture.
    snapshot.id = "a-new-build"
    try:
        original_snapshot = bank[0].repository.snapshot
        bank[0].repository.snapshot = lambda: snapshot
        with pytest.raises(BankError, match="reference_unavailable"):
            call(bank, "get_my_transaction", {"selection_handle": result["transactions"][0]["selection_handle"]})
        with pytest.raises(BankError, match="reference_unavailable"):
            call(bank, args={"cursor": result["next_cursor"]})
    finally:
        snapshot.id = old_id
        bank[0].repository.snapshot = original_snapshot


@pytest.mark.parametrize("mutation,expected", [
    (None, None), ("foreign-customer", "reference_unavailable"),
    ("foreign-product", "reference_unavailable"), ("amount", "snapshot_changed"),
    ("duplicate", "reference_unavailable"), ("etag", "source_verification_unavailable"),
])
def test_source_readback_pins_objects_and_rechecks_ownership(bank, dataset, monkeypatch, mutation, expected):
    import boto3
    import banking_mcp.repository as repository_module
    config = bank[0].config.model_copy(update={"source_env": dataset / "not-real.env"})
    checked = Service(config), bank[1]
    result = call(checked, args={"limit": 1})
    handle = result["transactions"][0]["selection_handle"]
    calls = []
    monkeypatch.setattr(repository_module, "load_env", lambda _: {
        "Region": "test", "BucketName": "test", "AccessKeyID": "test", "SecretAccessKey": "test"})
    snapshot = checked[0].repository.snapshot()

    class Source:
        def head_object(self, **kwargs):
            calls.append(kwargs)
            if mutation == "etag":
                raise RuntimeError("private AWS details")
            return {}

        def get_object(self, **kwargs):
            calls.append(kwargs)
            reader = csv.DictReader(io.StringIO((dataset / "src" / kwargs["Key"][5:]).read_text()))
            records = list(reader)
            # This customer's rows are the only rows eligible for a selected handle.
            selected = [r for r in records if r["customer_id"] == cid(3)]
            for row in selected:
                if mutation == "foreign-customer":
                    row["customer_id"] = cid(4)
                elif mutation == "foreign-product":
                    row["product_id"] = "PRD000004"
                elif mutation == "amount":
                    row["amount"] = "999999.99"
            if mutation == "duplicate":
                records += [r.copy() for r in selected]
            output = io.StringIO()
            writer = csv.DictWriter(output, reader.fieldnames)
            writer.writeheader()
            writer.writerows(records)
            return {"Body": io.BytesIO(output.getvalue().encode())}

        def close(self):
            pass

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: Source())
    args = {"selection_handle": handle, "verify_source": True}
    if expected:
        with pytest.raises(BankError, match=expected):
            call(checked, "get_my_transaction", args)
    else:
        assert call(checked, "get_my_transaction", args)["freshness"] == "verified_against_pinned_source"
    assert calls
    for request in calls:
        assert request["IfMatch"] == snapshot.objects[request["Key"][5:]]["etag"]


def test_http_rejects_untrusted_host_and_origin(bank):
    headers = {"Authorization": "Bearer " + bank[0].config.service_token,
               "Accept": "application/json, text/event-stream"}
    with TestClient(create_http_app(bank[0]), base_url="http://127.0.0.1:43421") as client:
        assert client.post("/mcp", headers={**headers, "Host": "evil.example"}, json={}).status_code == 421
        assert client.post("/mcp", headers={**headers, "Origin": "https://evil.example"}, json={}).status_code == 403


def test_stdio_child_process_and_private_revocation(bank, tmp_path):
    import anyio
    import subprocess
    import sys
    from pathlib import Path
    from textwrap import dedent
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    service, _ = bank
    build, targets = owned_action_target(bank)
    # The child action clock is synthetic; the 120-day policy boundary must
    # not depend on the wall date used by authentication and revocation.
    action_day = datetime.fromtimestamp(ACTION_TEST_NOW, timezone.utc).date()
    assert (action_day - datetime(2026, 6, 2, tzinfo=timezone.utc).date()).days == 119
    assert (action_day - datetime(2026, 5, 31, tzinfo=timezone.utc).date()).days == 121
    config = tmp_path / "bank.json"
    config.write_text(service.config.model_dump_json())
    repo = Path(__file__).resolve().parents[1]
    # The CLI creates a new Service, so the parent fixture's action clock does
    # not reach it. Keep June transactions in policy while JWT/revocation time
    # still uses the real clock and the normal CLI/stdio paths remain exercised.
    launcher = dedent(f"""\
        import time
        from banking_mcp import __main__ as cli
        class FixtureService(cli.Service):
            def __init__(self, config):
                super().__init__(config)
                self.actions.clock = lambda: {ACTION_TEST_NOW!r} + (time.time() - {ACTION_TEST_WALL_ORIGIN!r})
        cli.Service = FixtureService
        raise SystemExit(cli.main())
        """)
    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=["-c", launcher, "serve", "--config", str(config)], cwd=str(repo))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert {t.name for t in (await client.list_tools()).tools} == {
                    "banking_status", "list_my_transactions", "get_my_transaction",
                    "prepare_unrecognized_charge", "confirm_simulated_intake", "read_intake_receipt",
                    "create_verified_handoff", "read_verified_handoff"}
                args = {"limit": 1}
                result = await client.call_tool("list_my_transactions", args,
                    meta=assertion(bank, "list_my_transactions", args))
                assert not result.isError
                assert len(json.loads(result.content[0].text)["transactions"]) == 1
                prepare_args = {"transaction_id": targets[0], "snapshot": build,
                                "request_id": str(uuid.uuid4())}
                prepared = await client.call_tool("prepare_unrecognized_charge", prepare_args,
                    meta=assertion(bank, "prepare_unrecognized_charge", prepare_args, scope=["bank:prepare"]))
                assert not prepared.isError
                pending = json.loads(prepared.content[0].text)
                assert pending["transaction"]["transaction_date"].startswith("2026-06-02")
                # The launcher shares the deterministic action clock with the
                # parent fixture; authentication and revocation use wall time.
                event_date = datetime.fromisoformat(pending["transaction"]["transaction_date"]).date()
                action_now = ACTION_TEST_NOW + (time.time() - ACTION_TEST_WALL_ORIGIN)
                age = (datetime.fromtimestamp(action_now, timezone.utc).date() - event_date).days
                expected_reason = "out_of_policy" if age > 120 else "missing_evidence"
                assert pending["decision"] == "handoff" and pending["reason"] == expected_reason
                handoff_args = {"reason": expected_reason, "pending_handle": pending["pending_handle"]}
                created = await client.call_tool("create_verified_handoff", handoff_args,
                    meta=assertion(bank, "create_verified_handoff", handoff_args, scope=["bank:handoff"]))
                assert not created.isError
                handoff_id = json.loads(created.content[0].text)["handoff"]["id"]
                read_args = {"handoff_id": handoff_id}
                read = await client.call_tool("read_verified_handoff", read_args,
                    meta=assertion(bank, "read_verified_handoff", read_args, scope=["bank:handoff-read"]))
                assert not read.isError and json.loads(read.content[0].text)["handoff"]["id"] == handoff_id
                # A read assertion cannot invoke the private revocation control.
                invalid = subprocess.run([sys.executable, "-m", "banking_mcp", "revoke-session",
                    "--config", str(config)], input=assertion(bank, "revoke_session", {})[ASSERTION_META],
                    text=True, capture_output=True, cwd=repo, timeout=10)
                assert invalid.returncode == 2 and invalid.stdout == ""
                token = assertion(bank, "revoke_session", {}, scope=["bank:revoke"])[ASSERTION_META]
                claims = jwt.decode(token, options={"verify_signature": False})
                token = jwt.encode(claims, bank[1], algorithm="EdDSA",
                    headers={"kid": "test", "typ": "bank-revoke+jwt"})
                revoked = subprocess.run([sys.executable, "-m", "banking_mcp", "revoke-session",
                    "--config", str(config)], input=token, text=True, capture_output=True, cwd=repo, timeout=10)
                assert revoked.returncode == 0 and revoked.stdout == ""
                result = await client.call_tool("list_my_transactions", args,
                    meta=assertion(bank, "list_my_transactions", args))
                assert result.isError and "authorization_denied" in result.content[0].text
    anyio.run(exercise)
