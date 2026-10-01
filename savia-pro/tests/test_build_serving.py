from __future__ import annotations

import duckdb
import pytest

from conftest import CUSTOMER_A, builder


def test_build_preserves_selected_rows_and_drops_private_columns(serving):
    con = duckdb.connect(str(serving), read_only=True)
    try:
        assert con.execute("select count(*) from transactions").fetchone()[0] == 7
        info = dict(con.execute("select key, value from build_info").fetchall())
        assert info["selected_source_rows"] == info["served_rows"] == "7"
        columns = {row[1] for row in con.execute("pragma table_info('transactions')").fetchall()}
        assert not columns.intersection(builder.FORBIDDEN)
        assert "ownership_valid" not in columns
        assert "bucket" not in columns
        with pytest.raises(duckdb.InvalidInputException):
            con.execute("delete from transactions")
    finally:
        con.close()


@pytest.mark.parametrize("failure", ["missing-product", "foreign-product", "duplicate-product", "missing-customer"])
def test_failed_rebuild_keeps_previous_artifact(synthetic_lake, tmp_path, failure):
    lake, build, source, write_source = synthetic_lake
    out = tmp_path / "serving.duckdb"
    builder.build_serving(lake, build, out)
    before = out.read_bytes()
    if failure == "missing-product":
        source.execute("update transactions set product_id = 'ABSENT' where transaction_id = 'TX-BELOW-0'")
    elif failure == "foreign-product":
        source.execute("update transactions set product_id = 'PRODUCT-B' where transaction_id = 'TX-BELOW-0'")
    elif failure == "duplicate-product":
        source.execute("insert into products select * from products where product_id = 'PRODUCT-A'")
    else:
        source.execute("delete from customers where customer_id = ?", [CUSTOMER_A])
    write_source()
    with pytest.raises((ValueError, SystemExit)):
        builder.build_serving(lake, build, out)
    assert out.read_bytes() == before
    assert not list(out.parent.glob(f".{out.name}.*.building.duckdb*"))


def test_failed_reopen_verification_cannot_publish(synthetic_lake, tmp_path, monkeypatch):
    lake, build, _, _ = synthetic_lake
    out = tmp_path / "serving.duckdb"
    builder.build_serving(lake, build, out)
    before = out.read_bytes()

    def refuse(*_):
        raise ValueError("synthetic verification refusal")

    monkeypatch.setattr(builder, "_verify_serving", refuse)
    with pytest.raises(ValueError, match="verification refusal"):
        builder.build_serving(lake, build, out)
    assert out.read_bytes() == before
    assert not list(out.parent.glob(f".{out.name}.*.building.duckdb*"))


def test_similar_charge_window_uses_exact_elapsed_time(serving):
    con = duckdb.connect(str(serving), read_only=True)
    try:
        matches = con.execute("select transaction_id, hours_apart from similar_charges order by transaction_id").fetchall()
        assert [row[0] for row in matches] == ["TX-BELOW-1", "TX-EXACT-1"]
        assert matches[0][1] == pytest.approx(71 + 59 / 60)
        assert matches[1][1] == 72
        assert con.execute("select value from snapshot_stats where metric='similar_charge_pairs_72h'").fetchone()[0] == 2
    finally:
        con.close()
