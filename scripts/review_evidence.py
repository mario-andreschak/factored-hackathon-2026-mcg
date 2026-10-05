"""Replay public data, routing and analytics evidence without provider calls.

python scripts/review_evidence.py --out docs/review

Uses only committed synthetic fixtures and the already published frozen routing
diagnostic. Never changes models, thresholds, labels, operational state or secrets.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import math
from pathlib import Path
import platform
import runpy
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE_PATHS = [
    "scripts/review_evidence.py", "demo/evaluate_router.py", "ml/router.py",
    "ml/data/router_train.csv", "ml/data/router_test.csv", "pipeline/contracts.yaml",
    "pipeline/common.py", "pipeline/fixture.py", "pipeline/bronze.py", "pipeline/silver.py",
    "pipeline/gold.py", "pipeline/lookup.py", "pipeline/report.py", "pipeline/__main__.py",
    "pipeline/writer.py", "pipeline/verify.py", "analytics/__main__.py",
    "analytics/extract.py", "analytics/report.py", "dispute_workflow/state.py", "requirements-review.txt", "tests/test_pipeline.py",
    "tests/test_agent_analytics.py", "tests/test_router.py",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def wilson(successes: int, total: int) -> list[float] | None:
    if not total:
        return None
    z, p = 1.959963984540054, successes / total
    scale = 1 + z * z / total
    center = (p + z * z / (2 * total)) / scale
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / scale
    return [round(max(0, center - radius), 6), round(min(1, center + radius), 6)]


def router_replay(out: Path) -> dict:
    import numpy as np
    from demo.evaluate_router import evaluate, frozen_cases

    report = evaluate()  # Existing fixed C=8/tau=.65 procedure; no selection.
    cases = frozen_cases()
    expected = [row["label"] for row in cases]
    predictions = {name: expected.copy() for name in report["systems"]}
    keys = {"keyword_baseline": "baseline", "tfidf_logistic": "model",
            "tfidf_logistic_abstention": "with_abstention"}
    # The existing evaluator publishes all cases with any system error. Every
    # omitted case is correct for every system, so full decisions reconstruct exactly.
    for error in report["errors"]:
        for name, key in keys.items():
            predictions[name][error["case"] - 1] = error[key]
    baseline = np.asarray(predictions["keyword_baseline"]) == np.asarray(expected)
    comparisons = {}
    rng = np.random.default_rng(7)
    indices = rng.integers(0, len(cases), (10000, len(cases)))
    for name, system in report["systems"].items():
        correct = np.asarray(predictions[name]) == np.asarray(expected)
        assert int(correct.sum()) == round(system["accuracy"] * len(cases))
        difference = correct.astype(float) - baseline.astype(float)
        boots = difference[indices].mean(axis=1)
        gained = int((correct & ~baseline).sum())
        lost = int((~correct & baseline).sum())
        discordant = gained + lost
        # Two-sided exact McNemar binomial test on the paired disagreements.
        p = min(1., 2 * sum(math.comb(discordant, i) for i in range(min(gained, lost) + 1))
                / 2 ** discordant) if discordant else 1.
        system["human_misroute_rate_ci95_wilson"] = wilson(system["human_missed"], system["human_total"])
        system["human_misroute_denominator"] = "30 AI-labelled human-required diagnostic utterances"
        comparisons[name] = {
            "accuracy_difference_vs_keywords": round(float(difference.mean()), 6),
            "paired_bootstrap_ci95": [round(float(v), 6) for v in np.quantile(boots, [.025, .975])],
            "paired_gain_cases": gained, "paired_loss_cases": lost,
            "exact_mcnemar_p_two_sided": round(p, 9),
        }
    report["paired_comparisons"] = comparisons
    report["uncertainty_method"] = "10,000 paired bootstrap row resamples, seed 7; Wilson score intervals for human misroutes"
    report["replay_disclosure"] = (
        "Previously published diagnostic outcomes were already inspected. This is an unchanged-procedure "
        "reproduction and uncertainty analysis, not a new blind test. No training/labels/features/thresholds "
        "were changed. Intervals condition on these authored cases and proposed AI labels, not customer prevalence.")
    report["provider_requests"] = 0
    report["runtime_integration"] = "offline intent component only; not a newly accepted deployed assistant"
    write_json(out / "router-replay.json", report)
    return report


def pipeline_replay(scratch: Path, out: Path) -> dict:
    import duckdb
    from pipeline.__main__ import main
    from pipeline.common import current_gold, current_silver
    from pipeline.fixture import cid, write_base, write_late_batch
    from pipeline.lookup import get_customer_transactions

    source, data, reports = scratch / "pipeline-source", scratch / "pipeline-data", scratch / "pipeline-reports"
    write_base(source)

    def execute(stage: str) -> dict:
        with redirect_stdout(io.StringIO()):
            code = main(["run", "--source", str(source), "--out", str(data), "--reports", str(reports)])
        manifest = json.loads((reports / "manifest.json").read_text(encoding="utf-8"))
        if code != 0:
            raise RuntimeError(f"synthetic_pipeline_failed:{stage}:{code}")
        # Public aggregate manifest; replace machine-specific scratch location.
        public = json.loads(json.dumps(manifest).replace(str(scratch).replace("\\", "/"), "$SCRATCH")
                            .replace(str(scratch).replace("\\", "\\\\"), "$SCRATCH"))
        write_json(out / f"pipeline-{stage}.json", public)
        return manifest

    def logical_hashes() -> dict:
        with duckdb.connect() as con:
            return {table: con.execute(
                "SELECT md5(string_agg(_row_hash, ',' ORDER BY _row_hash)) FROM read_parquet(?)",
                [str(current_silver(data) / f"{table}.parquet")]).fetchone()[0]
                    for table in ["customers", "products", "transactions", "call_center_interactions", "call_transcripts", "complaints"]}

    base = execute("base")
    hashes = logical_hashes()
    repeat = execute("repeat")
    repeat_hashes = logical_hashes()
    old_gold = current_gold(data)
    before = get_customer_transactions(old_gold, cid(6), limit=100)
    owner_rows = get_customer_transactions(old_gold, cid(9), limit=100)
    missing_rows = get_customer_transactions(old_gold, "CUS999999", limit=100)
    write_late_batch(source)
    late = execute("late")
    after = get_customer_transactions(current_gold(data), cid(6), limit=100)
    status = lambda rows: next(r["transaction_status"] for r in rows if r["transaction_id"] == "TXN00000904")
    checks = {
        "every_raw_row_reconciles": all(t["silver"]["reconciles"] for m in [base, repeat, late] for t in m["tables"].values()),
        "idempotent_logical_content_all_six_tables": hashes == repeat_hashes,
        "wrong_product_owner_excluded": all(r["transaction_id"] != "TXN00000907" for r in owner_rows),
        "missing_customer_has_no_rows": missing_rows == [],
        "late_correction_pending_to_reversed": status(before) == "Pending" and status(after) == "Reversed",
        "late_new_transaction_visible": any(r["transaction_id"] == "TXN00000951" for r in after),
        "previous_published_snapshot_unchanged": before == get_customer_transactions(old_gold, cid(6), limit=100),
    }
    receipt = {
        "scope": "actual local pipeline on committed generated synthetic fixture; not organizer-data recomputation",
        "checks": checks, "logical_content_hashes_base": hashes, "logical_content_hashes_repeat": repeat_hashes,
        "base_tables": {table: {key: t["silver"][key] for key in
                                   ["raw_rows", "rows", "quarantined_rows", "duplicate_rows_removed", "reconciles"]}
                        for table, t in base["tables"].items()},
        "transaction_late_batch": {"base_raw": base["tables"]["transactions"]["silver"]["raw_rows"],
                                   "late_raw": late["tables"]["transactions"]["silver"]["raw_rows"],
                                   "status_before": status(before), "status_after": status(after)},
        "source_credentials_used": False, "provider_requests": 0,
    }
    write_json(out / "pipeline-replay.json", receipt)
    return receipt


def analytics_replay(scratch: Path, out: Path) -> dict:
    from analytics.extract import add_feedback, build, discover
    from analytics.report import summarize

    fixture = runpy.run_path(str(ROOT / "tests/test_agent_analytics.py"))
    source = scratch / "analytics-source"
    source.mkdir()
    fixture["state_dir"].__wrapped__(source)
    before = {p.name: digest(p) for p in source.glob("*.sqlite3")}
    output = scratch / "analytics-output.sqlite3"
    workflow, chat = discover(source)
    counts = build(output, workflow_dbs=workflow, chat_dbs=chat, now=fixture["NOW"])
    add_feedback(output, source="customer", conversation_id="conversation-1", rating=1, now=fixture["NOW"])
    summary = summarize(output)
    import sqlite3
    with sqlite3.connect(output) as db:
        dump = "\n".join(db.iterdump())
    checks = {
        "operational_sources_unchanged": before == {p.name: digest(p) for p in source.glob("*.sqlite3")},
        "raw_customer_text_and_identity_absent": all(secret not in dump for secret in fixture["SECRET_VALUES"]),
        "workflow_denominator_excludes_transcript_only": summary["volume"]["workflow_conversations"] == 2,
        "synthetic_handoff_and_action_counted": summary["outcomes"] == {"action_verified": 1, "handoff": 1, "transcript_only": 1},
    }
    receipt = {"scope": "metadata-only analytics on committed synthetic operational fixture; not measured customer ROI",
               "projection_counts": counts, "checks": checks, "metrics": summary,
               "feedback_provenance": "one synthetic positive fixture rating; no human/customer adjudication claim",
               "provider_cost": "not applicable: zero provider requests in this offline replay",
               "provider_requests": 0}
    write_json(out / "analytics-replay.json", receipt)
    return receipt


def test_replay(scratch: Path, out: Path) -> dict:
    junit = scratch / "tests.xml"
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_pipeline.py", "tests/test_agent_analytics.py",
               "tests/test_router.py", "--deselect", "tests/test_router.py::test_train_and_evaluate_writes_reports",
               f"--junitxml={junit}"]
    run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, encoding="utf-8", errors="replace")
    cases = []
    if junit.exists():
        for case in ET.parse(junit).iter("testcase"):
            status = next((tag for tag in ["failure", "error", "skipped"] if case.find(tag) is not None), "passed")
            cases.append({"name": case.attrib["name"], "class": case.attrib.get("classname"), "status": status})
    receipt = {"exit_code": run.returncode, "command": "python -m pytest -q tests/test_pipeline.py tests/test_agent_analytics.py tests/test_router.py --deselect tests/test_router.py::test_train_and_evaluate_writes_reports",
               "deselection_reason": "use the fixed published diagnostic procedure instead of invoking model-selection entry point",
               "total": len(cases), "passed": sum(c["status"] == "passed" for c in cases), "cases": cases}
    if run.returncode:
        receipt["failure_output"] = (run.stdout + run.stderr)[-12000:].replace(str(scratch), "$SCRATCH")
    write_json(out / "offline-tests.json", receipt)
    return receipt


def render(receipt: dict, router: dict, pipeline: dict, analytics: dict) -> str:
    tests = receipt["tests"]
    lines = ["# Public evidence replay", "", f"Executed {receipt['finished_utc']} with Git base `{receipt['git_head_at_start']}` "
             "and the exact working-tree source subset identified by SHA-256 in the receipt. "
             "The base commit alone does not identify the new replay script.", "",
             f"**{receipt['status'].upper()}**: {tests['passed']}/{tests['total']} existing offline checks passed; "
             f"{sum(pipeline['checks'].values())} pipeline and {sum(analytics['checks'].values())} analytics replay invariants passed. "
             "No provider requests, credentials, deployment changes or live banking actions.", "",
             "## What another reviewer can reproduce", "",
             "```powershell", "python -m pip install -r requirements-review.txt",
             "python scripts/review_evidence.py --out docs/review", "```", "",
             "The exact environment, inspected source hashes and named test results are in [replay-receipt.json](replay-receipt.json). "
             "The replay fails if a checked invariant/test fails or inspected source changes during execution. "
             "Machine paths and wall-clock durations can differ; compare logical data hashes, decisions and denominators.", "",
             "## Routing: compare useful discrimination and escalation cost", "",
             "**These are 120 independently AI-authored diagnostic utterances with proposed labels, not human-reviewed customer outcomes.** "
             "The already published C=8 and tau=0.65 remain fixed. This replay adds uncertainty analysis after prior error inspection; "
             "it is not a fresh blind evaluation and makes no production quality claim.", "",
             "| System | Correct / 120 | Difference from keywords, paired 95% CI | Human-required misroutes / 30 | Unnecessary human routes / 90 |",
             "| --- | ---: | --- | ---: | ---: |"]
    for name, system in router["systems"].items():
        comparison = router["paired_comparisons"][name]
        lo, hi = comparison["paired_bootstrap_ci95"]
        lines.append(f"| {name} | {round(system['accuracy'] * 120)} | {comparison['accuracy_difference_vs_keywords']:+.1%} "
                     f"({lo:+.1%} to {hi:+.1%}) | {system['human_missed']} | {system['unnecessary_handoffs']} |")
    lines += ["", "The raw classifier improves this diagnostic's label agreement over keywords, but still misses human-required cases. "
              "Abstention reduces those misses while sending many otherwise nonhuman-labelled cases to a person. "
              "A nonhuman route is not a completed resolution. Neither configuration is promoted by this report. "
              "Wilson intervals in [router-replay.json](router-replay.json) show uncertainty for the small safety denominator. "
              "Independent human adjudication and an untouched evaluation set remain necessary before a customer-quality claim.", "",
              "## Data: inspect every transformation", "",
              "[pipeline-replay.json](pipeline-replay.json) and the base/repeat/late manifests record all six fixture tables. "
              "The replay checks row reconciliation, quarantine/deduplication, equal logical content on rerun, ownership exclusion, "
              "a Pending-to-Reversed late correction, a newly visible transaction and preservation of the prior published snapshot. "
              "This is public synthetic-fixture execution; it does not recompute the private organizer-data report.", "",
              "| Table | Raw | Serving silver | Quarantined | Duplicates removed |", "| --- | ---: | ---: | ---: | ---: |"]
    for table, values in pipeline["base_tables"].items():
        lines.append(f"| {table} | {values['raw_rows']} | {values['rows']} | {values['quarantined_rows']} | {values['duplicate_rows_removed']} |")
    summary = analytics["metrics"]
    lines += ["", "## Analytics: decisions and their denominators", "",
              f"[analytics-replay.json](analytics-replay.json) projects {summary['volume']['workflow_turns']} workflow turns "
              f"from {summary['volume']['workflow_conversations']} synthetic workflow conversations and "
              f"{summary['volume']['transcript_only_turns']} transcript-only turn. "
              "The read-only source hashes stay unchanged and the output excludes raw customer text/identifiers. "
              "Synthetic outcomes are one verified action, one handoff and one transcript-only conversation; "
              "reported containment uses the two workflow conversations. Node p50/p95, retry/error rates and feedback "
              "are reproducible metadata calculations, not customer benefit estimates.", "",
              "Operational decisions supported: inspect tool retries/errors before adding concurrency; separate transcript-only "
              "traffic from workflow containment; review safety misses and over-escalation together. "
              "Live cost per case, repeat-contact reduction, human pickup and sustained reliability remain unmeasured. "
              "This replay has zero external inference cost because it issues no provider requests.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/review")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat()
    source_hashes = {p: digest(ROOT / p) for p in SOURCE_PATHS}
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    clock = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="savia-public-replay-") as temporary:
        scratch = Path(temporary)
        tests = test_replay(scratch, out)
        pipeline = pipeline_replay(scratch, out)
        analytics = analytics_replay(scratch, out)
        router = router_replay(out)
    unchanged = source_hashes == {p: digest(ROOT / p) for p in SOURCE_PATHS}
    passed = not tests["exit_code"] and all(pipeline["checks"].values()) and all(analytics["checks"].values()) and unchanged
    receipt = {"schema": "savia-public-evidence-replay/v1", "status": "passed" if passed else "failed",
               "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
               "elapsed_seconds": round(time.perf_counter() - clock, 3), "git_head_at_start": head,
               "source_state": "working-tree subset identified by source_sha256; Git HEAD is base context, not whole-release acceptance",
               "source_sha256": source_hashes, "inspected_source_unchanged": unchanged,
               "python": platform.python_version(), "platform": platform.platform(),
               "libraries": {name: importlib.metadata.version(name) for name in
                             ["duckdb", "numpy", "scikit-learn", "scipy", "joblib", "threadpoolctl",
                              "cloudpickle", "narwhals", "pytest", "PyYAML"]},
               "tests": {k: tests[k] for k in ["exit_code", "total", "passed"]},
               "pipeline_checks": pipeline["checks"], "analytics_checks": analytics["checks"],
               "provider_requests": 0, "label_quality": router["label_quality"],
               "limitations": ["synthetic pipeline/analytics fixtures", "AI-proposed routing labels; human adjudication pending",
                               "previously inspected frozen diagnostic, not new blind evidence", "not live customer or deployment acceptance"]}
    write_json(out / "replay-receipt.json", receipt)
    (out / "PUBLIC_EVIDENCE.md").write_text(render(receipt, router, pipeline, analytics), encoding="utf-8")
    print(json.dumps({"status": receipt["status"], "tests": receipt["tests"], "out": str(out)}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
