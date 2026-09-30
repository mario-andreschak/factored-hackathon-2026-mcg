# Banking hackathon product and PR review

Baseline reviewed September 29, 2026. This guide applies the project supervisor's
review mandate. It distinguishes organizer requirements, team decisions and
verified implementation; it does not turn unfinished work into a completed claim.

## FLUJO architecture boundary

FLUJO is a general-purpose product. Review changes against the
[product boundary](FLUJO_PRODUCT_BOUNDARY.md): banking or hackathon backend
code, routes, dependencies, policy and domain adapters belong in this application
and the banking MCP. Existing genuinely generic interfaces remain usable.
Separate FLUJO branches, renamed routes and injected banking adapters do not
create exceptions. FLUJO #534 restored the pre-#530 source tree; the previous
worker/image and its banking state require separate migration and review.

## SUPERVISOR action: Slack gateway and long-running work

The owner reports that the Slack gateway times out on long-running tasks. Own
and prioritize the gateway fix in its actual repository; this project PR is the
request and acceptance contract, not a gateway implementation or proof of a fix.
Keep the change generic to FLUJO and Slack, independent of banking.

**A conversation error requires FLUJO to report `status: 'error'` for that
same conversation.** Elapsed time in the gateway, an HTTP wait ending, a
transport break, or a Slack acknowledgement deadline does not establish that
state. Do not invent a fixed task-duration rule and present it as a FLUJO
conversation error. Keep the raw FLUJO diagnostic in protected operator records;
show the requester only a sanitized, user-safe reason and next step. Report
gateway delivery failure separately from FLUJO conversation state.

Persist accepted-work correlation across a gateway restart or transport break:
Slack workspace ID, channel ID, thread timestamp, and requesting principal,
plus FLUJO owner, session ID, and conversation ID. Before resuming observation
or delivering a reply, revalidate the saved Slack destination/requester and
FLUJO owner/session/conversation binding against current authority. If that
binding cannot be verified, hold delivery for protected reconciliation; do not
start another task or send a reply to an unverified thread.

Review the Slack event acknowledgement, job scheduler, FLUJO client, terminal
state observation, and reply delivery together. The fix is complete when a
long-running accepted task survives the former gateway cutoff and produces
exactly one final reply in its originating Slack thread; a matching FLUJO
`status: 'error'` produces a truthful, sanitized error reply; duration or
transport failure alone does not; and reconnect/restart does not launch a
duplicate task or post a duplicate final reply. Test mismatched or expired
correlation as a no-delivery case. Verify the deployed path with recorded
conversation state and Slack delivery evidence before reporting this resolved.
Security/session limits that FLUJO actually enforces must remain explicit and
separate from gateway guesses.

## Product focus

The customer has one problem: **“I do not recognize this charge.”** The product
helps an authenticated customer find and select an owned transaction, understand
verified facts, clarify ambiguity, and reach a useful human handoff. The planned
v0 target includes **simulated dispute intake with verified receipt read-back**;
its source prototype keeps actions disabled pending joined customer-path acceptance.
Source implementation and enabled deployment are separate evidence.
Creating an intake does not resolve a dispute. The operator receives verified facts,
steps already taken, unresolved questions and the reason a person is needed.

The team confirmed on September 29 that Gloria's prompts describe the accepted
**v0 direction** and remain work in progress. Evaluate them as a product
specification: map what already works, identify adapters/services still needed,
and correct contradictory or unsafe logic. A proposed tool missing from today's
MCP is an implementation gap, not by itself a reason to reject the design. The
target remains the complete inquiry/intake/handoff journey, beyond today's reads.

Before accepting a feature, identify the specific problem and customer, its useful
or distinctive contribution, the roadmap step it advances, the measurable outcome,
and the relevant hackathon rule. Customer product/transaction views can support
this journey. Credit eligibility, marketing, churn analysis, money movement, card
blocks and refund decisions are outside the selected product. An idea in the notes
or dataset use-case catalogue is not an approved scope change.

## Requirements and authority

Use the supplied PDFs directly when a rule is disputed. Page numbers below are
one-based PDF pages. New organizer guidance can supersede this baseline when its
source and effect are recorded.

