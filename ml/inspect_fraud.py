"""Does is_fraud carry learnable signal? Run before building any fraud model.

    python -m ml.inspect_fraud

For each candidate feature, transactions are binned and each bin gets its in-sample fraud
rate. Ranking transactions by that rate gives an AUC:
    ~0.50  the feature says nothing about fraud (label looks random w.r.t. it)
    >0.60  usable signal
    ~1.00  on fraud_score: almost certainly derived from the label (leakage, do not use)
In-sample per-bin AUC is an optimistic upper bound for that single feature, so small
gains above 0.5 on high-cardinality features should be read as noise.

Also reports whether fraud is stable over time and whether it clusters on customers.
Outputs aggregates only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

SILVER = Path("data/silver")


def auc_from_bins(bins: list[tuple[int, int]]) -> float | None:
    """bins: (positives, negatives) per bin. AUC of scoring each row by its bin's rate."""
    P = sum(p for p, _ in bins)
    N = sum(n for _, n in bins)
    if not P or not N:
        return None
    ordered = sorted(bins, key=lambda b: b[0] / (b[0] + b[1]))
    neg_below, acc = 0, 0.0
    for p, n in ordered:
        acc += p * (neg_below + 0.5 * n)
        neg_below += n
    return acc / (P * N)


FEATURES = {
    # name: SQL expression over table t (transactions joined to customer country c_country)
    "transaction_type":     "transaction_type",
    "transaction_category": "coalesce(transaction_category, 'NULL')",
    "channel":              "channel",
    "transaction_status":   "transaction_status",
    "response_code":        "coalesce(response_code, 'NULL')",
    "currency":             "currency",
    "transaction_country":  "transaction_country",
    "cross_border":         "(lower(strip_accents(transaction_country)) <> lower(strip_accents(c_country)))::VARCHAR",
    "merchant_category":    "coalesce(merchant_category, 'NULL')",
    "merchant_present":     "(merchant_name IS NOT NULL)::VARCHAR",
    "hour_of_day":          "hour(transaction_date)::VARCHAR",
    "weekday":              "dayofweek(transaction_date)::VARCHAR",
    "amount_usd_ventile":   "coalesce(ntile(20) OVER (ORDER BY amount_usd)::VARCHAR, 'NULL')",
    "amount_ventile_in_ccy":"currency || ':' || ntile(20) OVER (PARTITION BY currency ORDER BY amount)::VARCHAR",
    "txns_same_customer_day": "least(count(*) OVER (PARTITION BY customer_id, transaction_date::DATE), 10)::VARCHAR",
    "minutes_since_prev_txn": """coalesce(least(floor(log2(1 + date_diff('minute',
                                 lag(transaction_date) OVER (PARTITION BY customer_id ORDER BY transaction_date),
                                 transaction_date))), 20)::VARCHAR, 'first')""",
    "customer_segment":     "coalesce(c_segment, 'NULL')",
    "product_type":         "coalesce(p_type, 'NULL')",
    "fraud_score_decile":   "coalesce(ntile(10) OVER (ORDER BY fraud_score)::VARCHAR, 'NULL')",
    "fraud_score_null":     "(fraud_score IS NULL)::VARCHAR",
}


def main() -> int:
    tx = SILVER / "transactions.parquet"
    if not tx.exists():
        print(f"{tx} not found. Run: python -m pipeline run --stage silver", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    con = duckdb.connect()
    con.execute("SET enable_progress_bar = false")
    con.execute(f"""
        CREATE TEMP TABLE t AS
        SELECT x.*, c.country AS c_country, c.segment AS c_segment, p.product_type AS p_type
        FROM '{tx.as_posix()}' x
        LEFT JOIN '{(SILVER / "customers.parquet").as_posix()}' c USING (customer_id)
        LEFT JOIN '{(SILVER / "products.parquet").as_posix()}' p USING (product_id)
    """)
    n, pos = con.execute("SELECT count(*), count(*) FILTER (WHERE is_fraud) FROM t").fetchone()
    print(f"transactions {n:,} | is_fraud {pos:,} ({pos / n:.3%})\n")
    if not pos:
        print("No positives: nothing to learn.")
        return 0

    rows = []
    for name, expr in FEATURES.items():
        bins = con.execute(f"""
            SELECT v, count(*) FILTER (WHERE is_fraud), count(*) FILTER (WHERE NOT is_fraud)
            FROM (SELECT {expr} AS v, is_fraud FROM t) GROUP BY v""").fetchall()
        auc = auc_from_bins([(p, q) for _, p, q in bins])
        top = max(bins, key=lambda b: (b[1] / (b[1] + b[2])) if b[1] + b[2] >= 1000 else -1)
        lift = (top[1] / (top[1] + top[2])) / (pos / n) if top[1] + top[2] else 0
        rows.append((name, auc, len(bins), str(top[0])[:28], lift, top[1] + top[2]))

    print(f"{'feature':<24} {'AUC':>6} {'bins':>6}   highest-rate bin (>=1,000 rows)")
    for name, auc, k, v, lift, size in sorted(rows, key=lambda r: -(r[1] or 0)):
        print(f"{name:<24} {auc:>6.3f} {k:>6}   {v:<28} lift {lift:>5.2f}x  n={size:,}")

    print("\nFraud rate by month (stability; a model needs a stable pattern):")
    for month, rate, k in con.execute("""
            SELECT strftime(transaction_date, '%Y-%m'), avg(is_fraud::INT), count(*)
            FROM t GROUP BY 1 ORDER BY 1""").fetchall():
        print(f"  {month}  {rate:.3%}  (n={k:,})")

    print("\nDo fraud flags cluster on customers? (random labels -> close to the Poisson expectation)")
    obs = dict(con.execute("""
        SELECT least(k, 3), count(*) FROM (
            SELECT customer_id, count(*) FILTER (WHERE is_fraud) k FROM t GROUP BY 1) GROUP BY 1""").fetchall())
    customers = sum(obs.values())
    import math
    lam = pos / customers
    exp = {0: math.exp(-lam), 1: lam * math.exp(-lam), 2: lam ** 2 / 2 * math.exp(-lam)}
    exp[3] = 1 - sum(exp.values())
    for k in range(4):
        label = f"{k}+" if k == 3 else str(k)
        print(f"  customers with {label:<2} fraud flags: observed {obs.get(k, 0):>8,}   "
              f"expected if random {exp[k] * customers:>10,.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
