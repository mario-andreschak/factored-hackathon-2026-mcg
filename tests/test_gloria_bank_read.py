"""Real generated CSV -> pipeline -> MCP repository -> admitted read adapter."""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import shutil
import time
from types import SimpleNamespace
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import pytest

from banking_mcp.config import Config
from banking_mcp.security import BankError, Principal
from banking_mcp.service import Service
from frontend.server.config import Settings
from frontend.server.repository import Repository as PublicRepository
from frontend.server.state import State
from gloria_workflow.bank_read import OwnedBankReads, assert_bank_principal
from pipeline.__main__ import main
from pipeline.fixture import cid, write_base


def rewrite_csv(path, mutate):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    for row in rows:
        mutate(row)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    root = tmp_path_factory.mktemp("gloria-generated-bank")
    write_base(root / "source")
    rewrite_csv(root / "source/products.csv", lambda row: row.update(
        product_number="400000000000" + row["product_id"][-4:], product_type="Cuenta Ahorro"))
    for path in (root / "source/transactions").rglob("*.csv"):
        rewrite_csv(path, lambda row: row.update(fraud_score="20.00", amount_usd="25.00",
            transaction_city="Guadalajara", channel="POS", transaction_type="Purchase"))
    for path in (root / "source/complaints").rglob("*.csv"):
        rewrite_csv(path, lambda row: row.update(complaint_id="CMP-HISTORY-" + row["customer_id"][-4:],
            status="Closed", category="Transactions", subcategory="Cargo no reconocido"))
    assert main(["run", "--source", str(root / "source"), "--out", str(root / "data"),
                 "--reports", str(root / "reports")]) == 0
    return root


@pytest.fixture
def bank(dataset, tmp_path):
    source, data = tmp_path / "source", tmp_path / "data"
    shutil.copytree(dataset / "source", source)
    shutil.copytree(dataset / "data", data)
    key = Ed25519PrivateKey.generate()
    pem = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    now = [datetime(2026, 6, 15, 12, tzinfo=timezone.utc).timestamp()]
    evidence = tmp_path / "evidence.json"
    rates = tmp_path / "generated-event-rates.csv"
    rates.write_text("date,currency,usd_rate\n2026-06-01,MXN,0.10\n2026-06-02,MXN,0.10\n", encoding="utf-8")
    config = Config(data_dir=data, state_db=tmp_path / "ledger.sqlite3", service_token="synthetic-read-fixture-secret" * 2,
                    public_keys={"fixture": pem}, principal_customers={"subject-a": cid(3), "subject-b": cid(4)},
                    sandbox_report_coverage_start=int(now[0]) - 90000, synthetic_evidence_file=evidence,
                    event_rates_file=rates, event_rates_sha256=hashlib.sha256(rates.read_bytes()).hexdigest())
    service = Service(config)
    service.actions.clock = lambda: now[0]
    service.store.attest_sandbox_coverage(config.sandbox_report_coverage_start, "synthetic:gloria-bank-read-fixture")
    state = State(tmp_path / "frontend")
    state.bind("mexico", cid(3))
    public = PublicRepository(Settings(data_dir=data, state_dir=tmp_path / "frontend", static_dir=tmp_path / "static"), state)
    principal = Principal("subject-a", cid(3), str(uuid.uuid4()), str(uuid.uuid4()), int(time.time()) + 3600)
    adapter = OwnedBankReads(service, public, principal, source_root=source, clock=lambda: now[0])
    snapshot = service.repository.snapshot()
    rows = adapter._owned_rows(snapshot)
    evidence.write_text(json.dumps({"build_id": snapshot.id, "source_fingerprint": snapshot.source_fingerprint,
        "transactions": {row["transaction_id"]: {"historical_complaints": "clear_in_snapshot", "duplicate_signal": "clear",
            "fraud_score": 20, "amount_usd": 25} for row in rows}}))
    yield SimpleNamespace(adapter=adapter, service=service, public=public, principal=principal,
                          source=source, data=data, now=now, snapshot=snapshot, rows=rows, rates=rates)
    service.close()


def read(bank, name, **args):
    return asyncio.run(bank.adapter.read(name, args))


