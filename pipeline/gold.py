"""Gold: one output per consumer.

transactions_by_customer/  MCP banking service   fast per-customer lookup (bucketed + sorted)
contact_demand.parquet     analytics / slides     why disputes: reason x country x month + FCR/escalation
classifier_dataset.parquet ML                     customer text + weak labels + leakage-safe split
demo_seed_candidates.parquet backend / demo       customers that exercise each demo scenario
"""

from __future__ import annotations

import shutil
import time
from contextlib import closing
from dataclasses import replace

from .common import TXN_BUCKETS, Settings, connect, sql_bucket, sql_path, transaction_event_dates

# Classifier split: customers are hashed into 10 folds; time holdout on top of that.
# test  = folds 0-1 AND on/after TIME_HOLDOUT   (unseen customers, future period)
# val   = fold 2 (any date)
# train = folds 3-9 AND before TIME_HOLDOUT
# rest  = excluded (would leak either a customer or the future into train)
TIME_HOLDOUT = "2026-03-17"  # last 3 months of the 2023-06-17 .. 2026-06-17 window
NEAR_DUP_WINDOW = "INTERVAL 1 HOUR"


def run(settings: Settings, run_id: str, stats: dict) -> None:
    # Gold reads only local silver, including a legacy snapshot migration.
    with closing(connect(replace(settings, source="", s3={}))) as con:
        _run(con, settings, run_id, stats)


