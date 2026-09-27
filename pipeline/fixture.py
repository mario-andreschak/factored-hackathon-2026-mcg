"""SYNTHETIC TEST FIXTURE — NOT ORGANIZER DATA.

A tiny dataset with the same folder layout and columns as the organizer bucket
(`<table>.csv` for dimensions, `<table>/year=/month=/day=/part-*.csv` for facts),
seeded with known defects so tests can assert exact counts:

  customers    1 exact duplicate row, 1 PK with two versions (later last_updated wins)
  products     1 orphan customer_id, 1 product whose owner differs from the txn customer
  transactions 1 exact re-delivery in a later partition, 1 non-numeric amount,
               1 missing customer_id, 1 Reversed, 1 near-duplicate pair, 1 fraud flag
  late batch   (write_late_batch) a new partition day that carries
               - 1 row whose process_date is two days earlier (late arrival)
               - 1 correction of an existing txn (Pending -> Reversed): must upsert
               - 1 brand-new txn
"""

from __future__ import annotations

import csv
from pathlib import Path

from .common import load_contracts

N_CUSTOMERS = 20
# Data values are intentionally Spanish: they mirror the organizer dataset's vocabulary
# (customer utterances, contact reasons, country "México"). Everything else is English.
TEMPLATES = [
    "no reconozco un cargo de {m} por {a} pesos",
    "me cobraron dos veces en {m}",
    "quiero saber el estado de mi transferencia",
    "necesito bloquear mi tarjeta",
    "cuanto es el saldo de mi cuenta de ahorros",
]
MERCHANTS = ["Oxxo", "Exito", "Mercado Libre", "Rappi", "Carrefour"]


def _defaults(col: str, typ: str, spec: dict) -> str:
    if spec.get("enum"):
        return spec["enum"][0]
    if typ.startswith("DECIMAL"):
        return "0.50"
    if typ == "INTEGER":
        return "1"
    if typ == "BOOLEAN":
        return "False"
    if typ == "DATE":
        return "2025-01-01"
    if typ == "TIMESTAMP":
        return "2025-01-01 00:00:00"
    return f"{col}_x"


def _row(contracts, table, **over) -> dict:
    cols = contracts[table]["columns"]
    row = {c: _defaults(c, s["type"], s) for c, s in cols.items()}
    row.update({k: ("" if v is None else str(v)) for k, v in over.items()})
    return row


def _write(path: Path, contracts, table, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(contracts[table]["columns"]))
        w.writeheader()
        w.writerows(rows)


def _part(root: Path, table: str, day: str, name="part-0000.csv") -> Path:
    y, m, d = day.split("-")
    return root / table / f"year={y}" / f"month={m}" / f"day={d}" / name


def cid(i: int) -> str:
    return f"CUS{i:06d}"


