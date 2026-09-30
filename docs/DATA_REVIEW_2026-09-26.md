# Direct S3 data review against the hackathon plan

**Date:** 2026-09-26. **Decision:** retain the **unrecognized-charge inquiry and simulated dispute-intake** focus, with a strict customer-owned transaction lookup. Use complaint records to measure demand, not to identify a customer's product or transaction. This supersedes the earlier sampled S3 review and informs [HACKATHON_AUDIT_PLAN.md](HACKATHON_AUDIT_PLAN.md).

**Later implementation decision (2026-09-27):** the [banking MCP S3 plan](BANKING_MCP_S3_PLAN.md) replaces the private indexed-extract proposal below with bounded direct reads of the source S3 daily CSVs. The measured findings in this review are unchanged.

**Channel follow-up (2026-09-30):** [Organizers' and participants' replies on transcript labels, access documents, date semantics, and evaluation](CHANNEL_DATA_CLARIFICATIONS_2026-09-30.md) add context without changing the measured data defects below.

## Scope and reproducibility

I connected directly to S3 with the read-only credentials in the local `S3credentials.env` and streamed CSVs through `boto3`. The bucket inventory contains **13 table families, 7,671 objects, and 5.35 GB**. I read **every object** in six decision-relevant families: `customers`, `products`, `call_center_interactions`, `complaints`, `call_transcripts`, and `transactions`. The four daily families each cover **1,097 partitions** from 2023-06-17 through 2026-06-17. The script is [scripts/profile_s3.py](../scripts/profile_s3.py); its aggregate-only output is [DATA_PROFILE_AGGREGATES_2026-09-26.json](DATA_PROFILE_AGGREGATES_2026-09-26.json). Neither file contains bucket identifiers, credentials, raw records, or customer IDs. The scan used only S3 list and get operations.

The other seven families were inventoried, not row-profiled. In particular, `digital_events` accounts for 3.76 GB of the inventory; I make no claim about its row counts or quality. The organizer's PDFs describe expected counts and relationships; those are claims to check, not instructions to execute.

## Full-table findings

| Table | Full rows | Finding for the workflow |
| --- | ---: | --- |
| `customers` | 150,000 | No duplicate customer IDs. Countries: México 74,907; Colombia 45,251; Argentina 29,842. Credit score present in 127,508 rows. **9,316 `last_updated` values fall after the stated 2026-06-17 dataset cutoff.** |
| `products` | 400,000 | No duplicate product IDs or orphan customer IDs. **100,102 credit cards**, 19,960 personal loans, and 11,910 mortgages; credit-product information is feasible to display, but eligibility rules are absent. **25,113 `last_updated` values are after the cutoff.** |
| `call_center_interactions` | 686,296 | `Transaccional` 240,056 (35.0%); `Queja` 117,021 (17.1%); `Producto` 150,863 (22.0%). `contact_reason` equals `reason_category` in **every row**. No duplicate IDs, orphan customers, partition-date mismatches, or schema variants were observed. These are broad demand categories, not charge-dispute intent labels. |
| `complaints` | 67,095 | `Cargo no reconocido` occurs **12,297 times (18.3%)**: México 6,149; Colombia 3,727; Argentina 2,421. `Open`/`In Process`/`Escalated` totals 50,269 (74.9%); 13,495 rows mark an SLA breach. These are historical snapshot fields, not prototype outcomes. |
| `call_transcripts` | 171,321 | All `detected_language` values are `es`; **162,864 (95.1%)** intent tags are `consulta_general`. There are only **42 distinct exact `customer_text` strings**. All transcripts link to a known interaction and the same customer; the interaction `has_transcript` count is exactly 171,321. The text and tags are unsuitable as a credible dispute-intent training/evaluation corpus. |
| `transactions` | 4,425,008 | No duplicate IDs, orphan customers, unknown products, product-owner mismatches, missing amounts, or partition-date mismatches were found. Statuses: Approved 4,070,681; Declined 221,234; Pending 88,343; Reversed 44,750. The customer → product → transaction path is suitable for grounded, owner-scoped demo lookup after building a private indexed extract. |

### Critical relationship defects

