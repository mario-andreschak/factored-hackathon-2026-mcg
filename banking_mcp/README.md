# Banking MCP

Carlos's PRs #1 and #2 provide the data pipeline and lookup library. This package
adds the MCP server FLUJO can connect to. It serves the pipeline's validated,
customer-sharded Parquet snapshot and can read a selected transaction back from S3.
It is read-only: no dispute submission, refunds or bank mutations.

## Available in local FLUJO

At `http://127.0.0.1:43420/`, these registrations are connected:

| Registration | Dataset | Usable now |
| --- | --- | --- |
| **Banking MCP Demo** | Explicit synthetic fixture, one fixed demo customer | Build graphical flows and call all three tools. S3 verification is unavailable. |
| **Banking MCP Operator** | Private allowlist of approved dataset customers | Request an approved customer through existing chat or the Slack bridge, using the permanent Banking Operator flow. |
| **Banking MCP** | Real bucket's derived snapshot, 4,425,008 transactions | Protected FLUJO flow reads work with verified per-call identity; ordinary tool testers cannot supply customer authority. |

Banking MCP runs as a **stdio child process inside the existing FLUJO container**.
FLUJO launches `/opt/banking-mcp/.venv/bin/python`; stdin/stdout carry MCP messages.
There is no separate Banking MCP container, remote MCP URL, or banking server port.

```text
Existing FLUJO container
  FLUJO -> Python Banking MCP (stdio)
        -> Python operator banking MCP (stdio)
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
| `list_my_transactions` | Optional `customer_id`, `conversation_id`, `start_date`, `end_date`, `limit` (1–20), `cursor` | Masked transaction facts and opaque selection handles |
| `get_my_transaction` | `selection_handle`, optional `customer_id`, `conversation_id`, `verify_source` | One previously selected transaction; optional conditional S3 read-back |

Dates filter **process_date**, with at most 31 inclusive dates. Defaults use the
latest 31 days present in the historical source, not the current calendar month.
Pagination sorts by transaction timestamp and ID. Cursors keep the same window;
repeat explicit dates when paging a custom window.

Customer/conversation selectors are optional schema fields; they never grant
authority to a bound customer. Product and transaction IDs, fraud labels, S3 keys,
credentials and lineage fields never appear in tool results. Handles and cursors expire
after 15 minutes and are bound to the verified subject, customer, session,
conversation and immutable build. A new build invalidates old references. Merchant
text remains untrusted data; models must not follow instructions inside it.

### Approved operator tests through existing chat and Slack

The new `operator-test` profile is an explicit private configuration for approved
organizer-synthetic customers or generated fixtures. It is not activated by a
missing assertion. Use `config.operator.example.json` with a private nonempty
`approved_customers` allowlist and separate durable state. Keep this registration
available only to authorized operators in the existing private FLUJO/Slack setup.
The profile labels its results `synthetic:true` and `operator_test:true`.

Both customer tools require an approved `customer_id` and resolved `conversation_id`
in this mode. The runtime must supply and overwrite conversation correlation on
both tools. If necessary, fix the nonsecret conversation parameter to
`@current.conversation.id` in the existing graphical flow; it overwrites attempted
model values and accepts opaque Slack thread IDs. Missing or unresolved correlation
fails. Operators simply ask for approved A or B in ordinary chat or Slack; they do
not supply secret `_meta`. Disable a customer preset to permit selection, or fix A
to test argument overwrite. Correlation and presets do not authenticate a customer.

Handles/cursors are bound to the selected customer and conversation: switching A
to B in an operator thread is permitted, but A's handle fails under B. Cross-thread
isolation depends on the runtime supplying the actual root's correlation; the MCP
cannot establish a Slack root from a model-authored argument alone. A bound
conversation must start fresh rather than adopt
an operator A/B transcript or provider session. This profile does not add a customer
frontend or create per-customer flows.

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
   rejects any supplied customer/conversation selector differing from that verified
   principal, then checks customer/product ownership while querying the customer bucket.
   Omitting the selectors means the verified customer's transactions; no customer
   preset or private metadata resolver is required for this contract.
5. Before returning a read, it checks expiry and revocation again. Missing or invalid
   authority returns an error, with no customer read.

The local stdio transport does not select a customer. Static headers/env-vars or a shared conversation ID cannot replace the
per-call assertion. Synthetic mode bypasses customer assertions only for a marked,
fixed-customer fixture and explicitly labels every customer result `synthetic:true`.

The optional generic FLUJO callback runs after final argument normalization.
The separately selected hackathon adapter uses it to sign fresh per-call
assertions. Signing keys and bank policy stay outside graph parameters.
Actual model, ownership and interface acceptance are recorded in
[the implementation report](../docs/BANKING_MCP_IMPLEMENTATION.md); Python
contract tests alone do not establish that end-to-end result.

See [the implemented FLUJO integration](../docs/BANKING_MCP_IMPLEMENTATION.md) for
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
`CURRENT`. Every published build also inventories gold Parquet paths/sizes in
`snapshot.json`. The MCP checks that inventory and fails closed for missing/corrupt
buckets rather than returning an empty history. Legacy builds without it require
migration before reloading the updated server. Create a new immutable gold build
from the current published silver and lineage, without rereading S3:

```powershell
python -m pipeline run --stage gold --source local-unused --tables customers products transactions --out data --reports data/pipeline-reports
```

Use installed Python and private dataset/report paths for the existing worker.
This preserves legacy source provenance; it does not prove stronger ingestion
version identity. Builds are retained rather than pruned while readers may use
them. For a fully validated refresh, run all stages with the existing private S3
env file. Bronze validates that the selected source inventory is unchanged after
ingestion, assuming static inputs for the run; changed inputs cannot be published.
Silver-only or silver+gold from cached bronze requires its validated lineage marker. No
credentials or source object keys belong in model inputs or public logs.

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
synthetic reads. Operator tests cover missing/unknown selectors, unresolved correlation,
A/B selection, foreign customer/thread handles, parallel calls and an actual shared
stdio child. Snapshot inventory and connection shutdown are tested independently.
See [earlier local integration evidence](../docs/BANKING_MCP_IMPLEMENTATION.md);
those deployed checks predate the new operator contract.

Eight active reads and 512 queued reads bound the work. Overflow returns `server_busy`.
Queued requests cannot outlive their signed authority. This bounds resource usage;
it is not a promise of equal latency at 500 customers. The remaining acceptance test
must use 500 authenticated frontend customers through FLUJO, with the real signer,
default 20-row pages, retries and provider calls. Measure p95/p99 and tune bounded
query/provider queues and state inside the existing worker based on that result.
Neither local lookup benchmarks nor the earlier Static burst establishes 500
conversational model sessions or S3 verification latency.
