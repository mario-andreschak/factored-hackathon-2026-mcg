"""Boundary tests against a tiny explicitly synthetic Parquet snapshot."""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import duckdb
import pytest
from fastapi.testclient import TestClient

from frontend.server.app import COOKIE, create_app
from frontend.server.config import Settings
from frontend.server.repository import DatasetUnavailable, Repository
from frontend.server.state import State


def bucket(customer):
    return int(hashlib.md5(customer.encode()).hexdigest()[:8], 16) % 128


@pytest.fixture()
def settings(tmp_path):
    data = tmp_path / "data"
    build = data / "builds" / "fixture-1"
    silver = build / "silver"
    silver.mkdir(parents=True)
    gold = build / "gold" / "transactions_by_customer"
    gold.mkdir(parents=True)
    with duckdb.connect() as con:
        con.execute("""CREATE TABLE customers AS SELECT * FROM (VALUES
            ('private-customer-co','Colombia','Bogotá','Plus','Active',TIMESTAMP '2025-01-01'),
            ('private-customer-mx','México','Monterrey','Basic','Active',TIMESTAMP '2025-01-02'),
            ('private-customer-ar','Argentina','Buenos Aires','Premium','Active',TIMESTAMP '2025-01-03')
        ) t(customer_id,country,city,segment,customer_status,registration_date)""")
        con.execute("""CREATE TABLE products AS SELECT *, 2500::DECIMAL(15,2) AS credit_limit,
            4.5::DECIMAL(5,2) AS interest_rate, DATE '2025-01-01' AS opening_date,
            DATE '2028-01-01' AS expiration_date,TIMESTAMP '2026-06-18' AS last_updated,
            TIMESTAMP '2026-06-17' AS last_transaction_date FROM (VALUES
            ('private-account-co','private-customer-co','Cuenta Ahorro','COP',1000::DECIMAL(15,2),'Active'),
            ('private-account-usd','private-customer-co','Cuenta Corriente','USD',25::DECIMAL(15,2),'Active'),
            ('private-card-co','private-customer-co','Tarjeta Crédito','COP',200::DECIMAL(15,2),'Active'),
            ('private-account-mx','private-customer-mx','Cuenta Ahorro','USD',500::DECIMAL(15,2),'Active'),
            ('private-account-ar','private-customer-ar','Cuenta Ahorro','ARS',750::DECIMAL(15,2),'Active')
        ) t(product_id,customer_id,product_type,currency,current_balance,product_status)""")
        con.execute("""CREATE TABLE transactions AS SELECT *, DATE '2026-06-17' AS process_date,
            'App' AS channel, NULL::VARCHAR AS transaction_category, NULL::VARCHAR AS merchant_name,
            NULL::VARCHAR AS merchant_category,'Colombia' AS transaction_country,
            NULL::VARCHAR AS transaction_city, true AS ownership_valid, false AS is_fraud
        FROM (VALUES
            ('private-txn-co-deposit','private-customer-co','private-account-co',TIMESTAMP '2026-06-17 12:00:00','Deposit',150::DECIMAL(15,2),'COP','Approved'),
            ('private-txn-co-purchase','private-customer-co','private-card-co',TIMESTAMP '2026-06-17 11:00:00','Purchase',50::DECIMAL(15,2),'COP','Approved'),
            ('private-txn-co-transfer','private-customer-co','private-account-co',TIMESTAMP '2026-06-17 10:00:00','Transfer',200::DECIMAL(15,2),'COP','Approved'),
            ('private-txn-co-pending','private-customer-co','private-account-co',TIMESTAMP '2026-06-17 09:00:00','Deposit',999::DECIMAL(15,2),'COP','Pending'),
            ('private-txn-co-usd','private-customer-co','private-account-usd',TIMESTAMP '2026-06-17 08:00:00','Deposit',10::DECIMAL(15,2),'USD','Approved'),
            ('private-txn-mx','private-customer-mx','private-account-mx',TIMESTAMP '2026-06-17 07:00:00','Deposit',20::DECIMAL(15,2),'USD','Approved'),
            ('private-txn-ar','private-customer-ar','private-account-ar',TIMESTAMP '2026-06-17 06:00:00','Withdrawal',30::DECIMAL(15,2),'ARS','Approved'),
            ('private-txn-cross-owner','private-customer-co','private-account-ar',TIMESTAMP '2026-06-17 13:00:00','Deposit',800::DECIMAL(15,2),'ARS','Approved'),
            ('private-txn-orphan','absent-customer','private-account-ar',TIMESTAMP '2026-06-17 14:00:00','Deposit',800::DECIMAL(15,2),'ARS','Approved')
        ) t(transaction_id,customer_id,product_id,transaction_date,transaction_type,amount,currency,transaction_status)""")
        # Even a mistakenly valid gold bit must not override silver owner joins.
        con.execute("UPDATE transactions SET ownership_valid=false WHERE transaction_id='private-txn-co-usd'")
        for table in ("customers", "products"):
            con.execute(f"COPY {table} TO ? (FORMAT PARQUET)", [str(silver / f"{table}.parquet")])
        for customer in ["private-customer-co", "private-customer-mx", "private-customer-ar", "absent-customer"]:
            out = gold / f"bucket={bucket(customer)}" / "data_0.parquet"
            out.parent.mkdir(exist_ok=True)
            path = out.as_posix().replace("'", "''")
            con.execute(f"COPY (SELECT * FROM transactions WHERE customer_id=?) TO '{path}' (FORMAT PARQUET)", [customer])
    inventory = {p.relative_to(build / "gold").as_posix(): p.stat().st_size for p in (build / "gold").rglob("*.parquet")}
    (build / "snapshot.json").write_text(json.dumps({"build_id": "fixture-1", "source_fingerprint": "a" * 16,
        "created_at": "2026-09-29T00:00:00Z", "gold_files": inventory}))
    (data / "CURRENT").write_text("fixture-1")
    return Settings(data_dir=data, state_dir=tmp_path / "state", static_dir=tmp_path / "dist", demo_code="2026",
                    profiles={key: {"customer_id": customer} for key,customer in [
                        ("colombia","private-customer-co"),("mexico","private-customer-mx"),("argentina","private-customer-ar")]})


