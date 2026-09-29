"""End-to-end tests on the SYNTHETIC fixture (pipeline/fixture.py), never on organizer data.

Run:  python -m pytest -q
"""

from __future__ import annotations

import json
import shutil

import duckdb
import pytest

from pipeline.__main__ import main
from pipeline.common import bucket_for, current_gold, current_silver, sql_bucket
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
    return (current_silver(tmp / "out") / f"{table}.parquet").as_posix()


def gold_dir(tmp):
    return current_gold(tmp / "out")


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
    rows = get_customer_transactions(gold_dir(ws), cid(6), limit=100)
    assert {r["transaction_id"]: r["transaction_status"] for r in rows}["TXN00000904"] == "Reversed"


def test_silver_and_gold_rerun_without_source(ws):
    run(ws)
    shutil.rmtree(ws / "src")                 # silver/gold must only need local bronze
    code, m = run(ws, "--stage", "silver", "gold")
    assert code == 0
    assert m["tables"]["transactions"]["bronze"]["rows"] == 69   # carried from the previous manifest


def test_lookup_enforces_ownership_and_isolation(ws):
    run(ws)
    gold = gold_dir(ws)
    rows = get_customer_transactions(gold, cid(9), limit=100)
    assert all(r["transaction_id"] != "TXN00000907" for r in rows)       # product owned by someone else
    assert get_customer_transactions(gold, "CUS000999", limit=100) == []
    assert get_customer_transactions(gold, cid(3), limit=1000) and \
        len(get_customer_transactions(gold, cid(3), limit=1000)) <= 100  # limit is capped
    assert "is_fraud" not in get_customer_transactions(gold, cid(5))[0]  # never exposed


def test_classifier_split_has_no_customer_or_future_leakage(ws):
    _, m = run(ws)
    path = (gold_dir(ws) / "classifier_dataset.parquet").as_posix()
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
    path = (gold_dir(ws) / "demo_seed_candidates.parquet").as_posix()
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


# --- lineage, concurrency benchmark, source verification --------------------------------

def test_source_objects_are_versioned(ws):
    _, m1 = run(ws)
    inv = json.loads((ws / "reports" / "source_objects.json").read_text(encoding="utf-8"))
    assert len(inv["tables"]["transactions"]["objects"]) == m1["tables"]["transactions"]["bronze"]["source_objects"]
    assert all(o["etag"] and o["bytes"] > 0 for o in inv["tables"]["transactions"]["objects"])
    assert m1["source_fingerprint"] == inv["fingerprint"]
    _, m2 = run(ws)
    assert m2["source_fingerprint"] == m1["source_fingerprint"]           # same inputs, same version
    write_late_batch(ws / "src")
    _, m3 = run(ws)
    assert m3["source_fingerprint"] != m1["source_fingerprint"]           # new object, new version
    assert m3["tables"]["customers"]["bronze"]["source_fingerprint"] == \
        m1["tables"]["customers"]["bronze"]["source_fingerprint"]         # untouched table unchanged
    _, m4 = run(ws, "--stage", "silver", "gold")
    assert m4["source_fingerprint"] == m3["source_fingerprint"]           # carried into partial runs


def test_published_manifest_inventories_every_gold_file(ws):
    run(ws)
    build = gold_dir(ws).parent
    manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    actual = {p.relative_to(build / "gold").as_posix(): p.stat().st_size
              for p in (build / "gold").rglob("*.parquet")}
    assert manifest["gold_files"] == actual
    assert any(p.startswith("transactions_by_customer/bucket=") for p in actual)


def test_source_change_during_headers_fails_before_publication(ws, monkeypatch):
    from pipeline import bronze
    run(ws)
    published = gold_dir(ws)
    original = bronze.read_headers
    changed = False

    def changing_headers(settings, files):
        nonlocal changed
        headers = original(settings, files)
        if not changed:
            changed = True
            with open(files[0], "a", encoding="utf-8") as f:
                f.write("\n")
        return headers

    monkeypatch.setattr(bronze, "read_headers", changing_headers)
    with pytest.raises(RuntimeError, match="source inventory changed"):
        run(ws)
    assert gold_dir(ws) == published
    assert not (ws / "out" / "bronze" / "source_objects.json").exists()
    with pytest.raises(RuntimeError, match="validated bronze inventory missing"):
        run(ws, "--stage", "silver", "gold")


