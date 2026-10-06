# Independent Savia / FLUJO repository assessment

**87/100 — a strong complete hackathon submission, with substantive implementation and unusually inspectable evidence.**

Frozen HEAD: `df957f99a6e544cde5a698cfb6d9685e92ee3255`  
Repository: `C:/Users/Moe/.codex/worktrees/savia-review-evidence/factored-hackathon-2026`  
Reviewer: quality-review-4. Independent, repository-only, no target score supplied.

I began with README, read AGENTS.md and the FLUJO product boundary, then followed the submission/customer/pitch route into architecture, the complete R0–R18 dispute lifecycle, implementation, data pipeline, ML diagnostic, analytics, original measured artifacts and comparison material. I did not read earlier assessment/rating reports, other chats or repositories; I did not delegate, browse, install, call a provider/bank, deploy or edit product source.

The judgment covers the **complete declared hackathon submission**: deterministic banking core, implemented conversational enhancements, expandable orchestration and evidence. Fictional customers and simulated actions are appropriate to that scope. The requested video placeholder is a destination, and larger-fleet or real-bank qualification is a separate scope. Neither is treated as a missing hackathon requirement.

| Fixed dimension | Score | Reason |
| --- | ---: | --- |
| technical judgment | 18/20 | Strong deterministic R0-R18 lifecycle, owner/session/query/snapshot binding, explicit consent, independent receipt readback, revocation, idempotency and durable uncertain recovery. Banking stays outside generic FLUJO main. Deduction reflects overlapping legacy/direct/in-process/native integration modes and present-tense architecture wording that requires substantial appendix reading to distinguish targets from current behavior; no checked core action-authority defect was found. |
| AI engineering | 17/20 | Implemented integrated voice, exact playback acknowledgments, bounded factual language inputs, schema/grounding checks and deterministic fallbacks, two real model reviewer roles, durable inquiries and reviewed fleet-result correlation. The recorded two-reviewer enhancement is useful but chooses from six prewritten suggestions; it is less substantive investigation than broad specialist-exploration language implies. Sparse useful-answer observations and pending human audio review limit evidence for conversational breadth. Larger fleet and real-bank qualification are separate scopes, not missing hackathon requirements. |
| data engineering | 19/20 | Substantial six-table 5,899,720-row historical pipeline; raw reconciliation, lineage, typed quarantine, deterministic corrections/deduplication, owner-valid serving, safe aggregates, atomic last-good publication, writer fencing and customer-sharded serving. Critical implementation behavior passed local synthetic tests. A static-source inventory/ETag approach is weaker than version-pinned source reads, and full-refresh/single-writer operation plus explicit operator stale-lock recovery limit expansion, but are well disclosed and appropriate to a hackathon. |
| ML/evaluation | 15/20 | Sound refusal to learn from template-leaked/no-signal source labels, training-only C/tau selection, frozen independently AI-authored ES/PT holdout, keyword/raw/abstention comparison, language/class errors, confusion matrices and uncertainty. Independent reconstruction confirms 70/120 vs 94/120 vs 65/120 and the safety/escalation tradeoff. Ground truth remains unadjudicated despite the provenance document's before-final-submission requirement. Synthetic family dependence and small class slices limit generalization. Luna adds 100 grounded structured completions but only ten request phrasings and ties a deterministic baseline; it is not evidence of ML decision improvement or current UI model quality. |
| data analytics | 18/20 | Privacy-preserving operational extraction and verified current host snapshots keep intent, intake, existing intake, handoff request and actual resolution distinct. Operating evidence connects ownership/leakage/latency/token/error denominators to decisions, and host analytics tests pass. The report is a current-slot snapshot without exact workflow attribution, card-block ledger integration, durable token/cost capture or customer cohort outcome analysis. Those limits are honest, but constrain the analytical depth and decisions supported. |
| **Total** | **87/100** | Complete and convincing within its demonstrated scope; stronger human-adjudicated evaluation and tighter claim/release wording would improve it. |

## First five findings, in discovery order

These are chronological findings, not a severity-ranked list. Later source/tests corroborated the early observations.

1. **strength:** README and the submission/customer route describe an end-to-end focused product with explicit simulated-bank boundaries, retained facts, helpful informational closure and saved follow-through. Evidence: `README.md`, `docs/submission/START_HERE.md`, `docs/submission/CUSTOMER_JOURNEY.md`.