def login(client, profile="colombia", **kwargs):
    return client.post("/api/auth/login", json={"profile":profile,"code":"2026"}, **kwargs)


INVITE_CODE = "Savia_visitor_" + "a" * 32
REPLACEMENT_INVITE_CODE = "Savia_visitor_" + "b" * 32


def invite_settings(settings):
    build = settings.data_dir / "builds" / "fixture-1"
    manifest_file = build / "snapshot.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["source_validation"] = "unchanged_inventory_after_ingestion"
    manifest_file.write_text(json.dumps(manifest))
    marker = {"kind": "team_synthetic_fixture", "build_id": manifest["build_id"],
              "source_fingerprint": manifest["source_fingerprint"]}
    (build / "synthetic_provenance.json").write_text(json.dumps(marker))
    return replace(settings, auth_mode="invite", demo_code="", public_origin="http://localhost",
                   invites={hashlib.sha256(INVITE_CODE.encode()).hexdigest(): "colombia"},
                   profiles={"colombia": settings.profiles["colombia"]}, expected_snapshot=marker)


def invite_login(client, code=INVITE_CODE, **kwargs):
    headers = {"origin": "http://localhost", **kwargs.pop("headers", {})}
    return client.post("/api/auth/invite", json={"code": code}, headers=headers, **kwargs)