| Organizer requirement | Source | Evidence required for delivery |
| --- | --- | --- |
| One coherent end-to-end banking service workflow | [Statement](reference/Factored%20AI%20%26%20Data%20Hackathon%202026%20%281%29.pdf), pp. 2–3; [kickoff](reference/Datathon_2026_Kickoff.pdf), pp. 10–11 | Normal outcome, ambiguous/unsupported request and human-required case work through the deployed journey. |
| Spanish and Portuguese; grounded facts and verified actions | Statement p. 3; kickoff pp. 10–13 | Both languages exercised, context/selection preserved, and claimed outcomes checked against permitted tool records. Portuguese fixtures are team-generated because the supplied corpus is Spanish. |
| Authentication, access control, confirmation and safe fallback outside model prose | Statement pp. 3, 5 | Cross-customer, expired-session, injection, retry and failed-tool cases enforce the boundary in service code. |
| Repeatable preparation, data contracts, quality, lineage and freshness policy | Statement pp. 3–4; kickoff pp. 12–13 | Source-to-serving provenance, checks and an explicit update/snapshot contract; customer/product master values labeled as snapshots where appropriate. |
| At least one learned component and appropriate baseline; held-out evaluation | Statement pp. 3–5; kickoff p. 12 | Same frozen workload, justified labels/split/thresholds, failure/adversarial cases and error analysis. New model training is optional. |
| Honest operational and outcome measurements | Statement pp. 4–6; kickoff p. 15 | Counts/denominators, attempted automation, safe outcomes, missed/unnecessary handoffs, unsafe events, end-to-end p50/p95 and cost per attempt/success, with language breakdown and limitations. Cost per success is undefined if there are no successes. |
| Credible route to operation | Statement p. 4; kickoff p. 15 | Traces/execution records, bounded retries, safe fallback and reproducible setup; explain capacity, monitoring, access control, retention and remaining deployment work. |
| Permitted data and sandbox actions only | Statement p. 5 | Input origin/type identified (real, de-identified, synthetic or team-generated). Credentials, private customer records and restricted data absent from public artifacts and external model requests; documented permitted-field boundary. Synthetic policies/actions clearly identified. |

The kickoff timeline (p. 6, including its slide image) closes submissions on
**October 5, 2026**; the supplied materials give no closing hour or timezone.
Kickoff p. 18 requires a public `factored-hackathon-2026-[team-name]` repository,
a deployed tool link, **4–6 slides** and a short mandatory demonstration video,
submitted to `hackathon.admin@factored.ai`. Preparing these artifacts does not
authorize the supervisor to send the submission email.

## Team completion target and contingency

The team aims to finish the hackathon contribution by **October 3, 2026,
23:59 UTC-5** (**October 4, 04:59 UTC**). "Finished" means a submission-ready,
hackathon-winning standard of quality, not merely feature-complete code:

- The complete Spanish and Portuguese customer journey is polished, coherent
  and usable, including ambiguous requests, failures and human handoff.
- Product behavior and claims are tested and verified against the deployed
  end-to-end path, with reproducible evidence for safety, data, model quality
  and performance. Fix material failures before calling the product ready.
- The demonstration video is finished and ready to submit; the deployed demo,
  slides and repository tell the same truthful, compelling story.
- The repository is tidy and reproducible, with no stale or misleading claims,
  stray artifacts or unresolved critical review findings. All submission
  documents are accurate, polished and easy to digest.

**The team's goal is to win this hackathon.** The SUPERVISOR should apply this
quality bar to the October 3 target and report any unmet gate explicitly.
Reserve October 4 and 5 (UTC-5 calendar days) as a last-resort buffer for
critical fixes, final verification and submission. Do not plan new scope for
those days. The organizer's October 5 closing hour and timezone remain
unconfirmed; submit before the actual organizer cutoff rather than assuming
all of October 5 is available.

The user authorizes the **SUPERVISOR** to spin up additional agents when
necessary, including testing and independent review agents, to find and close
missed setup or delivery gaps. The user reports unlimited usage for the next
24 hours from this September 30 request, so prioritize parallel work that can
help meet the October 3 target. Coordinate assignments and verify results
against the same product, safety and evidence gates in this guide. This
staffing authorization does not change merge or submission authority below.

