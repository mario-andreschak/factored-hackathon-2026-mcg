#!/usr/bin/env python3
"""Savia Pro - acceptance checks.

Runs against a live API and asserts the promises this product makes, so a
reviewer can watch them being enforced instead of taking the README's word.

    python3 -m server.main &          # or: ./run.sh
    python3 tools/acceptance.py

Exits non-zero on the first failing assertion. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("SAVIA_BASE", "http://127.0.0.1:43950")

passed = 0
failed = 0


def check(label: str, condition: bool, detail: str = "") -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f" -> {detail}" if detail else ""))
    return condition


def section(name: str) -> None:
    print(f"\n{name}")


def call(path: str, token: str | None = None, body: dict | None = None):
    """Returns (status, parsed-or-text)."""
    request = urllib.request.Request(BASE + path, method="POST" if body is not None else "GET")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, data, timeout=20) as response:
            raw = response.read().decode()
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except urllib.error.HTTPError as error:
        raw = error.read().decode()
        try:
            return error.code, json.loads(raw)
        except json.JSONDecodeError:
            return error.code, raw
    except urllib.error.URLError as error:
        print(f"\ncannot reach {BASE}: {error}\nStart the API first: python3 -m server.main")
        sys.exit(2)


def walk(node):
    """Yields every scalar in a nested structure, with its path."""
    stack = [("", node)]
    while stack:
        path, value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                stack.append((f"{path}.{key}", child))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                stack.append((f"{path}[{index}]", child))
        else:
            yield path, value


# ======================================================================
section("the service is up and describes its source")

status, health = call("/api/health")
check("health responds", status == 200 and health.get("ok") is True)

status, snapshot = call("/api/snapshot")
build = snapshot["build"]
totals = snapshot["totals"]
shares = snapshot["shares"]
check("the snapshot is identified by build id", status == 200 and bool(build["build_id"]))
check("the snapshot reports a source fingerprint", bool(build.get("source_fingerprint")))
check("the snapshot names the lake it was built from", build["lake_path"].startswith("/"))

check("the published row count is the real one", totals["transactions"] == 4_425_008,
      str(totals["transactions"]))
check("the missing-merchant share is measured, not estimated",
      abs(shares["no_merchant"] - 0.7674) < 0.001, str(shares["no_merchant"]))
check("the next-day-event share is measured",
      abs(shares["next_day_event"] - 0.25) < 0.005, str(shares["next_day_event"]))
check("the similar-charge scan publishes its real result",
      totals["similar_charge_pairs_72h"] == 0, str(totals["similar_charge_pairs_72h"]))
check("the merchant vocabulary is published as the limitation it is",
      totals["distinct_merchant_names"] == 24, str(totals["distinct_merchant_names"]))


# ======================================================================
section("nothing is readable without a session")

for path in ["/api/overview", "/api/transactions", "/api/insights", "/api/signals", "/api/reviews"]:
    status, _ = call(path)
    check(f"{path} refuses an anonymous caller", status == 401, str(status))


# ======================================================================
section("the catalogue never exposes a customer identifier")

status, listing = call("/api/profiles")
profiles = listing["profiles"]
check("profiles are listed", status == 200 and len(profiles) >= 2)

leaked = [path for profile in profiles for path, value in walk(profile)
          if "customer_id" in path or (isinstance(value, str) and value.startswith("CLI-"))]
check("no customer identifier appears in the catalogue", not leaked, ", ".join(leaked[:3]))

slugs = [profile["slug"] for profile in profiles]
tokens = {}
for slug in slugs:
    status, session = call("/api/session", body={"slug": slug})
    check(f"session issued for {slug}", status == 200 and bool(session.get("token")))
    tokens[slug] = session["token"]

status, _ = call("/api/session", body={"slug": "CLI-06IPRRS0DV7R"})
check("a raw customer id cannot be used as a selector", status >= 400, str(status))
status, _ = call("/api/session", body={"slug": "../../etc/passwd"})
check("a path-traversal selector is refused", status >= 400, str(status))


# ======================================================================
section("one customer cannot read another")

ledgers = {}
for slug, token in tokens.items():
    status, page = call("/api/transactions?limit=5", token)
    check(f"{slug} reads its own ledger", status == 200 and page["total"] > 0)
    ledgers[slug] = page["transactions"]

first, second = slugs[0], slugs[1]
foreign = ledgers[second][0]["reference"]
status, _ = call(f"/api/transactions/{urllib.parse.quote(foreign)}", tokens[first])
check("a foreign transaction is not found, not merely hidden", status == 404, str(status))

own = ledgers[first][0]["reference"]
status, _ = call(f"/api/transactions/{urllib.parse.quote(own)}", tokens[first])
check("the same call works for an owned transaction", status == 200, str(status))

status, _ = call(f"/api/transactions/{urllib.parse.quote(foreign)}", tokens[first] + "x")
check("a tampered token is rejected", status == 401, str(status))

# A review may only be opened over a row the session owns.
status, _ = call("/api/reviews", tokens[first], {
    "reference": foreign, "reason": "unrecognised_charge",
    "answers": {}, "note": "", "urgent": False})
check("a review cannot be opened over a foreign transaction", status == 404, str(status))


# ======================================================================
section("the fraud columns never reach the browser")

FORBIDDEN = ("is_fraud", "fraud_score", "fraud", "_row_hash", "_source_file",
             "_partition_date", "_run_id", "_owner_mismatch", "bucket", "customer_id")

payloads = {}
token = tokens[first]
for path in ["/api/overview", "/api/transactions?limit=50", "/api/insights",
             "/api/signals", "/api/snapshot", "/api/profiles"]:
    status, payload = call(path, token)
    payloads[path] = payload

offenders = []
for path, payload in payloads.items():
    for key_path, value in walk(payload):
        lowered = key_path.lower()
        for word in FORBIDDEN:
            if word in lowered:
                offenders.append(f"{path}{key_path}")
        if isinstance(value, str) and value.startswith("CLI-"):
            offenders.append(f"{path}{key_path}=CLI-…")
check("no response carries a fraud flag, source key or customer id",
      not offenders, ", ".join(sorted(set(offenders))[:4]))

status, detail = call(f"/api/transactions/{urllib.parse.quote(own)}", token)
detail_offenders = [p for p, _ in walk(detail)
                    for w in FORBIDDEN if w in p.lower()]
check("the transaction detail is clean too", not detail_offenders,
      ", ".join(detail_offenders[:3]))


# ======================================================================
section("the ledger answers honestly")

status, page = call("/api/transactions?flags=no_merchant&limit=200", token)
check("the no-merchant filter returns only rows without a merchant",
      all(row["merchant"] is None for row in page["transactions"]))

status, page = call("/api/transactions?flags=next_day&limit=200", token)
check("the next-day filter returns only rows whose event follows its process date",
      all(row["event_date"][:10] > row["process_date"][:10] for row in page["transactions"]),
      "one row did not satisfy the rule")

status, page = call("/api/transactions?flags=unknown_direction&limit=200", token)
check("rows with no direction are never given a sign",
      all(row["direction"] == "unknown" for row in page["transactions"]))

status, page = call("/api/transactions?sort=amount_desc&limit=20", token)
amounts = [float(row["amount"]) for row in page["transactions"]]
check("sorting by amount actually sorts", amounts == sorted(amounts, reverse=True))

status, page = call("/api/transactions?status=Pending&limit=200", token)
check("a pending row is never reported as settled",
      all(row["status"] == "Pending" for row in page["transactions"]))

status, nothing = call("/api/transactions?q=zzzz-no-such-merchant", token)
check("an empty result is an empty result, not a guess", nothing["matched"] == 0)

status, signals = call("/api/signals", token)
found = {row["kind"]: row["count"] for row in signals["found"]}
clear = {row["kind"] for row in signals["clear"]}
check("every rule is accounted for, whether or not it matched",
      {"pending", "reversed", "declined", "next_day", "no_merchant",
       "fx", "inactive_product", "similar_charge"} <= (set(found) | clear),
      str(sorted(set(found) | clear)))
check("a rule that found nothing is reported as clear, not omitted",
      "similar_charge" in clear and "similar_charge" not in found)
check("a rule that matched carries a real example row",
      all(row["examples"] and row["examples"][0]["reference"] for row in signals["found"]))


# ======================================================================
section("a review record cannot overclaim")

status, created = call("/api/reviews", token, {
    "reference": own, "reason": "unrecognised_charge",
    "answers": {"recognise": "no"}, "note": "acceptance run", "urgent": False})
check("a review is created over an owned row", status == 200, str(status))
record = created["review"]

for field in ("bank_action_taken", "dispute_submitted", "chargeback_requested",
              "refund_issued", "agent_transfer", "response_deadline_promised"):
    check(f"the record states {field} = false", record[field] is False, str(record.get(field)))
check("the record states local_only = true", record["local_only"] is True)
check("the record promises no decision and no response time",
      "no response time" in record["next_step"].lower()
      or "no bank decision" in record["next_step"].lower(), record["next_step"])

check("the record carries a sha-256 over the verified facts",
      len(record["evidence"]["facts_sha256"]) == 64)
check("the verified facts are the row the server read",
      record["verified_facts"]["reference"] == own)
check("what the customer typed is kept out of the verified facts",
      "acceptance run" not in json.dumps(record["verified_facts"]))
check("what the customer typed is kept, separately",
      record["customer_note"] == "acceptance run")
check("the record names the build the facts came from",
      record["evidence"]["build_id"] == build["build_id"])

status, urgent = call("/api/reviews", token, {
    "reference": own, "reason": "unrecognised_charge",
    "answers": {"recognise": "no"}, "note": "", "urgent": True})
security = urgent["review"]
check("a lost or stolen card outranks the stated reason",
      security["reason"] == "security_concern" and security["priority"] == "security",
      json.dumps({"reason": security["reason"], "priority": security["priority"]}))
check("the urgent path asks no further questions", security["questions_skipped"] is True)
check("the urgent path still promises nothing",
      security["dispute_submitted"] is False and security["bank_action_taken"] is False)

status, mine = call("/api/reviews", token)
check("my own records are listed back", any(r["id"] == security["id"] for r in mine["reviews"]))
status, other = call("/api/reviews", tokens[second])
check("another customer's records are not listed to me",
      not any(r["id"] == security["id"] for r in other["reviews"]))


# ======================================================================
section("export")

request = urllib.request.Request(BASE + "/api/export.csv?limit=10")
request.add_header("Authorization", "Bearer " + token)
with urllib.request.urlopen(request, timeout=20) as response:
    csv_text = response.read().decode()
header = csv_text.splitlines()[0]
check("the CSV carries both date bases", "event_date" in header and "process_date" in header, header)
check("the CSV carries no fraud column",
      not any(word in header for word in ("fraud", "is_fraud", "customer_id")), header)


# ======================================================================
print(f"\n{passed}/{passed + failed} checks passed")
if failed:
    print(f"{failed} FAILED")
    sys.exit(1)
print("Savia Pro acceptance passed.")