def test_real_ownership_currency_and_no_invented_data(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/overview").status_code == 401
        assert login(client).status_code == 200
        data = client.get("/api/overview").json()
        assert len(data["transactions"]) == 4  # rejects owner mismatch AND false ownership bit
        assert data["metadata"]["transactions_total"] == 4
        raw = json.dumps(data)
        assert "private-" not in raw and "is_fraud" not in raw
        assert all(p["masked_number"] is None for p in data["products"])
        assert all(t["merchant"] is None for t in data["transactions"])
        transfer = next(t for t in data["transactions"] if t["type"] == "Transfer")
        assert transfer["direction"] == "unknown" and transfer["amount"] == 200
        totals = {r["currency"]:r for r in data["summary"]["balances_by_currency"]}
        assert totals["COP"]["deposit_balance"] == 1000
        assert totals["COP"]["credit_balance"] == 200
        assert totals["USD"]["deposit_balance"] == 25
        month = data["summary"]["monthly_activity"][0]
        assert month["inflow"] == 150 and month["outflow"] == 50 and month["unclassified"] == 200
        assert data["metadata"]["source_fingerprint"] == "a"*16


def test_public_profiles_do_not_expose_ids(settings):
    with TestClient(create_app(settings)) as client:
        data = client.get("/api/auth/profiles").json()
        assert len(data["profiles"]) == 3 and data["demo"] and "code_hint" not in data
        assert "private-" not in json.dumps(data)
        assert next(p for p in data["profiles"] if p["id"] == "mexico")["primary_currency"] == "USD"


def test_session_restart_rotation_expiry_and_logout(settings):
    with TestClient(create_app(settings)) as client:
        login(client)
        initial = client.cookies.get(COOKIE)
        assert "HttpOnly" in login(client).headers["set-cookie"]
        assert initial != client.cookies.get(COOKIE)
        with TestClient(create_app(settings)) as restarted:
            restarted.cookies.set(COOKIE, initial)
            assert restarted.get("/api/auth/me").status_code == 401
            restarted.cookies.set(COOKIE, client.cookies.get(COOKIE))
            assert restarted.get("/api/auth/me").status_code == 200
        current = client.cookies.get(COOKIE)
        assert client.post("/api/auth/logout", json={}).status_code == 204
        client.cookies.set(COOKIE,current)
        assert client.get("/api/auth/me").status_code == 401
        login(client)
        with client.app.state.bank_state.connect() as db:
            db.execute("UPDATE sessions SET expires_at=0")
        assert client.get("/api/auth/me").status_code == 401


def test_same_origin_and_login_throttle(settings):
    with TestClient(create_app(settings)) as client:
        assert login(client, headers={"origin":"https://evil.invalid"}).status_code == 403
        assert login(client, headers={"origin":"http://testserver"}).status_code == 200
        assert login(client, headers={"sec-fetch-site":"cross-site"}).status_code == 403
        assert client.post("/api/auth/logout",content="x").status_code == 415
        assert client.post("/api/auth/login",json={"profile":"colombia","code":"é"}).status_code == 401
        for _ in range(9):
            assert client.post("/api/auth/login",json={"profile":"colombia","code":"wrong"}).status_code == 401
        assert login(client).status_code == 429


def test_published_snapshot_fail_closed_after_cached_read(settings):
    with TestClient(create_app(settings)) as client:
        login(client)
        assert client.get("/healthz").status_code == 200
        pointer = settings.data_dir / "CURRENT"
        pointer.write_text("../fixture-1")
        assert client.get("/api/overview").status_code == 503
        pointer.write_text("fixture-1")
        gold = next((settings.data_dir / "builds/fixture-1/gold").rglob("*.parquet"))
        gold.unlink()
        assert client.get("/healthz").status_code == 503
        assert client.get("/api/overview").status_code == 503


def test_concurrent_profiles_and_foreign_transaction_reference(settings):
    repo = Repository(settings, State(settings.state_dir))
    def read(profile):
        data = repo.overview(profile)
        expected = {"colombia":"COP","mexico":"USD","argentina":"ARS"}[profile]
        assert all(t["currency"] == expected for t in data["transactions"])
        return data
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(read,["colombia","mexico","argentina"]*8))
    foreign = results[1]["transactions"][0]["reference"]
    assert repo.transaction("colombia", foreign) is None
    with TestClient(create_app(settings)) as client:
        login(client)
        client.app.state.chat_service = object()
        response = client.post("/api/chat/messages",json={"message":"Ayuda","transaction_reference":foreign})
        assert response.status_code == 404


def test_action_api_resolves_owned_reference_and_localizes_verified_state(settings):
    class ActionService:
        def __init__(self):
            self.calls = []

        async def action(self, customer, session_id, expires, operation):
            self.calls.append((customer, session_id, operation))
            if operation["operation"] == "prepare":
                return {"state": "pending_confirmation", "pending_handle": "a" * 43}
            return {"state": "handoff_verified", "handoff": {"id": "HOF-abcdefgh"}}

    with TestClient(create_app(settings)) as client:
        assert login(client).status_code == 200
        service = ActionService()
        client.app.state.chat_service = service
        own = client.get("/api/overview").json()["transactions"][0]["reference"]
        prepared = client.post("/api/action/prepare", json={"transaction_reference": own, "language": "pt"})
        assert prepared.status_code == 200
        assert prepared.json()["state"] == "pending_confirmation"
        assert "Confirme" in prepared.json()["message"]
        assert service.calls[0][0] == "private-customer-co"
        assert service.calls[0][2]["transactionId"].startswith("private-txn-")
        assert "private-txn-" not in prepared.text
        handoff = client.post("/api/action/handoff", json={"reason": "customer_request", "language": "es"})
        assert handoff.status_code == 200
        assert "HOF-abcdefgh" in handoff.json()["message"]
        assert "respuesta de una persona" in handoff.json()["message"]
        foreign = Repository(settings, State(settings.state_dir)).overview("mexico")["transactions"][0]["reference"]
        denied = client.post("/api/action/prepare", json={"transaction_reference": foreign})
        assert denied.status_code == 404
        assert len(service.calls) == 2


