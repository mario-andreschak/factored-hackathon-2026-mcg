# Factored AI & Data Hackathon 2026 — MCG

This repository contains the data audit, DuckDB pipeline, classifier baseline, read-only banking MCP and **Savia**, a customer-facing online banking demo for FLUJO-powered unrecognized-charge inquiries. Savia uses real organizer products and transactions from the published silver/gold snapshot. Names are fictional demo aliases; banking actions and complaint submission remain unimplemented customer features.

## Open the banking demo

The local Docker deployment is available at [localhost:43800](http://localhost:43800). Choose a Colombia, México or Argentina profile and enter the configured demo access code (local default: `2026`). Explore balances, accounts/cards, product details, transaction filters and CSV export, or ask the FLUJO assistant about a movement.

See [frontend setup and portable deployment](frontend/README.md) and [dataset, architecture and verification evidence](docs/ONLINE_BANKING_FRONTEND.md). The frontend runs alongside the existing FLUJO worker; its image contains neither customer rows nor service credentials.

## Start here

- [Hackathon audit and delivery plan](docs/HACKATHON_AUDIT_PLAN.md)
- [Direct S3 data review](docs/DATA_REVIEW_2026-09-26.md)
- [Banking MCP direct S3 plan](docs/BANKING_MCP_S3_PLAN.md)
- [FLUJO customer-bound banking run design](docs/FLUJO_BANKING_RUN_AUTH.md)
- [FLUJO proposal review, alternatives and executed evidence](docs/FLUJO_BANKING_RUN_AUTH_REVIEW.md)
- [DuckDB data pipeline and snapshot serving option](pipeline/README.md)
- [Banking MCP: tools, local FLUJO connections and identity contract](banking_mcp/README.md)
- [Banking MCP implementation and executed checks](docs/BANKING_MCP_IMPLEMENTATION.md)
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
| `banking_mcp/` | Read-only MCP server with verified per-call authority and bounded transaction reads |
| `frontend/` | Savia React UI, authenticated snapshot API, FLUJO customer chat and portable Docker deployment |
| `notes/` | Team idea notes |
| `private/` | Local-only original credential-bearing reference |

FLUJO remains the workflow backend. The banking MCP uses Carlos's customer-sharded Parquet snapshots for lookup and conditional S3 read-back for a selected transaction. Real customer reads require signed per-call authority outside model arguments; the FLUJO identity-hook PR implements verified runtime authority. The MCP runs as stdio inside the existing FLUJO container. A separate synthetic demo is usable now for graphical flow development. The customer-facing agent must not receive generic S3 tools or credentials. This serving path updates the earlier direct-S3 proposal.
