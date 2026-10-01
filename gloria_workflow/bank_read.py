"""Admitted host-only banking reads over the authoritative MCP source and ledger.

No model selector supplies a principal and this port has no action/write method.
Pinned raw records and risk signals remain inside the application; returned
transaction identities use the frontend's customer-bound opaque references.
"""
from __future__ import annotations

import asyncio
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time
import unicodedata

import duckdb

from banking_mcp.actions import ACTION
from banking_mcp.security import BankError, Principal
from pipeline.common import bucket_for, load_env


MAX_OWNED_ROWS = 10000
MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_TABLE_BYTES = 512 * 1024 * 1024
MAX_SOURCE_OBJECTS = 2048
MAX_RATE_BYTES = 4 * 1024 * 1024
MAX_RATE_ROWS = 100000
_TABLES = {"customers", "products", "transactions", "complaints", "call_center_interactions"}
_CLOSED = {"closed", "resolved", "cancelled", "canceled", "rejected"}
_OPEN = {"open", "inprocess", "escalated"}


def assert_bank_principal(service, principal: Principal) -> None:
    """Join server-derived admission to the MCP's private immutable mapping."""
    if (not isinstance(principal, Principal) or service.config.mode != "delegated"
            or service.config.principal_customers.get(principal.subject) != principal.customer):
        raise BankError("authorization_denied")
    service.auth.assert_current(principal)
    service.store.bind_session(principal)
    service.auth.assert_current(principal)


def _norm(value):
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", str(value or ""))
                            if not unicodedata.combining(c)).casefold().split())


_PRODUCT_WORDS = {
    "tarjeta": "card", "tarjetas": "card", "cartao": "card", "cartoes": "card",
    "cuenta": "account", "cuentas": "account", "conta": "account", "contas": "account",
    "credito": "credit", "debito": "debit",
    "ahorro": "savings", "ahorros": "savings", "poupanca": "savings",
    "corriente": "current", "corrientes": "current", "corrente": "current", "correntes": "current",
}
_PRODUCT_CONNECTORS = {"de", "del", "do", "da", "la", "el", "o", "a"}


def _product_features(value):
    words = [word for word in re.findall(r"\w+", _norm(value)) if word not in _PRODUCT_CONNECTORS]
    if not words or any(word not in _PRODUCT_WORDS for word in words):
        return None
    return frozenset(_PRODUCT_WORDS[word] for word in words)


def _matches_product_hint(hint, product_type):
    # Translate only recognized ES/PT product words. Keep every supplied type
    # qualifier: a debit hint cannot select a credit card, and unknown words
    # cannot be discarded to turn an unavailable product into a sole match.
    requested, available = _product_features(hint), _product_features(product_type)
    return requested is not None and available is not None and requested <= available


def _number(value, *, maximum=None, signed=False):
    try:
        if value in (None, "") or isinstance(value, bool):
            return None
        result = Decimal(str(value))
        if not result.is_finite() or not signed and result < 0 or maximum is not None and result > maximum:
            return None
        return result
    except (InvalidOperation, ValueError, TypeError):
        return None


def _utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