def test_secure_cookie_origin_and_custom_demo_code(settings):
    settings = replace(settings,secure_cookie=True,public_origin="https://bank.example",demo_code="private-code")
    with TestClient(create_app(settings),base_url="https://bank.example") as client:
        assert "code_hint" not in client.get("/api/auth/profiles").json()
        response=client.post("/api/auth/login",json={"profile":"colombia","code":"private-code"},headers={"origin":"https://bank.example"})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").status_code == 200
        assert login(client,headers={"origin":"http://bank.example"}).status_code == 403


def test_invite_only_reveals_bound_synthetic_persona(settings):
    candidate = invite_settings(settings)
    with TestClient(create_app(candidate), base_url="http://localhost") as client:
        assert client.get("/api/auth/profiles").json() == {"mode": "invite", "demo": True, "profiles": []}
        assert client.get("/api/overview").status_code == 401
        assert login(client, headers={"origin": "http://localhost"}).status_code == 404
        assert client.post("/api/auth/invite", json={"code": INVITE_CODE, "profile": "mexico"},
                           headers={"origin": "http://localhost"}).status_code == 422
        assert client.post("/api/auth/invite", json={"code": INVITE_CODE}).status_code == 403
        assert client.post("/api/auth/invite", json={"code": INVITE_CODE},
                           headers={"origin": "http://127.0.0.1"}).status_code == 403
        for attempt in range(12):
            invalid = invite_login(client, f"Savia_visitor_{attempt:02d}_" + "z" * 32)
            assert invalid.status_code == 401 and "colombia" not in invalid.text
        # All visitors share the proxy IP in a common deployment. Failed
        # guesses must not lock a valid, high-entropy invitation out globally.
        response = invite_login(client)
        assert response.status_code == 200 and response.json()["profile"]["id"] == "colombia"
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/api/auth/me").json()["profile"]["id"] == "colombia"
        overview = client.get("/api/overview").json()
        assert overview["metadata"]["dataset"] == "team-synthetic-fixture"
        assert overview["metadata"]["source_validation"] == "unchanged_inventory_after_ingestion"
        assert "sintéticos" in overview["metadata"]["identity_note"]
        assert "sintéticos" in overview["profile"]["identity_note"]
        assert client.get("/api/chat/status").json()["available"] is False
        assert client.app.state.bank_state.customer("mexico") is None
        with pytest.raises(DatasetUnavailable):
            client.app.state.repository.profile("mexico")
        with client.app.state.bank_state.connect() as db:
            db.execute("DELETE FROM profiles WHERE id='colombia'")
        assert client.get("/api/overview").status_code == 503
        assert client.app.state.bank_state.customer("colombia") is None


def test_invited_profile_cannot_resolve_another_visitors_charge(settings):
    candidate = invite_settings(settings)
    mexico_code = "Savia_visitor_" + "m" * 32
    candidate = replace(candidate,
                        invites={**candidate.invites, hashlib.sha256(mexico_code.encode()).hexdigest(): "mexico"},
                        profiles={**candidate.profiles, "mexico": settings.profiles["mexico"]})
    with TestClient(create_app(candidate), base_url="http://localhost") as client:
        assert invite_login(client).status_code == 200
        owned = client.get("/api/overview").json()["transactions"][0]["reference"]
        assert invite_login(client, mexico_code).status_code == 200
        assert client.get("/api/overview").json()["profile"]["id"] == "mexico"
        assert client.app.state.repository.transaction("mexico", owned) is None
        denied = client.post("/api/chat/messages", json={"message": "Revisa este cargo",
                                                  "transaction_reference": owned},
                             headers={"origin": "http://localhost"})
        assert denied.status_code == 404