def test_source_added_during_ingestion_fails_before_publication(ws, monkeypatch):
    from pipeline import bronze
    run(ws)
    published = gold_dir(ws)
    original = bronze.read_headers
    changed = False

    def adding_headers(settings, files):
        nonlocal changed
        headers = original(settings, files)
        if not changed:
            changed = True
            write_late_batch(ws / "src")
        return headers

    monkeypatch.setattr(bronze, "read_headers", adding_headers)
    with pytest.raises(RuntimeError, match="source inventory changed"):
        run(ws)
    assert gold_dir(ws) == published


def test_gold_only_uses_published_lineage_not_latest_bronze_report(ws):
    run(ws)
    previous = gold_dir(ws).parent
    old_inventory = json.loads((previous / "source_objects.json").read_text(encoding="utf-8"))
    write_late_batch(ws / "src")
    run(ws, "--stage", "bronze")
    assert json.loads((ws / "reports" / "source_objects.json").read_text(encoding="utf-8"))["fingerprint"] != \
        old_inventory["fingerprint"]
    _, manifest = run(ws, "--stage", "gold")
    new_inventory = json.loads((gold_dir(ws).parent / "source_objects.json").read_text(encoding="utf-8"))
    assert new_inventory == old_inventory
    assert manifest["source_fingerprint"] == old_inventory["fingerprint"]
    rows = get_customer_transactions(gold_dir(ws), cid(6), limit=100)
    assert "TXN00000951" not in _customer_ids(rows)


def test_gold_only_migrates_legacy_inventory_without_claiming_read_validation(ws):
    run(ws)
    build = gold_dir(ws).parent
    lineage = build / "source_objects.json"
    inventory = json.loads(lineage.read_text(encoding="utf-8"))
    inventory.pop("source_validation")
    lineage.write_text(json.dumps(inventory), encoding="utf-8")
    snapshot_path = build / "snapshot.json"
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot.pop("gold_files")
    snapshot.pop("source_validation")
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    (ws / "out" / "bronze" / "source_objects.json").unlink()
    shutil.rmtree(ws / "src")
    code, _ = run(ws, "--stage", "gold", "--tables", "customers", "products", "transactions")
    migrated = json.loads((gold_dir(ws).parent / "snapshot.json").read_text(encoding="utf-8"))
    assert code == 0 and migrated["gold_files"]
    assert migrated["source_validation"] == "legacy_inventory"
    assert migrated["source_fingerprint"] == snapshot["source_fingerprint"]


def test_publications_never_delete_a_pinned_reader_snapshot(ws):
    from pipeline.common import publish
    run(ws)
    pinned = gold_dir(ws)
    before = _customer_ids(get_customer_transactions(pinned, cid(3), limit=100))
    for i in range(6):
        build_id = f"20990101T00000{i}Z-test"
        (ws / "out" / "builds" / build_id).mkdir()
        publish(ws / "out", build_id)
    assert pinned.is_dir()
    assert _customer_ids(get_customer_transactions(pinned, cid(3), limit=100)) == before


def test_stages_and_benchmarks_close_owned_connections(ws, monkeypatch):
    from pipeline import bronze, gold, lookup, silver
    owned = []
    original = duckdb.connect

    class TrackedConnection:
        def __init__(self, real):
            self.real, self.closed = real, False
            owned.append(self)

        def __getattr__(self, name):
            return getattr(self.real, name)

        def close(self):
            self.real.close()
            self.closed = True

    def tracked_connect(settings):
        from pipeline.common import connect
        return TrackedConnection(connect(settings))

    for stage in (bronze, silver, gold):
        monkeypatch.setattr(stage, "connect", tracked_connect)
    run(ws)
    assert len(owned) == 3 and all(c.closed for c in owned)
    monkeypatch.setattr(lookup.duckdb, "connect", lambda: TrackedConnection(original()))
    lookup.bench(gold_dir(ws), samples=2)
    lookup.bench_concurrent(gold_dir(ws), levels=(2,), requests=4)
    assert len(owned) == 5 and all(c.closed for c in owned)


