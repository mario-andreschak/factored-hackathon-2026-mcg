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

Outputs go to `data/` (git-ignored): `data/bronze/` (raw landing), `data/builds/<run_id>/` (silver, gold, quarantine) and `data/CURRENT` (the published build). Only aggregates are written to `docs/pipeline/`
(`quality_report.md`, `manifest.json`), which are safe to commit: no rows, no credentials,
the bucket name is redacted. Low-RAM machines: add `--memory-limit 6GB`.

**Measured on the real bucket** (Windows laptop, 2026-09-27): all 6 tables, 5.9M rows, 4,391 objects in
~13 min, most of it S3 download. `--stage silver gold` re-runs locally in ~3 min. Per-customer lookup over
4.4M transactions: **p50 21 ms, p95 23 ms**. Row counts match `scripts/profile_s3.py` exactly
(4,425,008 transactions · 686,296 interactions · 171,321 transcripts · 67,095 complaints), so two
independent readers agree.

## Serving layer: snapshots, isolation, lineage, load, and source verification

| Need | How |
|---|---|
| **A failed build never replaces good data** | Silver, gold and quarantine are written to an isolated `data/builds/<run_id>/`. Gold only runs if silver passed every contract. `data/CURRENT` is swapped **atomically** to the new build only after the whole run succeeds; otherwise the previous snapshot keeps serving (`manifest.json` shows `"published": false`). Builds are never modified after they are written, so a reader that resolved a snapshot keeps a complete, consistent view even while a rebuild runs. The last 3 builds are kept. Resolve the live snapshot with `pipeline.common.current_gold("data")`. |
| **No cross-customer results** | `lookup.get_customer_transactions()` opens its **own cursor per call** (execute, description and fetch on that cursor, then close it), even when given a shared connection. A row is served only if the **customer exists**, the **product exists**, and the product belongs to that same customer. |
| **Reports are safe to commit** | Values are written to `docs/pipeline/` only for allow-listed categorical columns (`publish_values: true` in `contracts.yaml`). Free text (`customer_text`, complaint `description`, `merchant_name`, ...) is reported as **counts only**. |
| **S3 stays the source of record** | The pipeline only reads it. `docs/pipeline/source_objects.json` lists every object a build read (key, bytes, ETag, last-modified) plus a **source fingerprint**, which is also recorded in `manifest.json`. Same inputs give the same fingerprint; any new or changed object changes it. Every silver row keeps its `_source_file`. |
| **Load** | `python -m pipeline bench` runs 1 / 50 / 500 concurrent callers against the published snapshot and writes `docs/pipeline/lookup_bench.json`. Result on a 4-CPU machine over a 2M-row stand-in, local disk, one process: p95 **7 / 341 / 351 ms**, 0 errors, ~265 req/s. Per-request cursors cost latency under load; that is the price of isolation. A deployed service adds network overhead and can scale horizontally, because snapshots are read-only files. |
| **Confirm before acting** | [`verify.py`](verify.py) `verify_transaction_in_source()` re-reads the transaction from its S3 partition, plus the 7 days after it for late arrivals, and compares it with gold. It returns `verified`, `changed` (use the source values) or `not_found`. **Another customer's transaction returns `not_found`, identical to a missing one**; the real reason is only in `audit`, for server logs. Try it: `python -m pipeline verify --sample`. |

## What each stage guarantees

| Stage | Guarantees |
|---|---|
| **bronze** | Every CSV object is landed as-is (all `VARCHAR`), with `_source_file`, `_partition_date`, `_run_id`, `_ingested_at`. Objects are grouped by header, so **schema evolution** is handled and counted (`schema_variants`) without a slow per-file `union_by_name`. |
| **silver** | Types and required fields enforced from [`contracts.yaml`](contracts.yaml). Failing rows go to `data/quarantine/<table>.parquet` with reasons. **Dedup by PK** keeps the latest version (`dedup_order`, deterministic tie-break), and the report separates exact re-deliveries from conflicting versions. **Orphan FKs are flagged** (`_fk_<col>_missing`), never dropped, and so are **references to a product owned by a different customer** (`_owner_mismatch_<col>`). **Inconsistent spellings** (values that collide once accents and case are ignored, e.g. `México`/`Mexico`) are reported. **Late arrivals** flagged (`_late_arrival`: row sits in a partition later than its `process_date`). PII not needed downstream is dropped. The run **exits non-zero** if a table's reject rate exceeds `max_reject_rate`. |
| **reconciliation** | For every table: `raw = silver + quarantined + duplicates_removed`. Shown as ✅/❌ in the report. |
| **idempotency** | Full refresh; same input → identical silver rows (content hashes compared in tests). A late partition simply appears on the next run, and a corrected record **upserts** (tested). |

## Gold outputs

| Output | Consumer | Notes |
|---|---|---|
| `transactions_by_customer/bucket=N/` | banking MCP service | 128 stable md5 buckets, sorted by customer and date. [`lookup.py`](lookup.py) opens one bucket and filters by the **session's** customer. It only returns rows with `ownership_valid` and never returns `is_fraud` (kept for routing only). |
| `contact_demand.parquet` | analytics / slides | month × country × reason × channel with FCR, escalation, follow-up, and median wait/duration. |
| `classifier_dataset.parquet` | ML | Customer text plus weak labels. The split is by **customer fold and time** (test = unseen customers after 2026-03-17). `text_seen_in_train` flags template leakage. |
| `demo_seed_candidates.parquet` | backend / demo | Up to 25 customers per scenario: `normal` (clean history, happy path), `reversed`, `pending`, `declined`, `fraud_flagged` (→ human handoff), `near_duplicate` (same product and amount within 1 h). |

## What the organizer data tells us (profile + first real pipeline run)

These change how the rest of the team should work:

1. **Transcripts are templates.** Only **42 distinct `customer_text` values** across 171,321 transcripts, and `detected_intents` is `consulta_general` for 95%. Any classifier trained on this will look near-perfect and prove nothing. **The ML evaluation must use team-authored held-out text** (paraphrases, regional slang, Portuguese). **Measured: 100% of test-split texts (2,946/2,946) also appear in train**, even with a customer + time split.
2. **Weak labels are coarse.** `contact_reason` always equals `reason_category` (6 values: Transaccional, Producto, Queja, Técnico, Comercial, Retención).
3. **The advertised defects are absent in these tables.** 0 duplicate IDs, 0 orphans and 0 partition/process-date mismatches in transactions, interactions, transcripts and complaints. The **late-arrival and upsert behaviour is therefore proven on the labeled synthetic fixture** (`pipeline/fixture.py`), as the problem statement allows.
4. **Real quality issues found:** `merchant_name` is empty on **76.7%** of transactions, so the assistant must identify a charge by type, channel, amount and date, not by merchant. `transaction_country` mixes `México` and `Mexico` (40,515 rows). All 44,570 populated `complaints.affected_product_id` point to another customer's product. `origin_interaction_id` is always empty. 6,698 complaints have no subcategory.
5. **Vocabulary differs from the dictionary.** Product types and countries are in Spanish (`Tarjeta Crédito`, `México`). Enums therefore start in `warn` mode and are listed under *Contract drift* in the report. Promote them to `reject` once confirmed.

## Files

`contracts.yaml` rules · `bronze.py` / `silver.py` / `gold.py` stages · `lookup.py` MCP read path + bench · `report.py` report/manifest · `fixture.py` **synthetic** test data (not organizer data) · `verify.py` source re-check · `../tests/test_pipeline.py` 21 end-to-end tests, including a regression test for each finding of the PR #1 review.