def ref(bank, raw="TXN00000043"):
    return bank.public.reference("txn", bank.principal.customer, raw)


def create_case(bank, raw="TXN00000003"):
    prepared = bank.service.actions.prepare(bank.principal, raw, bank.snapshot.id, str(uuid.uuid4()))
    assert prepared["decision"] == "intake"
    created = bank.service.actions.confirm(bank.principal, prepared["pending_handle"], True)
    assert created["state"] == "created"
    bank.now[0] += 1
    return created["receipt"]


def republish(bank):
    """New real pipeline build represents new evidence, never edited manifests."""
    assert main(["run", "--source", str(bank.source), "--out", str(bank.data),
                 "--reports", str(bank.data.parent / "changed-reports")]) == 0
    bank.adapter = OwnedBankReads(bank.service, bank.public, bank.principal,
        source_root=bank.source, clock=lambda: bank.now[0])
    bank.snapshot = bank.service.repository.snapshot()
    bank.rows = bank.adapter._owned_rows(bank.snapshot)


def target_source(bank, raw="TXN00000043"):
    row = next(row for row in bank.rows if row["transaction_id"] == raw)
    return bank.source / row["_source_file"]


def append_row(path, mutate):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    row = dict(rows[0])
    mutate(row)
    with path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields).writerow(row)


def test_source_verified_owned_target_has_private_risk_without_raw_identity(bank):
    result = read(bank, "get_transaction", transaction_id=ref(bank), snapshot_id=bank.snapshot.id)
    assert result["status"] == "ok" and result["source_verified"] is True, result
    assert result["transaction"]["transaction_id"] == ref(bank)
    assert result["transaction"]["product_last4"] == "0003"
    assert result["risk_signals"]["fraud_score"] == 20
    assert result["risk_signals"]["amount_usd"] == 14.35
    assert result["risk_signals"]["amount_usd_provenance"]["source"] == "pinned_event_rates"
    assert result["risk_signals"]["duplicate_signal"] == "clear"
    assert "customer_id" not in repr(result) and "product_number" not in repr(result)
    assert "TXN00000043" not in repr(result) and cid(3) not in repr(result)
    assert "4000000000000003" not in repr(result)


@pytest.mark.parametrize("slots,count", [
    ({"amount": 143.50, "currency": "MXN", "transaction_type": "Purchase", "channel": "POS",
      "city": "Guadalajara", "country": "México", "product_hint": "cuenta", "product_last4": "0003"}, 1),
    ({"amount": 143.50, "channel": "ATM"}, 0),
    ({"amount": 143.50, "transaction_type": "Withdrawal"}, 0),
    ({"amount": 143.50, "city": "Bogotá"}, 0),
    ({"amount": 143.50, "country": "Colombia"}, 0),
    ({"amount": 143.50, "product_last4": "0004"}, 0),
    ({"amount": 143.50, "product_hint": "crédito"}, 0),
])
def test_all_declared_filters_apply_before_total_and_sole_selection(bank, slots, count):
    result = read(bank, "search_transactions", slots=slots)
    assert result["status"] == "ok", result
    assert result["match_count"] == count
    assert len(result["candidates"]) == count
    assert result["search_context"]["coverage_complete"] is True


