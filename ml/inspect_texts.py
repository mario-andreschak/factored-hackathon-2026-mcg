"""Inspect the distinct customer texts in gold/classifier_dataset and how they relate to labels.

    python -m ml.inspect_texts

Prints, for every distinct normalized customer_text: its frequency, how its rows are spread
across contact_reason, and how pure that spread is. If a text maps to many reasons at
similar rates, the weak label is noise for that text and cannot be learned from the text.

Also writes data/ml/text_inventory.csv (git-ignored) for manual labelling.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb

from pipeline.common import current_gold

OUT = Path("data/ml/text_inventory.csv")


def main() -> int:
    try:
        DATASET = current_gold("data") / "classifier_dataset.parquet"
    except FileNotFoundError as exc:
        print(f"{exc}. Run: python -m pipeline run --stage silver gold", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8")
    con = duckdb.connect()
    con.execute(f"CREATE VIEW d AS SELECT * FROM '{DATASET.as_posix()}'")

    total, texts, reasons = con.execute(
        "SELECT count(*), count(DISTINCT text_norm), count(DISTINCT label_contact_reason) FROM d").fetchone()
    print(f"rows {total:,} | distinct texts {texts} | distinct contact_reason {reasons}\n")

    # How much does the text tell us about the label? Compare the majority-label accuracy
    # obtainable from the text alone against always predicting the global majority.
    best_by_text, majority = con.execute("""
        WITH c AS (SELECT text_norm, label_contact_reason, count(*) n FROM d GROUP BY 1, 2)
        SELECT (SELECT sum(m) FROM (SELECT max(n) m FROM c GROUP BY text_norm)) / sum(n),
               (SELECT max(t) FROM (SELECT sum(n) t FROM c GROUP BY label_contact_reason)) / sum(n)
        FROM c""").fetchone()
    print(f"Upper bound of ANY text classifier on contact_reason: {best_by_text:.1%}")
    print(f"Always predicting the most common reason:            {majority:.1%}")
    print("If these are close, contact_reason is not predictable from the text.\n")

    rows = con.execute("""
        WITH c AS (SELECT text_norm, label_contact_reason r, count(*) n FROM d GROUP BY 1, 2),
             t AS (SELECT text_norm, sum(n) total, max(n) top FROM c GROUP BY 1)
        SELECT t.text_norm, t.total, round(t.top / t.total, 3) AS purity,
               string_agg(c.r || ' ' || round(100.0 * c.n / t.total)::INT || '%', ', '
                          ORDER BY c.n DESC) AS reasons
        FROM t JOIN c USING (text_norm)
        GROUP BY ALL ORDER BY t.total DESC""").fetchall()
    for text, n, purity, dist in rows:
        print(f"[{n:>6,} | purity {purity:.2f}] {text}\n      {dist}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
            SELECT text_norm AS text, count(*) AS rows,
                   mode(label_contact_reason) AS top_contact_reason,
                   mode(label_detected_intents) AS top_detected_intents,
                   '' AS route  -- fill by hand: inquiry | dispute | other | human
            FROM d GROUP BY 1 ORDER BY rows DESC
        ) TO '{OUT.as_posix()}' (HEADER)""")
    print(f"\nwrote {OUT} (git-ignored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
