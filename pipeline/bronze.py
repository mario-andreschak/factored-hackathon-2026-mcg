"""Bronze: land raw CSVs as Parquet, untouched except for lineage columns.

Everything is read as VARCHAR so nothing is silently coerced or dropped here;
typing and rejection happen in silver where they are counted.
"""

from __future__ import annotations

import csv
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import Settings, connect, sql_path

PART_RE = r"year=(\d{4})/month=(\d{2})/day=(\d{2})"


def discover(con, settings: Settings) -> dict[str, list[str]]:
    """Map table -> list of CSV objects, using the same naming rule as scripts/profile_s3.py:
    table = first path segment under the source root, minus a trailing '.csv'."""
    root = settings.source.rstrip("/")
    if root.startswith("s3://"):
        files = [r[0] for r in con.execute(f"SELECT file FROM glob('{sql_path(root)}/**/*.csv')").fetchall()]
        rel = [f[len(root) + 1:] for f in files]
    else:
        base = Path(root)
        files = sorted(str(p) for p in base.rglob("*.csv"))
        rel = [Path(f).relative_to(base).as_posix() for f in files]
    tables: dict[str, list[str]] = {}
    for full, r in zip(files, rel):
        table = r.split("/")[0].removesuffix(".csv")
        tables.setdefault(table, []).append(full)
    return {t: sorted(v) for t, v in tables.items()}


def read_headers(settings: Settings, files: list[str]) -> list[tuple[str, ...]]:
    """First CSV line of each object. S3: one small ranged GET per object, in parallel."""
    def parse(first_line: str) -> tuple[str, ...]:
        return tuple(next(csv.reader([first_line])))

    if not settings.source.startswith("s3://"):
        out = []
        for f in files:
            with open(f, encoding="utf-8-sig", newline="") as fh:
                out.append(parse(fh.readline()))
        return out

    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3", region_name=settings.s3["Region"],
        aws_access_key_id=settings.s3["AccessKeyID"],
        aws_secret_access_key=settings.s3["SecretAccessKey"],
        config=Config(max_pool_connections=32, retries={"max_attempts": 4}))

    def one(uri: str) -> tuple[str, ...]:
        bucket, key = uri[len("s3://"):].split("/", 1)
        body = client.get_object(Bucket=bucket, Key=key, Range="bytes=0-65535")["Body"].read()
        return parse(body.decode("utf-8-sig", errors="replace").splitlines()[0])

    with ThreadPoolExecutor(max_workers=32) as pool:
        return list(pool.map(one, files))


def run(settings: Settings, run_id: str, stats: dict) -> None:
    con = connect(settings)
    settings.bronze.mkdir(parents=True, exist_ok=True)
    found = discover(con, settings)
    missing = [t for t in settings.tables if t not in found]
    if missing:
        raise SystemExit(f"bronze: no CSV objects found for {missing} under the source root")

    for table in settings.tables:
        files = found[table]
        t0 = time.perf_counter()
        out = settings.bronze / f"{table}.parquet"
        # Store paths relative to the source root so bucket names never reach outputs.
        root = settings.source.rstrip("/").replace("\\", "/")
        if not root.startswith("s3://"):
            root = str(Path(root)).replace("\\", "/")  # rglob() paths start with this exact prefix
        source_expr = f"substr(replace(filename, '\\', '/'), {len(root) + 2})"

        # Schema evolution without union_by_name over every file (40x slower):
        # group objects by their exact header, read each group positionally-safe,
        # then union the groups by column name.
        groups: dict[tuple[str, ...], list[str]] = {}
        for f, header in zip(files, read_headers(settings, files)):
            groups.setdefault(header, []).append(f)
        parts = []
        for header, members in groups.items():
            file_list = "[" + ", ".join(f"'{sql_path(f)}'" for f in members) + "]"
            columns = "{" + ", ".join("'" + c.replace("'", "''") + "': 'VARCHAR'" for c in header) + "}"
            # Header is already known, so skip per-file sniffing: explicit columns, all text.
            parts.append(f"""SELECT * FROM read_csv({file_list}, header = true, auto_detect = false,
                                    columns = {columns}, delim = ',', quote = '"', escape = '"',
                                    union_by_name = false, filename = true, hive_partitioning = false)""")
        con.execute(f"""
            COPY (
                SELECT * EXCLUDE (filename),
                       {source_expr} AS _source_file,
                       TRY_CAST(regexp_replace(
                           regexp_extract(replace(filename, '\\', '/'), '{PART_RE}'),
                           '{PART_RE}', '\\1-\\2-\\3') AS DATE) AS _partition_date,
                       '{run_id}' AS _run_id,
                       now()::TIMESTAMP AS _ingested_at
                FROM ({" UNION ALL BY NAME ".join(parts)})
            ) TO '{sql_path(out)}' (FORMAT parquet, COMPRESSION zstd)
        """)
        cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM '{sql_path(out)}'").fetchall()]
        rows, files_with_rows = con.execute(
            f"SELECT count(*), count(DISTINCT _source_file) FROM '{sql_path(out)}'").fetchone()
        stats.setdefault(table, {})["bronze"] = {
            "source_objects": len(files),
            "source_objects_with_rows": files_with_rows,
            "rows": rows,
            "schema_variants": len(groups),
            "columns": [c for c in cols if not c.startswith("_")],
            "seconds": round(time.perf_counter() - t0, 1),
        }
        print(f"bronze  {table:<26} {rows:>11,} rows from {len(files):>5} objects "
              f"({stats[table]['bronze']['seconds']}s)", flush=True)
