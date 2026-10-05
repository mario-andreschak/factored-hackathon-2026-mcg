# Online banking frontend

> Historical organizer-snapshot portal and deployment review, primarily September
> 29. The source/runtime claims below keep that scope. The separate final-day
> [fictional local RC](../deploy/rc/README.md) uses fresh fixtures and an in-process
> banking service; see the [release report](submission/RELEASE_CANDIDATE.md) for
> current measured behavior and hosted-runtime identity.

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

The snapshot has two date bases. For 1,106,307 of its 4,425,008 transactions,
the calendar day of `transaction_date` is one day after `process_date`.
The latest processing date is June 17, 2026, while the latest event timestamp
is June 18, 2026. The portal list and month views use the event timestamp;
CSV export includes both dates. Banking MCP `list_my_transactions` applies
its start/end window to `process_date`. Selected-transaction chat context
carries both dates so a June 18 event processed on June 17 is not treated
as a conflicting record.

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
Completed public chat exchanges and validated transaction summaries persist there
as well. `GET /api/chat/history` restores only the authenticated session's ordered
user/assistant messages; worker conversation IDs, tools, credentials and server-added
prompt facts are excluded. Closing the dialog keeps its request alive, and page
refresh polls an admitted query's active status without resending it. Logout and
expiry prevent history access. A one-time migration clears legacy conversation
bindings that had no displayable transcript; subsequent restarts preserve the
paired transcript and conversation binding atomically. Restored history is bounded
to recent exchanges, with a visible disclosure when limited.

Transaction API pages contain at most 500 rows and expose offsets, matching counts
and `next_offset`. They list only a `period` window (`week`, `month` or the
default and maximum `quarter`: 7, 30 or 90 days ending on the latest published
event), applied in the scan before materializing the customer's rows. Filtering
occurs before pagination. The browser loads all pages of the selected window
and verifies the build ID, fingerprint, unique references and full owned count
before allowing local filters or CSV export. Inconsistent or incomplete history
fails closed. Selected transaction references resolve over the complete
ownership-checked gold relation independently of a display page.
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

The API and chat adapter passed 34 focused tests covering owner filtering,
filtering before result limits, malformed snapshot failures, opaque references,
revoked sessions, profile rebinding, invalid origins, Unicode access-code
input, bounded chat deadlines, complete history paging, older selected transactions,
durable transcript restoration, atomic writes and customer-bound FLUJO assertions. The existing
worker completed three real Sol customer queries using the approved signer
and narrow profile mapping; each returned owner-matched references, and each
fresh test session was revoked successfully. These host adapter checks took
31.9–32.8 seconds per response and did not modify the worker configuration.

The complete repository Python suite passed 157 tests and 43 subtests in
79.34 seconds, including those 34 frontend API/chat/history tests. The remaining
acceptance-runner CI script added 7 passing tests, for 164 tests plus
43 subtests across the executed checks. Python compilation checks passed
for `banking_mcp`, `pipeline`, `demo`, `scripts` and `frontend/server`.
After the date-basis correction, all 15 focused frontend API tests passed,
including selected next-day event context and owner checks. Prettier and the
TypeScript/Vite production build passed again.

The final Linux Docker build passed TypeScript and Vite compilation with
the dependency lockfile. The running image is
`sha256:5a638e66991b473ced00e5863bc6fc0b2e417fb031a3c7fd562395ea929a97c8`
at 239,542,683 bytes. Dataset files, private configuration, signing keys and
test sources are excluded from the image. `docker compose ... up -d --build
--wait` created or updated only `hackathon-banking-frontend-1`, publishing
`127.0.0.1:43800` to port 8080. The service reported healthy and
`GET /healthz` returned `status=ok`, `dataset_ready=true`.

The current image started at `2026-09-29T17:38:01Z`. Every copied runtime
source file and generated static asset was compared byte-for-byte against
the frozen working tree: all 6 Python files, `requirements.txt` and 20 static
files matched. The combined SHA-256 manifest is
`5c922ade080b471fffe859d886e11938dc6c0e7e6ee58151acecea5a24b1879a`.
The browser assets are `index-Cxk_VqUk.css` and `index-B1P03VjK.js`.

Docker inspection confirmed the unprivileged `banking` user, read-only root
filesystem and data/config/signer mounts, an isolated writable named state
volume, and membership in the existing `flujo-slack_default` network. The
frontend deployment did not recreate the existing FLUJO worker, browser proxy
or Slack gateway. Docker Desktop then stopped responding during live verification;
starting the installed app restored the existing containers. The frontend and
worker reported healthy after recovery at `2026-09-29T16:22:09Z`; the proxy and
gateway were running on their existing images. Dataset `CURRENT` stayed unchanged.
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

The rebuilt browser displayed both dates for a real Valentina movement:
June 2, 2026 at 02:48 as the movement date and June 1, 2026 as its
processing date. This verifies the visible date distinction; the selected
next-day chat payload was verified by the focused API test.

The review regressions also ran in a native browser against an isolated synthetic
604-row history. Search found an older purchase absent from the first 500 API rows;
its selected inquiry succeeded, and an actual CSV download contained all 604 rows,
including that purchase. Closing during a query preserved its message and busy
state. Refresh restored completed exchanges and their selected transaction, and a
follow-up reused the same upstream conversation. A different profile after logout
had an empty transcript. API tests additionally traverse 1,604 owned rows with
equal timestamps and reject foreign, false-ownership and forged-product selections.

On the corrected real deployment, a customer inquiry survived dialog closing and
page refresh while FLUJO was still processing it. The restored UI disabled sends,
polled the admitted query, then displayed the ordered exchange and validated
transaction summary. A follow-up without reselecting the transaction confirmed its
actual amount and processing date. The restored dialog also fit a 320-pixel mobile
viewport without horizontal overflow. Independent source review found no material
remaining issue in these two fixes.

The local deployment procedure is in [frontend/README.md](../frontend/README.md).