def test_failed_stage_closes_owned_connection(ws, monkeypatch):
    from pipeline import bronze
    original = bronze.connect
    owned = []

    class TrackedConnection:
        def __init__(self, real):
            self.real, self.closed = real, False
            owned.append(self)

        def __getattr__(self, name):
            return getattr(self.real, name)

        def close(self):
            self.real.close()
            self.closed = True

    monkeypatch.setattr(bronze, "connect", lambda settings: TrackedConnection(original(settings)))
    monkeypatch.setattr(bronze, "read_headers", lambda *args: (_ for _ in ()).throw(RuntimeError("test")))
    with pytest.raises(RuntimeError, match="test"):
        run(ws)
    assert len(owned) == 1 and owned[0].closed


@pytest.mark.parametrize("operation", ["listing", "headers"])
def test_s3_helpers_close_clients_and_bodies_on_failure(tmp_path, monkeypatch, operation):
    from pipeline import bronze
    from pipeline.common import Settings
    settings = Settings("s3://test/data", tmp_path, tmp_path, [])

    class Body:
        closed = False

        def read(self):
            raise RuntimeError("read failed")

        def close(self):
            self.closed = True

    class Client:
        closed = False
        body = Body()

        def get_object(self, **kwargs):
            return {"Body": self.body}

        def get_paginator(self, *args):
            return self

        def paginate(self, **kwargs):
            raise RuntimeError("listing failed")

        def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr(bronze, "s3_client", lambda *args: client)
    with pytest.raises(RuntimeError, match="failed"):
        if operation == "listing":
            bronze.list_objects(settings)
        else:
            bronze.read_headers(settings, ["s3://test/data/customers.csv"])
    assert client.closed
    if operation == "headers":
        assert client.body.closed


def test_concurrent_bench_reports_every_level(ws):
    from pipeline.lookup import bench_concurrent
    run(ws)
    r = bench_concurrent(gold_dir(ws), levels=(1, 8), requests=40)
    assert [lv["concurrency"] for lv in r["levels"]] == [1, 8]
    assert all(lv["errors"] == 0 and lv["ok"] == 40 and lv["p95_ms"] is not None for lv in r["levels"])


def test_verify_against_source(ws):
    from pipeline.verify import verify_transaction_in_source
    run(ws)
    src, gold = str(ws / "src"), gold_dir(ws)
    ok = verify_transaction_in_source(src, "TXN00000001", cid(1), "2026-06-01", gold_dir=gold)
    assert ok["status"] == "verified" and ok["transaction"]["transaction_id"] == "TXN00000001"
    assert "is_fraud" not in ok["transaction"] and "customer_id" not in ok["transaction"]

    # Someone else's transaction is indistinguishable from a missing one.
    other = verify_transaction_in_source(src, "TXN00000001", cid(2), "2026-06-01", gold_dir=gold)
    missing = verify_transaction_in_source(src, "TXN99999999", cid(2), "2026-06-01", gold_dir=gold)
    assert other["status"] == missing["status"] == "not_found"
    assert other["transaction"] is None and other["audit"]["reason"] == "owner_mismatch"
    assert set(other) == set(missing)

    # Product owned by another customer (TXN00000907) is refused via gold's ownership flag.
    assert verify_transaction_in_source(src, "TXN00000907", cid(9), "2026-06-01",
                                        gold_dir=gold)["status"] == "not_found"

    # A correction lands in a later partition after the last build: source wins, flagged as changed.
    write_late_batch(ws / "src")
    ch = verify_transaction_in_source(src, "TXN00000904", cid(6), "2026-06-01", gold_dir=gold,
                                      refresh_listing=True)
    assert ch["status"] == "changed"
    assert ch["transaction"]["transaction_status"] == "Reversed"
    assert ch["differences"]["transaction_status"] == ["Pending", "Reversed"]
    assert ch["source_key"].startswith("transactions/year=2026/month=06/day=04/")
    # A late row that gold has never seen is found by searching later partitions.
    late = verify_transaction_in_source(src, "TXN00000950", cid(6), "2026-06-02", gold_dir=gold,
                                        refresh_listing=True)
    assert late["status"] == "changed" and late["transaction"]["transaction_id"] == "TXN00000950"


