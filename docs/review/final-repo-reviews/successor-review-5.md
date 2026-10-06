# Independent successor review 5

**Assessment: 90/100.** This is my repository-only assessment, not an organizer score. I found no demonstrated blocker for the declared simulated hackathon submission in the inspected implementation or my bounded offline checks. The complete ten-team customer investigation remains an unaccepted extension; its failed provider attempt is not a completed fleet result.

Reviewed frozen HEAD `02a657d81edc4d4ec080c488bd65983b167406a1`, tree `9c3e22cfc624aa6173123f36a69af312a97a9d7c`, in `C:/Users/Moe/.codex/worktrees/savia-review-evidence/factored-hackathon-2026`. HEAD/tree and clean tracked status were verified before and after the review. No tracked file, branch, deployment, provider, credential, or operational state was changed. All review outputs use `.tmp/successor-review-5*` paths.

## Scope and interpretation

I followed README into the submission guide, evidence map, development story, deterministic-engine guide, architecture, release map, technical receipts and executable source. I assessed the complete submission across technical judgment, AI engineering, data engineering, ML/evaluation and analytics. I inspected the pitch HTML and two local presentation/customer images, but did not play the film or listen to the WAVs. I verified the latest native audio artifacts structurally and cryptographically.

The declared product is an authenticated Spanish/Portuguese fictional dispute workflow, with customer-owned facts, deterministic policy, explicit consent, simulated intake/card protection, verified receipts, retained inquiries and bounded assistance. Real-bank execution, live human assignment, push/email delivery, sustained operation and the exact ten-by-ten investigation are not demonstrated. I did not treat those undisclosed production results as prerequisites for a hackathon prototype, and I did not credit them as implemented customer outcomes.

Only repository evidence was consulted. Prior rating records and peer scratch were excluded. No web, provider, other repository or chat was consulted for assessment. A requested parent progress message reported completed checks without discussing scores or importing another assessment.

## First five actual discoveries, in discovery order

1. **The generic/domain boundary is explicit.** AGENTS.md and `docs/FLUJO_PRODUCT_BOUNDARY.md`, read first, require FLUJO main/default builds to remain general purpose; Savia banking authority belongs here, in Banking MCP or on the explicitly isolated hackathon branch. Historical domain integration is not current deployment acceptance.
2. **The customer success is narrowly described.** README's opening product story claims a grounded answer, two actual completed model reviewers, helpful acknowledgment, saved advice and recovery after a new chat/reload. It does not identify the filmed path as a 100-agent investigation.
3. **The deterministic engine is the foundation.** README describes the complete ordered R0–R18 workflow, ownership, clarification, explicit consent, receipt verification, restart recovery, idempotency and revocation; language/voice and teams extend it. The later code inspection and 1,078-check replay substantiate this design.
4. **Voice and card authority have different evidence.** README separately describes native playback acknowledgments and a consented owned-card block in a fictional ledger. The declaration that asking never writes is borne out by the actual host/action code and replayed card tests.
5. **Capacity has separate denominators.** README places the two-reviewer example alongside 18 live foundation sandboxes, a 300-reference FLUJO workload and a larger ten-team architecture. The deeper capacity receipts retain queueing, provisioning failures, the first 217/300 result and the failed later customer-root request.

## Scores

| Dimension | Score / 20 |
| --- | ---: |
| Technical judgment | 19 |
| AI engineering | 18 |
| Data engineering | 19 |
| ML/evaluation | 16 |
| Data analytics | 18 |
| Total | 90 / 100 |

### Technical judgment — 19/20

The strongest contribution is the authority boundary. `dispute_workflow/policy.py` returns pure ordered transitions, and even valid R3 requests host readback rather than model-owned writes. It rejects absent authentication, foreign references, stale consent, incomplete search/risk evidence and uncertain outcomes. Query capsules, snapshot binding and exact receipt correlation prevent one query's consent/results from completing another. `runtime.py`, `state.py`, `action_host.py` and `banking_mcp/actions.py` preserve uncertain writes and original request identity across recovery. The banking writer rechecks eligibility and authority inside its transaction; distinct requests cannot bypass the verified 24-hour threshold.

