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
from datetime import datetime, timezone
from pathlib import Path

from . import bronze, gold, lookup, report, silver
from .common import Settings, current_gold, current_silver, load_env, publish

DEFAULT_TABLES = ["customers", "products", "transactions", "call_center_interactions",
                  "call_transcripts", "complaints"]
STAGES = ["bronze", "silver", "gold"]


def build_settings(a) -> Settings:
    s3 = {}
    source = a.source
    if source == "s3":
        s3 = load_env(Path(a.env))
        source = f"s3://{s3['BucketName']}/data"
    return Settings(source=source, out_dir=Path(a.out), report_dir=Path(a.reports),
                    tables=a.tables, s3=s3, threads=a.threads, memory_limit=a.memory_limit)


def cmd_run(a) -> int:
    settings = build_settings(a)
    stages = STAGES if "all" in a.stage else [s for s in STAGES if s in a.stage]
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    manifest_path = settings.report_dir / "manifest.json"
    stats: dict = {}
    if "bronze" not in stages and manifest_path.exists():  # keep bronze stats from the last full run
        prev_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        prev = prev_manifest.get("tables", {})
        stats = {t: {"bronze": v["bronze"]} for t, v in prev.items() if "bronze" in v and t in settings.tables}
        if prev_manifest.get("source_fingerprint"):
            stats["_source_fingerprint"] = prev_manifest["source_fingerprint"]
    settings.build_id = run_id
    if "gold" in stages and "silver" not in stages:
        # gold-only: this snapshot is built from a copy of the last published silver
        shutil.copytree(current_silver(settings.out_dir), settings.silver)
    t0 = time.perf_counter()
    published = False
    for stage in stages:
        if stage == "gold" and stats.get("_contract_failures"):
            print("gold    skipped: silver failed its contracts", flush=True)
            break
        {"bronze": bronze.run, "silver": silver.run, "gold": gold.run}[stage](settings, run_id, stats)
    # Only a build that produced gold and passed every contract becomes the serving snapshot.
    derived = [s for s in stages if s != "bronze"]
    if "gold" in stages and not stats.get("_contract_failures"):
        if (settings.gold / "transactions_by_customer").exists():
            stats.setdefault("_gold", {})["lookup_bench"] = lookup.bench(settings.gold)
            b = stats["_gold"]["lookup_bench"]
            print(f"bench   per-customer lookup        p50 {b['p50_ms']} ms | p95 {b['p95_ms']} ms", flush=True)
        # The MCP must pin lineage to the same immutable snapshot as the served rows.
        # A report beside CURRENT can be overwritten by the next ingestion run.
        lineage = settings.report_dir / "source_objects.json"
        if lineage.exists():
            inventory = json.loads(lineage.read_text(encoding="utf-8"))
            if inventory.get("fingerprint") == stats.get("_source_fingerprint"):
                shutil.copyfile(lineage, settings.build_dir / "source_objects.json")
        (settings.build_dir / "snapshot.json").write_text(json.dumps({
            "build_id": run_id, "source_fingerprint": stats.get("_source_fingerprint"),
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }) + "\n", encoding="utf-8")
        publish(settings.out_dir, run_id)
        published = True
        print(f"publish build {run_id} is now serving", flush=True)
    elif stats.get("_contract_failures"):
        print(f"publish SKIPPED: build {run_id} failed; the previous snapshot keeps serving", flush=True)
    elif derived:
        print(f"publish SKIPPED: build {run_id} has no gold stage (run silver and gold together to publish)",
              flush=True)
    redacted = "s3://<bucket>/data" if settings.source.startswith("s3://") else Path(settings.source).as_posix()
    report.write(settings.report_dir, {
        "run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - t0, 1), "source": redacted, "stages": ",".join(stages),
        "published": published,
        "source_fingerprint": stats.get("_source_fingerprint"),
        "tables_requested": settings.tables}, stats)
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
        row = duckdb.connect().execute(f"""
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
