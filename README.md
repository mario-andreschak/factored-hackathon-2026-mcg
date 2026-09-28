# Factored AI & Data Hackathon 2026 — MCG

This repository contains our data audit and implementation plan for a FLUJO-powered **unrecognized-charge inquiry and simulated dispute-intake** workflow. It is an analysis and planning deliverable; the customer-facing flow and banking sandbox are not implemented yet.

## Start here

- [Hackathon audit and delivery plan](docs/HACKATHON_AUDIT_PLAN.md)
- [Direct S3 data review](docs/DATA_REVIEW_2026-09-26.md)
- [Banking MCP direct S3 plan](docs/BANKING_MCP_S3_PLAN.md)
- [FLUJO customer-bound banking run design](docs/FLUJO_BANKING_RUN_AUTH.md)
- [FLUJO proposal review, alternatives and executed evidence](docs/FLUJO_BANKING_RUN_AUTH_REVIEW.md)
- [DuckDB data pipeline and snapshot serving option](pipeline/README.md)
- [Aggregate profile](docs/DATA_PROFILE_AGGREGATES_2026-09-26.json)
- [Challenge and dataset references](docs/reference/)
- [S3 profiling script](scripts/profile_s3.py)

The full scan found **12,297 unrecognized-charge complaints** and **4,425,008 transactions** with valid customer/product ownership. Historical complaint links are unusable for the proposed customer workflow: all complaint origin-interaction IDs are empty, and every populated affected-product ID belongs to another customer. See the review for methods, denominators, and limits.

## Local S3 profiling

Install the dependency and copy the configuration template:

```powershell
python -m pip install -r requirements-s3.txt
Copy-Item S3credentials.env.example S3credentials.env
```

Fill `S3credentials.env` privately, then run:

```powershell
python scripts/profile_s3.py
```

The script reads S3 objects and writes only aggregate counts to `docs/DATA_PROFILE_AGGREGATES_2026-09-26.json`. It does not save source rows or credentials. The local env file, raw data, and `private/` source materials are ignored by Git. The data dictionary under `docs/reference/` has its credential page redacted.

## Repository layout

| Path | Purpose |
| --- | --- |
| `docs/` | Plan, evidence report, and aggregate JSON |
| `docs/reference/` | Organizer PDFs, including a redacted data dictionary |
| `scripts/` | Reproducible profiling and FLUJO review probes |
| `pipeline/` | DuckDB ingestion, ownership validation and customer-sharded snapshot outputs |
| `notes/` | Team idea notes |
| `private/` | Local-only original credential-bearing reference |

The proposed banking MCP server is a separate application component in the plan. FLUJO remains the workflow backend and calls it with verified, per-run customer context; the MCP service reads bounded source S3 transaction CSVs, enforces ownership in service code, and returns only masked banking facts. The customer-facing agent must not receive generic S3 tools or credentials. The direct-read design supersedes the earlier private-extract implementation choice in the September 26 audit.