`banking_mcp/security.py` verifies an exact EdDSA header/claim profile, canonical argument digest, tool scope, fresh replay identity, principal mapping, revocation and ledger generation. The separate direct-host transport signs only final normalized calls and keeps bank keys/capabilities outside language requests. The RC truthfully identifies its in-process Banking MCP Service boundary. The generic FLUJO packet exposes ordinary chat/flow/MCP interfaces and a default-undefined extension adapter; the packet's local 39-file byte/blob verification and five real retry-module smoke checks passed.

My current-source core replay passed all 1,078 checks. The additional suite reproduced the 100-concurrent-confirmation test yielding one fictional block/receipt and recovery through a new Service, plus consent, foreign-owner, receipt-tampering and joined API protections. Technical maturity is unusually strong for a hackathon. A perfect score would require stronger joined/deployment and operating assurance across the configurable direct/native/fleet paths, not merely larger counts of source tests.

### AI engineering — 18/20

The implementation contains structured interpretation stages, independent grounding checks, one bounded repair and deterministic fallback. `savia_assistant/service.py` runs two separate actual model tasks with distinct role enums; it renders trusted selected facts and reviewed copy rather than displaying arbitrary model suggestions. Owner-bound request identity, durable leases/events, interrupted-worker handling and quiet follow-up support a coherent returning-customer experience. This is meaningful bounded orchestration, although the demonstrated specialists select advice enums rather than conducting a broad autonomous investigation.

The fleet consumer binds immutable inputs and original runs, verifies board evidence, distinct finding authors/reviewers/conclusion checker and installed execution snapshots, and holds uncertain submissions instead of replaying them. Forty-two fleet tests plus API and inquiry tests passed in my additional suite. The exact full fleet has no accepted customer result: the recorded root request failed with HTTP404 before delegation. The older 300-reference workload and sandbox exercises are infrastructure evidence, not substitutes.

`frontend/server/conversation.py` gives native voice no bank access, gates delegation from the current utterance, registers host results, buffers native-result PCM until the transcript matches the canonical script, and admits spoken history only after a current exact sample acknowledgment. The browser waits for source completion and the audio-device clock, and the successor ACK barrier settles a failure without poisoning later turns. My 107 voice-server tests passed; current UI recovery has a separately pinned 148-test receipt and fresh-browser live captures. WAV/NDJSON/caption/sample equality passed for both latest ES/PT cases. I credit actual recorded provider behavior while withholding claims about physical hearing, waveform meaning, robust unconstrained dialogue, or full-fleet completion. The ElevenLabs comparison is product positioning with dated vendor claims, not a matched performance or superiority benchmark.

### Data engineering — 19/20

The six-table bronze/silver/gold pipeline is concrete and reproducible. It keeps lineage and input fingerprints, types/contracts, deterministic upserts/deduplication, quarantine accounting, ownership flags and serving exclusions. The historical manifest accounts for 5,899,720 rows and 4,390 source objects; raw private data was unavailable to recompute that run. The code publishes immutable serving builds only after required internal/external reports succeed, then atomically swaps CURRENT. A per-root writer lock and retained snapshots protect active readers; the serving repository verifies source inventory, ownership and event-date anchors instead of assuming a file or flag proves validity.

My public fixture replay passed all seven pipeline invariants: every row reconciles, repeated logical content matches across six tables, wrong-product ownership is excluded, an unknown customer returns no rows, a late correction changes Pending to Reversed, a late new transaction becomes visible, and the prior published snapshot remains unchanged. The current pipeline tests also cover report/pointer publication failures. The 100-test banking suite passed in my separate run.

The contribution makes the important distinction between foreign-key existence and customer ownership, and implements that distinction rather than hiding source defects. The remaining point reflects bounded S3 inventory/ETag freshness and lack of power-loss durability or a multi-filesystem transaction. Full refresh, operator-managed cleanup and stale-lock recovery are appropriate documented tradeoffs for this scope, not missing streaming features.

### ML/evaluation — 16/20

The team first diagnosed the supplied dataset: 42 distinct normalized transcript texts across 171,321 rows, complete train/test text overlap, and weak fraud/text labels unsuitable for a generalization claim. Choosing deterministic safety policy and a separately authored intent diagnostic is sound experimental judgment. The learned component is inspectable TF-IDF char/word features plus logistic regression, with training-only C/tau selection, frozen byte-hashed ES/PT holdout, explicit pre-report similarity hygiene, keyword baseline, language/class metrics, confusion/errors and abstention tradeoffs.

