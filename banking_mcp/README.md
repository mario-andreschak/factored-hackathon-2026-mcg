# Banking MCP

Carlos's PRs #1 and #2 provide the data pipeline and lookup library. This package
adds the MCP server FLUJO can connect to. It serves the pipeline's validated,
customer-sharded Parquet snapshot and can read a selected transaction back from S3.
It is read-only: no dispute submission, refunds or bank mutations.

## Available in local FLUJO

At `http://127.0.0.1:43420/`, both registrations are connected:

| Registration | Dataset | Usable now |
| --- | --- | --- |
| **Banking MCP Demo** | Explicit synthetic fixture, one fixed demo customer | Build graphical flows and call all three tools. S3 verification is unavailable. |
| **Banking MCP** | Real bucket's derived snapshot, 4,425,008 transactions | Discover tools and check status. Customer reads require a signed assertion on each tool call. |

The real service intentionally rejects ordinary FLUJO customer calls today. The
remaining integration is the trusted FLUJO runtime signer described below. The
local test signer proves the MCP contract; it does not authenticate frontend users.

FLUJO and both MCP services run **inside the same Docker Desktop Linux VM**, in
separate Linux containers on FLUJO's private Docker network. The MCP runs Python
inside its container; it never launches a Windows Python executable. They are reachable
from FLUJO at `http://banking-mcp:8000/mcp` and
`http://banking-mcp-demo:8000/mcp`, and from the host on loopback ports 43421/43422.
Each uses its own service bearer and persistent SQLite state volume. The demo
container has no real dataset or S3 credential mount. Configuration and keys live
under the ignored `private/banking-mcp/` directory in the main checkout.

```text
Docker Desktop Linux VM
  FLUJO container  →  banking-mcp container (real data, signed authority)
                  →  banking-mcp-demo container (synthetic data only)
```

The dataset/config files are read-only bind mounts into these containers. Writable
replay/reference state lives in Docker volumes. Separate containers keep real S3
credentials and raw customer data outside FLUJO's general tool runtime.

## Tools

| Tool | Business arguments | Result |
| --- | --- | --- |
| `banking_status` | None | Readiness and mode, without customer information |
| `list_my_transactions` | Optional `start_date`, `end_date`, `limit` (1–20), `cursor` | Masked transaction facts and opaque selection handles |
| `get_my_transaction` | `selection_handle`, optional `verify_source` | One previously selected transaction; optional conditional S3 read-back |

Dates filter **process_date**, with at most 31 inclusive dates. Defaults use the
latest 31 days present in the historical source, not the current calendar month.
Pagination sorts by transaction timestamp and ID. Cursors keep the same window;
repeat explicit dates when paging a custom window.

Customer, product and transaction IDs, fraud labels, S3 keys, credentials and
lineage fields never appear in tool schemas or results. Handles and cursors expire
after 15 minutes and are bound to the verified subject, customer, session,
conversation and immutable build. A new build invalidates old references. Merchant
text remains untrusted data; models must not follow instructions inside it.

## How customer isolation works

1. The authenticated frontend sends a message to FLUJO. Its backend verifies the
   session and resolves the user's authorized customer. URL parameters, model
   arguments, conversation IDs and `@` substitutions are not authentication.
2. FLUJO creates trusted run context outside prompts, graph variables and
   user-controlled metadata. Conversation ownership and the allowed graph revision
   must be checked before execution.
3. Immediately before **each** banking call, the trusted runtime signs the exact
   tool name and business arguments. It attaches the assertion to MCP
   `tools/call.params._meta["com.flujo.bank/assertion"]`. A retry gets a new assertion.
4. The MCP verifies the signature, audience, tool, argument hash, expiry, replay
   state and session revocation. It resolves the subject through its private mapping,
   then checks customer/product ownership while querying the customer bucket.
5. Before returning a read, it checks expiry and revocation again. Missing or invalid
   authority returns an error, with no customer read.

The shared HTTP bearer only authenticates the FLUJO service. It never selects a
customer. Static headers/env-vars or a shared conversation ID cannot replace the
per-call assertion. Synthetic mode bypasses customer assertions only for a marked,
fixed-customer fixture and explicitly labels every customer result `synthetic:true`.

See [the FLUJO integration design](../docs/FLUJO_BANKING_RUN_AUTH.md) for the remaining
ingress, run-context and tool-dispatch work. Signing keys must stay outside FLUJO
graph configuration, user metadata, the model and ordinary tool parameters. Strip
incoming assertions and mint fresh ones from verified server context. Reject
client-supplied run authority. Do not log assertions or expose them through tracing.

### Assertion contract

Use Ed25519/`EdDSA`, an allowlisted `kid`, and JWT `typ:bank-mcp+jwt`.
The header accepts exactly `alg`, `kid`, `typ`; no remote key URLs.

Required claims:

