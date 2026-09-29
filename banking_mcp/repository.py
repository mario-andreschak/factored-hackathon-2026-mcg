"""Bounded Parquet reads, owner checks, and conditional source read-back."""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
import threading
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import duckdb

from pipeline.common import bucket_for, load_env, sql_path
from .config import Config
from .security import BankError, Principal, StateStore

BUILD_ID = re.compile(r"[A-Za-z0-9_-]{1,96}")
SOURCE_KEY = re.compile(r"transactions/year=\d{4}/month=\d{2}/day=\d{2}/[^/]+\.csv")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
FIELDS = ("transaction_id", "product_id", "transaction_date", "process_date", "amount", "currency",
          "transaction_status", "merchant_name", "transaction_type", "channel", "_source_file", "_row_hash")


class Snapshot:
    def __init__(self, build: Path, con):
        self.build, self.id = build, build.name
        self.gold = build / "gold" / "transactions_by_customer"
        if not self.gold.is_dir():
            raise BankError("dataset_unavailable")
        # The published inventory distinguishes a legitimate empty bucket from a
        # missing file. Legacy builds without it must be rebuilt before serving.
        manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            raise BankError("dataset_unavailable")
        files = manifest.get("gold_files")
        if not isinstance(files, dict) or not files or manifest.get("build_id") != self.id:
            raise BankError("dataset_unavailable")
        self.bucket_files: dict[int, dict[Path, int]] = {}
        for relative, size in files.items():
            if not isinstance(relative, str) or type(size) is not int or size < 0:
                raise BankError("dataset_unavailable")
            file = (build / "gold" / relative).resolve()
            if ((build / "gold").resolve() not in file.parents or not file.is_file()
                or file.suffix != ".parquet" or file.stat().st_size != size):
                raise BankError("dataset_unavailable")
            matched = re.fullmatch(r"transactions_by_customer/bucket=(\d+)/([^/]+\.parquet)", relative)
            if matched:
                self.bucket_files.setdefault(int(matched[1]), {})[file] = size
        if not self.bucket_files:
            raise BankError("dataset_unavailable")
        cur = con.cursor()
        try:
            self.customers = frozenset(r[0] for r in cur.execute(
                f"SELECT customer_id FROM read_parquet('{sql_path(build / 'silver' / 'customers.parquet')}')"
            ).fetchall())
            products = cur.execute(
                f"SELECT product_id, customer_id, product_type FROM read_parquet("
                f"'{sql_path(build / 'silver' / 'products.parquet')}')").fetchall()
            self.products = {p: (c, typ) for p, c, typ in products}
        finally:
            cur.close()
        lineage = build / "source_objects.json"
        self.objects = {}
        if lineage.is_file():
            for table in json.loads(lineage.read_text(encoding="utf-8"))["tables"].values():
                self.objects.update({o["key"]: o for o in table["objects"]})
        days = []
        for key in self.objects:
            if SOURCE_KEY.fullmatch(key):
                days.append(date.fromisoformat("-".join(re.search(
                    r"year=(\d{4})/month=(\d{2})/day=(\d{2})", key).groups())))
        if not days:
            raise BankError("dataset_unavailable")
        self.first_date, self.last_date = min(days), max(days)


