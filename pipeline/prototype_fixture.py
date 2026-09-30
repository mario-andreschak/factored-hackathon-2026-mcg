"""Generate a small, credible banking prototype source; never organizer data.

Usage::

    python -m pipeline.prototype_fixture <empty-source-directory>
    python -m pipeline run --source <source-directory> --out <isolated-snapshot> \
        --reports <isolated-reports>

All people, merchants, identifiers and events below are fictional. The source is
deterministic and intentionally refuses a nonempty directory, so it cannot quietly
replace a real dataset. The adjacent marker describes origin; pipeline source
validation still means only that these local CSV files stayed unchanged while read.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .common import load_contracts


MARKER = "SYNTHETIC_BANKING_PROTOTYPE.json"
PUBLISHED_MARKER = "synthetic_provenance.json"


@dataclass(frozen=True)
class Persona:
    profile: str
    code: str
    alias: str
    surname: str
    country: str
    city: str
    state: str
    accent: str
    segment: str
    currency: str
    account_balance: str
    card_balance: str
    credit_limit: str
    salary: str
    grocery: str
    cafe: str
    subscription: str
    withdrawal: str
    reversed_amount: str
    transfer: str
    candidate_amount: str
    pending_amount: str
    grocer: str
    coffee_shop: str
    subscription_merchant: str
    candidate_merchant: str
    pending_merchant: str
    language: str
    customer_text: str

    @property
    def customer_id(self) -> str:
        return f"SYNTH-{self.code}-001"

    @property
    def account_id(self) -> str:
        return f"SYNTH-{self.code}-ACCOUNT"

    @property
    def card_id(self) -> str:
        return f"SYNTH-{self.code}-CARD"

    @property
    def candidate_id(self) -> str:
        return f"SYNTH-{self.code}-UNRECOGNIZED"


PERSONAS = (
    Persona("mexico", "MX", "Valentina", "Mora", "México", "Ciudad de México",
            "Ciudad de México", "mexican", "Plus", "MXN", "78520.40", "10980.20",
            "120000.00", "31500.00", "852.30", "126.00", "189.00", "1800.00",
            "799.00", "2500.00", "4280.75", "2400.00", "Mercado Origen",
            "Café Tilo", "Luz Música", "Nébula Market", "Casa Naranjo", "es",
            "No reconozco la compra de 4280.75 MXN en Nébula Market de mi tarjeta. ¿Pueden revisarla?"),
    Persona("colombia", "CO", "Santiago", "Ríos", "Colombia", "Bogotá", "Bogotá D.C.",
            "colombian", "Premium", "COP", "14420000.00", "2178500.00",
            "35000000.00", "8750000.00", "187450.00", "28900.00", "44900.00",
            "450000.00", "159900.00", "500000.00", "1290000.00", "613000.00",
            "Mercado Cedro", "Café Río", "Ritmo Plus", "Aurora Digital", "Hogar Nube", "pt",
            "Não reconheço a compra de 1290000.00 COP em Aurora Digital no meu cartão. Podem verificar?"),
    Persona("argentina", "AR", "Lucía", "Ferrer", "Argentina", "Buenos Aires", "CABA",
            "argentine", "Basic", "ARS", "3870000.00", "912300.00", "6000000.00",
            "2450000.00", "110500.00", "19800.00", "14900.00", "175000.00",
            "69900.00", "180000.00", "585000.00", "270000.00", "Almacén Sur",
            "Café Jacarandá", "Onda Música", "Atlas Viajes", "Casa Ladera", "es",
            "No reconozco el cargo de 585000.00 ARS en Atlas Viajes de mi tarjeta. Quiero revisarlo."),
)


def _record(contracts: dict, table: str, **values: object) -> dict[str, str]:
    columns = contracts[table]["columns"]
    unknown = values.keys() - columns.keys()
    if unknown:
        raise ValueError(f"unknown {table} columns: {sorted(unknown)}")
    return {column: "" if values.get(column) is None else str(values.get(column, ""))
            for column in columns}


def _write(path: Path, contracts: dict, table: str, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(contracts[table]["columns"]))
        writer.writeheader()
        writer.writerows(rows)


def _partition(root: Path, table: str, day: str) -> Path:
    year, month, date = day.split("-")
    return root / table / f"year={year}" / f"month={month}" / f"day={date}" / "part-0000.csv"


def _varied(base: str, month: int, rate: str = "0.04") -> str:
    return str((Decimal(base) * (Decimal(1) + Decimal(rate) * (month - 6))).quantize(Decimal("0.01")))


def write_prototype_source(root: Path) -> None:
    """Write six contract-compatible CSV tables into a fresh isolated directory."""
    root = Path(root)
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        raise FileExistsError(f"prototype source must be an empty directory: {root}")
    root.mkdir(parents=True, exist_ok=True)
    contracts = load_contracts()

    customers: list[dict[str, str]] = []
    products: list[dict[str, str]] = []
    transactions: dict[str, list[dict[str, str]]] = {}
    interactions: dict[str, list[dict[str, str]]] = {}
    transcripts: dict[str, list[dict[str, str]]] = {}
    complaints: dict[str, list[dict[str, str]]] = {}

    for person in PERSONAS:
        customers.append(_record(
            contracts, "customers", customer_id=person.customer_id,
            first_name=person.alias, last_name=person.surname, city=person.city,
            state=person.state, country=person.country, detected_accent=person.accent,
            segment=person.segment, registration_date="2023-08-21 11:00:00",
            customer_status="Active", last_updated="2026-09-27 08:00:00",
            accepts_marketing="False"))

        for product_id, product_type, balance, limit, last_transaction in (
            (person.account_id, "Cuenta Ahorro", person.account_balance, None,
             "2026-09-18 14:15:00"),
            (person.card_id, "Tarjeta Crédito", person.card_balance, person.credit_limit,
             "2026-09-25 17:45:00"),
        ):
            products.append(_record(
                contracts, "products", product_id=product_id,
                customer_id=person.customer_id, product_type=product_type,
                currency=person.currency, current_balance=balance, credit_limit=limit,
                opening_date="2024-02-12", expiration_date="2029-12-31" if limit else None,
                product_status="Active", opening_channel="App", has_linked_app="True",
                days_past_due="0", last_transaction_date=last_transaction,
                last_updated="2026-09-27 08:00:00"))

        serial = 0

        def add(day: str, hour: str, kind: str, amount: str, *, product_id: str,
                category: str, merchant: str = "", merchant_category: str = "",
                status: str = "Approved", channel: str = "Card",
                transaction_id: str | None = None, flagged: bool = False) -> None:
            nonlocal serial
            serial += 1
            transactions.setdefault(day, []).append(_record(
                contracts, "transactions",
                transaction_id=transaction_id or f"SYNTH-{person.code}-TX-{serial:03d}",
                transaction_date=f"{day} {hour}", process_date=day,
                product_id=product_id, customer_id=person.customer_id,
                transaction_type=kind, transaction_category=category,
                amount=amount, currency=person.currency, channel=channel,
                merchant_name=merchant, merchant_category=merchant_category,
                transaction_country=person.country, transaction_city=person.city,
                transaction_status=status, response_code="00" if status == "Approved" else "",
                is_fraud=str(flagged), fraud_score="0.91" if flagged else "0.08"))

        # Four months of regular activity, with amounts held in each native currency.
        for month in range(6, 10):
            prefix = f"2026-{month:02d}"
            add(f"{prefix}-08", "09:15:00", "Deposit", person.salary,
                product_id=person.account_id, category="Nómina", channel="Transfer")
            add(f"{prefix}-12", "18:25:00", "Purchase", _varied(person.grocery, month),
                product_id=person.card_id, category="Supermercado", merchant=person.grocer,
                merchant_category="Groceries")
            add(f"{prefix}-20", "08:40:00", "Purchase", _varied(person.cafe, month),
                product_id=person.card_id, category="Cafetería", merchant=person.coffee_shop,
                merchant_category="Food")
            add(f"{prefix}-22", "07:00:00", "Purchase", person.subscription,
                product_id=person.card_id, category="Suscripción",
                merchant=person.subscription_merchant, merchant_category="Entertainment")

        add("2026-07-28", "15:30:00", "Withdrawal", person.withdrawal,
            product_id=person.account_id, category="Efectivo", channel="ATM")
        add("2026-08-27", "10:05:00", "Purchase", person.reversed_amount,
            product_id=person.card_id, category="Compra anulada", merchant="Tienda Prado",
            merchant_category="Shopping", status="Reversed")
        add("2026-09-18", "14:15:00", "Transfer", person.transfer,
            product_id=person.account_id, category="Transferencia", channel="App")
        # One plausible but unrecognized approved card charge per profile. The fraud
        # flag is a synthetic scenario cue, not a finding about a real transaction.
        add("2026-09-24", "02:14:00", "Purchase", person.candidate_amount,
            product_id=person.card_id, category="Compra en línea",
            merchant=person.candidate_merchant, merchant_category="Online shopping",
            transaction_id=person.candidate_id, flagged=True)
        add("2026-09-25", "17:45:00", "Purchase", person.pending_amount,
            product_id=person.card_id, category="Hogar", merchant=person.pending_merchant,
            merchant_category="Home", status="Pending")

        interaction_id = f"SYNTH-{person.code}-CONTACT"
        day = "2026-09-25"
        interactions.setdefault(day, []).append(_record(
            contracts, "call_center_interactions", interaction_id=interaction_id,
            interaction_date=f"{day} 10:15:00", process_date=day,
            customer_id=person.customer_id, interaction_type="Inquiry", channel="Chat",
            contact_reason="Cargo no reconocido", reason_category="Transactional",
            duration_seconds="180", wait_time_seconds="0", was_resolved="False",
            requires_followup="True", detected_sentiment="Concerned",
            customer_detected_accent=person.accent, was_escalated="False",
            mentioned_products=person.card_id, has_transcript="True",
            has_recording="False"))
        transcripts.setdefault(day, []).append(_record(
            contracts, "call_transcripts", transcript_id=f"SYNTH-{person.code}-TRANSCRIPT",
            interaction_id=interaction_id, process_date=day,
            customer_id=person.customer_id, customer_text=person.customer_text,
            detected_language=person.language, detected_accent=person.accent,
            detected_intents="unrecognized_charge", main_topics="card_transaction",
            transcription_model="synthetic-written", audio_quality="not_applicable"))

        old_case_day = "2026-08-27"
        complaints.setdefault(old_case_day, []).append(_record(
            contracts, "complaints", complaint_id=f"SYNTH-{person.code}-OLD-CASE",
            creation_date=f"{old_case_day} 11:00:00", process_date=old_case_day,
            customer_id=person.customer_id, case_type="Dispute", category="Cards",
            subcategory="Compra anulada", reception_channel="App",
            affected_product_id=person.card_id,
            description="Consulta anterior sobre una compra anulada.",
            claimed_amount=person.reversed_amount, currency=person.currency,
            priority="Medium", status="Closed", sla_breached="False",
            resolution_date="2026-08-29 11:00:00", resolution_days="2",
            resolution="Reverso confirmado", resolution_satisfaction="4",
            is_repeat_complainer="False"))

    _write(root / "customers.csv", contracts, "customers", customers)
    _write(root / "products.csv", contracts, "products", products)
    for table, partitions in (("transactions", transactions),
                              ("call_center_interactions", interactions),
                              ("call_transcripts", transcripts), ("complaints", complaints)):
        for day, rows in sorted(partitions.items()):
            _write(_partition(root, table, day), contracts, table, rows)
    (root / MARKER).write_text(json.dumps({
        "synthetic": True, "origin": "team-generated-prototype", "version": 1,
        "profiles": [{"profile": p.profile, "customer_id": p.customer_id,
                      "country": p.country, "currency": p.currency,
                      "candidate_transaction_id": p.candidate_id} for p in PERSONAS],
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stamp_published_snapshot(source: Path, snapshot: Path) -> Path:
    """Bind a published build to every generated CSV without changing pipeline lineage.

    `source_validation` in snapshot.json retains its precise local-ingestion meaning.
    The independent marker lets consumers require known team-generated source too.
    """
    source, snapshot = Path(source), Path(snapshot)
    expected_profiles = [{"profile": p.profile, "customer_id": p.customer_id,
                          "country": p.country, "currency": p.currency,
                          "candidate_transaction_id": p.candidate_id} for p in PERSONAS]
    source_marker = json.loads((source / MARKER).read_text(encoding="utf-8"))
    if source_marker != {"synthetic": True, "origin": "team-generated-prototype",
                         "version": 1, "profiles": expected_profiles}:
        raise ValueError("source is not this exact generated prototype")
    build_id = (snapshot / "CURRENT").read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", build_id):
        raise ValueError("invalid CURRENT pointer")
    builds = (snapshot / "builds").resolve()
    build = (builds / build_id).resolve()
    if build.parent != builds:
        raise ValueError("CURRENT escapes the selected snapshot root")
    manifest = json.loads((build / "snapshot.json").read_text(encoding="utf-8"))
    inventory = json.loads((build / "source_objects.json").read_text(encoding="utf-8"))
    fingerprint = manifest.get("source_fingerprint")
    if (manifest.get("build_id") != build_id or not re.fullmatch(r"[a-f0-9]{16}", str(fingerprint))
        or manifest.get("source_validation") != "unchanged_inventory_after_ingestion"
        or inventory.get("fingerprint") != fingerprint
        or inventory.get("source_validation") != manifest["source_validation"]):
        raise ValueError("published manifest and source inventory do not match")
    required = {"customers", "products", "transactions", "call_center_interactions",
                "call_transcripts", "complaints"}
    if set(inventory.get("tables", {})) != required:
        raise ValueError("prototype snapshot must include all six source tables")
    seen: set[str] = set()
    for table in sorted(required):
        for item in inventory["tables"][table]["objects"]:
            key = item["key"]
            if not isinstance(key, str):
                raise ValueError("unexpected source object in published inventory")
            relative = Path(key)
            if (relative.is_absolute() or ".." in relative.parts
                or relative.suffix != ".csv" or relative.parts[0].removesuffix(".csv") != table
                or key in seen):
                raise ValueError("unexpected source object in published inventory")
            seen.add(key)
            path = source / relative
            if not path.is_file() or path.stat().st_size != item["bytes"]:
                raise ValueError("generated source object differs from the published inventory")
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:32]
            if item["etag"] != "sha256:" + digest:
                raise ValueError("generated source object differs from the published inventory")
    if seen != {p.relative_to(source).as_posix() for p in source.rglob("*.csv")}:
        raise ValueError("generated source inventory has added or missing CSV files")
    # A matching marker alone is an assertion by the source author. Regenerate the
    # canonical fixture and compare bytes before endorsing a build as this fixture.
    with tempfile.TemporaryDirectory(prefix="banking-prototype-verify-") as temp:
        canonical = Path(temp) / "source"
        write_prototype_source(canonical)
        for key in seen:
            if (source / key).read_bytes() != (canonical / key).read_bytes():
                raise ValueError("published source is not the canonical generated prototype")
    payload = {"kind": "team_synthetic_fixture", "build_id": build_id,
               "source_fingerprint": fingerprint}
    out = build / PUBLISHED_MARKER
    if out.exists():
        if json.loads(out.read_text(encoding="utf-8")) != payload:
            raise ValueError("published provenance marker already differs")
    else:
        with out.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "stamp":
        parser = argparse.ArgumentParser(description="Bind published build to generated source")
        parser.add_argument("source", type=Path)
        parser.add_argument("snapshot", type=Path)
        args = parser.parse_args(argv[1:])
        out = stamp_published_snapshot(args.source, args.snapshot)
        print(f"Synthetic provenance written to {out}")
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("source", type=Path, help="new, empty directory for synthetic CSVs")
        args = parser.parse_args(argv)
        write_prototype_source(args.source)
        print(f"Synthetic prototype source written to {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