2. **scope finding:** The recorded two-reviewer success and larger fleet design are separate. A later customer fleet attempt failed on its first provider call; the customer guide discloses this. Present-tense ten-team/ready-to-scale phrasing in pitch/comparison needs the same adjacent scope qualification. Evidence: `docs/submission/CUSTOMER_JOURNEY.md`, `web/submission/pitch/savia-final-pitch.html`, `docs/submission/ELEVENLABS_COMPARISON.md`.

3. **comparison finding:** ElevenLabs comparison is useful product positioning, but it is not a matched benchmark or proof that the commercial platform lacks durable cases, policy, tools or consent. The repository itself acknowledges a financial-services dispute showcase and vendor-reported voice metrics. Evidence: `docs/submission/ELEVENLABS_COMPARISON.md`, `web/submission/pitch/slides/slide-03.png`, `web/submission/pitch/savia-final-pitch.html`.

4. **strength with limit:** The generic/domain product boundary is explicit and architecturally supported. The pinned generic FLUJO subset contains reusable chat/flow/tool/MCP/execution contracts; its 104 scoped upstream tests are historical, use mocks and a dependency cache with disclosed version drift. Evidence: `AGENTS.md`, `docs/FLUJO_PRODUCT_BOUNDARY.md`, `docs/FLUJO_HACKATHON_DEPLOYMENT.md`, `docs/submission/FLUJO_PLATFORM_EVIDENCE.md`.

5. **strength:** The R0-R18 engine is executable deterministic policy over typed state, with a runtime that exposes no bank write port and a separate trusted host/ledger boundary for consent and verified actions. This is substantive implementation, not only a diagram. Evidence: `docs/submission/DISPUTE_ENGINE.md`, `dispute_workflow/policy.py`, `dispute_workflow/runtime.py`, `dispute_workflow/action_host.py`, `banking_mcp/actions.py`.

## What the source and evidence establish

The engine is a real stateful workflow. `dispute_workflow/policy.py` implements ordered rules without bank I/O; the runtime handles typed interpretation, selected evidence, query isolation, retry bounds, grounded-response validation and fallback. `BankingActionHost` and `banking_mcp/actions.py` bind trusted owner/session/conversation/snapshot context to explicit control actions, retain pending requests, recheck ownership and return independently read persisted receipts. Card preparation does not change status, consent must be literal true, foreign capability use is rejected, and the committed block is reread. Local tests cover restart/replay, uncertainty, cancellation, expiration, revocation and concurrency. I found no action-authority defect in the checked core.

The two-reviewer enhancement makes two actual structured model requests with disjoint roles. It validates an enum choice and uses trusted facts plus reviewed text to produce useful saved advice. The source has no bank client in the inquiry service; informational closure and human acceptance are separate states. Its durable leases and fleet correlation reject unverified result packets, require original native snapshots, distinct author/reviewer/checker conversations and exact board bindings. This is credible expandable engineering. The presently recorded pair selects among six predefined suggestions; it does not perform an open-ended autonomous evidence search. The distinction should remain visible when describing “investigation.”

Voice has more substance than an animated avatar: integrated controls, queued completed updates, sample-count accounting, exact full-playback ACKs and server-owned registered result narration. The saved-speech WAV physically matches its published SHA-256 and 196,800 PCM16 mono frames at 24 kHz, or 8.2 seconds; the receipt ACK count matches. That verifies file/receipt consistency, not human-perceived audio quality. Original recordings disclose condensed narration and omitted canonical caveats; later narration source strengthens the contract without relabeling older recordings.

The data plane is particularly strong. Bronze preserves values and lineage; silver types and quarantines invalid records, structurally hashes kept content, deterministically deduplicates versions and distinguishes missing foreign keys from owner mismatches. Gold makes served ownership an explicit predicate and publishes isolated immutable builds only after contracts pass. One writer and atomic CURRENT replacement preserve the last good snapshot. The historical six-table manifest accounts for **5,899,720 raw rows**, and fixture tests exercise corrections, late arrivals, rejection/publication and isolation. The 44,570 foreign complaint-product joins and 42 transcript templates are meaningful analytical discoveries that changed the product. Their private-source counts are recorded evidence; I did not re-ingest restricted rows.

The ML work avoids misleading template memorization. Fixed train-only selection, preserved holdout provenance, baseline/model/abstention comparison and separate human-miss/escalation metrics are sensible. Independent reconstruction confirms **70/120**, **94/120** and **65/120** correct; human-required misses **13/30, 3/30, 1/30** and unnecessary human routes **6, 9, 52**. The model improvement is **20 percentage points**, with an independently reconstructed i.i.d. case-bootstrap interval **10–30 points**. Related authored scenario families and unadjudicated labels make that a diagnostic interval, not a customer-population confidence statement.

