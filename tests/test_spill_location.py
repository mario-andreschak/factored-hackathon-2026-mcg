"""Synthetic checks that DuckDB buffers stay private and outside immutable builds."""

from contextlib import closing
from pathlib import Path

import pytest

from pipeline import common, verify
from pipeline.fixture import cid, write_base
from scripts import check_dataset as health


def spill_path(con):
    return Path(con.execute("SELECT current_setting('temp_directory')").fetchone()[0]).resolve()


def test_coexisting_connections_use_distinct_private_spill_directories(tmp_path, monkeypatch):
    cwd = tmp_path / "unrelated-cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    settings = common.Settings(source="", out_dir=tmp_path / "private-data", report_dir=tmp_path,
                               tables=[])
    with closing(common.connect(settings)) as first, closing(common.connect(settings)) as second:
        paths = [spill_path(first), spill_path(second)]
        assert paths[0] != paths[1]
        assert all(path.parent == settings.out_dir.resolve() / ".duckdb-spill" for path in paths)
        assert all(path.is_dir() for path in paths)
    assert not (cwd / ".tmp").exists()
    assert not (cwd / ".duckdb-spill").exists()


def test_health_spill_setup_uses_data_root_and_preserves_immutable_build(tmp_path, monkeypatch):
    data = tmp_path / "private-data"
    build = data / "builds" / "synthetic-build"
    build.mkdir(parents=True)
    configured = []
    original = health.configure_spill_directory

    def observe(con, root):
        original(con, root)
        configured.append(spill_path(con))

    monkeypatch.setattr(health, "configure_spill_directory", observe)
    # The missing synthetic silver fails after connection configuration; health must
    # still place temporary buffers beside builds, never mutate the immutable build.
    with pytest.raises(health.HealthFailure, match="silver_file_missing"):
        health._row_checks(build, [], {"customers"}, {}, {"errors": [], "warnings": []})
    assert len(configured) == 1
    assert configured[0].parent == data.resolve() / ".duckdb-spill"
    assert list(build.iterdir()) == []


@pytest.mark.parametrize("published_layout", [True, False], ids=["published-build", "standalone-gold"])
def test_offline_verification_uses_private_gold_data_root(tmp_path, monkeypatch, published_layout):
    source = tmp_path / "synthetic-source"
    write_base(source)
    data = tmp_path / "private-data"
    gold = data / "builds" / "synthetic-build" / "gold" if published_layout else data / "gold"
    gold.mkdir(parents=True)
    unrelated = tmp_path / "unrelated-cwd"
    unrelated.mkdir()
    monkeypatch.chdir(unrelated)
    configured = []
    original = verify.connect

    def observe(settings):
        con = original(settings)
        configured.append(spill_path(con))
        return con

    monkeypatch.setattr(verify, "connect", observe)
    result = verify.verify_transaction_in_source(str(source), "TXN00000001", cid(1), "2026-06-01",
                                                gold_dir=gold, refresh_listing=True)
    assert result["status"] == "changed"  # Synthetic source row is absent from empty gold.
    assert len(configured) == 1
    assert configured[0].parent == data.resolve() / ".duckdb-spill"
    assert not (unrelated / ".tmp").exists()
    assert not (unrelated / ".duckdb-spill").exists()
    assert not (gold / ".duckdb-spill").exists()
