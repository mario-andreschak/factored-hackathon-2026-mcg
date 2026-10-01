"""Synthetic fixtures only: never open the published organizer lake."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("savia_build_serving", ROOT / "tools" / "build_serving.py")
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

CUSTOMER_A = "SYNTHETIC-CUSTOMER-A"
CUSTOMER_B = "SYNTHETIC-CUSTOMER-B"


@pytest.fixture
def synthetic_lake(tmp_path, monkeypatch):
    # The apostrophe also covers SQL quoting of a local source path.
    lake = tmp_path / "synthetic's-lake"
    build = lake / "builds" / "fixture-build"
    silver = build / "silver"
    gold = build / "gold" / "transactions_by_customer" / "bucket=0"
    silver.mkdir(parents=True)
    gold.mkdir(parents=True)
    (lake / "CURRENT").write_text("fixture-build\n", encoding="utf-8")
    (build / "snapshot.json").write_text(json.dumps({
        "build_id": "fixture-build", "source_fingerprint": "synthetic-only",
        "created_at": "2026-01-01T00:00:00Z", "source_validation": "synthetic-only",
    }), encoding="utf-8")
    monkeypatch.setattr(builder, "PROFILES", [
        dict(slug="fixture-a", customer_id=CUSTOMER_A, alias="Fixture One", note="Synthetic"),
        dict(slug="fixture-b", customer_id=CUSTOMER_B, alias="Fixture Two", note="Synthetic"),
    ])
    con = duckdb.connect()
    con.execute("""create table customers (
        customer_id varchar, city varchar, state varchar, country varchar,
        segment varchar, customer_status varchar, registration_date date)""")
    con.executemany("insert into customers values (?, 'Test', 'Test', 'Test', 'Basic', 'Active', '2020-01-01')",
                    [(CUSTOMER_A,), (CUSTOMER_B,)])
    con.execute("""create table products (
        product_id varchar, customer_id varchar, product_type varchar, currency varchar,
        current_balance double, credit_limit double, interest_rate double,
        opening_date date, expiration_date date, product_status varchar,
        opening_channel varchar, has_linked_app boolean, days_past_due integer,
        last_transaction_date timestamp, _fk_customer_id_missing boolean)""")
    con.executemany("""insert into products values (
        ?, ?, ?, 'USD', ?, ?, 0, '2020-01-01', null, 'Active', 'App', true, 0,
        '2026-01-01 00:00:00', false)""", [
        ("PRODUCT-A", CUSTOMER_A, "Cuenta Ahorro", 1000.0, None),
        ("CREDIT-A", CUSTOMER_A, "Tarjeta Crédito", None, 500.0),
        ("PRODUCT-B", CUSTOMER_B, "Cuenta Ahorro", 200.0, None),
    ])
    con.execute("""create table transactions (
        transaction_id varchar, customer_id varchar, product_id varchar,
        transaction_date timestamp, process_date date, transaction_type varchar,
        transaction_category varchar, amount double, currency varchar, amount_usd double,
        channel varchar, merchant_name varchar, merchant_category varchar,
        transaction_country varchar, transaction_city varchar, transaction_status varchar,
        response_code varchar, ownership_valid boolean, is_fraud boolean,
        fraud_score double, _row_hash varchar, _source_file varchar)""")
    start = datetime(2026, 1, 1, 0, 1)
    rows = []
    for label, hours, minutes, amount in [("BELOW", 71, 59, 10), ("EXACT", 72, 0, 20), ("OVER", 72, 58, 30)]:
        for index, at in enumerate((start, start + timedelta(hours=hours, minutes=minutes))):
            rows.append((f"TX-{label}-{index}", CUSTOMER_A, "PRODUCT-A", at,
                         at.date(), "Purchase", None, amount, "USD", amount, "POS",
                         label, None, "Test", "Test", "Approved", None, True,
                         True, 0.9, "private-row-hash", "private-source-key"))
    rows.append(("TX-FOREIGN", CUSTOMER_B, "PRODUCT-B", start, start.date(),
                 "Purchase", None, 15, "USD", 15, "POS", "Foreign", None,
                 "Test", "Test", "Approved", None, True, False, 0.1, "private", "private"))
    con.executemany("insert into transactions values (" + ",".join(["?"] * 22) + ")", rows)

    def write_source():
        for table, path in [("customers", silver / "customers.parquet"),
                            ("products", silver / "products.parquet"),
                            ("transactions", gold / "part.parquet")]:
            if path.exists():
                path.unlink()
            con.execute(f"copy {table} to '{builder._sql_path(path)}' (format parquet)")

    write_source()
    try:
        yield lake, build, con, write_source
    finally:
        con.close()


@pytest.fixture
def serving(synthetic_lake, tmp_path):
    lake, build, _, _ = synthetic_lake
    out = tmp_path / "serving.duckdb"
    builder.build_serving(lake, build, out)
    return out


@pytest.fixture
def client(serving, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from server import api, db, reviews

    if db._connection is not None:
        db._connection.close()
    monkeypatch.setattr(db, "_connection", None)
    monkeypatch.setattr(db, "SERVING_DB", serving)
    monkeypatch.setattr(reviews, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(reviews, "LEDGER", tmp_path / "state" / "reviews.jsonl")
    try:
        with TestClient(api.app) as test_client:
            yield test_client
    finally:
        if db._connection is not None:
            db._connection.close()
            db._connection = None
