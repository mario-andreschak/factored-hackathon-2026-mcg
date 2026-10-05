"""The portal lists at most three months of history, counted back from the latest event."""
from __future__ import annotations

import json
from dataclasses import replace

import duckdb
import pytest
from fastapi.testclient import TestClient

from frontend.server.app import create_app
from frontend.server.repository import Repository
from frontend.tests.test_api import bucket, login, settings  # noqa: F401 - pytest fixture

# The fixture's latest event is 2026-06-17, so the windows start on these days.
# Each edge pair is one row on the first included day and one on the day before.
EDGE_ROWS = [
    ("private-edge-week-in", "2026-06-11", 1),
    ("private-edge-week-out", "2026-06-10", 2),
    ("private-edge-month-in", "2026-05-19", 4),
    ("private-edge-month-out", "2026-05-18", 8),
    ("private-edge-quarter-in", "2026-03-20", 16),
    ("private-edge-quarter-out", "2026-03-19", 32),
]
BASE_ROWS = 4  # owned Colombian rows already dated 2026-06-17


@pytest.fixture()
def dated_history(settings):  # noqa: F811
    build = settings.data_dir / "builds/fixture-1"
    path = build / "gold" / "transactions_by_customer" / f"bucket={bucket('private-customer-co')}" / "data_0.parquet"
    with duckdb.connect() as con:
        con.execute("CREATE TABLE history AS SELECT * FROM read_parquet(?)", [str(path)])
        for transaction_id, day, amount in EDGE_ROWS:
            con.execute("""INSERT INTO history SELECT * REPLACE (
                ? AS transaction_id, CAST(? AS TIMESTAMP) + INTERVAL 1 HOUR AS transaction_date,
                CAST(? AS DECIMAL(15,2)) AS amount)
                FROM history WHERE transaction_id='private-txn-co-deposit'""", [transaction_id, day, amount])
        con.execute("COPY history TO ? (FORMAT PARQUET)", [str(path)])
    manifest_path = build / "snapshot.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["gold_files"][path.relative_to(build / "gold").as_posix()] = path.stat().st_size
    manifest_path.write_text(json.dumps(manifest))
    return settings


def amounts(rows):
    return sorted(t["amount"] for t in rows if t["occurred_at"] < "2026-06-17")


def test_portal_defaults_to_three_months_and_excludes_older_history(dated_history):
    with TestClient(create_app(dated_history)) as client:
        login(client)
        data = client.get("/api/overview").json()
        assert amounts(data["transactions"]) == [1, 2, 4, 8, 16]
        assert data["metadata"]["transactions_total"] == BASE_ROWS + 5
        assert data["metadata"]["filtered_count"] == BASE_ROWS + 5
        assert data["metadata"]["period"] == "quarter"
        assert data["metadata"]["period_days"] == 90
        assert data["metadata"]["period_start"] == "2026-03-20"
        assert data["metadata"]["data_as_of"].startswith("2026-06-17")
        assert client.get("/api/overview?period=quarter").json()["transactions"] == data["transactions"]


@pytest.mark.parametrize(("period", "start", "expected"), [
    ("week", "2026-06-11", [1]),
    ("month", "2026-05-19", [1, 2, 4]),
    ("quarter", "2026-03-20", [1, 2, 4, 8, 16]),
])
def test_each_period_lists_exactly_its_window(dated_history, period, start, expected):
    with TestClient(create_app(dated_history)) as client:
        login(client)
        data = client.get("/api/overview", params={"period": period}).json()
        assert amounts(data["transactions"]) == expected
        assert data["metadata"]["transactions_total"] == BASE_ROWS + len(expected)
        assert data["metadata"]["period"] == period and data["metadata"]["period_start"] == start
        page = client.get("/api/transactions", params={"period": period, "limit": 1}).json()
        assert page["metadata"]["filtered_count"] == BASE_ROWS + len(expected)
        assert page["metadata"]["next_offset"] == 1


def test_filters_and_pages_never_reach_outside_the_window(dated_history):
    with TestClient(create_app(dated_history)) as client:
        login(client)
        march = client.get("/api/transactions", params={"month": "2026-03"}).json()
        assert [t["amount"] for t in march["transactions"]] == [16]
        assert client.get("/api/transactions", params={"month": "2026-03", "period": "month"}).json()["transactions"] == []
        references = []
        offset = 0
        while offset is not None:
            page = client.get("/api/transactions", params={"period": "quarter", "limit": 2, "offset": offset}).json()
            references.extend(t["reference"] for t in page["transactions"])
            offset = page["metadata"]["next_offset"]
        assert len(references) == len(set(references)) == BASE_ROWS + 5


def test_monthly_activity_covers_three_months_whatever_period_is_listed(dated_history):
    with TestClient(create_app(dated_history)) as client:
        login(client)
        for period in ("week", "month", "quarter"):
            activity = {m["month"]: m for m in client.get("/api/overview", params={"period": period}).json()[
                "summary"]["monthly_activity"] if m["currency"] == "COP"}
            assert sorted(activity) == ["2026-03", "2026-05", "2026-06"]
            assert activity["2026-03"]["inflow"] == 16  # the 2026-03-19 deposit is outside
            assert activity["2026-05"]["inflow"] == 4 + 8


@pytest.mark.parametrize("period", ["year", "all", "", "QUARTER"])
def test_unknown_periods_are_rejected(dated_history, period):
    with TestClient(create_app(dated_history)) as client:
        login(client)
        assert client.get("/api/overview", params={"period": period}).status_code == 422
        assert client.get("/api/transactions", params={"period": period}).status_code == 422


def test_internal_full_history_and_reference_lookup_are_not_windowed(dated_history):
    """Disputes search and resolve older owned rows; only the portal listing is bounded."""
    with TestClient(create_app(dated_history)) as client:
        login(client)
        repository = client.app.state.repository
        assert amounts(repository.overview("colombia")["transactions"]) == [1, 2, 4, 8, 16, 32]
        with pytest.raises(ValueError):
            repository.overview("colombia", period="year")
        older = repository.reference("txn", "private-customer-co", "private-edge-quarter-out")
        assert repository.transaction("colombia", older)["amount"] == 32


def test_window_advances_with_newer_published_data(dated_history):
    with TestClient(create_app(dated_history)) as client:
        snapshot = client.app.state.repository.snapshot()
    assert Repository.history_start(snapshot, "quarter").isoformat() == "2026-03-20"
    tomorrow = replace(snapshot, data_as_of="2026-06-18T09:30:00")
    assert Repository.history_start(tomorrow, "week").isoformat() == "2026-06-12"
    assert Repository.history_start(tomorrow, "quarter").isoformat() == "2026-03-21"
    assert Repository.history_start(replace(snapshot, data_as_of=None), "quarter") is None