@pytest.mark.parametrize("product_type,hints", [
    ("Tarjeta Crédito", [("tarjeta", 1), ("cartão", 1), ("cartão de crédito", 1),
                        ("crédito", 1), ("tarjeta de débito", 0), ("débito", 0), ("conta", 0)]),
    ("Cartão Crédito", [("tarjeta crédito", 1), ("cartão", 1), ("crédito", 1),
                       ("cartão de débito", 0), ("cuenta", 0)]),
    ("Tarjeta Débito", [("cartão de débito", 1), ("tarjeta", 1), ("débito", 1),
                       ("crédito", 0), ("tarjeta crédito", 0), ("conta", 0)]),
    ("Cartão Débito", [("tarjeta de débito", 1), ("cartão", 1), ("débito", 1),
                      ("cartão de crédito", 0), ("cuenta", 0)]),
    ("Cuenta Ahorro", [("cuenta", 1), ("conta", 1), ("conta poupança", 1),
                      ("cuenta de ahorros", 1), ("poupança", 1), ("conta corrente", 0), ("cartão", 0)]),
    ("Conta Poupança", [("cuenta ahorro", 1), ("conta", 1), ("ahorro", 1),
                       ("cuenta corriente", 0), ("tarjeta", 0)]),
    ("Cuenta Corriente", [("conta corrente", 1), ("cuenta", 1), ("corrente", 1),
                         ("poupança", 0), ("cuenta ahorro", 0), ("cartão", 0)]),
    ("Conta Corrente", [("cuenta corriente", 1), ("conta", 1), ("corriente", 1),
                       ("conta poupança", 0), ("tarjeta", 0)]),
])
def test_owned_product_filters_translate_es_pt_without_dropping_qualifiers(bank, product_type, hints):
    rewrite_csv(bank.source / "products.csv", lambda row: row.update(product_type=product_type)
                if row["customer_id"] == bank.principal.customer else None)
    republish(bank)
    # A wrong or unknown hint must reject the otherwise sole amount candidate.
    for hint, count in hints + [("cartão dragón", 0), ("cuenta imposible", 0), ("de", 0), ("1234", 0)]:
        result = read(bank, "search_transactions", slots={"amount": 143.50, "product_hint": hint})
        assert result["status"] == "ok", (hint, result)
        assert result["match_count"] == count, (product_type, hint, result)
        assert len(result["candidates"]) == count
        assert result["search_context"]["coverage_complete"] is True
        if count:
            assert result["candidates"][0]["transaction_id"] == ref(bank)
            assert result["candidates"][0]["product_type"] == product_type


@pytest.mark.parametrize("reference", ["txn_" + "f" * 24, "TXN00000043"])
def test_unknown_and_raw_identifiers_never_select_an_owned_target(bank, reference):
    assert read(bank, "get_transaction", transaction_id=reference) == {"status": "error", "code": "reference_unavailable"}


def test_foreign_owner_reference_cannot_reveal_target(bank):
    foreign = bank.public.reference("txn", cid(4), "TXN00000044")
    assert read(bank, "get_transaction", transaction_id=foreign) == {"status": "error", "code": "reference_unavailable"}
    with pytest.raises(BankError, match="authorization_denied"):
        assert_bank_principal(bank.service, Principal("subject-a", cid(4), "bad", "bad", int(time.time()) + 3600))


def test_model_identity_arguments_are_rejected_before_repository(bank, monkeypatch):
    monkeypatch.setattr(bank.service.repository, "snapshot", lambda: pytest.fail("identity override must precede private reads"))
    assert read(bank, "search_transactions", customer_id=cid(4), slots={}) == {"status": "error", "code": "authorization_denied"}


def test_pinned_source_mutation_prevents_verified_target(bank):
    path = next((bank.source / "transactions/year=2026/month=06/day=02").glob("*.csv"))
    rewrite_csv(path, lambda row: row.update(amount="99999.00") if row["transaction_id"] == "TXN00000043" else None)
    assert read(bank, "get_transaction", transaction_id=ref(bank)) == {"status": "error", "code": "source_verification_unavailable"}


def test_closed_historical_complaint_never_becomes_target_existing_case(bank):
    result = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert result["status"] == "ok", result
    assert result["duplicate_check"] == "clear_in_snapshot"
    assert result["complaints"] == [] and result["historical_candidates"] == []
    assert result["report_window"]["prior_distinct_verified_count"] == 0
    listing = read(bank, "list_customer_complaints")
    assert listing["match_count"] == 1 and listing["coverage_complete"] is True
    historical = listing["complaints"][0]
    assert historical["transaction_id"] is None and historical["linkage"] == "unknown"
    assert historical["complaint_id"] == "CMP-HISTORY-0003"
    assert "affected_product_id" not in repr(listing)
    assert read(bank, "get_complaint", complaint_id="CMP-HISTORY-0004") == {"status": "error", "code": "reference_unavailable"}


