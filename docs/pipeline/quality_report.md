# Data quality report

Run `20260927T215415Z-c2be31` · pipeline 0.1.0 · contracts `e1fe119611f1` · source `s3://<bucket>/data` · stages `bronze,silver,gold`

Measured by `python -m pipeline run`. Every raw row is accounted for: **raw = silver + quarantined + duplicates removed** (the *Reconciles* column).

## Row accounting

| Table | Source objects | Raw rows | Quarantined | Dups removed | Silver rows | Reconciles | Late arrivals | Partition≠process_date |
|---|---:|---:|---:|---:|---:|:-:|---:|---:|
| customers | 1 | 150,000 | 0 | 0 | 150,000 | ✅ | 0 | 0 |
| products | 1 | 400,000 | 0 | 0 | 400,000 | ✅ | 0 | 0 |
| transactions | 1,097 | 4,425,008 | 0 | 0 | 4,425,008 | ✅ | 0 | 0 |
| call_center_interactions | 1,097 | 686,296 | 0 | 0 | 686,296 | ✅ | 0 | 0 |
| call_transcripts | 1,097 | 171,321 | 0 | 0 | 171,321 | ✅ | 0 | 0 |
| complaints | 1,097 | 67,095 | 0 | 0 | 67,095 | ✅ | 0 | 0 |

## Duplicates

| Table | Duplicate rows removed | PKs with >1 version | PKs whose versions differ |
|---|---:|---:|---:|
| customers | 0 | 0 | 0 |
| products | 0 | 0 | 0 |
| transactions | 0 | 0 | 0 |
| call_center_interactions | 0 | 0 | 0 |
| call_transcripts | 0 | 0 | 0 |
| complaints | 0 | 0 | 0 |

## Referential integrity (orphans are flagged, not dropped)

| Table.column | → parent | Non-null | Missing in parent | Rate |
|---|---|---:|---:|---:|
| products.customer_id | customers | 400,000 | 0 | 0.00% |
| transactions.product_id | products | 4,425,008 | 0 | 0.00% |
| transactions.customer_id | customers | 4,425,008 | 0 | 0.00% |
| call_center_interactions.customer_id | customers | 686,296 | 0 | 0.00% |
| call_transcripts.interaction_id | call_center_interactions | 171,321 | 0 | 0.00% |
| call_transcripts.customer_id | customers | 171,321 | 0 | 0.00% |
| complaints.customer_id | customers | 67,095 | 0 | 0.00% |
| complaints.affected_product_id | products | 44,570 | 0 | 0.00% |
| complaints.origin_interaction_id | call_center_interactions | 0 | 0 | — |

## Quarantine reasons

None.

## Nullable columns — null rate (top 6 per table)

- **customers**: detected_accent 29.9%, registration_branch_id 0.0%, accepts_marketing 0.0%
- **products**: credit_limit 68.7%, days_past_due 68.7%, expiration_date 66.7%, last_transaction_date 23.6%, interest_rate 10.0%, opening_branch_id 0.0%
- **transactions**: merchant_category 76.8%, merchant_name 76.7%, branch_id 68.6%, transaction_category 60.9%, amount_usd 57.3%, fraud_score 20.0%
- **call_center_interactions**: mentioned_products 60.0%, wait_time_seconds 30.0%, customer_detected_accent 29.8%, agent_used_accent 29.8%, duration_seconds 14.0%, agent_id 0.0%
- **call_transcripts**: detected_accent 36.8%, duration_seconds 14.0%, accent_confidence 10.0%, detected_keywords 5.1%, audio_quality 5.0%, detected_intents 4.9%
- **complaints**: origin_interaction_id 100.0%, closing_date 96.3%, resolution_satisfaction 96.3%, compensation_granted 93.1%, resolution 77.2%, resolution_date 77.1%

## Contract drift

None detected.

## Gold outputs

- **transactions_by_customer**: 4,425,008 rows in 128 buckets; 4,425,008 with product owned by the same customer (only these are served).
- **classifier_dataset**: 171,321 rows, splits {'test': 2946, 'val': 17219, 'train': 109580, 'excluded': 41576}, time holdout 2026-03-17. Distinct normalized texts: 42. **Test rows whose exact text also appears in train: 2,946 (1.0)** — report metrics on the unseen-text subset too.
- **contact_demand**: 3,927 rows. Top reasons: Transaccional 35.0%; Producto 22.0%; Queja 17.1%; Técnico 15.0%; Comercial 8.0%; Retención 3.0%
- **demo_seed_candidates**: 500 customers (500 with a reversal, 0 with near-duplicate charges, 500 fraud-flagged).
- **lookup latency** (50 customers, local disk): p50 20.8 ms · p95 23.2 ms · max 49.5 ms.
