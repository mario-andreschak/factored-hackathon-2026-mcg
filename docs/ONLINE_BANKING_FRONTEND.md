# Online banking frontend

The portal gives hackathon customers a sign-in flow, product and balance
overview, transaction exploration and support using the organizer dataset.
React/Vite assets and a FastAPI API ship in one Docker image. The data API
reads the existing silver products/customers and customer-sharded gold
transaction Parquet files with DuckDB; source
credentials and full customer rows never enter the image or client bundle.

## Repository and runtime context

Work started on `codex/banking-frontend`, in a new managed worktree based on
banking MCP PR #6 at `c526014841597d42e845c439e5e600a3f9b80205`.
The root checkout's local `main` was still at `6c6cef7`, whose README describes
an earlier planning state. The inspected remote `origin/main` has advanced to
`031db90`, after PR #5 merged the banking MCP and subsequent commits added
`graph_config_v3.yaml`, `resources/prompts/`, `resources/policies/`, `contracts/`
and `config/policy_rules.yaml`. These are workflow/policy specifications and
proposals; their presence does not establish a deployed dispute-submission
workflow. The runtime used here is the existing approved `Banking_Customer`
graph and authenticated read-only banking MCP.

[PR #6](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/6)
contains the implemented banking MCP and real FLUJO acceptance evidence.
[PR #7](https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/7)
adds nine Spanish/Portuguese conversational prompt YAMLs; those prompts are
not a complete running customer frontend. This branch depends on PR #6 and
does not merge or modify either open PR.

The existing Docker Desktop deployment has a healthy
`flujo-slack-flujo-1` worker, a separate UI proxy on loopback port 43420 and a
Slack gateway on `flujo-slack_default`. The new frontend joins that network
through an optional Compose override and publishes loopback port 43800.
Its deployment does not recreate the existing worker, alter policy or access
the Docker socket.

## Data and authority

The original repository's ignored `data/` directory is mounted read-only at
`/banking-data`. Demo profile IDs are selected or configured only on the API
server. Product and transaction reads are restricted to the selected
customer, with product ownership checked before returning a transaction.
Names shown for demo profiles are aliases, not source identity claims.

The inspected published build is `20260928T235012Z-ad5cf4`, created
`2026-09-28T23:50:25+00:00`, with source fingerprint `492b923192bf6ea2` and
`source_validation=legacy_inventory`. It contains 150,000 silver customers,
400,000 silver products and 4,425,008 transactions across 128 gold buckets.
Every gold transaction has valid ownership. Transaction timestamps run from
June 17, 2023 through June 18, 2026. This identifies the published organizer
snapshot; it is not a fresh S3 or live-bank synchronization claim.

Only customers, products and transactions are present as silver tables in
the current build. Earlier repository reports describe six tables in an
older build, so complaint/transcript availability cannot be inferred from
those reports. Transaction and product currencies are USD, COP and ARS;
the frontend preserves the supplied currency even for a Mexico profile.
Amounts are positive source magnitudes. Deposit, purchase and withdrawal
types support a displayed direction; transfers, payments and adjustments
retain an unknown direction instead of inventing a debit or credit leg.

The private frontend config is mounted as a single file. When chat is
enabled, a separately mounted frontend signing key and execution token
authorize requests to the existing `/v1/chat/completions` route. Customer
assertions bind the authenticated customer and conversation to each request.
The application does not expose worker administration routes to the browser.
The older specialized banking chat and conversation routes are retired in
the current FLUJO banking implementation.

Browser sessions and chat ownership bindings persist in an isolated named volume.
Customer routes support authenticated banking reads and transaction inquiries.
The container runs as an unprivileged user with a read-only root filesystem,
bounded temporary storage and dropped Linux capabilities. Private config,
source rows, signing keys and state are excluded from the build context.

## Portable container contract

| Resource | Container location | Requirement |
| --- | --- | --- |
| HTTP service | Port `8080` | HTTPS terminates at the hosting platform |
| Published dataset | `/banking-data` | Read-only `CURRENT`, manifest, gold files and silver customers/products |
| Private frontend config | `/banking-config/frontend.json` | Read-only, outside Git |
| Optional frontend signer | `/banking-config/frontend-signer.pem` | Read-only, for approved FLUJO chat |
| Application state | `/banking-state` | Persistent, writable by UID/GID 10001 |
| Health probe | `GET /healthz` | Returns status without customer identifiers |

`frontend/compose.yaml` can run standalone. `frontend/compose.flujo.yaml`
connects it to the existing external FLUJO network. Configure dataset and
secret mounts through environment variables; no developer-specific paths
are embedded in the image. Run one API replica against its SQLite state.
Scaling beyond one replica requires a shared session/state store and
appropriate dataset distribution.

For cloud hosting, use the same image and port, set an explicit HTTPS
`BANKING_PUBLIC_ORIGIN` and `BANKING_COOKIE_SECURE=1`, and supply the mounts
through the provider's secret and storage mechanisms. Production customer
authentication and verified identity mapping must replace the hackathon
profile/code sign-in before public customer use.

## Verification

The API and chat adapter passed 22 focused tests covering owner filtering,
filtering before result limits, malformed snapshot failures, opaque references,
revoked sessions, profile rebinding, invalid origins, Unicode access-code
input, bounded chat deadlines and customer-bound FLUJO assertions. The existing
worker completed three real Sol customer queries using the approved signer
and narrow profile mapping; each returned owner-matched references, and each
fresh test session was revoked successfully. These host adapter checks took
31.9–32.8 seconds per response and did not modify the worker configuration.

The complete repository Python suite passed 145 tests and 43 subtests in
223.23 seconds, including those 22 frontend API/chat tests. The remaining
acceptance-runner CI script added 7 passing tests, for 152 tests plus
43 subtests across the executed checks. Python compilation checks passed
for `banking_mcp`, `pipeline`, `demo`, `scripts` and `frontend/server`.

The final Linux Docker build passed TypeScript and Vite compilation with
the dependency lockfile. The running image is
`sha256:75052199a5218379ee8f2b0cce6ef51c512470f621a9a1a70cb95407b01041c1`
at 239,531,279 bytes. Dataset files, private configuration, signing keys and
test sources are excluded from the image. `docker compose ... up -d --build
--wait` created or updated only `hackathon-banking-frontend-1`, publishing
`127.0.0.1:43800` to port 8080. The service reported healthy and
`GET /healthz` returned `status=ok`, `dataset_ready=true`.

The final container started at `2026-09-29T15:53:22Z`. Every copied runtime
source file and generated static asset was compared byte-for-byte against
the frozen working tree: all 6 Python files, `requirements.txt` and 20 static
files matched. The combined SHA-256 manifest is
`a1ed591b29d839efc2f15f8ac00366c62d46529542f81c9a5fdbd8b447480e8e`.
The browser assets are `index-BaG6PKe_.css` and `index-Cc7q3G5f.js`.

Docker inspection confirmed the unprivileged `banking` user, read-only root
filesystem and data/config/signer mounts, an isolated writable named state
volume, and membership in the existing `flujo-slack_default` network. The
existing FLUJO worker remained healthy with its preceding ten-hour uptime;
the existing browser proxy and Slack gateway were also left running.
One resource sample showed 52 MiB frontend memory; this is a sample, not a
load-test or peak-memory claim.

Actual HTTP login/overview/logout checks returned all three configured real
profiles: Colombia had 7 products and 92 transactions in COP; Mexico had
7 products and 94 transactions in USD; Argentina had 8 products and
84 transactions in ARS. All reported the same published snapshot and an
available authenticated FLUJO chat connection. Anonymous overview returned
401 and a foreign-origin login returned 403. Test sessions were revoked at
logout.

Browser review used a 1,265-pixel desktop viewport and 390- and 320-pixel
mobile viewports. The mobile account layout was adjusted to fit the actual
large COP balances, and the narrow chart bars were sized for the 320-pixel
layout. Hidden mobile navigation is removed from the accessibility tree.
An actual browser CSV download was inspected on disk: its four exported
rows all matched the selected declined-status filter. Screenshots and
downloaded customer rows are local review artifacts and are not committed.
An actual selected-transaction request through the browser completed with a
real FLUJO reply matching the approved status, source amount and transaction
date, with no browser console errors. Reply emphasis and references render
through escaped React text rather than injected HTML.

The local deployment procedure is in [frontend/README.md](../frontend/README.md).