I reproduced the fixed C=8/tau=.65 diagnostic without model selection or editing evaluation reports. Raw learned routing scored 94/120 versus 70/120 for keywords, with a paired 20-point improvement and bootstrap interval 10–30 points. Human-required misses are 3/30 versus 13/30; abstention reduces this to 1/30 but produces 52/90 unnecessary human routes versus 9/90 for raw routing. Those observations justify a cautious component claim, not promotion on accuracy alone.

The separate Luna audit reproduced 100 complete exact-correct/bounded-safe outputs, 50 ES/50 PT, zero recorded tool attempts, mechanical fixture oracles and peak app-server overlap 100. Its ten distinct repeated phrases and equally perfect deterministic baseline do not establish natural-language generalization or LLM advantage. The 120 routing labels remain AI-proposed; the independent two-AI sample audit covers 8/120, not human truth. Human adjudication, untouched future evaluation, meaningful dialogue-level coverage and production prevalence remain substantial evaluation gaps. These limitations lower this dimension despite strong honesty and reproducibility; they do not block the declared synthetic demonstration.

### Data analytics — 18/20

The data audit changes product decisions: unreliable complaint-product ownership leads to owned-transaction grounding; missing merchants leads to date/amount/channel identification; transcript leakage changes the ML plan. The operational extractor opens source SQLite stores read-only, copies metadata rather than private customer text/amounts/identifiers, and uses HMAC pseudonyms. It distinguishes planned workflow outcomes from verified host snapshots, validates exact owner/session/expiry admissions, refuses contradictory copies, and reports unsupported/unknown coverage explicitly. Current host slots are not lifetime actions; handoff requests are not human pickup.

My public analytics replay passed all four invariants, including unchanged operational source hashes, privacy exclusions and the workflow-only containment denominator. Thirty-four host-outcome tests passed in the additional suite. I separately reran operating-evidence calculations: Luna p50/p95 37.400468/50.693110 seconds, 1,326,179 input and 5,217 output tokens, 868,608 cached input; the baseline tie, routing miss/handoff tradeoff and original customer n=3 (2 useful) remain separate. The operating decisions sensibly call for background progress, prompt-overhead inspection and human review rather than claiming ROI.

The missing points reflect unavailable persisted token/cost coverage, current-slot rather than lifetime action attribution, the exclusion of card-block history from host analytics, and a very small customer outcome sample. Repeat contacts, real resolution, human pickup and cost per case remain proposed pilot measurements.

## Checks actually reproduced

Counts below are separate workloads; I do not combine them into a larger qualification count. Test doubles and generated data retain their stated scope.

| Check | Result | Evidence output |
| --- | --- | --- |
| Frozen core harness on this HEAD | 1,078 passed; zero failures/errors/skips; 100.502 s; source unchanged; zero external Python attempts | `.tmp/successor-review-5-core/receipt.json`, `junit.xml`, `pytest-output.txt`, `network-guard.json` |
| Public evidence replay with assigned ML interpreter | 70 current checks passed; 7 pipeline and 4 analytics invariants; fixed router reproduced; 93.132 s; inspected sources unchanged | `.tmp/successor-review-5-replay/replay-receipt.json` and accompanying reports |
| Card, actual RC API, voice-server, inquiry/fleet/API and host-outcome tests | 211 passed; zero failures/errors/skips; pytest 25.69 s | `.tmp/successor-review-5-integration.xml`, `.tmp/successor-review-5-integration.log` |
| Banking MCP and connection configuration tests | 103 passed; zero failures/errors/skips; pytest 48.21 s | `.tmp/successor-review-5-bank.xml`, `.tmp/successor-review-5-bank.log` |
| Offline Luna verifier | 100 unique/complete exact-correct/safe records, baseline matches all, peak overlap 100 | `.tmp/successor-review-5-luna-audit/audit.json`, `baseline.json` |
| Generic FLUJO byte/blob verification and retry smoke | 39/39 files, 619,009 bytes match; 5/5 checks pass; Node v22.13.1 | Commands' output; original technical packet retained unchanged |
| Runtime, portal and qualification source congruence | All 183 c44 runtime source Git blobs and all 28 portal files match current HEAD; 38/39 historical core files match; 8/9 pipeline qualification files match | `.tmp/successor-review-5-artifact-check.json` |
| Current native artifact coherence | Both WAVs match NDJSON PCM, recorded hashes, exact host captions and completed/ACK sample counts; ES 399,600, PT 370,800 samples at 24 kHz | `.tmp/successor-review-5-artifact-check.json` |
| Read-only operating analysis | Recomputed workload counts, latency slices, tokens, paired routing intervals and source-data/customer denominators | `.tmp/successor-review-5-operating.json` |

