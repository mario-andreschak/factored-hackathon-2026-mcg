"""Health checks use the labeled synthetic pipeline fixture, never organizer rows."""
from __future__ import annotations

import json
import shutil
from contextlib import closing

import duckdb
import pytest

from pipeline.__main__ import main as pipeline_main
from pipeline.common import current_build, sql_path
from pipeline.fixture import cid, write_base
from scripts import check_dataset as health


@pytest.fixture(scope="module")
def healthy_source(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic_dataset_health")
    write_base(root / "source")
    assert pipeline_main(["run", "--source", str(root / "source"),
                          "--out", str(root / "out"), "--reports", str(root / "reports")]) == 0
    return root / "out"


@pytest.fixture
def dataset(healthy_source, tmp_path):
    out = tmp_path / "out"
    shutil.copytree(healthy_source, out)
    return out


def rewrite_json(path, update):
    value = json.loads(path.read_text(encoding="utf-8"))
    update(value)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def bucket_file(out):
    return next((current_build(out) / "gold" / "transactions_by_customer").rglob("*.parquet"))


def test_valid_snapshot_counts_and_independent_owner_check(dataset):
    report = health.check_dataset(dataset)
    assert report["ok"], report
    assert report["status"] == "ok"
    assert report["lineage"]["status"] == "inventory_validated"
    assert report["bronze"]["reusable"]
    assert report["bronze"]["matches_published_inventory"]
    assert report["silver_rows"]["transactions"] == 66
    assert report["gold_transactions"]["ownership_valid_rows"] == 65
    assert report["gold_transactions"]["ownership_invalid_rows"] == 1
    assert report["gold_transactions"]["ownership_flag_mismatches"] == 0
    assert cid(0) not in json.dumps(report)


def test_missing_bucket_file_is_an_integrity_failure(dataset):
    bucket_file(dataset).unlink()
    report = health.check_dataset(dataset)
    assert not report["ok"]
    assert "gold_file_missing" in report["errors"]


def test_unlisted_gold_file_is_rejected(dataset):
    original = bucket_file(dataset)
    shutil.copyfile(original, original.with_name("unexpected.parquet"))
    report = health.check_dataset(dataset)
    assert not report["ok"]
    assert "gold_file_set_mismatch" in report["errors"]


def test_expected_consumer_file_cannot_be_omitted_from_inventory(dataset):
    build = current_build(dataset)
    (build / "gold" / "classifier_dataset.parquet").unlink()
    rewrite_json(build / "snapshot.json", lambda value: value["gold_files"].pop("classifier_dataset.parquet"))
    report = health.check_dataset(dataset)
    assert "gold_outputs_incomplete" in report["errors"]


def test_lineage_table_fingerprint_mismatch_is_rejected(dataset):
    rewrite_json(current_build(dataset) / "source_objects.json",
                 lambda value: value["tables"]["transactions"].update(fingerprint="0" * 16))
    assert "source_table_fingerprint_mismatch" in health.check_dataset(dataset)["errors"]


def test_pinned_manifest_from_another_build_is_rejected(dataset):
    rewrite_json(current_build(dataset) / "manifest.json", lambda value: value.update(run_id="other-build"))
    assert "manifest_build_mismatch" in health.check_dataset(dataset)["errors"]


def test_validated_build_requires_a_pinned_manifest(dataset):
    (current_build(dataset) / "manifest.json").unlink()
    assert "pinned_manifest_missing" in health.check_dataset(dataset)["errors"]


def test_legacy_inventory_warns_without_claiming_new_validation(dataset):
    build = current_build(dataset)
    rewrite_json(build / "snapshot.json", lambda value: value.update(source_validation="legacy_inventory"))
    rewrite_json(build / "source_objects.json", lambda value: value.pop("source_validation"))
    (build / "manifest.json").unlink()
    report = health.check_dataset(dataset)
    assert report["ok"]
    assert report["status"] == "warning"
    assert report["lineage"]["status"] == "legacy_inventory"
    assert "legacy_lineage_refresh_from_bronze_recommended" in report["warnings"]
    assert "legacy_pinned_manifest_unavailable" in report["warnings"]
    assert report["gold_transactions"]["ownership_flag_mismatches"] == 0


def rewrite_gold(out, select):
    build = current_build(out)
    path = bucket_file(out)
    temporary = path.with_suffix(".tmp")
    with closing(duckdb.connect()) as con:
        con.execute(f"COPY (SELECT {select} FROM read_parquet('{sql_path(path)}', hive_partitioning=false)) "
                    f"TO '{sql_path(temporary)}' (FORMAT parquet)")
    temporary.replace(path)
    relative = path.relative_to(build / "gold").as_posix()
    rewrite_json(build / "snapshot.json", lambda value: value["gold_files"].update({relative: path.stat().st_size}))


def test_owner_flags_are_checked_against_the_real_chain_not_trusted(dataset):
    rewrite_gold(dataset, "* EXCLUDE (ownership_valid), NOT ownership_valid AS ownership_valid")
    report = health.check_dataset(dataset)
    assert "gold_ownership_mismatch" in report["errors"]
    assert report["gold_transactions"]["ownership_flag_mismatches"] > 0


def test_gold_values_are_compared_to_silver_even_with_a_valid_size_inventory(dataset):
    rewrite_gold(dataset, "* EXCLUDE (amount), amount + 1 AS amount")
    report = health.check_dataset(dataset)
    assert "gold_silver_data_mismatch" in report["errors"]
    assert report["gold_transactions"]["silver_data_mismatches"] > 0


def test_current_cannot_escape_the_build_directory(dataset):
    (dataset / "CURRENT").write_text("../outside", encoding="utf-8")
    assert "current_pointer_invalid" in health.check_dataset(dataset)["errors"]


class FakeClient:
    def __init__(self, objects, failure=None):
        self.objects, self.failure, self.closed = objects, failure, False

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return self

    def paginate(self, *, Bucket, Prefix):
        if self.failure:
            raise RuntimeError(self.failure)
        assert Bucket == "private-bucket"
        return [{"Contents": [{"Key": "data/" + o["key"], "ETag": '"' + o["etag"] + '"', "Size": o["bytes"]}
                               for o in self.objects if ("data/" + o["key"]).startswith(Prefix)]}]

    def close(self):
        self.closed = True


def mock_s3(monkeypatch, objects, failure=None):
    client = FakeClient(objects, failure)
    monkeypatch.setattr(health, "load_env", lambda _: {"BucketName": "private-bucket"})
    monkeypatch.setattr(health, "_s3_client", lambda _: client)
    return client


def test_source_metadata_comparison_detects_added_deleted_and_changed(monkeypatch):
    pinned = {"transactions": [{"key": "transactions/old.csv", "etag": "old", "bytes": 5},
                               {"key": "transactions/changed.csv", "etag": "before", "bytes": 9}]}
    client = mock_s3(monkeypatch, [{"key": "transactions/new.csv", "etag": "new", "bytes": 5},
                                    {"key": "transactions/changed.csv", "etag": "after", "bytes": 9}])
    report = health.compare_source_objects(pinned, "unused.env")
    assert (report["added"], report["deleted"], report["changed"]) == (1, 1, 1)
    assert report["status"] == "drift"
    assert client.closed
    assert "transactions/changed.csv" not in json.dumps(report)


def test_selected_source_drift_makes_the_whole_health_check_fail(dataset, monkeypatch):
    lineage = json.loads((current_build(dataset) / "source_objects.json").read_text())
    objects = [o.copy() for table in lineage["tables"].values() for o in table["objects"]]
    objects[0]["etag"] = "changed"
    client = mock_s3(monkeypatch, objects)
    report = health.check_dataset(dataset, "unused.env")
    assert not report["ok"]
    assert "source_inventory_drift" in report["errors"]
    assert report["source_comparison"]["changed"] == 1
    assert client.closed


def test_source_exception_is_sanitized_and_client_closed(monkeypatch):
    private_error = "AWS private-bucket access-key secret-key customer-row"
    client = mock_s3(monkeypatch, [], failure=private_error)
    report = health.compare_source_objects({"transactions": []}, "unused.env")
    assert report == {"status": "unavailable", "error": "source_metadata_check_failed"}
    assert private_error not in json.dumps(report)
    assert client.closed


def test_cli_writes_only_aggregates_and_cannot_replace_snapshot_metadata(dataset, tmp_path, capsys):
    target = tmp_path / "health.json"
    assert health.main(["--out", str(dataset), "--report", str(target)]) == 0
    output = capsys.readouterr().out
    assert cid(0) not in output
    assert json.loads(target.read_text())["ok"]
    snapshot = current_build(dataset) / "snapshot.json"
    original = snapshot.read_bytes()
    assert health.main(["--out", str(dataset), "--report", str(snapshot)]) == 2
    assert snapshot.read_bytes() == original
