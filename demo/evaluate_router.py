"""One fixed router/baseline comparison on the frozen AI-authored diagnostic set.

No provider calls, model artifacts, training data edits, or threshold tuning.
Writes separate honest component reports; never measures banking resolution.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

FROZEN_SHA256 = "3c4f68d880146915d7fb27c7884733190c1d87d84e1fee6d066afeed85538684"
FIXED_C = 8
FIXED_TAU = 0.65
ROOT = Path(__file__).resolve().parents[1]
HOLDOUT = ROOT / "ml/data/router_test.csv"


def frozen_cases(path: Path = HOLDOUT) -> list[dict]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != FROZEN_SHA256:
        raise ValueError("holdout_hash_mismatch")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["text", "label", "lang", "author"]:
            raise ValueError("invalid_holdout_schema")
        cases = list(reader)
    counts = Counter((row["label"], row["lang"]) for row in cases)
    if counts != Counter({(label, lang): 15 for label in ("inquiry", "dispute", "human", "other") for lang in ("es", "pt")}):
        raise ValueError("invalid_holdout_mix")
    if len({row["text"] for row in cases}) != 120 or any(row["author"] != "codex_blind_holdout_20260928" for row in cases):
        raise ValueError("invalid_holdout_authorship")
    return cases


def evaluate() -> dict:
    import numpy as np
    import sklearn
    from ml import router

    cases = frozen_cases()
    train = router.read_csv(router.TRAIN)
    train_text = [r["text"] for r in train]
    text, labels, languages = ([r[k] for r in cases] for k in ("text", "label", "lang"))
    if ({router.normalize(t) for t in train_text} & {router.normalize(t) for t in text}
            or router.near_duplicates(train_text, text)):
        raise ValueError("holdout_training_overlap")
    # C/tau were already selected on training CV in the committed provisional
    # report before this diagnostic workload existed; do not optimize them here.
    model = router.build_pipeline(FIXED_C).fit(train_text, [r["label"] for r in train])
    probabilities = model.predict_proba(text)
    classes = list(model.classes_)
    raw = [classes[i] for i in probabilities.argmax(1)]
    routed = router.route(probabilities, classes, FIXED_TAU)
    baseline = router.baseline_predict(text)
    systems = {}
    for name, predictions in [("keyword_baseline", baseline), ("tfidf_logistic", raw), ("tfidf_logistic_abstention", routed)]:
        measured = router.metrics(labels, predictions, languages, np.random.default_rng(router.SEED))
        automated = [(actual, predicted) for actual, predicted in zip(labels, predictions) if predicted != "human"]
        measured["automated_share"] = round(len(automated) / len(cases), 3)
        measured["precision_on_nonhuman_routes"] = round(sum(a == p for a, p in automated) / len(automated), 3) if automated else None
        systems[name] = measured
    return {"scope": "offline intent component; not banking resolution, customer isolation or live provider capacity",
            "label_quality": "independently AI-authored; human adjudication pending",
            "workload": "balanced diagnostic 120 cases; 60 es/60 pt; 15 per label per language",
            "holdout_sha256": FROZEN_SHA256, "train_sha256": hashlib.sha256(router.TRAIN.read_bytes()).hexdigest(),
            "train_n": len(train), "test_n": len(cases), "model": "TF-IDF char/word + logistic regression",
            "scikit_learn_version": sklearn.__version__, "numpy_version": np.__version__,
            "fixed_C": FIXED_C, "fixed_tau": FIXED_TAU, "seed": router.SEED,
            "parameter_source": "committed provisional report: training-only cross-validation, before this holdout",
            "normalized_exact_overlap": 0, "near_duplicate_overlap_above_0_8": 0,
            "systems": systems,
            "errors": [{"case": index + 1, "text": row["text"], "lang": row["lang"], "expected": row["label"],
                        "baseline": b, "model": m, "with_abstention": r}
                       for index, (row, b, m, r) in enumerate(zip(cases, baseline, raw, routed))
                       if any(p != row["label"] for p in (b, m, r))]}


def render(report: dict) -> str:
    lines = ["# Frozen ES/PT router diagnostic", "",
             "**AI-authored labels; independent human adjudication is still pending.**",
             "This measures intent routing only. It does not measure safe banking resolution, authentication, or production improvement.", "",
             "120 balanced diagnostic cases (60 ES/60 PT), 307 training phrases. C=8 and abstention threshold=0.65 were fixed from training-only CV before this workload existed.", "",
             "| System | Accuracy (95% bootstrap CI) | Macro-F1 | Human-required routed elsewhere | Unnecessary human routes | Nonhuman-route share |",
             "| --- | --- | --- | --- | --- | --- |"]
    for name, measured in report["systems"].items():
        lo, hi = measured["accuracy_ci95"]
        lines.append(f"| {name} | {measured['accuracy']:.1%} ({lo:.1%}–{hi:.1%}) | {measured['macro_f1']:.3f} | "
                     f"{measured['human_missed']}/{measured['human_total']} | {measured['unnecessary_handoffs']} | {measured['automated_share']:.1%} |")
    lines += ["", "| System | ES label accuracy (n=60) | PT label accuracy (n=60) |", "| --- | --- | --- |"]
    for name, measured in report["systems"].items():
        lines.append(f"| {name} | {measured['by_lang']['es']['accuracy']:.1%} | {measured['by_lang']['pt']['accuracy']:.1%} |")
    lines += ["", "A nonhuman route is not an automated case resolution. A `human` misroute is a component safety proxy, not an observed bank disclosure or action.",
              "Balanced languages/classes do not estimate traffic prevalence. AI label uncertainty, small per-class samples, and authored scenario families limit conclusions.",
              "The v1 similarity-screen correction and both dataset hashes are recorded in `docs/ml/router_holdout_provenance.md`. No outcome-driven tuning was performed. Do not tune on this workload after reading its errors.",
              "", "Hashes, library versions, confusion matrices and all component errors are in `intent_router_evaluation.json`.",
              "Existing graphical ES/PT provider tests, ownership tests, and end-to-end latency/cost measurements remain separate acceptance gates.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "docs/demo")
    args = parser.parse_args()
    report = evaluate()
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "intent_router_evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.report_dir / "intent_router_evaluation.md").write_text(render(report), encoding="utf-8")
    print(json.dumps({"test_n": report["test_n"], "labels": report["label_quality"], "systems": report["systems"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