Core command: `python -B docs/submission/measurements/core-engine-final/core-engine-run.py --repo . --expected-head 02a657d81edc4d4ec080c488bd65983b167406a1 --out .tmp/successor-review-5-core`.

Public command: `.tmp/successor-ml-env/Scripts/python.exe -B scripts/review_evidence.py --out .tmp/successor-review-5-replay`. TEMP/TMP and pytest basetemp were redirected under the assigned prefix, and bytecode/cache writes were disabled. The current selected replay has 70 tests; the historical 67-test receipt was not relabeled as my result.

Additional command: `python -B -m pytest -q --import-mode=importlib -p no:cacheprovider --basetemp=.tmp/successor-review-5-pytest-integration tests/test_card_block.py tests/test_card_block_api.py frontend/tests/test_voice.py savia_assistant/tests tests/test_host_outcome_analytics.py --junitxml=.tmp/successor-review-5-integration.xml`.

Bank command: `python -B -m pytest -q --import-mode=importlib -p no:cacheprovider --basetemp=.tmp/successor-review-5-pytest-bank tests/test_banking_mcp.py tests/test_connect_banking_mcp.py --junitxml=.tmp/successor-review-5-bank.xml`.

Luna command: `python -B scripts/verify_luna_benchmark.py docs/submission/measurements/luna-100/run-100 --out .tmp/successor-review-5-luna-audit`. Generic commands: `node docs/submission/measurements/flujo-platform/verify-source.cjs` and `node --experimental-strip-types --require ./docs/submission/measurements/flujo-platform/offline-preload.cjs ./docs/submission/measurements/flujo-platform/offline-smoke.mjs`.

The core/additional/banking runs used available Python 3.13.1 and pytest 9.1.1. Their dependency environment is recorded in the core receipt. The isolated review interpreter supplied the exact review ML pins. No dependency was installed. The missing frontend node_modules prevented an independent UI test/build replay; its committed source and pinned UI receipts were inspected instead.

## Confirmed issues, gaps and limits

No current product defect was demonstrated by my selected source/tests. Confirmed supplied-data defects are the published 44,570/44,570 cross-owner complaint-product links, 76.7% missing merchants and severe transcript-template leakage; the submission responds to them in source. The private organizer run was not repeated here, so those counts remain historical aggregate observations.

The fleet attempt is a confirmed failed extension workload: HTTP404 on the first background model call before any delegation, no accepted reviewed result. Current source implements and tests its recovery/verification contract; a production-scale completed customer investigation remains unproven. Original PT selected-fact and native delegation failures remain historical failures, with separately pinned corrections and results rather than erased denominators. Current voice normal playback was recorded in two attempts; the original batch remains failed even though the later PT continuation succeeds.

Current native artifacts prove returned PCM and matching captions/acknowledgments, not waveform/transcript semantic alignment or physical hearing. Bounded exact native narration and clean even-length PCM cannot prove that all intended speech was actually spoken. Canonical-script matching is a strong presentation guard with that explicit remaining limit.

Source congruence matters: current `banking_mcp/repository.py` differs from the original 39-file core receipt and has its separate publication-boundary qualification; the generated flow manifest differs from the nine-file pipeline receipt. My current core replay supplies a new current-source observation, but no whole-release acceptance is inferred from old counts. The apparent 32 runtime working-byte mismatches were solely Windows CRLF conversion: all normalized files and all 183 Git blobs match the runtime receipt. The unquoted initial PowerShell tree expression was corrected immediately; it was a verification command error, not source drift.

No live/public endpoint or commercial vendor capability was independently checked. Full FLUJO compilation/build, the packet's 104 upstream tests, complete Windows/Linux CI, live providers, physical audio, real-bank authority, human pickup, push/email and prolonged reliability were outside this repository-only replay. The comparison does not establish competitive voice speed, language quality, cost or production superiority. These are limits on what this review proves, not inferred blockers for the fictional submission.
