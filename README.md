# Savia — Factored AI & Data Hackathon 2026 — MCG

A charge you don't recognize leaves you with two questions: what happened, and
what happens next? **Ask once. Explore options with Savia's team. Return for a
clear next step.** Savia is a friendly Spanish and Portuguese voice assistant
that brings the question, verified transaction facts and follow-up together.

Customers can ask two Savia AI agents to consider an informational inquiry from
different perspectives: evidence to compare and useful next steps. Their actual
work status and suggestions are saved so the customer can return without losing
the thread. Voice and keyboard conversation sit alongside the guarded banking
workbench; bank consent and receipt verification remain separate.

For customers, the value is a clear explanation and useful status during the
day. For the bank, the opportunity is fewer repeat contacts and a better-informed
review when a person is needed: the request, verified facts and unresolved
questions stay together. These are the product's intended benefits; the release
report distinguishes demonstrated behavior from unmeasured business impact.
Customer permissions, explicit consent and action policy are enforced by
application services.

Public demos use fictional customers and a simulated dispute service. A verified
intake receipt records intake; it does not establish a refund or resolution of
the underlying dispute. Marking an informational answer helpful does not resolve
a bank case. A saved handoff packet does not establish human pickup.

## Release and demo

Start with the [release candidate report](docs/submission/RELEASE_CANDIDATE.md) for the identified
source/runtime, measured customer journey, recording, decks and remaining gates.
The [submission guide](docs/SUBMISSION_GUIDE.md) maps organizer requirements to
that report. Earlier source tests and recordings retain their original scope.

Try the [public fictional demo](https://savia-rc-2026.fly.dev) with
**`SAVIA-2026`** at the entry gate and customer profile login. Customers,
movements and intake are simulated; provider completions and voice calls are
real. The [public RC runbook](deploy/rc/PUBLIC.md) describes the isolated
deployment and pinned source.

Media artifacts are in [submission media](docs/submission/media/), with
the [editable submission deck](docs/submission/media/decks/savia-submission-deck.pptx)
and [pitch deck](docs/submission/media/decks/savia-pitch-deck.pptx). The release
report records final review, exports, recording and claim verification.

The product story follows one fictional customer from an unrecognized charge to
a useful answer, team exploration and a return visit with helpful status. A
consented simulated intake, Portuguese clarification and honest failure/handoff
show how the experience handles uncertainty. The [inquiry guide and actual
proof](docs/submission/assistant/README.md) distinguish the two-agent provider run
from the generic FLUJO MCP wiring. The release report owns final recorded claims.

The portal's new-chat control archives the visible transcript and clears its
selected context; the previous conversation remains viewable. Saved inquiries,
bank receipts, pending consent and follow-ups remain separate. Inquiry tracking
runs while the host is running, with quiet unchanged checks and a seven-day
limit. Scheduling tests do not establish a week of observed operation.

## Run locally

Choose the setup that matches what you want to exercise:

| Setup | Instructions | Scope |
| --- | --- | --- |
| Fictional portal preview | [Frontend setup](frontend/README.md#isolated-synthetic-invitation-preview) | Generates isolated fixtures and invitations, builds the UI, and serves a loopback API. No model, FLUJO, MCP or action is started. |
| Fictional local customer workflow | [RC startup](deploy/rc/README.md) | Fresh fixtures, durable inquiries and simulated ledger; banking service in process. Select the generic FLUJO model or explicit direct OpenRouter profile. Native-flow and network bank-MCP deployment remain separate scopes. |
| Savia voice interface | [Eyes and voice setup](frontend/README.md) | Integrated assistant conversation and background status; current acceptance is recorded in the release report. |
| Data pipeline | [Pipeline setup](pipeline/README.md) | Repeatable ingestion, ownership checks, lineage and customer-sharded snapshots. Organizer data requires approved private access. |

The fictional preview runbook includes Windows PowerShell and POSIX commands,
dependency installation and invitation generation. Use the invitation from the
generated private file at [localhost:43801](http://localhost:43801). Private
access codes and provider credentials stay outside source. Keep private config,
customer rows and state outside tracked files.

The integrated fictional candidate opens at [127.0.0.1:43900](http://127.0.0.1:43900)
after following the RC startup guide. The default profile uses an available
generic FLUJO model; `--provider openrouter` explicitly selects the separate
direct-provider profile. Its generated fixture and state are separate from the
organizer-data portal and hosted Fly build; the release report identifies each runtime.

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
The app owns informational inquiry events and follow-up independently of banking
consent and receipts. FLUJO supplies generic interfaces and the scoped MCP flow;
language execution uses the explicitly selected profile. Banking keys and action
capabilities stay outside generic language inputs. See the
[direct-host contract](frontend/DIRECT_MCP.md) and
[workflow implementation](docs/DISPUTE_IMPLEMENTATION.md).

**FLUJO main stays general purpose.** Domain integration belongs in this
repository, the banking MCP, or the owner-authorized isolated
`codex/hackathon-banking` branch. The [product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md)
and [deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md) govern integration.
The [frozen runtime source](docs/submission/runtime-source-final.json) identifies
the accepted integrated Savia build. The
[technical system landscape](docs/architecture/system-landscape.md) documents
Savia's case lifecycle, native voice and recovered ten-by-ten FLUJO swarm design. The
[viewer](docs/architecture/deployment-landscapes.html#system) includes its
diagram and retains the dated September 30 Docker/Fly configuration.

## Development and evidence

Use the [documentation index](docs/README.md) for contracts, data findings,
evaluation, contributor history and frozen qualification reports. The
[local CI policy](docs/LOCAL_CI.md) describes the eleven-job Windows/Linux route;
passing source checks qualify their exact source, not a deployed journey. The
[development-history viewer](docs/DEVELOPMENT_HISTORY.md) is an optional local
replay backed by private caches; it is not a public submission artifact.

| Directory | Purpose |
| --- | --- |
| `frontend/`, `frontend/src/avatar/` | Customer portal and integrated voice companion |
| `savia_assistant/` | Durable informational inquiries, two-agent exploration and scoped MCP |
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