**SUPERVISOR agent setting for new tasks:** Use **Sol 6.1** at **Very High** or
**Max** reasoning effort. Use **High** only for exceptional, narrow tasks that
do not need thorough work. **Never use Low or Medium effort**, including for
new testing or review agents.

The [delivery plan](HACKATHON_AUDIT_PLAN.md) supplies the selected roadmap. FLUJO,
MCP, signed assertions, query/page limits, the 120-case evaluation target and the
500-customer capacity target are **team choices**, not organizer mandates. Agents,
streaming, dashboards, forecasting and tool count are optional (statement p. 4).
Review architecture changes explicitly and measure their effect on this product.

## Implementation and evidence boundaries

- `banking_mcp/service.py` implements `banking_status`, `list_my_transactions` and
  `get_my_transaction`: read-only, customer-bound tools. Verify discovery/schema
  and responses on the reviewed revision before treating a proposed contract as
  usable. The historical read implementation used at most 31 process dates, with
  20 rows per page. The issue #21 source adds up to 90 event calendar dates,
  verified local case receipts and saved handoff packets; see
  [its source contracts](ISSUE21_DATA_AND_RECEIPTS.md). Source tests do not prove
  those changes are installed in the existing worker.
- The deployed backend uses customer-sharded gold snapshots. The data-recovery
  work is rebuilding from S3 separately. Source metadata agreement and conditional
  read-back do not by themselves prove inherited ingestion or full freshness.
- Historical complaints have no transaction ID. The full audit found every
  populated affected-product link belongs to another customer. Never infer a
  historical case/transaction link from that field. New sandbox cases can link to
  an owned transaction through a verified, explicit creation record.
- A local FLUJO handoff ticket is an operator receipt, not a bank dispute filing.
  New intake writes require trusted consent bound to customer, conversation,
  selected transaction and exact action, durable idempotency and receipt read-back.
- The trained router and its baseline are useful preliminary work. Its same-author
  60-case report is **provisional**, not an independent final holdout. The roadmap
  and ML docs must agree on which learned component is integrated and evaluated.
- Separate deterministic/mocked CI, backend-only or Static load, manual native
  model/MCP capacity measurements, and end-to-end customer outcome evaluation.
  Record source/deployed revisions and limits. A native submitted burst with an
  admission cap is not 500 simultaneously active model processes or a service SLA.
- Treat merchant/source text as untrusted data. Masking alone does not establish
  external-model permission: document allowed fields and applicable organizer
  restrictions. Keep raw source records, secrets and private mappings out of reviews.

## Review procedure

1. Read the live base/head, changed code, relevant contracts, roadmap and existing
   findings. Include unreviewed direct changes on `main` and linked FLUJO runtime
   dependencies. Preserve active shared worktrees, snapshots and services.
2. Assess product contribution and technical behavior together. Follow a concrete
   request from identity through data/tools, language response and verified outcome.
   Check ownership on every path, failure/abstention behavior, schema compatibility,
   bounded retries and truthful user-visible claims.
3. Reproduce material findings with focused tests or a concrete source trace. Check
   CI against the reviewed head and distinguish what each test actually proves.
   Do not repeat paid model or load runs merely to inspect unchanged evidence.
4. Report actionable findings with severity, file/line, trigger, consequence and
   required correction. Distinguish introduced merge blockers from unfinished
   submission gates; an unrelated safe PR need not finish the entire roadmap.
5. Recheck the head before publishing. Track review SHA, findings and follow-up
   links so unchanged findings are not reposted. The current GitHub identity authors
   the open PRs, so supervisor reviews use comments and do not count as independent
   approval. The supervisor merges only with explicit user authorization and does
   not change protection rules.

Block merging changes that break ownership/authentication, invent action success,
weaken consent/idempotency, expose restricted data/secrets, advertise unsupported
tools/policy as implemented, materially broaden scope, or misrepresent evaluation
evidence. WIP proposals can describe future tools when their status is explicit.
Resolve these with the relevant owner. FRONTEND owns the customer journey; DATASET
owns preparation/lineage; MCP coordinates the backend/runtime on the supervisor's
behalf. Promote the complete demo only when its end-to-end and submission gates
are evidenced, including the failure paths.

An in-chat supervision automation checks every 30 minutes. It reports meaningful
changes, findings and required action, and stays quiet while state is unchanged.
It records reviewed revisions and dependency status outside the public repository.
