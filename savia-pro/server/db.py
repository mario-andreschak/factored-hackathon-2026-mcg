"""Savia Pro - read-only access to the serving database.

Every function here is a SELECT. The connection is opened read-only so a bug in
a handler cannot write to the serving build, and the raw lake is never touched
at request time.

DuckDB connections are not thread-safe, so each request borrows a cursor under
a lock. The serving build is small enough that queries finish in well under a
millisecond, which makes the lock uncontended in practice.
"""

from __future__ import annotations

import threading
from typing import Any, Iterable

import duckdb

from .config import SERVING_DB, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX

_lock = threading.Lock()
_connection: duckdb.DuckDBPyConnection | None = None


class ServingUnavailable(RuntimeError):
    pass


def connect() -> duckdb.DuckDBPyConnection:
    global _connection
    if _connection is None:
        if not SERVING_DB.exists():
            raise ServingUnavailable(
                f"no serving database at {SERVING_DB}. Run: python3 tools/build_serving.py")
        _connection = duckdb.connect(str(SERVING_DB), read_only=True)
    return _connection


def rows(sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    with _lock:
        cursor = connect().cursor()
        cursor.execute(sql, list(params))
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, record)) for record in cursor.fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
    found = rows(sql, params)
    return found[0] if found else None


# --------------------------------------------------------------------------
# Catalogue
# --------------------------------------------------------------------------

def build_info() -> dict[str, str]:
    return {r["key"]: r["value"] for r in rows("select key, value from build_info")}


def snapshot_stats() -> dict[str, int]:
    return {r["metric"]: int(r["value"]) for r in rows("select metric, value from snapshot_stats")}


def profiles() -> list[dict[str, Any]]:
    """Public profile list. Deliberately returns no customer identifier."""
    return rows("""
        select p.slug, p.alias, p.note, c.city, c.state, c.country, c.segment,
               c.customer_status, c.registration_date,
               s.transactions, s.products, s.currencies,
               s.first_process_date, s.last_process_date
        from profiles p
        join customers c using (customer_id)
        join customer_stats s using (customer_id)
        order by p.ord
    """)


def customer_for_slug(slug: str) -> dict[str, Any] | None:
    return one("""
        select p.customer_id, p.slug, p.alias, p.note,
               c.city, c.state, c.country, c.segment, c.customer_status, c.registration_date
        from profiles p join customers c using (customer_id)
        where p.slug = ?
    """, [slug])


# --------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------

def products_for(customer_id: str) -> list[dict[str, Any]]:
    return rows("""
        select * from products where customer_id = ?
        order by case product_type
                   when 'Cuenta Ahorro' then 0 when 'Cuenta Corriente' then 1
                   when 'Tarjeta Débito' then 2 when 'Tarjeta Crédito' then 3
                   when 'Inversión' then 4 else 5 end,
                 product_id
    """, [customer_id])


def customer_stats(customer_id: str) -> dict[str, Any]:
    return one("select * from customer_stats where customer_id = ?", [customer_id]) or {}


def monthly_series(customer_id: str, currency: str) -> list[dict[str, Any]]:
    return rows("""
        select strftime(event_date, '%Y-%m') as month,
               sum(case when direction = 'credit'  then amount else 0 end) as inflow,
               sum(case when direction = 'debit'   then amount else 0 end) as outflow,
               sum(case when direction = 'unknown' then amount else 0 end) as undetermined,
               count(*) as count
        from transactions
        where customer_id = ? and currency = ? and transaction_status <> 'Declined'
        group by 1 order by 1
    """, [customer_id, currency])


def currencies_for(customer_id: str) -> list[str]:
    return [r["currency"] for r in rows("""
        select currency, count(*) n from transactions where customer_id = ?
        group by 1 order by n desc
    """, [customer_id])]


def category_totals(customer_id: str, currency: str) -> list[dict[str, Any]]:
    return rows("""
        select coalesce(transaction_category, '__none__') as category,
               sum(amount) as total, count(*) as count
        from transactions
        where customer_id = ? and currency = ? and direction = 'debit'
          and transaction_status = 'Approved'
        group by 1 order by total desc
    """, [customer_id, currency])


