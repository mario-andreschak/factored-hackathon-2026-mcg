"""Read existing public evidence and derive operating decisions; no provider calls.

python scripts/analyze_operating_evidence.py --out docs/review
Requires matplotlib for two exported figures; never tunes a model or edits inputs.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics

ROOT = Path(__file__).resolve().parents[1]
LUNA = "docs/submission/measurements/luna-100/run-100/"
INPUTS = [LUNA + name for name in ["requests.jsonl", "workload.json", "summary.json", "baseline.json", "audit.json"]] + [
    "docs/review/router-replay.json", "ml/data/router_test.csv", "docs/pipeline/manifest.json",
    "ml/README.md", "docs/submission/measurements/final-comparison-counted.json",
    "docs/submission/measurements/post-fix-pt-selected-counted.json",
    "scripts/analyze_operating_evidence.py",
]


def hashes() -> dict[str, str]:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in INPUTS}


def load(name: str):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def latency(rows: list[dict]) -> dict:
    values = sorted(float(row["latency_seconds"]) for row in rows)
    return {"n": len(values), "minimum_seconds": round(values[0], 6),
            "p50_seconds": round(statistics.median(values), 6),
            "p95_seconds": round(values[math.ceil(.95 * len(values)) - 1], 6),
            "maximum_seconds": round(values[-1], 6)}


def analyze() -> tuple[dict, list[dict]]:
    import numpy as np
    import csv

    requests = [json.loads(line) for line in (ROOT / (LUNA + "requests.jsonl")).read_text(encoding="utf-8").splitlines() if line]
    workload, summary, baseline, audit = (load(LUNA + name) for name in ["workload.json", "summary.json", "baseline.json", "audit.json"])
    expected = {case["task"]["case_id"]: case["expected"] for case in workload}
    assert len(requests) == len(expected) == len({r["case_id"] for r in requests}) == 100
    assert all(r["parsed_output"] == expected[r["case_id"]] and r["correct"] and r["safe"] for r in requests)
    assert all(not r["tool_attempts"] and r["turn_status"] == "completed" for r in requests)
    assert len(baseline) == 100 and all(r["output"] == expected[r["case_id"]] for r in baseline)
    assert all(r["model_returned"] == "gpt-6-luna" for r in requests)
    totals = {key: sum(r["token_usage"]["total"][key] for r in requests) for key in
              ["inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens", "totalTokens"]}
    assert all(totals[key] == audit["counts"][key] for key in totals)
    assert totals["totalTokens"] == totals["inputTokens"] + totals["outputTokens"]
    all_latency = latency(requests)
    assert abs(all_latency["p50_seconds"] - summary["p50_seconds"]) < .000001
    assert abs(all_latency["p95_seconds"] - summary["p95_seconds"]) < .000001
    groups = {key: {value: latency([r for r in requests if r[key] == value]) for value in sorted({r[key] for r in requests})}
              for key in ["language", "scenario"]}
    phrases = Counter(case["task"]["customer_request"] for case in workload)

    router = load("docs/review/router-replay.json")
    with (ROOT / "ml/data/router_test.csv").open(encoding="utf-8", newline="") as handle:
        cases = list(csv.DictReader(handle))
    assert len(cases) == router["test_n"] == 120
    assert hashlib.sha256((ROOT / "ml/data/router_test.csv").read_bytes()).hexdigest() == router["holdout_sha256"]
    truth = [c["label"] for c in cases]
    predictions = {name: truth.copy() for name in router["systems"]}
    mapping = {"keyword_baseline": "baseline", "tfidf_logistic": "model", "tfidf_logistic_abstention": "with_abstention"}
    for error in router["errors"]:
        for name, field in mapping.items():
            predictions[name][error["case"] - 1] = error[field]
    correct = {name: np.array(values) == np.array(truth) for name, values in predictions.items()}
    indices = np.random.default_rng(7).integers(0, 120, (10000, 120))
    routing = {}
    for name, values in predictions.items():
        human_missed = sum(actual == "human" and predicted != "human" for actual, predicted in zip(truth, values))
        unnecessary = sum(actual != "human" and predicted == "human" for actual, predicted in zip(truth, values))
        assert human_missed == router["systems"][name]["human_missed"]
        assert unnecessary == router["systems"][name]["unnecessary_handoffs"]
        difference = correct[name].astype(float) - correct["keyword_baseline"].astype(float)
        interval = [round(float(v), 6) for v in np.quantile(difference[indices].mean(axis=1), [.025, .975])]
        assert interval == router["paired_comparisons"][name]["paired_bootstrap_ci95"]
        routing[name] = {"correct": int(correct[name].sum()), "n": 120,
                         "human_missed": human_missed, "human_n": 30, "unnecessary_handoffs": unnecessary, "nonhuman_n": 90,
                         "paired_accuracy_difference_vs_keywords": round(float(difference.mean()), 6),
                         "paired_bootstrap_ci95": interval,
                         "human_misroute_ci95_wilson": router["systems"][name]["human_misroute_rate_ci95_wilson"]}

    pipeline = load("docs/pipeline/manifest.json")
    affected = pipeline["tables"]["complaints"]["silver"]["orphans"]["affected_product_id"]
    texts = pipeline["gold"]["classifier_dataset"]
    assert affected["non_null"] == affected["owned_by_other_customer"] == 44570
    assert texts["distinct_normalized_texts"] == 42
    assert texts["test_rows_with_text_seen_in_train"] == texts["splits"]["test"] == 2946
    assert texts["test_text_leakage_rate"] == 1
    historical, post_fix = (load("docs/submission/measurements/" + name) for name in
                            ["final-comparison-counted.json", "post-fix-pt-selected-counted.json"])
    customer = []
    for case in historical["cases"]:
        actual = case["actual"]
        operations = [o for o in actual["observed_operations"] if o["kind"] == "model"]
        customer.append({"case": case["case"], "language": case["language"], "latency_ms": actual["latency_ms"],
                         "http_status": actual["http_status"], "exact_history": actual["exact_reply_in_history"],
                         "useful_agent_screened": case["agent_screening"]["useful"], "human_adjudicated": False,
                         "model_calls": actual["model_call_count"],
                         "prompt_tokens": sum(o["prompt_tokens"] for o in operations),
                         "completion_tokens": sum(o["completion_tokens"] for o in operations),
                         "reported_dollar_cost": None})
    assert len(customer) == 3 and sum(c["useful_agent_screened"] for c in customer) == 2
    return {
        "scope": "read-only analysis of three separate published workloads; no new provider/model execution",
        "luna": {"requests": 100, "distinct_customer_request_phrases": len(phrases),
                 "phrase_repeat_counts": sorted(phrases.values()), "correct": 100, "bounded_safe": 100,
                 "baseline_correct": 100, "latency": all_latency, "latency_slices": groups,
                 "tokens": totals, "uncached_input_tokens": totals["inputTokens"] - totals["cachedInputTokens"],
                 "cached_fraction_of_input_tokens": round(totals["cachedInputTokens"] / totals["inputTokens"], 6),
                 "input_to_output_token_ratio": round(totals["inputTokens"] / totals["outputTokens"], 3),
                 "dollar_cost": None, "cost_reason": "subscription usage; no dollar billing receipt",
                 "model_identity_scope": "requested/returned app-server identity; server-side identity not independently observable",
                 "latency_boundary": "submission to completed app-server turn including network/admission/queueing"},
        "router": {"systems": routing, "label_quality": "AI-proposed diagnostic labels; independent human adjudication pending",
                   "reproduction": "existing published decisions and paired intervals independently recalculated; not a new blind test"},
        "data": {"evidence_grade": "published organizer-source aggregate manifest; raw private source not recomputed",
                 "complaint_affected_product_links": affected["non_null"], "cross_customer_links": affected["owned_by_other_customer"],
                 "total_complaints": pipeline["tables"]["complaints"]["silver"]["rows"],
                 "classifier_dataset": texts},
        "customer": {"original_three_cases": customer, "post_fix_separate_n1": post_fix["summary"],
                     "post_fix_limit": "deterministic trusted-host selected_fallback after guarded model rejection; separate revision",
                     "bank_resolution_observed": False},
    }, requests


def figures(report: dict, requests: list[dict], out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), gridspec_kw={"width_ratios": [1, 2]})
    axes[0].boxplot([[r["latency_seconds"] for r in requests if r["language"] == language] for language in ["es", "pt"]],
                    tick_labels=["Spanish\nn=50", "Portuguese\nn=50"], showfliers=True)
    axes[0].set_ylabel("Submit to completion (seconds)")
    axes[0].set_title("Language slices")
    slices = report["luna"]["latency_slices"]["scenario"]
    labels = list(slices)
    x = np.arange(len(labels))
    axes[1].bar(x - .18, [slices[s]["p50_seconds"] for s in labels], .36, label="p50", color="#167d7f")
    axes[1].bar(x + .18, [slices[s]["p95_seconds"] for s in labels], .36, label="p95", color="#de9440")
    axes[1].set_xticks(x, [s.replace("_", "\n") + "\nn=20" for s in labels])
    axes[1].set_ylabel("Submit to completion (seconds)")
    axes[1].legend(frameon=False)
    axes[1].set_title("Five generated scenario slices")
    fig.suptitle("Observed Luna latency: 100 requests, 10 distinct customer phrases", fontweight="bold")
    fig.text(.5, .005, "Request intervals include network/admission/queueing; slices are descriptive, not independent ES/PT generalization.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .04, 1, .94))
    fig.savefig(out / "luna-latency.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8.5, 5.3))
    names = {"keyword_baseline": "Keywords", "tfidf_logistic": "Classifier", "tfidf_logistic_abstention": "Classifier + abstention"}
    for name, system in report["router"]["systems"].items():
        x, y = system["unnecessary_handoffs"] / 90 * 100, system["human_missed"] / 30 * 100
        lo, hi = [v * 100 for v in system["human_misroute_ci95_wilson"]]
        ax.errorbar(x, y, yerr=[[y - lo], [hi - y]], fmt="o", capsize=5, markersize=8)
        offset = (-125, 6) if name.endswith("abstention") else (9, 3)
        ax.annotate(f"{names[name]}\nmisses {system['human_missed']}/30; extra {system['unnecessary_handoffs']}/90", (x, y),
                    xytext=offset, textcoords="offset points", fontsize=10)
    ax.set_xlim(-2, 74)
    ax.set_ylim(0, 68)
    ax.set_xlabel("Nonhuman-labelled cases routed to a person (%) — denominator 90")
    ax.set_ylabel("Human-required cases routed elsewhere (%) — denominator 30")
    ax.set_title("Routing trade-off on 120 AI-labelled diagnostic utterances", fontweight="bold")
    fig.text(.5, .025, "Vertical bars: Wilson 95% intervals. No human adjudication, population safety or bank-resolution claim.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .055, 1, 1))
    fig.savefig(out / "routing-tradeoff.png", dpi=180)
    plt.close(fig)


def render(r: dict) -> str:
    luna, data, customer = r["luna"], r["data"], r["customer"]
    tokens = luna["tokens"]
    return f"""# Operating decisions from measured evidence

