# Independent repository-only final assessment 5

Reviewed pin: `b4d83b53f22414ca2aa4368b3bb2c4ec0b0d79dc`, branch observed as `codex/savia-submission-final-review`. Repository: `C:/Users/Moe/.codex/worktrees/savia-submission-portal/factored-hackathon-2026`. Initial and final tracked Git status were clean. Review date: October 5, 2026.

I began with AGENTS.md, the FLUJO product boundary, and README, then followed their source/evidence links. I did not read earlier assessment reports or ratings, inspect another repository/chat/reviewer, browse, install anything, or make a provider/bank request. Scratch changes are confined to `.tmp/final-review-5.*` and `.tmp/final-review-5/`. This evaluates a declared fictional prototype, with the complete deterministic R0–R18 engine as core and voice/swarm as extensions. The requested final-video placeholder is acceptable and is labeled alongside the existing film.

## Independent scores

### Savia: 90/100

| Fixed dimension | Score | Justification |
|---|---:|---|
| Technical judgment | 19/20 | The real ordered motor, authenticated owned reads, session/query/snapshot binding, explicit host consent, attempted-write marker, independent durable receipt readback, replay, revocation and handoff form a substantial coherent lifecycle. Bank authority stays outside model output and generic FLUJO. Missing risk evidence fails closed. Current policy thresholds are duplicated across the motor, host admission and bank actions, creating a future drift hazard. |
| AI engineering | 18/20 | Implemented ES/PT stage contracts, bounded repair and fallback, integrated voice, exact playback acknowledgment, durable inquiry and two actual completed model workers have source and dated recordings. The fleet connector correlates native original runs, execution snapshots, independent authors/reviewers and board events. Recorded reviewers select bounded suggestion enums rather than perform open-ended evidence research; broad language/usefulness evidence remains small. The future 100-conversation fleet is not required to validate the demonstrated two-reviewer prototype. |
| Data engineering | 19/20 | Contract-driven bronze/silver/gold, structural row hashes, deterministic deduplication, quarantine, reconciliation, ownership flags, customer sharding, writer exclusion and atomic publication are implemented and meaningfully tested. The large historical six-table manifest reconciles 5,899,720 rows. S3 ingestion observes inventories rather than VersionId-pinning every read, and snapshot durability under power loss is not measured. Those limits are disclosed. |
| ML / evaluation | 16/20 | The team correctly rejects template leakage and weak fraud labels, chooses an inspectable router using training-only CV, freezes separately AI-authored ES/PT text, compares keywords/raw/abstention and reports class/language/error/uncertainty metrics. Recalculated paired accuracy improvement is 20 percentage points with 95% interval 10–30. The labels still require independent human adjudication; the 100 Luna cases contain ten phrasings and tie the deterministic baseline. This establishes diagnostic component behavior, not deployed quality uplift. |
| Analytics | 18/20 | Metadata-only read-only extraction, HMAC identity projections, grain-specific outcomes/error/latency/feedback reports, exact denominators and reproducible paired analysis are useful. Ownership and transcript findings changed product choices; latency, token overhead and abstention burden lead to concrete operating decisions. Host actions are not fully joined into workflow analytics, model usage/cost is not durably persisted there, and n=3 customer usefulness is agent-screened rather than human-adjudicated. |

### Generic FLUJO foundation evidenced here: 88/100

