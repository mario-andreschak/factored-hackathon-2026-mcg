from __future__ import annotations

import hashlib
import json

import pytest

from conftest import CUSTOMER_A, CUSTOMER_B


def session(client, slug="fixture-a"):
    response = client.post("/api/session", json={"slug": slug})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["token"]}


@pytest.mark.parametrize("path", ["/api/overview", "/api/transactions", "/api/transactions/TX-BELOW-0",
                                  "/api/insights", "/api/signals", "/api/reviews", "/api/export.csv"])
def test_customer_reads_require_a_session(client, path):
    assert client.get(path).status_code == 401


def test_profile_scope_and_projection(client):
    headers = session(client)
    assert client.post("/api/session", json={"slug": CUSTOMER_A}).status_code == 404
    assert client.get("/api/transactions/TX-FOREIGN", headers=headers).status_code == 404
    assert client.post("/api/reviews", headers=headers, json={"reference": "TX-FOREIGN"}).status_code == 404
    assert client.get("/api/transactions/TX-BELOW-0", headers=headers).status_code == 200
    token = headers["Authorization"] + "x"
    assert client.get("/api/overview", headers={"Authorization": token}).status_code == 401
    for path in ["/api/profiles", "/api/overview", "/api/transactions", "/api/insights", "/api/signals"]:
        response = client.get(path, headers=headers)
        assert response.status_code == 200
        text = json.dumps(response.json())
        assert CUSTOMER_A not in text and CUSTOMER_B not in text
        for forbidden in ["customer_id", "fraud_score", "is_fraud", "_row_hash", "_source_file", "ownership_valid"]:
            assert forbidden not in text


def test_missing_balances_are_unknown_and_known_values_stay_source_values(client):
    overview = client.get("/api/overview", headers=session(client)).json()
    bucket = overview["balances"][0]
    assert bucket["deposit"] == 1000.0
    assert bucket["credit"] is None
    assert bucket["credit_limit"] == 500.0
    product = next(p for p in overview["products"] if p["reference"] == "CREDIT-A")
    assert product["balance"] is None and product["available"] is None


def test_any_missing_contribution_propagates_independent_of_order(client, monkeypatch):
    from server import db
    rows = [
        dict(product_id="P1", product_type="Cuenta Ahorro", currency="USD", current_balance=None),
        dict(product_id="P2", product_type="Cuenta Ahorro", currency="USD", current_balance=100),
        dict(product_id="P3", product_type="Tarjeta Crédito", currency="USD", current_balance=0, credit_limit=None),
    ]
    for ordered in (rows, list(reversed(rows))):
        monkeypatch.setattr(db, "products_for", lambda _, ordered=ordered: ordered)
        bucket = client.get("/api/overview", headers=session(client)).json()["balances"][0]
        assert bucket["deposit"] is None
        assert bucket["credit"] == 0
        assert bucket["credit_limit"] is None
        assert bucket["investment"] == 0  # Known empty category, not missing data.


def test_zero_credit_values_are_known_not_missing():
    from server.security import product_payload
    result = product_payload(dict(product_id="ZERO", product_type="Tarjeta Crédito",
                                  current_balance=0, credit_limit=0))
    assert result["balance"] == result["credit_limit"] == result["available"] == 0


def test_review_separates_customer_words_and_promises_no_bank_action(client):
    headers = session(client)
    response = client.post("/api/reviews", headers=headers, json={
        "reference": "TX-BELOW-0", "note": "customer statement, not source evidence",
        "answers": {"recognise": "no"}, "urgent": True,
    })
    assert response.status_code == 200
    record = response.json()["review"]
    assert record["customer_note"] == "customer statement, not source evidence"
    assert "customer statement" not in json.dumps(record["verified_facts"])
    canonical = json.dumps(record["verified_facts"], sort_keys=True, separators=(",", ":"), default=str)
    assert record["evidence"]["facts_sha256"] == hashlib.sha256(canonical.encode()).hexdigest()
    assert record["reason"] == "security_concern" and record["questions_skipped"] is True
    assert record["local_only"] is True
    for field in ("bank_action_taken", "dispute_submitted", "chargeback_requested",
                  "refund_issued", "agent_transfer", "response_deadline_promised"):
        assert record[field] is False
    other = client.get("/api/reviews", headers=session(client, "fixture-b")).json()["reviews"]
    assert all(row["id"] != record["id"] for row in other)
