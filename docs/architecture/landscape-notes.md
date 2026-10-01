# Docker and Fly deployment landscapes

Reviewed 30 September 2026. These are configuration diagrams, with data-plane
paths separated from requests, batch migration and persistent state. No customer
rows, private identities, bucket names, tokens or signing keys are included.

## Docker

1. The customer opens `http://localhost:43800`. The published port is bound to
   `127.0.0.1` and forwards to Savia's container port 8080. The browser runs the
   static frontend and calls Savia `/api/*`; it never opens Parquet or S3 itself.
2. Savia's FastAPI server authenticates the demo profile, binds the session to an
   approved customer, and uses DuckDB to query the mounted snapshot. Its joins
   require customer/product ownership and valid transaction ownership.
3. For chat, Savia calls `http://flujo:4200/v1/chat/completions` over the private
   Docker network, with an execution bearer and a short-lived Ed25519 signed user
   assertion. The logout path calls `/v1/banking/session/revoke`. Frontend signers
   and upstream credentials stay in the server. The configured worker verifies
   admission, binds the owner and pins the approved graph.
4. The restricted inquiry run calls the banking MCP as a Python **stdio child**,
   with run-bound customer authority. MCP checks customer and product ownership
   again and returns masked facts and opaque selection handles. Its ordinary
   read path is the shared read-only Parquet snapshot, not a live S3 scan.
5. When `verify_source` is requested for a selected transaction, MCP makes
   bounded, ETag-pinned S3 HEAD/GET reads of the relevant source objects. This
   verification does not refresh or publish a new snapshot and does not write S3.
6. Savia, FLUJO and MCP each have separate writable state volumes. The shared
   dataset and private config/signers are read-only host binds. FLUJO :4200 and
   its :4201 sandbox have no published host ports.
7. Other local access paths: the operator opens `http://localhost:43420` through
   the UI proxy; Slack reaches a separate Socket Mode gateway that shares the
   worker's network namespace and uses `127.0.0.1:4200`. This Slack path has its
   own service credentials and is not a substitute for customer banking identity.
   The synthetic-only preview at `localhost:43801` is a separate deployment and
   is outside this real-snapshot diagram.

**Docker status:** the deployment README records that the captured source
worker's compiled banking adapter was missing, so its customer banking chat and
revocation could fail authentication. The arrows describe configured paths;
they do not assert that this image completes them successfully.

## Fly

1. The user opens `https://flujo-factored-2026.fly.dev`. Fly edge terminates
   HTTPS and forwards to gateway 8080, the only public service listener. The
   gateway's outer demo login issues a Secure, HttpOnly, SameSite=Strict cookie.
   The inner Savia demo/profile login remains required as configured.
2. The gateway proxies customer traffic only to Savia at `127.0.0.1:8082`.
   Savia serves the frontend assets and APIs, reads the same logical snapshot,
   and sends signed customer chat to FLUJO at `127.0.0.1:4200`. The worker's
   :4201 sandbox and the stdio banking MCP remain private.
3. Gateway, Savia and FLUJO run in the **same Machine**, supervised together.
   Runtime services run as UID 1000. This is process separation and loopback
   networking, rather than separate Fly apps or a 6PN service network.
4. The mounted encrypted 10 GB volume `/data` holds the published dataset,
   frontend state, FLUJO configuration and new conversations, banking authority
   state, and real/synthetic MCP state. `/banking-data` aliases
   `/data/banking-data`; `/banking-state` aliases `/data/banking-state`.
5. Initial migration packages current gold, silver customer/product masters,
   manifests, approved configuration, signers, runtime dependencies and
   consistent bank SQLite backups. Bronze and historical builds stay local.
   Imported conversations/browser sessions start empty; new state then persists.
6. Root bootstrap validates the migration marker and approved policy hash,
   publishes private runtime config into protected `/run` files, seals the
   dataset read-only to application services, and drops runtime services to
   UID 1000. Private migration data and credentials do not enter the image.
7. S3 verification and the external model-provider calls are outbound paths.
   The provider receives the inquiry and minimized facts, not AWS credentials
   or a direct dataset API. All bank tools are read-only and bank actions remain
   disabled. No recurring Fly ETL or automatic dataset refresh is configured.
8. The local Slack deployment continues independently after the Fly migration.
   Fly's health endpoint probes Savia dataset readiness and authenticated worker
   readiness; a healthy probe alone does not verify a complete customer inquiry.

**Fly status:** the deployment README records the corrected banking-adapter
image as deployed, with customer inquiry, logout revocation and exact-session
ledger acceptance still pending. This documentation task did not run those live
checks or change either deployment. The first uncorrected migration image had
the same adapter omission as the captured Docker source.

## Scope and sources

Docker means the existing local multi-container deployment. The file
`deploy/fly/Dockerfile` is additionally a **local combined-image build option for
Fly**; it is not the topology of the running local Docker stack. Fly's canonical
remote build uses `Dockerfile.remote`, with `Dockerfile.bank-enabled` adding the
banking adapter repair.

The S3 origin is drawn twice in each SVG to keep arrows legible: left for offline
ingestion, right for an optional runtime source check. It is the same source.
DuckDB runs inside the pipeline and each serving reader; it is not a network
database. Persistence arrows cover application state, not writes to source data.

Evidence:

- `pipeline/README.md`, `pipeline/common.py`, `pipeline/lookup.py`: pipeline,
  snapshot publication and ownership filtering.
- `deploy/fly/fly.toml`, `runtime.mjs`, `gateway.mjs`, `capture-docker.mjs`,
  `README.md`: Fly boundaries, loopback ports, migrations, persistence and status.
- Running Docker port/network/mount metadata for
  `hackathon-banking-frontend-1` and `flujo-slack-flujo-1`.
- Frontend source in the running image: `server/app.py`, `server/repository.py`,
  `server/chat.py`; banking image source: `banking_mcp/server.py`,
  `banking_mcp/service.py`, `banking_mcp/repository.py`.
- Local frontend Compose files in the `banking-frontend` worktree and the sibling
  `flujo-slack-bot/compose.yaml`, `src/ui.js`, `README.md`.
- Only allowlisted non-secret fields were inspected from private runtime configs.
  Planning documents with earlier direct-S3 proposals were not treated as the
  deployed serving topology.

## Files

- `docker-landscape.svg`, `fly-landscape.svg`: editable vector diagrams.
- `docker-landscape.png`, `fly-landscape.png`: rendered image previews.
- `deployment-landscapes.pdf`: two landscape vector pages for sharing.
- `deployment-landscapes.html`: self-contained viewer, zoom and descriptions.
- `build-landscapes.py`: regenerates SVGs, viewer and these notes. PNG/PDF exports
  use a local browser render of the SVGs.
