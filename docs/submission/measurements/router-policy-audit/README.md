# Frozen router sample: automated policy audit

Two fresh Codex agents independently applied the written label protocol to the
same fixed eight Spanish/Portuguese requests. **Both agreed on all eight labels,
and each agreed with the frozen dataset's proposed labels on 8/8.** This is
completed automated semantic validation of **8/120 synthetic requests**. It is
not human adjudication, a classifier accuracy measurement, or approval of the
remaining 112 labels.

On **October 5, 2026 (America/Bogota)**, the owner delegated the language
review to the agents. For the bounded hackathon handover, the coordinator used
this disclosed automated sample audit in place of the earlier human-only
pre-submission plan. The owner did not supply labels or human label
approval. Language-speaking human adjudication remains pending and is needed
before claiming human-validated labels or real-customer quality.

The sample was fixed before the audits: one lowest SHA256 of UTF-8 `seed + text`
per **original proposed class/language stratum**, then shuffled by the same
hash. The seed is `savia-human-sample-v1-20261005`. The reviewers received the
label-free packet and protocol; they did not receive the CSV, proposed labels,
predictions, training examples, each other's audit, or earlier reviews. Each
fresh agent started without inherited conversation context. Their raw outputs
were frozen before the coordinator compared them with the proposed labels.
This independence is about access to this task's materials; both judgments are
AI-generated and can share language-model biases.

| Case | Language | English gloss | Both audits / proposed label | Policy reason |
| --- | --- | --- | --- | --- |
| A | Portuguese | How much available limit do I have on the card right now? | `inquiry` | Neutral request for an own-account fact; no problem is asserted. |
| B | Portuguese | My caregiver is pressuring me to hand over control of the account, and I am afraid of being left without my money. | `human` | Asserted coercive control and vulnerability invoke the human route. |
| C | Portuguese | The amount charged to the card is greater than the amount on the purchase receipt. | `dispute` | The customer asserts an incorrect charge amount. |
| D | Spanish | If you do not address this duplicate charge, I am going to file a lawsuit against the bank. | `human` | The legal threat takes priority over the duplicate-charge problem. |
| E | Portuguese | Suggest an easy recipe for lunch. | `other` | A recipe request falls outside account and transaction support. |
| F | Spanish | Do you allow pets inside the branch? | `other` | Branch facilities/access fall outside the chosen support scope. |
| G | Spanish | The refund appears as completed at the merchant, but I still do not have that money in the account. | `dispute` | The customer asserts a missing refund. |
| H | Spanish | Hey, I sent money a little while ago. Can you tell me whether it is still being processed? | `inquiry` | A neutral transfer-status question does not assert nonreceipt or failure. |

The glosses and reasons above come from the AI audits. The exact original
utterances remain in the [frozen packet](human-adjudication-sample.json).
Its original filename and `savia-blind-human-sample/v1` schema are retained for
byte identity; they describe its initial intended use, not completed human work.

The protocol gives asserted security risk, an explicit person request, legal
threat or vulnerability priority over a transaction problem; a transaction
problem takes priority over a neutral factual request; remaining cases are
`other`. A negated incident or person request alone does not invoke `human`.
See the full [label protocol](../../../ml/router_holdout_provenance.md#label-protocol).

Run from the repository root with Python 3.10+; no dependencies or provider
calls are required:

```sh
python scripts/audit_router_policy_sample.py
```

The script verifies the exact CSV SHA256, original packet SHA256, both raw
review hashes, reviewer identities, permitted classes and case IDs. It
reproduces the prespecified selection and shuffle, then compares the frozen
audits with the eight proposed labels. Its deterministic output must match
the [recorded comparison](comparison.json). It checks identity, sampling and
agreement; it is not a semantic classifier or an independent correctness oracle.

The [manifest](manifest.json) records the hashes, scope and handover decision.
The raw [audit A](policy-label-audit-a.json) and
[audit B](policy-label-audit-b.json) are preserved without normalization.
The original CSV and model, thresholds, prior metrics, training data and
historical review records remain unchanged. No predictions were used to select
the sample or conduct these audits, and no new holdout accuracy was measured.

One example per proposed class/language gives finite coverage of the protocol,
not a random prevalence sample. The other 112 labels, negation and closer
boundaries across the full set still need further validation. Agreement here
does not establish real customer behavior, deployed routing, banking actions,
or safety beyond these eight examples.
