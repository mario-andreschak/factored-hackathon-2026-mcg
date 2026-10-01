#!/usr/bin/env python3
"""Savia Pro - build the serving database from the published organizer snapshot.

This is the only component that touches the raw lakehouse. It reads the
read-only Parquet build mounted at /banking-data, keeps the rows that belong to
the approved demo customers, and writes a small DuckDB file the API serves from.

Why a serving build instead of querying the lake per request:

  * the gold layer is 4.4 million rows across 128 buckets; a full scan takes
    seconds, which is not an interactive latency budget;
  * ownership has to be enforced once, provably, at build time rather than
    hoped for on every request;
  * the columns the browser must never see (fraud flags, source keys, row
    hashes, partition metadata) are dropped here, so they cannot leak later
    through a forgotten SELECT *.

Run:  python3 tools/build_serving.py            # uses /banking-data/CURRENT
      python3 tools/build_serving.py --verify   # also re-reads and asserts
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import duckdb

LAKE = Path(os.environ.get("SAVIA_LAKE", "/banking-data"))
OUT = Path(os.environ.get("SAVIA_SERVING", Path(__file__).resolve().parents[1] / "var" / "serving.duckdb"))

# Approved demo customers. Chosen by measuring the real snapshot for breadth:
# transaction count, number of products, more than one currency, and at least
# one of every transaction status. See docs section "Choosing the profiles".
PROFILES = [
    dict(slug="ar-premium",  customer_id="CLI-06IPRRS0DV7R", alias="Valentina Ferreyra",
         note="Premium, Buenos Aires. Mortgage, USD investment and a closed savings account."),
    dict(slug="ar-basic",    customer_id="CLI-AD13IUTW7LEK", alias="Tomás Aguirre",
         note="Basic, La Plata. The heaviest ledger, and three quarters of it has no merchant."),
    dict(slug="co-plus",     customer_id="CLI-TVX8Q10GJDTW", alias="Mariana Ocampo",
         note="Plus, Medellín. Ten products across COP and USD."),
    dict(slug="co-blocked",  customer_id="CLI-HMZRKO0S07TC", alias="Andrés Villalba",
         note="Basic, Cartagena. Holds a blocked credit card that still carries history."),
    dict(slug="co-inactive", customer_id="CLI-V3CA9GOAY6CN", alias="Lucía Betancur",
         note="Basic, Bogotá. The customer record itself is marked inactive."),
]

# Columns the serving layer is allowed to carry out of the lake. Anything not
# listed here never reaches the database the API opens.
TX_COLUMNS = [
    "transaction_id", "customer_id", "product_id", "transaction_date", "process_date",
    "transaction_type", "transaction_category", "amount", "currency", "amount_usd",
    "channel", "merchant_name", "merchant_category", "transaction_country",
    "transaction_city", "transaction_status", "response_code",
]
FORBIDDEN = ["is_fraud", "fraud_score", "_row_hash", "_source_file", "_run_id",
             "_partition_date", "_ingested_at", "_owner_mismatch_product_id"]


def log(msg: str) -> None:
    print(f"  {msg}", flush=True)


def resolve_build(lake: Path, explicit: str | None) -> Path:
    if explicit:
        path = lake / "builds" / explicit
    else:
        current = (lake / "CURRENT").read_text().strip()
        path = lake / "builds" / current
    if not (path / "gold").is_dir():
        raise SystemExit(f"no gold layer under {path}")
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=None, help="build id under <lake>/builds")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    started = time.time()
    build = resolve_build(LAKE, args.build)
    meta = json.loads((build / "snapshot.json").read_text())
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    print(f"Savia Pro serving build")
    log(f"lake   {LAKE}")
    log(f"build  {meta['build_id']}  fingerprint {meta['source_fingerprint']}")
    log(f"out    {out}")

    gold = str(build / "gold" / "transactions_by_customer" / "**" / "*.parquet")
    silver = build / "silver"

    con = duckdb.connect(str(out))
    con.execute("pragma threads=4")

    # --- source views ------------------------------------------------------
    con.execute(f"""
        create view src_tx as
        select * from read_parquet('{gold}', hive_partitioning=true)
        where ownership_valid
    """)
    con.execute(f"create view src_cust as select * from '{silver / 'customers.parquet'}'")
    con.execute(f"create view src_prod as select * from '{silver / 'products.parquet'}'")

    total_rows = con.execute("select count(*) from src_tx").fetchone()[0]
    log(f"ownership-valid gold rows: {total_rows:,}")

    # --- whole-snapshot statistics, measured once -------------------------
    log("measuring the whole snapshot (this is the slow part) ...")
    # fetchdf() would pull in pandas/numpy; a cursor row plus the column
    # description keeps this script dependency-free apart from duckdb.
    cur = con.execute("""
        select
          count(*)                                                                  as transactions,
          count(distinct customer_id)                                               as customers,
          count(distinct product_id)                                                as products,
          sum(case when merchant_name is null then 1 else 0 end)                    as no_merchant,
          sum(case when transaction_category is null then 1 else 0 end)             as no_category,
          sum(case when date_diff('day', process_date, cast(transaction_date as date)) = 1
                   then 1 else 0 end)                                               as next_day_event,
          sum(case when transaction_status = 'Pending'  then 1 else 0 end)          as pending,
          sum(case when transaction_status = 'Reversed' then 1 else 0 end)          as reversed,
          sum(case when transaction_status = 'Declined' then 1 else 0 end)          as declined,
          min(process_date)                                                         as first_process_date,
          max(process_date)                                                         as last_process_date,
          max(cast(transaction_date as date))                                       as last_event_date
        from src_tx
    """)
    stats = dict(zip([d[0] for d in cur.description], cur.fetchone()))

    # The duplicate rule the product advertises, evaluated over the entire
    # snapshot so the UI can state the real answer instead of guessing.
    dup_total = con.execute("""
        with t as (
          select lag(transaction_date) over (
                   partition by customer_id, merchant_name, amount, currency
                   order by transaction_date) as prev,
                 transaction_date
          from src_tx where merchant_name is not null)
        select count(*) from t
        where prev is not null and date_diff('hour', prev, transaction_date) <= 72
    """).fetchone()[0]
    stats["similar_charge_pairs_72h"] = dup_total
    stats["distinct_merchant_names"] = con.execute(
        "select count(distinct merchant_name) from src_tx").fetchone()[0]
    log(f"similar-charge pairs within 72h across the whole snapshot: {dup_total:,}")

    con.execute("create table build_info (key varchar, value varchar)")
    for key, value in [
        ("build_id", meta["build_id"]),
        ("source_fingerprint", meta["source_fingerprint"]),
        ("snapshot_created_at", meta["created_at"]),
        ("source_validation", meta.get("source_validation", "unknown")),
        ("serving_built_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        ("lake_path", str(LAKE)),
    ]:
        con.execute("insert into build_info values (?, ?)", [key, str(value)])

    con.execute("create table snapshot_stats (metric varchar, value bigint, note varchar)")
    for metric in ["transactions", "customers", "products", "no_merchant", "no_category",
                   "next_day_event", "pending", "reversed", "declined",
                   "similar_charge_pairs_72h", "distinct_merchant_names"]:
        con.execute("insert into snapshot_stats values (?, ?, ?)",
                    [metric, int(stats[metric]), "whole published snapshot"])
    for metric in ["first_process_date", "last_process_date", "last_event_date"]:
        con.execute("insert into build_info values (?, ?)", [metric, str(stats[metric])])

    # --- approved customers ------------------------------------------------
    ids = [p["customer_id"] for p in PROFILES]
    placeholders = ", ".join(f"'{i}'" for i in ids)

    found = {r[0] for r in con.execute(
        f"select customer_id from src_cust where customer_id in ({placeholders})").fetchall()}
    missing = [i for i in ids if i not in found]
    if missing:
        raise SystemExit(f"approved customers absent from this build: {missing}")

    con.execute(f"""
        create table customers as
        select customer_id, city, state, country, segment, customer_status,
               cast(registration_date as date) as registration_date
        from src_cust where customer_id in ({placeholders})
    """)

    con.execute("create table profiles (slug varchar, customer_id varchar, alias varchar, note varchar, ord integer)")
    for order, profile in enumerate(PROFILES):
        con.execute("insert into profiles values (?, ?, ?, ?, ?)",
                    [profile["slug"], profile["customer_id"], profile["alias"], profile["note"], order])

    # --- products ----------------------------------------------------------
    con.execute(f"""
        create table products as
        select product_id, customer_id, product_type, currency,
               cast(current_balance as double) as current_balance,
               cast(credit_limit as double)    as credit_limit,
               cast(interest_rate as double)   as interest_rate,
               opening_date, expiration_date, product_status, opening_channel,
               has_linked_app, days_past_due,
               cast(last_transaction_date as timestamp) as last_transaction_date
        from src_prod
        where customer_id in ({placeholders}) and coalesce(_fk_customer_id_missing, false) = false
    """)

    # --- transactions ------------------------------------------------------
    # Ownership is re-checked here by joining to the products actually owned by
    # the customer. A row whose product is not in that set is dropped, so the
    # API can never serve a transaction across an ownership boundary.
    cols = ", ".join(f"t.{c}" for c in TX_COLUMNS)
    con.execute(f"""
        create table transactions as
        select {cols},
               cast(t.transaction_date as date) as event_date,
               date_diff('day', t.process_date, cast(t.transaction_date as date)) as date_gap_days,
               case t.transaction_type
                 when 'Purchase'   then 'debit'
                 when 'Withdrawal' then 'debit'
                 when 'Deposit'    then 'credit'
                 else 'unknown'
               end as direction,
               (t.transaction_status = 'Approved') as is_settled,
               (t.merchant_name is null)           as merchant_missing,
               (p.currency is not null and p.currency <> t.currency) as currency_differs_from_product,
               p.product_type, p.product_status, p.currency as product_currency
        from src_tx t
        join products p on p.product_id = t.product_id and p.customer_id = t.customer_id
        where t.customer_id in ({placeholders})
    """)

    con.execute("create index tx_cust on transactions (customer_id)")
    con.execute("create index tx_ref on transactions (transaction_id)")

    # --- per-customer rollups ---------------------------------------------
    con.execute("""
        create table customer_stats as
        select customer_id,
               count(*) as transactions,
               count(distinct product_id) as products,
               count(distinct currency) as currencies,
               sum(case when merchant_missing then 1 else 0 end) as no_merchant,
               sum(case when transaction_category is null then 1 else 0 end) as no_category,
               sum(case when date_gap_days = 1 then 1 else 0 end) as next_day_event,
               sum(case when direction = 'unknown' then 1 else 0 end) as direction_unknown,
               sum(case when transaction_status = 'Pending' then 1 else 0 end) as pending,
               sum(case when transaction_status = 'Reversed' then 1 else 0 end) as reversed,
               sum(case when transaction_status = 'Declined' then 1 else 0 end) as declined,
               sum(case when currency_differs_from_product then 1 else 0 end) as fx_mismatch,
               min(process_date) as first_process_date,
               max(process_date) as last_process_date
        from transactions group by customer_id
    """)

    # The advertised similar-charge rule, evaluated per approved customer.
    con.execute("""
        create table similar_charges as
        with t as (
          select transaction_id, customer_id, merchant_name, amount, currency, transaction_date,
                 lag(transaction_id)   over w as prev_id,
                 lag(transaction_date) over w as prev_at
          from transactions where merchant_name is not null
          window w as (partition by customer_id, merchant_name, amount, currency
                       order by transaction_date))
        select customer_id, transaction_id, prev_id,
               date_diff('hour', prev_at, transaction_date) as hours_apart
        from t where prev_id is not null
          and date_diff('hour', prev_at, transaction_date) <= 72
    """)

    # Merchants seen three or more times. Grouping by merchant and amount found
    # nothing in this snapshot, because the amounts vary: the same merchant can
    # charge three times with a 3x spread. So the rollup keeps the spread and the
    # product refuses to call any of it a subscription.
    con.execute("""
        create table repeat_merchants as
        select customer_id, merchant_name, currency,
               count(*)                                        as occurrences,
               count(distinct strftime(event_date, '%Y-%m'))    as months,
               min(amount)                                      as min_amount,
               max(amount)                                      as max_amount,
               avg(amount)                                      as avg_amount,
               max(event_date)                                   as last_seen,
               count(distinct amount) = 1                        as amount_is_constant
        from transactions
        where merchant_name is not null and transaction_status = 'Approved'
        group by 1, 2, 3
        having count(*) >= 3
    """)

    for view in ["src_tx", "src_cust", "src_prod"]:
        con.execute(f"drop view {view}")

    # --- guarantees --------------------------------------------------------
    served = con.execute("select count(*) from transactions").fetchone()[0]
    orphans = con.execute("""
        select count(*) from transactions t
        left join products p on p.product_id = t.product_id and p.customer_id = t.customer_id
        where p.product_id is null
    """).fetchone()[0]
    if orphans:
        raise SystemExit(f"{orphans} served transactions fail the ownership join")

    tx_cols = {r[1] for r in con.execute("pragma table_info('transactions')").fetchall()}
    leaked = sorted(tx_cols.intersection(FORBIDDEN))
    if leaked:
        raise SystemExit(f"forbidden columns reached the serving table: {leaked}")

    print("\n  served rows per approved customer")
    for row in con.execute("""
        select p.slug, s.transactions, s.products, s.currencies, s.pending, s.reversed,
               s.declined, s.no_merchant, s.first_process_date, s.last_process_date
        from customer_stats s join profiles p using (customer_id) order by p.ord
    """).fetchall():
        log(f"{row[0]:<12} {row[1]:>4} tx  {row[2]:>2} products  {row[3]} ccy  "
            f"pend {row[4]:>2} rev {row[5]:>2} dec {row[6]:>2}  "
            f"no-merchant {row[7]:>3}  {row[8]} -> {row[9]}")

    con.execute("checkpoint")
    con.close()

    size = out.stat().st_size / 1024
    print(f"\n  {served:,} transactions served from a {size:.0f} KiB database "
          f"({time.time() - started:.1f}s, {orphans} ownership failures, {len(leaked)} leaked columns)")

    if args.verify:
        check = duckdb.connect(str(out), read_only=True)
        tables = {r[0] for r in check.execute("show tables").fetchall()}
        expected = {"build_info", "snapshot_stats", "customers", "profiles", "products",
                    "transactions", "customer_stats", "similar_charges", "repeat_merchants"}
        assert expected.issubset(tables), f"missing tables: {expected - tables}"
        assert check.execute("select count(*) from transactions").fetchone()[0] == served
        check.close()
        print("  verify: reopened read-only, all tables present, row count matches")

    return 0


if __name__ == "__main__":
    sys.exit(main())