```text
iss: configured trusted runtime issuer
aud: banking-mcp (exact string)
sub: verified auth subject, mapped privately to a dataset customer
iat, nbf, exp: integer seconds; nbf == iat; lifetime <= 60 seconds
jti: new random unique ID for every attempted call
session_id, conversation_id, run_id, graph_revision: trusted runtime context
tool: exact called banking tool name
scope: ["bank:read"]
args_sha256: hex SHA-256 of RFC 8785 canonical JSON of the raw business arguments
```

The MCP trusts the configured signer to verify session, conversation, run and graph
ownership. It does not query a FLUJO run registry itself. Revocation is currently an
operator `StateStore.revoke(session_id)` operation; frontend logout/revocation
propagation still needs the runtime integration. Deploy one instance with its
persistent state volume; multiple replicas require shared replay/revocation/reference
storage before they can safely serve interchangeable requests.

## S3 and snapshot freshness

Build the pipeline with this branch's code. It writes private source lineage into
gold and copies `source_objects.json` into the same immutable build before updating
`CURRENT`. Older builds lacking these fields must be rebuilt using cached bronze:

```powershell
python -m pipeline run --stage silver gold --tables customers products transactions --out data --reports data/pipeline-reports
```

Normal MCP reads use Parquet. `verify_source:true` checks customer/product source
ETags and fetches only the selected date's allowlisted transaction CSV with S3
`If-Match`. It enforces an 8 MiB object cap and rechecks the selected transaction's
owners and returned banking facts. A changed or unavailable object fails safely.
No caller can choose a bucket, key, URL or transaction ID.

`verified_against_pinned_source` means that selected row still matches the pinned
objects. It does **not** mean all late-arriving objects have been discovered or that
the dataset is current. Refreshes use the pipeline and atomically publish a new build.
None of these tools authorizes a bank action.

## Run locally

```powershell
python -m pip install -r requirements-mcp.txt
python -m banking_mcp demo --out data/banking-demo --config private/banking-mcp/demo.json
python -m banking_mcp serve --config private/banking-mcp/demo.json
```

The demo command refuses to overwrite an existing published dataset. To use real
data, copy `config.example.json` into `private/`, fill the private subject mapping,
public verification key and a randomly generated service token of at least 32
characters. Use absolute host paths for native Python. Keep the private signer in
the trusted runtime, separate from the MCP. The MCP gets only the public key.

HTTP binds to loopback by default. Every HTTP request needs the service bearer.
Hostnames are allowlisted and browser origins restricted to local origins. For
Docker, explicitly bind `0.0.0.0`, allow the internal hostname and publish only to
loopback. For a deployment beyond the local machine, put TLS and authenticated
network access in front of the endpoint.

Build the image with `docker build -f Dockerfile.banking-mcp -t factored-hackathon/banking-mcp:local .`.
Mount the dataset and config read-only, mount a writable `/state` volume, and mount
S3 credentials only for the real service. The Docker config uses `/dataset`,
`/state/banking.db`, `/run/secrets/banking.json` and `/run/secrets/source.env`. Run
as the image's non-root user, with a read-only root, `/tmp` tmpfs, dropped
capabilities and `no-new-privileges`. The image build context excludes private data
and credentials. Local container names are `hackathon-banking-mcp` and
`hackathon-banking-mcp-demo`; both restart with Docker.

### Register in FLUJO

For FLUJO running in Docker:

```powershell
python scripts/connect_banking_mcp.py --name "Banking MCP" --config private/banking-mcp/real-docker.json --server-url http://banking-mcp:8000/mcp
python scripts/connect_banking_mcp.py --name "Banking MCP Demo" --config private/banking-mcp/demo-docker.json --server-url http://banking-mcp-demo:8000/mcp
```

For native FLUJO/Python, omit `--server-url` and pass `--python` with the local
Python executable to use stdio. Registration saves the HTTP bearer as a secret
header, with apps, skills, sampling and proxy exposure disabled. The server advertises
only synchronous tools: no prompts, customer resources, tasks, callbacks or SSE GET
streams.

## Verification and capacity

Run `python -m pytest -q tests/test_banking_mcp.py tests/test_pipeline.py`.
Tests cover argument tampering, forged/expired/replayed assertions, revocation during
reads, private handles/cursors, restart persistence, owner rechecks, changed snapshots,
HTTP service/host/origin checks, conditional S3 verification and 500 interleaved
synthetic reads. See [local integration evidence](../docs/BANKING_MCP_IMPLEMENTATION.md).

Eight active reads and 512 queued reads bound the work. Overflow returns `server_busy`.
Queued requests cannot outlive their signed authority. This bounds resource usage;
it is not a promise of equal latency at 500 customers. The remaining acceptance test
must use 500 authenticated frontend customers through FLUJO, with the real signer,
default 20-row pages, retries and provider calls. Measure p95/p99 and scale the query
service and shared state based on that result.