| Fixed dimension | Score | Justification |
|---|---:|---|
| Architecture / extensibility | 24/25 | Exact pinned generic FlowSpec compiler, chat dispatcher, provider-neutral completion contract, MCP interfaces, typed execution runner, immutable flow snapshots and trusted execution adapter are inspectable. Non-banking digest examples show a credible independent application. Domain code remains outside generic main. The packet is a subset rather than a complete platform distribution. |
| Execution / integration | 22/25 | Saved/inline flows, explicit invocation source, ephemeral/conversation modes, continuation, named variables, events, cancellation and configurable approval form broad reusable contracts. MCP dispatch and model routing are real source. The dated 300-reference and sandbox collaboration receipts support separate workloads; this packet does not freshly run real transports/providers or the entire generic platform. |
| Safety / recovery | 17/20 | Opaque server-minted extension contexts, mutation authority, content snapshots, reentrant conversation locking and conservative effect checkpoints are strong foundations. Unknown tool effects require manual handling. Locks are process-local; retry safety trusts tool annotations; ordinary approval is opt-in and headless default is auto. These are described accurately, rather than promoted as bank authorization or distributed exactly-once guarantees. |
| Reproducible engineering | 17/20 | 39 immutable Git-object copies have byte/blob identities and verify locally; the retained 104-test/9-suite receipt and five real-module smoke checks are explicit. Clean locked installation, production build, complete suite, transitive integrity and cross-process crash/recovery are absent from this packet; eleven direct-package differences in the historical cache are disclosed. |
| Usability | 8/10 | The guide is readable, examples connect public authoring/chat/tool/run boundaries, and narrow offline verification works without a neighbor checkout. Examples require real catalogs and are unexecuted; generic UI usability is not evidenced by this source subset. |

Scores assess demonstrated prototype/foundation engineering, not production certification. Missing bank deployment certification, live human pickup, push/email and week-long operation are pilot scopes and do not make the fictional prototype incomplete.

## First five findings, in discovery order

1. README distinguishes simulated intake, helpful informational closure and a real bank resolution. Its R0–R18 core claim describes the implemented fictional decision/action lifecycle rather than a refund guarantee.
2. README separates the completed two-reviewer customer recording from a larger fleet whose acceptance is pending. Capacity submission counts, simultaneous sandboxes and customer agents have different denominators.
3. The data findings materially alter architecture: unreliable complaint-to-product ownership links are excluded in favor of fresh owned transactions; template-heavy transcripts are excluded from a generalization claim.
4. The first evaluation claims already expose their boundaries: proposed AI router labels await human review; the new provider fixture workload ties a deterministic baseline. Neither is evidence of production resolution quality or ROI.
5. The linked generic FLUJO packet identifies exact upstream source, tests and constraints. Its 39 files and 104 selected mocked tests establish inspectable generic interfaces, with no claim of a full fresh platform build or live MCP interoperability.

These early findings were subsequently checked against source and receipts; they are listed by discovery, not severity.

## Deep source observations and successes

- `dispute_workflow/policy.py:413` returns the first ordered decision without bank I/O. R0–R2 guard stale terminal success; R3 consumes scoped verified evidence and emits host-status reads; R17 requests portal confirmation, never a model-authorized write. Query-scoped state prevents pooling different targets or receipts.
- `banking_mcp/actions.py:541` persists an attempted marker before a potentially uncertain case write, rechecks current ownership/snapshot/risk under the bank writer lock, then independently reads the durable receipt. Repeated/overlapping confirms recover one original operation. `action_host.py:333` holds the frontend writer fence against durable revocation through bank write/readback.
- `banking_mcp/security.py:352` verifies exact EdDSA claim schema, bounded TTL, tool/scope, canonical argument digest, mapped customer and ledger generation, then consumes JTI durably. `authority()` checks authorization both before operation and before commit.
- `runtime.py:1088` refreshes the trusted clock after model latency, independently grounds query responses, bounds repair, and uses deterministic fallback. `response.py:623` validates facts, provenance, identifiers, credentials, claims and recommendation support. These textual guards are conservative bounded checks, not arbitrary semantic proof.
- `savia_assistant/service.py:311` runs two real role-specific model calls constrained to distinct enum contracts. It persists only accepted categories, displays trusted template text, records actual worker state, and avoids silently replaying crashed teams. `fleet.py:312` rejects packet-only claims and verifies original native transcripts/snapshots, distinct authors/reviewers, matching input/goal/run/template identities and independent conclusion review.
- `frontend/server/conversation.py:226` accepts only current exact complete sample counts into spoken history. `useSaviaVoice.ts:371` waits for device/source drain before acknowledgment and serializes it through an acknowledgment barrier. Dated native receipts support actual speech, distinct from offline mocked voice checks.
- Pipeline source demonstrates ownership checks beyond foreign-key existence, contract gates, structural deduplication and immutable build publication. New tests exercise last-good snapshot preservation, updates/late arrivals and customer lookup isolation.
- The portal exposes all four requested destinations, labels its illustration, preserves the existing film link/captions, and labels the final-video placeholder. The viewed grounded-answer screenshot shows selected charge facts and explicit simulated-case wording. A screenshot is dated visual evidence, not a fresh graphical acceptance run.

