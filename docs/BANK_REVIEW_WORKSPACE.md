# Bank and employee review alongside Savia

Savia helps a customer understand an owned charge and take the permitted next
step. A bank needs to know whether that assistance was safe and useful, whether
a human received the case, and whether a new version improves the journey.
FLUJO's execution history explains what ran; bank review adds human judgment
and bank service outcomes. Banking roles, case policy, labels and metrics belong
in this repository or the banking MCP under the
[FLUJO product boundary](FLUJO_PRODUCT_BOUNDARY.md).

## Who needs what

| Person | Decision | Useful surface |
| --- | --- | --- |
| Service employee | What needs attention and what can I safely tell the customer? | Assigned case, reason/urgency, verified facts, Savia response, consent/receipt status, missing evidence, bank acknowledgment and routing |
| ES/PT quality reviewer | Was the answer grounded, safe and understandable? | Permitted transcript, source/policy evidence, independent rubric, disagreement review, trace references |
| Bank service owner | Is service improving without hiding risk or shifting work to employees? | Safe inquiries, intake, correct/missed handoffs, pickup/aging, repeat contact, failures, language coverage, latency and cost |
| Risk/model/release owner | Should this version be enabled, limited or rolled back? | Pinned versions/deployment, paired comparison, reviewed failures, evidence-based release decision and owner |
| Data/operations owner | Why did the system fail or lose confidence? | Freshness/coverage, unavailable reads, uncertainty/quarantine, private FLUJO and tool diagnostics |

Employee support and quality evaluation are distinct. An employee can acknowledge
a case without rating the model; a reviewer can flag an answer without resolving
the dispute. Neither action grants model authority or replaces customer consent.

## Existing source and the gap

