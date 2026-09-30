"""Re-check one transaction against the source of record (S3 CSVs) before acting on it.

Gold Parquet is a fast, derived copy. Before the assistant creates a dispute case, the
MCP service calls verify_transaction_in_source() so the case is based on what the source
says *now*, not on a possibly stale build.

Security contract
-----------------
* customer_id MUST come from the verified session, never from model-authored text.
* A transaction that exists but belongs to someone else returns status "not_found",
  exactly like a missing one, so the endpoint cannot be used to probe other customers'
  transaction IDs. The real reason is only in result["audit"] for server-side logs;
  never forward "audit" to the model or the customer.
* Only customer-visible fields are returned (no is_fraud, no fraud_score).
"""

from __future__ import annotations

import time
from contextlib import closing
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import duckdb

from .bronze import PART_RE, list_objects, table_of
from .common import Settings, bucket_for, connect, sql_path
from .lookup import CUSTOMER_FIELDS

VISIBLE = [f.strip() for f in CUSTOMER_FIELDS.split(",")]
COMPARED = ["transaction_date", "amount", "currency", "transaction_status", "merchant_name",
            "transaction_type", "channel"]
_LISTING: dict[str, tuple[float, list[dict]]] = {}
LISTING_TTL_S = 300  # new late partitions become visible within 5 minutes


def _partitions(settings: Settings, table: str, start: date, days: int, refresh: bool) -> list[dict]:
    import re
    cached = _LISTING.get(settings.source)
    if refresh or not cached or time.time() - cached[0] > LISTING_TTL_S:
        _LISTING[settings.source] = (time.time(), list_objects(settings))
    wanted = {(start + timedelta(d)).isoformat() for d in range(days + 1)}
    out = []
    for o in _LISTING[settings.source][1]:
        m = re.search(PART_RE, o["key"])
        if table_of(o["key"]) == table and m and "-".join(m.groups()) in wanted:
            out.append(o)
    return out


def _norm(field: str, value) -> str | None:
    if value is None or value == "":
        return None
    if field == "amount":
        try:
            return str(Decimal(str(value)).normalize())
        except InvalidOperation:
            return str(value)
    if field == "transaction_date":
        return str(value).replace("T", " ")[:19]
    return str(value)


def verify_transaction_in_source(source: str, transaction_id: str, customer_id: str,
                                 process_date: str | date, *, s3: dict | None = None,
                                 gold_dir: Path | str | None = None, search_days: int = 7,
                                 refresh_listing: bool = False) -> dict:
    """Return {"status": "verified" | "changed" | "not_found", "transaction": {...} | None, ...}.

    verified  the source row matches what gold served
    changed   the source row exists for this customer but differs from gold (e.g. a late
              correction); use the returned source values and tell the customer
    not_found no row for this customer (missing, or owned by someone else; see audit)

    Late arrivals: a transaction may sit in a partition after its process_date, so
    partitions process_date .. process_date + search_days are searched and the latest
    version wins, the same rule silver uses.
    """
    t0 = time.perf_counter()
    start = date.fromisoformat(str(process_date)[:10])
    gold_path = Path(gold_dir).resolve() if gold_dir is not None else None
    out_dir = (gold_path.parents[2] if gold_path is not None and gold_path.parent.parent.name == "builds"
               else gold_path.parent if gold_path is not None else Path("data").resolve())
    settings = Settings(source=source, out_dir=out_dir, report_dir=Path("."), tables=[], s3=s3 or {})
    objects = _partitions(settings, "transactions", start, search_days, refresh_listing)
    base = {"transaction_id": transaction_id, "partitions_checked": len(objects)}
    if not objects:
        return {**base, "status": "not_found", "transaction": None,
                "audit": {"reason": "no_source_partition_in_window"},
                "ms": round((time.perf_counter() - t0) * 1000, 1)}

    files = "[" + ", ".join(f"'{sql_path(o['uri'])}'" for o in objects) + "]"
    with closing(connect(settings)) as con:
        rel = con.execute(f"""
            SELECT * FROM read_csv({files}, header = true, all_varchar = true, union_by_name = true,
                                   filename = true, hive_partitioning = false)
            WHERE transaction_id = ?
            ORDER BY filename DESC""", [transaction_id])
        cols = [d[0] for d in rel.description]
        versions = [dict(zip(cols, r)) for r in rel.fetchall()]
    if not versions:
        return {**base, "status": "not_found", "transaction": None, "audit": {"reason": "not_in_source"},
                "ms": round((time.perf_counter() - t0) * 1000, 1)}
    row = versions[0]  # latest partition wins
    key = next((o["key"] for o in objects if row["filename"].replace("\\", "/").endswith(o["key"])), None)
    if row.get("customer_id") != customer_id:
        return {**base, "status": "not_found", "transaction": None,
                "audit": {"reason": "owner_mismatch", "source_key": key},
                "ms": round((time.perf_counter() - t0) * 1000, 1)}

    visible = {f: row.get(f) for f in VISIBLE}
    result = {**base, "status": "verified", "transaction": visible, "process_date": row.get("process_date"),
              "source_key": key, "versions_found": len(versions), "differences": {}, "audit": {}}

    if gold_dir is not None:
        bucket = Path(gold_dir) / "transactions_by_customer" / f"bucket={bucket_for(customer_id)}"
        g = None
        if bucket.exists():
            with closing(duckdb.connect()) as gold_con:
                gr = gold_con.execute(
                    f"SELECT * FROM read_parquet('{sql_path(bucket)}/*.parquet') "
                    f"WHERE transaction_id = ? AND customer_id = ?", [transaction_id, customer_id])
                gcols = [d[0] for d in gr.description]
                hit = gr.fetchone()
                g = dict(zip(gcols, hit)) if hit else None
        if g is not None and not g.get("ownership_valid"):
            return {**base, "status": "not_found", "transaction": None,
                    "audit": {"reason": "product_owner_mismatch", "source_key": key},
                    "ms": round((time.perf_counter() - t0) * 1000, 1)}
        if g is None:
            result["status"] = "changed"
            result["differences"] = {"_row": ["absent in gold", "present in source"]}
        else:
            diffs = {f: [_norm(f, g.get(f)), _norm(f, row.get(f))] for f in COMPARED
                     if _norm(f, g.get(f)) != _norm(f, row.get(f))}
            if diffs:
                result["status"] = "changed"
                result["differences"] = diffs  # {field: [gold, source]}
    result["ms"] = round((time.perf_counter() - t0) * 1000, 1)
    return result