This analysis reads existing public artifacts and recomputes their aggregates. It makes **zero provider requests** and changes no model, threshold or source data. [Machine-readable calculations and input hashes](operating-decisions.json) keep the three workloads separate. Reproduce with `python scripts/analyze_operating_evidence.py --out docs/review` (Python, NumPy and Matplotlib; plotting version recorded in the receipt).

| Evidence → denominator | Observed result | Operating decision supported |
| --- | --- | --- |
| [Actual Luna requests](../submission/measurements/luna-100/run-100/requests.jsonl) → 100 generated cases; 50 ES/50 PT, 20 per scenario; **10 distinct phrases**, each repeated with varied facts | 100 exact-correct and bounded-safe; deterministic baseline also 100/100 | Keep ownership, candidate matching and no-write rules in deterministic trusted code. This test demonstrates a structured provider path and does not establish that an LLM improves those decisions or scales customer investigations. |
| Same 100 actual request intervals → submission through completed app-server turn | p50 {luna['latency']['p50_seconds']:.3f}s, p95 {luna['latency']['p95_seconds']:.3f}s, maximum {luna['latency']['maximum_seconds']:.3f}s | Treat this 100-request configuration as background work requiring visible progress. It is not evidence for a conversational latency promise. ES/PT/scenario slices below identify observed tails without attributing them causally to language. |
| Same 100 per-thread token receipts → input count includes cached tokens | {tokens['inputTokens']:,} input, {tokens['outputTokens']:,} output; {tokens['cachedInputTokens']:,} cached ({luna['cached_fraction_of_input_tokens']:.1%} of input); {luna['uncached_input_tokens']:,} uncached | Inspect the default Codex instructions/schema context before scaling: {luna['input_to_output_token_ratio']:.1f} input tokens per output token on short bounded replies. Cache behavior belongs in capacity/cost reporting. Subscription dollar cost is **unknown**; token counts cannot become a free-inference or dollar-saving claim. |
| [Frozen router reproduction](router-replay.json) → 120 proposed AI labels, including 30 human-required and 90 nonhuman-labelled cases | Classifier 94/120 vs keywords 70/120; paired improvement 20 percentage points (95% bootstrap interval 10–30). Misses: 3/30 vs 13/30 | Learned routing distinguishes these authored examples better than keywords. Retain independent human adjudication as an acceptance gate; this is an already inspected diagnostic, not a fresh blind test or deployed quality rate. |
| Fixed tau=.65 on the same diagnostic → no tuning | Abstention reduces human-required misses from 3/30 to 1/30 while increasing unnecessary human routes from 9/90 to 52/90: **43 additional human routes** | Evaluate safety misses and handoff capacity together. The measured burden rules out promoting abstention based on the miss count alone. Do not tune on this known workload. |
| [Published pipeline manifest](../pipeline/manifest.json) → {data['complaint_affected_product_links']:,} non-null affected-product links out of {data['total_complaints']:,} complaints | All {data['cross_customer_links']:,} affected-product links join to a product owned by a different customer, although all referenced products exist | Do not ground a complaint in the product link merely because its foreign key exists. Enforce customer ownership and prefer owned transactions. Public synthetic replay/tests independently prove the exclusion mechanism; private source counts were **not** recomputed here. |
| Same published manifest → 171,321 transcript rows but **42 distinct normalized texts**; 2,946 test rows | 2,946/2,946 held-out rows reuse text seen in train (100% template overlap) | Reject a random-row or time-only split's text-generalization claim. Use independent utterances and label review for the intent component; keep supplied transcript labels outside a learned safety claim. The historical [ML assessment](../../ml/README.md) also reports text-only label agreement bounded near the majority baseline. |
| [Actual original customer comparison](../submission/measurements/final-comparison-counted.json) → n=3 across recorded source boundaries | HTTP200 and exact saved history 3/3; agent-screened useful answers 2/3; human adjudication pending | Transport success and persistence do not imply useful answers. Preserve the Portuguese selected-fact failure as an error; retain selected transaction scope across decomposition. Report usefulness separately from HTTP success. |
| [Post-fix Portuguese record](../submission/measurements/post-fix-pt-selected-counted.json) → separate n=1 and revision | Useful selected-fact display, HTTP200/exact history, {customer['post_fix_separate_n1']['latency_ms']['median']/1000:.3f}s; guarded deterministic host fallback | Credit the recovery path and its latency. Keep it separate from n=3 and from accepted free-form model generation; this is no causal quality or speedup estimate. |

