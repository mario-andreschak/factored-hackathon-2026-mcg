# Local organizer requirements and prior evaluation evidence

Audited October 4, 2026, America/Bogota. This is a read-only source audit, not a new evaluation or runtime acceptance run. Audit provider calls: **0**; banking/tool calls: **0**. Page references below are one-based PDF pages. Kickoff pages 6 and 18 were also visually inspected because the timeline dates are embedded images.

## Submission package

Source: [local kickoff](../../reference/Datathon_2026_Kickoff.pdf), pages 6 and 18.

| Requirement | Exact constraint in the local source | Release implication |
| --- | --- | --- |
| Deadline | Timeline page 6: **October 5**, submissions close. | The PDF does not state a cutoff hour or timezone. Do not invent an 11:59 PM deadline. |
| Repository | Page 18: public GitHub repository; naming structure `factored-hackathon-2026-[your team's name]`. | Include a usable repository link. The slide prints `public*` but contains no explanatory footnote. |
| Deployment | Page 18: link to where the tool is deployed. | A local recording/source snapshot alone does not fulfill this requested link. |
| Presentation | Page 18: **4–6 slides**, with details on the tool. | Keep the submitted presentation in this range. |
| Video | Page 18: short, mandatory video pitch demonstrating the working solution and explaining core architectural decisions. | No numerical duration, codec, resolution, aspect ratio, or file-size limit appears in either audited PDF. |
| Delivery destination | Page 18: `hackathon.admin@factored.ai`. | This audit sends no email. |
| Extra assets | No separate pitch deck, editable-format requirement, speaker-note requirement, or PDF-export requirement was found. | Those are useful human/release deliverables from coordination, not organizer mandates established by these PDFs. |

The page 6 timeline also lists September 25 challenge launch, October 15 finalists announced, and October 16 award ceremony. Do not infer additional submission rules from those dates.

## What the demonstration and measurements must establish

Source: [local problem statement](../../reference/Factored%20AI%20%26%20Data%20Hackathon%202026%20%281%29.pdf), pages 2–6; kickoff pages 10–15 corroborate the broad expectations.

| Area | Organizer requirement and page | Consequence for Savia's evidence |
| --- | --- | --- |
| Focus and customer usefulness | One coherent end-to-end workflow; explain prioritization using supplied data and establish a baseline (p2–3). Include normal resolution, ambiguity/unsupported requests, and human intervention; demonstrate Spanish and Portuguese (p3). | A ticket creation alone cannot prove the customer problem was resolved. Show verified facts, helpful next steps, continuity, and an honest follow-up. |
| Grounding and authority | Maintain context, clarify ambiguity, ground responses in permitted information, report only verified action outcomes (p3). Enforce permissions/policy outside model prose; handoff includes request, facts, actions, evidence, unresolved questions (p3). | Record the actual successful read/receipt used for each action claim. Distinguish model language from host/tool authorization. |
| Learned component | Compare a learned component with an appropriate baseline; valid labels or relevance judgments, leakage prevention, justified metrics/thresholds/splits (p3). Same held-out workload; state mix, label quality, model/prompt versions and variability; include failures (p5). | The existing frozen router comparison is relevant component evidence with disclosed label limitations. It does not replace the joined customer-path comparison. |
| Failure coverage | Held-out incorrect/missing data, expired sessions, unauthorized access, injection, tool failures, multilingual ambiguity; report outcomes, unsafe outcomes, handoff, latency, cost, sample sizes, limitations (p3–4). | Keep deterministic policy tests separate from real provider/browser calls; identify each simulated portion. |
| Outcome definitions | Safe automated resolution is a correct policy-compliant outcome without a human, over all in-scope cases, plus automation-attempt share (p6). Containment is merely ending without transfer (p6). Escalation quality includes useful context, missed and unnecessary transfers (p6). | An intent route or a local intake receipt is neither bank resolution nor accepted live-agent transfer. |
| Efficiency | End-to-end p50/p95 latency and cost per attempted case and per successful automated resolution; workload, n, assumptions; use **not defined** if no successful resolutions (p6). | Foreground response and background task latency can be reported separately, with a defined customer-visible end-to-end boundary. Tiny n does not establish capacity. |
| Input provenance | Identify real, de-identified, synthetic, and team-generated inputs; exclude private customer records, credentials, restricted data from public submissions/external requests (p5). Sandbox/mock banking tools are acceptable if contracts and limits are documented (p5). | Use fictional customers in public recordings. Say which bank behavior is simulated even when model/tool calls really ran. |
| Runtime limits | Prototype need not operate a live bank (p2); tracing, bounded retries, safe fallback, reproducible setup, capacity/access/retention and remaining work (p4). No live lending or money movement required or authorized (p5). | Honest source/runtime separation and sandbox disclosure satisfy the intended scope better than unsupported live-bank claims. |
| Architecture freedom | New model training, multiple agents, tool-count targets, streaming, forecasting, dashboards are not mandatory (p4). | Avoid adding features purely to satisfy a nonexistent numeric architecture requirement. |

If an LLM judges answers, the statement requires a documented rubric and a sample validated against human or deterministic judgments (p5). Offline comparisons, simulations, and projected business savings must be labeled separately; an offline comparison is not a measured production improvement (p6). Zero failures in a small sample does not establish zero risk (p6).