def test_invite_requires_pinned_synthetic_mount_even_after_cached_health(settings):
    candidate = invite_settings(settings)
    marker = settings.data_dir / "builds" / "fixture-1" / "synthetic_provenance.json"
    with TestClient(create_app(candidate), base_url="http://localhost") as client:
        assert client.get("/healthz").status_code == 200
        marker.write_text(json.dumps({**candidate.expected_snapshot, "kind": "not_synthetic"}))
        assert client.get("/healthz").status_code == 503
        marker.unlink()
        assert client.get("/healthz").status_code == 503
    with pytest.raises(DatasetUnavailable):
        with TestClient(create_app(candidate), base_url="http://localhost"):
            pass


def test_invite_policy_rotation_revokes_demo_and_prior_invite_sessions(settings):
    with TestClient(create_app(settings), base_url="http://localhost") as demo:
        assert login(demo).status_code == 200
        old_demo_cookie = demo.cookies.get(COOKIE)
    candidate = invite_settings(settings)
    with TestClient(create_app(candidate), base_url="http://localhost") as first:
        first.cookies.set(COOKIE, old_demo_cookie)
        assert first.get("/api/auth/me").status_code == 401
        first.cookies.clear()
        assert invite_login(first).status_code == 200
        old_invite_cookie = first.cookies.get(COOKIE)
    rotated = replace(candidate, invites={hashlib.sha256(REPLACEMENT_INVITE_CODE.encode()).hexdigest(): "colombia"})
    with TestClient(create_app(rotated), base_url="http://localhost") as second:
        second.cookies.set(COOKIE, old_invite_cookie)
        assert second.get("/api/auth/me").status_code == 401
        second.cookies.clear()
        assert invite_login(second).status_code == 401
        assert invite_login(second, REPLACEMENT_INVITE_CODE).status_code == 200
        rotated_cookie = second.cookies.get(COOKIE)
    with TestClient(create_app(settings), base_url="http://localhost") as restored_demo:
        restored_demo.cookies.set(COOKIE, rotated_cookie)
        assert restored_demo.get("/api/auth/me").status_code == 401
        restored_demo.cookies.clear()
        assert login(restored_demo).status_code == 200


def test_invite_configuration_rejects_unsafe_or_ambiguous_bindings(settings):
    candidate = invite_settings(settings)
    for changes in ({"public_origin": "http://bank.example"},
                    {"public_origin": "https://bank.example", "secure_cookie": False},
                    {"public_origin": None},
                    {"invites": {"plaintext": "colombia"}},
                    {"profiles": {}},
                    {"expected_snapshot": {**candidate.expected_snapshot, "kind": "legacy_inventory"}},
                    {"chat": {"base_url": "http://flujo:4200"}}):
        with pytest.raises(ValueError):
            replace(candidate, **changes)
    secured = replace(candidate, public_origin="https://bank.example", secure_cookie=True)
    with TestClient(create_app(secured), base_url="https://bank.example") as client:
        assert invite_login(client, headers={"origin": "http://bank.example"}).status_code == 403
        response = invite_login(client, headers={"origin": "https://bank.example"})
        assert response.status_code == 200 and "Secure" in response.headers["set-cookie"]


def test_changed_private_profile_binding_revokes_old_deployment_cookie(settings):
    with TestClient(create_app(settings)) as old_client:
        login(old_client)
        cookie = old_client.cookies.get(COOKIE)
        profiles = {**settings.profiles, "colombia": {"customer_id": "new-private-customer"}}
        with TestClient(create_app(replace(settings,profiles=profiles))) as restarted:
            restarted.cookies.set(COOKIE,cookie)
            assert restarted.get("/api/auth/me").status_code == 401


def test_private_demo_code_rotation_revokes_existing_cookie(settings):
    with TestClient(create_app(settings)) as first:
        assert login(first).status_code == 200
        old_cookie = first.cookies.get(COOKIE)
    with TestClient(create_app(replace(settings, demo_code="rotated-private-code"))) as second:
        second.cookies.set(COOKIE, old_cookie)
        assert second.get("/api/auth/me").status_code == 401
        assert login(second).status_code == 401
        assert second.post("/api/auth/login", json={"profile": "colombia", "code": "rotated-private-code"}).status_code == 200


@pytest.mark.parametrize("manifest", [[], None, {"build_id":"fixture-1","source_fingerprint":"a"*16,"gold_files":{}}])
def test_malformed_published_inventory_is_service_unavailable(settings, manifest):
    (settings.data_dir / "builds/fixture-1/snapshot.json").write_text(json.dumps(manifest))
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").status_code == 503
        assert client.get("/api/auth/profiles").status_code == 503