![Actual Luna latency by language and scenario](luna-latency.png)

![Safety misses and escalation burden](routing-tradeoff.png)

The original n=3 records contain 22 actual model-stage calls and disclosed token observations; dollar costs remain absent. Their browser-request boundary, model/provider and revisions differ from Luna's app-server benchmark, so latencies, success counts and token totals are not pooled. Live human pickup, repeat-contact reduction, refund/bank resolution and sustained reliability remain unmeasured. These decisions use the evidence that exists; they do not assign Savia a new judging score.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "docs/review")
    args = parser.parse_args()
    source_hashes = hashes()
    report, requests = analyze()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    figures(report, requests, out)
    import matplotlib
    import numpy
    report["provenance"] = {"analyzed_utc": datetime.now(timezone.utc).isoformat(), "input_sha256": source_hashes,
                            "source_unchanged": source_hashes == hashes(), "python": platform.python_version(),
                            "numpy": numpy.__version__, "matplotlib": matplotlib.__version__,
                            "provider_requests": 0, "latency_percentile_method": "p50 median; p95 nearest rank, ceil(.95*n)",
                            "figure_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in
                                              [out / "luna-latency.png", out / "routing-tradeoff.png"]}}
    assert report["provenance"]["source_unchanged"]
    (out / "operating-decisions.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out / "OPERATING_DECISIONS.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"status": "passed", "actual_requests": 100, "distinct_phrases": report["luna"]["distinct_customer_request_phrases"],
                      "cached_input_fraction": report["luna"]["cached_fraction_of_input_tokens"], "provider_requests": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
