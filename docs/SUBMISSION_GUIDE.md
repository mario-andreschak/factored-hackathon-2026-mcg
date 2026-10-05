# Savia submission guide

Checked October 4, 2026 against the local organizer PDFs. This is a requirements
inventory; the [release candidate report](submission/RELEASE_CANDIDATE.md) identifies
actual delivered links, source, runtime, measurements and limitations.

## Required submission materials

The [kickoff](reference/Datathon_2026_Kickoff.pdf), page 18, requires:

| Material | Final inventory location |
| --- | --- |
| Public GitHub repository named `factored-hackathon-2026-[team name]` | Release report: repository URL and immutable source candidate |
| Link to the deployed tool | Release report: runtime URL, access instructions and deployment scope |
| Presentation of 4–6 slides about the tool | Release report: final deck/export links under `docs/submission/media/` |
| Short mandatory video showing the working solution and core architecture | Release report: final playable MP4 link under `docs/submission/media/` |

The kickoff timeline on page 6 shows submissions closing **October 5, 2026**.
That slide gives no closing hour or timezone. Page 18 gives no numeric video
duration. Submit the materials to `hackathon.admin@factored.ai` as instructed
there; this guide does not send a submission. Check organizer updates before
assuming an exact cutoff or additional video constraint.

Editable decks, speaker notes, a separate pitch deck and detailed measurement
receipts are team release deliverables. They supplement the organizer's listed
submission materials.

## Product pitch direction

The human's October 4 updated briefing calls for a bank-investor pitch following
**Why → What → How**: lead with the customer's problem and bank value, introduce
Savia's experience, then explain the engineering that earns trust. The video
brief is **90% product/creativity, 10% technical**; the slides brief is **60%
product/creativity, 40% technical**. These are the updated presentation priorities,
separate from the submission-material requirements in the original PDFs.

Use product animation, transitions and mockups alongside actual working footage.
Connect architecture, data and model choices to a customer or bank benefit.
Keep measured results scoped and savings described as intended or projected
unless they were actually measured. The customer's story should carry the pitch;
technical evidence supports the claims.

## What the working story must demonstrate

The [problem statement](reference/Factored%20AI%20%26%20Data%20Hackathon%202026%20%281%29.pdf),
pages 2–6, calls for one focused end-to-end workflow backed by supplied-data
analysis. For Savia, make the following evidence easy to find in the release report:

| Requirement | Savia evidence to identify |
| --- | --- |
| Normal, ambiguous/unsupported and human-required paths; Spanish and Portuguese | Recorded fictional customer journey, clarification and honest fallback/handoff |
| Context, permitted facts and verified actions | Exact owned transaction evidence, saved context, consent and receipt read-back |
| Controlled automation | Service-level ownership and policy; action confirmation; useful handoff context |
| Repeatable data preparation | Pipeline contracts, quality checks, lineage and snapshot/freshness limitations |
| Learned component against a baseline on the same held-out workload | Actual model/prompt versions, workload size/mix, label provenance and errors |
| Quality and failure handling | Success/unsafe counts and denominators, missed/unnecessary handoffs, failures, p50/p95 latency and cost basis |
| Route to operation | Reproducible setup, traces, bounded retries, fallback, capacity/access/retention limits and remaining deployment work |

The supplied-data audit motivates the workflow; historical complaint outcomes
are not a measured improvement caused by Savia. Diagnostic AI-authored labels
must not be described as human-reviewed. Keep simulated intake completion,
inquiry resolution, containment and actual dispute resolution distinct. Report
unknown cost explicitly and include failed or timed-out attempts.

## Public demo boundary

Public recordings use newly generated fictional customers. Identify simulated
banking tools and synthetic policy. Keep restricted organizer rows, raw customer
identifiers, credentials and private history out of the public repository, video,
decks and external model inputs. The challenge permits documented sandbox tools
and trusted test sessions; it does not require or authorize moving money.

Savia's release story should make the customer's next step concrete after the
initial answer: what is verified, what remains pending, and how to check status
without repeating the request. Demonstrate during-day follow-up only where the
actual runtime supports it. A local handoff receipt proves a saved packet, not
human pickup. An intake receipt proves intake, not a refund.