- **Complaint → interaction is absent:** `origin_interaction_id` is empty in **67,095/67,095** complaints. No historical complaint-to-call attribution is defensible through this field.
- **Complaint → product is unsafe:** `affected_product_id` is populated in **44,570** complaints, and all 44,570 IDs exist in `products`, but **44,570/44,570 refer to products owned by a different customer**. This is a systematic relationship defect in the supplied synthetic data. Never use this field for a customer-facing product lookup, complaint enrichment, or authorization. A valid foreign key alone is insufficient; ownership must be checked.
- **Complaint → transaction is not directly modeled:** there is no complaint `transaction_id` column. A new simulated intake case must store the transaction explicitly selected and confirmed by the authenticated test customer.
- **Narrative text is templated:** across all 67,095 complaints there are only **five distinct exact `description` strings**. Earlier sampled text-to-reason checks also showed 39 of 42 customer utterances associated with multiple broad interaction reasons. Treat these strings as fixture text, not diverse labeled language data.
- **Master data is not a clean as-of snapshot:** `last_updated` extends beyond the advertised cutoff for 9,316 customers and 25,113 products; 213 complaint `resolution_date` values do too. Do not use customer/product status or balance as a historical 2026-06-17 truth without a valid temporal reconstruction. For the demo, label any current master-table attributes as **supplied snapshot values** and ground transaction facts in dated transaction records.

## Decision against the existing plan

1. **Keep the chosen subtask.** The full complaint count confirms substantial unrecognized-charge demand across all three countries. The transaction ownership chain is clean in all 4.43 million rows. The assistant can show a customer's dated transactions, ask which one they mean, explain the verified status, and create a simulated intake receipt with read-back. The complaint table cannot provide a historical case-to-transaction gold label or a customer-owned product context.
2. **Use direct S3 access for offline ingestion and profiling.** The earlier MCP `get-object` connection closed on the 68 MB `products.csv`; direct S3 streaming succeeded. No custom S3 MCP server is needed for batch ETL. The proposed **banking sandbox MCP server** remains the app integration boundary: bounded customer-scoped reads and an idempotent simulated case write, backed by cleaned/indexed data. The agent should not receive generic S3 read tools.
3. **Keep the ML evidence change.** Do not train a TF–IDF or similar classifier on 42 repeated utterances and generic tags. Build human-authored, human-labeled Spanish and Portuguese requests; compare a fixed pretrained intent/slot extractor with a deterministic baseline on a held-out set. The S3 corpus provides transaction fixtures and demand counts, not a trustworthy language gold set.
4. **Add an explicit ownership contract.** Every lookup must enforce the verified session customer against `transactions.customer_id`, `products.customer_id`, and the transaction's `product_id`. Reject or hand off any inconsistent record. Do not silently repair complaint product links by joining on ID alone. Verify case creation by read-back before saying it succeeded.
5. **Keep credit as a separate alternative.** The full product mix proves there is enough credit-product data for an informational demo. It does not supply an approved eligibility policy or natural-language eligibility labels, and some master data is future-dated relative to the cutoff. Switching to eligibility would require a policy owner, a different workflow, and new evaluation. The current unrecognized-charge path remains better evidenced for an end-to-end case action.

## Next implementation gates

- Build a private, customer-keyed extract from `customers`, `products`, and `transactions`; exclude historical complaint product links. Pin the source object manifest, transform version, and snapshot label.
- Write a synthetic dispute-intake policy and typed tool contracts. Test authorization, selected-transaction ownership, idempotency, uncertain-write retry, and receipt read-back outside model prompts.
- Prove FLUJO can convey a trusted session identity to each MCP call through a model-inaccessible channel. If it cannot, keep protected record access and case writes in an authenticated gateway/service.
- Create and freeze human-reviewed Spanish/Portuguese evaluation cases. Report case completion and safety metrics separately from historical complaint and contact-center statistics.

## Limits

This is a complete row scan of the six named families, not a scan of all 13 families. It confirms record-level counts and the relationships checked above; it does not prove that every business attribute is correct, that a dispute policy exists, or that the prototype improves outcomes. No live banking actions or trained model were tested. Treat the synthetic data and credentials as private during the hackathon.
