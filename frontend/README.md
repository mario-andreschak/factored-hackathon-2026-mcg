# Online banking frontend

A customer banking portal built with React and Vite, served together with a
FastAPI data API. When configured for the private organizer-data demo, balances,
products and transactions come from Carlos's published silver and
customer-sharded gold Parquet snapshot; names are fictional aliases. The isolated
synthetic invitation preview below uses only generated fictional data.

The direct MCP source candidate is documented in [DIRECT_MCP.md](DIRECT_MCP.md).
Bank authority now belongs to this host; FLUJO provides bounded generic language
guidance. Legacy worker-bound state requires explicit reconciliation and isolated
state. A joined direct-host/MCP service image has not been built or deployed;
local Vite builds and the fictional frontend preview do not establish that runtime.

The transaction dispute workflow has a separate native workflow and private
configuration. See [workflow setup and qualification](../docs/DISPUTE_IMPLEMENTATION.md)
for its matched frontend/bank mappings, independent ledger, and approved
continuity settings. The direct-MCP example below configures the default service.

Movements show at most the last three months. `GET /api/overview` and
`GET /api/transactions` take `period=week|month|quarter` (7, 30 or 90 days,
default `quarter`), counted back from the latest published event, so the window
advances as daily data arrives and older rows are never read into the portal.
Home's monthly activity always covers the three-month window. The browser loads
every owned page of the selected window before exposing local search, filters or
CSV export. Each API page is limited to 500 rows; offsets and snapshot checks
prevent a transaction from silently disappearing. Selected chat references and
the dispute workflow still resolve against the complete ownership-checked history.

Movement dates and month views use the transaction event timestamp; CSV exports
include both event and processing dates.
The banking MCP filters its list start/end dates by transaction event date. In the
published snapshot, 1,106,307 of 4,425,008 events fall on the next calendar
day; the latest processing date is June 17, 2026, while the latest event is
June 18, 2026. Transaction details and exports include both dates; generic
language receives only the selected event date.

Closing the assistant preserves its messages and any running query. Completed
public exchanges are stored in the application state volume and restored after
page refresh or container restart. Refreshing during a query polls its status
without resubmitting it. History is bound to the authenticated customer session;
logout or a new login never restores another session's messages. Restored history
can show only recent exchanges, with an explicit notice when limited.

When direct host chat is configured, logout records local denial and a durable
bank MCP revocation intent before clearing the browser session. Fresh signed
revocations use the private bank transport, never generic completions. Health
reports aggregate delivery counts; queued intents do not establish acknowledgement.
See [DIRECT_MCP.md](DIRECT_MCP.md) for exact action, signing, replay and state rules.
Legacy worker-owned volumes are refused, never automatically transplanted.

## Run beside the existing FLUJO worker

Run the following in this `frontend/` directory. Use absolute paths to the
existing dataset and private configuration; neither is copied into the image.
The configuration includes approved profile mappings and optional direct bank
host/generic language credentials. Never commit it. Use
`direct-mcp.config.example.json` for the new architecture; its placeholders require
reviewed private bindings. Migration runtime is held until integration and provider
isolation review are complete. The commands below describe later operation.

```powershell
$env:BANKING_DATA_DIR = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/data'
$env:BANKING_CONFIG_FILE = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-frontend/frontend.json'
$env:BANKING_SIGNER_FILE = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-mcp/frontend-signer.pem'
$env:BANKING_CA_FILE = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-mcp/bank-ca.pem'
docker compose -f compose.yaml -f compose.flujo.yaml up -d --build --wait
```