def write_base(root: Path) -> None:
    c = load_contracts()
    root.mkdir(parents=True, exist_ok=True)
    countries = ["México", "Colombia", "Argentina"]
    customers = [_row(c, "customers", customer_id=cid(i), country=countries[i % 3],
                      last_updated="2026-06-01 00:00:00") for i in range(N_CUSTOMERS)]
    customers.append(dict(customers[0]))                                   # exact duplicate
    customers.append({**customers[1], "segment": "Premium",                # newer version wins
                      "last_updated": "2026-06-10 00:00:00"})
    _write(root / "customers.csv", c, "customers", customers)

    products = [_row(c, "products", product_id=f"PRD{i:06d}", customer_id=cid(i)) for i in range(N_CUSTOMERS)]
    products.append(_row(c, "products", product_id="PRD999999", customer_id="CUS999999"))  # orphan
    _write(root / "products.csv", c, "products", products)

    def tx(n, i, day, **over):
        base = dict(transaction_id=f"TXN{n:08d}", customer_id=cid(i),
                    product_id=f"PRD{i:06d}", transaction_date=f"{day} 10:{n % 60:02d}:00",
                    process_date=day, amount=f"{100 + n}.50", merchant_name=MERCHANTS[n % 5],
                    transaction_status="Approved", is_fraud="False")
        return _row(c, "transactions", **{**base, **over})

    day1 = [tx(n, n % N_CUSTOMERS, "2026-06-01") for n in range(40)]
    day1.append(tx(900, 3, "2026-06-01", merchant_name="Rappi", amount="55.00",
                   transaction_date="2026-06-01 12:00:00"))
    day1.append(tx(901, 3, "2026-06-01", merchant_name="Rappi", amount="55.00",   # near-duplicate
                   transaction_date="2026-06-01 12:07:00"))
    day1.append(tx(902, 4, "2026-06-01", transaction_status="Reversed"))
    day1.append(tx(903, 5, "2026-06-01", is_fraud="True"))
    day1.append(tx(904, 6, "2026-06-01", transaction_status="Pending"))
    day1.append(tx(905, 7, "2026-06-01", amount="abc"))                            # cast failure
    day1.append(tx(906, 8, "2026-06-01", customer_id=""))                          # null required
    day1.append(tx(907, 9, "2026-06-01", product_id="PRD000010"))                  # owner mismatch
    _write(_part(root, "transactions", "2026-06-01"), c, "transactions", day1)
    day2 = [tx(n, n % N_CUSTOMERS, "2026-06-02") for n in range(40, 60)]
    day2.append(dict(day1[0]))                                                     # re-delivery
    _write(_part(root, "transactions", "2026-06-02"), c, "transactions", day2)

    # Interactions + transcripts across the time holdout so every split is populated.
    inter, trans = [], []
    days = ["2025-06-01", "2025-11-15", "2026-02-01", "2026-04-01", "2026-06-01"]
    for n in range(60):
        i, day = n % N_CUSTOMERS, days[n % len(days)]
        iid = f"INT{n:08d}"
        inter.append(_row(c, "call_center_interactions", interaction_id=iid, customer_id=cid(i),
                          interaction_date=f"{day} 09:00:00", process_date=day,
                          contact_reason=["Cargo no reconocido", "Consulta de saldo",
                                          "Bloqueo de tarjeta"][n % 3],
                          reason_category=["Transactional", "Product", "Technical"][n % 3],
                          was_resolved=str(n % 2 == 0), was_escalated=str(n % 5 == 0),
                          has_transcript="True"))
        trans.append(_row(c, "call_transcripts", transcript_id=f"TRN{n:08d}", interaction_id=iid,
                          customer_id=cid(i), process_date=day, detected_language="es",
                          customer_text=TEMPLATES[n % len(TEMPLATES)].format(m=MERCHANTS[n % 5], a=100 + n)))
    for n, day in enumerate(days):
        _write(_part(root, "call_center_interactions", day), c, "call_center_interactions",
               [r for r in inter if r["process_date"] == day])
        _write(_part(root, "call_transcripts", day), c, "call_transcripts",
               [r for r in trans if r["process_date"] == day])

    complaints = [_row(c, "complaints", complaint_id=f"CMP{n:08d}", customer_id=cid(n),
                       creation_date="2026-06-01 11:00:00", process_date="2026-06-01",
                       subcategory="Cargo no reconocido", affected_product_id="",
                       origin_interaction_id="", description="cargo no reconocido")
                  for n in range(5)]
    _write(_part(root, "complaints", "2026-06-01"), c, "complaints", complaints)


def write_late_batch(root: Path) -> None:
    """A later partition that arrives after the first pipeline run."""
    c = load_contracts()
    base = dict(
        customer_id=cid(6), product_id=f"PRD{6:06d}", merchant_name="Exito",
        amount="80.00", is_fraud="False")
    rows = [
        _row(c, "transactions", transaction_id="TXN00000904", transaction_date="2026-06-01 10:04:00",
             process_date="2026-06-01", transaction_status="Reversed", **base),        # correction
        _row(c, "transactions", transaction_id="TXN00000950", transaction_date="2026-06-02 18:00:00",
             process_date="2026-06-02", transaction_status="Approved", **base),        # late arrival
        _row(c, "transactions", transaction_id="TXN00000951", transaction_date="2026-06-04 09:00:00",
             process_date="2026-06-04", transaction_status="Approved", **base),        # new
    ]
    _write(_part(root, "transactions", "2026-06-04"), c, "transactions", rows)
