"""Bronze: land raw CSVs as Parquet, untouched except for lineage columns.

Everything is read as VARCHAR so nothing is silently coerced or dropped here;
typing and rejection happen in silver where they are counted.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from .common import Settings, connect, sql_path

PART_RE = r"year=(\d{4})/month=(\d{2})/day=(\d{2})"


def s3_client(settings: Settings, pool: int = 32):
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3", region_name=settings.s3["Region"],
        aws_access_key_id=settings.s3["AccessKeyID"],
        aws_secret_access_key=settings.s3["SecretAccessKey"],
        config=Config(max_pool_connections=pool, retries={"max_attempts": 4}))


def list_objects(settings: Settings) -> list[dict]:
    """Every CSV object under the source root with version metadata.

    Returns dicts: uri (full, internal only), key (relative to root, safe to publish),
    bytes, etag (S3 ETag, or sha256 for local files), last_modified.
    """
    root = settings.source.rstrip("/")
    out = []
    if root.startswith("s3://"):
        bucket, _, prefix = root[len("s3://"):].partition("/")
        prefix = prefix.rstrip("/") + "/" if prefix else ""
        pages = s3_client(settings).get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for page in pages:
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".csv"):
                    out.append({"uri": f"s3://{bucket}/{obj['Key']}", "key": obj["Key"][len(prefix):],
                                "bytes": obj["Size"], "etag": obj["ETag"].strip('"'),
                                "last_modified": obj["LastModified"].isoformat(timespec="seconds")})
    else:
        base = Path(root)
        for p in sorted(base.rglob("*.csv")):
            st = p.stat()
            out.append({"uri": str(p), "key": p.relative_to(base).as_posix(), "bytes": st.st_size,
                        "etag": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()[:32],
                        "last_modified": datetime.fromtimestamp(st.st_mtime, timezone.utc)
                        .isoformat(timespec="seconds")})
    return sorted(out, key=lambda o: o["key"])


def table_of(key: str) -> str:
    """Same naming rule as scripts/profile_s3.py: first path segment minus a trailing '.csv'."""
    return key.split("/")[0].removesuffix(".csv")


def fingerprint(objects: list[dict]) -> str:
    """Identifies exactly which source object versions a build read."""
    h = hashlib.sha256()
    for o in sorted(objects, key=lambda o: o["key"]):
        h.update(f"{o['key']}|{o['etag']}|{o['bytes']}\n".encode())
    return h.hexdigest()[:16]


def discover(con, settings: Settings) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    for o in list_objects(settings):
        tables.setdefault(table_of(o["key"]), []).append(o)
    return tables


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

    client = s3_client(settings)

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

    inventory = {t: [{k: o[k] for k in ("key", "bytes", "etag", "last_modified")} for o in found[t]]
                 for t in settings.tables}
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    (settings.report_dir / "source_objects.json").write_text(json.dumps({
        "run_id": run_id,
        "note": "Exact source object versions read by this build. Keys are relative to the "
                "source root; the bucket name is intentionally omitted.",
        "fingerprint": fingerprint([o for objs in found.values() for o in objs
                                    if table_of(o["key"]) in settings.tables]),
        "tables": {t: {"fingerprint": fingerprint(found[t]), "objects": inventory[t]}
                   for t in settings.tables},
    }, indent=1) + "\n", encoding="utf-8")
    stats["_source_fingerprint"] = fingerprint([o for t in settings.tables for o in found[t]])

    for table in settings.tables:
        files = [o["uri"] for o in found[table]]
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
            "source_bytes": sum(o["bytes"] for o in found[table]),
            "source_fingerprint": fingerprint(found[table]),
            "source_objects_with_rows": files_with_rows,
            "rows": rows,
            "schema_variants": len(groups),
            "columns": [c for c in cols if not c.startswith("_")],
            "seconds": round(time.perf_counter() - t0, 1),
        }
        print(f"bronze  {table:<26} {rows:>11,} rows from {len(files):>5} objects "
              f"({stats[table]['bronze']['seconds']}s)", flush=True)