def _run(con, settings: Settings, run_id: str, stats: dict) -> None:
    settings.gold.mkdir(parents=True, exist_ok=True)
    s = lambda t: sql_path(settings.silver / f"{t}.parquet")
    have = lambda t: (settings.silver / f"{t}.parquet").exists()
    g = stats.setdefault("_gold", {})

    if have("transactions") and have("products") and have("customers"):
        t0 = time.perf_counter()
        out = settings.gold / "transactions_by_customer"
        if out.exists():
            shutil.rmtree(out)  # builds are fresh directories; this only guards manual re-runs
        con.execute(f"""
            COPY (
                SELECT t.transaction_id, t.customer_id, t.product_id, t.transaction_date,
                       t.process_date, t.transaction_type, t.transaction_category, t.amount,
                       t.currency, t.amount_usd, t.channel, t.merchant_name, t.merchant_category,
                       t.transaction_country, t.transaction_city, t.transaction_status,
                       t.response_code,
                       t.is_fraud,                          -- routing only; never shown to customer
                       t._late_arrival,
                       t._source_file, t._partition_date, t._row_hash,
                       -- Served only if the customer exists AND the product exists AND the
                       -- product belongs to that same customer.
                       (c.customer_id IS NOT NULL AND p.product_id IS NOT NULL
                        AND p.customer_id = t.customer_id) AS ownership_valid,
                       {sql_bucket('t.customer_id', TXN_BUCKETS)} AS bucket
                FROM '{s("transactions")}' t
                LEFT JOIN '{s("products")}' p ON p.product_id = t.product_id
                LEFT JOIN '{s("customers")}' c ON c.customer_id = t.customer_id
                ORDER BY bucket, t.customer_id, t.transaction_date DESC
            ) TO '{sql_path(out)}' (FORMAT parquet, PARTITION_BY (bucket), COMPRESSION zstd,
                                    ROW_GROUP_SIZE 20000)
        """)
        rows, valid = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE ownership_valid) "
            f"FROM read_parquet('{sql_path(out)}/**/*.parquet')").fetchone()
        g["transactions_by_customer"] = {"rows": rows, "ownership_valid_rows": valid,
                                         "buckets": TXN_BUCKETS,
                                         "seconds": round(time.perf_counter() - t0, 1),
                                         "transaction_event_dates": transaction_event_dates(
                                             con, list(out.rglob("*.parquet")))}
        print(f"gold    transactions_by_customer   {rows:>11,} rows ({valid:,} ownership-valid)", flush=True)

    if have("call_center_interactions") and have("customers"):
        out = settings.gold / "contact_demand.parquet"
        con.execute(f"""
            COPY (
                SELECT strftime(i.interaction_date, '%Y-%m') AS month,
                       coalesce(c.country, 'UNKNOWN') AS country,
                       i.reason_category, i.contact_reason, i.channel,
                       count(*) AS contacts,
                       count(i.was_resolved) AS resolved_known,
                       avg(i.was_resolved::INT) AS fcr_rate,
                       avg(i.was_escalated::INT) AS escalation_rate,
                       avg(i.requires_followup::INT) AS followup_rate,
                       median(i.wait_time_seconds) AS median_wait_s,
                       median(i.duration_seconds) AS median_duration_s
                FROM '{s("call_center_interactions")}' i
                LEFT JOIN '{s("customers")}' c USING (customer_id)
                GROUP BY ALL ORDER BY month, country, contacts DESC
            ) TO '{sql_path(out)}' (FORMAT parquet)
        """)
        top = con.execute(f"""SELECT contact_reason, sum(contacts) AS n,
                                     sum(contacts) / (SELECT sum(contacts) FROM '{sql_path(out)}') AS pct
                              FROM '{sql_path(out)}' GROUP BY 1 ORDER BY 2 DESC LIMIT 12""").fetchall()
        g["contact_demand"] = {"rows": con.execute(f"SELECT count(*) FROM '{sql_path(out)}'").fetchone()[0],
                               "top_contact_reasons": [{"reason": r, "contacts": n, "share": round(sh, 4)}
                                                       for r, n, sh in top]}
        print(f"gold    contact_demand             {g['contact_demand']['rows']:>11,} rows", flush=True)

    if have("call_transcripts") and have("call_center_interactions"):
        out = settings.gold / "classifier_dataset.parquet"
        cust_join = (f"LEFT JOIN '{s('customers')}' c ON c.customer_id = tr.customer_id"
                     if have("customers") else "")
        country = "c.country" if have("customers") else "NULL"
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE clf AS
            SELECT tr.transcript_id, tr.customer_id, tr.interaction_id,
                   i.interaction_date,
                   tr.customer_text,
                   lower(trim(regexp_replace(tr.customer_text, '\\s+', ' ', 'g'))) AS text_norm,
                   i.contact_reason   AS label_contact_reason,     -- weak label (system-assigned)
                   i.reason_category  AS label_reason_category,    -- weak label
                   tr.detected_intents AS label_detected_intents,  -- model-derived, weakest
                   {country} AS country,
                   tr.detected_accent,
                   {sql_bucket('tr.customer_id', 10)} AS customer_fold,
                   CASE
                     WHEN {sql_bucket('tr.customer_id', 10)} IN (0, 1)
                          AND i.interaction_date >= DATE '{TIME_HOLDOUT}' THEN 'test'
                     WHEN {sql_bucket('tr.customer_id', 10)} = 2 THEN 'val'
                     WHEN {sql_bucket('tr.customer_id', 10)} >= 3
                          AND i.interaction_date < DATE '{TIME_HOLDOUT}' THEN 'train'
                     ELSE 'excluded'
                   END AS split
            FROM '{s("call_transcripts")}' tr
            JOIN '{s("call_center_interactions")}' i
              ON i.interaction_id = tr.interaction_id AND i.customer_id = tr.customer_id
            {cust_join}
            WHERE tr.customer_text IS NOT NULL
        """)
        # Template leakage: synthetic transcripts may repeat verbatim across customers,
        # so a customer/time split alone does not guarantee unseen text.
        con.execute(f"""
            COPY (
                SELECT clf.*, (clf.text_norm IN (SELECT text_norm FROM clf WHERE split = 'train'))
                              AND clf.split <> 'train' AS text_seen_in_train
                FROM clf ORDER BY transcript_id
            ) TO '{sql_path(out)}' (FORMAT parquet)
        """)
        splits = dict(con.execute(f"SELECT split, count(*) FROM '{sql_path(out)}' GROUP BY 1").fetchall())
        test_n, test_seen = con.execute(
            f"SELECT count(*), count(*) FILTER (WHERE text_seen_in_train) "
            f"FROM '{sql_path(out)}' WHERE split = 'test'").fetchone()
        distinct_texts = con.execute(f"SELECT count(DISTINCT text_norm) FROM '{sql_path(out)}'").fetchone()[0]
        total = sum(splits.values())
        dropped = con.execute(f"""SELECT count(*) FROM '{s("call_transcripts")}' tr
            WHERE tr.customer_text IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM '{s("call_center_interactions")}' i
              WHERE i.interaction_id = tr.interaction_id AND i.customer_id = tr.customer_id)""").fetchone()[0]
        g["classifier_dataset"] = {
            "rows": total, "splits": splits,
            "time_holdout": TIME_HOLDOUT,
            "distinct_normalized_texts": distinct_texts,
            "test_rows_with_text_seen_in_train": test_seen,
            "test_text_leakage_rate": round(test_seen / test_n, 4) if test_n else None,
            "transcripts_without_matching_interaction": dropped,
        }
        print(f"gold    classifier_dataset         {total:>11,} rows | splits {splits} "
              f"| test text seen in train: {g['classifier_dataset']['test_text_leakage_rate']}", flush=True)

    tbc = settings.gold / "transactions_by_customer"
    if tbc.exists():
        out = settings.gold / "demo_seed_candidates.parquet"
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE profile AS
            WITH t AS (
                SELECT * FROM read_parquet('{sql_path(tbc)}/**/*.parquet') WHERE ownership_valid
            ),
            near_dup AS (   -- same product and amount (and merchant, when known) within the window
                SELECT customer_id,
                       transaction_date - lag(transaction_date) OVER (
                           PARTITION BY customer_id, product_id, amount, coalesce(merchant_name, '')
                           ORDER BY transaction_date) AS gap
                FROM t
            ),
            nd AS (SELECT customer_id, count(*) AS n FROM near_dup
                   WHERE gap <= {NEAR_DUP_WINDOW} GROUP BY 1)
            SELECT t.customer_id,
                   count(*) AS n_transactions,
                   count(*) FILTER (WHERE transaction_status = 'Reversed') AS n_reversed,
                   count(*) FILTER (WHERE transaction_status = 'Pending')  AS n_pending,
                   count(*) FILTER (WHERE transaction_status = 'Declined') AS n_declined,
                   count(*) FILTER (WHERE is_fraud) AS n_fraud_flagged,
                   coalesce(any_value(nd.n), 0) AS n_near_duplicate_charges,
                   count(*) FILTER (WHERE merchant_name IS NOT NULL) AS n_with_merchant,
                   max(transaction_date) AS last_transaction_date
            FROM t LEFT JOIN nd USING (customer_id)
            GROUP BY t.customer_id
        """)
        # One small, readable pool per demo scenario. "normal" = happy path with a clean history.
        scenarios = {
            "normal":         "n_reversed = 0 AND n_pending = 0 AND n_declined = 0 AND n_fraud_flagged = 0",
            "reversed":       "n_reversed > 0 AND n_fraud_flagged = 0",
            "pending":        "n_pending > 0 AND n_fraud_flagged = 0",
            "declined":       "n_declined > 0 AND n_fraud_flagged = 0",
            "fraud_flagged":  "n_fraud_flagged > 0",
            "near_duplicate": "n_near_duplicate_charges > 0",
        }
        picks = " UNION ALL ".join(
            f"""(SELECT '{name}' AS scenario, * FROM profile WHERE {cond}
                 ORDER BY (n_transactions BETWEEN 10 AND 80) DESC, n_with_merchant DESC, customer_id
                 LIMIT 25)""" for name, cond in scenarios.items())
        con.execute(f"COPY ({picks}) TO '{sql_path(out)}' (FORMAT parquet)")
        population = con.execute("SELECT " + ", ".join(
            f"count(*) FILTER (WHERE {cond})" for cond in scenarios.values()) + " FROM profile").fetchone()
        picked = dict(con.execute(f"SELECT scenario, count(*) FROM '{sql_path(out)}' GROUP BY 1").fetchall())
        g["demo_seed_candidates"] = {
            "customers_eligible": dict(zip(scenarios, population)),
            "customers_picked": {k: picked.get(k, 0) for k in scenarios},
        }
        print(f"gold    demo_seed_candidates       eligible {g['demo_seed_candidates']['customers_eligible']}",
              flush=True)
