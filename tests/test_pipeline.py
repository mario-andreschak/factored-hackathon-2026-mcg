"""End-to-end tests on the SYNTHETIC fixture (pipeline/fixture.py), never on organizer data.

Run:  python -m pytest -q
"""

from __future__ import annotations

import json
import shutil

import duckdb
import pytest

from pipeline.__main__ import main
from pipeline.common import bucket_for, sql_bucket
from pipeline.fixture import cid, write_base, write_late_batch
from pipeline.lookup import get_customer_transactions


def run(tmp, *extra):
    code = main(["run", "--source", str(tmp / "src"), "--out", str(tmp / "out"),
                 "--reports", str(tmp / "reports"), *extra])
    manifest = json.loads((tmp / "reports" / "manifest.json").read_text(encoding="utf-8"))
    return code, manifest


def q(sql, *params):
    return duckdb.sql(sql, params=list(params) if params else None).fetchall()


def silver(tmp, table):
    return (tmp / "out" / "silver" / f"{table}.parquet").as_posix()


@pytest.fixture()
def ws(tmp_path):
    write_base(tmp_path / "src")
    return tmp_path


def test_every_raw_row_is_accounted_for(ws):
    code, m = run(ws)
    assert code == 0
    for table, s in m["tables"].items():
        sv = s["silver"]
        assert sv["reconciles"], table
        assert sv["raw_rows"] == s["bronze"]["rows"], table


def test_quarantine_dedup_and_orphans(ws):
    _, m = run(ws)
    t = m["tables"]
    assert t["customers"]["silver"]["duplicate_rows_removed"] == 2
    assert t["customers"]["silver"]["pks_with_conflicting_content"] == 1
    assert q(f"SELECT segment FROM '{silver(ws, 'customers')}' WHERE customer_id = ?", cid(1)) == [("Premium",)]

    tx = t["transactions"]["silver"]
    assert tx["raw_rows"] == 69
    assert tx["quarantined_rows"] == 2
    assert tx["reject_reasons"] == {"cast_failed:amount": 1, "null:customer_id": 1}
    assert tx["duplicate_rows_removed"] == 1
    assert tx["rows"] == 66
    assert tx["late_arrivals"] == 1          # the re-delivered row lives in a later partition

    assert t["products"]["silver"]["orphans"]["customer_id"]["missing_in_parent"] == 1
    g = m["gold"]["transactions_by_customer"]
    assert (g["rows"], g["ownership_valid_rows"]) == (66, 65)


def test_rerun_is_idempotent(ws):
    run(ws)
    first = {t: q(f"SELECT md5(string_agg(_row_hash, ',' ORDER BY _row_hash)) FROM '{silver(ws, t)}'")
             for t in ("customers", "transactions")}
    run(ws)
    second = {t: q(f"SELECT md5(string_agg(_row_hash, ',' ORDER BY _row_hash)) FROM '{silver(ws, t)}'")
              for t in ("customers", "transactions")}
    assert first == second


def test_late_batch_upserts_and_is_flagged(ws):
    run(ws)
    before = q(f"SELECT transaction_status FROM '{silver(ws, 'transactions')}' WHERE transaction_id='TXN00000904'")
    assert before == [("Pending",)]

    write_late_batch(ws / "src")
    _, m = run(ws)
    tx = m["tables"]["transactions"]["silver"]
    assert tx["raw_rows"] == 72
    assert tx["rows"] == 68                   # +2 new ids; the correction replaces, not appends
    assert tx["pks_with_conflicting_content"] == 1
    assert tx["late_arrivals"] == 3           # re-delivery + correction + late row
    after = q(f"""SELECT transaction_status, _late_arrival, _partition_date::VARCHAR
                  FROM '{silver(ws, 'transactions')}' WHERE transaction_id='TXN00000904'""")
    assert after == [("Reversed", True, "2026-06-04")]
    # Gold serves the corrected state.
    rows = get_customer_transactions(ws / "out" / "gold", cid(6), limit=100)
    assert {r["transaction_id"]: r["transaction_status"] for r in rows}["TXN00000904"] == "Reversed"


def test_silver_and_gold_rerun_without_source(ws):
    run(ws)
    shutil.rmtree(ws / "src")                 # silver/gold must only need local bronze
    code, m = run(ws, "--stage", "silver", "gold")
    assert code == 0
    assert m["tables"]["transactions"]["bronze"]["rows"] == 69   # carried from the previous manifest


def test_lookup_enforces_ownership_and_isolation(ws):
    run(ws)
    gold = ws / "out" / "gold"
    rows = get_customer_transactions(gold, cid(9), limit=100)
    assert all(r["transaction_id"] != "TXN00000907" for r in rows)       # product owned by someone else
    assert get_customer_transactions(gold, "CUS000999", limit=100) == []
    assert get_customer_transactions(gold, cid(3), limit=1000) and \
        len(get_customer_transactions(gold, cid(3), limit=1000)) <= 100  # limit is capped
    assert "is_fraud" not in get_customer_transactions(gold, cid(5))[0]  # never exposed


