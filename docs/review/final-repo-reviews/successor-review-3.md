# Independent complete-submission assessment: successor-review-3

**89/100: Technical judgment 19/20; AI engineering 17/20; Data engineering 19/20; ML/evaluation 16/20; Data analytics 18/20.** These are my repository-only assessments, not organizer scores.

Reviewed frozen HEAD `02a657d81edc4d4ec080c488bd65983b167406a1`, tree `9c3e22cfc624aa6173123f36a69af312a97a9d7c`, in the assigned checkout. Tracked status was clean before inspection and after the checks. I read no prior or peer ratings, used no web/provider/neighbor repository, installed nothing, and changed no tracked file or branch. Scratch and replay outputs use `.tmp/successor-review-3*`.

## Scope and conclusion

I followed README through START_HERE, the evidence map, engine and policy contracts, development process, architecture, pipeline, provider and voice receipts, ML/evaluation, analytics, pitch and ElevenLabs comparison. I inspected implemented boundaries as well as their reported results. The declared submission is a deterministic dispute prototype over fictional customer/action data, enhanced by grounded conversation, two completed informational reviewers, retained inquiries and speech. Expanded fleet investigations, real-bank outcomes, live human pickup and notifications are identified as additional acceptance scopes.

There is **no demonstrated blocker for that bounded submission**. Its current deterministic core passes its published qualification at the reviewed HEAD, and its public data/ML/analytics replay passes. I did reproduce a specific native-voice usability defect: the plain imperative card-block commands used in the documented journey fail the voice delegation gate. This does not undermine the implemented consented API/card ledger or its recorded acceptance; it means the supported card action cannot be reached through those particular native-voice utterances.

## First five findings, in discovery order

1. The checkout actually matches the supplied HEAD and tree, with no tracked changes. This establishes which source is being assessed rather than transferring an older release result.
2. AGENTS.md and `docs/FLUJO_PRODUCT_BOUNDARY.md` explicitly keep generic FLUJO main free of domain code; the preserved hackathon branch and application-owned host are separate source/deployment scopes.
3. README declares a complete ordered R0–R18 engine with host ownership/consent/readback, while identifying the customers and card ledger as fictional and disclaiming real money movement or real banker assignment.
4. The submission route distinguishes the actual two-reviewer customer success from the expanded ten-team/100-conversation target; START_HERE retains an integrated attempt that failed at a disabled provider workspace before an accepted fleet result.
5. The data account describes ownership-invalid complaint-product links and extreme transcript template reuse, with resulting decisions to ground new inquiries in owned transactions and evaluate intent on a separate frozen bilingual diagnostic.

## Dimension assessments

### Technical judgment — 19/20

This is unusually careful application authority design for a hackathon. `dispute_workflow/policy.py` implements all nineteen rules as pure transitions; R0–R2 precede private reads and action presentation, R3 requires trusted consent and receipt scope, and missing/old evidence does not become an assumed safe value. `runtime.py` explicitly has no write port. `action_host.py` binds admitted identity, session, conversation, query and target, while `banking_mcp/actions.py` independently checks owned evidence, expiration, snapshot continuity and explicit consent. The intake path commits an attempted marker before a potentially uncertain write and recovers through reads; the card path uses a unique durable row and rereads the committed receipt. Receipt bytes alone are insufficient: card facts, original preparation, timestamps and schema are checked.

I replayed the current 14-suite core qualification: **1,078 passed, zero failures/errors/skips**, 196.124 seconds, unchanged inspected source and zero blocked external network attempts. This is source qualification using fictional stores and controlled observations, not fresh deployed bank acceptance. The boundary docs, development history, copied generic FLUJO contracts and release pins show good separation and migration judgment. The final point is reserved for operational qualification beyond the local/recorded prototype: restart tests are substantial, but power-loss durability, live-bank adapters and sustained joined reliability are not established.

### AI engineering — 17/20

