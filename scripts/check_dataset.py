"""Read-only snapshot/lineage health check; output contains aggregates, never rows.

Run with the pipeline environment: python scripts/check_dataset.py --out data
Add --env S3credentials.env to compare every selected source object's metadata.
Inventory/size checks are not immutable S3 versioning or a proof of business truth.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import closing
from pathlib import Path, PurePosixPath

import duckdb

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.bronze import fingerprint, table_of
from pipeline.common import TXN_BUCKETS, configure_spill_directory, load_env, sql_bucket, sql_path

PRIMARY_KEYS = {
    "customers": "customer_id", "products": "product_id",
    "transactions": "transaction_id", "call_center_interactions": "interaction_id",
    "call_transcripts": "transcript_id", "complaints": "complaint_id",
}
BANKING_TABLES = {"customers", "products", "transactions"}
VALIDATED = "unchanged_inventory_after_ingestion"
BUILD_ID = re.compile(r"[A-Za-z0-9_-]{1,96}")
BUCKET_FILE = re.compile(r"transactions_by_customer/bucket=(\d+)/[^/]+\.parquet")


class HealthFailure(Exception):
    """Only constant, public error codes may cross the CLI boundary."""


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HealthFailure("metadata_unreadable") from None
    if not isinstance(value, dict):
        raise HealthFailure("metadata_invalid")
    return value


def _contained(path: Path, root: Path) -> bool:
    return root.resolve() in path.resolve().parents


def _inventory(value: dict, require_banking: bool = True) -> dict[str, list[dict]]:
    tables = value.get("tables")
    if (not isinstance(tables, dict) or not tables
            or (require_banking and not BANKING_TABLES.issubset(tables))):
        raise HealthFailure("source_inventory_incomplete")
    if not set(tables).issubset(PRIMARY_KEYS):
        raise HealthFailure("source_inventory_tables_invalid")
    selected, keys = {}, set()
    for table, info in tables.items():
        objects = info.get("objects") if isinstance(info, dict) else None
        if not isinstance(objects, list) or not objects:
            raise HealthFailure("source_inventory_invalid")
        for obj in objects:
            if (not isinstance(obj, dict) or not isinstance(obj.get("key"), str)
                    or not isinstance(obj.get("etag"), str) or not obj["etag"]
                    or type(obj.get("bytes")) is not int or obj["bytes"] < 0):
                raise HealthFailure("source_inventory_invalid")
            key = PurePosixPath(obj["key"])
            if (key.is_absolute() or ".." in key.parts or "\\" in obj["key"]
                    or key.as_posix() != obj["key"] or table_of(obj["key"]) != table
                    or not obj["key"].endswith(".csv") or obj["key"] in keys):
                raise HealthFailure("source_inventory_invalid")
            keys.add(obj["key"])
        if info.get("fingerprint") != fingerprint(objects):
            raise HealthFailure("source_table_fingerprint_mismatch")
        selected[table] = objects
    if value.get("fingerprint") != fingerprint([o for objects in selected.values() for o in objects]):
        raise HealthFailure("source_fingerprint_mismatch")
    return selected


def _s3_client(env: dict):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", region_name=env["Region"], aws_access_key_id=env["AccessKeyID"],
        aws_secret_access_key=env["SecretAccessKey"],
        config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}),
    )


def compare_source_objects(pinned: dict[str, list[dict]], env_path: Path | str) -> dict:
    """Compare selected tables only; source keys and AWS errors stay private."""
    try:
        env = load_env(Path(env_path))
        current = {table: {} for table in pinned}
        with closing(_s3_client(env)) as client:
            paginator = client.get_paginator("list_objects_v2")
            for table in sorted(pinned):
                for page in paginator.paginate(Bucket=env["BucketName"], Prefix="data/" + table):
                    for obj in page.get("Contents", []):
                        full_key = obj["Key"]
                        if not full_key.startswith("data/") or not full_key.endswith(".csv"):
                            continue
                        key = full_key[len("data/"):]
                        if table_of(key) == table:
                            current[table][key] = (obj["ETag"].strip('"'), obj["Size"])
        counts = {}
        for table, objects in pinned.items():
            old = {o["key"]: (o["etag"], o["bytes"]) for o in objects}
            new = current[table]
            counts[table] = {
                "pinned_objects": len(old), "current_objects": len(new),
                "added": len(new.keys() - old.keys()), "deleted": len(old.keys() - new.keys()),
                "changed": sum(old[k] != new[k] for k in old.keys() & new.keys()),
            }
        total = {name: sum(c[name] for c in counts.values())
                 for name in ("pinned_objects", "current_objects", "added", "deleted", "changed")}
        return {"status": "drift" if total["added"] or total["deleted"] or total["changed"] else "unchanged",
                "method": "selected_table_etag_and_size", **total, "tables": counts}
    except Exception:
        return {"status": "unavailable", "error": "source_metadata_check_failed"}


def _gold_files(build: Path, snapshot: dict, tables: set[str]) -> list[Path]:
    gold = build / "gold"
    if not _contained(gold, build):
        raise HealthFailure("gold_path_unsafe")
    files = snapshot.get("gold_files")
    if not isinstance(files, dict) or not files:
        raise HealthFailure("gold_inventory_missing")
    transactions = []
    for relative, size in files.items():
        if not isinstance(relative, str) or type(size) is not int or size < 0:
            raise HealthFailure("gold_inventory_invalid")
        relative_path = PurePosixPath(relative)
        path = gold / relative
        if (relative_path.is_absolute() or ".." in relative_path.parts or "\\" in relative
                or relative_path.as_posix() != relative or not _contained(path, gold)
                or path.suffix != ".parquet"):
            raise HealthFailure("gold_inventory_invalid")
        if not path.is_file():
            raise HealthFailure("gold_file_missing")
        if path.stat().st_size != size:
            raise HealthFailure("gold_file_size_mismatch")
        matched = BUCKET_FILE.fullmatch(relative)
        if matched:
            if matched[1] != str(int(matched[1])) or int(matched[1]) >= TXN_BUCKETS:
                raise HealthFailure("gold_bucket_invalid")
            transactions.append(path)
        elif relative.startswith("transactions_by_customer/"):
            raise HealthFailure("gold_bucket_invalid")
    present = {p.relative_to(gold).as_posix() for p in gold.rglob("*.parquet")}
    if present != set(files):
        raise HealthFailure("gold_file_set_mismatch")
    expected = {"demo_seed_candidates.parquet"}
    if {"customers", "call_center_interactions"}.issubset(tables):
        expected.add("contact_demand.parquet")
    if {"call_transcripts", "call_center_interactions"}.issubset(tables):
        expected.add("classifier_dataset.parquet")
    if not transactions or not expected.issubset(files):
        raise HealthFailure("gold_outputs_incomplete")
    return sorted(transactions)


def _row_checks(build: Path, files: list[Path], tables: set[str], manifest: dict,
                result: dict) -> None:
    with closing(duckdb.connect()) as con:
        configure_spill_directory(con, build.parent.parent)
        con.execute("SET threads=2")
        con.execute("SET memory_limit='1GB'")
        counts = {}
        for table in sorted(tables):
            path = build / "silver" / (table + ".parquet")
            if not path.is_file() or not _contained(path, build):
                raise HealthFailure("silver_file_missing")
            con.execute(f"CREATE VIEW s_{table} AS SELECT * FROM read_parquet('{sql_path(path)}')")
            pk = PRIMARY_KEYS[table]
            rows, unique, missing = con.execute(
                f"SELECT count(*), count(DISTINCT {pk}), count(*) FILTER (WHERE {pk} IS NULL) "
                f"FROM s_{table}").fetchone()
            counts[table] = rows
            if unique != rows or missing:
                result["errors"].append("silver_primary_key_invalid")
            recorded = manifest.get("tables", {}).get(table, {})
            silver = recorded.get("silver", {})
            bronze = recorded.get("bronze", {})
            if silver:
                if silver.get("rows") != rows:
                    result["errors"].append("silver_manifest_count_mismatch")
                accounting = [silver.get(k) for k in
                              ("raw_rows", "rows", "quarantined_rows", "duplicate_rows_removed")]
                if (not all(type(n) is int and n >= 0 for n in accounting)
                        or accounting[0] != sum(accounting[1:]) or silver.get("reconciles") is not True
                        or (bronze and bronze.get("rows") != accounting[0])):
                    result["errors"].append("silver_reconciliation_failed")
            else:
                result["warnings"].append("historical_silver_metrics_unavailable")
        result["silver_rows"] = counts
        paths = "[" + ",".join(f"'{sql_path(p)}'" for p in files) + "]"
        con.execute(f"CREATE VIEW g_transactions AS SELECT * FROM read_parquet({paths}, hive_partitioning=true)")
        shared = ("customer_id", "product_id", "transaction_date", "process_date", "amount", "currency",
                  "transaction_type", "transaction_category", "amount_usd", "channel", "merchant_name",
                  "merchant_category", "transaction_country", "transaction_city", "transaction_status",
                  "response_code", "is_fraud", "_late_arrival", "_source_file", "_partition_date", "_row_hash")
        differs = " OR ".join(f"g.{c} IS DISTINCT FROM t.{c}" for c in shared)
        expected_owner = "(c.customer_id IS NOT NULL AND p.product_id IS NOT NULL AND p.customer_id=g.customer_id)"
        rows, unique, valid, flag_mismatches, wrong_buckets, data_mismatches = con.execute(f"""
            SELECT count(*), count(DISTINCT g.transaction_id),
                   count(*) FILTER (WHERE g.ownership_valid),
                   count(*) FILTER (WHERE g.ownership_valid IS DISTINCT FROM {expected_owner}),
                   count(*) FILTER (WHERE g.bucket IS DISTINCT FROM {sql_bucket('g.customer_id', TXN_BUCKETS)}),
                   count(*) FILTER (WHERE t.transaction_id IS NULL OR {differs})
            FROM g_transactions g
            LEFT JOIN s_transactions t ON t.transaction_id=g.transaction_id
            LEFT JOIN s_products p ON p.product_id=g.product_id
            LEFT JOIN s_customers c ON c.customer_id=g.customer_id
        """).fetchone()
        result["gold_transactions"] = {
            "rows": rows, "ownership_valid_rows": valid, "ownership_invalid_rows": rows - valid,
            "ownership_flag_mismatches": flag_mismatches, "wrong_bucket_rows": wrong_buckets,
            "silver_data_mismatches": data_mismatches,
        }
        if rows != counts["transactions"] or unique != rows:
            result["errors"].append("gold_transaction_count_mismatch")
        if flag_mismatches:
            result["errors"].append("gold_ownership_mismatch")
        if wrong_buckets:
            result["errors"].append("gold_bucket_assignment_mismatch")
        if data_mismatches:
            result["errors"].append("gold_silver_data_mismatch")
        recorded = manifest.get("gold", {}).get("transactions_by_customer", {})
        if recorded and (recorded.get("rows") != rows or recorded.get("ownership_valid_rows") != valid):
            result["errors"].append("gold_manifest_count_mismatch")
        result["gold_rows"] = {"transactions_by_customer": rows}
        for name in ("contact_demand", "classifier_dataset", "demo_seed_candidates"):
            path = build / "gold" / (name + ".parquet")
            if not path.is_file():
                continue
            total = con.execute(f"SELECT count(*) FROM read_parquet('{sql_path(path)}')").fetchone()[0]
            result["gold_rows"][name] = total
            metrics = manifest.get("gold", {}).get(name, {})
            expected = metrics.get("rows")
            if name == "demo_seed_candidates" and metrics.get("customers_picked"):
                expected = sum(metrics["customers_picked"].values())
            if expected is not None and expected != total:
                result["errors"].append("gold_manifest_count_mismatch")


def _bronze_status(out: Path, tables: set[str], pinned: dict, result: dict) -> None:
    marker = out / "bronze" / "source_objects.json"
    if not marker.is_file():
        result["bronze"] = {"status": "validation_marker_missing", "reusable": False}
        result["warnings"].append("bronze_refresh_required_before_silver_rebuild")
        return
    if not _contained(marker, out):
        raise HealthFailure("bronze_path_unsafe")
    inventory = _read_json(marker)
    selected = _inventory(inventory, require_banking=False)
    if not tables.issubset(selected):
        result["bronze"] = {"status": "selected_tables_missing", "reusable": False}
        result["warnings"].append("bronze_refresh_required_before_silver_rebuild")
        return
    selected_fp = fingerprint([o for t in tables for o in selected[t]])
    validated = inventory.get("source_validation") == VALIDATED
    available = all((out / "bronze" / (t + ".parquet")).is_file() for t in tables)
    result["bronze"] = {"status": "inventory_validated" if validated else "legacy_inventory",
                        "reusable": validated and available,
                        "matches_published_inventory": selected_fp == pinned["fingerprint"]}
    if not validated or not available:
        result["warnings"].append("bronze_refresh_required_before_silver_rebuild")


def check_dataset(out: Path | str, env_path: Path | str | None = None) -> dict:
    result = {"ok": False, "status": "failed", "errors": [], "warnings": [],
              "source_comparison": {"status": "not_requested"}}
    try:
        out = Path(out).resolve()
        if not _contained(out / "CURRENT", out):
            raise HealthFailure("current_pointer_invalid")
        build_id = (out / "CURRENT").read_text(encoding="utf-8").strip()
        if not BUILD_ID.fullmatch(build_id):
            raise HealthFailure("current_pointer_invalid")
        builds = out / "builds"
        build = builds / build_id
        if not _contained(builds, out) or build.resolve().parent != builds.resolve() or not build.is_dir():
            raise HealthFailure("current_build_missing_or_unsafe")
        result["build_id"] = build_id
        for filename in ("snapshot.json", "source_objects.json"):
            if not _contained(build / filename, build):
                raise HealthFailure("metadata_path_unsafe")
        snapshot = _read_json(build / "snapshot.json")
        if snapshot.get("build_id") != build_id:
            raise HealthFailure("snapshot_build_mismatch")
        lineage = _read_json(build / "source_objects.json")
        selected = _inventory(lineage)
        if snapshot.get("source_fingerprint") != lineage["fingerprint"]:
            raise HealthFailure("snapshot_source_fingerprint_mismatch")
        validation = lineage.get("source_validation", "legacy_inventory")
        if validation not in (VALIDATED, "legacy_inventory"):
            raise HealthFailure("source_validation_invalid")
        if snapshot.get("source_validation", "legacy_inventory") != validation:
            raise HealthFailure("snapshot_source_validation_mismatch")
        result["lineage"] = {"status": "inventory_validated" if validation == VALIDATED else "legacy_inventory",
                             "tables": sorted(selected),
                             "source_objects": sum(len(v) for v in selected.values()),
                             "immutable_source_versions": False}
        if validation == "legacy_inventory":
            result["warnings"].append("legacy_lineage_refresh_from_bronze_recommended")
        manifest_path = build / "manifest.json"
        manifest = {}
        if manifest_path.is_file():
            if not _contained(manifest_path, build):
                raise HealthFailure("metadata_path_unsafe")
            manifest = _read_json(manifest_path)
            # CURRENT has already established which snapshot is serving.
            # New manifests record pre-publication readiness; the old boolean
            # remains accepted for historical immutable snapshots.
            ready = (manifest.get("publication_status") == "ready"
                     if "publication_status" in manifest else manifest.get("published") is True)
            if manifest.get("run_id") != build_id or not ready:
                raise HealthFailure("manifest_build_mismatch")
            if manifest.get("source_fingerprint") != lineage["fingerprint"]:
                raise HealthFailure("manifest_source_fingerprint_mismatch")
            if set(manifest.get("tables_requested", [])) != set(selected):
                raise HealthFailure("manifest_tables_mismatch")
            if manifest.get("contract_failures"):
                raise HealthFailure("published_contract_failure")
            if not manifest.get("silver_contracts_sha256_12"):
                result["warnings"].append("historical_silver_contract_version_unavailable")
        elif validation == "legacy_inventory":
            result["warnings"].append("legacy_pinned_manifest_unavailable")
        else:
            raise HealthFailure("pinned_manifest_missing")
        files = _gold_files(build, snapshot, set(selected))
        result["gold_files_checked"] = len(snapshot["gold_files"])
        _row_checks(build, files, set(selected), manifest, result)
        _bronze_status(out, set(selected), lineage, result)
        if env_path is not None:
            result["source_comparison"] = compare_source_objects(selected, env_path)
            if result["source_comparison"]["status"] == "drift":
                result["errors"].append("source_inventory_drift")
            elif result["source_comparison"]["status"] != "unchanged":
                result["errors"].append("source_metadata_check_failed")
    except HealthFailure as exc:
        result["errors"].append(str(exc))
    except FileNotFoundError:
        result["errors"].append("dataset_file_missing")
    except Exception:
        # DuckDB errors may contain SQL, paths or source row values; never emit them.
        result["errors"].append("dataset_check_failed")
    result["errors"] = sorted(set(result["errors"]))
    result["warnings"] = sorted(set(result["warnings"]))
    result["ok"] = not result["errors"]
    result["status"] = "failed" if result["errors"] else "warning" if result["warnings"] else "ok"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data", help="Data root containing CURRENT")
    parser.add_argument("--env", help="Private S3 env; enables full selected-table metadata comparison")
    parser.add_argument("--report", help="Optional aggregate JSON output file")
    args = parser.parse_args(argv)
    result = check_dataset(args.out, args.env)
    if args.report:
        report_path = Path(args.report).resolve()
        out = Path(args.out).resolve()
        protected = {out / "CURRENT", Path(args.env).resolve() if args.env else out / "CURRENT"}
        if (report_path in protected or _contained(report_path, out / "builds")
                or _contained(report_path, out / "bronze") or report_path.suffix != ".json"):
            result["errors"].append("report_target_unsafe")
        else:
            try:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            except OSError:
                result["errors"].append("report_write_failed")
        if result["errors"]:
            result["ok"], result["status"] = False, "failed"
    print(json.dumps(result, indent=2))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