class Repository:
    def __init__(self, config: Config, store: StateStore):
        self.config, self.store = config, store
        self.con = duckdb.connect()
        self.con.execute("SET threads=2")
        self.con.execute("SET memory_limit='1GB'")
        self._lock = threading.Lock()
        self._snapshot = None

    def close(self):
        with self._lock:
            if self.con is not None:
                self.con.close()
                self.con = None
            self._snapshot = None

    def snapshot(self) -> Snapshot:
        try:
            build_id = (self.config.data_dir / "CURRENT").read_text(encoding="utf-8").strip()
            if not BUILD_ID.fullmatch(build_id):
                raise BankError("dataset_unavailable")
            builds = (self.config.data_dir / "builds").resolve()
            build = (builds / build_id).resolve()
            if build.parent != builds:
                raise BankError("dataset_unavailable")
            with self._lock:
                if self.con is None:
                    raise BankError("dataset_unavailable")
                if self._snapshot is None or self._snapshot.id != build_id:
                    self._snapshot = Snapshot(build, self.con)
                return self._snapshot
        except (OSError, ValueError, KeyError, duckdb.Error):
            raise BankError("dataset_unavailable") from None

    def _rows(self, snapshot: Snapshot, principal: Principal, where: str, params: list,
              limit: int) -> list[dict]:
        if principal.customer not in snapshot.customers:
            raise BankError("authorization_denied")
        path = snapshot.gold / f"bucket={bucket_for(principal.customer)}"
        expected = snapshot.bucket_files.get(bucket_for(principal.customer), {})
        try:
            present = {p.resolve() for p in path.glob("*.parquet")}
            if present != set(expected) or any(p.stat().st_size != size for p, size in expected.items()):
                raise BankError("dataset_unavailable")
        except OSError:
            raise BankError("dataset_unavailable") from None
        if not expected:
            return []
        if self.con is None:
            raise BankError("dataset_unavailable")
        cur = self.con.cursor()
        try:
            files = "[" + ", ".join(f"'{sql_path(p)}'" for p in sorted(expected)) + "]"
            cur.execute(f"SELECT {', '.join(FIELDS)} FROM read_parquet({files}) "
                        f"WHERE customer_id=? AND ownership_valid AND ({where}) "
                        "ORDER BY transaction_date DESC, transaction_id DESC LIMIT ?",
                        [principal.customer, *params, limit])
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
        except (OSError, duckdb.Error):
            raise BankError("dataset_unavailable") from None
        finally:
            cur.close()
        # Repeat owner checks independently of the materialized ownership_valid flag.
        if any(snapshot.products.get(r["product_id"], (None,))[0] != principal.customer for r in rows):
            raise BankError("data_quality_error")
        return rows

    def _visible(self, row: dict, snapshot: Snapshot) -> dict:
        ref = hmac.new(self.config.service_token.encode(), row["transaction_id"].encode(),
                       hashlib.sha256).hexdigest()[:12]
        return {
            "transaction_reference": "txn_" + ref,
            "transaction_date": row["transaction_date"].isoformat(),
            "process_date": row["process_date"].isoformat(),
            "amount": str(row["amount"]), "currency": row["currency"],
            "status": row["transaction_status"],
            "merchant": (row["merchant_name"] or "")[:160] or None,
            "transaction_type": (row["transaction_type"] or "")[:80],
            "channel": (row["channel"] or "")[:80],
            "product": (snapshot.products[row["product_id"]][1] or "")[:80],
        }

    def list_transactions(self, principal: Principal, start_date: str | None, end_date: str | None,
                          limit: int, cursor: str | None) -> dict:
        snapshot = self.snapshot()
        start = date.fromisoformat(start_date) if start_date else max(snapshot.first_date, snapshot.last_date - timedelta(days=30))
        end = date.fromisoformat(end_date) if end_date else snapshot.last_date
        if end < start or (end - start).days > 30 or start < snapshot.first_date or end > snapshot.last_date:
            raise BankError("invalid_date_window")
        where, params = "process_date BETWEEN ? AND ?", [start, end]
        if cursor:
            data = self.store.get(cursor, "cursor", principal)
            if data["build"] != snapshot.id or data["start"] != start.isoformat() or data["end"] != end.isoformat():
                raise BankError("reference_unavailable")
            where += " AND (transaction_date < ?::TIMESTAMP OR (transaction_date = ?::TIMESTAMP AND transaction_id < ?))"
            params += [data["date"], data["date"], data["id"]]
        rows = self._rows(snapshot, principal, where, params, limit + 1)
        items = []
        for row in rows[:limit]:
            handle = self.store.put("selection", principal, {"build": snapshot.id, "id": row["transaction_id"]})
            items.append({**self._visible(row, snapshot), "selection_handle": handle})
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = self.store.put("cursor", principal, {
                "build": snapshot.id, "start": start.isoformat(), "end": end.isoformat(),
                "date": last["transaction_date"].isoformat(), "id": last["transaction_id"]})
        return {"transactions": items, "next_cursor": next_cursor,
                "date_window": {"start": start.isoformat(), "end": end.isoformat(), "basis": "process_date"},
                "snapshot": snapshot.id, "freshness": "derived_snapshot", "read_only": True}

    def get_transaction(self, principal: Principal, handle: str, verify_source: bool) -> dict:
        snapshot = self.snapshot()
        data = self.store.get(handle, "selection", principal)
        if data["build"] != snapshot.id:
            raise BankError("reference_unavailable")
        rows = self._rows(snapshot, principal, "transaction_id=?", [data["id"]], 2)
        if len(rows) != 1:
            raise BankError("reference_unavailable")
        row = rows[0]
        freshness = "derived_snapshot"
        if verify_source:
            self._verify_source(snapshot, principal, row)
            freshness = "verified_against_pinned_source"
        return {"transaction": self._visible(row, snapshot), "snapshot": snapshot.id,
                "freshness": freshness, "read_only": True}

    def owned_transaction_id(self, principal: Principal, transaction_id: str, build: str) -> tuple[Snapshot, dict]:
        """Host-only exact target resolution; ownership and CURRENT are rechecked."""
        snapshot = self.snapshot()
        if snapshot.id != build:
            raise BankError("snapshot_changed")
        rows = self._rows(snapshot, principal, "transaction_id=?", [transaction_id], 2)
        if len(rows) != 1:
            raise BankError("reference_unavailable")
        return snapshot, rows[0]

    def _verify_source(self, snapshot: Snapshot, principal: Principal, row: dict):
        if self.config.source_env is None:
            raise BankError("source_verification_unavailable")
        key = row["_source_file"]
        if not SOURCE_KEY.fullmatch(key) or key not in snapshot.objects:
            raise BankError("source_verification_unavailable")
        env = load_env(self.config.source_env)
        import boto3
        from botocore.config import Config as AwsConfig
        client = boto3.client("s3", region_name=env["Region"],
                              aws_access_key_id=env["AccessKeyID"], aws_secret_access_key=env["SecretAccessKey"],
                              config=AwsConfig(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}))
        try:
            # The snapshot's customer/product maps are usable only while both source objects match.
            for master in ("customers.csv", "products.csv"):
                obj = snapshot.objects[master]
                client.head_object(Bucket=env["BucketName"], Key="data/" + master, IfMatch=obj["etag"])
            obj = snapshot.objects[key]
            if obj["bytes"] > MAX_SOURCE_BYTES:
                raise BankError("source_verification_unavailable")
            response = client.get_object(Bucket=env["BucketName"], Key="data/" + key, IfMatch=obj["etag"])
            body = response["Body"]
            try:
                raw = body.read(MAX_SOURCE_BYTES + 1)
            finally:
                body.close()
            if len(raw) > MAX_SOURCE_BYTES:
                raise BankError("source_verification_unavailable")
            matches = [r for r in csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
                       if r.get("transaction_id") == row["transaction_id"]]
            if len(matches) != 1 or matches[0].get("customer_id") != principal.customer or matches[0].get("product_id") != row["product_id"]:
                raise BankError("reference_unavailable")
            source = matches[0]
            if (Decimal(source["amount"]) != row["amount"]
                or datetime.fromisoformat(source["transaction_date"]) != row["transaction_date"]
                or date.fromisoformat(source["process_date"]) != row["process_date"]
                or any(
                (source.get(k) or "").strip() != (row[k] or "")
                for k in ("currency", "transaction_status", "merchant_name", "transaction_type", "channel")
            )):
                raise BankError("snapshot_changed")
        except BankError:
            raise
        except Exception:
            # Source keys, AWS errors and record content never reach the model or browser.
            raise BankError("source_verification_unavailable") from None
        finally:
            client.close()