The models have bounded roles rather than implicit bank authority. `savia_assistant/service.py` gives evidence and next-step workers disjoint enums, validates strict JSON, renders reviewed copy from permitted facts, persists cases/events and leases, and treats interrupted workers as failed rather than silently re-running them. The recorded `team-story-summary.json` establishes two actual completed provider calls and retained useful suggestions; their task is bounded suggestion selection, not an open-ended 100-agent investigation. `fleet.py` goes further in source: original-run bindings, native completed child identity, board records, distinct reviewers and execution snapshot/model/concurrency checks are required before publishing a result.

Voice source registers host output, buffers native result audio until its transcript matches the canonical script, checks formats/sample bounds, and acknowledges full playback after the audio-device clock. The ACK settlement fix preserves one turn's failure while allowing a later turn to proceed. I verified all **64 files** in the latest public voice bundle and exact WAV properties: mono PCM16 at 24 kHz, ES 399,600 frames/16.65 seconds and PT 370,800 frames/15.45 seconds. The live bundle truthfully retains a failed combined batch and a separate successful PT continuation.

The deduction reflects the reproduced native-voice command gap and the small joined customer sample. Historical 300/300 reference-code capacity and 18 simultaneous leaf sandboxes are useful infrastructure evidence, with source/workload pins and retained failures; they cannot establish the uncompleted full customer fleet. The ElevenLabs comparison is a reasonable product-positioning comparison with dated vendor-reported voice capabilities, not a matched latency or quality experiment. I did not independently verify those commercial claims.

### Data engineering — 19/20

The implementation goes beyond a notebook: bronze object inventory and provenance, silver contracts/quarantine/deterministic deduplication, ownership-valid customer-sharded gold, immutable builds and pinned serving lineage. `pipeline/__main__.py` finishes snapshot reports and required external reports before replacing CURRENT; failed contracts or writes preserve the previous serving pointer. `writer.py` uses one atomic writer lock and requires explicit recovery for stale locks. `lookup.py` uses a separate cursor per request, addressing a real shared-result-slot customer isolation hazard.

My current replay passed **70 existing checks plus seven pipeline and four analytics invariants**. Pipeline invariants reproduce six-table row reconciliation, unchanged logical content on repeat, wrong-owner exclusion, absent-customer isolation, a Pending-to-Reversed late correction, a newly visible transaction and preservation of the prior snapshot. I independently recomputed the committed full manifest's accounting sum as **5,899,720 rows** across six tables; that is artifact consistency, not a private-data rerun. Eight of nine publication-qualification file hashes still match. The changed graph file differs from that pin only in its recorded conversation-source hash; the pipeline/reader implementation hashes match. Crash durability and atomicity of external reports across filesystems remain explicitly limited, appropriately preventing a maximum score without making the prototype unusable.

### ML/evaluation — 16/20

The strongest judgment is refusing misleading learning claims from 171,321 transcripts with only 42 distinct normalized texts and total test/train template overlap, and from synthetic fraud labels. The alternative router is inspectable, trained on 307 authored utterances, compared against an ordered keyword baseline, and evaluated at frozen C=8/tau=.65 with exact CSV hashes, balanced ES/PT classes, overlap screening, error lists and language/class metrics. I reproduced the fixed procedure without model selection: keywords **70/120**, raw TF-IDF/logistic **94/120**, abstention **65/120**. Human-required misses are **13/30, 3/30, 1/30**, respectively; unnecessary human routes are **6, 9, 52**. The paired raw-model improvement is 20 points with a conditional bootstrap interval of 10–30 points.

I also reconstructed the separate Luna records: 100 unique requests, exact oracle/baseline match **100/100**, bounded safety **100/100**, 50 ES/50 PT and peak overlapping turns 100. This is useful provider grounding/load evidence, but it has ten request phrasings, repeats simple scenarios with varied facts, ties the deterministic baseline, and bypasses Savia/FLUJO/MCP/voice. The eight-case policy audit reproduces its fixed sampling and 8/8 agreement, covering only 8/120 labels. Labels remain AI-proposed with human adjudication pending; the known diagnostic cannot become an untouched generalization set, and neither benchmark proves customer prevalence, semantic safety or model-driven business improvement. These limitations materially cap this dimension, despite sound diagnostic practice.

### Data analytics — 18/20

