#!/usr/bin/env python3
"""Validate and aggregate user-supplied, human-labelled offline outcome evidence."""
import argparse
import json
import math
from collections import defaultdict
from pathlib import Path


class InputError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InputError(message)


def named(value, field):
    require(isinstance(value, str) and bool(value.strip()), f"{field} must be nonempty")
    return value


def boolean(row, field):
    require(field in row and type(row[field]) is bool, f"{field} must be boolean")
    return row[field]


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def summarize(rows, case_count):
    n = len(rows)
    count = lambda predicate: sum(bool(predicate(row)) for row in rows)
    required = count(lambda r: r["_requires_handoff"])
    not_required = n - required
    successes = count(lambda r: r["safe_inquiry_resolution"])
    known = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    unknown = n - len(known)
    cost_per_success = (
        {"status": "undefined_no_success", "usd": None} if successes == 0 else
        {"status": "unknown_cost", "usd": None} if unknown else
        {"status": "known", "usd": round(sum(known) / successes, 6)}
    )
    metric = lambda numerator, denominator: {"count": numerator, "denominator": denominator}
    return {
        "unique_cases": case_count, "attempts": n,
        "automation_attempted": metric(count(lambda r: r["automation_attempted"]), n),
        "authorized_dispatch": metric(count(lambda r: r["authorized_dispatch"]), n),
        "safe_inquiry_resolution": metric(successes, n),
        "verified_simulated_intake": metric(count(lambda r: r["intake_completed"]), n),
        "containment": metric(count(lambda r: not r["transferred"]), n),
        "unsafe_outcomes": metric(count(lambda r: r["unsafe_outcome"]), n),
        "required_handoff": metric(required, n),
        "correct_handoff": metric(count(lambda r: r["_requires_handoff"] and r["actual_outcome"] == "correct_handoff" and r["transferred"] and r["handoff_packet_complete"]), required),
        "missed_handoff": metric(count(lambda r: r["_requires_handoff"] and not (r["actual_outcome"] == "correct_handoff" and r["transferred"] and r["handoff_packet_complete"])), required),
        "unnecessary_handoff": metric(count(lambda r: not r["_requires_handoff"] and r["transferred"]), not_required),
        "latency_ms": {"count": n, "p50": percentile([r["latency_ms"] for r in rows], .50),
                       "p95": percentile([r["latency_ms"] for r in rows], .95)},
        "cost_usd": {"known_count": len(known), "unknown_count": unknown,
                     "known_sum": round(sum(known), 6),
                     "per_attempt": {"status": "unknown_cost", "usd": None} if unknown else
                                    {"status": "known", "usd": round(sum(known) / n, 6)},
                     "per_safe_resolution": cost_per_success},
    }


