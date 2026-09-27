"""CLI.

    python -m pipeline run                       # all stages from S3 (reads S3credentials.env)
    python -m pipeline run --stage silver gold   # re-run from local bronze, no S3 needed
    python -m pipeline run --source tests/fixture_data   # any local folder with the S3 layout
    python -m pipeline bench                     # per-customer lookup latency on gold
    python -m pipeline fixture tests/fixture_data        # write the labeled synthetic fixture
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import bronze, gold, lookup, report, silver
from .common import Settings, load_env

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
        prev = json.loads(manifest_path.read_text(encoding="utf-8")).get("tables", {})
        stats = {t: {"bronze": v["bronze"]} for t, v in prev.items() if "bronze" in v and t in settings.tables}
    t0 = time.perf_counter()
    for stage in stages:
        {"bronze": bronze.run, "silver": silver.run, "gold": gold.run}[stage](settings, run_id, stats)
    if "gold" in stages and (settings.gold / "transactions_by_customer").exists():
        stats.setdefault("_gold", {})["lookup_bench"] = lookup.bench(settings.gold)
        b = stats["_gold"]["lookup_bench"]
        print(f"bench   per-customer lookup        p50 {b['p50_ms']} ms | p95 {b['p95_ms']} ms", flush=True)
    redacted = "s3://<bucket>/data" if settings.source.startswith("s3://") else Path(settings.source).as_posix()
    report.write(settings.report_dir, {
        "run_id": run_id, "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": round(time.perf_counter() - t0, 1), "source": redacted, "stages": ",".join(stages),
        "tables_requested": settings.tables}, stats)
    print(f"report  {settings.report_dir / 'quality_report.md'}", flush=True)
    if stats.get("_contract_failures"):
        print("CONTRACT FAILURES:\n  " + "\n  ".join(stats["_contract_failures"]), file=sys.stderr)
        return 2
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

    b = sub.add_parser("bench", help="per-customer lookup latency")
    b.add_argument("--out", default="data")
    b.add_argument("--samples", type=int, default=50)
    b.set_defaults(func=lambda a: print(json.dumps(lookup.bench(Path(a.out) / "gold", a.samples))) or 0)

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
