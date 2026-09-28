"""Only synthetic data and signing keys. No source credentials or model calls."""
from __future__ import annotations

import json
import csv
import io
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from starlette.testclient import TestClient

from banking_mcp.config import Config
from banking_mcp.security import ASSERTION_META, TOKEN_TYPE, BankError, arguments_digest
from banking_mcp.server import create_http_app
from banking_mcp.service import Service
from pipeline.__main__ import main
from pipeline.fixture import cid, write_base


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
    config = Config(data_dir=dataset / "out", state_db=tmp_path / "state.db", service_token="x" * 48,
                    public_keys={"test": key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()},
                    principal_customers={"alice": cid(3), "bob": cid(4)})
    return Service(config), key


def assertion(bank, tool_name, args, subject="alice", **overrides):
    service, key = bank
    now = int(time.time())
    claims = {"iss": service.config.issuer, "aud": service.config.audience, "sub": subject,
              "iat": now, "nbf": now, "exp": now + 60, "jti": str(uuid.uuid4()),
              "session_id": "session-" + subject, "conversation_id": "conversation-" + subject,
              "run_id": str(uuid.uuid4()), "graph_revision": "v1", "tool": tool_name,
              "scope": ["bank:read"], "args_sha256": arguments_digest(args), **overrides}
    return {ASSERTION_META: jwt.encode(claims, key, algorithm="EdDSA", headers={"kid": "test", "typ": TOKEN_TYPE})}


def call(bank, tool="list_my_transactions", args=None, subject="alice", **claims):
    args = args or {}
    return bank[0].execute(tool, args, assertion(bank, tool, args, subject, **claims))


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


@pytest.mark.parametrize("args", [{"customer_id": cid(4)}, {"limit": 100}, {"limit": "1"},
                                 {"bucket": "other"}, {"start_date": "2026-02-31"}])
def test_strict_business_schema(bank, args):
    with pytest.raises(BankError, match="invalid_arguments"):
        call(bank, args=args)


def test_revoke_before_and_after_read(bank, monkeypatch):
    original = bank[0].repository.list_transactions
    def revoke_during(*args, **kwargs):
        result = original(*args, **kwargs)
        bank[0].store.revoke("session-alice")
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
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    service, _ = bank
    config = tmp_path / "bank.json"
    config.write_text(service.config.model_dump_json())
    repo = Path(__file__).resolve().parents[1]
    async def exercise():
        params = StdioServerParameters(command=sys.executable,
            args=["-m", "banking_mcp", "serve", "--config", str(config)], cwd=str(repo))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                assert {t.name for t in (await client.list_tools()).tools} == {
                    "banking_status", "list_my_transactions", "get_my_transaction"}
                args = {"limit": 1}
                result = await client.call_tool("list_my_transactions", args,
                    meta=assertion(bank, "list_my_transactions", args))
                assert not result.isError
                assert len(json.loads(result.content[0].text)["transactions"]) == 1
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
