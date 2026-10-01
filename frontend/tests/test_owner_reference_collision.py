"""Pure owned-reference resolver fakes: no app, connection, files or dataset.

The scoped relation is injected, so these tests cover collision handling only;
they do not claim to exercise the real SQL ownership joins or MCP authority.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontend.server.repository import Repository


PUBLIC = "txn_" + "a" * 24
FIRST, SECOND = "generated-owned-charge-a", "generated-owned-charge-b"
OWNER = "generated-owner"


class IdCursor:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.fetches = 0

    def fetchmany(self, size):
        assert size == 1024
        self.fetches += 1
        return [(raw_id,) for raw_id in next(self.batches, [])]


class RowCursor:
    def __init__(self, row):
        self.description = [(key,) for key in row]
        self.row = tuple(row.values())

    def fetchall(self):
        return [self.row]


class ScopedConnection:
    def __init__(self, batches):
        self.ids = IdCursor(batches)
        self.detail_reads = []

    def execute(self, sql, parameters=None):
        if sql == "SELECT transaction_id FROM scoped":
            assert parameters is None
            return self.ids
        assert sql.startswith("SELECT ") and sql.endswith(" FROM scoped WHERE transaction_id=?")
        assert len(parameters) == 1 and parameters[0] in {FIRST, SECOND}
        self.detail_reads.append(parameters[0])
        row = {"transaction_id": parameters[0], "product_id": "generated-owned-product",
               "occurred_at": "2026-09-20T12:00:00", "process_date": "2026-09-20",
               "type": "Purchase", "amount": 42.0, "currency": "COP", "status": "Approved",
               "merchant": "Generated Store", "channel": "App"}
        if ", owned_product_type" in sql:
            row["owned_product_type"] = "Cuenta Ahorro"
        return RowCursor(row)


def owned_resolver(batches):
    repository = Repository.__new__(Repository)
    snapshot = SimpleNamespace(build=Path("generated-only-fixture"))
    connection = ScopedConnection(batches)
    repository.state = SimpleNamespace(customer=lambda profile: OWNER)
    repository.snapshot = lambda: snapshot

    def profile(profile_id, serving):
        assert profile_id == "colombia" and serving is snapshot
        return {"id": profile_id}

    def scoped(con, serving, customer):
        assert con is connection and serving is snapshot and customer == OWNER
        return True

    def reference(kind, customer, raw_id):
        assert customer == OWNER
        if kind == "txn":
            assert raw_id in {FIRST, SECOND}
            return PUBLIC  # Deliberately force two distinct raw IDs to collide.
        assert kind == "prod" and raw_id == "generated-owned-product"
        return "prod_" + "b" * 24

    @contextmanager
    def connect():
        yield connection

    repository.profile, repository._scoped = profile, scoped
    repository.reference, repository.connection = reference, connect
    return repository, connection


@pytest.mark.parametrize("batches", [[[FIRST, SECOND]], [[FIRST], [SECOND]]])
def test_action_target_rejects_distinct_owned_ids_with_same_public_reference(batches):
    repository, connection = owned_resolver(batches)
    assert repository.action_target("colombia", PUBLIC) is None
    assert connection.ids.fetches == len(batches)
    assert connection.detail_reads == []


@pytest.mark.parametrize("batches", [[[FIRST, SECOND]], [[FIRST], [SECOND]]])
def test_ordinary_portal_lookup_keeps_first_match_without_action_authority(batches):
    repository, connection = owned_resolver(batches)
    displayed = repository.transaction("colombia", PUBLIC)
    assert displayed["reference"] == PUBLIC and displayed["merchant"] == "Generated Store"
    assert "transaction_id" not in displayed and "owned_product_type" not in displayed
    assert connection.ids.fetches == 1 and connection.detail_reads == [FIRST]


def test_action_target_accepts_one_owned_raw_id_after_complete_scan():
    repository, connection = owned_resolver([[FIRST]])
    target = repository.action_target("colombia", PUBLIC)
    assert target["transaction_id"] == FIRST and target["snapshot"] == "generated-only-fixture"
    assert target["transaction"]["product"] == "Cuenta Ahorro"
    assert connection.ids.fetches == 2 and connection.detail_reads == [FIRST]