The analytics is useful and privacy-aware. `analytics/extract.py`, `host.py` and `report.py` operate on read-only operational stores, pseudonymize identity and exclude raw customer text/facts. Host outcome snapshots use immutable admission binding, shape/time checks, source deduplication and conflicting-copy handling; they do not promote workflow intent to a verified action or infer human pickup. Rates expose denominators and distinguish latest action slots from lifetime attempts. My fixture replay confirms unchanged source databases, removal of fixture text/identifiers, two workflow-conversation denominators and separate transcript-only observations.

`docs/review/OPERATING_DECISIONS.md` turns analysis into concrete choices: exclude ownership-invalid complaint links, reject text leakage, retain deterministic authority when Luna ties it, treat 37.400/50.693-second load latency as background work, inspect input/cache overhead, and trade safety misses against 43 additional unnecessary handoffs under abstention. It retains the original 2/3 useful-answer observation separately from a later PT fallback fix. Metrics do not substitute HTTP success for usefulness or simulated intake for bank resolution. Remaining gaps are persisted model token/cost telemetry, exact host-to-workflow attribution, lifetime/card-ledger joining and a real longitudinal customer/ROI cohort. Those limit operating decisions rather than invalidate the demonstrated calculations.

## Checks reproduced and congruence

- Current source identity and clean tracked status verified before and after.
- Public fixed replay: `.tmp/successor-review-3-public/replay-receipt.json`; **70/70** existing checks, seven pipeline and four analytics invariants, all true, 132.159 seconds. No provider requests and no model-selection entry point.
- Core replay: `.tmp/successor-review-3-core/receipt.json`; **1,078/1,078**, source unchanged, external network guard clear. These counts are reported separately; no pooled test total is asserted.
- Luna verifier: `.tmp/successor-review-3-luna/audit.json`; reconstructed records, hashes, language/scenario slices, independent baseline and overlap peak. No new inference.
- Router sample audit: exact dataset/packet/raw-audit identities, prescribed sample and 8/8 agreement reproduced; no new semantic/human adjudication.
- Artifact congruence: `.tmp/successor-review-3-artifacts.json`; 64/64 voice bundle hashes/sizes match, both PCM counts match, full pipeline row accounting reconciles. Of the historical 184-file core manifest, 15 files differ; I did not relabel its historical whole-source result as current. The fresh current core replay provides its own acceptance.
- Native voice defect: `.tmp/successor-review-3-voice-gate.json` and `.tmp/successor-review-3-voice-probe.json`. Actual `Conversation.turn`/stream consumer with an HTTPX fictional transport: ES/PT imperatives send zero tools and emit no delegate; question-form controls send one tool and emit the unchanged request. Zero actual network/provider/bank calls.

## Defects, gaps and limits

**Confirmed current defect:** `frontend/server/conversation.py:106` recognizes bank nouns but its request-action grammar omits card-block verbs. At line 329 this disables the only bank-delegation tool for “bloquea mi tarjeta” and “bloqueie meu cartão”; the stream consumer cannot emit delegation when admission is false. Add the intended ES/PT card commands and conservative negative-command cases to that admission contract. I made no source change.

**Observed failures, retained at their actual scope:** the latest voice combined batch stops at an authentication wait after ES, with unresolved exact wait origin; PT continuation succeeds separately. The larger fleet attempt fails at a disabled provider workspace before delegation. Neither invalidates successful recorded workloads, and neither proves uninterrupted bilingual authentication or accepted full-fleet execution.

**Not demonstrated extensions:** full 100-conversation customer investigation, live-bank operations, real human pickup, push/email delivery, crash/power-loss durability and multi-day reliability. They are not silently treated as hackathon blockers.

This review neither accesses restricted organizer rows nor reruns live deployments/providers. Static assets and receipts are inspected local evidence, not proof that remote services still behave today. Audio frame/caption/ACK agreement does not prove waveform/text alignment or physical hearing. The copied generic FLUJO packet is a review subset, not a full platform build; its archived 104-test result uses a disclosed dependency cache mismatch. I inspected its contracts but did not reproduce those tests. Scores apply to the complete bounded submission evidenced here, with these practical limits.
