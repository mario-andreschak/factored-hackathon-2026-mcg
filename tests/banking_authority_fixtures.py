"""Explicit authority for newly generated, temporary banking test ledgers."""
from banking_mcp.security import Principal


def ledger_generation(store):
    with store.connect() as db:
        row = db.execute("SELECT generation FROM sandbox_ledger_identity WHERE id=1").fetchone()
    assert row is not None
    return row[0]


def principal_for(store, *fields):
    return Principal(*fields, ledger_generation=ledger_generation(store))