def channel_mix(customer_id: str) -> list[dict[str, Any]]:
    return rows("""
        select channel, count(*) as count from transactions
        where customer_id = ? group by 1 order by count desc
    """, [customer_id])


def top_merchants(customer_id: str, currency: str, limit: int = 8) -> list[dict[str, Any]]:
    return rows("""
        select merchant_name as merchant, merchant_category as category,
               sum(amount) as total, count(*) as count, max(event_date) as last_seen
        from transactions
        where customer_id = ? and currency = ? and merchant_name is not null
          and direction = 'debit' and transaction_status = 'Approved'
        group by 1, 2 order by total desc limit ?
    """, [customer_id, currency, limit])


def repeat_merchants(customer_id: str) -> list[dict[str, Any]]:
    """Merchants charging three or more times. The amount spread travels with
    the row so the interface can refuse to call a varying charge a subscription."""
    return rows("""
        select merchant_name as merchant, currency, occurrences, months,
               min_amount, max_amount, avg_amount, last_seen, amount_is_constant
        from repeat_merchants where customer_id = ?
        order by occurrences desc, months desc limit 12
    """, [customer_id])


# --------------------------------------------------------------------------
# Ledger
# --------------------------------------------------------------------------

SORTS = {
    "date_desc": "transaction_date desc, transaction_id desc",
    "date_asc": "transaction_date asc, transaction_id asc",
    "amount_desc": "amount desc, transaction_date desc",
    "amount_asc": "amount asc, transaction_date desc",
}

FLAGS = {
    "pending": "transaction_status = 'Pending'",
    "reversed": "transaction_status = 'Reversed'",
    "declined": "transaction_status = 'Declined'",
    "no_merchant": "merchant_missing",
    "no_category": "transaction_category is null",
    "unknown_direction": "direction = 'unknown'",
    "next_day": "date_gap_days = 1",
    "fx": "currency_differs_from_product",
    "unsettled": "transaction_status <> 'Approved'",
}


def _where(customer_id: str, f: dict[str, Any]) -> tuple[str, list[Any]]:
    clauses = ["customer_id = ?"]
    params: list[Any] = [customer_id]

    simple = [("product", "product_id"), ("type", "transaction_type"),
              ("status", "transaction_status"), ("channel", "channel"),
              ("currency", "currency"), ("direction", "direction")]
    for key, column in simple:
        value = f.get(key)
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)

    category = f.get("category")
    if category == "__none__":
        clauses.append("transaction_category is null")
    elif category:
        clauses.append("transaction_category = ?")
        params.append(category)

    if f.get("date_from"):
        clauses.append("event_date >= ?")
        params.append(f["date_from"])
    if f.get("date_to"):
        clauses.append("event_date <= ?")
        params.append(f["date_to"])
    if f.get("min_amount") is not None:
        clauses.append("amount >= ?")
        params.append(float(f["min_amount"]))
    if f.get("max_amount") is not None:
        clauses.append("amount <= ?")
        params.append(float(f["max_amount"]))

    for flag in f.get("flags") or []:
        if flag in FLAGS:
            clauses.append(FLAGS[flag])

    query = (f.get("q") or "").strip()
    if query:
        # Merchant text is untrusted input from the source system, so it is only
        # ever used as a bound parameter, never concatenated into SQL.
        clauses.append("""(
            lower(coalesce(merchant_name, '')) like '%' || lower(?) || '%'
         or lower(coalesce(transaction_city, '')) like '%' || lower(?) || '%'
         or lower(transaction_id) like '%' || lower(?) || '%'
         or lower(transaction_type) like '%' || lower(?) || '%'
        )""")
        params.extend([query] * 4)

    return " and ".join(clauses), params


