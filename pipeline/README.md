# Data pipeline (DuckDB)

Deterministic bronze → silver → gold pipeline over the organizer's S3 CSVs. One command, no
cluster, runs on a laptop or Colab. Complements `scripts/profile_s3.py` (which measures) by
producing **clean, reusable, tested outputs** for the banking MCP service, analytics, and ML.

```
S3 CSVs ──► bronze (raw, all text + lineage) ──► silver (typed, deduped, flagged) ──► gold (one output per consumer)
                                                  └─► quarantine (rejected rows + reason)
```

## Run it

```powershell
python -m pip install -r requirements-pipeline.txt -r requirements-s3.txt
python -m pipeline run                              # all stages, reads S3credentials.env
python -m pipeline run --stage silver gold          # re-run from local bronze, no S3 needed
python -m pytest -q                                 # tests on the synthetic fixture
```

Outputs go to `data/` (git-ignored). Only aggregates are written to `docs/pipeline/`
(`quality_report.md`, `manifest.json`), which are safe to commit: no rows, no credentials,
the bucket name is redacted. Low-RAM machines: add `--memory-limit 6GB`.

Measured on a synthetic 2M-row / 1,163-object stand-in (local disk, 4 vCPU): full run **25 s**;
per-customer lookup **p50 ≈ 5 ms, p95 ≈ 7 ms**. Real S3 timings will be in `manifest.json`.

## What each stage guarantees

| Stage | Guarantees |
|---|---|
| **bronze** | Every CSV object is landed as-is (all `VARCHAR`), with `_source_file`, `_partition_date`, `_run_id`, `_ingested_at`. Objects are grouped by header, so **schema evolution** is handled and counted (`schema_variants`) without a slow per-file `union_by_name`. |
| **silver** | Types and required fields enforced from [`contracts.yaml`](contracts.yaml). Failing rows go to `data/quarantine/<table>.parquet` with reasons. **Dedup by PK** keeps the latest version (`dedup_order`, deterministic tie-break), and the report separates exact re-deliveries from conflicting versions. **Orphan FKs are flagged** (`_fk_<col>_missing`), never dropped. **Late arrivals** flagged (`_late_arrival`: row sits in a partition later than its `process_date`). PII not needed downstream is dropped. The run **exits non-zero** if a table's reject rate exceeds `max_reject_rate`. |
| **reconciliation** | For every table: `raw = silver + quarantined + duplicates_removed`. Shown as ✅/❌ in the report. |
| **idempotency** | Full refresh; same input → identical silver rows (content hashes compared in tests). A late partition simply appears on the next run, and a corrected record **upserts** (tested). |

## Gold outputs

| Output | Consumer | Notes |
|---|---|---|
| `transactions_by_customer/bucket=N/` | banking MCP service | 128 stable md5 buckets, sorted by customer and date. [`lookup.py`](lookup.py) opens one bucket and filters by the **session's** customer. It only returns rows with `ownership_valid` and never returns `is_fraud` (kept for routing only). |
| `contact_demand.parquet` | analytics / slides | month × country × reason × channel with FCR, escalation, follow-up, and median wait/duration. |
| `classifier_dataset.parquet` | ML | Customer text plus weak labels. The split is by **customer fold and time** (test = unseen customers after 2026-03-17). `text_seen_in_train` flags template leakage. |
| `demo_seed_candidates.parquet` | backend / demo | Customers with a reversal, near-duplicate charges (same product, merchant and amount within 1 h), or a fraud flag. |

## What the organizer data already tells us (from `DATA_PROFILE_AGGREGATES_2026-09-26.json`)

These change how the rest of the team should work:

1. **Transcripts are templates.** Only **42 distinct `customer_text` values** across 171,321 transcripts, and `detected_intents` is `consulta_general` for 95%. Any classifier trained on this will look near-perfect and prove nothing. **The ML evaluation must use team-authored held-out text** (paraphrases, regional slang, Portuguese). The pipeline's `test_text_leakage_rate` will show this on the real run.
2. **Weak labels are coarse.** `contact_reason` always equals `reason_category` (6 values: Transaccional, Producto, Queja, Técnico, Comercial, Retención).
3. **The advertised defects are absent in these tables.** 0 duplicate IDs, 0 orphans and 0 partition/process-date mismatches in transactions, interactions, transcripts and complaints. The **late-arrival and upsert behaviour is therefore proven on the labeled synthetic fixture** (`pipeline/fixture.py`), as the problem statement allows.
4. **Real quality issues found:** `transaction_country` mixes `México` and `Mexico` (40,515 rows). All 44,570 populated `complaints.affected_product_id` point to another customer's product. `origin_interaction_id` is always empty. 6,698 complaints have no subcategory.
5. **Vocabulary differs from the dictionary.** Product types and countries are in Spanish (`Tarjeta Crédito`, `México`). Enums therefore start in `warn` mode and are listed under *Contract drift* in the report. Promote them to `reject` once confirmed.

## Files

`contracts.yaml` rules · `bronze.py` / `silver.py` / `gold.py` stages · `lookup.py` MCP read path + bench · `report.py` report/manifest · `fixture.py` **synthetic** test data (not organizer data) · `../tests/test_pipeline.py` 12 end-to-end tests.