## Commands actually run and results

All commands below ran from the reviewed worktree. No dependency or product file was changed.

| Command | Actual result |
|---|---|
| `git rev-parse HEAD`; `git status --short` | Exact pin above; clean tracked status before/after. |
| `python .tmp/final-review-5/offline_checks.py` | **321 passed**, 0 failures/errors/skips, 88.00 pytest seconds. Existing suites: policy, query policy, independent runtime acceptance, action host, card block, pipeline and agent analytics. Python DNS/connect guard observed 0 external attempts; bytecode/cache disabled and fixture temp paths restricted to scratch. |
| `python .tmp/final-review-5/offline_checks.py --voice` | **47 passed**, 0 failures/errors/skips, 2.36 pytest seconds. Existing scripted-provider voice and inquiry-service suites; 0 guarded external attempts. Total new existing-test passes: **368**. |
| `node docs/submission/measurements/flujo-platform/verify-source.cjs` | Success; **39 files, 619,009 bytes** match the upstream manifest/blob identities. |
| `node --experimental-strip-types --require ./docs/submission/measurements/flujo-platform/offline-preload.cjs ./docs/submission/measurements/flujo-platform/offline-smoke.mjs` | **5/5 checks pass**, Node v22.13.1. Only experimental/module-type warnings; no receipt rewrite. |
| `python -B scripts/verify_luna_benchmark.py docs/submission/measurements/luna-100/run-100 --out .tmp/final-review-5/luna-verifier` | Offline replay succeeds: 100 unique complete outputs, exact/safe 100/100, baseline/oracle agreement 100/100, 50/50 language slices, 20/20 scenario slices, peak overlapping turns 100. |
| `python -B .tmp/final-review-5/verify_artifacts.py` | **285 Markdown local targets and 37 portal targets resolve**, no missing targets. Historical six-table row arithmetic reconciles. Router train/holdout exact hashes match. All 25 domain files match the frozen 1,078-check source manifest; five unrelated/unexecuted manifest files differ. |
| Read-only AST/hash comparison of the published core harness TESTS list | All **14 executed core-test files** also match that original manifest. Thus **39 domain plus core-test files** are congruent; this does not transfer whole-repository CI to the current HEAD. |
| Read-only `scripts.analyze_operating_evidence.analyze()` | Existing published outputs recompute: keyword 70/120, raw model 94/120, abstention 65/120; raw paired +.20, CI [.10,.30]; human misses 13/30, 3/30, 1/30; unnecessary routes 6/90, 9/90, 52/90. Luna p50/p95 37.400468/50.693110 seconds. |

The 1,078-check core and 104-test upstream results are **retained dated receipts**, not newly rerun totals. I verified relevant byte congruence and receipt contents. Default Python has no scikit-learn, so I did not retrain/re-execute the learned classifier or install dependencies. Recalculating predictions/intervals from frozen outputs is distinct from training/model execution. The network guards are in-process, not OS sandboxes.

## Defects, missing links and unsupported claims

No confirmed functional failure was found in the focused 368-check replay. No missing local target was found in the reviewed entry route. Remote URLs, film availability, provider identity and live deployment were not freshly queried under this repository-only scope.

