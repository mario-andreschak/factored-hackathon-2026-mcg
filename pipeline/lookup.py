"""Per-customer transaction lookup over gold/transactions_by_customer.

This is the read path the banking MCP service can use. It opens exactly one bucket
(~1/128 of the table), relies on Parquet row-group min/max stats on customer_id to
skip most of it, and only returns rows whose product really belongs to the customer.

The caller MUST pass the customer_id from the verified session, never from model text.
"""

from __future__ import annotations

import statistics
import threading
import time
from pathlib import Path

import duckdb

from .common import bucket_for, sql_path

CUSTOMER_FIELDS = ("transaction_id, transaction_date, transaction_type, transaction_category, "
                   "amount, currency, channel, merchant_name, transaction_country, "
                   "transaction_city, transaction_status")


_DEFAULT: duckdb.DuckDBPyConnection | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_connection() -> duckdb.DuckDBPyConnection:
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = duckdb.connect()
        return _DEFAULT


def get_customer_transactions(gold_dir: Path | str, customer_id: str, limit: int = 20,
                              con: duckdb.DuckDBPyConnection | None = None) -> list[dict]:
    """Newest transactions of ONE customer from a published gold snapshot.

    Isolation: `con` (optional) is only used as a factory. Every call opens its own cursor,
    runs execute -> description -> fetch on it, and closes it. The shared connection's
    own result slot is never used, so two concurrent callers cannot read each other's
    results (DuckDB's execute() returns the connection itself; interleaving
    A-execute, B-execute, A-fetch on a shared connection hands B's rows to A).
    """
    limit = max(1, min(int(limit), 100))
    path = Path(gold_dir) / "transactions_by_customer" / f"bucket={bucket_for(customer_id)}"
    if not path.exists():
        return []
    cur = (con or _default_connection()).cursor()
    try:
        cur.execute(
            f"""SELECT {CUSTOMER_FIELDS} FROM read_parquet('{sql_path(path)}/*.parquet')
                WHERE customer_id = ? AND ownership_valid
                ORDER BY transaction_date DESC LIMIT ?""", [customer_id, limit])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        cur.close()
    return [dict(zip(cols, row)) for row in rows]


def _pct(sorted_ms: list[float], q: float) -> float | None:
    if not sorted_ms:
        return None
    return round(sorted_ms[min(len(sorted_ms) - 1, max(0, int(round(q * len(sorted_ms))) - 1))], 1)


def bench_concurrent(gold_dir: Path | str, levels=(1, 50, 500), requests: int = 1000) -> dict:
    """Latency and throughput with N simultaneous callers (threads, one DuckDB cursor per request).

    Each level issues `requests` lookups for customers drawn round-robin from a fixed sample,
    so levels are comparable. This measures the storage layer in one process on one machine;
    a deployed service adds network and server overhead on top.
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    gold_dir = Path(gold_dir)
    base = duckdb.connect()
    ids = [r[0] for r in base.execute(f"""
        SELECT DISTINCT customer_id FROM read_parquet(
            '{sql_path(gold_dir / "transactions_by_customer")}/**/*.parquet')
        WHERE ownership_valid ORDER BY customer_id LIMIT 500""").fetchall()]
    if not ids:
        return {"levels": [], "note": "no customers in gold"}
    out = []
    for n in levels:
        def one(i: int):
            t0 = time.perf_counter()
            try:
                get_customer_transactions(gold_dir, ids[i % len(ids)], con=base)
                return (time.perf_counter() - t0) * 1000, None
            except Exception as exc:  # counted, not raised: a benchmark must finish
                return (time.perf_counter() - t0) * 1000, type(exc).__name__

        t0 = time.perf_counter()
        with ThreadPoolExecutor(max_workers=n) as pool:
            results = list(pool.map(one, range(max(requests, n))))
        wall = time.perf_counter() - t0
        ok = sorted(ms for ms, err in results if err is None)
        errors = [err for _, err in results if err]
        out.append({"concurrency": n, "requests": len(results), "ok": len(ok), "errors": len(errors),
                    "error_types": sorted(set(errors)), "p50_ms": _pct(ok, 0.50), "p95_ms": _pct(ok, 0.95),
                    "p99_ms": _pct(ok, 0.99), "throughput_rps": round(len(results) / wall, 1)})
    return {"machine_cpus": os.cpu_count(), "customers_sampled": len(ids),
            "method": "in-process threads sharing one DuckDB connection, one cursor per request, "
                      "local gold Parquet (published snapshot)",
            "levels": out}


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