def aggregate(data):
    require(isinstance(data, dict), "root must be an object")
    require(data.get("schema") == "customer-outcomes/v1", "schema must be customer-outcomes/v1")
    provenance = data.get("provenance")
    require(isinstance(provenance, dict), "provenance object required")
    for field in ("source_sha", "fixture_id", "fixture_version", "data_origin", "evidence_tier", "trace_reference"):
        named(provenance.get(field), f"provenance.{field}")
    require(provenance["data_origin"] == "team_generated_synthetic", "only team-generated synthetic fixtures accepted")
    require(provenance["evidence_tier"] in ("source_mock", "simulated_runtime", "native_trace", "deployed_trace"),
            "unknown evidence tier")
    lock = data.get("lock")
    require(isinstance(lock, dict), "lock object required")
    for field in ("workload_id", "case_set_sha256", "locked_at_utc", "rubric_version"):
        named(lock.get(field), f"lock.{field}")
    require(len(lock["case_set_sha256"]) == 64 and
            all(c in "0123456789abcdef" for c in lock["case_set_sha256"]), "invalid case set SHA256")
    require(lock.get("status") == "human_reviewed_locked", "human-reviewed locked labels required")
    reviewers = lock.get("reviewers")
    require(isinstance(reviewers, list) and
            all(isinstance(x, str) and x.strip() for x in reviewers) and
            len(set(reviewers)) >= 2, "two distinct reviewers required")
    cases = data.get("cases")
    attempts = data.get("attempts")
    require(isinstance(cases, list) and cases and isinstance(attempts, list) and attempts,
            "nonempty cases and attempts required")
    by_case = {}
    for case in cases:
        require(isinstance(case, dict), "case must be object")
        case_id = named(case.get("case_id"), "case_id")
        require(case_id not in by_case, f"duplicate case {case_id}")
        require(case.get("language") in ("es", "pt"), f"{case_id}: language must be es or pt")
        labels = case.get("labels")
        require(isinstance(labels, dict), f"{case_id}: labels required")
        require(labels.get("review_status") == "human_reviewed_locked", f"{case_id}: unlocked labels")
        named(labels.get("expected_route"), f"{case_id}.expected_route")
        boolean(labels, "requires_handoff")
        boolean(labels, "in_scope")
        require(labels["in_scope"], f"{case_id}: out-of-scope case in locked workload")
        by_case[case_id] = case
    require({c["language"] for c in cases} == {"es", "pt"}, "both es and pt cases required")
    seen = set()
    repeats = set()
    groups = defaultdict(list)
    allowed_outcomes = {"safe_inquiry", "verified_simulated_intake", "correct_handoff",
                        "unresolved", "unsafe", "timeout", "tool_error"}
    for row in attempts:
        require(isinstance(row, dict), "attempt must be object")
        case_id = named(row.get("case_id"), "attempt.case_id")
        require(case_id in by_case, f"unknown case {case_id}")
        system = row.get("system")
        require(system in ("baseline", "proposed"), f"{case_id}: invalid system")
        repeat = row.get("repeat")
        require(type(repeat) is int and repeat > 0, f"{case_id}: repeat must be positive integer")
        key = (case_id, system, repeat)
        require(key not in seen, f"duplicate case/system/repeat {key}")
        seen.add(key)
        repeats.add(repeat)
        outcome = row.get("actual_outcome")
        require(isinstance(outcome, str) and outcome in allowed_outcomes,
                f"{key}: actual_outcome required")
        for field in ("automation_attempted", "authorized_dispatch", "safe_inquiry_resolution",
                      "intake_completed", "transferred", "handoff_packet_complete", "unsafe_outcome"):
            boolean(row, field)
        require(not row["authorized_dispatch"] or row["automation_attempted"], f"{key}: dispatch without attempt")
        require(row["safe_inquiry_resolution"] == (outcome == "safe_inquiry") and
                (not row["safe_inquiry_resolution"] or
                 (not by_case[case_id]["labels"]["requires_handoff"] and
                  not row["transferred"] and not row["unsafe_outcome"])),
                f"{key}: inconsistent safe resolution")
        require(row["intake_completed"] == (row["actual_outcome"] == "verified_simulated_intake"),
                f"{key}: inconsistent intake outcome")
        if row["intake_completed"]:
            require(row["authorized_dispatch"], f"{key}: intake requires authorized dispatch")
            require(row.get("confirmation_recorded") is True,
                    f"{key}: intake requires recorded confirmation")
            receipt = row.get("receipt_readback")
            require(isinstance(receipt, dict) and all(receipt.get(f) is True for f in
                    ("verified", "owner_match", "session_match", "query_match", "target_match", "snapshot_match")),
                    f"{key}: intake requires verified matching receipt readback")
        require(row["unsafe_outcome"] == (row["actual_outcome"] == "unsafe"), f"{key}: inconsistent unsafe outcome")
        require(not row["handoff_packet_complete"] or row["transferred"], f"{key}: packet without transfer")
        require(row["actual_outcome"] != "correct_handoff" or
                (row["transferred"] and row["handoff_packet_complete"]), f"{key}: incorrect handoff claim")
        latency = row.get("latency_ms")
        require(type(latency) in (int, float) and math.isfinite(latency) and latency >= 0,
                f"{key}: latency_ms required including failures")
        require("cost_usd" in row, f"{key}: cost_usd required (null if unknown)")
        cost = row["cost_usd"]
        basis = row.get("cost_basis")
        require((cost is None and basis == "unknown") or
                (type(cost) in (int, float) and math.isfinite(cost) and cost >= 0 and
                 basis in ("measured", "documented_zero") and (cost != 0 or basis == "documented_zero")),
                f"{key}: unknown cost must be null; zero requires documented_zero")
        row = dict(row, _requires_handoff=by_case[case_id]["labels"]["requires_handoff"])
        groups[(system, by_case[case_id]["language"])].append(row)
    expected = {(case_id, system, repeat) for case_id in by_case for system in ("baseline", "proposed")
                for repeat in repeats}
    require(seen == expected, f"incomplete same-case system/repeat panel: {len(expected - seen)} missing")
    output = {}
    for system in ("baseline", "proposed"):
        output[system] = {}
        for language in ("es", "pt"):
            output[system][language] = summarize(groups[(system, language)],
                                                  sum(c["language"] == language for c in cases))
        output[system]["overall"] = summarize(groups[(system, "es")] + groups[(system, "pt")], len(cases))
        output[system]["by_repeat"] = {str(repeat): {language: summarize(
            [r for r in groups[(system, language)] if r["repeat"] == repeat],
            sum(c["language"] == language for c in cases)) for language in ("es", "pt")}
            for repeat in sorted(repeats)}
    return {"schema": "customer-outcomes-report/v1",
            "qualification": "offline user-supplied aggregation; provenance and human review not independently verified",
            "provenance": provenance, "lock": lock, "repeats": sorted(repeats),
            "systems": output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="locked JSON evidence input")
    args = parser.parse_args()
    try:
        report = aggregate(json.loads(args.input.read_text(encoding="utf-8")))
    except (InputError, OSError, json.JSONDecodeError) as exc:
        parser.exit(2, f"invalid outcome evidence: {exc}\n")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
