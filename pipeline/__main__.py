"""CLI.

    python -m pipeline run                       # all stages from S3 (reads S3credentials.env)
    python -m pipeline run --stage silver gold   # re-run from local bronze, no S3 needed
    python -m pipeline run --source tests/fixture_data   # any local folder with the S3 layout
    python -m pipeline bench                     # lookup latency at 1 / 50 / 500 concurrent users
    python -m pipeline verify TXN.. --customer CUS.. --date 2026-06-01   # re-check against source
    python -m pipeline fixture tests/fixture_data        # write the labeled synthetic fixture
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from . import bronze, gold, lookup, report, silver
from .common import (Settings, contracts_digest, current_build, current_gold, load_contracts,
                     load_env, publish, sql_path)
from .writer import writer_lock

DEFAULT_TABLES = ["customers", "products", "transactions", "call_center_interactions",
                  "call_transcripts", "complaints"]
STAGES = ["bronze", "silver", "gold"]
BANKING_TABLES = {"customers", "products", "transactions"}


def validate_selection(tables: list[str], stages: list[str]) -> None:
    unknown = set(tables) - set(DEFAULT_TABLES)
    if unknown:
        raise ValueError(f"unknown tables: {', '.join(sorted(unknown))}")
    if len(tables) != len(set(tables)):
        raise ValueError("select each table only once")
    if "bronze" in stages and "gold" in stages and "silver" not in stages:
        raise ValueError("bronze and gold require the silver stage between them")
    if "gold" in stages and not BANKING_TABLES.issubset(tables):
        raise ValueError("publishing gold requires customers, products and transactions; "
                         "use bronze/silver stages for other table subsets")
    if "silver" in stages or "gold" in stages:
        contracts = load_contracts()
        missing = []
        for table in tables:
            parents = {c["fk"].split(".")[0] for c in contracts[table]["columns"].values()
                       if c.get("fk") and not c.get("drop")}
            missing.extend(f"{table} requires {parent}" for parent in sorted(parents - set(tables)))
        if missing:
            raise ValueError("selected tables omit parent dependencies: " + "; ".join(missing))


def selected_inventory(path: Path, tables: list[str]) -> tuple[dict, dict]:
    original = json.loads(path.read_text(encoding="utf-8"))
    missing = set(tables) - set(original["tables"])
    if missing:
        raise RuntimeError("source inventory does not cover requested tables; rebuild from bronze")
    selected = {t: original["tables"][t] for t in tables}
    return original, {**original, "tables": selected,
                      "fingerprint": bronze.fingerprint([o for t in tables
                                                          for o in selected[t]["objects"]])}


def pinned_manifest(path: Path, inventory: dict) -> dict:
    if not path.is_file():
        return {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    # Mutable docs/pipeline reports are never an input to a build. Metadata must
    # describe the same landing or immutable published snapshot as its inventory.
    if manifest.get("source_fingerprint") != inventory["fingerprint"]:
        raise RuntimeError("pinned aggregate manifest does not match its source inventory")
    return manifest


def bronze_statistics(settings: Settings, inventory: dict, manifest: dict) -> dict:
    stats = {}
    for table in settings.tables:
        recorded = manifest.get("tables", {}).get(table, {}).get("bronze", {})
        if recorded.get("source_fingerprint") == inventory["tables"][table]["fingerprint"]:
            stats[table] = {"bronze": recorded}
            continue
        # A validated pre-existing landing may have an inventory but no pinned
        # aggregate manifest. Recount it locally instead of inventing old metrics.
        import duckdb
        path = settings.bronze / f"{table}.parquet"
        with closing(duckdb.connect()) as con:
            rows, sources = con.execute(
                f"SELECT count(*), count(DISTINCT _source_file) FROM '{sql_path(path)}'").fetchone()
        objects = inventory["tables"][table]["objects"]
        stats[table] = {"bronze": {
            "rows": rows, "source_objects_with_rows": sources,
            "source_objects": len(objects), "source_bytes": sum(o["bytes"] for o in objects),
            "source_fingerprint": inventory["tables"][table]["fingerprint"],
        }}
    return stats


def build_settings(a) -> Settings:
    s3 = {}
    source = a.source
    if source == "s3":
        if "all" in a.stage or "bronze" in a.stage:
            s3 = load_env(Path(a.env))
            source = f"s3://{s3['BucketName']}/data"
        else:
            source = "cached_bronze"  # offline derived stages use their pinned input lineage
    return Settings(source=source, out_dir=Path(a.out), report_dir=Path(a.reports),
                    tables=a.tables, s3=s3, threads=a.threads, memory_limit=a.memory_limit)


def cmd_run(a) -> int:
    stages = STAGES if "all" in a.stage else [s for s in STAGES if s in a.stage]
    validate_selection(a.tables, stages)
    settings = build_settings(a)
    with writer_lock(settings.out_dir):
        return run_locked(settings, stages)


def run_locked(settings: Settings, stages: list[str]) -> int:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    stats: dict = {}
    input_manifest = {}
    inventory = None
    redacted = "s3://<bucket>/data" if settings.source.startswith("s3://") else Path(settings.source).as_posix()
    silver_contracts = contracts_digest()
    silver_build_id = run_id
    settings.build_id = run_id
    lineage = settings.bronze / "source_objects.json"
    if "silver" in stages and "bronze" not in stages and not lineage.is_file():
        raise RuntimeError("validated bronze inventory missing; run bronze before silver")
    if "silver" in stages and "bronze" not in stages:
        original, inventory = selected_inventory(lineage, settings.tables)
        input_manifest = pinned_manifest(settings.bronze / "manifest.json", original)
        stats = bronze_statistics(settings, inventory, input_manifest)
        redacted = input_manifest.get("source", "validated local bronze inventory")
    if "gold" in stages and "silver" not in stages:
        # gold-only: this snapshot is built from a copy of the last published silver
        previous = current_build(settings.out_dir)
        lineage = previous / "source_objects.json"
        if not lineage.is_file():
            raise RuntimeError("published source inventory missing; rebuild from bronze")
        original, inventory = selected_inventory(lineage, settings.tables)
        input_manifest = pinned_manifest(previous / "manifest.json", original)
        stats = {t: {k: v for k, v in input_manifest.get("tables", {}).get(t, {}).items()
                     if k in ("bronze", "silver")} for t in settings.tables}
        redacted = input_manifest.get("source", "legacy published source inventory")
        silver_contracts = input_manifest.get("silver_contracts_sha256_12",
                                             input_manifest.get("contracts_sha256_12"))
        silver_build_id = input_manifest.get("silver_build_id", previous.name)
        missing = [t for t in settings.tables if not (previous / "silver" / f"{t}.parquet").is_file()]
        if missing:
            raise RuntimeError(f"published silver does not cover requested tables: {missing}")
        settings.silver.mkdir(parents=True, exist_ok=True)
        for table in settings.tables:
            shutil.copyfile(previous / "silver" / f"{table}.parquet",
                            settings.silver / f"{table}.parquet")
    t0 = time.perf_counter()
    publication_ready = False
    for stage in stages:
        if stage == "gold" and stats.get("_contract_failures"):
            print("gold    skipped: silver failed its contracts", flush=True)
            break
        {"bronze": bronze.run, "silver": silver.run, "gold": gold.run}[stage](settings, run_id, stats)
        if stage == "bronze":
            _, inventory = selected_inventory(lineage, settings.tables)
            (settings.bronze / "manifest.json").write_text(json.dumps({
                "run_id": run_id, "source": redacted, "source_fingerprint": inventory["fingerprint"],
                "tables": {t: {"bronze": stats[t]["bronze"]} for t in settings.tables},
            }, indent=2) + "\n", encoding="utf-8")
    # Only a build that produced gold and passed every contract becomes the serving snapshot.
    derived = [s for s in stages if s != "bronze"]
    if "gold" in stages and not stats.get("_contract_failures"):
        if (settings.gold / "transactions_by_customer").exists():
            stats.setdefault("_gold", {})["lookup_bench"] = lookup.bench(settings.gold)
            b = stats["_gold"]["lookup_bench"]
            print(f"bench   per-customer lookup        p50 {b['p50_ms']} ms | p95 {b['p95_ms']} ms", flush=True)
        # The MCP must pin lineage to the same immutable snapshot as the served rows.
        # A report beside CURRENT can be overwritten by the next ingestion run.
        if not (settings.gold / "transactions_by_customer").is_dir():
            raise RuntimeError("gold did not produce the banking serving output; publication refused")
        stats["_source_fingerprint"] = inventory["fingerprint"]
        (settings.build_dir / "source_objects.json").write_text(
            json.dumps(inventory, indent=1) + "\n", encoding="utf-8")
        (settings.build_dir / "snapshot.json").write_text(json.dumps({
            "build_id": run_id, "source_fingerprint": stats.get("_source_fingerprint"),
            "source_validation": inventory.get("source_validation", "legacy_inventory"),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "transaction_event_dates": {
                **stats["_gold"]["transactions_by_customer"]["transaction_event_dates"],
                "source_fingerprint": inventory["fingerprint"],
            },
            "gold_files": {p.relative_to(settings.gold).as_posix(): p.stat().st_size
                           for p in sorted(settings.gold.rglob("*.parquet"))},
        }) + "\n", encoding="utf-8")
        publication_ready = True
    elif stats.get("_contract_failures"):
        print(f"publish SKIPPED: build {run_id} failed; the previous snapshot keeps serving", flush=True)
    elif derived:
        print(f"publish SKIPPED: build {run_id} has no gold stage (run silver and gold together to publish)",
              flush=True)
    if inventory is not None:
        stats["_source_fingerprint"] = inventory["fingerprint"]
    run = {
        "run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - t0, 1), "source": redacted, "stages": ",".join(stages),
        # Reports describe the candidate before CURRENT is swapped. Readiness
        # is not proof that publication succeeded; CURRENT is authoritative.
        "publication_status": "ready" if publication_ready else "not_ready",
        "source_fingerprint": stats.get("_source_fingerprint"),
        "source_validation": (inventory.get("source_validation", "legacy_inventory")
                              if inventory is not None else None),
        "tables_requested": settings.tables,
        "silver_build_id": silver_build_id if "gold" in stages or "silver" in stages else None,
        "silver_contracts_sha256_12": silver_contracts if "gold" in stages or "silver" in stages else None,
    }
    if publication_ready:
        # Complete the immutable snapshot and required external aggregate
        # reports before changing the serving pointer. No report writes follow
        # publication, so their failure cannot turn a failed run into a release.
        report.write(settings.build_dir, run, stats)
    report.write(settings.report_dir, run, stats)
    if publication_ready:
        publish(settings.out_dir, run_id)
        print(f"publish build {run_id} is now serving", flush=True)
    print(f"report  {settings.report_dir / 'quality_report.md'}", flush=True)
    if stats.get("_contract_failures"):
        print("CONTRACT FAILURES:\n  " + "\n  ".join(stats["_contract_failures"]), file=sys.stderr)
        return 2
    return 0


def cmd_bench(a) -> int:
    result = lookup.bench_concurrent(current_gold(a.out), a.concurrency, a.requests)
    Path(a.reports).mkdir(parents=True, exist_ok=True)
    (Path(a.reports) / "lookup_bench.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{'users':>6} {'requests':>9} {'ok':>6} {'errors':>6} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8} {'req/s':>8}")
    for r in result["levels"]:
        print(f"{r['concurrency']:>6} {r['requests']:>9} {r['ok']:>6} {r['errors']:>6} {r['p50_ms']:>8} "
              f"{r['p95_ms']:>8} {r['p99_ms']:>8} {r['throughput_rps']:>8}")
    print(f"wrote {Path(a.reports) / 'lookup_bench.json'}")
    return 0


def cmd_verify(a) -> int:
    from .verify import verify_transaction_in_source
    if a.sample:
        import duckdb
        from .common import sql_path
        with closing(duckdb.connect()) as con:
            row = con.execute(f"""
                SELECT transaction_id, customer_id, process_date::VARCHAR
                FROM read_parquet('{sql_path(current_gold(a.out) / "transactions_by_customer")}/**/*.parquet')
                WHERE ownership_valid USING SAMPLE 1 ROWS""").fetchone()
        a.transaction_id, a.customer, a.date = row
        print(f"sampled {a.transaction_id} for {a.customer} on {a.date}")
    if not (a.transaction_id and a.customer and a.date):
        print("give TRANSACTION_ID --customer --date, or --sample", file=sys.stderr)
        return 2
    s3 = load_env(Path(a.env)) if a.source == "s3" else None
    source = f"s3://{s3['BucketName']}/data" if s3 else a.source
    result = verify_transaction_in_source(source, a.transaction_id, a.customer, a.date, s3=s3,
                                          gold_dir=current_gold(a.out))
    print(json.dumps(result, indent=2, default=str, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m pipeline", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run pipeline stages")
    r.add_argument("--stage", nargs="+", default=["all"], choices=["all", *STAGES])
    r.add_argument("--source", default="s3", help="'s3' (default) or a local folder with the same layout")
    r.add_argument("--env", default="S3credentials.env")
    r.add_argument("--out", default="data", help="local output root (git-ignored)")
    r.add_argument("--reports", default="docs/pipeline", help="aggregate reports (committed)")
    r.add_argument("--tables", nargs="+", default=DEFAULT_TABLES)
    r.add_argument("--threads", type=int)
    r.add_argument("--memory-limit", help="e.g. 6GB on a 16 GB laptop / Colab")
    r.set_defaults(func=cmd_run)

    b = sub.add_parser("bench", help="per-customer lookup latency, sequential and concurrent")
    b.add_argument("--out", default="data")
    b.add_argument("--concurrency", type=int, nargs="+", default=[1, 50, 500])
    b.add_argument("--requests", type=int, default=1000, help="requests per concurrency level")
    b.add_argument("--reports", default="docs/pipeline")
    b.set_defaults(func=cmd_bench)

    v = sub.add_parser("verify", help="re-read one transaction from the source of record")
    v.add_argument("transaction_id", nargs="?", help="omit with --sample")
    v.add_argument("--customer", help="customer_id from the verified session")
    v.add_argument("--date", help="process_date as served by gold (YYYY-MM-DD)")
    v.add_argument("--sample", action="store_true", help="pick a random transaction from gold and verify it")
    v.add_argument("--source", default="s3")
    v.add_argument("--env", default="S3credentials.env")
    v.add_argument("--out", default="data")
    v.set_defaults(func=cmd_verify)

    f = sub.add_parser("fixture", help="write the labeled synthetic test fixture")
    f.add_argument("path")
    f.add_argument("--with-late-batch", action="store_true")

    def _fixture(a):
        from .fixture import write_base, write_late_batch
        write_base(Path(a.path))
        if a.with_late_batch:
            write_late_batch(Path(a.path))
        print(f"fixture written to {a.path}")
        return 0
    f.set_defaults(func=_fixture)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
