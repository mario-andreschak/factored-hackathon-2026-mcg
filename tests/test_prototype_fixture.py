"""The generated prototype must be clean, owned, reproducible and visibly synthetic."""

from __future__ import annotations

import hashlib
import json

import duckdb
import pytest

from pipeline.__main__ import main as pipeline_main
from pipeline.common import current_build, sql_path
from pipeline.prototype_fixture import (MARKER, PERSONAS, PUBLISHED_MARKER, main as prototype_main,
                                        stamp_published_snapshot, write_prototype_source)
from pipeline.prepare_invite_preview import prepare


def test_prototype_source_is_deterministic_and_never_overwrites(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    assert prototype_main([str(first)]) == 0
    write_prototype_source(second)
    files = {path.relative_to(first).as_posix(): path.read_bytes()
             for path in first.rglob("*") if path.is_file()}
    assert files == {path.relative_to(second).as_posix(): path.read_bytes()
                     for path in second.rglob("*") if path.is_file()}
    assert json.loads((first / MARKER).read_text(encoding="utf-8"))["origin"] == "team-generated-prototype"
    assert len(list((first / "transactions").rglob("*.csv"))) > 3
    with pytest.raises(FileExistsError, match="empty directory"):
        write_prototype_source(first)


def test_prototype_publishes_clean_owned_gold_and_binds_provenance(tmp_path):
    source, snapshot, reports = (tmp_path / name for name in ("source", "snapshot", "reports"))
    write_prototype_source(source)
    assert pipeline_main(["run", "--source", str(source), "--out", str(snapshot),
                          "--reports", str(reports)]) == 0
    build = current_build(snapshot)
    report = json.loads((reports / "manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    assert report["published"] is True
    assert manifest["source_validation"] == "unchanged_inventory_after_ingestion"
    for table, stats in report["tables"].items():
        assert stats["silver"]["quarantined_rows"] == 0, table
        assert stats["silver"]["duplicate_rows_removed"] == 0, table
    assert report["gold"]["transactions_by_customer"]["rows"] == 63
    assert report["gold"]["transactions_by_customer"]["ownership_valid_rows"] == 63

    with duckdb.connect() as con:
        rows = con.execute(f"""SELECT c.customer_id, c.country, count(t.transaction_id),
                count(DISTINCT strftime(t.transaction_date, '%Y-%m')),
                count(*) FILTER (WHERE t.transaction_status='Pending'),
                count(*) FILTER (WHERE t.transaction_status='Reversed')
            FROM read_parquet('{sql_path(build / 'silver' / 'customers.parquet')}') c
            JOIN read_parquet('{sql_path(build / 'gold' / 'transactions_by_customer')}/**/*.parquet') t
              ON t.customer_id=c.customer_id
            GROUP BY 1,2 ORDER BY 1""").fetchall()
        assert rows == sorted((p.customer_id, p.country, 21, 4, 1, 1) for p in PERSONAS)
        for person in PERSONAS:
            candidate = con.execute(f"""SELECT t.customer_id, t.product_id, t.amount::VARCHAR,
                        t.currency, t.transaction_type, t.transaction_status, t.merchant_name,
                        t.is_fraud, t.ownership_valid
                FROM read_parquet('{sql_path(build / 'gold' / 'transactions_by_customer')}/**/*.parquet') t
                WHERE t.transaction_id=?""", [person.candidate_id]).fetchone()
            assert candidate == (person.customer_id, person.card_id, person.candidate_amount,
                                 person.currency, "Purchase", "Approved",
                                 person.candidate_merchant, True, True)
        languages = con.execute(f"""SELECT customer_id, detected_language, customer_text
            FROM read_parquet('{sql_path(build / 'silver' / 'call_transcripts.parquet')}')
            ORDER BY customer_id""").fetchall()
        assert [(customer, language) for customer, language, _ in languages] == sorted(
            (p.customer_id, p.language) for p in PERSONAS)
        assert any(language == "pt" and "Não reconheço" in text for _, language, text in languages)

    assert prototype_main(["stamp", str(source), str(snapshot)]) == 0
    provenance_path = build / PUBLISHED_MARKER
    assert provenance_path == build / PUBLISHED_MARKER
    assert json.loads(provenance_path.read_text(encoding="utf-8")) == {
        "kind": "team_synthetic_fixture", "build_id": build.name,
        "source_fingerprint": manifest["source_fingerprint"]}
    config_path, codes_path = prepare(source, snapshot, tmp_path / "private", "http://localhost:43801")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    codes = json.loads(codes_path.read_text(encoding="utf-8"))
    assert config["auth_mode"] == "invite" and not config["chat"]
    assert config["expected_snapshot"] == json.loads(provenance_path.read_text(encoding="utf-8"))
    assert config["profiles"]["colombia"]["customer_id"] == "SYNTH-CO-001"
    assert len(config["invites"]) == len(codes) == 3
    assert {hashlib.sha256(code.encode()).hexdigest(): profile
            for profile, code in codes.items()} == config["invites"]
    assert all(len(code) >= 32 for code in codes.values())
    assert all(code not in config_path.read_text(encoding="utf-8") for code in codes.values())
    with pytest.raises(FileExistsError, match="already exist"):
        prepare(source, snapshot, tmp_path / "private", "http://localhost:43801")
    assert stamp_published_snapshot(source, snapshot) == provenance_path
    customer_file = source / "customers.csv"
    customer_file.write_text(customer_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="differs from the published inventory"):
        stamp_published_snapshot(source, snapshot)


def test_altered_generated_source_cannot_be_stamped_as_canonical(tmp_path):
    source, snapshot, reports = (tmp_path / name for name in ("source", "snapshot", "reports"))
    write_prototype_source(source)
    candidate_day = source / "transactions" / "year=2026" / "month=09" / "day=24" / "part-0000.csv"
    candidate_day.write_text(
        candidate_day.read_text(encoding="utf-8").replace("Aurora Digital", "Other Merchant"),
        encoding="utf-8")
    assert pipeline_main(["run", "--source", str(source), "--out", str(snapshot),
                          "--reports", str(reports)]) == 0
    with pytest.raises(ValueError, match="not the canonical generated prototype"):
        stamp_published_snapshot(source, snapshot)
    assert not (current_build(snapshot) / PUBLISHED_MARKER).exists()
