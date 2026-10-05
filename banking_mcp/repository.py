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

from pipeline.bronze import fingerprint
from pipeline.common import bucket_for, load_env, sql_path, transaction_event_dates
from .config import Config
from .security import BankError, Principal, StateStore

BUILD_ID = re.compile(r"[A-Za-z0-9_-]{1,96}")
SOURCE_KEY = re.compile(r"transactions/year=\d{4}/month=\d{2}/day=\d{2}/[^/]+\.csv")
MAX_SOURCE_BYTES = 8 * 1024 * 1024
SEARCH_CALENDAR_DAYS = 90
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
        inventory = json.loads(lineage.read_text(encoding="utf-8"))
        if not isinstance(inventory, dict):
            raise BankError("dataset_unavailable")
        tables = inventory.get("tables")
        if not isinstance(tables, dict) or not {"customers", "products", "transactions"}.issubset(tables):
            raise BankError("dataset_unavailable")
        self.objects = {}
        for name, table in tables.items():
            if not isinstance(name, str) or not isinstance(table, dict) or not isinstance(table.get("objects"), list):
                raise BankError("dataset_unavailable")
            objects = table["objects"]
            for obj in objects:
                if (not isinstance(obj, dict) or not isinstance(obj.get("key"), str)
                    or type(obj.get("bytes")) is not int or obj["bytes"] < 0
                    or not isinstance(obj.get("etag"), str) or not obj["etag"]
                    or obj["key"] in self.objects
                    or obj["key"].split("/")[0].removesuffix(".csv") != name):
                    raise BankError("dataset_unavailable")
                self.objects[obj["key"]] = obj
            if table.get("fingerprint") != fingerprint(objects):
                raise BankError("dataset_unavailable")
        self.source_fingerprint = fingerprint(list(self.objects.values()))
        if (inventory.get("fingerprint") != self.source_fingerprint
            or manifest.get("source_fingerprint") != self.source_fingerprint
            or manifest.get("source_validation") != inventory.get("source_validation", "legacy_inventory")
            or not {"customers.csv", "products.csv"}.issubset(self.objects)):
            raise BankError("dataset_unavailable")
        quality = json.loads((build / "manifest.json").read_text(encoding="utf-8"))
        if (not isinstance(quality, dict) or quality.get("run_id") != self.id or quality.get("source_fingerprint") != self.source_fingerprint
            or quality.get("source_validation") != manifest.get("source_validation")
            or quality.get("published") is not True or quality.get("contract_failures") != []):
            raise BankError("dataset_unavailable")
        cur = con.cursor()
        try:
            serving = sorted(file for bucket in self.bucket_files.values() for file in bucket)
            paths = "[" + ", ".join(f"'{sql_path(p)}'" for p in serving) + "]"
            # An ownership flag alone cannot justify the snapshot-wide anchor.
            # Repeat the customer/product relationship before deriving its range.
            bad_owners = cur.execute(
                f"SELECT count(*) FROM read_parquet({paths}) t "
                f"LEFT JOIN read_parquet('{sql_path(build / 'silver' / 'customers.parquet')}') c "
                "ON c.customer_id=t.customer_id "
                f"LEFT JOIN read_parquet('{sql_path(build / 'silver' / 'products.parquet')}') p "
                "ON p.product_id=t.product_id WHERE t.ownership_valid "
                "AND (c.customer_id IS NULL OR p.product_id IS NULL OR p.customer_id IS DISTINCT FROM t.customer_id)"
            ).fetchone()[0]
            source_keys = [r[0] for r in cur.execute(
                f"SELECT DISTINCT _source_file FROM read_parquet({paths}) WHERE ownership_valid").fetchall()]
            if bad_owners or any(not isinstance(key, str) or not SOURCE_KEY.fullmatch(key)
                                 or key not in self.objects for key in source_keys):
                raise BankError("dataset_unavailable")
            dates = transaction_event_dates(cur, serving)
        finally:
            cur.close()
        if not dates["ownership_valid_rows"] or dates["missing_event_dates"] or not dates["first"] or not dates["last"]:
            raise BankError("dataset_unavailable")
        # Legacy pinned snapshots can derive this from their validated serving
        # rows. A supplied aggregate must describe those same rows and lineage.
        recorded = manifest.get("transaction_event_dates")
        if recorded is not None and (not isinstance(recorded, dict)
            or type(recorded.get("ownership_valid_rows")) is not int
            or type(recorded.get("missing_event_dates")) is not int
            or recorded != {**dates, "source_fingerprint": self.source_fingerprint}):
            raise BankError("dataset_unavailable")
        self.first_date, self.last_date = date.fromisoformat(dates["first"]), date.fromisoformat(dates["last"])
        self.event_dates = {key: dates[key] for key in ("first", "last", "basis", "calendar")}


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
        except (OSError, ValueError, KeyError, TypeError, duckdb.Error):
            raise BankError("dataset_unavailable") from None

    def assert_current_snapshot(self, expected_build: str) -> None:
        """Recheck the published pointer immediately before a local write.

        This is a point-in-time check. Saved receipts retain their original
        snapshot; a later publication does not rewrite their provenance.
        No Parquet, S3 or provider work runs under the SQLite writer gate.
        """
        try:
            current = (self.config.data_dir / "CURRENT").read_text(encoding="utf-8").strip()
            if not BUILD_ID.fullmatch(current):
                raise BankError("dataset_unavailable")
        except (OSError, UnicodeError):
            raise BankError("dataset_unavailable") from None
        if current != expected_build:
            raise BankError("snapshot_changed")

    def owned_card(self, principal: Principal, product_id: str, build: str) -> dict:
        """Resolve an exact owned card; callers cannot choose another customer."""
        snapshot = self.snapshot()
        if snapshot.id != build:
            raise BankError("snapshot_changed")
        owner = snapshot.products.get(product_id)
        if principal.customer not in snapshot.customers or not owner or owner[0] != principal.customer:
            raise BankError("authorization_denied")
        if owner[1] not in {"Tarjeta Crédito", "Tarjeta Débito"}:
            raise BankError("card_required")
        with self._lock:
            if self.con is None:
                raise BankError("dataset_unavailable")
            rows = self.con.execute("SELECT product_type,currency,product_status FROM read_parquet(?) "
                "WHERE product_id=? AND customer_id=?", [str(snapshot.build / "silver/products.parquet"),
                product_id, principal.customer]).fetchall()
        if len(rows) != 1 or rows[0][2] != "Active":
            raise BankError("card_unavailable")
        return {"type": rows[0][0], "currency": rows[0][1], "source_status": rows[0][2]}

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
        if any(not isinstance(r["transaction_date"], datetime) or not isinstance(r["process_date"], date)
               for r in rows):
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
        # A partial request needs clarification. Only omission of both dates
        # chooses the snapshot default; explicit dates are never shifted.
        if (start_date is None) != (end_date is None):
            raise BankError("invalid_date_window")
        try:
            for value in (start_date, end_date):
                if value is not None and (not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)):
                    raise ValueError("calendar date required")
            if start_date is None:
                start = max(snapshot.first_date, snapshot.last_date - timedelta(days=SEARCH_CALENDAR_DAYS - 1))
                end = snapshot.last_date
            else:
                start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
        except ValueError:
            raise BankError("invalid_date_window") from None
        except OverflowError:
            raise BankError("dataset_unavailable") from None
        if (end < start or (end - start).days >= SEARCH_CALENDAR_DAYS
            or start < snapshot.first_date or end > snapshot.last_date):
            raise BankError("invalid_date_window")
        where, params = "transaction_date::DATE BETWEEN ? AND ?", [start, end]
        if cursor:
            data = self.store.get(cursor, "cursor", principal)
            if (data["build"] != snapshot.id or data["start"] != start.isoformat() or data["end"] != end.isoformat()
                or data.get("basis") != "transaction_date" or data.get("anchor") != snapshot.last_date.isoformat()):
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
                "basis": "transaction_date", "anchor": snapshot.last_date.isoformat(),
                "date": last["transaction_date"].isoformat(), "id": last["transaction_id"]})
        return {"transactions": items, "next_cursor": next_cursor,
                "date_window": {"start": start.isoformat(), "end": end.isoformat(), "basis": "transaction_date",
                                "calendar": "source_timestamp_calendar_date", "anchor": snapshot.last_date.isoformat(),
                                "max_calendar_days": SEARCH_CALENDAR_DAYS},
                "snapshot_event_dates": dict(snapshot.event_dates),
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