class OwnedBankReads:
    def __init__(self, service, public_repository, principal: Principal, *, source_root=None,
                 guard=None, clock=None, duplicate_minutes=2):
        self.service, self.repository = service, service.repository
        self.public_repository, self.principal = public_repository, principal
        if public_repository.settings.data_dir.resolve() != service.config.data_dir.resolve():
            raise ValueError("inquiry repositories must share a dataset")
        self.source_root = Path(source_root).resolve() if source_root is not None else None
        self.guard = guard
        self.clock = clock or time.time
        if duplicate_minutes != 2:
            raise ValueError("canonical nearby duplicate window must be two minutes")
        self.duplicate_minutes = duplicate_minutes
        self._snapshot_id = None
        self._fence()

    def _fence(self):
        if self.guard:
            self.guard()
        assert_bank_principal(self.service, self.principal)

    def _query(self, sql, params):
        cursor = self.repository.con.cursor()
        try:
            cursor.execute(sql, params)
            names = [item[0] for item in cursor.description]
            return [dict(zip(names, row)) for row in cursor.fetchall()]
        except duckdb.Error:
            raise BankError("data_unavailable") from None
        finally:
            cursor.close()

    def _ref(self, raw):
        return self.public_repository.reference("txn", self.principal.customer, raw)

    def _snapshot(self):
        snapshot = self.repository.snapshot()
        if self._snapshot_id is not None and snapshot.id != self._snapshot_id:
            raise BankError("snapshot_changed")
        self._snapshot_id = snapshot.id
        return snapshot

    def _source(self, snapshot, key):
        """Read only a declared object, conditionally pinned to this snapshot."""
        obj = snapshot.objects.get(key)
        if not obj or type(obj.get("bytes")) is not int or obj["bytes"] > MAX_SOURCE_BYTES:
            raise BankError("source_verification_unavailable")
        if self.source_root is not None:
            path = (self.source_root / key).resolve()
            if self.source_root not in path.parents:
                raise BankError("source_verification_unavailable")
            try:
                with path.open("rb") as stream:
                    raw = stream.read(MAX_SOURCE_BYTES + 1)
            except OSError:
                raise BankError("source_verification_unavailable") from None
            etag = "sha256:" + hashlib.sha256(raw).hexdigest()[:32]
            if len(raw) != obj["bytes"] or etag != obj["etag"]:
                raise BankError("source_verification_unavailable")
            return raw
        if self.service.config.source_env is None:
            raise BankError("source_verification_unavailable")
        import boto3
        from botocore.config import Config as AwsConfig
        try:
            env = load_env(self.service.config.source_env)
            client = boto3.client("s3", region_name=env["Region"],
                aws_access_key_id=env["AccessKeyID"], aws_secret_access_key=env["SecretAccessKey"],
                config=AwsConfig(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}))
            try:
                response = client.get_object(Bucket=env["BucketName"], Key="data/" + key, IfMatch=obj["etag"])
                body = response["Body"]
                try:
                    raw = body.read(MAX_SOURCE_BYTES + 1)
                finally:
                    body.close()
                if len(raw) != obj["bytes"] or len(raw) > MAX_SOURCE_BYTES:
                    raise BankError("source_verification_unavailable")
                return raw
            finally:
                client.close()
        except BankError:
            raise
        except Exception:
            raise BankError("source_verification_unavailable") from None

    @staticmethod
    def _csv(raw):
        try:
            reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
            if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
                raise ValueError()
            return reader
        except (ValueError, UnicodeError):
            raise BankError("source_verification_unavailable") from None

    def _table_sources(self, snapshot, table):
        if table not in _TABLES:
            raise BankError("invalid_arguments")
        try:
            inventory = json.loads((snapshot.build / "source_objects.json").read_text(encoding="utf-8"))
            table_inventory = inventory["tables"][table]
            objects = table_inventory["objects"]
            if (not isinstance(objects, list) or len(objects) > MAX_SOURCE_OBJECTS
                    or sum(item["bytes"] for item in objects) > MAX_TABLE_BYTES):
                raise ValueError()
            for item in objects:
                if snapshot.objects.get(item["key"]) != item:
                    raise ValueError()
            return objects
        except (KeyError, OSError, ValueError, TypeError):
            raise BankError("data_unavailable") from None

    def _table_complete(self, snapshot, table):
        try:
            manifest = json.loads((snapshot.build / "manifest.json").read_text(encoding="utf-8"))
            stats = manifest["tables"][table]["silver"] if "tables" in manifest else manifest[table]["silver"]
            if stats["quarantined_rows"] != 0:
                raise ValueError()
        except (KeyError, OSError, ValueError, TypeError):
            raise BankError("data_unavailable") from None

    def _products(self, snapshot):
        # Private product numbers are consulted only to derive an owned last-four.
        # They never enter a response, classifier, log or persistent workflow.
        raw = self._source(snapshot, "products.csv")
        owned_source = {}
        for row in self._csv(raw):
            if row.get("customer_id") == self.principal.customer:
                owned_source.setdefault(row.get("product_id"), []).append(row)
        rows = self._query("SELECT product_id,customer_id,product_type,currency,product_status,last_updated "
                           "FROM read_parquet(?) WHERE customer_id=? ORDER BY product_id",
                           [str(snapshot.build / "silver/products.parquet"), self.principal.customer])
        result = {}
        for row in rows:
            if snapshot.products.get(row["product_id"], (None,))[0] != self.principal.customer:
                raise BankError("data_quality_error")
            candidates = [source for source in owned_source.get(row["product_id"], [])
                if all((source.get(key) or "").strip() == (row[key] or "")
                       for key in ("product_type", "currency", "product_status"))
                and datetime.fromisoformat(source["last_updated"]) == row["last_updated"]]
            if not candidates:
                raise BankError("source_verification_unavailable")
            suffixes = {re.sub(r"\D", "", source.get("product_number") or "")[-4:] for source in candidates}
            last4 = next(iter(suffixes)) if len(suffixes) == 1 and len(next(iter(suffixes))) == 4 else None
            result[row["product_id"]] = {**row, "product_last4": last4}
        return result

    def _owned_rows(self, snapshot):
        base = self.repository._rows(snapshot, self.principal, "TRUE", [], MAX_OWNED_ROWS + 1)
        if len(base) > MAX_OWNED_ROWS:
            raise BankError("search_coverage_incomplete")
        bronze, marker, before = self._bronze(snapshot)
        raw_ids = self._query("SELECT DISTINCT trim(transaction_id) AS transaction_id FROM read_parquet(?) "
            "WHERE trim(customer_id)=? LIMIT ?", [str(bronze / "transactions.parquet"), self.principal.customer, MAX_OWNED_ROWS + 1])
        self._bronze_current(bronze, marker, before)
        if ({row["transaction_id"] for row in raw_ids} != {row["transaction_id"] for row in base}
                or len(raw_ids) > MAX_OWNED_ROWS):
            raise BankError("search_coverage_incomplete")
        if not base:
            return []
        extended = self._query("SELECT * FROM read_parquet(?) WHERE customer_id=? AND transaction_id IN (SELECT unnest(?))",
            [str(snapshot.build / "silver/transactions.parquet"), self.principal.customer, [row["transaction_id"] for row in base]])
        by_id = {row["transaction_id"]: row for row in extended}
        if len(by_id) != len(base):
            raise BankError("data_quality_error")
        results = []
        for row in base:
            other = by_id[row["transaction_id"]]
            if (other["product_id"] != row["product_id"] or other["_row_hash"] != row["_row_hash"]
                    or any(other.get(key) != row.get(key) for key in row)):
                raise BankError("data_quality_error")
            results.append(other)
        return results

    def _visible(self, row, snapshot, products):
        native = self.repository._visible(row, snapshot)
        return {"transaction_id": self._ref(row["transaction_id"]),
                "transaction_date": native["transaction_date"], "process_date": native["process_date"],
                "amount": native["amount"], "currency": native["currency"],
                "transaction_status": native["status"], "status": native["status"],
                "transaction_type": native["transaction_type"], "merchant_name": native["merchant"],
                "channel": native["channel"], "transaction_city": row.get("transaction_city"),
                "transaction_country": row.get("transaction_country"), "product": native["product"],
                "product_type": native["product"], "product_last4": products[row["product_id"]]["product_last4"]}

    def resolve_owned_reference(self, reference, *, snapshot_id=None):
        """Trusted host helper; the returned raw row must never be given to a model."""
        self._fence()
        snapshot = self._snapshot()
        if snapshot_id and snapshot.id != snapshot_id:
            raise BankError("snapshot_changed")
        rows = self._owned_rows(snapshot)
        selected = [row for row in rows if self._ref(row["transaction_id"]) == reference]
        if len(selected) != 1:
            raise BankError("reference_unavailable")
        self.repository.assert_current_snapshot(snapshot.id)
        self._fence()
        return snapshot, selected[0]

    def _verify_target(self, snapshot, row):
        self._source(snapshot, "customers.csv")
        source = [item for item in self._csv(self._source(snapshot, row["_source_file"]))
                  if item.get("transaction_id") == row["transaction_id"]
                  and item.get("customer_id") == self.principal.customer
                  and item.get("product_id") == row["product_id"]]
        if not source:
            raise BankError("reference_unavailable")
        try:
            matches = [item for item in source if (Decimal(item["amount"]) == row["amount"]
                    and datetime.fromisoformat(item["transaction_date"]) == row["transaction_date"]
                    and date.fromisoformat(item["process_date"]) == row["process_date"]
                    and all((item.get(key) or "").strip() == (row.get(key) or "") for key in
                        ("currency", "transaction_status", "merchant_name", "transaction_type", "channel", "transaction_city", "transaction_country"))
                    and _number(item.get("fraud_score"), maximum=100) == _number(row.get("fraud_score"), maximum=100)
                    and _number(item.get("amount_usd")) == _number(row.get("amount_usd")))]
            if not matches:
                raise BankError("snapshot_changed")
        except (ValueError, KeyError, TypeError, InvalidOperation):
            raise BankError("source_verification_unavailable") from None

    def _bronze(self, snapshot):
        # Shared bronze is usable only while its completed landing marker is
        # pinned to this serving source inventory. A new landing removes that
        # marker before overwriting files; check it on both sides of the read.
        bronze = self.service.config.data_dir / "bronze"
        try:
            marker = json.loads((bronze / "source_objects.json").read_text(encoding="utf-8"))
            if marker["fingerprint"] != snapshot.source_fingerprint:
                raise ValueError()
            before = (bronze / "transactions.parquet").stat()
        except (OSError, ValueError, KeyError, TypeError):
            raise BankError("duplicate_coverage_unavailable") from None
        return bronze, marker, before

    @staticmethod
    def _bronze_current(bronze, marker, before):
        try:
            after = (bronze / "transactions.parquet").stat()
            if (json.loads((bronze / "source_objects.json").read_text(encoding="utf-8")) != marker
                    or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
                    ):
                raise ValueError()
        except (OSError, ValueError, KeyError, TypeError):
            raise BankError("duplicate_coverage_unavailable") from None

    def _duplicates(self, snapshot, target, rows):
        nearby = [row for row in rows if row["transaction_id"] != target["transaction_id"]
            and row["amount"] == target["amount"] and row["currency"] == target["currency"]
            and abs((row["transaction_date"] - target["transaction_date"]).total_seconds()) <= self.duplicate_minutes * 60]
        bronze, marker, before = self._bronze(snapshot)
        # Include private risk/location columns in a tied-version conflict; a
        # chosen lower scalar must not erase a contradictory persisted version.
        versions = self._query("SELECT DISTINCT TRY_CAST(amount AS DECIMAL(15,2)) AS amount,TRY_CAST(transaction_date AS TIMESTAMP) AS transaction_date,TRY_CAST(process_date AS DATE) AS process_date,trim(product_id) AS product_id,trim(currency) AS currency,trim(transaction_status) AS status,trim(merchant_name) AS merchant,trim(transaction_type) AS type,trim(channel) AS channel,trim(transaction_city) AS city,trim(transaction_country) AS country,trim(transaction_category) AS category,trim(merchant_category) AS merchant_category,trim(branch_id) AS branch_id,trim(response_code) AS response_code,TRY_CAST(is_fraud AS BOOLEAN) AS is_fraud,TRY_CAST(fraud_score AS DECIMAL(5,2)) AS fraud_score,TRY_CAST(amount_usd AS DECIMAL(15,2)) AS amount_usd,_source_file "
            "FROM read_parquet(?) WHERE customer_id=? AND transaction_id=? LIMIT ?",
            [str(bronze / "transactions.parquet"), self.principal.customer, target["transaction_id"], MAX_OWNED_ROWS + 1])
        for key in {row["_source_file"] for row in versions}:
            self._source(snapshot, key)
        self._bronze_current(bronze, marker, before)
        if not versions or len(versions) > MAX_OWNED_ROWS or any(row["process_date"] is None for row in versions):
            raise BankError("duplicate_coverage_unavailable")
        latest = max(row["process_date"] for row in versions if row["process_date"] is not None)
        if latest != target["process_date"]:
            raise BankError("snapshot_changed")
        contents = {tuple(row[key] for key in row if key not in {"_source_file", "process_date"}) for row in versions if row["process_date"] == latest}
        conflicting = len(contents) > 1
        return {"duplicate_signal": "persistent" if nearby or conflicting else "clear",
                "conflicting_duplicate": conflicting,
                "possible_duplicate_of": [self._ref(row["transaction_id"]) for row in nearby[:5]] or None}

    def _historical(self, snapshot):
        self._table_complete(snapshot, "complaints")
        objects = self._table_sources(snapshot, "complaints")
        for obj in objects:
            self._source(snapshot, obj["key"])
        rows = self._query("SELECT complaint_id,customer_id,status,category,subcategory,creation_date,_source_file "
            "FROM read_parquet(?) WHERE customer_id=? ORDER BY creation_date DESC,complaint_id LIMIT ?",
            [str(snapshot.build / "silver/complaints.parquet"), self.principal.customer, MAX_OWNED_ROWS + 1])
        if len(rows) > MAX_OWNED_ROWS:
            raise BankError("history_coverage_incomplete")
        for row in rows:
            source = [item for item in self._csv(self._source(snapshot, row["_source_file"]))
                      if item.get("complaint_id") == row["complaint_id"]]
            if len(source) != 1 or source[0].get("customer_id") != self.principal.customer:
                raise BankError("data_unavailable")
            if any((source[0].get(key) or "").strip() != (row.get(key) or "") for key in ("status", "category", "subcategory")):
                raise BankError("data_unavailable")
        return rows

    @staticmethod
    def _historical_public(row):
        return {"complaint_id": row["complaint_id"], "status": row["status"], "source": "historical_complaints",
                "transaction_id": None, "linkage": "unknown", "created_at": row["creation_date"].isoformat()}

    def _sandbox(self, snapshot):
        with self.service.store.connect() as db:
            if not self.service.actions._coverage(db, self.clock()):
                raise BankError("risk_data_unavailable")
            rows = db.execute("SELECT id,transaction_id,facts FROM sandbox_cases WHERE customer=? AND action=? ORDER BY created_at DESC,id LIMIT ?",
                (self.principal.customer, ACTION, MAX_OWNED_ROWS + 1)).fetchall()
            if len(rows) > MAX_OWNED_ROWS:
                raise BankError("history_coverage_incomplete")
            # A retained attempted/verified preparation is positive evidence
            # that absent case rows cannot establish an empty complaint list.
            preparations = db.execute("SELECT DISTINCT transaction_id,facts FROM action_pending "
                "WHERE customer=? AND action=? LIMIT ?", (self.principal.customer, ACTION, MAX_OWNED_ROWS + 1)).fetchall()
            if len(preparations) > MAX_OWNED_ROWS:
                raise BankError("history_coverage_incomplete")
            for target, facts in preparations:
                try:
                    parsed = json.loads(facts)
                    projection = self.service.actions._case_projection(db, self.principal.customer, target, parsed)
                except (ValueError, TypeError):
                    raise BankError("action_unverified") from None
                if projection["state"] == "action_unverified":
                    raise BankError("action_unverified")
            results = []
            for case_id, transaction_id, facts in rows:
                try:
                    parsed = json.loads(facts)
                except (ValueError, TypeError):
                    raise BankError("action_unverified") from None
                projection = self.service.actions._case_projection(db, self.principal.customer, transaction_id, parsed, pending_uncertain=False)
                if projection["state"] != "verified" or projection["receipt"]["id"] != case_id:
                    raise BankError("action_unverified")
                receipt = projection["receipt"]
                results.append({"complaint_id": case_id, "status": "Open", "source": "sandbox_cases",
                    "transaction_id": self._ref(transaction_id), "linkage": "exact_sandbox", "created_at": receipt["created_at"],
                    "snapshot_id": receipt["snapshot"], "source_verified": True,
                    "transaction": {key: value for key, value in receipt["transaction"].items()
                                    if key != "transaction_reference"}})
            return results

    def _window(self, transaction_id, now):
        with self.service.store.connect() as db:
            prior, receipts_complete = self.service.actions._prior_cases(db, self.principal.customer, transaction_id, now)
            complete = receipts_complete and self.service.actions._coverage(db, now)
        return {"scope": "prototype_sandbox_cases", "window_start": _utc(now - 86400), "window_end": _utc(now),
                "prior_distinct_verified_count": prior if complete else None, "coverage_complete": complete}

    def _usd_risk(self, row):
        """Use exact USD, or a separately pinned event-date conversion.

        The transaction source's supplied amount_usd is an observation; it
        cannot replace the contract's independent event-date rate evidence.
        """
        event_date = row["transaction_date"].date().isoformat()
        if row["currency"] == "USD":
            return abs(row["amount"]), {"source": "exact_usd", "date": event_date, "currency": "USD"}
        config = self.service.config
        if config.event_rates_file is None:
            return None, {"source": "unavailable", "date": event_date, "currency": row["currency"]}
        try:
            with config.event_rates_file.open("rb") as stream:
                raw = stream.read(MAX_RATE_BYTES + 1)
            if len(raw) > MAX_RATE_BYTES or hashlib.sha256(raw).hexdigest() != config.event_rates_sha256:
                raise ValueError()
            reader = self._csv(raw)
            if reader.fieldnames != ["date", "currency", "usd_rate"]:
                raise ValueError()
            rates = {}
            for index, item in enumerate(reader):
                if index >= MAX_RATE_ROWS or set(item) != {"date", "currency", "usd_rate"}:
                    raise ValueError()
                key = (item["date"], item["currency"])
                rate = _number(item["usd_rate"])
                if (not re.fullmatch(r"\d{4}-\d{2}-\d{2}", key[0])
                        or date.fromisoformat(key[0]).isoformat() != key[0]
                        or not re.fullmatch(r"[A-Z]{3}", key[1]) or key in rates
                        or rate is None or rate <= 0):
                    raise ValueError()
                rates[key] = rate
            rate = rates.get((event_date, row["currency"]))
            if rate is None:
                raise ValueError()
            value = abs(row["amount"]) * rate
            if not value.is_finite() or not math.isfinite(float(value)):
                raise ValueError()
            return value, {"source": "pinned_event_rates", "date": event_date,
                "currency": row["currency"], "rates_sha256": config.event_rates_sha256}
        except (OSError, ValueError, TypeError, DecimalException, OverflowError, BankError):
            return None, {"source": "unavailable", "date": event_date, "currency": row["currency"]}

    def _read(self, name, args):
        self._fence()
        snapshot = self._snapshot()
        if args.get("snapshot_id") and args["snapshot_id"] != snapshot.id:
            raise BankError("snapshot_changed")
        if name == "get_customer_profile":
            products = self._products(snapshot)
            customers = self._query("SELECT segment,last_updated FROM read_parquet(?) WHERE customer_id=?",
                [str(snapshot.build / "silver/customers.parquet"), self.principal.customer])
            source = [row for row in self._csv(self._source(snapshot, "customers.csv"))
                if row.get("customer_id") == self.principal.customer and len(customers) == 1
                and datetime.fromisoformat(row["last_updated"]) == customers[0]["last_updated"]]
            if (not source or len({(row.get("first_name"), row.get("segment")) for row in source}) != 1
                    or (source[0].get("segment") or "").strip() != customers[0]["segment"]):
                raise BankError("source_verification_unavailable")
            result = {"status": "ok", "currencies": sorted({row["currency"] for row in products.values()}),
                      "first_name": (source[0].get("first_name") or "")[:80], "segment": customers[0]["segment"],
                      "products": [{"product_id": self.public_repository.reference("prod", self.principal.customer, row["product_id"]),
                          **{key: row[key] for key in ("product_type", "currency", "product_status", "product_last4")}} for row in products.values()]}
        elif name == "search_transactions":
            slots = args.get("slots", {})
            if (slots.get("date_from") is None) != (slots.get("date_to") is None):
                raise BankError("invalid_date_window")
            start = date.fromisoformat(slots["date_from"]) if slots.get("date_from") else max(snapshot.first_date, snapshot.last_date - timedelta(days=89))
            end = date.fromisoformat(slots["date_to"]) if slots.get("date_to") else snapshot.last_date
            if start < snapshot.first_date or end > snapshot.last_date or end < start or (end - start).days >= 90:
                raise BankError("invalid_date_window")
            rows, products = self._owned_rows(snapshot), self._products(snapshot)
            if slots.get("product_last4") and any(products[row["product_id"]]["product_last4"] is None for row in rows):
                raise BankError("product_last4_unavailable")
            amount = _number(slots.get("amount"), signed=True)
            if slots.get("amount") is not None and amount is None:
                raise BankError("invalid_filter")
            tolerance = Decimal("0.10") if slots.get("amount_is_approximate") else Decimal("0.01")
            matched = []
            for row in rows:
                if not start <= row["transaction_date"].date() <= end:
                    continue
                if slots.get("transaction_id") and self._ref(row["transaction_id"]) != slots["transaction_id"]:
                    continue
                if amount is not None and abs(row["amount"] - amount) > abs(amount) * tolerance:
                    continue
                if any(slots.get(slot) and slots[slot] != row.get(field) for slot, field in
                       (("currency", "currency"), ("transaction_type", "transaction_type"), ("channel", "channel"))):
                    continue
                if any(slots.get(slot) and _norm(slots[slot]) != _norm(row.get(field)) for slot, field in
                       (("city", "transaction_city"), ("country", "transaction_country"))):
                    continue
                if slots.get("merchant") and _norm(slots["merchant"]) not in _norm(row.get("merchant_name")):
                    continue
                product = products[row["product_id"]]
                if slots.get("product_hint") and not _matches_product_hint(slots["product_hint"], product["product_type"]):
                    continue
                if slots.get("product_last4") and slots["product_last4"] != product["product_last4"]:
                    continue
                matched.append(self._visible(row, snapshot, products))
            candidates = [{**row, "ref": str(index + 1)} for index, row in enumerate(matched[:5])]
            digest = hashlib.sha256(json.dumps([snapshot.id, slots, [row["transaction_id"] for row in matched]], sort_keys=True, default=str).encode()).hexdigest()
            result = {"status": "ok", "match_count": len(matched), "candidates": candidates, "snapshot_hash": digest,
                "search_context": {"coverage_complete": True, "snapshot_id": snapshot.id, "date_basis": "event_date",
                    "date_from": start.isoformat(), "date_to": end.isoformat(), "used_snapshot_default": not slots.get("date_from")},
                "data_quality_flags": []}
        elif name in {"get_transaction", "get_related_complaints"}:
            snapshot, row = self.resolve_owned_reference(args.get("transaction_id"), snapshot_id=args.get("snapshot_id"))
            self._verify_target(snapshot, row)
            products = self._products(snapshot)
            if name == "get_transaction":
                duplicate = self._duplicates(snapshot, row, self._owned_rows(snapshot))
                fraud = _number(row.get("fraud_score"), maximum=100)
                usd, usd_provenance = self._usd_risk(row)
                result = {"status": "ok", "transaction": self._visible(row, snapshot, products),
                    "source_verified": True, "risk_data_complete": fraud is not None and usd is not None,
                    "risk_signals": {**duplicate, "fraud_score": float(fraud) if fraud is not None else None,
                                     "amount_usd": float(usd) if usd is not None else None,
                                     "amount_usd_provenance": usd_provenance},
                    "data_quality_flags": ["possible_duplicate"] if duplicate["duplicate_signal"] == "persistent" else [],
                    "snapshot": snapshot.id, "snapshot_id": snapshot.id}
                result["transaction"].update(possible_duplicate_of=duplicate["possible_duplicate_of"],
                                              conflicting_duplicate=duplicate["conflicting_duplicate"])
            else:
                history = self._historical(snapshot)
                historical = []
                for item in history:
                    status = _norm(item["status"]).replace(" ", "")
                    category, subcategory = _norm(item["category"]), _norm(item["subcategory"])
                    if status in _CLOSED:
                        continue
                    if category and category not in {"transactions", "transacciones"}:
                        continue
                    if subcategory and subcategory not in {"cargo no reconocido", "cargos no reconocidos"}:
                        continue
                    historical.append(self._historical_public(item))
                with self.service.store.connect() as db:
                    projection = self.service.actions._case_projection(db, self.principal.customer, row["transaction_id"], self.repository._visible(row, snapshot))
                exact = ([{"complaint_id": projection["receipt"]["id"], "status": "Open", "source": "sandbox_cases",
                           "transaction_id": self._ref(row["transaction_id"]), "linkage": "exact_sandbox"}]
                         if projection["state"] == "verified" else [])
                duplicate_check = ("exact_open_case" if exact else "incomplete" if projection["state"] == "action_unverified"
                                   else "historical_uncertain" if historical else "clear_in_snapshot")
                result = {"status": "ok", "complaints": exact, "historical_candidates": historical,
                          "match_method": "exact_sandbox", "duplicate_check": duplicate_check,
                          "report_window": self._window(row["transaction_id"], self.clock()), "data_quality_flags": []}
        elif name in {"list_customer_complaints", "get_complaint"}:
            historical = [self._historical_public(row) for row in self._historical(snapshot)]
            complaints = historical + self._sandbox(snapshot)
            digest = hashlib.sha256(json.dumps([snapshot.id, complaints], sort_keys=True).encode()).hexdigest()
            if args.get("snapshot_hash") and digest != args["snapshot_hash"]:
                raise BankError("snapshot_changed")
            if name == "get_complaint":
                found = [row for row in complaints if row["complaint_id"] == args.get("complaint_id")]
                if len(found) != 1:
                    raise BankError("reference_unavailable")
                result = {"status": "ok", "complaint": found[0], "coverage_complete": True, "snapshot_hash": digest}
            else:
                if args.get("only_open") is True:
                    complaints = [row for row in complaints if _norm(row["status"]).replace(" ", "") not in _CLOSED]
                result = {"status": "ok", "complaints": [{**row, "ref": str(index + 1)} for index, row in enumerate(complaints)],
                          "match_count": len(complaints), "coverage_complete": True, "snapshot_hash": digest}
        elif name == "get_recent_interactions":
            days = args.get("days", 30)
            if type(days) is not int or not 1 <= days <= 365:
                raise BankError("invalid_filter")
            window_end = datetime.fromtimestamp(self.clock(), timezone.utc).replace(tzinfo=None)
            window_start = window_end - timedelta(days=days)
            self._table_complete(snapshot, "call_center_interactions")
            for obj in self._table_sources(snapshot, "call_center_interactions"):
                self._source(snapshot, obj["key"])
            rows = self._query("SELECT interaction_date,contact_reason,was_resolved,was_escalated FROM read_parquet(?) "
                "WHERE customer_id=? AND interaction_date BETWEEN ? AND ? ORDER BY interaction_date DESC LIMIT 5",
                [str(snapshot.build / "silver/call_center_interactions.parquet"), self.principal.customer, window_start, window_end])
            result = {"status": "ok", "interactions": [{**row,
                "contact_reason": (row["contact_reason"] or "")[:160],
                "interaction_date": row["interaction_date"].isoformat()} for row in rows]}
        else:
            raise BankError("invalid_arguments")
        self.repository.assert_current_snapshot(snapshot.id)
        self._fence()
        return {"snapshot_id": snapshot.id, **result}

    def assert_action_eligible(self, reference, snapshot_id):
        """Host-only fresh policy admission, never a model-authored authorization.

        This verifies read eligibility before the host offers/prepares intake.
        Explicit portal consent, exact pending scope and all Actions guards still
        apply independently at confirmation. The returned raw row stays private.
        """
        target = self._read("get_transaction", {"transaction_id": reference, "snapshot_id": snapshot_id})
        related = self._read("get_related_complaints", {"transaction_id": reference, "snapshot_id": snapshot_id})
        row, risk = target["transaction"], target["risk_signals"]
        if risk["duplicate_signal"] != "clear":
            raise BankError("duplicate_review")
        age = (datetime.fromtimestamp(self.clock(), timezone.utc).date() - date.fromisoformat(row["transaction_date"][:10])).days
        if age < 0 or age > 120 or row["transaction_status"] != "Approved":
            raise BankError("out_of_policy")
        if related["duplicate_check"] != "clear_in_snapshot":
            raise BankError("action_unverified" if related["duplicate_check"] == "incomplete" else "missing_evidence")
        report = related["report_window"]
        if (risk["fraud_score"] is not None and risk["fraud_score"] >= 70
                or risk["amount_usd"] is not None and risk["amount_usd"] >= 1000
                or report["coverage_complete"] and report["prior_distinct_verified_count"] + 1 >= 3):
            raise BankError("handoff_required")
        if not target["risk_data_complete"] or not report["coverage_complete"]:
            raise BankError("risk_data_unavailable")
        snapshot, raw = self.resolve_owned_reference(reference, snapshot_id=snapshot_id)
        return snapshot, raw, {"transaction": target, "related_complaints": related}

    def action_evidence(self, raw_target, snapshot_id):
        """Fresh private facts for Actions' trusted host callback, no write power."""
        self._fence()
        self.repository.owned_transaction_id(self.principal, raw_target, snapshot_id)
        reference = self._ref(raw_target)
        target = self._read("get_transaction", {"transaction_id": reference, "snapshot_id": snapshot_id})
        risk = target["risk_signals"]
        historical = "uncertain"
        try:
            related = self._read("get_related_complaints", {"transaction_id": reference, "snapshot_id": snapshot_id})
            historical = {"clear_in_snapshot": "clear_in_snapshot", "exact_open_case": "exact_open_case"}.get(related["duplicate_check"], "uncertain")
        except BankError as exc:
            if exc.code in {"authorization_denied", "snapshot_changed", "reference_unavailable"}:
                raise
        self._fence()
        return {"historical_complaints": historical, "duplicate_signal": risk["duplicate_signal"],
                "fraud_score": risk["fraud_score"], "amount_usd": risk["amount_usd"]}

    async def read(self, name, args):
        if not isinstance(args, dict):
            return {"status": "error", "code": "invalid_arguments"}
        if any(key in args for key in ("customer_id", "owner", "session_id", "conversation_id", "principal")):
            return {"status": "error", "code": "authorization_denied"}
        if isinstance(args.get("slots"), dict) and args["slots"].get("foreign_customer_reference") is True:
            return {"status": "error", "code": "authorization_denied"}
        try:
            return await asyncio.to_thread(self._read, name, args)
        except BankError as exc:
            return {"status": "error", "code": exc.code}
        except (OSError, ValueError, TypeError, KeyError, duckdb.Error):
            return {"status": "error", "code": "data_unavailable"}
