"""Build an offline bank review page. No service, model or bank action is started."""
import argparse
import json
from pathlib import Path
import sqlite3

from .report import build_page, demo_packet, read_analytics
from scripts.report_customer_outcomes import InputError, aggregate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--demo", action="store_true", help="fictional walkthrough; no measured results")
    source.add_argument("--analytics-db", type=Path, help="existing private analytics SQLite database")
    parser.add_argument("--outcome-input", type=Path, help="private locked customer-outcomes/v1 comparison")
    parser.add_argument("--limit", type=int, default=500, help="maximum review turns (1-5000)")
    parser.add_argument("--out", type=Path, required=True, help="new HTML file, preferably inside private/")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 5000:
        parser.error("--limit must be between 1 and 5000")
    if args.demo and args.outcome_input:
        parser.error("keep illustrative demo and actual offline comparison in separate reports")
    try:
        packet = demo_packet() if args.demo else read_analytics(args.analytics_db, args.limit)
        if args.outcome_input:
            evidence = json.loads(args.outcome_input.read_text(encoding="utf-8"))
            packet["comparison"] = aggregate(evidence)
            languages = {case["case_id"]: case["language"] for case in evidence["cases"]}
            counts = {system: {scope: {outcome: 0 for outcome in ("unresolved", "timeout", "tool_error")}
                              for scope in ("overall", "es", "pt")} for system in ("baseline", "proposed")}
            for attempt in evidence["attempts"]:
                if attempt["actual_outcome"] in counts[attempt["system"]]["overall"]:
                    for scope in ("overall", languages[attempt["case_id"]]):
                        counts[attempt["system"]][scope][attempt["actual_outcome"]] += 1
            packet["comparison_failure_counts"] = counts
        page = build_page(packet)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents overwriting input, operational state or an earlier report.
        with args.out.open("x", encoding="utf-8") as output:
            output.write(page)
    except (ValueError, InputError, OSError, sqlite3.Error) as exc:
        parser.exit(2, f"bank review build failed: {exc}\n")
    print("Created offline bank review page. Keep metadata reports and review exports private.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