def test_exact_sandbox_receipt_is_distinct_from_historical_linkage(bank):
    receipt = create_case(bank, "TXN00000043")
    related = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert related["duplicate_check"] == "exact_open_case"
    assert related["complaints"][0]["complaint_id"] == receipt["id"]
    assert related["complaints"][0]["transaction_id"] == ref(bank)
    assert related["report_window"]["prior_distinct_verified_count"] == 0
    status = read(bank, "get_complaint", complaint_id=receipt["id"])
    assert status["complaint"]["linkage"] == "exact_sandbox"
    assert status["complaint"]["status"] == "Open"
    assert status["complaint"]["snapshot_id"] == receipt["snapshot"]
    assert status["complaint"]["transaction"]["amount"] == receipt["transaction"]["amount"]
    assert "transaction_reference" not in repr(status)


def test_missing_prior_receipt_returns_unknown_count_without_lower_clearance(bank):
    receipt = create_case(bank)
    with bank.service.store.connect() as db:
        db.execute("DELETE FROM sandbox_case_receipts WHERE case_id=?", (receipt["id"],))
    related = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert related["status"] == "ok", related
    assert related["report_window"]["coverage_complete"] is False
    assert related["report_window"]["prior_distinct_verified_count"] is None
    assert read(bank, "list_customer_complaints") == {"status": "error", "code": "action_unverified"}


def test_unattested_empty_ledger_cannot_prove_complete_zero_history(bank):
    with bank.service.store.connect() as db:
        db.execute("DELETE FROM sandbox_coverage")
    related = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert related["report_window"]["coverage_complete"] is False
    assert related["report_window"]["prior_distinct_verified_count"] is None
    assert read(bank, "list_customer_complaints") == {"status": "error", "code": "risk_data_unavailable"}


def test_revocation_after_private_work_blocks_return(bank, monkeypatch):
    original = bank.adapter._products
    def revoke(*args):
        result = original(*args)
        bank.service.store.revoke(bank.principal.session)
        return result
    monkeypatch.setattr(bank.adapter, "_products", revoke)
    assert read(bank, "get_transaction", transaction_id=ref(bank)) == {"status": "error", "code": "authorization_denied"}


def test_missing_history_file_never_becomes_empty_history(bank):
    (bank.snapshot.build / "silver/complaints.parquet").unlink()
    assert read(bank, "list_customer_complaints") == {"status": "error", "code": "data_unavailable"}


def test_search_rejects_dates_outside_disclosed_snapshot(bank):
    assert read(bank, "search_transactions", slots={"date_from": "2026-01-01", "date_to": "2026-01-02"}) == {
        "status": "error", "code": "invalid_date_window"}


def test_reads_do_not_create_pending_cases_or_handoffs(bank):
    for name, args in (("search_transactions", {"slots": {"amount": 143.5}}),
                       ("get_transaction", {"transaction_id": ref(bank)}),
                       ("get_related_complaints", {"transaction_id": ref(bank)}),
                       ("list_customer_complaints", {})):
        assert read(bank, name, **args)["status"] == "ok"
    with bank.service.store.connect() as db:
        for table in ("action_pending", "sandbox_cases", "sandbox_handoffs"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_profile_projects_source_first_name_and_owned_opaque_product(bank):
    profile = read(bank, "get_customer_profile")
    assert profile["status"] == "ok" and profile["first_name"] == "first_name_x"
    assert profile["products"][0]["product_id"] == bank.public.reference("prod", cid(3), "PRD000003")
    assert profile["products"][0]["product_last4"] == "0003"
    assert "PRD000003" not in repr(profile) and "4000000000000003" not in repr(profile)


@pytest.mark.parametrize("seconds,duplicate", [(120, True), (121, False)])
def test_nearby_duplicate_boundary_ignores_merchant_and_product(bank, seconds, duplicate):
    products = bank.source / "products.csv"
    append_row(products, lambda row: row.update(product_id="PRD-SECOND-OWNED", customer_id=cid(3), product_number="4000000000004321"))
    path = target_source(bank)
    original = next(row for row in bank.rows if row["transaction_id"] == "TXN00000043")
    from datetime import timedelta
    append_row(path, lambda row: row.update(transaction_id="TXN-NEARBY", customer_id=cid(3),
        product_id="PRD-SECOND-OWNED", amount=str(original["amount"]), currency=original["currency"],
        transaction_date=(original["transaction_date"] + timedelta(seconds=seconds)).isoformat(" "),
        process_date=original["process_date"].isoformat(), merchant_name="Different fictional merchant"))
    republish(bank)
    result = read(bank, "get_transaction", transaction_id=ref(bank))
    assert result["status"] == "ok", result
    expected = [ref(bank, "TXN-NEARBY")] if duplicate else None
    assert result["transaction"]["possible_duplicate_of"] == expected
    assert result["risk_signals"]["duplicate_signal"] == ("persistent" if duplicate else "clear")


@pytest.mark.parametrize("field,value", [("merchant_name", "Conflicting merchant"),
    ("fraud_score", "85.00"), ("transaction_city", "Otra ciudad")])
def test_latest_process_date_ties_retain_conflicts_in_all_business_facts(bank, field, value):
    path = target_source(bank)
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    target = next(row for row in rows if row["transaction_id"] == "TXN00000043")
    conflict = {**target, field: value}
    with path.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields).writerow(conflict)
    republish(bank)
    result = read(bank, "get_transaction", transaction_id=ref(bank))
    assert result["status"] == "ok", result
    assert result["transaction"]["conflicting_duplicate"] is True
    assert result["risk_signals"]["duplicate_signal"] == "persistent"
    with pytest.raises(BankError, match="duplicate_review"):
        bank.adapter.assert_action_eligible(ref(bank), bank.snapshot.id)


