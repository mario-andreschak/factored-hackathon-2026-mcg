"""Per-customer transaction lookup over gold/transactions_by_customer.

This is the read path the banking MCP service can use. It opens exactly one bucket
(~1/128 of the table), relies on Parquet row-group min/max stats on customer_id to
skip most of it, and only returns rows whose product really belongs to the customer.

The caller MUST pass the customer_id from the verified session, never from model text.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path

import duckdb

from .common import bucket_for, sql_path

CUSTOMER_FIELDS = ("transaction_id, transaction_date, transaction_type, transaction_category, "
                   "amount, currency, channel, merchant_name, transaction_country, "
                   "transaction_city, transaction_status")


def get_customer_transactions(gold_dir: Path | str, customer_id: str, limit: int = 20,
                              con: duckdb.DuckDBPyConnection | None = None) -> list[dict]:
    limit = max(1, min(int(limit), 100))
    con = con or duckdb.connect()
    path = Path(gold_dir) / "transactions_by_customer" / f"bucket={bucket_for(customer_id)}"
    if not path.exists():
        return []
    rel = con.execute(
        f"""SELECT {CUSTOMER_FIELDS} FROM read_parquet('{sql_path(path)}/*.parquet')
            WHERE customer_id = ? AND ownership_valid
            ORDER BY transaction_date DESC LIMIT ?""", [customer_id, limit])
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, row)) for row in rel.fetchall()]


def bench(gold_dir: Path | str, samples: int = 50) -> dict:
    con = duckdb.connect()
    ids = [r[0] for r in con.execute(f"""
        SELECT DISTINCT customer_id FROM read_parquet(
            '{sql_path(Path(gold_dir) / "transactions_by_customer")}/**/*.parquet')
        WHERE ownership_valid ORDER BY customer_id LIMIT ?""", [samples]).fetchall()]
    timings = []
    for cid in ids:
        t0 = time.perf_counter()
        get_customer_transactions(gold_dir, cid, con=con)
        timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    return {
        "samples": len(timings),
        "p50_ms": round(statistics.median(timings), 1) if timings else None,
        "p95_ms": round(timings[max(0, int(len(timings) * 0.95) - 1)], 1) if timings else None,
        "max_ms": round(timings[-1], 1) if timings else None,
    }