The main source maintenance defect is policy duplication: the configurable motor reads window/status/risk thresholds from `config/policy_rules.yaml`, but `OwnedBankReads.assert_action_eligible` (`bank_read.py:930`) and `Actions` (`actions.py:440,498`) hardcode 120 days, approved status, 70 fraud score, USD 1,000 and 3 reports. They match version 1.1.0 today. A future config-only change can make explanation/consent and actual admission disagree. This is a latent drift hazard, not an observed unsafe current action. Keep both independent guards, but derive them from one pinned application-owned policy contract and qualify deliberate policy-version transitions.

Evidence gaps are explicit: independent human router adjudication is pending despite the provenance document requiring it before final submission; customer usefulness is agent-screened on three original cases; two bootstrap reviewers choose enums; model cost/usage is not persisted in operational analytics; no full current-head 11-job CI receipt is established by the bounded core packet. These lower the relevant evidence scores, rather than invalidate the deterministic fictional engine.

Claims that would be unsupported if promoted: 100 simultaneous GPU generations or 100 cooperating customer agents from Luna, production bilingual banking quality from ten request phrasings, real-bank action/resolution from simulated receipts, better voice/latency/cost/compliance than ElevenLabs, a successful 100-conversation customer fleet from the failed root attempt, or current whole-source/runtime acceptance from older receipts. The reviewed top-level README/portal generally avoid those claims. The architecture's present-tense opening about commissioning 100 specialists and push/email is easy to skim as shipped behavior; its owner-directed target label, dashed connections and later acceptance map qualify it. Make the first paragraph say “target architecture” as clearly as the portal does.

## Comparison quality

The ElevenLabs account is a fair product-positioning reference: it cites a dated vendor announcement and explicitly declines matched voice, latency, cost, breadth or compliance superiority. I did not independently verify the vendor announcement. Its approximately 100 ms model inference figure is not compared to Savia's end-to-end/app-server latencies as the same metric.

The learned-router comparison is technically useful: fixed training-derived parameters, exact freeze hashes, provenance/hygiene history, paired rather than unrelated accuracy uncertainty, language/class slices and safety/coverage tradeoff. Abstention adds 43 human routes while reducing raw-model human misses by two; the analytics correctly refuse to call that an unconditional operating win. Proposed AI labels and authored families limit external validity.

Luna's exact fixture oracle and independently derived deterministic baseline are unusually auditable, but the tie demonstrates a bounded provider path and repetition under load. It establishes no added decision intelligence. Tool-disabled structured completions cannot stand in for adversarial deployed authorization tests. Original n=3 and post-fix n=1 customer captures keep their revisions/fallback distinctions; they are diagnostic examples, not a causal improvement study.

## Exact blockers and useful improvements

There is no newly discovered blocker to handing over the declared fictional deterministic prototype with its requested video placeholder and working-film pointer. Completing independent human adjudication is required to meet the repository's own final-submission label requirement or promote the router labels to verified ground truth; otherwise keep its current provisional diagnostic wording prominently.

Highest-value improvements: unify/version the duplicated bank policy inputs; join host action receipts and durable token/latency observations into operational analytics; add a small independently human-adjudicated ES/PT customer evaluation with frozen prompts and usefulness/grounding criteria; publish a complete current-head CI receipt if claiming complete CI; qualify generic transport/build/crash behavior from a clean locked environment when expanding foundation acceptance.

The failed fleet provider workspace is an exact blocker only to that expanded integration's acceptance. Repair its configuration and qualify original native correlation, all required conversations and reviewed customer output before claiming the fleet works. Live human pickup, push/email, production bank execution and multi-day resilience remain optional/pilot acceptance objectives for this handover.

Scratch evidence: `.tmp/final-review-5/checks.json`, `junit.xml`, `voice/checks.json`, `voice/junit.xml`, `artifact-verification.json`, `operating-recalculation.json`, and `luna-verifier/`. Original audits and receipts remain unchanged.