def test_earlier_corrected_version_does_not_create_false_conflict(bank):
    path = target_source(bank)
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        fields, rows = reader.fieldnames, list(reader)
    target = next(row for row in rows if row["transaction_id"] == "TXN00000043")
    earlier = bank.source / "transactions/year=2026/month=06/day=01/part-0000.csv"
    with earlier.open("a", newline="", encoding="utf-8") as stream:
        csv.DictWriter(stream, fieldnames=fields).writerow({**target, "process_date": "2026-06-01", "merchant_name": "Older corrected merchant"})
    republish(bank)
    result = read(bank, "get_transaction", transaction_id=ref(bank))
    assert result["status"] == "ok", result
    assert result["transaction"]["conflicting_duplicate"] is False
    assert result["risk_signals"]["duplicate_signal"] == "clear"


def test_missing_bronze_marker_never_proves_complete_search_or_duplicate_absence(bank):
    (bank.data / "bronze/source_objects.json").unlink()
    for name, args in (("search_transactions", {"slots": {"amount": 143.5}}),
                       ("get_transaction", {"transaction_id": ref(bank)})):
        assert read(bank, name, **args) == {"status": "error", "code": "duplicate_coverage_unavailable"}


def test_retained_verified_attempt_prevents_case_row_deletion_from_lowering_history(bank):
    receipt = create_case(bank)
    with bank.service.store.connect() as db:
        db.execute("DELETE FROM sandbox_cases WHERE id=?", (receipt["id"],))
    related = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert related["report_window"]["coverage_complete"] is False
    assert related["report_window"]["prior_distinct_verified_count"] is None
    assert read(bank, "list_customer_complaints") == {"status": "error", "code": "action_unverified"}


@pytest.mark.parametrize("status", ["Open", "In Process", "Unclassified"])
def test_possible_open_historical_complaint_stays_unknown_linkage(bank, status):
    for path in (bank.source / "complaints").rglob("*.csv"):
        rewrite_csv(path, lambda row: row.update(status=status) if row["customer_id"] == cid(3) else None)
    republish(bank)
    related = read(bank, "get_related_complaints", transaction_id=ref(bank))
    assert related["status"] == "ok", related
    assert related["duplicate_check"] == "historical_uncertain"
    assert related["complaints"] == []
    assert related["historical_candidates"][0]["transaction_id"] is None
    assert related["historical_candidates"][0]["linkage"] == "unknown"
    evidence = bank.adapter.action_evidence("TXN00000043", bank.snapshot.id)
    assert evidence["historical_complaints"] == "uncertain"


