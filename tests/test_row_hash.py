"""Synthetic regressions for unambiguous typed content hashes and deduplication."""

from __future__ import annotations

import re

import duckdb
import pytest

from pipeline import bronze, silver
from pipeline.common import Settings, load_contracts
from pipeline.fixture import _row, _write


def customer(customer_id, **values):
    return _row(load_contracts(), "customers", customer_id=customer_id,
                last_updated="2026-06-01 00:00:00", **values)


def build(tmp_path, rows, build_id):
    source = tmp_path / "source"
    _write(source / "customers.csv", load_contracts(), "customers", rows)
    settings = Settings(source=str(source), out_dir=tmp_path / "data",
                        report_dir=tmp_path / "reports", tables=["customers"], build_id=build_id)
    stats = {}
    bronze.run(settings, f"ingestion-{build_id}", stats)
    silver.run(settings, build_id, stats)
    with duckdb.connect() as con:
        records = con.execute("""
            SELECT customer_id, city, state, detected_accent, _row_hash, _run_id
            FROM read_parquet(?) ORDER BY customer_id
        """, [str(settings.silver / "customers.parquet")]).fetchall()
    return stats["customers"]["silver"], records


@pytest.mark.parametrize("versions", [
    [{"city": "Alpha|Beta", "state": "Gamma"},
     {"city": "Alpha", "state": "Beta|Gamma"}],
    [{"detected_accent": None}, {"detected_accent": "∅"}],
], ids=["embedded-separator", "literal-null-sentinel"])
def test_distinct_versions_are_conflicts_even_when_flat_strings_alias(tmp_path, versions):
    rows = [customer("CUS_CONFLICT", **values) for values in versions]
    exact = customer("CUS_EXACT")
    stats, records = build(tmp_path, [*rows, exact, dict(exact)], "first")

    assert stats["raw_rows"] == 4
    assert stats["rows"] == 2
    assert stats["quarantined_rows"] == 0
    assert stats["duplicate_rows_removed"] == 2
    assert stats["pks_with_multiple_versions"] == 2
    assert stats["pks_with_conflicting_content"] == 1
    assert stats["reconciles"]
    assert len(records) == 2
    assert all(re.fullmatch(r"[0-9a-f]{32}", row[4]) for row in records)


def test_equivalent_typed_content_and_dropped_pii_are_exact_redeliveries(tmp_path):
    first = customer("CUS_EXACT", registration_date="2025-01-01", accepts_marketing="False",
                     first_name="Synthetic first version")
    second = {**first, "registration_date": "2025-01-01 00:00:00", "accepts_marketing": "false",
              "first_name": "Synthetic second version"}
    stats, _ = build(tmp_path, [first, second], "first")

    assert stats["rows"] == 1
    assert stats["duplicate_rows_removed"] == 1
    assert stats["pks_with_multiple_versions"] == 1
    assert stats["pks_with_conflicting_content"] == 0
    assert stats["quarantined_rows"] == 0


def test_reordered_rerun_keeps_hashes_and_dedup_winners_stable(tmp_path):
    rows = [
        customer("CUS_DELIMITER", city="Alpha|Beta", state="Gamma"),
        customer("CUS_DELIMITER", city="Alpha", state="Beta|Gamma"),
        customer("CUS_NULL", detected_accent=None),
        customer("CUS_NULL", detected_accent="∅"),
        customer("CUS_ESCAPED", city='A "quoted" city\\district|∅', state="Line\nbreak"),
    ]
    first_stats, first = build(tmp_path, rows, "first")
    second_stats, second = build(tmp_path, list(reversed(rows)), "second")

    assert first_stats["pks_with_conflicting_content"] == second_stats["pks_with_conflicting_content"] == 2
    assert [row[:-1] for row in first] == [row[:-1] for row in second]
    assert {row[-1] for row in first} == {"ingestion-first"}
    assert {row[-1] for row in second} == {"ingestion-second"}
