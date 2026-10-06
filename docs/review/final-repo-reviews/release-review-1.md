# Independent release review 1

**Final score: 88/100.** No blocking defect found for the declared fictional-bank hackathon handover. The voice retry defect and provenance wording below are actionable; neither invalidates the working core or fictional-card result.

Frozen HEAD `5c943f3060ba2784f8cd69458038ece2deb88a3d`; tree `6109d8d7067665860db363808b04eade4b91fdcc`. Both matched before and after review; tracked status stayed clean. The first PowerShell tree command needed quoting and was corrected.

Complete declared fictional-bank Savia/FLUJO hackathon submission, including core R0-R18, product/pitch/development, generic platform packet, pipeline, ML/evaluation, analytics and current card/voice/release qualifications; separate larger/real-bank/ROI scopes retained. Repository and local Git objects only.

This equal-weight rubric is a review instrument, not official organizer numeric weights. No prior ratings or other agents’ reports were read. The final score is preserved independently of any desired outcome.

## Scores

| Dimension | Score | Evidence-based judgment |
| --- | ---: | --- |
| Technical judgment | 18/20 | Complete ordered R0-R18 application policy, independently fenced ownership, explicit consent, signed exact-call admission, query/snapshot binding, receipt readback and durable replay/recovery. Generic FLUJO/domain separation is implemented and release provenance is unusually precise. Native voice recovery and stale 39-file congruence wording keep this below full marks. |
| AI engineering | 17/20 | Working integrated ES/PT application, constrained two-reviewer informational work, persisted inquiry/event/suggestion lifecycle, model output repair/fallback, exact registered-result captions, device-clock playback gate, and independently checked fleet-result contracts. Actual customer, voice and generic capacity receipts retain separate pins. Failed-ACK barrier poisons later native turns within the same context; customer examples remain small and cross-revision, and canonical audio has no independent waveform/text semantic adjudication. |
| Data engineering | 19/20 | Substantial six-family bronze/silver/gold data system with 5,899,720-row accounting, deterministic correction/deduplication, lineage, quarantine, privacy, owned customer serving, immutable builds, locked writers and reports-before-CURRENT publication. 51 pipeline tests passed here, including failed reports/pointer swaps and old snapshot continuity. S3 VersionId pinning and crash durability are correctly disclosed boundaries rather than established guarantees. |
| ML/evaluation | 16/20 | Good judgment rejects template leakage and random/co-generated fraud labels; train-only selection, fixed hash-checked ES/PT diagnostic, keyword/raw/abstaining comparison, class/language errors, uncertainty, independent mechanical Luna oracle and baseline are concrete. Proposed AI labels remain unadjudicated by humans; 8/120 automated audit coverage, ten Luna phrases, baseline tie and 3/30 raw-model human misses limit generalization. Fresh learned-router fitting was unavailable here because installed scikit-learn is missing; published decision arithmetic was independently replayed. |
| Data analytics | 18/20 | Useful read-only metadata analytics, pseudonyms, host receipt observations separated from workflow intent, honest current-slot denominators, disagreements/recovery/coverage, paired uncertainty and operational decisions grounded in data quality and latency. Independent operating assertions reproduced exact metrics. Missing durable tokens/cost, turn/query attribution and card lifetime aggregation limit the operating picture; measured ROI is explicitly a separate future pilot scope. |

## First five findings, in actual entry-point discovery order

These reflect the initial AGENTS/product-boundary → README reading order. Later source and receipt checks supplied the corroboration; they are not reordered to place defects first.

1. **strength and qualification:** AGENTS and product boundary explicitly keep generic FLUJO main clean while allowing application/Banking MCP and an isolated hackathon branch; preserved source is not deployment acceptance. Sources: `AGENTS.md`, `docs/FLUJO_PRODUCT_BOUNDARY.md`.

2. **implemented strength with scope qualification:** README leads with a grounded customer example, two actual completed model reviewers, helpful informational closure and retained context; later team scaling is identified separately. Subsequent source/receipt inspection supports the bounded example. Sources: `README.md`, `docs/submission/measurements/team-story-summary.json`, `savia_assistant/service.py`.

3. **implemented strength with provenance qualification:** README identifies a complete deterministic R0-R18 foundation and ties its 1,725-test historical qualification to its original pins rather than making it a current whole-head claim. Policy/runtime source and 180 selected policy/acceptance checks support substantive implementation. Sources: `README.md`, `docs/submission/DISPUTE_ENGINE.md`, `dispute_workflow/policy.py`, `dispute_workflow/runtime.py`.