Analytics uses read-only source connections, HMAC pseudonyms, metadata-only extraction and separately verified host snapshots. It rejects malformed/foreign/conflicting admission evidence and keeps workflow intent separate from current host intake/handoff outcomes. It explains that current slots are not lifetime attempts, that a saved handoff is not human pickup, and that parallel node durations are work time. Operating decisions connect grounding/leakage, safety burden, queue latency and input-token overhead to concrete choices. Exact query/action attribution, card-block integration and persistent model usage/cost remain absent.

## Actual offline checks and artifact consistency

The complete check receipts are under `.tmp/quality-review-4/`.

- **1,058 tests passed, zero failures/errors/skips**, across 14 selected suites. Elapsed guarded process: **101.951 seconds**. Suites cover policy/query policy, independent workflow acceptance, action host, prior receipts, response guards, durable state/handoff, card ledger/API, inquiry service/fleet, pipeline and host analytics. Pytest plugins/cache and bytecode were disabled; generated temp state and JUnit stayed inside assigned scratch. Python external DNS/socket instrumentation observed **zero external attempts**. See `offline_checks.py`, `check-receipt.json`, `pytest-output.txt` and `junit.xml`.
- The shipped offline Luna verifier reconstructed **100 unique completed/correct/bounded-safe records**, **100 matching independent deterministic baseline outputs**, **50 ES/50 PT** and **100 overlapping app-server turns**. Published prompt/workload hashes, output records, token totals and timing aggregate assertions pass. This used no new provider call. See `luna-audit/audit.json`.
- **39/39 copied generic FLUJO files**, **619,009 bytes**, match SHA-256 and Git blob/source evidence against HEAD. The documented dependency-free guarded retry smoke passed **5/5 checks** on Node v22.13.1. The historical **104** broader upstream tests were inspected as receipts, not rerun.
- **39/39 domain/core-test file hashes** in the original core-congruence inventory match this frozen checkout. **8/8 core-publication hashes** match. The public JUnit differs from its original private digest because hostname and two synthetic sensitive parameter values were deliberately curated; its derivative digest and explanation are present and valid. This does not transfer a historical test pass to the whole current deployment.
- Frozen training/holdout byte hashes and zero normalized exact overlap were verified. The actual keyword baseline was executed; all published model/abstention error records were checked against CSV cases, and accuracy/F1/confusion/human-miss/handoff counts reconstructed. **No scikit-learn refit** was attempted: it is absent from the available interpreter and installs were forbidden.
- Saved recommendation WAV SHA-256, PCM format/frame count/duration and receipt ACK sample count agree. I visually inspected the saved-useful-result customer screenshot and commercial comparison slide; I did not perform human audio adjudication or a new browser journey.
- Final `git diff --exit-code HEAD --` passes and `git status --short` is empty. The exact HEAD is unchanged. Only assigned scratch and the requested assessment outputs were written.

An initial bare Node smoke invocation omitted the documented TypeScript-strip flag and failed; the documented guarded command passed. An initial audit assumed original and curated public JUnit hashes were identical; reading the publication manifest resolved the distinction and all public hashes pass. These were review-invocation assumptions, not product defects.

## Comparison quality

- **commercial:** Clear product emphasis and dated vendor references, with explicit no-matched-benchmark caveat. It does not substantiate exclusivity, inferiority or quantitative voice advantage.
- **router:** Strong controlled component comparison with fixed parameters, same frozen workload, class/language denominators and safety/coverage tradeoff; label and authored-family uncertainty remain.
- **luna:** Strong artifact-grounding and overlap audit, but repeated fixture phrases and 100/100 baseline tie limit claims to bounded structured request performance.
- **customer:** Useful same-facts baseline and preservation of n=3 useful-answer failure plus a separate post-fix fallback; different source/provider/request boundaries are not pooled.
- **capacity:** Failure-preserving capacity story distinguishes 217/300 first wording, 300/300 neutral repeat, queued latency, actual filesystem observations and sandbox collaboration from a completed customer fleet.

