"""Produce aggregate-only hackathon S3 evidence.

Requires boto3. Reads S3credentials.env (BucketName, Region, AccessKeyID,
SecretAccessKey) and writes no source records or credential values.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import closing
from pathlib import Path

import boto3
from botocore.config import Config


CUTOFF = "2026-06-17"
PARTITION_DATE = re.compile(r"year=(\d{4})/month=(\d{2})/day=(\d{2})/")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip().strip('"').strip("'")
    required = {"BucketName", "Region", "AccessKeyID", "SecretAccessKey"}
    if missing := required - values.keys():
        raise ValueError(f"Missing env names: {', '.join(sorted(missing))}")
    return values


def counter_json(counter: Counter) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, default=Path("S3credentials.env"))
    parser.add_argument("--output", type=Path, default=Path("docs/DATA_PROFILE_AGGREGATES_2026-09-26.json"))
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    values = load_env(args.env)
    client = boto3.client(
        "s3",
        region_name=values["Region"],
        aws_access_key_id=values["AccessKeyID"],
        aws_secret_access_key=values["SecretAccessKey"],
        config=Config(connect_timeout=10, read_timeout=120,
                      max_pool_connections=max(args.workers + 4, 20),
                      retries={"max_attempts": 4}),
    )
    bucket = values["BucketName"]
    inventory: dict[str, list[dict]] = defaultdict(list)
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="data/"):
        for obj in page.get("Contents", []):
            table = obj["Key"].split("/")[1].removesuffix(".csv")
            inventory[table].append({"key": obj["Key"], "bytes": obj["Size"]})
    result: dict = {
        "method": "Direct read-only S3 streaming; aggregate output only; no raw records retained",
        "dataset_cutoff": CUTOFF,
        "inventory": {
            table: {"objects": len(objects), "bytes": sum(x["bytes"] for x in objects)}
            for table, objects in sorted(inventory.items())
        },
        "tables": {},
    }

    def rows_for(key: str):
        response = client.get_object(Bucket=bucket, Key=key)
        with closing(response["Body"]) as body:
            reader = csv.DictReader(io.TextIOWrapper(body, encoding="utf-8-sig", newline=""))
            columns = tuple(reader.fieldnames or ())
            yield columns, reader

    def run_partitions(table: str, scan):
        keys = [x["key"] for x in inventory[table]]
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(scan, key) for key in keys]
            for index, future in enumerate(as_completed(futures), 1):
                yield future.result()
                if index % 250 == 0 or index == len(keys):
                    print(f"{table}: {index}/{len(keys)} objects", flush=True)

    # Single-file master tables. Keep only ID-to-country/owner maps for FK checks.
    customers: dict[str, str] = {}
    cust = {"rows": 0, "duplicate_ids": 0, "countries": Counter(), "segments": Counter(),
            "status": Counter(), "credit_score_nonempty": 0, "income_nonempty": 0,
            "last_updated_after_cutoff": 0, "columns": []}
    for columns, reader in rows_for("data/customers.csv"):
        cust["columns"] = list(columns)
        for row in reader:
            cust["rows"] += 1
            cid = row["customer_id"]
            cust["duplicate_ids"] += cid in customers
            customers[cid] = row["country"]
            cust["countries"][row["country"]] += 1
            cust["segments"][row["segment"]] += 1
            cust["status"][row["customer_status"]] += 1
            cust["credit_score_nonempty"] += bool(row["credit_score"])
            cust["income_nonempty"] += bool(row["estimated_monthly_income"])
            cust["last_updated_after_cutoff"] += row["last_updated"][:10] > CUTOFF
    for name in ("countries", "segments", "status"):
        cust[name] = counter_json(cust[name])
    result["tables"]["customers"] = cust
    print(f"customers: {cust['rows']} rows", flush=True)

    products: dict[str, str] = {}
    prod = {"rows": 0, "duplicate_ids": 0, "orphan_customer_ids": 0,
            "types": Counter(), "status": Counter(), "by_customer_country": Counter(),
            "credit_limit_nonempty": 0, "days_past_due_nonempty": 0,
            "last_updated_after_cutoff": 0, "columns": []}
    for columns, reader in rows_for("data/products.csv"):
        prod["columns"] = list(columns)
        for row in reader:
            prod["rows"] += 1
            pid, cid = row["product_id"], row["customer_id"]
            prod["duplicate_ids"] += pid in products
            products[pid] = cid
            prod["orphan_customer_ids"] += cid not in customers
            prod["types"][row["product_type"]] += 1
            prod["status"][row["product_status"]] += 1
            prod["by_customer_country"][customers.get(cid, "UNKNOWN")] += 1
            prod["credit_limit_nonempty"] += bool(row["credit_limit"])
            prod["days_past_due_nonempty"] += bool(row["days_past_due"])
            prod["last_updated_after_cutoff"] += row["last_updated"][:10] > CUTOFF
    for name in ("types", "status", "by_customer_country"):
        prod[name] = counter_json(prod[name])
    result["tables"]["products"] = prod
    print(f"products: {prod['rows']} rows", flush=True)

    # Build an interaction ID map to verify later transcript/complaint links.
    interactions: dict[str, str] = {}
    ic = {"rows": 0, "duplicate_ids": 0, "orphan_customer_ids": 0,
          "reason": Counter(), "reason_category": Counter(), "by_country": Counter(),
          "by_month": Counter(), "resolved_true": 0, "escalated_true": 0,
          "has_transcript_true": 0, "requires_followup_true": 0,
          "contact_reason_equals_category": 0, "partition_date_mismatch": 0,
          "schema_variants": Counter()}

    def scan_interaction(key: str):
        out = {"rows": 0, "ids": {}, "local_duplicate_ids": 0,
               "orphan_customer_ids": 0, "reason": Counter(), "reason_category": Counter(),
               "by_country": Counter(), "by_month": Counter(), "resolved_true": 0,
               "escalated_true": 0, "has_transcript_true": 0,
               "requires_followup_true": 0, "contact_reason_equals_category": 0,
               "partition_date_mismatch": 0, "columns": ()}
        match = PARTITION_DATE.search(key)
        expected = "-".join(match.groups()) if match else None
        for columns, reader in rows_for(key):
            out["columns"] = columns
            for row in reader:
                out["rows"] += 1
                iid, cid = row["interaction_id"], row["customer_id"]
                out["local_duplicate_ids"] += iid in out["ids"]
                out["ids"][iid] = cid
                out["orphan_customer_ids"] += cid not in customers
                out["reason"][row["contact_reason"]] += 1
                out["reason_category"][row["reason_category"]] += 1
                out["by_country"][customers.get(cid, "UNKNOWN")] += 1
                out["by_month"][row["process_date"][:7]] += 1
                out["resolved_true"] += row["was_resolved"] == "True"
                out["escalated_true"] += row["was_escalated"] == "True"
                out["has_transcript_true"] += row["has_transcript"] == "True"
                out["requires_followup_true"] += row["requires_followup"] == "True"
                out["contact_reason_equals_category"] += row["contact_reason"] == row["reason_category"]
                out["partition_date_mismatch"] += row["process_date"] != expected
        return out

    for part in run_partitions("call_center_interactions", scan_interaction):
        ic["rows"] += part["rows"]
        ic["duplicate_ids"] += part["local_duplicate_ids"]
        for iid, cid in part["ids"].items():
            ic["duplicate_ids"] += iid in interactions
            interactions[iid] = cid
        for name in ("orphan_customer_ids", "resolved_true", "escalated_true",
                     "has_transcript_true", "requires_followup_true",
                     "contact_reason_equals_category", "partition_date_mismatch"):
            ic[name] += part[name]
        for name in ("reason", "reason_category", "by_country", "by_month"):
            ic[name].update(part[name])
        ic["schema_variants"][part["columns"]] += 1
    for name in ("reason", "reason_category", "by_country", "by_month"):
        ic[name] = counter_json(ic[name])
    ic["schema_variants"] = len(ic["schema_variants"])
    result["tables"]["call_center_interactions"] = ic

    co = {"rows": 0, "duplicate_ids": 0, "orphan_customer_ids": 0,
          "category": Counter(), "subcategory": Counter(), "case_type": Counter(),
          "status": Counter(), "by_country": Counter(), "unrecognized_by_country": Counter(),
          "by_month": Counter(), "origin_interaction_nonempty": 0,
          "origin_interaction_known": 0, "origin_interaction_customer_mismatch": 0,
          "affected_product_nonempty": 0, "affected_product_known": 0,
          "affected_product_customer_mismatch": 0, "claimed_amount_nonempty": 0,
          "sla_breached_true": 0, "partition_date_mismatch": 0,
          "resolution_after_cutoff": 0, "schema_variants": Counter()}
    complaint_ids: set[str] = set()
    descriptions: set[str] = set()

    def scan_complaint(key: str):
        out = {"rows": 0, "ids": set(), "local_duplicate_ids": 0,
               "descriptions": set(), "orphan_customer_ids": 0,
               "category": Counter(), "subcategory": Counter(), "case_type": Counter(),
               "status": Counter(), "by_country": Counter(),
               "unrecognized_by_country": Counter(), "by_month": Counter(),
               "origin_interaction_nonempty": 0, "origin_interaction_known": 0,
               "origin_interaction_customer_mismatch": 0,
               "affected_product_nonempty": 0, "affected_product_known": 0,
               "affected_product_customer_mismatch": 0, "claimed_amount_nonempty": 0,
               "sla_breached_true": 0, "partition_date_mismatch": 0,
               "resolution_after_cutoff": 0, "columns": ()}
        match = PARTITION_DATE.search(key)
        expected = "-".join(match.groups()) if match else None
        for columns, reader in rows_for(key):
            out["columns"] = columns
            for row in reader:
                out["rows"] += 1
                cid, case_id = row["customer_id"], row["complaint_id"]
                out["local_duplicate_ids"] += case_id in out["ids"]
                out["ids"].add(case_id)
                out["descriptions"].add(row["description"])
                out["orphan_customer_ids"] += cid not in customers
                out["category"][row["category"]] += 1
                out["subcategory"][row["subcategory"]] += 1
                out["case_type"][row["case_type"]] += 1
                out["status"][row["status"]] += 1
                country = customers.get(cid, "UNKNOWN")
                out["by_country"][country] += 1
                if row["subcategory"] == "Cargo no reconocido":
                    out["unrecognized_by_country"][country] += 1
                out["by_month"][row["process_date"][:7]] += 1
                origin = row["origin_interaction_id"]
                out["origin_interaction_nonempty"] += bool(origin)
                out["origin_interaction_known"] += bool(origin and origin in interactions)
                out["origin_interaction_customer_mismatch"] += bool(
                    origin and origin in interactions and interactions[origin] != cid)
                pid = row["affected_product_id"]
                out["affected_product_nonempty"] += bool(pid)
                out["affected_product_known"] += bool(pid and pid in products)
                out["affected_product_customer_mismatch"] += bool(
                    pid and pid in products and products[pid] != cid)
                out["claimed_amount_nonempty"] += bool(row["claimed_amount"])
                out["sla_breached_true"] += row["sla_breached"] == "True"
                out["partition_date_mismatch"] += row["process_date"] != expected
                out["resolution_after_cutoff"] += bool(
                    row["resolution_date"] and row["resolution_date"][:10] > CUTOFF)
        return out

    for part in run_partitions("complaints", scan_complaint):
        co["rows"] += part["rows"]
        co["duplicate_ids"] += part["local_duplicate_ids"] + len(part["ids"] & complaint_ids)
        complaint_ids.update(part["ids"])
        descriptions.update(part["descriptions"])
        for name in ("orphan_customer_ids", "origin_interaction_nonempty",
                     "origin_interaction_known", "origin_interaction_customer_mismatch",
                     "affected_product_nonempty", "affected_product_known",
                     "affected_product_customer_mismatch", "claimed_amount_nonempty",
                     "sla_breached_true", "partition_date_mismatch", "resolution_after_cutoff"):
            co[name] += part[name]
        for name in ("category", "subcategory", "case_type", "status",
                     "by_country", "unrecognized_by_country", "by_month"):
            co[name].update(part[name])
        co["schema_variants"][part["columns"]] += 1
    co["distinct_exact_descriptions"] = len(descriptions)
    for name in ("category", "subcategory", "case_type", "status",
                 "by_country", "unrecognized_by_country", "by_month"):
        co[name] = counter_json(co[name])
    co["schema_variants"] = len(co["schema_variants"])
    result["tables"]["complaints"] = co

    tr = {"rows": 0, "duplicate_ids": 0, "orphan_customer_ids": 0,
          "languages": Counter(), "intents": Counter(), "by_country": Counter(),
          "interaction_known": 0, "interaction_customer_mismatch": 0,
          "customer_text_nonempty": 0, "partition_date_mismatch": 0,
          "schema_variants": Counter()}
    transcript_ids: set[str] = set()
    customer_texts: set[str] = set()
    text_reasons: dict[str, Counter] = defaultdict(Counter)

    def scan_transcript(key: str):
        out = {"rows": 0, "ids": set(), "local_duplicate_ids": 0,
               "texts": set(), "text_reasons": defaultdict(Counter),
               "orphan_customer_ids": 0, "languages": Counter(), "intents": Counter(),
               "by_country": Counter(), "interaction_known": 0,
               "interaction_customer_mismatch": 0, "customer_text_nonempty": 0,
               "partition_date_mismatch": 0, "columns": ()}
        match = PARTITION_DATE.search(key)
        expected = "-".join(match.groups()) if match else None
        for columns, reader in rows_for(key):
            out["columns"] = columns
            for row in reader:
                out["rows"] += 1
                tid, cid, iid = row["transcript_id"], row["customer_id"], row["interaction_id"]
                out["local_duplicate_ids"] += tid in out["ids"]
                out["ids"].add(tid)
                out["orphan_customer_ids"] += cid not in customers
                out["languages"][row["detected_language"]] += 1
                out["intents"][row["detected_intents"]] += 1
                out["by_country"][customers.get(cid, "UNKNOWN")] += 1
                out["interaction_known"] += iid in interactions
                out["interaction_customer_mismatch"] += bool(
                    iid in interactions and interactions[iid] != cid)
                text = row["customer_text"]
                out["customer_text_nonempty"] += bool(text)
                out["texts"].add(text)
                out["text_reasons"][text][row["detected_intents"]] += 1
                out["partition_date_mismatch"] += row["process_date"] != expected
        return out

    for part in run_partitions("call_transcripts", scan_transcript):
        tr["rows"] += part["rows"]
        tr["duplicate_ids"] += part["local_duplicate_ids"] + len(part["ids"] & transcript_ids)
        transcript_ids.update(part["ids"])
        customer_texts.update(part["texts"])
        for text, labels in part["text_reasons"].items():
            text_reasons[text].update(labels)
        for name in ("orphan_customer_ids", "interaction_known",
                     "interaction_customer_mismatch", "customer_text_nonempty",
                     "partition_date_mismatch"):
            tr[name] += part[name]
        for name in ("languages", "intents", "by_country"):
            tr[name].update(part[name])
        tr["schema_variants"][part["columns"]] += 1
    tr["distinct_exact_customer_texts"] = len(customer_texts)
    tr["texts_with_multiple_intent_tags"] = sum(len(x) > 1 for x in text_reasons.values())
    for name in ("languages", "intents", "by_country"):
        tr[name] = counter_json(tr[name])
    tr["schema_variants"] = len(tr["schema_variants"])
    result["tables"]["call_transcripts"] = tr
    del interactions, transcript_ids, customer_texts, text_reasons

    tx = {"rows": 0, "duplicate_ids": 0, "orphan_customer_ids": 0,
          "product_unknown": 0, "product_owner_mismatch": 0,
          "status": Counter(), "type": Counter(), "country": Counter(),
          "by_month": Counter(), "fraud_true": 0, "amount_missing": 0,
          "partition_date_mismatch": 0, "schema_variants": Counter()}
    transaction_ids: set[str] = set()

    def scan_transaction(key: str):
        out = {"rows": 0, "ids": set(), "local_duplicate_ids": 0,
               "orphan_customer_ids": 0, "product_unknown": 0,
               "product_owner_mismatch": 0, "status": Counter(), "type": Counter(),
               "country": Counter(), "by_month": Counter(), "fraud_true": 0,
               "amount_missing": 0, "partition_date_mismatch": 0, "columns": ()}
        match = PARTITION_DATE.search(key)
        expected = "-".join(match.groups()) if match else None
        for columns, reader in rows_for(key):
            out["columns"] = columns
            for row in reader:
                out["rows"] += 1
                tid, cid, pid = row["transaction_id"], row["customer_id"], row["product_id"]
                out["local_duplicate_ids"] += tid in out["ids"]
                out["ids"].add(tid)
                out["orphan_customer_ids"] += cid not in customers
                out["product_unknown"] += pid not in products
                out["product_owner_mismatch"] += bool(
                    pid in products and products[pid] != cid)
                out["status"][row["transaction_status"]] += 1
                out["type"][row["transaction_type"]] += 1
                out["country"][row["transaction_country"]] += 1
                out["by_month"][row["process_date"][:7]] += 1
                out["fraud_true"] += row["is_fraud"] == "True"
                out["amount_missing"] += not bool(row["amount"])
                out["partition_date_mismatch"] += row["process_date"] != expected
        return out

    for part in run_partitions("transactions", scan_transaction):
        tx["rows"] += part["rows"]
        tx["duplicate_ids"] += part["local_duplicate_ids"] + len(part["ids"] & transaction_ids)
        transaction_ids.update(part["ids"])
        for name in ("orphan_customer_ids", "product_unknown",
                     "product_owner_mismatch", "fraud_true", "amount_missing",
                     "partition_date_mismatch"):
            tx[name] += part[name]
        for name in ("status", "type", "country", "by_month"):
            tx[name].update(part[name])
        tx["schema_variants"][part["columns"]] += 1
    for name in ("status", "type", "country", "by_month"):
        tx[name] = counter_json(tx[name])
    tx["schema_variants"] = len(tx["schema_variants"])
    result["tables"]["transactions"] = tx

    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote aggregate profile: {args.output}", flush=True)


if __name__ == "__main__":
    main()