4. **implemented strength and fictional scope:** The card journey requires explicit confirmation, an owned selection and independent durable receipt reread; asking alone does not write. README labels the ledger fictional. Real source and the concurrent/API checks support that boundary. Sources: `README.md`, `banking_mcp/actions.py`, `dispute_workflow/action_host.py`, `tests/test_card_block.py`, `tests/test_card_block_api.py`.

5. **capacity strength with distinct-workload qualification:** README credits 18 sandbox collaboration and 300/300 FLUJO requests but calls the customer architecture up to 100 team conversations. The capacity report preserves first-run failures, queue-inclusive latency and separate customer acceptance. Sources: `README.md`, `docs/submission/measurements/INFRASTRUCTURE_CAPACITY.md`, `docs/submission/measurements/infrastructure-capacity.json`.

## What works and why the submission is substantial

The core is implemented software, not a route diagram. `dispute_workflow/policy.py` has ordered authentication/attack/foreign-reference guards, query-bound clarification, status/date eligibility, duplicate/open-case checks, complete high-risk evidence, consent and existing-receipt handling. `runtime.py` rereads owned facts, updates the trusted clock after model delays, limits response repair, validates generated financial assertions and uses deterministic fallbacks. `action_host.py`, Banking MCP security/actions and SQLite state keep customer/admission/query/snapshot identities outside model authority. The current card path commits once and rereads independently. The selected real-local API test covers consent, a new login, snapshot continuity and foreign-owner refusal; its action fixture is generated, while model suggestions/voice providers are mocked where appropriate.

The application adds useful persistence beyond a single answer: saved inquiries, event cursors, two constrained reviewer roles, customer-marked informational closure, restart/lease/idempotency logic, and independently checked recovered-fleet findings. The film and saved-advice receipts qualify a bounded two-reviewer customer example at their own source/images. Current canonical native receipts qualify 2/2 exact ES/PT captions and product playback ACKs; they narrate guidance while separately rereading already blocked fictional cards. The final runtime package preserves accepted transport bytes rather than pretending that old provider calls were rerun.

The data system accounts for all 5,899,720 historical rows in six families, then enforces contracts, deterministic version choice, lineage, quarantine and owner-valid serving partitions. New immutable snapshots and required reports finish before CURRENT changes. This is meaningful engineering: tests here cover late corrections, exclusion of wrong ownership, failed builds/report writes, pointer failures and old pinned readers. The 44,570 bad complaint-product ownership links and 42 distinct transcript texts changed the grounding and modelling choices. The public sample implements these mechanisms; private aggregate totals were inspected/reconciled rather than reacquired.

ML/evaluation is a measured component, not a claimed real-customer quality rate. The fixed bilingual diagnostic and its keyword/raw/abstaining comparison expose errors and human-route burden. Luna’s 100 completed provider outputs, mechanical oracle and deterministic tie are independently reconstructable, but only ten request phrases recur with different facts. Analytics translates those facts into practical decisions, preserves failed Portuguese and fleet observations, separates wall latency from summed node work, and refuses to turn current host intake snapshots into bank-resolution or ROI metrics.

The generic FLUJO packet contains 39 licensed exact upstream source files and 104 historical scoped offline tests. I inspected compile/validation/save, chat direct/flow dispatch, MCP/model contracts, locking and recovery code, and replayed the dependency-free retry checks. It is a credible generic foundation subset, explicitly not a complete independently buildable platform certification.300/300 reference-code and18-sandbox collaboration evidence are separate capacity workloads, with original217/300 first-run failures, provisioning failures and queue-inclusive273.40/441.60s p50/p95 disclosed.

The pitch, development story and ElevenLabs comparison have coherent customer value and source boundaries. “Bank-controlled case service” is supported as application architecture and fictional demonstration. Vendor voice latency and90+ languages are attributed vendor claims; there is no matched competitor benchmark, all-local deployed Savia proof or measured repeat-contact reduction. The larger ten-by-ten lifecycle and real delivery integrations remain targets, not blockers silently substituted for the demonstrated foundation.

## Defects, gaps and qualifications

### P2 — Failed playback ACK poisons subsequent native turns in unchanged voice context