def test_action_evidence_is_exact_fresh_shape_and_retains_high_source_risk(bank):
    rewrite_csv(target_source(bank), lambda row: row.update(fraud_score="85.00") if row["transaction_id"] == "TXN00000043" else None)
    republish(bank)
    (bank.snapshot.build / "silver/complaints.parquet").unlink()
    evidence = bank.adapter.action_evidence("TXN00000043", bank.snapshot.id)
    assert evidence == {"historical_complaints": "uncertain", "duplicate_signal": "clear", "fraud_score": 85, "amount_usd": 14.35}
    with pytest.raises(BankError, match="reference_unavailable"):
        bank.adapter.action_evidence("TXN00000044", bank.snapshot.id)


def test_missing_fraud_risk_stays_null(bank):
    rewrite_csv(target_source(bank), lambda row: row.update(fraud_score="") if row["transaction_id"] == "TXN00000043" else None)
    republish(bank)
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["status"] == "ok" and target["risk_data_complete"] is False
    assert target["risk_signals"]["fraud_score"] is None
    with pytest.raises(BankError, match="risk_data_unavailable"):
        bank.adapter.assert_action_eligible(ref(bank), bank.snapshot.id)


def test_missing_owned_last_four_is_explicit_and_never_ignored(bank):
    rewrite_csv(bank.source / "products.csv", lambda row: row.update(product_number="") if row["customer_id"] == cid(3) else None)
    republish(bank)
    assert read(bank, "search_transactions", slots={"amount": 143.5, "product_last4": "0003"}) == {
        "status": "error", "code": "product_last4_unavailable"}
    assert read(bank, "get_customer_profile")["products"][0]["product_last4"] is None


def test_rejected_owned_source_row_cannot_disappear_into_complete_zero_or_unique_search(bank):
    append_row(target_source(bank), lambda row: row.update(transaction_id="TXN-REJECTED-OWNED", customer_id=cid(3),
        product_id="PRD000003", amount="invalid-amount"))
    assert main(["run", "--source", str(bank.source), "--out", str(bank.data),
                 "--reports", str(bank.data.parent / "changed-reports")]) == 0
    bank.adapter = OwnedBankReads(bank.service, bank.public, bank.principal,
        source_root=bank.source, clock=lambda: bank.now[0])
    assert read(bank, "search_transactions", slots={"amount": 143.5}) == {
        "status": "error", "code": "search_coverage_incomplete"}


def test_search_money_uses_signed_decimal_and_zero_requires_exact_match(bank):
    rewrite_csv(target_source(bank), lambda row: row.update(amount="-25.00") if row["transaction_id"] == "TXN00000043" else None)
    republish(bank)
    result = read(bank, "search_transactions", slots={"amount": -25})
    assert result["match_count"] == 1 and result["candidates"][0]["transaction_id"] == ref(bank)
    assert read(bank, "search_transactions", slots={"amount": 0})["match_count"] == 0


def test_recent_interactions_are_owned_categories_without_transcript_content(bank):
    result = read(bank, "get_recent_interactions", days=90)
    assert result["status"] == "ok" and result["interactions"]
    assert set(result["interactions"][0]) == {"interaction_date", "contact_reason", "was_resolved", "was_escalated"}
    assert "customer_text" not in repr(result) and "agent_text" not in repr(result) and cid(3) not in repr(result)
    assert read(bank, "get_recent_interactions")["interactions"] == []
    assert read(bank, "get_recent_interactions", days=0) == {"status": "error", "code": "invalid_filter"}


def test_different_frontend_and_bank_dataset_is_rejected_before_any_private_read(bank, monkeypatch, tmp_path):
    monkeypatch.setattr(bank.service.repository, "snapshot", lambda: pytest.fail("mixed dataset admission must precede read"))
    public = SimpleNamespace(settings=SimpleNamespace(data_dir=tmp_path / "unrelated-data"))
    with pytest.raises(ValueError, match="share a dataset"):
        OwnedBankReads(bank.service, public, bank.principal, source_root=bank.source)


def test_complaint_only_open_filter_keeps_exact_case_and_excludes_closed_history(bank):
    receipt = create_case(bank)
    listed = read(bank, "list_customer_complaints", only_open=True)
    assert listed["match_count"] == 1 and listed["complaints"][0]["complaint_id"] == receipt["id"]


