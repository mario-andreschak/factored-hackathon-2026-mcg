"""Pure observer tests over ephemeral synthetic rows, never app/network execution."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import uuid

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from banking_mcp.security import Principal
from scripts.synthetic_integration.frontend_fault import FixtureScope, PrepareBinding, canonical_digest
from scripts.synthetic_integration import frontend_observers as module


def run(awaitable):
    return asyncio.run(awaitable)


@pytest.fixture
def fixture(tmp_path):
    now = int(time.time())
    session, conversation, request_id, action_id = (str(uuid.uuid4()) for _ in range(4))
    issuer, subject, model, deployment = "synthetic-issuer", "synthetic-álîce", "flow-fixture", "synthetic-déploy"
    customer, transaction, snapshot, fingerprint = "fixture-customer-a", "fixture-charge-a", "fixture-build", "d" * 64
    facts = {"transaction_reference": "txn_" + "b" * 12, "transaction_date": datetime.fromtimestamp(now, timezone.utc).isoformat(),
             "process_date": datetime.fromtimestamp(now, timezone.utc).date().isoformat(), "amount": "25.00", "currency": "BRL",
             "status": "Approved", "merchant": "Synthetic fixture merchant", "transaction_type": "Credit",
             "channel": "Online", "product": "Synthetic account"}
    marker = tmp_path / "synthetic_provenance.json"
    marker.write_text(json.dumps({"kind": "team_synthetic_fixture", "build_id": snapshot, "source_fingerprint": fingerprint}))
    paths = module.GeneratedFixturePaths(tmp_path, marker, tmp_path / "frontend.sqlite3",
                                         tmp_path / "frontend-chat.sqlite3", tmp_path / "mcp.sqlite3")
    scope = FixtureScope(fixture_id="observer-source-test", source_fingerprint=fingerprint, profile_id="colombia",
                         worker_origin="http://worker.invalid", issuer=issuer, subject=subject, frontend_session_id=session,
                         frontend_session_exp=now + 3600, frontend_model=model,
                         frontend_owner=module.frontend_owner(issuer, subject, model), bank_deployment_id=deployment,
                         bank_session_id=module.bank_session_id(deployment, issuer, session), customer_id=customer,
                         transaction_id=transaction, snapshot=snapshot, facts_sha256=canonical_digest(facts),
                         ledger_generation="e" * 64,
                         expected_outcome="handoff_verified")
    cookie = "generated-private-cookie-never-output"
    with sqlite3.connect(paths.frontend_state_db) as db:
        db.executescript("""CREATE TABLE profiles(id TEXT PRIMARY KEY,customer_id TEXT);
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,id TEXT UNIQUE,profile_id TEXT,expires_at INTEGER);""")
        db.execute("INSERT INTO profiles VALUES (?,?)", (scope.profile_id, customer))
        db.execute("INSERT INTO sessions VALUES (?,?,?,?)", (hashlib.sha256(cookie.encode()).hexdigest(), session, scope.profile_id, scope.frontend_session_exp))
    with sqlite3.connect(paths.frontend_chat_db) as db:
        db.executescript("""CREATE TABLE chat_sessions(session_id TEXT PRIMARY KEY,owner TEXT,expires INTEGER,
            conversation_id TEXT,revoked INTEGER,subject TEXT,customer_id TEXT);
            CREATE TABLE action_status(session_id TEXT PRIMARY KEY,owner TEXT,expires INTEGER,result_json TEXT,
            action_id TEXT,target_reference TEXT,revision INTEGER,prepare_transaction_id TEXT,
            prepare_snapshot TEXT,prepare_conversation_id TEXT);""")
        db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)", (session, scope.frontend_owner,
                   scope.frontend_session_exp, conversation, 0, subject, customer))
        db.execute("INSERT INTO action_status VALUES (?,?,?,?,?,?,?,?,?,?)", (session, scope.frontend_owner, scope.frontend_session_exp,
                   json.dumps({"state": "preparing", "request_id": request_id}), action_id, "txn_" + "a" * 24, 1,
                   transaction, snapshot, conversation))
    binding = PrepareBinding(request_id, conversation, transaction, snapshot)
    owner_binding = Principal(subject, customer, scope.bank_session_id, conversation, now + 60).binding()
    key = hashlib.sha256(json.dumps([owner_binding, request_id]).encode()).hexdigest()
    handle = "syntheticPendingHandle" + "a" * 22
    provenance = {"source": "owned_serving_snapshot", "snapshot": snapshot,
                  "as_of": datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")}
    packet = {"schema": "banking-sandbox-handoff/v1", "transaction": facts, "transaction_provenance": provenance,
              "reason": "missing_evidence", "unanswered_questions": [], "human_responded": False}
    response = {"state": "handoff_verified", "pending_handle": handle, "snapshot": snapshot, "action": "simulated_intake",
                "decision": "handoff", "reason": "missing_evidence", "transaction": facts,
                "handoff": {"id": "HOF-abcdefgh", "reason": "missing_evidence", "snapshot": snapshot,
                            "created_at": provenance["as_of"], "facts": facts, "packet": packet,
                            "transaction_currentness": "same_snapshot", "human_responded": False}}
    with sqlite3.connect(paths.mcp_state_db) as db:
        db.executescript("""CREATE TABLE sessions(session TEXT PRIMARY KEY,subject TEXT,customer TEXT);
            CREATE TABLE revoked(session TEXT PRIMARY KEY);
            CREATE TABLE action_pending(id TEXT PRIMARY KEY,binding TEXT,customer TEXT,transaction_id TEXT,
            snapshot TEXT,action TEXT,decision TEXT,reason TEXT,facts TEXT,expires REAL,request_key TEXT UNIQUE,
            result_json TEXT,confirmation_state TEXT);
            CREATE TABLE sandbox_handoffs(id TEXT PRIMARY KEY,binding TEXT,customer TEXT,transaction_id TEXT,
            snapshot TEXT,reason TEXT,created_at REAL,facts TEXT,idempotency_key TEXT UNIQUE,packet_json TEXT);
            CREATE TABLE sandbox_ledger_identity(id INTEGER PRIMARY KEY,generation TEXT);
            CREATE TABLE sandbox_coverage(id INTEGER PRIMARY KEY,generation TEXT,coverage_start INTEGER,
            provenance_digest TEXT,attested_at INTEGER);
            CREATE TABLE sandbox_cases(id TEXT PRIMARY KEY,customer TEXT,transaction_id TEXT,action TEXT,snapshot TEXT,created_at REAL,facts TEXT);
            CREATE TABLE sandbox_case_receipts(case_id TEXT PRIMARY KEY,receipt_json TEXT);""")
        db.execute("INSERT INTO sandbox_ledger_identity VALUES (1,?)", (scope.ledger_generation,))
        db.execute("INSERT INTO sessions VALUES (?,?,?)", (scope.bank_session_id, subject, customer))
        result = {k: response[k] for k in ("snapshot", "action", "decision", "reason", "transaction")}
        window_end = datetime.fromtimestamp(now - 10, timezone.utc)
        result.update(risk={"coverage": "sandbox_only", "source": "sandbox_cases", "risk_data_complete": False,
                           "unrecognized_count_24h": None,
                           "window_start": datetime.fromtimestamp(now - 10 - 86400, timezone.utc).isoformat().replace("+00:00", "Z"),
                           "window_end": window_end.isoformat().replace("+00:00", "Z")},
                      existing_case={"state": "not_found", "receipt": None})
        db.execute("INSERT INTO action_pending VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (hashlib.sha256(handle.encode()).hexdigest(), owner_binding,
                   customer, transaction, snapshot, "simulated_intake", "handoff", "missing_evidence", json.dumps(facts), now + 590, key,
                   json.dumps(result), "prepared"))
        db.execute("INSERT INTO sandbox_handoffs VALUES (?,?,?,?,?,?,?,?,?,?)", ("HOF-abcdefgh", owner_binding,
                   customer, transaction, snapshot, "missing_evidence", now, json.dumps(facts, sort_keys=True), key, json.dumps(packet, sort_keys=True)))
    private_key = Ed25519PrivateKey.generate()
    observer = module.FrontendObservers(paths, scope, {"fixture-key": private_key.public_key()})
    return {"paths": paths, "scope": scope, "binding": binding, "observer": observer, "private_key": private_key,
            "cookie": cookie, "response": response, "facts": facts, "key": key, "action_id": action_id, "now": now}


def update(path, table, field, value):
    with sqlite3.connect(path) as db:
        db.execute(f"UPDATE {table} SET {field}=?", (value,))


def assertion(fixture, *, private_key=None, header=None, **overrides):
    now, scope = int(time.time()), fixture["scope"]
    claims = {"iss": scope.issuer, "aud": "flujo-banking-ingress", "sub": scope.subject,
              "session_id": scope.frontend_session_id, "session_exp": scope.frontend_session_exp,
              "iat": now, "nbf": now, "exp": now + 100, "jti": str(uuid.uuid4()), "scope": ["bank:read"], **overrides}
    token = jwt.encode(claims, private_key or fixture["private_key"], algorithm="EdDSA",
                       headers=header or {"kid": "fixture-key", "typ": "flujo-ingress+jwt"})
    return token, httpx.Headers({"X-Flujo-User-Assertion": token})


def commit(fixture):
    return run(fixture["observer"].verify_commit(fixture["scope"], fixture["binding"], fixture["response"]))


def test_cookie_lookup_binds_actual_saved_profile_customer_and_real_expiry(fixture):
    login = module.read_login_session(fixture["paths"], cookie=fixture["cookie"], expected_profile="colombia",
                                      expected_customer=fixture["scope"].customer_id, snapshot=fixture["scope"].snapshot,
                                      source_fingerprint=fixture["scope"].source_fingerprint)
    assert (login.session_id, login.session_exp) == (fixture["scope"].frontend_session_id, fixture["scope"].frontend_session_exp)
    assert fixture["cookie"] not in repr(login)


@pytest.mark.parametrize("field,value", [("cookie", "foreign-cookie"), ("expected_profile", "mexico"), ("expected_customer", "foreign-customer")])
def test_cookie_lookup_rejects_foreign_saved_identity_without_echo(fixture, field, value):
    arguments = dict(cookie=fixture["cookie"], expected_profile="colombia", expected_customer=fixture["scope"].customer_id,
                     snapshot=fixture["scope"].snapshot, source_fingerprint=fixture["scope"].source_fingerprint)
    arguments[field] = value
    with pytest.raises(module.ObservationRejected) as error:
        module.read_login_session(fixture["paths"], **arguments)
    assert value not in str(error.value) and fixture["cookie"] not in str(error.value)


def test_cookie_expiry_is_checked_against_real_clock(fixture):
    update(fixture["paths"].frontend_state_db, "sessions", "expires_at", int(time.time()) - 1)
    with pytest.raises(module.ObservationRejected, match="fixture_login_rejected"):
        module.read_login_session(fixture["paths"], cookie=fixture["cookie"], expected_profile="colombia",
                                  expected_customer=fixture["scope"].customer_id, snapshot=fixture["scope"].snapshot,
                                  source_fingerprint=fixture["scope"].source_fingerprint)


def test_exact_frontend_and_worker_session_digest_recipes(fixture):
    scope = fixture["scope"]
    expected_owner = hashlib.sha256(json.dumps([scope.issuer, scope.subject, scope.frontend_model], separators=(",", ":")).encode()).hexdigest()
    expected_bank = hashlib.sha256(json.dumps([scope.bank_deployment_id, scope.issuer, scope.frontend_session_id], ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert scope.frontend_owner == expected_owner
    assert scope.bank_session_id == expected_bank
    assert scope.bank_session_id != hashlib.sha256(json.dumps([scope.bank_deployment_id, scope.issuer, scope.frontend_session_id], separators=(",", ":")).encode()).hexdigest()


def test_real_clock_trusted_ed25519_assertion_callback(fixture):
    token, headers = assertion(fixture)
    identity = run(fixture["observer"].identity_verifier(headers))
    assert identity.issuer == fixture["scope"].issuer and identity.subject == fixture["scope"].subject
    assert identity.frontend_session_id == fixture["scope"].frontend_session_id
    assert identity.session_exp == fixture["scope"].frontend_session_exp and identity.jwt_exp > time.time()
    assert identity.assertion_sha256 == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(identity)


@pytest.mark.parametrize("overrides", [
    {"iss": "foreign-issuer"}, {"aud": "foreign-audience"}, {"sub": "foreign-subject"},
    {"session_id": "foreign-session"}, {"session_exp": 1}, {"scope": ["bank:write"]},
    {"scope": ["bank:read", "bank:write"]}, {"extra_claim": "not-allowed"},
    {"iat": 1, "nbf": 1, "exp": 100},
    {"iat": int(time.time()) + 1000, "nbf": int(time.time()) + 1000, "exp": int(time.time()) + 1100},
    {"exp": int(time.time()) + 500}, {"nbf": 1}, {"iat": True},
])
def test_signature_claim_identity_and_time_failures_never_become_verified(fixture, overrides):
    token, headers = assertion(fixture, **overrides)
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].identity_verifier(headers))


def test_untrusted_signer_wrong_type_and_duplicate_headers_rejected(fixture):
    _, headers = assertion(fixture, private_key=Ed25519PrivateKey.generate())
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].identity_verifier(headers))
    _, headers = assertion(fixture, header={"kid": "fixture-key", "typ": "bank-mcp+jwt"})
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].identity_verifier(headers))
    token, _ = assertion(fixture)
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].identity_verifier(httpx.Headers([("X-Flujo-User-Assertion", token), ("X-Flujo-User-Assertion", token)])))


def test_valid_signature_is_not_enough_when_login_was_deleted(fixture):
    _, headers = assertion(fixture)
    with sqlite3.connect(fixture["paths"].frontend_state_db) as db:
        db.execute("DELETE FROM sessions")
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].identity_verifier(headers))


def test_actual_host_reserved_uuid_action_revision_are_observed(fixture):
    intent = run(fixture["observer"].resolve_host_intent(fixture["scope"], fixture["binding"]))
    assert intent.action_id == fixture["action_id"] and intent.revision == 1
    assert intent.binding == fixture["binding"] and intent.scope_digest == fixture["scope"].digest
    assert intent.session_exp == fixture["scope"].frontend_session_exp


@pytest.mark.parametrize("table,field,value", [
    ("chat_sessions", "owner", "foreign-owner"), ("chat_sessions", "subject", "foreign-subject"),
    ("chat_sessions", "customer_id", "foreign-customer"), ("chat_sessions", "expires", 1),
    ("chat_sessions", "revoked", 1), ("chat_sessions", "conversation_id", str(uuid.uuid4())),
    ("action_status", "owner", "foreign-owner"), ("action_status", "expires", 1),
    ("action_status", "prepare_transaction_id", "foreign-charge"), ("action_status", "prepare_snapshot", "foreign-snapshot"),
    ("action_status", "prepare_conversation_id", str(uuid.uuid4())), ("action_status", "action_id", "not-host-uuid"),
    ("action_status", "revision", 0), ("action_status", "target_reference", "private-charge"),
    ("action_status", "result_json", json.dumps({"state": "preparing", "request_id": str(uuid.uuid4())})),
])
def test_wrong_host_tuple_rejects_commit_source_assertion(fixture, table, field, value):
    update(fixture["paths"].frontend_chat_db, table, field, value)
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


def test_actual_pending_and_policy_handoff_row_and_packet_digests(fixture):
    proof = commit(fixture)
    assert proof.pending_handle == fixture["response"]["pending_handle"] and proof.handoff_id == "HOF-abcdefgh"
    assert proof.scope_digest == fixture["scope"].digest and proof.binding == fixture["binding"]
    assert proof.response_sha256 == canonical_digest(fixture["response"])
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.row_factory = sqlite3.Row
        pending = db.execute("SELECT * FROM action_pending").fetchone()
        handoff = db.execute("SELECT * FROM sandbox_handoffs").fetchone()
    assert proof.pending_row_digest == canonical_digest(dict(pending))
    assert proof.handoff_row_digest == canonical_digest(dict(handoff))
    assert proof.handoff_packet_sha256 == canonical_digest(json.loads(handoff["packet_json"]))


@pytest.mark.parametrize("table", ["sessions", "action_pending", "sandbox_handoffs"])
def test_missing_actual_records_reject_canned_success(fixture, table):
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute(f"DELETE FROM {table}")
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


@pytest.mark.parametrize("field,value", [
    ("id", "wrong-handle-hash"), ("binding", "foreign-binding"), ("customer", "foreign-customer"),
    ("transaction_id", "foreign-charge"), ("snapshot", "foreign-snapshot"), ("request_key", "foreign-request-key"),
    ("confirmation_state", "attempted"), ("facts", "{}"), ("result_json", "{}"),
    ("decision", "intake"), ("reason", "high_risk"), ("expires", 1),
])
def test_pending_hash_key_binding_facts_and_real_expiry_must_match(fixture, field, value):
    update(fixture["paths"].mcp_state_db, "action_pending", field, value)
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


def test_revoked_actual_mcp_session_rejects_fault(fixture):
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("INSERT INTO revoked VALUES (?)", (fixture["scope"].bank_session_id,))
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


@pytest.mark.parametrize("field,value", [
    ("binding", "foreign-binding"), ("customer", "foreign-customer"), ("transaction_id", "foreign-charge"),
    ("snapshot", "foreign-snapshot"), ("reason", "customer_request"), ("idempotency_key", "foreign-key"),
    ("facts", "{}"), ("packet_json", "{}"), ("created_at", int(time.time()) + 1000),
])
def test_handoff_requires_exact_actual_packet_record(fixture, field, value):
    update(fixture["paths"].mcp_state_db, "sandbox_handoffs", field, value)
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


def test_nonempty_questions_and_human_pickup_never_match_policy_default_packet(fixture):
    for changes in ({"unanswered_questions": ["Synthetic user question"]}, {"human_responded": True}):
        packet = deepcopy(fixture["response"]["handoff"]["packet"])
        packet.update(changes)
        update(fixture["paths"].mcp_state_db, "sandbox_handoffs", "packet_json", json.dumps(packet))
        with pytest.raises(module.ObservationRejected):
            commit(fixture)


def test_readback_cannot_be_switched_to_another_hof_or_packet(fixture):
    fixture["response"]["handoff"]["id"] = "HOF-foreign1"
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


def test_marker_and_explicit_generated_root_reject_shared_or_foreign_paths(fixture, tmp_path):
    fixture["paths"].synthetic_provenance.write_text(json.dumps({"kind": "organizer", "build_id": fixture["scope"].snapshot,
                                                               "source_fingerprint": fixture["scope"].source_fingerprint}))
    with pytest.raises(module.ObservationRejected):
        commit(fixture)
    outside = tmp_path.parent / (str(uuid.uuid4()) + ".sqlite3")
    outside.write_bytes(b"synthetic-outside-test-file")
    try:
        with pytest.raises(module.ObservationRejected, match="fixture_path_rejected"):
            fixture["paths"].contained_file(outside)
    finally:
        outside.unlink()


def test_snapshot_marker_extra_fields_are_not_a_different_provenance_schema(fixture):
    marker = {"kind": "team_synthetic_fixture", "build_id": fixture["scope"].snapshot,
              "source_fingerprint": fixture["scope"].source_fingerprint, "invented_approval": True}
    fixture["paths"].synthetic_provenance.write_text(json.dumps(marker))
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


def test_no_frontend_or_ledger_writes_hashes_rows_or_action_statements(fixture, monkeypatch):
    paths = fixture["paths"]
    db_paths = (paths.frontend_state_db, paths.frontend_chat_db, paths.mcp_state_db)
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in db_paths}
    original, statements = sqlite3.connect, []

    def observed_connect(*args, **kwargs):
        assert "?mode=ro" in args[0] and kwargs["uri"] is True
        db = original(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    with monkeypatch.context() as scope:
        scope.setattr(module.sqlite3, "connect", observed_connect)
        token, headers = assertion(fixture)
        run(fixture["observer"].identity_verifier(headers))
        commit(fixture)
    assert before == {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in db_paths}
    assert statements and not any(sql.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE", "ATTACH", "VACUUM"} for sql in statements)


def authored_phase(fixture):
    artifact = fixture["paths"].fixture_root / "authored-closed-interval.json"
    artifact.write_bytes(b'{"synthetic":true,"source_test_only":"closed authored interval"}')
    fixture_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
    generation = "e" * 64
    start, end = int(time.time()) - 86500, int(time.time()) - 1
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("INSERT OR REPLACE INTO sandbox_ledger_identity VALUES (1,?)", (generation,))
        db.execute("INSERT INTO sandbox_coverage VALUES (1,?,?,?,?)", (generation, start,
                   hashlib.sha256(("synthetic:present-v1:" + fixture_hash).encode()).hexdigest(), int(time.time())))
    return dict(fixture_artifact=artifact, fixture_sha256=fixture_hash, expected_generation=generation,
                expected_coverage_start=start, declared_closed_interval_end=end,
                expected_provenance="synthetic:present-v1:" + fixture_hash)


def test_readonly_authored_phase_proves_exact_artifact_and_existing_attestation_rows(fixture):
    inputs = authored_phase(fixture)
    before = fixture["paths"].mcp_state_db.read_bytes()
    evidence = fixture["observer"].verify_attested_phase(**inputs)
    assert evidence.fixture_sha256 == inputs["fixture_sha256"] and evidence.provenance == inputs["expected_provenance"]
    assert evidence.ledger_generation == inputs["expected_generation"] and evidence.coverage_start == inputs["expected_coverage_start"]
    assert evidence.fixture_id == fixture["scope"].fixture_id and len(evidence.independent_verification_sha256) == 64
    assert before == fixture["paths"].mcp_state_db.read_bytes()


@pytest.mark.parametrize("field,value", [("generation", "f" * 64), ("coverage_start", 1), ("provenance_digest", "wrong-digest"), ("attested_at", int(time.time()) + 1000)])
def test_attested_phase_wrong_ledger_correlations_rejected(fixture, field, value):
    inputs = authored_phase(fixture)
    update(fixture["paths"].mcp_state_db, "sandbox_coverage", field, value)
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_attested_phase(**inputs)


def test_authored_closure_future_or_short_interval_and_changed_artifact_rejected(fixture):
    inputs = authored_phase(fixture)
    for change in ({"declared_closed_interval_end": int(time.time()) + 1000},
                   {"declared_closed_interval_end": inputs["expected_coverage_start"] + 100},
                   {"expected_coverage_start": int(time.time()) - 100}):
        with pytest.raises(module.ObservationRejected):
            fixture["observer"].verify_attested_phase(**{**inputs, **change})
    inputs["fixture_artifact"].write_bytes(b"synthetic changed artifact")
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_attested_phase(**inputs)


def pending_phase(fixture):
    fixture["scope"] = replace(fixture["scope"], expected_outcome="pending_confirmation")
    fixture["observer"] = module.FrontendObservers(fixture["paths"], fixture["scope"], {"fixture-key": fixture["private_key"].public_key()})
    fixture["response"] = {key: value for key, value in fixture["response"].items() if key != "handoff"}
    fixture["response"].update(state="pending_confirmation", decision="intake", reason=None)
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        result = json.loads(db.execute("SELECT result_json FROM action_pending").fetchone()[0])
        result.update(decision="intake", reason=None)
        result["risk"].update(risk_data_complete=True, unrecognized_count_24h=1)
        db.execute("UPDATE action_pending SET decision='intake',reason=NULL,result_json=?", (json.dumps(result),))


def test_pending_confirmation_needs_actual_authored_phase_verification(fixture):
    pending_phase(fixture)
    with pytest.raises(module.ObservationRejected, match="authored_phase_evidence_required"):
        commit(fixture)
    inputs = authored_phase(fixture)
    fixture["observer"].verify_attested_phase(**inputs)
    proof = commit(fixture)
    assert proof.handoff_id is None and proof.handoff_packet_sha256 is None
    update(fixture["paths"].mcp_state_db, "sandbox_coverage", "generation", "f" * 64)
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


@pytest.mark.parametrize("changes", [{"risk_data_complete": True}, {"unrecognized_count_24h": 1},
                                     {"coverage": "bank-wide"}, {"source": "foreign"},
                                     {"window_end": "2000-01-01T00:00:00Z"}])
def test_stock_missing_coverage_requires_actual_ledger_only_risk(fixture, changes):
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        result = json.loads(db.execute("SELECT result_json FROM action_pending").fetchone()[0])
        result["risk"].update(changes)
        db.execute("UPDATE action_pending SET result_json=?", (json.dumps(result),))
    with pytest.raises(module.ObservationRejected):
        commit(fixture)


@pytest.mark.parametrize("table", ["sandbox_cases", "sandbox_case_receipts", "sandbox_coverage"])
def test_stock_fresh_generation_excludes_seeded_cases_receipts_or_coverage(fixture, table):
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        if table == "sandbox_cases":
            db.execute("INSERT INTO sandbox_cases VALUES ('CMP-SBX-oldcase1','x','x','simulated_intake','x',1,'{}')")
        elif table == "sandbox_case_receipts":
            db.execute("INSERT INTO sandbox_case_receipts VALUES ('CMP-SBX-oldcase1','{}')")
        else:
            db.execute("INSERT INTO sandbox_coverage VALUES (1,?,1,'x',1)", (fixture["scope"].ledger_generation,))
    with pytest.raises(module.ObservationRejected, match="stock_missing_coverage_rejected"):
        commit(fixture)


def test_generation_replacement_and_old_attestation_are_not_phase_proof(fixture):
    inputs = authored_phase(fixture)
    update(fixture["paths"].mcp_state_db, "sandbox_coverage", "attested_at", inputs["declared_closed_interval_end"] - 1)
    with pytest.raises(module.ObservationRejected, match="attested_ledger_rejected"):
        fixture["observer"].verify_attested_phase(**inputs)
    update(fixture["paths"].mcp_state_db, "sandbox_ledger_identity", "generation", "f" * 64)
    with pytest.raises(module.ObservationRejected, match="ledger_generation_rejected"):
        fixture["observer"].verify_attested_phase(**inputs)


def confirmation_fixture(fixture):
    pending_phase(fixture)
    inputs = authored_phase(fixture)
    fixture["observer"].verify_attested_phase(**inputs)
    saved = {**fixture["response"], "request_id": fixture["binding"].request_id, "target_reference": "txn_" + "a" * 24}
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET result_json=?,revision=2,prepare_transaction_id=NULL,prepare_snapshot=NULL,prepare_conversation_id=NULL", (json.dumps(saved),))
    original = fixture["observer"].capture_confirmation_base("txn_" + "a" * 24, fixture["response"]["pending_handle"])
    assert original.binding == fixture["binding"] and original.action_id == fixture["action_id"] and original.revision == 2
    uncertain = {key: saved[key] for key in ("pending_handle", "snapshot", "transaction", "target_reference")}
    uncertain["state"] = "action_unverified"
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET result_json=?,revision=3", (json.dumps(uncertain),))
    return original


def case_fixture(fixture):
    created_at = time.time()
    scope = fixture["scope"]
    receipt = {"id": "CMP-SBX-abcdefgh", "kind": "simulated_intake", "simulated": True, "snapshot": scope.snapshot,
               "created_at": datetime.fromtimestamp(created_at, timezone.utc).isoformat().replace("+00:00", "Z"),
               "status": "received", "transaction": fixture["facts"]}
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("UPDATE action_pending SET confirmation_state='verified'")
        db.execute("INSERT INTO sandbox_cases VALUES (?,?,?,?,?,?,?)", (receipt["id"], scope.customer_id, scope.transaction_id,
                   "simulated_intake", scope.snapshot, created_at, json.dumps(fixture["facts"])))
        db.execute("INSERT INTO sandbox_case_receipts VALUES (?,?)", (receipt["id"], json.dumps(receipt)))
    return receipt


def test_confirmation_binds_original_actual_uuid_even_when_uncertain_json_has_no_uuid(fixture):
    from scripts.synthetic_integration.frontend_confirm_fault import ConfirmScope
    original = confirmation_fixture(fixture)
    handle, target = fixture["response"]["pending_handle"], "txn_" + "a" * 24
    current = run(fixture["observer"].resolve_confirmation_intent(original, handle, target))
    assert current.binding == original.binding and current.action_id == original.action_id and current.revision == 3
    receipt = case_fixture(fixture)
    scope = ConfirmScope(fixture["scope"], original, target, hashlib.sha256(handle.encode()).hexdigest())
    proof = run(fixture["observer"].verify_confirmation_commit(scope, handle, {"state": "intake_verified", "receipt": receipt}))
    assert proof.case_id == receipt["id"] and proof.receipt_sha256 == canonical_digest(receipt)
    assert handle not in repr(proof)
    wrong_original = replace(original, action_id=str(uuid.uuid4()))
    with pytest.raises(module.ObservationRejected):
        run(fixture["observer"].resolve_confirmation_intent(wrong_original, handle, target))


@pytest.mark.parametrize("table,field,value", [
    ("sandbox_cases", "customer", "foreign-customer"), ("sandbox_cases", "transaction_id", "foreign-charge"),
    ("sandbox_cases", "snapshot", "foreign-snapshot"), ("sandbox_cases", "facts", "{}"),
    ("sandbox_case_receipts", "receipt_json", "{}"), ("action_pending", "confirmation_state", "attempted"),
])
def test_receipt_requires_actual_case_and_exact_stored_receipt_readback(fixture, table, field, value):
    original = confirmation_fixture(fixture)
    receipt = case_fixture(fixture)
    update(fixture["paths"].mcp_state_db, table, field, value)
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_receipt(original, fixture["response"]["pending_handle"], "txn_" + "a" * 24, receipt)


def general_fixture(fixture):
    request_id, questions = str(uuid.uuid4()), ["Pregunta sintética", "Pergunta sintética"]
    scope, conversation = fixture["scope"], fixture["binding"].conversation_id
    owner = Principal(scope.subject, scope.customer_id, scope.bank_session_id, conversation, int(time.time()) + 60).binding()
    key = hashlib.sha256(json.dumps([owner, request_id]).encode()).hexdigest()
    created = int(time.time())
    packet = {"schema": "banking-sandbox-handoff/v1", "transaction": None, "transaction_provenance": None,
              "reason": "customer_request", "unanswered_questions": questions, "human_responded": False}
    readback = {"id": "HOF-general1", "reason": "customer_request", "snapshot": None,
                "created_at": datetime.fromtimestamp(created, timezone.utc).isoformat().replace("+00:00", "Z"), "facts": {},
                "human_responded": False, "unanswered_questions": questions, "transaction_provenance": None,
                "transaction_currentness": "not_applicable"}
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET target_reference=NULL,result_json=?,revision=3", (json.dumps({"state": "handoff_verified",
                   "request_id": request_id, "reason": "customer_request", "unanswered_questions": questions, "handoff": readback}),))
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("INSERT INTO sandbox_handoffs VALUES (?,?,?,?,?,?,?,?,?,?)", (readback["id"], owner, scope.customer_id,
                   None, None, "customer_request", created, "{}", key, json.dumps(packet)))
    return request_id, questions, readback


def test_general_hof_exact_frozen_questions_packet_readback_and_no_pickup(fixture):
    request, questions, readback = general_fixture(fixture)
    proof = fixture["observer"].verify_general_handoff(request, fixture["binding"].conversation_id, questions, readback)
    assert proof["handoff_id"] == readback["id"] and proof["human_pickup"] == "unproven"
    assert proof["generation"] == fixture["scope"].ledger_generation
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_general_handoff(request, fixture["binding"].conversation_id, ["Edited synthetic question"], readback)
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("DELETE FROM sandbox_handoffs WHERE id=?", (readback["id"],))
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_general_handoff(request, fixture["binding"].conversation_id, questions, readback)


def test_business_snapshot_counts_and_full_row_hashes_are_generation_bound(fixture):
    observer, conversation = fixture["observer"], fixture["binding"].conversation_id
    before = observer.ledger_observation(conversation)
    same = observer.ledger_observation(conversation)
    comparison = observer.compare_ledger_observations(before, same)
    assert comparison["scope"] == "business_ledger_rows_only" and comparison["observed_rows_unchanged"] is True
    assert all(delta == 0 for delta in comparison["net_row_count_delta"].values())
    update(fixture["paths"].mcp_state_db, "action_pending", "confirmation_state", "attempted")
    changed = observer.ledger_observation(conversation)
    comparison = observer.compare_ledger_observations(before, changed)
    assert comparison["observed_rows_unchanged"] is False and comparison["net_row_count_delta"]["action_pending"] == 0
    assert comparison["intervening_transient_writes"] == "unproven"
    with pytest.raises(module.ObservationRejected):
        observer.compare_ledger_observations(before, replace(changed, generation="f" * 64))


def test_terminal_receipt_wire_omits_top_facts_and_uuid_but_remains_exact(fixture):
    original = confirmation_fixture(fixture)
    receipt = case_fixture(fixture)
    handle, target = fixture["response"]["pending_handle"], "txn_" + "a" * 24
    terminal = {"state": "intake_verified", "receipt": receipt, "pending_handle": handle, "target_reference": target}
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET result_json=?,revision=4", (json.dumps(terminal),))
    proof = fixture["observer"].verify_fresh_confirmation(original, handle, target, receipt)
    assert proof["fresh"] is True and proof["case_id"] == receipt["id"]
    terminal["receipt"] = {**receipt, "transaction": {**receipt["transaction"], "amount": "99.00"}}
    update(fixture["paths"].frontend_chat_db, "action_status", "result_json", json.dumps(terminal))
    with pytest.raises(module.ObservationRejected):
        fixture["observer"].verify_fresh_confirmation(original, handle, target, receipt)


def test_matching_old_case_can_never_supply_preclick_absence_or_fresh_confirmation(fixture):
    original = confirmation_fixture(fixture)
    receipt = case_fixture(fixture)
    old_created = fixture["now"] - 10
    receipt["created_at"] = datetime.fromtimestamp(old_created, timezone.utc).isoformat().replace("+00:00", "Z")
    with sqlite3.connect(fixture["paths"].mcp_state_db) as db:
        db.execute("UPDATE sandbox_cases SET created_at=?", (old_created,))
        db.execute("UPDATE sandbox_case_receipts SET receipt_json=?", (json.dumps(receipt),))
    handle, target = fixture["response"]["pending_handle"], "txn_" + "a" * 24
    assert fixture["observer"].verify_receipt(original, handle, target, receipt)["case_id"] == receipt["id"]
    with pytest.raises(module.ObservationRejected, match="fresh_receipt_rejected"):
        fixture["observer"].verify_fresh_confirmation(original, handle, target, receipt)
    update(fixture["paths"].frontend_chat_db, "action_status", "result_json", json.dumps({**fixture["response"],
           "request_id": fixture["binding"].request_id, "target_reference": target}))
    update(fixture["paths"].mcp_state_db, "action_pending", "confirmation_state", "prepared")
    with pytest.raises(module.ObservationRejected, match="confirmation_case_already_exists"):
        fixture["observer"].capture_confirmation_base(target, handle)


def test_concrete_browser_truth_reads_actual_cookie_absence_and_fresh_terminal_receipt(fixture):
    from scripts.synthetic_integration.frontend_browser import SavedTuple, digest
    pending_phase(fixture)
    inputs = authored_phase(fixture)
    fixture["observer"].verify_attested_phase(**inputs)
    handle, target = fixture["response"]["pending_handle"], "txn_" + "a" * 24
    saved_wire = {**fixture["response"], "request_id": fixture["binding"].request_id, "target_reference": target}
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET result_json=?,revision=2,prepare_transaction_id=NULL,prepare_snapshot=NULL,prepare_conversation_id=NULL", (json.dumps(saved_wire),))
    saved = SavedTuple(fixture["binding"].request_id, target, handle, fixture["scope"].snapshot, fixture["facts"])
    cookie_sha = hashlib.sha256(fixture["cookie"].encode()).hexdigest()
    predecessor = run(fixture["observer"].pending(saved, cookie_sha))
    assert predecessor.receipt_absent is True and predecessor.tuple_sha256 == digest(saved.public())
    receipt = case_fixture(fixture)
    terminal = {"state": "intake_verified", "receipt": receipt, "pending_handle": handle, "target_reference": target}
    with sqlite3.connect(fixture["paths"].frontend_chat_db) as db:
        db.execute("UPDATE action_status SET result_json=?,revision=4", (json.dumps(terminal),))
    truth = run(fixture["observer"].fresh_receipt(saved, cookie_sha))
    assert truth.fresh is True and truth.receipt == receipt and truth.receipt_sha256 == canonical_digest(receipt)
    assert truth.tuple_sha256 == predecessor.tuple_sha256 and truth.ledger_generation == predecessor.ledger_generation
    with pytest.raises(module.ObservationRejected, match="browser_cookie_rejected"):
        run(fixture["observer"].fresh_receipt(saved, "f" * 64))
    recreated = module.FrontendObservers(fixture["paths"], fixture["scope"], {"fixture-key": fixture["private_key"].public_key()})
    recreated.verify_attested_phase(**inputs)
    with pytest.raises(module.ObservationRejected, match="browser_receipt_baseline_required"):
        run(recreated.fresh_receipt(saved, cookie_sha))
