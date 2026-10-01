# Factored AI & Data Hackathon 2026 — MCG

This repository contains the data audit, DuckDB pipeline, classifier baseline, banking MCP and **Savia**, a customer-facing online banking demo for FLUJO-powered unrecognized-charge inquiries. Savia uses real organizer products and transactions from the published silver/gold snapshot. Names are fictional demo aliases. An opt-in simulated intake and verified human handoff prototype is described in [docs/SIMULATED_INTAKE_V0.md](docs/SIMULATED_INTAKE_V0.md); it does not submit a bank dispute or issue a refund.

## FLUJO product boundary

FLUJO is a long-lived, general-purpose product. Keep its main branch and default
build free of banking or hackathon backend code, routes, policy and dependencies.
Use existing generic interfaces; keep product-specific behavior in Savia and the
banking MCP where possible. The owner-authorized FLUJO
[`codex/hackathon-banking` branch](https://github.com/mario-andreschak/FLUJO/tree/codex/hackathon-banking)
preserves the reversed hackathon integration separately from generic main.
See the [architecture boundary and review gate](docs/FLUJO_PRODUCT_BOUNDARY.md)
and [deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md).

## Open the banking demo

The local Docker deployment is described at [localhost:43800](http://localhost:43800). For the local organizer-data demo, choose a Colombia, México or Argentina profile and enter the configured access code; there is no shared default code. External fictional invitations use their separately bound owner access. See the setup guide for the active mode and release limits. Explore balances, accounts/cards, product details, transaction filters and CSV export, or ask about a movement.

See [frontend setup and portable deployment](frontend/README.md) and [dataset, architecture and verification evidence](docs/ONLINE_BANKING_FRONTEND.md). The frontend runs alongside the existing FLUJO worker; its image contains neither customer rows nor service credentials.

## Docker and Fly deployment landscapes

The diagrams show the captured configurations reviewed on September 30, 2026:
where source data enters, how it reaches the frontend API and banking MCP, how
users connect, and which network, process and storage boundaries protect it.
The banking integration shown belongs to the dedicated hackathon runtime
described in the [deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md).

### Docker: local containers

![Docker deployment landscape: S3 ingestion, shared read-only snapshot, Savia frontend API, private FLUJO worker and banking MCP, user connections and persistent state](docs/architecture/docker-landscape.png)

### Fly: hosted Machine

![Fly deployment landscape: private initial migration, HTTPS gateway, loopback Savia and FLUJO services, banking MCP and persistent data volume](docs/architecture/fly-landscape.png)

Download the [two-page landscape PDF](docs/architecture/deployment-landscapes.pdf),
[Docker SVG](docs/architecture/docker-landscape.svg),
[Fly SVG](docs/architecture/fly-landscape.svg), or
[self-contained viewer with zoom and descriptions](docs/architecture/deployment-landscapes.html).
See [configuration details and evidence](docs/architecture/landscape-notes.md)
for the separate screen/chat read paths, optional S3 verification, persistence
and recorded runtime limitations. The source Docker image's banking-adapter
omission and Fly's pending customer inquiry/revocation acceptance are marked;
these diagrams do not establish successful live acceptance.

## Start here

- [FLUJO product boundary for this hackathon](docs/FLUJO_PRODUCT_BOUNDARY.md)
- [Dedicated FLUJO hackathon branch and deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md)
- [Data recovery review and local runbook (September 29)](docs/DATA_RECOVERY_2026-09-29.md)
- [Current banking MCP implementation and measured limits](docs/BANKING_MCP_IMPLEMENTATION.md)
- [Current operator demo](docs/BANKING_OPERATOR_DEMO.md)
- [Hackathon audit and delivery plan](docs/HACKATHON_AUDIT_PLAN.md)
- [Hackathon supervision and October 3 team target](docs/HACKATHON_SUPERVISION.md)
- [Direct S3 data review](docs/DATA_REVIEW_2026-09-26.md)
- [Channel clarifications on dataset quality (September 30)](docs/CHANNEL_DATA_CLARIFICATIONS_2026-09-30.md)
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

The banking MCP uses Carlos's customer-sharded Parquet snapshots for lookup and conditional S3 read-back of a selected transaction. Customer reads require signed per-call authority outside model arguments. FLUJO #534 removed the banking adapter and in-worker integration from generic main; their combined source is now preserved on the dedicated hackathon branch. Existing measurements describe older revisions, not acceptance of a newly deployed branch. Project PRs #31/#32 are an unfinished host/MCP alternative and are not included in this branch. Neither the source restoration nor branch preservation upgraded the local worker or established joined customer acceptance. Bank keys, raw record identifiers, selection/action capabilities and generic S3 credentials must not reach the language flow.