def test_cent_precision_summary_and_explicit_snapshot_provenance(settings):
    products = settings.data_dir / "builds/fixture-1/silver/products.parquet"
    with duckdb.connect() as con:
        con.execute("CREATE TABLE amounts AS SELECT * FROM read_parquet(?)", [str(products)])
        con.execute("UPDATE amounts SET current_balance=0.10 WHERE product_id='private-account-co'")
        con.execute("UPDATE amounts SET current_balance=0.20,currency='COP' WHERE product_id='private-account-usd'")
        con.execute("COPY amounts TO ? (FORMAT PARQUET)",[str(products)])
    manifest_file = settings.data_dir / "builds/fixture-1/snapshot.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["source_validation"] = "legacy_inventory"
    manifest_file.write_text(json.dumps(manifest))
    with TestClient(create_app(settings)) as client:
        login(client)
        data=client.get("/api/overview").json()
        assert data["summary"]["balances_by_currency"][0]["deposit_balance"] == 0.30
        assert data["metadata"]["source_validation"] == "legacy_inventory"
        assert data["metadata"]["freshness"] == "derived_snapshot"


def test_transaction_filters_run_before_page_limit_and_keep_owner_scope(settings):
    with TestClient(create_app(settings)) as client:
        login(client)
        pending = client.get("/api/transactions?status=Pending&limit=1").json()
        assert len(pending["transactions"]) == 1 and pending["transactions"][0]["status"] == "Pending"
        assert pending["metadata"]["filtered_count"] == 1
        data = client.get("/api/overview").json()
        card = next(p for p in data["products"] if p["type"] == "Tarjeta Crédito")
        card_history = client.get("/api/transactions",params={"product":card["reference"],"limit":1}).json()
        assert len(card_history["transactions"]) == 1 and card_history["transactions"][0]["type"] == "Purchase"
        search = client.get("/api/transactions?q=transfer&limit=1").json()
        assert len(search["transactions"]) == 1 and search["transactions"][0]["type"] == "Transfer"
        login(client,"mexico")
        foreign = client.get("/api/transactions",params={"product":card["reference"],"limit":1}).json()
        assert foreign["transactions"] == [] and foreign["metadata"]["filtered_count"] == 0


@pytest.fixture()
def expanded_history(settings, request):
    """Many newer rows with equal timestamps exercise stable page tie-breaking."""
    newer_rows = request.param
    build = settings.data_dir / "builds/fixture-1"
    path = build / "gold" / "transactions_by_customer" / f"bucket={bucket('private-customer-co')}" / "data_0.parquet"
    with duckdb.connect() as con:
        con.execute("CREATE TABLE history AS SELECT * FROM read_parquet(?)", [str(path)])
        con.execute("""CREATE TABLE expanded AS SELECT h.* REPLACE (
            'private-new-' || n.seq::VARCHAR AS transaction_id,
            TIMESTAMP '2026-06-18' AS transaction_date
        ) FROM history h CROSS JOIN range(?) n(seq)
        WHERE transaction_id='private-txn-co-deposit'""", [newer_rows])
        con.execute("INSERT INTO expanded SELECT * FROM history")
        con.execute("COPY expanded TO ? (FORMAT PARQUET)", [str(path)])
    manifest_path = build / "snapshot.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["gold_files"][path.relative_to(build / "gold").as_posix()] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest))
    return settings, newer_rows


