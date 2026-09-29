# Online banking frontend

A customer banking portal built with React and Vite, served together with a
FastAPI data API. Balances, products and transactions come from Carlos's
published silver and customer-sharded gold Parquet snapshot. Demo names are aliases.

## Run beside the existing FLUJO worker

Run the following in this `frontend/` directory. Use absolute paths to the
existing dataset and private configuration; neither is copied into the image.
The configuration includes the approved profile mappings and optional FLUJO
chat credentials. Never commit it.

```powershell
$env:BANKING_DATA_DIR = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/data'
$env:BANKING_CONFIG_FILE = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-frontend/frontend.json'
$env:BANKING_SIGNER_FILE = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-mcp/frontend-signer.pem'
docker compose -f compose.yaml -f compose.flujo.yaml up -d --build --wait
```

Open [the banking portal](http://localhost:43800). The optional network override
joins `flujo-slack_default`; the existing worker continues running separately.
Only the new frontend service is created or updated. Use the configured demo
access code at sign-in.

```powershell
docker compose -f compose.yaml -f compose.flujo.yaml ps
Invoke-RestMethod http://localhost:43800/healthz
docker compose -f compose.yaml -f compose.flujo.yaml logs --tail 50 frontend
```

Changing a private configuration file requires restarting the frontend. Update
the image with the same `up -d --build --wait` command. To stop the frontend,
use `docker compose -f compose.yaml -f compose.flujo.yaml down`; the named state
volume is retained. Do not add `--volumes` unless its saved sessions and chat bindings
are intentionally disposable.

## Standalone deployment

Use `compose.yaml` by itself when FLUJO chat is not configured. Copy
`config.example.json` to a private path and set `BANKING_CONFIG_FILE` to that
copy. The API can select real demo customers from the mounted snapshot when
no explicit `profiles` mapping is configured.

The Docker image listens on `0.0.0.0:8080` and has no Docker or host-path
dependency. It can run on Fly, GCP or Azure behind HTTPS. Provide the published
dataset tree at `/banking-data` read-only, the private config at
`/banking-config/frontend.json`, and persistent writable state at `/banking-state`.
The dataset tree must include `CURRENT`, `builds/<CURRENT>/snapshot.json`, all
manifest-listed gold files, and silver `customers.parquet` and `products.parquet`.
The API does not need the bronze download or S3 credentials.
FLUJO chat additionally requires a private upstream URL, execution credential
and frontend signing key with matching worker policy.

Set `BANKING_PUBLIC_ORIGIN` to the HTTPS public origin and
`BANKING_COOKIE_SECURE=1`. If changing the local port, set `BANKING_PORT` and
`BANKING_PUBLIC_ORIGIN` together. The local Compose file deliberately publishes
only on loopback; the cloud platform should route HTTPS to port 8080 directly.

The sign-in flow is a hackathon demo using approved customer mappings and a
shared code. Before public customer access, replace it with a trusted identity
provider and server-side verified customer ownership. Demo aliases, organizer
data must stay clearly labeled. The portal serves read-only banking inquiries.
Snapshot
timestamps establish dataset lineage, not live-bank synchronization.

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