def transactions(customer_id: str, f: dict[str, Any]) -> dict[str, Any]:
    where, params = _where(customer_id, f)
    order = SORTS.get(f.get("sort") or "date_desc", SORTS["date_desc"])
    limit = min(int(f.get("limit") or PAGE_LIMIT_DEFAULT), PAGE_LIMIT_MAX)
    offset = max(int(f.get("offset") or 0), 0)

    summary = one(f"""
        select count(*) as matched,
               sum(case when direction = 'credit'  then amount else 0 end) as inflow,
               sum(case when direction = 'debit'   then amount else 0 end) as outflow,
               sum(case when direction = 'unknown' then amount else 0 end) as undetermined,
               count(distinct currency) as currencies
        from transactions where {where}
    """, params) or {"matched": 0}

    page = rows(f"""
        select * from transactions where {where}
        order by {order} limit ? offset ?
    """, [*params, limit + 1, offset])

    has_more = len(page) > limit
    return {
        "rows": page[:limit],
        "summary": summary,
        "offset": offset,
        "limit": limit,
        "next_offset": offset + limit if has_more else None,
        "total": int(customer_stats(customer_id).get("transactions") or 0),
    }


def transaction(customer_id: str, reference: str) -> dict[str, Any] | None:
    return one("select * from transactions where customer_id = ? and transaction_id = ?",
               [customer_id, reference])


def neighbours(customer_id: str, row: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Rows a person would want beside this one: the advertised similar-charge
    rule, then same merchant, then same amount on the same product."""
    reference = row["transaction_id"]

    similar = rows("""
        select t.*, s.hours_apart from similar_charges s
        join transactions t on t.transaction_id = case
              when s.transaction_id = ? then s.prev_id else s.transaction_id end
         and t.customer_id = s.customer_id
        where s.customer_id = ? and (s.transaction_id = ? or s.prev_id = ?)
    """, [reference, customer_id, reference, reference])

    same_merchant = []
    if row.get("merchant_name"):
        same_merchant = rows("""
            select * from transactions
            where customer_id = ? and merchant_name = ? and transaction_id <> ?
            order by abs(date_diff('day', event_date, ?)) limit 5
        """, [customer_id, row["merchant_name"], reference, row["event_date"]])

    same_amount = rows("""
        select * from transactions
        where customer_id = ? and product_id = ? and amount = ? and currency = ?
          and transaction_id <> ?
        order by abs(date_diff('day', event_date, ?)) limit 5
    """, [customer_id, row["product_id"], row["amount"], row["currency"], reference,
          row["event_date"]])

    return {"similar": similar, "same_merchant": same_merchant, "same_amount": same_amount}


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------

SIGNAL_RULES = [
    ("pending", "transaction_status = 'Pending'"),
    ("reversed", "transaction_status = 'Reversed'"),
    ("declined", "transaction_status = 'Declined'"),
    ("fx", "currency_differs_from_product"),
    ("next_day", "date_gap_days = 1"),
    ("no_merchant", "merchant_missing"),
    ("inactive_product", "product_status <> 'Active'"),
]


def signals(customer_id: str) -> list[dict[str, Any]]:
    """Each signal is a count plus real example rows. No scoring, no ranking by
    a model: the rule is stated and the matching rows are shown."""
    out = []
    for kind, clause in SIGNAL_RULES:
        total = one(f"select count(*) n from transactions where customer_id = ? and {clause}",
                    [customer_id])["n"]
        examples = rows(f"""
            select * from transactions where customer_id = ? and {clause}
            order by transaction_date desc limit 3
        """, [customer_id])
        out.append({"kind": kind, "count": int(total), "examples": examples})

    similar = one("select count(*) n from similar_charges where customer_id = ?",
                  [customer_id])["n"]
    examples = rows("""
        select t.* from similar_charges s
        join transactions t on t.transaction_id = s.transaction_id and t.customer_id = s.customer_id
        where s.customer_id = ? limit 3
    """, [customer_id])
    out.append({"kind": "similar_charge", "count": int(similar), "examples": examples})
    return out
