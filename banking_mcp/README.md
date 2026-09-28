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

Banking MCP runs as a **stdio child process inside the existing FLUJO container**.
FLUJO launches `/opt/banking-mcp/.venv/bin/python`; stdin/stdout carry MCP messages.
There is no separate Banking MCP container, remote MCP URL, or banking server port.

```text
Existing FLUJO container
  FLUJO -> Python Banking MCP (stdio)
        -> Python synthetic demo MCP (stdio)
```

Code and dependencies are installed in the worker image. Dataset, credentials and
private configuration are read-only mounts. Replay, revocation and reference records
live on durable writable volumes. The synthetic process uses its marked fixture and
separate state. Private files remain in ignored `private/`. The banking flow cannot
advertise shell, filesystem or generic S3 tools.

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

The local stdio transport does not select a customer. Static headers/env-vars or a shared conversation ID cannot replace the
per-call assertion. Synthetic mode bypasses customer assertions only for a marked,
fixed-customer fixture and explicitly labels every customer result `synthetic:true`.

See [the FLUJO integration design](../docs/FLUJO_BANKING_RUN_AUTH.md) for
ingress, run-context and tool-dispatch requirements. Signing keys must stay outside FLUJO
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
ownership. It does not query a FLUJO run registry itself. Frontend logout first
revokes FLUJO's durable session, then passes a separately typed `bank-revoke+jwt`
assertion over stdin to the fixed local `revoke-session --config <private-file>`
command. It is not an MCP tool. Authority never appears in argv or environment.
The MCP independently verifies the assertion and revokes its shared SQLite session;
existing processes consult that store before returning reads. Multiple FLUJO replicas
need shared fenced identity, replay and reference storage.

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

### Install inside the existing FLUJO worker

`Dockerfile.flujo-banking` extends the existing worker image and inherits FLUJO's
startup command. Build with `--build-arg FLUJO_IMAGE=<existing-worker-image>`.
Update the existing worker service to that image; do not start another FLUJO instance.
Mount the dataset at `/banking-data`, config at `/run/banking/bank-config.json`,
source credentials at `/run/banking/source.env`, and durable state at `/banking-state`.
Private config paths must match these Linux mounts. Run as FLUJO's existing `node`
user; the state volume must be writable by that user. A separate demo config points
only to `/banking-data/banking-demo` and its own writable state volume.

The default `serve` transport is stdio. HTTP remains an optional standalone transport;
it is not used by this FLUJO deployment. `Dockerfile.banking-mcp` is an optional
standalone server image, not the worker installation path.

### Register in FLUJO

For the existing Linux FLUJO container, after installing code and mounts:

```powershell
python scripts/connect_banking_mcp.py --name "Banking MCP" --config private/banking-mcp/real-stdio.json --runtime-stdio
python scripts/connect_banking_mcp.py --name "Banking MCP Demo" --config private/banking-mcp/demo-stdio.json --runtime-stdio --runtime-config /run/banking/demo-config.json
```

For native FLUJO/Python, omit `--runtime-stdio` and pass `--python` with the local
Python executable. Registration uses stdio and empty env, and disables apps, skills,
sampling, elicitation and proxy exposure. The server advertises
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