HTTP non-OK/rejected /api/voice/played rejects the stored ackBarrier. Catch displays unavailable or falls back but retains rejection. A later converse awaits it before POST /api/voice/turn, thus immediately falls back. Context reset/new chat or microphone restart recovers. Existing native-voice UI test fixture always returns successful ACKs.

**Action:** Recover the serialization barrier after handling the failed ACK while keeping unacknowledged output out of spoken history; add same-context retry after409/network error coverage.

**References:** `frontend/src/avatar/useSaviaVoice.ts:306`, `frontend/src/avatar/useSaviaVoice.ts:407`, `frontend/src/avatar/useSaviaVoice.ts:418`, `frontend/src/avatar/useSaviaVoice.ts:718`.

### P3 — Current entry-point39-file congruence wording is stale

Current comparison gives38/39 matches to the historical core map. Repository publication-format compatibility changed afterward. All89 protected and 183 packaged current hashes match their newer final-runtime receipt, so this is not unexplained running-source drift.

**Action:** Date/restrict39-file statement to the original f3c57b26/ce8f6c80 phases or publish a38/39 plus explicit tested publication delta mapping.

**References:** `README.md`, `web/submission/pitch/savia-final-pitch.html`, `docs/submission/measurements/core-engine-final/source-congruence.json`, `banking_mcp/repository.py:97`.

### declared evaluation gap — AI-labelled router ground truth remains provisional

Only8/120 labels have an automated fresh-agent audit; no independent human adjudication. Raw classifier misses3/30 human-required labels; abstention misses1/30 while adding43 extra human routes.

**Action:** Obtain independently recorded ES/PT adjudication and a new untouched set before tuning or claiming production routing improvement.

**References:** `docs/ml/router_holdout_provenance.md`, `docs/submission/measurements/router-policy-audit/README.md`, `docs/demo/intent_router_evaluation.md`.

### separate target qualification — Full100-agent customer investigation and delivery integrations remain incomplete

Later integrated root failed first provider call with404 disabled workspace,0 delegated leads/accepted fleet findings. Ten ready Machines do not qualify100 native conversations. Real human pickup, push/email and multi-day reliability lack accepted receipts. Two-reviewer prototype and infrastructure successes remain valid separate scopes.

**Action:** Restore/bind the declared provider and perform a budgeted exact lifecycle qualification when claiming the larger target.

**References:** `docs/architecture/system-landscape.md`, `docs/submission/measurements/fleet-customer-attempt/receipt.json`, `docs/submission/measurements/MEASURED_RESULTS.md`.

### declared presentation/analytics gap — Transport ACK and current-slot analytics have limited semantic/outcome scope

Native audit speaks guidance for previously blocked cards, not newly confirmed-block narration. No independent waveform/text comprehension adjudication; raw even-length premature PCM cannot prove complete speech. Host observations are current slots, not lifetime actions; card ledger, exact turn/query linkage and persisted token/cost metrics are absent.

**Action:** Add human ES/PT audio checks and new-block narration acceptance; persist explicit outcome/turn linkage and usage metadata for an operating pilot.

**References:** `docs/submission/measurements/native-canonical-live/README.md`, `docs/submission/measurements/verified-outcomes/README.md`, `analytics/README.md`.

## Exact checks and observations

- **Frozen identity before and after — passed after command correction.** HEAD and tree equal expected values; git status --short empty before/after. First unquoted PowerShell HEAD^{tree} command was misparsed; quoted HEAD^{tree} corrected it. No Git/source mutations.

- **Installed environment — observed.** Python 3.13.1; pytest 9.1.1; duckdb 1.5.5; NumPy 2.2.5; PyYAML 6.0.2; anyio 4.14.0; PyJWT 2.15.1; fastapi 0.141.1; httpx 0.28.1; starlette 1.3.1; uvicorn 0.54.0; mcp 1.30.0; Node 22.13.1. The first metadata probe stopped at missing scikit-learn; a second complete inventory confirmed it missing. frontend/node_modules and root node_modules absent. No install performed.

- **Selected offline application/data/fleet tests — passed.** 339 passed in 156.63 s (156.85 s guarded harness), zero failures/errors/skips; policy83, acceptance97, action-host8, card19, card-API1, pipeline51, host-analytics34, inquiry-service4, fleet42. PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, bytecode/cache disabled; relative .tmp/release-review-1-pytest basetemp. No guarded external DNS/socket attempts. Guard is instrumentation in this Python process, not OS isolation. Receipt: `.tmp/release-review-1-check-result.json`.

