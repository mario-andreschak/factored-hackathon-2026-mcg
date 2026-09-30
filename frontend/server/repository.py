from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import duckdb

from .config import SYNTHETIC_MARKER, Settings
from .state import State


PROFILE_DEFAULTS = {
    "colombia": {"alias": "Valentina", "country": "Colombia", "description": "Tu día a día, en pesos colombianos"},
    "mexico": {"alias": "Santiago", "country": "México", "description": "Tu banca, sin fronteras"},
    "argentina": {"alias": "Lucía", "country": "Argentina", "description": "Todo lo que mueve tus planes"},
}
DEPOSIT_TYPES = {"Cuenta Ahorro", "Cuenta Corriente"}
CREDIT_TYPES = {"Tarjeta Crédito", "Préstamo Personal", "Préstamo Hipotecario"}
# The dataset supplies positive magnitudes. Transfer, Payment and Adjustment do not
# identify the account leg, so they must not be presented as invented debit signs.
DIRECTIONS = {"Deposit": "credit", "Purchase": "debit", "Withdrawal": "debit"}
TRANSACTION_FIELDS = """transaction_id, product_id, transaction_date AS occurred_at,
    process_date, transaction_type AS type, transaction_category AS category,
    amount, currency, transaction_status AS status, channel, merchant_name AS merchant,
    merchant_category, transaction_country AS country, transaction_city AS city"""


class DatasetUnavailable(Exception):
    pass