@pytest.mark.parametrize("expanded_history", [600, 1600], indirect=True)
def test_history_pages_and_older_chat_selection_keep_strict_ownership(expanded_history):
    settings, newer_rows = expanded_history

    class CapturingChat:
        def __init__(self):
            self.calls = []
            self.public_calls = []

        async def send(self, customer, session_id, expires_at, message, *, display_message=None, selection=None):
            self.calls.append((customer, session_id, expires_at, message))
            self.public_calls.append((display_message, selection))
            return {"reply": "Movimiento recibido", "mode": "flujo", "status": "completed"}

    with TestClient(create_app(settings)) as client:
        assert login(client).status_code == 200
        overview = client.get("/api/overview").json()
        total = newer_rows + 4
        assert len(overview["transactions"]) == 500
        assert overview["metadata"]["transactions_total"] == total
        assert overview["metadata"]["filtered_count"] == total
        assert overview["metadata"]["transactions_limit"] == 500
        assert overview["metadata"]["transactions_offset"] == 0
        assert overview["metadata"]["transactions_truncated"] is True
        assert overview["metadata"]["next_offset"] == 500
        newer = overview["transactions"][0]
        assert newer["occurred_at"].startswith("2026-06-18")
        assert newer["process_date"] == "2026-06-17"

        # A filter can select the old purchase without loading every earlier page.
        older = client.get("/api/transactions", params={"q": "Purchase", "month": "2026-06", "limit": 1}).json()
        assert len(older["transactions"]) == 1
        selected = older["transactions"][0]
        assert selected["type"] == "Purchase" and selected["amount"] == 50
        assert selected["reference"] not in {t["reference"] for t in overview["transactions"]}
        assert older["metadata"]["filtered_count"] == 1
        assert older["metadata"]["transactions_truncated"] is False
        assert older["metadata"]["next_offset"] is None

        # Equal timestamps must not introduce gaps or overlap at page boundaries.
        references = [t["reference"] for t in overview["transactions"]]
        next_offset = overview["metadata"]["next_offset"]
        while next_offset is not None:
            page = client.get("/api/transactions", params={"offset": next_offset}).json()
            assert page["metadata"]["build_id"] == overview["metadata"]["build_id"]
            assert page["metadata"]["transactions_offset"] == next_offset
            assert page["metadata"]["filtered_count"] == total
            references.extend(t["reference"] for t in page["transactions"])
            next_offset = page["metadata"]["next_offset"]
        assert len(references) == len(set(references)) == total
        assert selected["reference"] in references

        filtered_page = client.get("/api/transactions", params={"q": "Purchase", "offset": 1, "limit": 1}).json()
        assert filtered_page["transactions"] == []
        assert filtered_page["metadata"]["filtered_count"] == 1
        assert filtered_page["metadata"]["next_offset"] is None
        assert client.get("/api/transactions?month=2026-13").status_code == 422
        assert client.get("/api/transactions?offset=-1").status_code == 422

        # Selecting a displayed older row must reach chat with its actual facts.
        chat = CapturingChat()
        client.app.state.chat_service = chat
        response = client.post("/api/chat/messages", json={"message": "Explícame este movimiento", "transaction_reference": selected["reference"]})
        assert response.status_code == 200 and len(chat.calls) == 1
        customer, session_id, expires_at, message = chat.calls[0]
        assert customer == "private-customer-co"
        current_session = client.app.state.bank_state.session(client.cookies.get(COOKIE))
        assert (session_id, expires_at) == (current_session.id, current_session.expires_at)
        assert '"type": "Purchase"' in message and '"amount": 50.0' in message
        assert '"occurred_at": "2026-06-17T11:00:00"' in message
        display_message, public_selection = chat.public_calls[0]
        assert display_message == "Explícame este movimiento"
        assert public_selection["reference"] == selected["reference"]
        assert public_selection["amount"] == 50 and public_selection["type"] == "Purchase"

        # A displayed next-day movement must carry its separate MCP query date.
        response = client.post("/api/chat/messages", json={"message": "Explícame este movimiento", "transaction_reference": newer["reference"]})
        assert response.status_code == 200 and len(chat.calls) == 2
        message = chat.calls[1][3]
        assert '"occurred_at": "2026-06-18T00:00:00"' in message
        assert '"process_date": "2026-06-17"' in message
        assert '"mcp_date_window_basis": "process_date"' in message
        display_message, public_selection = chat.public_calls[1]
        assert display_message == "Explícame este movimiento"
        assert public_selection["occurred_at"].startswith("2026-06-18")
        assert "process_date" not in public_selection

        repository = client.app.state.repository
        denied = [
            repository.reference("txn", "private-customer-ar", "private-txn-ar"),
            repository.reference("txn", "private-customer-co", "private-txn-cross-owner"),
            repository.reference("txn", "private-customer-co", "private-txn-co-usd"),
            "txn_" + "0" * 24,
        ]
        for reference in denied:
            response = client.post("/api/chat/messages", json={"message": "Ayuda", "transaction_reference": reference})
            assert response.status_code == 404
            assert response.json()["detail"] == "El movimiento seleccionado no está disponible."
            assert len(chat.calls) == 2

        # The selected owned reference remains unavailable to a different customer.
        assert repository.transaction("argentina", selected["reference"]) is None