Source review on October 2, 2026 started from main `35f6a4e`, including merged
[PR #49](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/49).
These are source capabilities, not acceptance of a deployed customer path.

| Source | Reuse | Limit |
| --- | --- | --- |
| [Agent analytics](../analytics/README.md) | Metadata, workflow modes, rule/grounding/fallback/error signals, language, node durations and simple feedback | Host confirmation can occur after the workflow ends. Workflow handoff markers do not establish bank receipt or pickup. Cost is absent; summed node time can overlap. |
| [Customer outcome scorer](CUSTOMER_OUTCOME_REPORT.md) | Same-case baseline/proposed comparison; ES/PT denominators, failure-inclusive latency, unknown costs and consent/receipt claim validation | Validates supplied evidence shape/consistency, not authenticity of review, execution or provenance. |
| [Operator demo](BANKING_OPERATOR_DEMO.md) and generic FLUJO tickets | Evidence inspection and private conversation/flow links | Local tickets are not bank case management, employee acknowledgment or customer isolation. |
| Savia host and banking MCP | Owned selections, consent, preparation, receipt readback, recovery and owner-scoped case projection | No staff identity, assignment or acknowledgment API follows from customer interfaces. |
| FLUJO execution/model/tool history | Engineering investigation of actual retained inputs/results | Completeness depends on execution mode/build. Historical retained results cannot reconstruct missing calls. |

The chats **FRONTEND**, **2h - FLUJO team coordinator**, and **Find missing dispute
workflow logs** were consulted for ownership and constraints. Existing release
owners and their human pause remain separate; this slice does not resume their
schedules or qualify their pending release/evaluation gates. Trace collection
work stays with its current owner.

The frontend owner confirmed that there is no staff authentication path, existing
handoff displays keep `human_responded: false`, and `review_reference` is only an
opaque display reference. Customer UI work in PRs #42/#43/#45 stays separate;
this slice changes none of those routes, styles or receipt records.

## Offline first slice

`python -m bank_review` generates one self-contained HTML file:

1. **Quality review:** bounded metadata sample, language/signal filters, workflow
   references, five-dimension rubric and draft JSON export. Fictional mode includes
   eight invented ES/PT exchanges; private analytics mode copies no transcript
   or bank record facts. Missing evidence is not assessable.
2. **Bank oversight:** turn volume and mode/language distributions. Human pickup
   and provider cost remain unknown. Turn counts never imply safe resolution,
   customer satisfaction, refunds or employee acknowledgment.
3. **Paired evaluation:** optionally display the existing scorer's validated
   `customer-outcomes/v1` input. Preserve per-language denominators, distinct cases
   versus repeated attempts, safe inquiry separate from simulated intake, handoff
   errors, unsafe outcomes, end-to-end latency, costs and provenance limitations.

No model, S3 read, bank action, service or operational/analytics database write
is performed. Exported drafts are unauthenticated, unadjudicated judgments.
They cannot become `human_reviewed_locked` labels or a bank acknowledgment.

### Run

From the repository root with Python 3.13, no extra dependencies:

```powershell
python -m bank_review --demo --out private/bank-review-demo.html
```

Open the generated HTML locally. It uses no remote assets, browser storage or
network calls. Export drafts before closing/reloading; they only live in memory.
Each build needs a new filename because existing files are never overwritten.

For private metadata, first build the existing analytics database using its
documented procedure in the appropriate isolated state environment, then:

```powershell
python -m bank_review --analytics-db private/agent-analytics.sqlite3 --limit 500 --out private/bank-review-snapshot.html
```

The reader validates the current analytics schema and reads counts/turns in one
read-only snapshot. The default sample is at most 500 turns, maximum 5,000.
Full-snapshot mode/language counts and bounded review rows have separate scope
labels. Grounding, uncertain-action and handoff signals receive sampling
preference; this is not an incident queue or SLA ordering. Output includes private
turn/conversation correlation references and operational metadata. It remains
private even though customer/session pseudonyms, amounts, merchants, slot values
and source text are excluded. Organizer and invitation data stay separate.
This workflow has no public-hosting step.

Include an already adjudicated comparison with:

```powershell
python -m bank_review --analytics-db private/agent-analytics.sqlite3 --outcome-input private/locked-outcomes.json --out private/bank-review-comparison.html
```

The comparison is a separate locked workload, not joined to the operational
sample or presumed to describe the same deployment. The scorer rejects
incomplete paired panels and contradictory receipt/outcome fields. Its lock and
provenance remain supplied claims: independently verify case hash, reviewer
provenance, runtime/build pins and actual receipts before release decisions.
Unknown cost stays unknown; measured zero requires documented evidence.

### Review rubric

`bank-quality-v1` covers grounding, action safety, routing/handoff, ES/PT quality
and customer clarity. Each is `meets`, `needs_work`, or `not_assessable`. There is
no average score that can cancel a safety failure with good writing.

For a held-out evaluation, freeze the workload and rubric; separate authors and
paraphrase families from development; obtain two independent ES/PT judgments
before disagreement adjudication, hiding system identity when possible. Freeze
approved expected outcomes and label provenance separately from model outputs.
Draft exports need that external process and do not replace it. This supports
[issue #13](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/13),
which remains open.

## Connecting employee service later

Use a bank-owned service with a separate staff identity boundary. A Savia
customer cookie, customer selector, operator test allowlist or model-provided ID
must not grant employee access. Derive tenant, role and case assignment
server-side; authorize transcript/fact/evidence reads and exports. Service staff
need assigned case facts, reviewers need minimal redacted evidence, and managers
normally need aggregates. Do not expose private FLUJO administrative routes or
raw model/tool archives to customers or all staff.

Keep three records separate:

| Record | Authority and grain | Relationship |
| --- | --- | --- |
| Operational case | Bank host/MCP; one owned case | Owner, selection/query, snapshot, consent and independently verified receipt |
| Execution evidence | FLUJO and trusted host; one execution/turn/tool attempt | Analytics `turn_id` matches chat `operation`; preserve conversation and actual native run/attempt IDs separately |
| Review annotation | Authenticated reviewer service; reviewer/rubric/version judgment | Immutable evidence revision and case/turn reference; append corrections rather than replacing prior judgments |

Validate correlation contracts on the actual pinned runtime. Never join by
timestamp or infer receipt success from assistant prose. Analytics
`action_verified` and `handoff_created` remain workflow hints until host readback
corroborates them. Missing, stale, conflicting or historical-only evidence must
stay visible. Action capabilities and signed calls do not enter the reviewer UI.

A real queue needs requested, packet persisted, bank received, employee
acknowledged and bank concluded states. These are proposed bank-side states,
not current MCP capabilities. Each transition needs a durable receipt, authorized
actor, timestamp, idempotency key and explicit retry/reconciliation behavior.
Opening or scoring a page does not acknowledge a case. Sandbox intake stays
separate from bank execution and dispute resolution. This follows the handoff
gate in [issue #15](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/15).

## What banks should measure

| Question | Metric and denominator | Required evidence |
| --- | --- | --- |
| Was the customer helped safely? | Safe inquiry / all attempts; verified simulated intake / attempts, separately | Grounded reviewed answer or matching consent and receipt readback |
| Was a human involved appropriately? | Correct/missed handoff / human-required cases; unnecessary handoff / non-required cases | Adjudicated route and verified complete packet/transfer |
| Did service continue? | Acknowledged / delivered cases; pickup time and queue aging | Employee/case-system events and bank-chosen clocks |
| Did the customer return? | Same-case repeat contact / eligible cases with complete observation window | Scoped case linkage and fixed window, not repeated benchmark attempts |
| Was it safe? | Unauthorized disclosures/actions and unsafe outcomes / all attempts, plus absolute counts | Authority/receipt evidence, independent answer review and adversarial cases |
| Does it work in both languages? | Primary metrics by ES/PT, sample sizes and not-assessable fraction | Independent language review; no pooled score hiding PT failures |
| Is it reliable and affordable? | End-to-end p50/p95 including failures; errors/timeouts / attempts; cost / attempt and safe inquiry | Wall-clock/usage receipts; summed parallel node time is diagnostic only |
| Can claims be reproduced? | Evidence completeness, freshness and pinned-version coverage | Graph/model/prompt/policy/source/snapshot/runtime identities and private trace references |

Containment is descriptive: it can include good answers, abandonment, unverified
actions or missed handoffs. Do not optimize it as success. Customer satisfaction
needs actual customer feedback, distinct from reviewer rating. Choose thresholds
and service targets with the bank; this prototype invents no regulatory obligation
or SLA.

## Next connected slice acceptance

- Independent staff tenant/assignment authorization, revocation and foreign-case
  denial, including transcript/evidence exports.
- Normal ES/PT, ambiguity, required human, read failure and uncertain-confirmation
  cases preserving exact owner/turn/receipt lineage.
- Trusted readbacks reconcile post-workflow consent/intake/handoff; missing or
  conflicted evidence stays unknown with no automatic write replay.
- Employee acknowledgment is persisted and read back through the actual case
  system; a review annotation cannot trigger it.
- Independent reviewers and adjudication preserve disagreement and freeze
  same-case labels before baseline/proposed scoring, retaining all failures.
- Full evidence and notes remain private; public reports contain reviewed
  aggregates only. Retention/export controls and rollback are bank-owned decisions.

This PR delivers the offline projection, worksheet and design, leaving staff
authentication, live case management and independent human evaluation unqualified.
