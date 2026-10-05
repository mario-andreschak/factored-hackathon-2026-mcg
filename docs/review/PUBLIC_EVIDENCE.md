# Public evidence replay

Executed 2026-10-05T21:27:17.630091+00:00 with Git base `795a0c37233091e522f8709c31598addb330188a` and the exact working-tree source subset identified by SHA-256 in the receipt. The base commit alone does not identify the new replay script.

**PASSED**: 67/67 existing offline checks passed; 7 pipeline and 4 analytics replay invariants passed. No provider requests, credentials, deployment changes or live banking actions.

## What another reviewer can reproduce

```powershell
python -m pip install -r requirements-review.txt
python scripts/review_evidence.py --out docs/review
```

The exact environment, inspected source hashes and named test results are in [replay-receipt.json](replay-receipt.json). The replay fails if a checked invariant/test fails or inspected source changes during execution. Machine paths and wall-clock durations can differ; compare logical data hashes, decisions and denominators.

## Routing: compare useful discrimination and escalation cost

**These are 120 independently AI-authored diagnostic utterances with proposed labels, not human-reviewed customer outcomes.** The already published C=8 and tau=0.65 remain fixed. This replay adds uncertainty analysis after prior error inspection; it is not a fresh blind evaluation and makes no production quality claim.

| System | Correct / 120 | Difference from keywords, paired 95% CI | Human-required misroutes / 30 | Unnecessary human routes / 90 |
| --- | ---: | --- | ---: | ---: |
| keyword_baseline | 70 | +0.0% (+0.0% to +0.0%) | 13 | 6 |
| tfidf_logistic | 94 | +20.0% (+10.0% to +30.0%) | 3 | 9 |
| tfidf_logistic_abstention | 65 | -4.2% (-15.8% to +7.5%) | 1 | 52 |

The raw classifier improves this diagnostic's label agreement over keywords, but still misses human-required cases. Abstention reduces those misses while sending many otherwise nonhuman-labelled cases to a person. A nonhuman route is not a completed resolution. Neither configuration is promoted by this report. Wilson intervals in [router-replay.json](router-replay.json) show uncertainty for the small safety denominator. Independent human adjudication and an untouched evaluation set remain necessary before a customer-quality claim.

## Data: inspect every transformation

[pipeline-replay.json](pipeline-replay.json) and the base/repeat/late manifests record all six fixture tables. The replay checks row reconciliation, quarantine/deduplication, equal logical content on rerun, ownership exclusion, a Pending-to-Reversed late correction, a newly visible transaction and preservation of the prior published snapshot. This is public synthetic-fixture execution; it does not recompute the private organizer-data report.

| Table | Raw | Serving silver | Quarantined | Duplicates removed |
| --- | ---: | ---: | ---: | ---: |
| customers | 22 | 20 | 0 | 2 |
| products | 21 | 21 | 0 | 0 |
| transactions | 69 | 66 | 2 | 1 |
| call_center_interactions | 60 | 60 | 0 | 0 |
| call_transcripts | 60 | 60 | 0 | 0 |
| complaints | 5 | 5 | 0 | 0 |

## Analytics: decisions and their denominators

[analytics-replay.json](analytics-replay.json) projects 3 workflow turns from 2 synthetic workflow conversations and 1 transcript-only turn. The read-only source hashes stay unchanged and the output excludes raw customer text/identifiers. Synthetic outcomes are one verified action, one handoff and one transcript-only conversation; reported containment uses the two workflow conversations. Node p50/p95, retry/error rates and feedback are reproducible metadata calculations, not customer benefit estimates.

Operational decisions supported: inspect tool retries/errors before adding concurrency; separate transcript-only traffic from workflow containment; review safety misses and over-escalation together. Live cost per case, repeat-contact reduction, human pickup and sustained reliability remain unmeasured. This replay has zero external inference cost because it issues no provider requests.