def test_classifier_split_has_no_customer_or_future_leakage(ws):
    _, m = run(ws)
    path = (ws / "out" / "gold" / "classifier_dataset.parquet").as_posix()
    overlap = q(f"""SELECT count(*) FROM (SELECT DISTINCT customer_id FROM '{path}' WHERE split='train')
                    JOIN (SELECT DISTINCT customer_id FROM '{path}' WHERE split IN ('test','val')) USING (customer_id)""")
    assert overlap == [(0,)]
    assert q(f"SELECT count(*) FROM '{path}' WHERE split='train' AND interaction_date >= DATE '2026-03-17'") == [(0,)]
    assert q(f"SELECT count(*) FROM '{path}' WHERE split='test' AND interaction_date < DATE '2026-03-17'") == [(0,)]
    assert sum(m["gold"]["classifier_dataset"]["splits"].values()) == 60


def test_demo_candidates_cover_each_scenario(ws):
    _, m = run(ws)
    d = m["gold"]["demo_seed_candidates"]["customers_eligible"]
    for scenario in ("normal", "reversed", "pending", "fraud_flagged", "near_duplicate"):
        assert d[scenario] >= 1, scenario
    path = (ws / "out" / "gold" / "demo_seed_candidates.parquet").as_posix()
    assert q(f"""SELECT n_near_duplicate_charges FROM '{path}'
                 WHERE scenario = 'near_duplicate' AND customer_id = ?""", cid(3)) == [(1,)]
    # A fraud-flagged customer must never be offered as a "normal" happy-path customer.
    assert q(f"SELECT count(*) FROM '{path}' WHERE scenario = 'normal' AND n_fraud_flagged > 0") == [(0,)]


def test_cross_customer_references_and_spelling_drift(ws):
    _, m = run(ws)
    t = m["tables"]
    # TXN00000907 uses a product owned by another customer; complaint 0 references customer 1's product.
    assert t["transactions"]["silver"]["orphans"]["product_id"]["owned_by_other_customer"] == 1
    assert t["complaints"]["silver"]["orphans"]["affected_product_id"]["owned_by_other_customer"] == 1
    spell = t["transactions"]["silver"]["inconsistent_spellings"]["transaction_country"]
    assert {"México", "Mexico"} <= set(spell[0])
    report = (ws / "reports" / "quality_report.md").read_text(encoding="utf-8")
    assert "same value, different spelling" in report and "owned by another customer" in report


def test_contract_failure_exits_non_zero(ws):
    # Corrupt most transaction amounts -> reject rate above max_reject_rate.
    p = next((ws / "src" / "transactions").rglob("*.csv"))
    text = p.read_text(encoding="utf-8").splitlines()
    header = text[0].split(",")
    idx = header.index("amount")
    bad = [text[0]] + [",".join(v if i != idx else "oops" for i, v in enumerate(line.split(",")))
                       for line in text[1:]]
    p.write_text("\n".join(bad) + "\n", encoding="utf-8")
    code, m = run(ws)
    assert code == 2
    assert m["contract_failures"]


def test_bucket_hash_matches_between_python_and_sql():
    ids = [cid(i) for i in range(200)]
    got = q(f"SELECT x, {sql_bucket('x', 128)} FROM unnest(?::VARCHAR[]) t(x)", ids)
    assert all(b == bucket_for(x) for x, b in got)


def test_reports_contain_no_bucket_or_secrets(ws):
    run(ws)
    text = (ws / "reports" / "quality_report.md").read_text(encoding="utf-8") + \
        (ws / "reports" / "manifest.json").read_text(encoding="utf-8")
    assert "SecretAccessKey" not in text and "AccessKeyID" not in text


def test_schema_evolution_and_quoted_text(ws):
    import csv
    from pipeline.common import load_contracts
    from pipeline.fixture import _part, _row
    c = load_contracts()
    cols = list(c["call_transcripts"]["columns"]) + ["sentiment_v2"]       # new column appears
    row = _row(c, "call_transcripts", transcript_id="TRN99999999", interaction_id="INT00000000",
               customer_id=cid(0), process_date="2026-06-05", detected_language="es",
               customer_text='me cobraron "dos veces", en Oxxo\ny luego otra vez')
    row["sentiment_v2"] = "neg"
    p = _part(ws / "src", "call_transcripts", "2026-06-05")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow(row)
    _, m = run(ws)
    t = m["tables"]["call_transcripts"]
    assert t["bronze"]["schema_variants"] == 2
    assert t["silver"]["source_columns_not_in_contract"] == ["sentiment_v2"]
    assert t["silver"]["reconciles"] and t["silver"]["rows"] == 61
    got = q(f"SELECT customer_text FROM '{silver(ws, 'call_transcripts')}' WHERE transcript_id='TRN99999999'")
    assert got == [('me cobraron "dos veces", en Oxxo\ny luego otra vez',)]