The commercial comparison is a coherent explanation of Savia's emphasis. Its main “voice platform / bank-controlled case service” contrast does **not** prove that ElevenLabs cannot be used to implement cases, policy, tools, consent or follow-up. The supplied vendor article itself has a financial-services dispute showcase. There is no matched workload, deployment, end-to-end latency, quality or cost comparison. Approximately 100 ms vendor inference is not comparable to queue-inclusive FLUJO latency, app-server fixture latency or customer audio-start timing. The repository generally makes these limits explicit; the claim should carry them where the reader first sees it.

## Defects, blockers and useful improvements

- **evaluation qualification:** Independent human adjudication of the 120-case intent labels is still pending. The provenance file explicitly requires it before final submission. This blocks an independently adjudicated ground-truth claim, not execution of the simulated deterministic core. Evidence: `docs/ml/router_holdout_provenance.md`, `docs/demo/intent_router_evaluation.md`.

- **claims/documentation:** Architecture introduction says it commissions 100 specialists and delivers push/email, while nearby sections describe a target and evidence explicitly leaves these unqualified. The comparison's 'architecture is ready to scale' and categorical voice/case contrast should state demonstrated scope adjacent to the claim. Evidence: `docs/architecture/system-landscape.md`, `docs/submission/ELEVENLABS_COMPARISON.md`, `docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md`.

- **reviewability:** Historical source-only setup text remains prominent in frontend/DIRECT_MCP.md while current release records include in-process host/API acceptance. The release documentation preserves provenance well, but the reader must reconcile several different customer/voice/fleet/action sources. A concise current capability/source matrix would improve reproducibility. Evidence: `frontend/DIRECT_MCP.md`, `docs/submission/RELEASE_CANDIDATE.md`, `docs/submission/measurements/MEASURED_RESULTS.md`.

- **scope limit:** No checked core defect blocks a complete fictional-bank hackathon submission. Real-bank action certification, exact 100-agent customer completion, production operations, final-video placeholder replacement and larger-fleet qualification were not treated as missing requirements.

Most useful improvements, within their proper scope:

1. Have bilingual human adjudicators label a new untouched evaluation set, record disagreements and confidence, and compare routing plus grounded response quality against deterministic baselines without tuning on the known holdout.

2. Describe the current reviewer enhancement as two bounded suggestion selectors; show what additional evidence an expanded team obtains before claiming richer specialist investigation.

3. Put actual two-reviewer/current core behavior adjacent to the ten-team target and push/email ambition in every present-tense pitch or architecture claim.

4. Add one compact release map connecting each currently claimed capability to its exact source/image, fixture or recording, then retire or banner stale source-only setup text.

5. Persist per-turn model token/usage observations and explicit query/action attribution so analytics can report customer-case cohorts, cost per case and host outcomes without inference from latest session state.

6. For future scale qualification, use version-pinned source inputs and measure existing resource/latency/cost behavior under a defined customer workload; do not replace the valid hackathon evidence with general production claims.

I did not find a checked core defect that prevents a complete simulated-bank hackathon submission. Pending human labels block a stronger independently adjudicated ML-ground-truth claim. Real bank resolution, full 100-agent customer completion, human pickup and production certification remain future qualifications and do not erase the implemented core, real two-reviewer success, native audio or recorded infrastructure exercises.

## Limits and source preservation

- Repository-only frozen assessment; no other repository, chat, reviewer/rating report, web, provider or bank request, credential access, install, deployment or product edit.
- Read README first and ignored earlier review/rating links. No delegation.
- Tests are controlled fixture/source behavior and doubles, with in-process Python external DNS/connect instrumentation; the guard is not an OS network sandbox.
- No fresh browser interaction, physical microphone test, human semantic listening, production UI build, full Windows/Linux CI, installed native graph/compiler replay, or generic FLUJO 104-suite rerun.
- Original organizer/S3 rows and private infrastructure per-request histories are unavailable in the permitted repository scope; historical aggregate counts are credited as recorded evidence, not independently re-ingested.
- An initial bare Node smoke command failed because it omitted the documented TypeScript stripping flag; the documented guarded command then passed all five checks. An initial original-JUnit digest assertion failed because the public artifact is a documented curated derivative; all eight publication hashes match. Neither was an application defect.
- ML refitting was not performed because scikit-learn was unavailable; hashes, actual keyword predictions, reported model error records/confusion matrices and paired uncertainty were independently reconstructed.
- The five dimensions judge the complete submitted hackathon product plus evidence and expandable platform, not a fictional bank prototype as production certification.

**Source unchanged.** Saved assessment: `.tmp/quality-review-4.md` and `.tmp/quality-review-4.json`. All check artifacts stay in `.tmp/quality-review-4/`.
