# Savia — Factored AI & Data Hackathon 2026 — MCG

A charge you don't recognize leaves you with two questions: what happened, and
what happens next? **Savia gives customers one place to understand the charge,
take the next step and check back without starting over.** It is a Spanish and
Portuguese banking-service prototype that brings the selected transaction,
conversation and follow-up together.

For customers, the value is a clear explanation and useful status during the
day. For the bank, the opportunity is fewer repeat contacts and a better-informed
review when a person is needed: the request, verified facts and unresolved
questions stay together. These are the product's intended benefits; the release
report distinguishes demonstrated behavior from unmeasured business impact.
Customer permissions, explicit consent and action policy are enforced by
application services.

Public demos use fictional customers and a simulated dispute service. A verified
intake receipt records intake; it does not establish a refund or resolution of
the underlying dispute. A saved handoff packet does not establish human pickup.

## Release and demo

Start with the [release candidate report](docs/submission/RELEASE_CANDIDATE.md) for the identified
source/runtime, measured customer journey, recording, decks and remaining gates.
The [submission guide](docs/SUBMISSION_GUIDE.md) maps organizer requirements to
that report. Earlier source tests and recordings retain their original scope.

Media artifacts are in [submission media](docs/submission/media/), with
the [editable submission deck](docs/submission/media/decks/savia-submission-deck.pptx)
and [pitch deck](docs/submission/media/decks/savia-pitch-deck.pptx). The release
report records final review, exports, recording and claim verification.

The intended demonstration follows one fictional customer from an unrecognized
charge to a useful answer or consented simulated intake, then a status check or
helpful next step. It includes Portuguese clarification, an honest failure or
human-required path, and voice conversation while work runs in the background.
See the release report for which parts were actually measured and recorded.

## Run locally

Choose the setup that matches what you want to exercise:

| Setup | Instructions | Scope |
| --- | --- | --- |
| Fictional portal preview | [Frontend setup](frontend/README.md#isolated-synthetic-invitation-preview) | Generates isolated fixtures and invitations, builds the UI, and serves a loopback API. No model, FLUJO, MCP or action is started. |
| Fictional local customer workflow | [RC startup](deploy/rc/README.md) | Generates fresh fixtures and a durable simulated ledger, calls the banking service in process, and uses an existing generic FLUJO model. Network MCP and native-flow deployment remain separate qualification scopes. |
| Voice companion | [Avatar setup](avatar/README.md) | Optional conversational interface; provider and joined banking acceptance have their own evidence. |
| Data pipeline | [Pipeline setup](pipeline/README.md) | Repeatable ingestion, ownership checks, lineage and customer-sharded snapshots. Organizer data requires approved private access. |

The fictional preview runbook includes Windows PowerShell and POSIX commands,
dependency installation and invitation generation. Use the invitation from the
generated private file at [localhost:43801](http://localhost:43801). No working
access code or provider credential is included in source. Keep private config,
customer rows and state outside tracked files.

The integrated fictional candidate opens at [127.0.0.1:43900](http://127.0.0.1:43900)
after following the RC startup guide. It requires an available configured generic
FLUJO model. Its generated fixture and state are separate from the organizer-data
portal and the hosted Fly build; the release report identifies each runtime.

## Why this workflow

The September 26 full scan of six relevant table families found **12,297
unrecognized-charge complaints out of 67,095 complaints**, and **4,425,008
transactions** with valid customer/product ownership. Historical complaint links
cannot identify a disputed transaction reliably: origin-interaction IDs were
empty, and every populated affected-product link crossed customer ownership.
The [data review](docs/DATA_REVIEW_2026-09-26.md) records the method and limits.

Savia therefore grounds new inquiries in owned transaction reads and keeps new
simulated receipts separate from uncertain historical complaint evidence. The
[ML notes](ml/README.md) explain the supplied transcripts' training limitations
and distinguish diagnostic router results from human-reviewed evaluation.
Current comparisons must cite their actual workload in the release report.

## Architecture and ownership

The pipeline prepares validated snapshots. The Savia host authenticates the
customer, resolves owned selections, handles explicit consent and verifies
receipts. The banking MCP owns banking data, policy and durable action state.
FLUJO supplies orchestration and language through existing interfaces; banking
keys and action capabilities stay outside generic language inputs. See the
[direct-host contract](frontend/DIRECT_MCP.md) and
[workflow implementation](docs/DISPUTE_IMPLEMENTATION.md).

**FLUJO main stays general purpose.** Domain integration belongs in this
repository, the banking MCP, or the owner-authorized isolated
`codex/hackathon-banking` branch. The [product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md)
and [deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md) govern integration.
The [Docker/Fly diagrams](docs/architecture/landscape-notes.md) describe the
September 30 configuration; they are historical diagrams, not current acceptance.

## Development and evidence

Use the [documentation index](docs/README.md) for contracts, data findings,
evaluation, contributor history and frozen qualification reports. The
[local CI policy](docs/LOCAL_CI.md) describes the eleven-job Windows/Linux route;
passing source checks qualify their exact source, not a deployed journey. The
[development-history viewer](docs/DEVELOPMENT_HISTORY.md) is an optional local
replay backed by private caches; it is not a public submission artifact.

| Directory | Purpose |
| --- | --- |
| `frontend/`, `avatar/` | Customer portal and voice companion |
| `banking_mcp/`, `dispute_workflow/` | Scoped banking tools and dispute workflow |
| `pipeline/`, `ml/` | Data preparation and diagnostic intent-router evaluation |
| `resources/`, `contracts/` | Prompts, synthetic policy and workflow contracts |
| `deploy/`, `scripts/` | Runtime setup, checks and reproducible utilities |
| `docs/submission/` | Final-day coordination, measurements and media |

Carlos contributed the data pipeline and customer lookup; Gloria designed the
prompt flow and R0–R18 decision motor. The customer assistant is Savia and the
implementation is named **transaction dispute workflow**. Historical reports
retain their original names and hashes. See [implementation credit and retained
state](docs/DISPUTE_IMPLEMENTATION.md) and Git history for the broader contribution record.
