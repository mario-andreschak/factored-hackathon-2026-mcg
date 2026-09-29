# Frozen ES/PT router diagnostic

**AI-authored labels; independent human adjudication is still pending.**
This measures intent routing only. It does not measure safe banking resolution, authentication, or production improvement.

120 balanced diagnostic cases (60 ES/60 PT), 307 training phrases. C=8 and abstention threshold=0.65 were fixed from training-only CV before this workload existed.

| System | Accuracy (95% bootstrap CI) | Macro-F1 | Human-required routed elsewhere | Unnecessary human routes | Nonhuman-route share |
| --- | --- | --- | --- | --- | --- |
| keyword_baseline | 58.3% (49.2%–67.5%) | 0.569 | 13/30 | 6 | 80.8% |
| tfidf_logistic | 78.3% (70.8%–85.0%) | 0.782 | 3/30 | 9 | 70.0% |
| tfidf_logistic_abstention | 54.2% (45.0%–63.3%) | 0.548 | 1/30 | 52 | 32.5% |

| System | ES label accuracy (n=60) | PT label accuracy (n=60) |
| --- | --- | --- |
| keyword_baseline | 58.3% | 58.3% |
| tfidf_logistic | 81.7% | 75.0% |
| tfidf_logistic_abstention | 58.3% | 50.0% |

A nonhuman route is not an automated case resolution. A `human` misroute is a component safety proxy, not an observed bank disclosure or action.
Balanced languages/classes do not estimate traffic prevalence. AI label uncertainty, small per-class samples, and authored scenario families limit conclusions.
The v1 similarity-screen correction and both dataset hashes are recorded in `docs/ml/router_holdout_provenance.md`. No outcome-driven tuning was performed. Do not tune on this workload after reading its errors.

Hashes, library versions, confusion matrices and all component errors are in `intent_router_evaluation.json`.
Existing graphical ES/PT provider tests, ownership tests, and end-to-end latency/cost measurements remain separate acceptance gates.