def clean(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def records(cursor) -> list[dict]:
    cols = [d[0] for d in cursor.description]
    return [{k: clean(v) for k, v in zip(cols, row)} for row in cursor.fetchall()]


@dataclass(frozen=True)
class Snapshot:
    build: Path
    fingerprint: str
    created_at: str | None
    bucket_files: dict[int, list[Path]]
    data_as_of: str | None
    file_sizes: dict[Path, int]
    source_validation: str


class Repository:
    def __init__(self, settings: Settings, state: State):
        self.settings, self.state = settings, state
        self.lock = threading.Lock()
        self._snapshot: Snapshot | None = None

    @staticmethod
    @contextmanager
    def connection():
        with TemporaryDirectory(prefix="banking-duckdb-") as directory:
            con = duckdb.connect()
            try:
                con.execute("SET threads=2")
                con.execute("SET memory_limit='512MB'")
                con.execute("SET max_temp_directory_size='256MB'")
                path = directory.replace("\\", "/").replace("'", "''")
                con.execute(f"SET temp_directory='{path}'")
                yield con
            finally:
                con.close()

    def snapshot(self) -> Snapshot:
        """Pin CURRENT once, validate complete published inventory, never fall back."""
        try:
            pointer = (self.settings.data_dir / "CURRENT").read_text(encoding="utf-8").strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", pointer):
                raise DatasetUnavailable()
            builds = (self.settings.data_dir / "builds").resolve()
            build = (builds / pointer).resolve()
            if build.parent != builds:
                raise DatasetUnavailable()
            expected = self.settings.expected_snapshot if self.settings.auth_mode == "invite" else None
            if expected and pointer != expected["build_id"]:
                raise DatasetUnavailable()
            with self.lock:
                if self._snapshot and self._snapshot.build == build:
                    if expected:
                        current_manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
                        if (not isinstance(current_manifest, dict)
                                or current_manifest.get("build_id") != expected["build_id"]
                                or current_manifest.get("source_fingerprint") != expected["source_fingerprint"]):
                            raise DatasetUnavailable()
                        self._check_synthetic_marker(build, expected)
                    # Files are immutable after publication, but missing mounted files
                    # must fail closed even after a healthy cached request.
                    self._check_files(self._snapshot)
                    return self._snapshot
                manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
                if not isinstance(manifest, dict):
                    raise DatasetUnavailable()
                fingerprint = manifest.get("source_fingerprint")
                if manifest.get("build_id") != pointer or not re.fullmatch(r"[a-f0-9]{12,64}", str(fingerprint)):
                    raise DatasetUnavailable()
                if expected:
                    if fingerprint != expected["source_fingerprint"]:
                        raise DatasetUnavailable()
                    self._check_synthetic_marker(build, expected)
                files = manifest.get("gold_files")
                if not isinstance(files, dict) or not files:
                    raise DatasetUnavailable()
                buckets = defaultdict(list)
                file_sizes = {}
                gold = (build / "gold").resolve()
                for relative, size in files.items():
                    if not isinstance(relative, str) or type(size) is not int or size < 0:
                        raise DatasetUnavailable()
                    file = (gold / relative).resolve()
                    if gold not in file.parents or not file.is_file() or file.stat().st_size != size:
                        raise DatasetUnavailable()
                    file_sizes[file] = size
                    matched = re.fullmatch(r"transactions_by_customer/bucket=(\d+)/([^/]+\.parquet)", relative)
                    if matched:
                        bucket = int(matched[1])
                        if bucket >= 128:
                            raise DatasetUnavailable()
                        buckets[bucket].append(file)
                if not buckets:
                    raise DatasetUnavailable()
                for table in ("customers", "products"):
                    file = build / "silver" / f"{table}.parquet"
                    if not file.is_file():
                        raise DatasetUnavailable()
                    file_sizes[file] = file.stat().st_size
                with self.connection() as con:
                    last = con.execute("SELECT max(transaction_date) FROM read_parquet(?)",
                                       [[str(p) for paths in buckets.values() for p in paths]]).fetchone()[0]
                validation = manifest.get("source_validation", "unspecified")
                if not isinstance(validation, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", validation):
                    raise DatasetUnavailable()
                self._snapshot = Snapshot(build, fingerprint, manifest.get("created_at"), dict(buckets), clean(last), file_sizes, validation)
                return self._snapshot
        except (OSError, ValueError, KeyError, duckdb.Error) as exc:
            raise DatasetUnavailable() from exc

    @staticmethod
    def _check_synthetic_marker(build: Path, expected: dict[str, str]):
        marker = json.loads((build / "synthetic_provenance.json").read_text(encoding="utf-8"))
        if not isinstance(marker, dict) or marker != expected:
            raise DatasetUnavailable()

    @staticmethod
    def _check_files(snapshot: Snapshot):
        for table in ("customers", "products"):
            if not (snapshot.build / "silver" / f"{table}.parquet").is_file():
                raise DatasetUnavailable()
        if any(not p.is_file() or p.stat().st_size != size for p, size in snapshot.file_sizes.items()):
            raise DatasetUnavailable()

    def reference(self, kind: str, customer_id: str, value: str) -> str:
        digest = hmac.new(self.state.secret, f"{kind}:{customer_id}:{value}".encode(), hashlib.sha256).hexdigest()[:24]
        return f"{kind}_{digest}"

    def _profile_template(self, profile_id: str) -> dict:
        defaults = PROFILE_DEFAULTS.get(profile_id)
        if not defaults:
            raise KeyError(profile_id)
        overrides = self.settings.profiles.get(profile_id, {})
        return {**defaults, **{k: v for k, v in overrides.items() if k in {"alias", "description", "country"}}}

    def ensure_profiles(self, snapshot: Snapshot):
        """Aliases are fictional; private mappings restrict selectable demo records."""
        if self.settings.auth_mode == "invite":
            # Startup applied only explicit bindings. Never search the mounted
            # dataset for a replacement visitor when a binding is missing.
            if any(self.state.customer(key) != config["customer_id"]
                   for key, config in self.settings.profiles.items()):
                raise DatasetUnavailable()
            return
        with self.lock:
            missing = [key for key in PROFILE_DEFAULTS if not self.state.customer(key)]
            explicit = self.settings.profiles
            for key in PROFILE_DEFAULTS:
                selected = explicit.get(key, {}).get("customer_id")
                if selected:
                    self.state.bind(key, selected)
                    if key in missing:
                        missing.remove(key)
            if not missing:
                return
            approved = set(self.settings.chat.get("principal_customers", {}).values())
            customers_path = str(snapshot.build / "silver" / "customers.parquet")
            products_path = str(snapshot.build / "silver" / "products.parquet")
            gold_paths = [str(p) for files in snapshot.bucket_files.values() for p in files]
            with self.connection() as con:
                con.read_parquet(customers_path).create_view("customers")
                con.read_parquet(products_path).create_view("products")
                con.read_parquet(gold_paths).create_view("transactions")
                # Use existing signed-principal customers when configured, keeping
                # authentication and model execution bound to the same identity.
                restriction = "AND c.customer_id IN (SELECT unnest(?))" if approved else ""
                for key in missing:
                    params = [self._profile_template(key)["country"]]
                    if approved:
                        params.append(sorted(approved))
                    candidates = con.execute(f"""
                        WITH product_profile AS (
                            SELECT customer_id, count(*) AS products,
                                   count(*) FILTER (WHERE product_type IN ('Cuenta Ahorro','Cuenta Corriente')) AS accounts,
                                   count(*) FILTER (WHERE product_type='Tarjeta Crédito') AS cards,
                                   count(*) FILTER (WHERE product_status='Active') AS active_products
                            FROM products GROUP BY 1
                        ), activity AS (
                            SELECT t.customer_id, count(*) AS transactions,
                                   count(*) FILTER (WHERE merchant_name IS NOT NULL) AS merchants,
                                   max(transaction_date) AS latest
                            FROM transactions t JOIN products p ON p.product_id=t.product_id AND p.customer_id=t.customer_id
                            WHERE ownership_valid GROUP BY 1
                        )
                        SELECT c.customer_id FROM customers c
                        JOIN product_profile p USING(customer_id) JOIN activity a USING(customer_id)
                        WHERE c.country=? AND c.customer_status='Active' {restriction}
                        ORDER BY (p.accounts>0 AND p.cards>0) DESC,
                                 (a.transactions BETWEEN 15 AND 100) DESC,
                                 p.active_products DESC, a.merchants DESC, a.latest DESC, c.customer_id
                        LIMIT 1
                    """, params).fetchone()
                    if candidates:
                        self.state.bind(key, candidates[0])

    def profile_customer(self, profile_id: str) -> str:
        if self.settings.auth_mode == "invite" and profile_id not in self.settings.profiles:
            raise DatasetUnavailable()
        snapshot = self.snapshot()
        self.ensure_profiles(snapshot)
        customer = self.state.customer(profile_id)
        if not customer:
            raise DatasetUnavailable()
        return customer

    def profile(self, profile_id: str, snapshot: Snapshot | None = None) -> dict:
        if self.settings.auth_mode == "invite" and profile_id not in self.settings.profiles:
            raise DatasetUnavailable()
        snapshot = snapshot or self.snapshot()
        self.ensure_profiles(snapshot)
        customer = self.state.customer(profile_id)
        if not customer:
            raise DatasetUnavailable()
        with self.connection() as con:
            rows = records(con.execute("""SELECT country, city, segment, customer_status AS status,
                                          registration_date AS member_since FROM read_parquet(?) WHERE customer_id=?""",
                                       [str(snapshot.build / "silver" / "customers.parquet"), customer]))
            currencies = con.execute("""SELECT currency FROM read_parquet(?) WHERE customer_id=?
                GROUP BY currency ORDER BY count(*) FILTER (WHERE product_type IN ('Cuenta Ahorro','Cuenta Corriente')) DESC,
                count(*) DESC, currency LIMIT 1""", [str(snapshot.build / "silver" / "products.parquet"), customer]).fetchone()
        template = self._profile_template(profile_id)
        if (not rows or rows[0]["country"] != template["country"]
                or (self.settings.auth_mode == "invite" and rows[0]["status"] != "Active")):
            raise DatasetUnavailable()
        identity_note = ("Perfil y movimientos sintéticos creados por el equipo para esta demostración."
                         if self.settings.auth_mode == "invite" else
                         "Identidad de demostración; datos del dataset del hackathon.")
        return {"id": profile_id, **template, **rows[0], "primary_currency": currencies[0] if currencies else None,
                "demo": True, "identity_note": identity_note}

    def profiles(self) -> list[dict]:
        snapshot = self.snapshot()
        self.ensure_profiles(snapshot)
        keys = self.settings.profiles if self.settings.auth_mode == "invite" else PROFILE_DEFAULTS
        return [self.profile(key, snapshot) for key in keys if self.state.customer(key)]

    def _scoped(self, con, snapshot: Snapshot, customer: str):
        con.read_parquet(str(snapshot.build / "silver" / "customers.parquet")).create_view("customers")
        con.read_parquet(str(snapshot.build / "silver" / "products.parquet")).create_view("products")
        bucket = int(hashlib.md5(customer.encode()).hexdigest()[:8], 16) % 128
        files = snapshot.bucket_files.get(bucket, [])
        if not files:
            return False
        con.read_parquet([str(p) for p in files]).create_view("transactions")
        # Bound parameters cannot appear in a CREATE VIEW in every supported DuckDB
        # version; create the relation with execute and materialize this one customer.
        con.execute("""CREATE TEMP TABLE scoped AS SELECT t.* FROM transactions t
            JOIN products p ON p.product_id=t.product_id AND p.customer_id=t.customer_id
            JOIN customers c ON c.customer_id=t.customer_id
            WHERE t.customer_id=? AND t.ownership_valid""", [customer])
        return True

    def _public_transaction(self, transaction: dict, customer: str) -> dict:
        transaction["reference"] = self.reference("txn", customer, transaction.pop("transaction_id"))
        transaction["product_reference"] = self.reference("prod", customer, transaction.pop("product_id"))
        transaction["direction"] = DIRECTIONS.get(transaction["type"], "unknown")
        return transaction

    def overview(self, profile_id: str, limit: int = 500, *, product: str | None = None,
                 status: str | None = None, q: str | None = None, offset: int = 0,
                 month: str | None = None) -> dict:
        snapshot = self.snapshot()
        profile = self.profile(profile_id, snapshot)
        customer = self.state.customer(profile_id)
        page_limit, page_offset = max(1, min(limit, 500)), max(0, offset)
        with self.connection() as con:
            have_transactions = self._scoped(con, snapshot, customer)
            product_rows = records(con.execute("""SELECT p.product_id, p.product_type AS type, p.currency,
                p.current_balance AS balance, p.credit_limit, p.interest_rate, p.product_status AS status,
                p.opening_date AS opened_at, p.expiration_date AS expires_at, p.last_updated,
                p.last_transaction_date AS last_transaction_at FROM products p
                JOIN customers c ON p.customer_id=c.customer_id WHERE p.customer_id=?
                ORDER BY CASE WHEN p.product_type IN ('Cuenta Ahorro','Cuenta Corriente') THEN 0
                    WHEN p.product_type='Tarjeta Crédito' THEN 1 ELSE 2 END, p.product_id""", [customer]))
            txn_rows, monthly, total, filtered_count = [], [], 0, 0
            if have_transactions:
                clauses, params = [], []
                if product:
                    owned_product = next((p["product_id"] for p in product_rows
                        if hmac.compare_digest(self.reference("prod", customer, p["product_id"]).encode(), product.encode())), None)
                    clauses.append("product_id=?" if owned_product else "FALSE")
                    if owned_product:
                        params.append(owned_product)
                if status:
                    clauses.append("transaction_status=?")
                    params.append(status)
                if month:
                    clauses.append("strftime(transaction_date,'%Y-%m')=?")
                    params.append(month)
                if q:
                    searchable = ("transaction_type", "merchant_name", "transaction_category", "channel", "transaction_city", "currency")
                    clauses.append("(" + " OR ".join(f"contains(lower(coalesce({field},'')),?)" for field in searchable) + ")")
                    params.extend([q.lower()] * len(searchable))
                where = " WHERE " + " AND ".join(clauses) if clauses else ""
                txn_rows = records(con.execute(f"""SELECT {TRANSACTION_FIELDS}
                    FROM scoped {where} ORDER BY transaction_date DESC, transaction_id LIMIT ? OFFSET ?""",
                    [*params, page_limit, page_offset]))
                filtered_count = con.execute("SELECT count(*) FROM scoped" + where, params).fetchone()[0]
                total = con.execute("SELECT count(*) FROM scoped").fetchone()[0]
                monthly = records(con.execute("""SELECT strftime(transaction_date,'%Y-%m') AS month, currency,
                    sum(CASE WHEN transaction_status='Approved' AND transaction_type='Deposit' THEN amount ELSE 0 END) AS inflow,
                    sum(CASE WHEN transaction_status='Approved' AND transaction_type IN ('Purchase','Withdrawal') THEN amount ELSE 0 END) AS outflow,
                    sum(CASE WHEN transaction_status='Approved' AND transaction_type IN ('Transfer','Payment','Adjustment') THEN amount ELSE 0 END) AS unclassified,
                    count(*) AS count FROM scoped GROUP BY 1,2 ORDER BY 1,2"""))
        balances = defaultdict(lambda: {"deposit_balance": Decimal("0"), "credit_balance": Decimal("0"),
                                        "investment_balance": Decimal("0"), "other_balance": Decimal("0")})
        for p in product_rows:
            p["reference"] = self.reference("prod", customer, p.pop("product_id"))
            p["masked_number"] = None
            p["balance_kind"] = "deposit" if p["type"] in DEPOSIT_TYPES else "credit" if p["type"] in CREDIT_TYPES else "investment" if p["type"] == "Inversión" else "other"
            balances[p["currency"]][f'{p["balance_kind"]}_balance'] += Decimal(str(p["balance"]))
        for t in txn_rows:
            self._public_transaction(t, customer)
        return {
            "profile": profile, "products": product_rows, "transactions": txn_rows,
            "summary": {"balances_by_currency": [{"currency": currency, **{k: clean(v) for k, v in amounts.items()}}
                          for currency, amounts in sorted(balances.items())],
                        "transaction_count": total, "monthly_activity": monthly},
            "metadata": {"dataset": "team-synthetic-fixture" if self.settings.auth_mode == "invite" else "organizer-snapshot", "build_id": snapshot.build.name,
                         "source_fingerprint": snapshot.fingerprint, "snapshot_created_at": snapshot.created_at,
                         "source_validation": snapshot.source_validation,
                         "freshness": SYNTHETIC_MARKER if self.settings.auth_mode == "invite" else "derived_snapshot",
                         "filtered_count": filtered_count,
                         "transactions_limit": page_limit, "transactions_offset": page_offset,
                         "transactions_truncated": len(txn_rows) < filtered_count,
                         "next_offset": page_offset + len(txn_rows) if page_offset + len(txn_rows) < filtered_count else None,
                         "data_as_of": snapshot.data_as_of, "transactions_returned": len(txn_rows), "transactions_total": total,
                         "balances_note": ("Saldos sintéticos de la demostración; no representan dinero real."
                                           if self.settings.auth_mode == "invite" else
                                           "Saldos de la instantánea publicada; no representan un saldo bancario en tiempo real."),
                         "amounts_note": "Importes originales por moneda. Solo depósitos, compras y retiros tienen dirección conocida; transferencias, pagos y ajustes se muestran sin un signo inventado. La actividad suma únicamente operaciones aprobadas.",
                         "identity_note": ("Los perfiles, productos y movimientos son datos sintéticos del equipo."
                                           if self.settings.auth_mode == "invite" else
                                           "Los nombres de acceso son alias ficticios. Los productos y movimientos proceden del dataset del hackathon."),
                         "account_numbers_note": ("Se muestran referencias opacas, no números de cuenta reales."
                                                  if self.settings.auth_mode == "invite" else
                                                  "Los números de cuenta se eliminaron en silver; se usa una referencia opaca.")},
        }

    def _owned_transaction(self, profile_id: str, reference: str) -> tuple[dict, str] | None:
        """Resolve a browser reference only inside this owner-scoped server."""
        if not isinstance(reference, str) or not re.fullmatch(r"txn_[a-f0-9]{24}", reference):
            return None
        snapshot = self.snapshot()
        self.profile(profile_id, snapshot)
        customer = self.state.customer(profile_id)
        with self.connection() as con:
            if not self._scoped(con, snapshot, customer):
                return None
            # Only IDs from the full ownership-checked relation are examined. Batch
            # fetches bound Python memory without imposing a history-age cutoff.
            cursor = con.execute("SELECT transaction_id FROM scoped")
            matched = None
            while rows := cursor.fetchmany(1024):
                matched = next((value for (value,) in rows if hmac.compare_digest(
                    self.reference("txn", customer, value), reference)), None)
                if matched is not None:
                    break
            if matched is None:
                return None
            rows = records(con.execute(f"SELECT {TRANSACTION_FIELDS} FROM scoped WHERE transaction_id=?", [matched]))
            if len(rows) != 1:
                return None
            return rows[0], snapshot.build.name

    def transaction(self, profile_id: str, reference: str) -> dict | None:
        """Resolve an owned reference independently of any display page or filter."""
        resolved = self._owned_transaction(profile_id, reference)
        if not resolved:
            return None
        row, _ = resolved
        return self._public_transaction(row, self.state.customer(profile_id))

    def action_target(self, profile_id: str, reference: str) -> dict | None:
        """Private target for FLUJO; raw IDs are never sent to the browser."""
        resolved = self._owned_transaction(profile_id, reference)
        if not resolved:
            return None
        row, build = resolved
        return {"transaction_id": row["transaction_id"], "snapshot": build,
                "transaction": {key: row[key] for key in
                                ("occurred_at", "type", "amount", "currency", "status", "merchant")}}