## Reusable frozen router diagnostic

The authoritative existing comparison is [the frozen report](../../demo/intent_router_evaluation.md) and [machine-readable results](../../demo/intent_router_evaluation.json), with [holdout provenance](../../ml/router_holdout_provenance.md). Do not use the older [provisional report](../../ml/router_report.md)'s 90% model accuracy as the final holdout result: its 60 test phrases shared authorship with training and only 8 were Portuguese.

The frozen workload has **120** synthetic cases: 60 Spanish, 60 Portuguese, four classes with 15 cases per class/language; training has 307 AI/team-authored phrases. A separate AI author did not inspect training phrases or model predictions. Labels remain **not independently human-adjudicated**. The balanced workload is diagnostic, not a sample of customer traffic. Frozen v2 changed one Portuguese utterance before reporting to address a training-similarity finding; v1 remains preserved. No outcome-driven tuning is recorded. C=8 and abstention threshold=0.65 were chosen from training-only cross-validation before this workload existed.

| Offline intent system | Accuracy, 95% bootstrap CI | Macro-F1 | Human-required cases routed elsewhere (n=30) | Unnecessary human routes (n=90 nonhuman reference cases) | Nonhuman-route share |
| --- | --- | --- | --- | --- | --- |
| Keyword baseline | 58.3%, 49.2–67.5% | 0.569 | 13/30 | 6/90 | 80.8% |
| TF-IDF + logistic regression | 78.3%, 70.8–85.0% | 0.782 | 3/30 | 9/90 | 70.0% |
| Same model + fixed abstention | 54.2%, 45.0–63.3% | 0.548 | 1/30 | 52/90 | 32.5% |

Language accuracy: baseline ES/PT 58.3%/58.3%; raw learned model 81.7%/75.0%; abstaining model 58.3%/50.0% (60 cases per language). The fixed abstention policy reduces missed human routes while increasing unnecessary human routes. Preserve both sides of that trade-off if shown on a slide.

Safe wording: **“On 120 frozen synthetic ES/PT intent cases with AI-authored labels awaiting human review, the learned router achieved 78.3% label accuracy versus 58.3% for keywords.”** If reporting the difference, call it **20.0 percentage points on this offline workload**, never a production service improvement or resolution rate.

This report uses local conventional ML, not new external LLM/provider calls. Nonhuman-route share is not automated resolution, and human misroutes are a component safety proxy rather than observed bank harm. It does not establish deployment performance, live model capacity, real customer isolation, authorization, grounding, follow-up quality, latency, cost, or banking resolution. Independent human adjudication remains the explicit provenance-note requirement before final submission; this audit has not supplied it. Later human labels must be separately versioned without modifying frozen bytes or tuning on observed errors.

## Verified provenance and replay

All hashes below were checked against current local bytes in this audit. The recorded report hashes match the local training and v2 holdout hashes. No model fitting or replay was performed by this audit.

| Artifact | SHA256 |
| --- | --- |
| `docs/reference/Factored AI & Data Hackathon 2026 (1).pdf` | `a913b701270460cf8fe3dda676bc9905e5826eed8578e3f1186f125361631275` |
| `docs/reference/Datathon_2026_Kickoff.pdf` | `94179ae60274bec8cb7f7926a5c3bb6a882b30b48986ba889028fcc8e6139768` |
| `ml/data/router_test.csv` | `3c4f68d880146915d7fb27c7884733190c1d87d84e1fee6d066afeed85538684` |
| `ml/data/router_test_blind_v1.csv` | `d23b67fffc2a3ef5367452e23ff9c20fe8cb3763942a68dd19860535b05ab303` |
| `ml/data/router_train.csv` | `23f1022bbbbe51582cd50a88464cd85f885465729dfd7494e90a9be680190509` |
| `docs/demo/intent_router_evaluation.json` | `1e4cd6b8d7bc13a1f15ce12651a618e5019f21a1f548a3315ce9fa99929211d5` |
| `demo/evaluate_router.py` | `b843879a7b5275cbae2b67ad45683b983b768c8d517c4f055a269fc661d71e9e` |

Replay from repository root, using an existing Python environment with `requirements-ml.txt` dependencies:

```powershell
python -m demo.evaluate_router --report-dir docs/submission/measurements/router-replay
```

The script validates hash, schema, mix, authorship, uniqueness, normalized exact overlap and character-similarity overlap, fits the previously fixed model, and writes new offline reports to that output directory. Existing report versions: scikit-learn 1.9.1, NumPy 2.5.3, seed 7. Preserve these versions for a directly comparable replay. This command makes no provider or banking calls and must not be represented as deployed acceptance.

The [FLUJO deployment source map](../../FLUJO_HACKATHON_DEPLOYMENT.md) explicitly separates generic main, the preserved hackathon branch, the older worker, and project-owned host source. Historical source preservation and isolated operator tests cannot be relabeled current joined customer-path acceptance. New runtime measurements should record the actual immutable source, UI/API/provider configuration, bank simulation contract, exact case count, attempted/completed calls, receipts, failure counts, and customer-usefulness rubric.