- **Voice API qualification replay — passed.** 107 passed in 3.88 s; zero failures/errors/skips; provider mocks; zero guarded external attempts. Does not execute React or prove waveform semantics. Receipt: `.tmp/release-review-1-voice-check-result.json`.

- **Current packaged source/qualification congruence — passed current pins; qualified historical delta.** 89/89 final protected hashes and 183/183 final-runtime packaged source hashes match current HEAD Git blobs. Original 39-file core congruence is 38/39 now; only banking_mcp/repository.py differs, with publication_status readiness / legacy published compatibility. Historical 1,078 result is not promoted to this whole HEAD. Receipt: `.tmp/release-review-1-congruence.json`.

- **Generic FLUJO source and dependency-free smoke — passed.** 39/39 copied sources, 619,009 bytes verified including current Git blobs; 5/5 retry parsing/bounded timing/cancellation checks passed on Node22.13.1. Original 104 tests across nine upstream suites inspected, not rerun; subset intentionally incomplete and its historical dependency cache has eleven direct version differences/missing packages.

- **Frozen Luna offline verifier — passed.** 100 unique completions, 100/100 exact-correct, 100/100 bounded-safe, independent baseline100/100, peak turn overlap100, 50ES/50PT and all five20-case scenario slices. p50 37.400s and p95 50.693s; ten request phrasings, not100 distinct utterances. No new provider calls. Receipt: `.tmp/release-review-1-luna/audit.json`.

- **Learned router fresh evaluation — blocked by missing installed dependency.** python -m demo.evaluate_router --report-dir .tmp/release-review-1-router stopped at import sklearn with ModuleNotFoundError. No retry/install, no model/report write.

- **Operating decision arithmetic and frozen diagnostic reconstruction — passed.** analyze_operating_evidence.analyze() assertions passed: router70/120 vs94/120 vs65/120; human misses13/30,3/30,1/30; unnecessary handoffs6/90,9/90,52/90; paired raw improvement0.2 with95% interval[0.1,0.3]. Luna tokens/latencies/10phrases and pipeline44570 cross-owner links/42texts/2946 leaked test texts agree. This reconstructs published outputs, not a new classifier fit/blind quality test or raw private dataset replay. Receipt: `.tmp/release-review-1-operating.json`.

- **Release artifacts and actual audio consistency — passed.** Final-product15/15 and native-canonical-live15/15 artifact hashes and byte sizes agree. ES309600 samples/12.90s and PT397200/16.55s at mono24kHzPCM16 match published PCM hashes, caption equality and exact ACK counts. No waveform semantic listening/alignment or live call repeated. Receipt: `.tmp/release-review-1-artifacts.json`.

- **Failed-ACK barrier mechanism — source defect confirmed by isolated mechanism probe.** Source assigns ackBarrier.then(publish), awaits it before subsequent native posts, and never recovers rejection in catch. Minimal Promise reproduction prevents next native post after failed ACK; resetting context restores it. This is a source-pattern probe, not a React/browser reproduction. Receipt: `.tmp/release-review-1-ack-probe.json`.

## Limits of this review

- Repository-only review: no other repository, chat, web, provider, deployment, credential, private source record or installation accessed; no agents spawned.

- Fictional-bank hackathon application and generic FLUJO evidence are assessed together. Standalone full generic-platform certification, real-bank authorization/certification,100-agent customer completion and measured ROI are separate scopes.

- Release/live/capacity outcomes are evaluated as committed dated receipts with artifact/source congruence; this review made no fresh public HTTP/browser/provider observation.

- Installed dependencies differ from historical pinned replay versions; scikit-learn and frontend Node dependencies missing. No fresh learned-router fit, frontend React suite/build, full generic upstream distribution, full eleven-job Windows/Linux CI or endurance test executed.

- Connection guards are instrumentation, not OS sandboxes. Selected tests use synthetic data and model/transport doubles; they do not qualify real-bank effects.

- ElevenLabs comparison was read repo-only. Its vendor assertions were not independently fetched or benchmarked; the comparison is product positioning with disclosed vendor timing and no matched competitive performance test.

- The historical private organizer raw 5.9M-row source and original private infrastructure histories were not recomputed; aggregate accounting and public synthetic regressions were checked. Historical and fresh counts are not pooled.

**Final assessment:** a strong, complete fictional-bank hackathon engine/application with unusually auditable data and qualification work;88/100. Production certification, fleet target completion and ROI need their own evidence.