# --- regressions from PR #1 review (Mario) ------------------------------------------------

def _customer_ids(rows):
    return sorted(r["transaction_id"] for r in rows)


def test_review_p1_shared_connection_never_leaks_results(ws):
    """Repro: A-execute, B-execute, A-fetch on a shared connection gave A the rows of B."""
    import threading
    run(ws)
    gold = gold_dir(ws)
    expected = {c: _customer_ids(get_customer_transactions(gold, c, limit=100))
                for c in (cid(0), cid(1), cid(3), cid(6))}
    assert expected[cid(0)] != expected[cid(1)]

    # 1) Deterministic: the shared connection's own result slot is never used.
    class NoDirectExecute:
        def __init__(self, real):
            self.real = real
        def execute(self, *a, **k):
            raise AssertionError("lookup must not execute on the shared connection")
        def cursor(self):
            return self.real.cursor()
    shared = NoDirectExecute(duckdb.connect())
    assert _customer_ids(get_customer_transactions(gold, cid(0), limit=100, con=shared)) == expected[cid(0)]

    # 2) The exact interleaving from the review, on a raw connection, shows the hazard ...
    raw = duckdb.connect()
    path0 = (gold / "transactions_by_customer" / f"bucket={bucket_for(cid(0))}").as_posix()
    path1 = (gold / "transactions_by_customer" / f"bucket={bucket_for(cid(1))}").as_posix()
    a = raw.execute(f"SELECT transaction_id FROM read_parquet('{path0}/*.parquet') WHERE customer_id=?", [cid(0)])
    raw.execute(f"SELECT transaction_id FROM read_parquet('{path1}/*.parquet') WHERE customer_id=?", [cid(1)])
    assert sorted(r[0] for r in a.fetchall()) == expected[cid(1)]   # A got B's rows: the bug
    # ... while per-call cursors on that same connection stay isolated.
    assert _customer_ids(get_customer_transactions(gold, cid(0), limit=100, con=raw)) == expected[cid(0)]

    # 3) Stress: many threads, one shared connection, every result must belong to its caller.
    errors, shared_con = [], duckdb.connect()
    def worker(n):
        for i in range(60):
            c = list(expected)[(n + i) % len(expected)]
            got = _customer_ids(get_customer_transactions(gold, c, limit=100, con=shared_con))
            if got != expected[c]:
                errors.append((c, got))
    threads = [threading.Thread(target=worker, args=(n,)) for n in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert errors == []


def _corrupt_first_transactions_file(ws):
    p = sorted((ws / "src" / "transactions").rglob("*.csv"))[0]
    lines = p.read_text(encoding="utf-8").splitlines()
    idx = lines[0].split(",").index("amount")
    p.write_text("\n".join([lines[0]] + [",".join(v if i != idx else "oops" for i, v in enumerate(l.split(",")))
                                         for l in lines[1:]]) + "\n", encoding="utf-8")


def test_review_p1_failed_build_keeps_last_good_snapshot(ws):
    """Repro: a rebuild that exits 2 replaced CUS000003's 5 served transactions with 1."""
    code, _ = run(ws)
    assert code == 0
    good_build = current_gold(ws / "out")
    before = _customer_ids(get_customer_transactions(good_build, cid(3), limit=100))
    assert len(before) == 5

    _corrupt_first_transactions_file(ws)
    code, m = run(ws)
    assert code == 2 and m["contract_failures"] and m["published"] is False
    assert current_gold(ws / "out") == good_build                       # pointer unchanged
    assert _customer_ids(get_customer_transactions(current_gold(ws / "out"), cid(3), limit=100)) == before
    # Gold was not even built for the failed run.
    failed = sorted((ws / "out" / "builds").iterdir())[-1]
    assert failed != good_build.parent and not (failed / "gold").exists()


def test_review_p1_reads_during_rebuild_see_a_complete_snapshot(ws, monkeypatch):
    import pipeline.gold as gold_mod
    run(ws)
    before_build = current_gold(ws / "out")
    before = _customer_ids(get_customer_transactions(before_build, cid(6), limit=100))
    write_late_batch(ws / "src")                                       # rebuild will change cid(6)
    seen = {}
    real_run = gold_mod.run

    def spy(settings, run_id, stats):
        real_run(settings, run_id, stats)
        # New gold is fully written but not yet published: readers still get the old snapshot,
        # and the old snapshot's files were never touched.
        live = current_gold(ws / "out")
        seen["pointer"] = live
        seen["rows"] = _customer_ids(get_customer_transactions(live, cid(6), limit=100))
    monkeypatch.setattr(gold_mod, "run", spy)
    code, _ = run(ws)
    assert code == 0
    assert seen["pointer"] == before_build and seen["rows"] == before
    after = _customer_ids(get_customer_transactions(current_gold(ws / "out"), cid(6), limit=100))
    assert current_gold(ws / "out") != before_build and "TXN00000951" in after and "TXN00000951" not in before
    # The previous snapshot is still intact for any reader that resolved it earlier.
    assert _customer_ids(get_customer_transactions(before_build, cid(6), limit=100)) == before


def test_review_p1_free_text_never_reaches_reports(ws):
    """Repro: case variants of a transcript sentence were copied verbatim into both reports."""
    import csv
    marker = "SYNTH-EMAIL-7731@example.test"
    for table, col, id_col in (("call_transcripts", "customer_text", "transcript_id"),
                               ("complaints", "description", "complaint_id")):
        files = sorted((ws / "src" / table).rglob("*.csv"))
        with files[0].open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
            header = list(rows[0])
        rows[0][col] = f"mi correo es {marker} por favor"
        rows[1][col] = f"MI CORREO ES {marker.upper()} POR FAVOR"
        with files[0].open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            w.writerows(rows)
    _, m = run(ws)
    reports = "".join(p.read_text(encoding="utf-8") for p in (ws / "reports").iterdir() if p.is_file())
    assert marker.lower() not in reports.lower()
    assert "SYNTH-EMAIL" not in reports.upper()
    for rid in ("TRN000000", "CMP000000"):                               # no record identifiers either
        assert rid not in reports
    # ...but the collision is still counted, and allow-listed categoricals still show values.
    assert m["tables"]["call_transcripts"]["silver"]["inconsistent_spellings_counts"]["customer_text"][
        "values_published"] is False
    assert "customer_text" not in m["tables"]["call_transcripts"]["silver"]["inconsistent_spellings"]
    assert "México" in reports


def test_review_p2_orphan_customer_is_never_served(ws):
    """Repro: txn with customer CUS999999 + product PRD999999 (both orphan) was served."""
    from pipeline.common import load_contracts
    from pipeline.fixture import _part, _row, _write
    c = load_contracts()
    _write(_part(ws / "src", "transactions", "2026-06-03"), c, "transactions", [
        _row(c, "transactions", transaction_id="TXN00000999", customer_id="CUS999999",
             product_id="PRD999999", transaction_date="2026-06-03 10:00:00", process_date="2026-06-03",
             amount="10.00", transaction_status="Approved", is_fraud="False")])
    code, m = run(ws)
    assert code == 0
    assert get_customer_transactions(gold_dir(ws), "CUS999999", limit=100) == []
    t = m["tables"]["transactions"]["silver"]["orphans"]
    assert t["customer_id"]["missing_in_parent"] == 1
    assert m["gold"]["transactions_by_customer"]["ownership_valid_rows"] == \
        m["gold"]["transactions_by_customer"]["rows"] - 2          # 907 (other owner) + 999 (orphan)