Open [the banking portal](http://localhost:43800). The optional network override
joins `flujo-slack_default`; the existing worker continues running separately.
Only the new frontend service is created or updated. Use the configured demo
access code at sign-in. The code must be set in the private configuration; the
image and example file provide no working default or sign-in hint.

```powershell
docker compose -f compose.yaml -f compose.flujo.yaml ps
Invoke-RestMethod http://localhost:43800/healthz
docker compose -f compose.yaml -f compose.flujo.yaml logs --tail 50 frontend
```

Changing a private configuration file requires restarting the frontend. Update
the image with the same `up -d --build --wait` command. To stop the frontend,
use `docker compose -f compose.yaml -f compose.flujo.yaml down`; the named state
volume is retained. Do not add `--volumes` unless its saved sessions, chat bindings and transcripts
are intentionally disposable.

## Isolated synthetic invitation preview

This standalone preview uses only repository-generated fictional data. Run it
as your host user on loopback port 43801, with a separate private state
directory. It does not start Docker, FLUJO, MCP, a model, or a banking action.
Keep the generated files restricted to that host user; the Compose image runs
as a different UID and cannot directly read them on POSIX. Use a fresh output path
for each run. The helper refuses a nonempty target and never replaces a
previous preview. These commands apply to this checkout; recheck the helper and
setup after integrating a different source revision.

From the repository root, run these POSIX shell commands:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-pipeline.txt -r frontend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
umask 077
preview="$(mktemp -d "${TMPDIR:-/tmp}/savia-synthetic-preview.XXXXXX")"
.venv/bin/python -m pipeline.prepare_release_preview "$preview"
mkdir -m 700 "$preview/state"
cd frontend
export BANKING_DATA_DIR="$preview/snapshot"
export BANKING_CONFIG_FILE="$preview/secrets/frontend.json"
export BANKING_STATE_DIR="$preview/state"
export BANKING_PUBLIC_ORIGIN=http://localhost:43801
../.venv/bin/python -m uvicorn server.app:app --host 127.0.0.1 --port 43801
```

From the repository root, run these Windows PowerShell commands. The ACL
command removes inherited access and grants the current Windows user full
control before preparation. A bounded Windows check inspected generated DACLs;
it did not test effective access from another account:

```powershell
python -m venv .venv
$py = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $py -m pip install -r requirements-pipeline.txt -r frontend/requirements.txt
npm --prefix frontend ci
npm --prefix frontend run build
$preview = Join-Path $env:TEMP ("savia-synthetic-preview-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $preview | Out-Null
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
& icacls $preview /inheritance:r /grant:r "${identity}:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not make preview directory private" }
& $py -m pipeline.prepare_release_preview $preview
$state = Join-Path $preview 'state'
New-Item -ItemType Directory -Path $state | Out-Null
Set-Location frontend
$env:BANKING_DATA_DIR = Join-Path $preview 'snapshot'
$env:BANKING_CONFIG_FILE = Join-Path $preview 'secrets/frontend.json'
$env:BANKING_STATE_DIR = $state
$env:BANKING_PUBLIC_ORIGIN = 'http://localhost:43801'
& $py -m uvicorn server.app:app --host 127.0.0.1 --port 43801
```

The helper prints the private configuration and invitation-code file paths,
never the codes. Keep both files outside tracked source and do not publish
them. Stop the local server with Ctrl+C. Use the same browser host as the
configured origin, [http://localhost:43801](http://localhost:43801); binding
to 127.0.0.1 keeps the service local. Check
[http://localhost:43801/healthz](http://localhost:43801/healthz) for
`dataset_ready: true` before signing in.

The generated source has three fictional customers, six products, and 63
ownership-valid transactions. The stamp checks every published source object
against the exact generated fixture before writing a separate provenance marker.
The pipeline's `source_validation` still describes local inventory stability;
it is not an S3 or organizer-data assertion. The private `frontend.json` binds
each random invitation digest to one explicit fictional customer. Plaintext
invitations appear only in the separate `secrets/invite-codes.json`; never
commit or publish either file.

Open [the synthetic preview](http://localhost:43801) and use one invitation
from the private codes file. The login page offers no customer selector; the
server derives the one allowed persona from the invitation. This standalone,
read-only data preview has no attached FLUJO worker, model or banking action.
Charge review shows owned fictional facts and marks assisted review unavailable;
it does not establish a verified case handoff. The direct-host/MCP source
candidate needs an isolated host, private transport and generic guidance flow
qualified together. Historical worker-ingress action proof does not validate
that candidate.
Invite mode refuses to start if its state directory contains any earlier chat
sessions or transcripts, including expired ones.
External candidate configurations require an exact HTTPS origin, Secure
cookies, a separately isolated state volume, and private ingress controls,
including per-visitor request limiting at the trusted edge. Invite tokens use
256 random bits; the app does not apply a shared proxy-IP lockout to invite
attempts.
Do not expose the organizer snapshot through this preview.

## Standalone deployment

Use `compose.yaml` by itself when FLUJO chat is not configured. Copy
`config.example.json` to a private path, set a private `demo_code`, and set
`BANKING_CONFIG_FILE` to that copy. Local demo mode can select customers from
the mounted snapshot when no explicit `profiles` mapping is configured.

The Docker image listens on `0.0.0.0:8080` and has no Docker or host-path
dependency. It can run on Fly, GCP or Azure behind HTTPS. Provide the published
dataset tree at `/banking-data` read-only, the private config at
`/banking-config/frontend.json`, and persistent writable state at `/banking-state`.
The dataset tree must include `CURRENT`, `builds/<CURRENT>/snapshot.json`, all
manifest-listed gold files, and silver `customers.parquet` and `products.parquet`.
The API does not need the bronze download or S3 credentials.
Direct assisted review requires the private MCP transport, approved bank host
signer/principal mapping and separate generic language credential/flow. Bank
assertions are never sent to the worker. See [DIRECT_MCP.md](DIRECT_MCP.md).

Set `BANKING_PUBLIC_ORIGIN` to the HTTPS public origin and
`BANKING_COOKIE_SECURE=1`. If changing the local port, set `BANKING_PORT` and
`BANKING_PUBLIC_ORIGIN` together. The local Compose file deliberately publishes
only on loopback; the cloud platform should route HTTPS to port 8080 directly.

The local organizer-data sign-in uses approved customer mappings and a shared
private demo code. Invite mode instead binds each high-entropy code to one
synthetic persona on the server. It is still a fictional prototype, not a
trusted banking identity provider. Real customer access requires verified
identity and account ownership. Organizer data must stay clearly labeled and
private until its external-use rights are settled. The portal currently serves
read-only banking inquiries.
Snapshot
timestamps establish dataset lineage, not live-bank synchronization.

The direct host migration refuses any legacy worker-bound chat, action, transcript
or revocation rows before mutation. Preserve and reconcile the old authority/state
explicitly, then use isolated state. Direct-host restarts preserve the independent
bank context and generic language conversation.

## Local development

```powershell
npm ci
npm run dev
```

For the API, install `requirements.txt`, set `BANKING_DATA_DIR`,
`BANKING_CONFIG_FILE` and `BANKING_STATE_DIR` to local paths, then run
`python -m uvicorn server.app:app --host 127.0.0.1 --port 8080` from this directory.
Vite proxies `/api` to port 8080. Check `/healthz` on the API port directly.
Set `BANKING_PUBLIC_ORIGIN` to
the Vite URL while developing. Build with `npm run build`.

See [architecture, dataset lineage and deployment evidence](../docs/ONLINE_BANKING_FRONTEND.md).
