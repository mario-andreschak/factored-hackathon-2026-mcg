"""Shared helpers: config, DuckDB connection, contracts, stable hashing."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import yaml

PIPELINE_VERSION = "0.1.0"
CONTRACTS_PATH = Path(__file__).with_name("contracts.yaml")
TXN_BUCKETS = 128  # transactions_by_customer fan-out; must match lookup.bucket_for()


@dataclass
class Settings:
    source: str                   # "s3://bucket/data" or a local folder with the same layout
    out_dir: Path                 # local, git-ignored (data/)
    report_dir: Path              # committed, aggregates only (docs/pipeline/)
    tables: list[str]
    s3: dict[str, str] = field(default_factory=dict)
    threads: int | None = None
    memory_limit: str | None = None
    build_id: str | None = None       # silver/gold/quarantine of this run live in builds/<build_id>/

    # bronze is a shared raw landing area; everything derived from it is written into an
    # isolated build directory and only becomes visible through publish() (see below).
    @property
    def bronze(self) -> Path: return self.out_dir / "bronze"
    @property
    def build_dir(self) -> Path:
        if not self.build_id:
            raise RuntimeError("build_id not set")
        return self.out_dir / "builds" / self.build_id
    @property
    def silver(self) -> Path: return self.build_dir / "silver"
    @property
    def quarantine(self) -> Path: return self.build_dir / "quarantine"
    @property
    def gold(self) -> Path: return self.build_dir / "gold"


# --- published snapshot ----------------------------------------------------------------
# data/CURRENT holds the id of the last build that passed every contract. It is replaced
# atomically (write temp file + os.replace), so a reader sees either the old or the new
# build, never a half-written one. Builds are immutable once written; a failed build is
# never published, so the previous good snapshot keeps serving.
KEEP_BUILDS = 3


def current_build(out_dir: Path | str) -> Path:
    out_dir = Path(out_dir)
    pointer = out_dir / "CURRENT"
    if not pointer.exists():
        raise FileNotFoundError(f"no published build under {out_dir} (run: python -m pipeline run)")
    build = out_dir / "builds" / pointer.read_text(encoding="utf-8").strip()
    if not build.is_dir():
        raise FileNotFoundError(f"{pointer} points to a missing build: {build}")
    return build


def current_gold(out_dir: Path | str) -> Path:
    return current_build(out_dir) / "gold"


def current_silver(out_dir: Path | str) -> Path:
    return current_build(out_dir) / "silver"


def publish(out_dir: Path | str, build_id: str) -> None:
    import os
    import shutil
    out_dir = Path(out_dir)
    if not (out_dir / "builds" / build_id).is_dir():
        raise FileNotFoundError(build_id)
    tmp = out_dir / f"CURRENT.{build_id}.tmp"
    tmp.write_text(build_id, encoding="utf-8")
    os.replace(tmp, out_dir / "CURRENT")
    # Prune old builds, never the published one. Readers resolve CURRENT per request, so
    # a snapshot is only removed after KEEP_BUILDS newer builds exist.
    builds = sorted((p for p in (out_dir / "builds").iterdir() if p.is_dir()),
                    key=lambda p: p.name, reverse=True)
    for old in builds[KEEP_BUILDS:]:
        if old.name != build_id:
            shutil.rmtree(old, ignore_errors=True)


def load_env(path: Path) -> dict[str, str]:
    """Same format as scripts/profile_s3.py (BucketName, Region, AccessKeyID, SecretAccessKey)."""
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    missing = {"BucketName", "Region", "AccessKeyID", "SecretAccessKey"} - values.keys()
    if missing:
        raise ValueError(f"{path} is missing: {', '.join(sorted(missing))}")
    return values


def load_contracts() -> dict:
    return yaml.safe_load(CONTRACTS_PATH.read_text(encoding="utf-8"))["tables"]


def contracts_digest() -> str:
    return hashlib.sha256(CONTRACTS_PATH.read_bytes()).hexdigest()[:12]


def connect(settings: Settings) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    if settings.threads:
        con.execute(f"SET threads = {int(settings.threads)}")
    if settings.memory_limit:
        con.execute(f"SET memory_limit = '{settings.memory_limit}'")
    con.execute("SET preserve_insertion_order = false")
    if settings.source.startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        # Credentials go into a temporary in-memory secret; never logged or written.
        con.execute(
            "CREATE OR REPLACE TEMPORARY SECRET datathon_s3 "
            "(TYPE s3, KEY_ID '{k}', SECRET '{s}', REGION '{r}')".format(
                k=_q(settings.s3["AccessKeyID"]),
                s=_q(settings.s3["SecretAccessKey"]),
                r=_q(settings.s3["Region"]),
            )
        )
    return con


def _q(value: str) -> str:
    return value.replace("'", "''")


def sql_path(p: Path | str) -> str:
    """Forward-slash path literal that works on Windows and in DuckDB."""
    return str(p).replace("\\", "/").replace("'", "''")


def ident(name: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError(f"unsafe identifier: {name}")
    return f'"{name}"'


def bucket_for(customer_id: str, buckets: int = TXN_BUCKETS) -> int:
    """Stable across processes, languages and DuckDB versions (unlike hash())."""
    return int(hashlib.md5(customer_id.encode("utf-8")).hexdigest()[:8], 16) % buckets


def sql_bucket(col: str, buckets: int) -> str:
    """SQL twin of bucket_for(); verified equal in tests."""
    return f"(('0x' || substr(md5({col}), 1, 8))::UBIGINT % {int(buckets)})::INTEGER"