def install_rates(bank, text, *, pin=True):
    bank.rates.write_text(text, encoding="utf-8")
    if pin:
        values = bank.service.config.model_dump()
        values["event_rates_sha256"] = hashlib.sha256(bank.rates.read_bytes()).hexdigest()
        bank.service.config = Config(**values)


@pytest.mark.parametrize("body", [
    "2026-06-01,MXN,0.10\n",                    # wrong event date
    "2026-06-02,COP,0.10\n",                    # wrong currency pair
    "2026-06-02,MXN,0\n",
    "2026-06-02,MXN,-0.10\n",
    "2026-06-02,MXN,NaN\n",
    "2026-06-02,MXN,Infinity\n",
    "2026-06-02,MXN,0.10\n2026-06-02,MXN,0.10\n",  # duplicate pairs are ambiguous
])
def test_invalid_or_uncovered_event_rate_never_uses_supplied_source_usd(bank, body):
    install_rates(bank, "date,currency,usd_rate\n" + body)
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["status"] == "ok" and target["source_verified"] is True
    assert target["risk_signals"]["amount_usd"] is None
    assert target["risk_signals"]["amount_usd_provenance"]["source"] == "unavailable"
    assert target["risk_data_complete"] is False
    assert bank.adapter.action_evidence("TXN00000043", bank.snapshot.id)["amount_usd"] is None
    with pytest.raises(BankError, match="risk_data_unavailable"):
        bank.adapter.assert_action_eligible(ref(bank), bank.snapshot.id)


def test_event_rate_hash_is_verified_each_read_without_cached_clearance(bank):
    assert read(bank, "get_transaction", transaction_id=ref(bank))["risk_signals"]["amount_usd"] == 14.35
    install_rates(bank, "date,currency,usd_rate\n2026-06-02,MXN,0.01\n", pin=False)
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["risk_signals"]["amount_usd"] is None and target["risk_data_complete"] is False


def test_absent_rates_configuration_keeps_non_usd_risk_unknown(bank):
    values = bank.service.config.model_dump()
    values.update(event_rates_file=None, event_rates_sha256=None)
    bank.service.config = Config(**values)
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["risk_signals"]["amount_usd"] is None and target["risk_data_complete"] is False


def test_exact_usd_uses_actual_amount_without_missing_or_supplied_fx(bank):
    rewrite_csv(target_source(bank), lambda row: row.update(currency="USD", amount_usd="1.00") if row["transaction_id"] == "TXN00000043" else None)
    republish(bank)
    bank.rates.unlink()
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["risk_signals"]["amount_usd"] == 143.5
    assert target["risk_signals"]["amount_usd_provenance"]["source"] == "exact_usd"
    assert target["risk_data_complete"] is True


def test_verified_event_rate_covers_missing_source_usd_observation(bank):
    rewrite_csv(target_source(bank), lambda row: row.update(amount_usd="") if row["transaction_id"] == "TXN00000043" else None)
    republish(bank)
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["risk_signals"]["amount_usd"] == 14.35 and target["risk_data_complete"] is True


@pytest.mark.parametrize("patch", [
    {"event_rates_sha256": None}, {"event_rates_file": None},
    {"event_rates_file": Path("relative-rates.csv")}, {"event_rates_sha256": "wrong-hash"}])
def test_rate_configuration_requires_absolute_path_and_full_hash_together(bank, patch):
    values = bank.service.config.model_dump()
    values.update(patch)
    with pytest.raises(ValueError):
        Config(**values)


def test_verified_rate_provenance_and_scalar_risk_stay_out_of_model_inputs(bank):
    from gloria_workflow.prompts import safe_structured_data
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    projected = safe_structured_data(target)
    assert "rates_sha256" not in repr(projected)
    assert "amount_usd" not in repr(projected) and "fraud_score" not in repr(projected)
    assert str(bank.rates) not in repr(target)


def test_high_event_rate_amount_cannot_be_lowered_by_supplied_source_usd(bank):
    install_rates(bank, "date,currency,usd_rate\n2026-06-02,MXN,10.00\n")
    target = read(bank, "get_transaction", transaction_id=ref(bank))
    assert target["risk_signals"]["amount_usd"] == 1435
    with pytest.raises(BankError, match="handoff_required"):
        bank.adapter.assert_action_eligible(ref(bank), bank.snapshot.id)
