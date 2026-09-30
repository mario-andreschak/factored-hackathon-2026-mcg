"""Generate new fictional CSV source inputs and unit blueprints; never state or a serving build."""
from __future__ import annotations
import argparse
import csv
import hashlib
import hmac
import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

BUNDLE = Path(__file__).resolve().parent
OUT = BUNDLE

def load(path):
    return json.loads(path.read_text(encoding="utf-8"))

def sha(data):
    return hashlib.sha256(data).hexdigest()

def iso(moment):
    return moment.isoformat().replace("+00:00", "Z")

def csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(columns), lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key, "") for key in columns})
    return stream.getvalue().encode("utf-8")

def evaluate(anchor):
    assert anchor.tzinfo is not None and anchor.utcoffset().total_seconds() == 0
    day = anchor.date()
    source_cache = load(BUNDLE / "source_cache.json")
    contract_bytes = (BUNDLE / "source/pipeline/contracts.yaml").read_bytes()
    assert sha(contract_bytes) == source_cache["files"]["pipeline/contracts.yaml"]["sha256"]
    contracts = yaml.safe_load(contract_bytes.decode("utf-8"))["tables"]
    customers, products = [], []
    for index, country, currency in ((0, "México", "MXN"), (1, "Colombia", "COP"), (2, "Argentina", "ARS")):
        customer, product = f"CUS90000{index}", f"PRD90000{index}"
        customers.append({"customer_id": customer, "city": "Ciudad Ficticia", "state": "Estado Ficticio", "country": country,
            "segment": "Basic", "registration_date": f"{day-timedelta(days=200)} 10:00:00", "customer_status": "Active", "last_updated": anchor.strftime("%Y-%m-%d %H:%M:%S")})
        products.append({"product_id": product, "customer_id": customer, "product_type": "Credit Card", "currency": currency,
            "current_balance": "100.00", "opening_date": str(day-timedelta(days=200)), "product_status": "Active", "last_updated": anchor.strftime("%Y-%m-%d %H:%M:%S")})
    specs = [
        (0,0,0,2,"100.00","5.00","MXN","Approved","Tienda Ficticia",0),
        (1,1,1,2,"50.00","0.01","COP","Approved","Mercado Ficticio",0),
        (2,0,0,1,"55.00","2.75","MXN","Approved","Comercio Duplicado Ficticio",0),
        (3,0,0,1,"55.00","2.75","MXN","Approved","Comercio Duplicado Ficticio",1),
        (4,0,0,121,"100.00","5.00","MXN","Approved","Compra Antigua Ficticia",0),
        (5,1,1,1,"100.00","0.02","COP","Pending","Compra Pendiente Ficticia",0),
        (6,2,0,1,"2.00","0.10","MXN","Approved","Producto Ajeno Ficticio",0),
    ]
    transactions = []
    for index, owner, product_owner, age, amount, usd, currency, status, merchant, minute in specs:
        transactions.append({"transaction_id": f"TXN9000000{index}", "customer_id": f"CUS90000{owner}", "product_id": f"PRD90000{product_owner}",
            "transaction_date": f"{day-timedelta(days=age)} 12:{minute:02}:00", "process_date": str(day), "transaction_type": "Purchase",
            "transaction_category": "Retail", "amount": amount, "currency": currency, "amount_usd": usd, "channel": "App",
            "merchant_name": merchant, "merchant_category": "Retail", "transaction_country": customers[owner]["country"],
            "transaction_city": "Ciudad Ficticia", "transaction_status": status, "is_fraud": "false", "fraud_score": "0.50"})
    tables = {"customers": customers, "products": products, "transactions": transactions}
    signals={row["transaction_id"]:{"historical_complaints":"clear_in_snapshot","duplicate_signal":"clear","fraud_score":0.5,"amount_usd":float(row["amount_usd"])} for row in transactions if row["transaction_id"]!="TXN90000006"}
    duplicate_signals={key:dict(value) for key,value in signals.items()}
    duplicate_signals["TXN90000002"]["duplicate_signal"]="persistent"
    risk_blueprint={"schema":"unbound-generated-risk-evidence-blueprint/v1","build_id":None,"source_fingerprint":None,
        "normal_transactions":signals,"persistent_duplicate_transactions":duplicate_signals,
        "bind_rule":"after separately reviewed private pipeline build, author two strict Actions._evidence files with ONLY build_id,source_fingerprint,transactions; bind actual snapshot ID/fingerprint and independently pin each file hash. This unbound wrapper is NOT accepted runtime evidence.",
        "basis":"authored finite synthetic USD/fraud/history signals; no market FX or bank verification"}
    history = {"schema":"authored-closed-synthetic-past-ledger/v1", "generation_anchor_real_utc":iso(anchor),
        "coverage_start_epoch":int(anchor.timestamp())-90000,"coverage_start_utc":iso(anchor-timedelta(hours=25)),
        "closed_through_real_utc":iso(anchor),"cases":[],"receipts":[],"handoffs":[],
        "owner_allowlist":[row["customer_id"] for row in customers],"basis":"explicit authored fictional zero-report past interval, not observed25h operation or bank/customer history",
        "generation_input":"$actual_64_hex_sandbox_ledger_identity_generated_by_future_isolated_StateStore; not minted here",
        "setup_rule":"regenerate this entire fixture in a NEW immutable output at actual future setup time; independently verify closed zero-history, actual fresh generation and no unmapped rows under exclusive fixture writer before dispatch; record actual close/attest times and any closed zero-event setup gap, never silently infer completeness"}
    history_bytes=(json.dumps(history,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
    history_sha=sha(history_bytes)
    provenance="synthetic:present-v1:"+history_sha
    attestation = {"schema":"supported-synthetic-coverage-initialization-blueprint/v1","api":"StateStore.attest_sandbox_coverage(start, provenance)",
        "start":history["coverage_start_epoch"],"provenance":provenance,"provenance_digest_sha256":sha(provenance.encode()),
        "history_manifest_sha256":history_sha,"generation":"$actual_fresh_generation_read_and_verified_before_dispatch",
        "configured_coverage_start_must_equal_start":True,"attested_at":"$actual_time.time_at_future_API_call; never backdated",
        "api_called_now":False,"raw_SQL_or_timestamp_rewrite_permitted":False,
        "limits":"API validates start/prefix/length/generation and stores provenance-string digest; it does NOT itself verify this history hash, closed interval or ledger contents. Reviewed setup harness must do that independently before invoking API under exclusive fixture ownership."}
    relative = f"transactions/year={day.year:04}/month={day.month:02}/day={day.day:02}/present-fixture.csv"
    raw = {"inputs/customers.csv": csv_bytes(contracts["customers"]["columns"], customers),
           "inputs/products.csv": csv_bytes(contracts["products"]["columns"], products),
           "inputs/"+relative: csv_bytes(contracts["transactions"]["columns"], transactions),
           "closed_history.json":history_bytes,"coverage_initialization.json":(json.dumps(attestation,indent=2)+"\n").encode("utf-8"),
           "risk_evidence_blueprint.json":(json.dumps(risk_blueprint,indent=2)+"\n").encode("utf-8")}
    proof = {"schema": "present-relative-fictional-inputs/v1", "generated_at_real_utc": iso(anchor),
        "anchor_rule": "dates are relative to actual UTC generation date; regenerate under a NEW version before later authorized setup, never override runtime time",
        "base_bank_commit": source_cache["base_commit"], "base_flujo_commit": "51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b",
        "new_runtime_source_pin": None, "tables": tables, "counts": {"customers":3,"products":3,"transactions":7,"ownership_valid":6,"ownership_invalid":1},
        "generator_source_sha256":sha((BUNDLE/"generate_fixture.py").read_bytes()),"contracts_source_sha256":sha(contract_bytes),
        "source_files_sha256": {name: sha(data) for name,data in raw.items()}, "transaction_source_key": relative,
        "serving_build_created": False, "new_build_id": None, "new_source_fingerprint": None,
        "unit_blueprints_are_fixture_seeded_not_observed_actions": True,
        "authority_rule": "later remote unit harness may seed fictional authorized test identity at actual setup time, disclose it; no login/customer authority proof; no JWT/session/nonce/auth expiry may be backdated",
        "stock_coverage_rule": "default fresh ledger is incomplete. Separate allowed authored closed synthetic past25h fixture may use existing attest_sandbox_coverage API after independent history/hash/generation verification; actual attested_at/auth/TTL/case/receipt/HOF stay real, no raw row/timestamp rewrite. This is seeded synthetic coverage, not observed operation or customer acceptance",
        "coverage_initialization_blueprint":attestation,"closed_history_manifest_sha256":history_sha,
        "scenario_subset": ["owned list/detail and foreign denial", "product-owner mismatch exclusion", "real age121 and pending-status guards", "absent-coverage normal prepare and selected missing_evidence HOF in separate generation", "explicit supported synthetic coverage permits normal prepare/confirm plus independent receipt read in a fresh reviewed hosted fixture; no successful receipt preseed", "persistent duplicate selected HOF", "general emergency/customer_request HOF", "exact-key HOF retry/conflicts; new UUID is new identity", "saved receipt projection unit blueprints only; distinct from future actual confirmed hosted receipt"],
        "deferred": ["normal hosted intake without independently verified/attested synthetic coverage", "joined real authority/login", "model intent and ES/PT language acceptance", "future-held-out evaluation and virtual risk/event timeline", "controlled lost-response/restart execution"],
        "runtime_http_tools_models_s3_state_actions_joined_human": 0}
    normal = transactions[0]
    # This key/reference is solely a fictional unit projection, never a live secret/reference.
    unit_reference = "txn_"+hmac.new(b"UNIT-FIXTURE-ONLY-NOT-LIVE-SECRET", normal["transaction_id"].encode(), hashlib.sha256).hexdigest()[:12]
    facts = {"transaction_reference": unit_reference, "transaction_date": normal["transaction_date"].replace(" ","T"), "process_date": normal["process_date"],
        "amount": normal["amount"], "currency":normal["currency"],"status":normal["transaction_status"],"merchant":normal["merchant_name"],"transaction_type":"Purchase","channel":"App","product":"Credit Card"}
    receipt = {"id":"CMP-SBX-MIN00001","kind":"simulated_intake","simulated":True,"snapshot":"unit-blueprint-present-v1","created_at":iso(anchor),"status":"received","transaction":facts}
    packet = {"schema":"banking-sandbox-handoff/v1","transaction":facts,"transaction_provenance":{"source":"owned_serving_snapshot","snapshot":receipt["snapshot"],"as_of":iso(anchor)},"reason":"missing_evidence","unanswered_questions":["¿Qué información falta para continuar?"],"human_responded":False}
    unit = {"schema":"private-fixture-seeded-unit-blueprints/v1","disclosure":"NOT saved rows or observed receipts. Fictional query-row doubles for exact pure helper validation only; no SQLite, auth, tools or action engine initialized.",
        "created_at_real":anchor.timestamp(),"owner":normal["customer_id"],"transaction_id":normal["transaction_id"],"facts":facts,"case_receipt":receipt,"selected_handoff_packet":packet,
        "general_handoff_packet":{**packet,"transaction":None,"transaction_provenance":None,"reason":"customer_request"},
        "fixture_binding":"unit-fixture-binding-not-live-authority","request_id":"11111111-1111-4111-8111-111111111111"}
    return proof, unit, raw

def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--refresh-draft", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="new private source-input output only; no build/state/API execution")
    args = parser.parse_args()
    if args.output_dir:
        assert not args.refresh_draft,"refresh is private authoring only"
        OUT=args.output_dir.resolve()
        if not args.check:
            assert not OUT.exists(),"new generation requires a fresh output directory"
            OUT.mkdir(parents=True)
    if args.check or args.refresh_draft:
        current = load(OUT/"fixture_inputs.json")
        anchor = datetime.fromisoformat(current["generated_at_real_utc"].replace("Z","+00:00"))
    else:
        assert not (OUT/"fixture_inputs.json").exists(), "preserve this snapshot; generate a new version"
        anchor = datetime.now(timezone.utc).replace(microsecond=0)
    proof, unit, raw = evaluate(anchor)
    if args.check:
        assert proof == load(OUT/"fixture_inputs.json") and unit == load(OUT/"unit_blueprints.json")
        assert all((OUT/name).read_bytes()==data for name,data in raw.items())
    else:
        if args.refresh_draft:
            assert not (OUT/"fixture_pin.json").exists(),"preserve pinned fixture"
            archive=OUT/"drafts";archive.mkdir(exist_ok=True)
            for filename in ("fixture_inputs.json","unit_blueprints.json","validation.json"):
                previous=OUT/filename
                if previous.exists():
                    archived=archive/(filename+"."+sha(previous.read_bytes()))
                    if not archived.exists():archived.write_bytes(previous.read_bytes())
            # Validation output is overwritten only after explicitly archiving this draft.
            if (OUT/"validation.json").exists():(OUT/"validation.json").unlink()
        for name,data in raw.items():
            target=OUT/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        (OUT/"fixture_inputs.json").write_text(json.dumps(proof,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        (OUT/"unit_blueprints.json").write_text(json.dumps(unit,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"fixture_sha256":sha((OUT/"fixture_inputs.json").read_bytes()),"anchor":proof["generated_at_real_utc"],"counts":proof["counts"],"serving_build_or_state_created":False}))

if __name__ == "__main__":
    main()
