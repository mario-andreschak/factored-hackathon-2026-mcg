# Banking MCP

Carlos's PRs #1 and #2 provide the data pipeline and lookup library. This package
adds the MCP server FLUJO can connect to. It serves the pipeline's validated,
customer-sharded Parquet snapshot and can read a selected transaction back from S3.
The customer read tools remain read-only. Delegated mode also has host-only
simulated intake and verified handoff tools; these make sandbox records only,
never dispute submissions, refunds or bank mutations. See
[the v0 contract](../docs/SIMULATED_INTAKE_V0.md).

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
| `get_my_transaction` | `selection_handle`, optional `customer_id`, `conversation_id`, `verify_source` | One selected transaction, verified local case projection, optional conditional S3 read-back |
| `prepare_unrecognized_charge` | Exact owned transaction ID and snapshot from the trusted host | Pending sandbox decision and private risk evidence |
| `confirm_simulated_intake` | Pending handle and explicit host-confirmed `true` | Persisted simulated intake, if eligible |
| `read_intake_receipt` | Pending handle | Independent receipt read-back after an uncertain write |
| `create_verified_handoff` | Reason, optional pending handle/request ID, bounded `unanswered_questions` | Persisted owner-bound request with verified facts and questions |
| `read_verified_handoff` | Handoff ID | Independent packet read-back before naming the ID |

The five action tools are advertised only in delegated mode and require distinct
per-call scopes. They are absent from the synthetic and operator test registrations.

Dates filter **transaction_date**. With both dates omitted, the window covers up
to 90 inclusive calendar days ending at the latest ownership-valid event date,
bounded by the snapshot's first event. Complete explicit windows are preserved
within the snapshot's verified bounds, with at most 90 days per request. Partial
or out-of-coverage dates fail safely instead of being shifted or clipped. The
response discloses the snapshot anchor and source timestamp calendar. Partition
dates, build time and wall time do not choose the default. A June 18 event stored
in a June 17 partition remains searchable on June 18. Cursors retain owner,
window and anchor; repeat explicit dates when paging a custom window.

`existing_case` describes only the exact owned charge in the local sandbox
ledger. Its states are `verified`, `not_found` and `action_unverified`; historical
complaints cannot establish a charge association. Only `verified` contains a
persisted receipt with status `received`. Existing receipts retain their original
snapshot and do not create another case. Legacy or uncertain records stay
unverified. A saved confirmation-attempt state prevents failed writes from later
becoming a clean absence result.

Handoff packets save server-verified charge facts, their snapshot/as-of
provenance, the reason and up to eight unanswered questions. A separate durable
read determines whether the request ID may be shown. `human_responded` remains
false; a saved request is not agent pickup. See the [source contracts and limits](../docs/ISSUE21_DATA_AND_RECEIPTS.md).

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

### Optional private project host companion (source preparation)

The source supports a companion standard MCP HTTP transport in the **same bank
process** while FLUJO retains its ordinary stdio registration. Both transports
share one original `Service`, `Authorizer`, state store, admission semaphore and
event loop. One outer owner closes the Service after both transports drain.
This does not load banking code into FLUJO or attach another client to its pipe.

The companion is disabled by default. Its project-only config fields are
`private_host_bind`, `private_host_port`, `private_host_clients`,
`private_host_cert_file` and `private_host_key_file`. Enabling it
requires delegated mode, an explicit literal IPv4 loopback/RFC1918 interface,
port1024–65535, and one to16 distinct explicit private caller IPv4 addresses.
All fields must be configured together. Wildcard/public/DNS binds and
partial configurations fail closed. `--transport` must remain `stdio`.
The existing standalone `streamable-http` mode stays separate.

Do not assume loopback crosses frontend/worker network namespaces. A deployment
must review actual fixed private interface/peer addresses, reachability and the
absence of host port publication. No forwarding sidecar, second banking child or
remote FLUJO registration is supplied. The companion accepts only configured
peer addresses and the exact bind-address Host header; Origin-bearing requests,
duplicate Authorization headers and forwarded identity are rejected.

Private TCP always uses TLS. The certificate and key must be absolute, unlinked,
single-link regular files owned by the bank process UID with mode0400. The host
client must verify/pin the expected bank certificate and target identity; trusting
only a bearer on a private IP is insufficient because another process could
replace a listener and collect signed calls or forge results. No HTTP or
verification-disabled fallback is supplied by this companion. Frontend trust
configuration must be reviewed alongside the listener; it is not established
by this server source alone.
The matching host base URL is `https://<private_host_bind>:<private_host_port>`.
Its trusted certificate must contain that literal IPv4 identity in the IP subject
alternative name. A DNS-name URL produces a different Host header and is rejected;
DNS-based configuration examples are not a working contract for this listener.

Before constructing the Service or opening a listener, the CLI holds an
exclusive nonblocking POSIX lock in the bank-owned0700 state directory. The
lock is a single-link owned0600 regular file, opened without following links.
Duplicate invocations fail closed without replacing an endpoint or Service.
The lock remains held through shutdown. Default stdio uses no companion lock.

Companion mode requires POSIX pipe/socket stdin and stdout. It supplies the MCP
SDK with cancellable nonblocking text streams, bounded to65536 bytes per incoming
line, so an idle open parent pipe cannot hold shutdown in a blocking reader
thread. The SDK still parses and serializes standard MCP messages. Descriptor
flags are restored after its tasks drain; the child does not close parent-owned
stdio handles. Default stdio retains the SDK's original stream behavior. Fake
checks cover this wiring; live EOF, signals and parent-death behavior remain
deployment acceptance gates.

The host uses the existing standard stateless JSON `/mcp` initialize, initialized
notification and `tools/call` protocol. A service bearer gates the transport;
customer authority is the fresh signed `com.flujo.bank/assertion` in actual MCP
request `_meta`. Original bank checks retain exact tool/scope/RFC8785 argument
digest, real TTL/JTI/replay, owner/session/conversation and durable revocation.
`/internal/revoke` keeps its separate typed signed assertion and exact response.
There is no direct action shortcut. Client-selected identifiers or tool
annotations are not authority. The agreed frontend contract is
`frontend-direct-mcp-contract/v3`, source receipt SHA256
`674c99164cea5927bae17516572a07bac04257ea943a81da800c1737a9f926f0`,
for the separately reviewed frontend draft PR31 at
`7d684c20d8f71a437854d6b40aafd049227c1899`. This bank transport draft
does not include that frontend branch or claim integrated acceptance. Its DNS
example URL must be replaced by the matching literal-IP URL and approved IP
certificate identity before this listener can accept it. Do not disable TLS or
relax the listener's peer/Host gates to make an example connect.

The frontend independently owns portal selection→raw ID/snapshot resolution,
host UUID/CAS and consent, retry/recovery and exact receipt/HOF readback. MCP's
txn12 projection is unchanged and is neither the portal txn24 reference nor a
selection handle. Host-run provenance is separate from FLUJO's language run.
Only minimized verified display facts may reach generic language chat.

**No activation or runtime acceptance is claimed.** The stock native model CLI
and bank child can share UID/environment access. An empty graph tool list,
read-only mount or neutral cwd does not establish bank-secret/data isolation.
Bank config/data/state/signing/bearer authority must be inaccessible to the model
identity through reviewed OS process/file isolation, and absent from its inherited
environment. Private network and UID launch/EOF/parent-death behavior also remain
deployment gates. Historical51ff/6ebe/b774 package evidence does not transfer to
the corrected architecture. No observer/adapter injection into FLUJO is permitted.
Separating the bank UID alone does not isolate another customer's generic FLUJO
conversation logs or environment from a native CLI sharing FLUJO's node UID.
Exact native filesystem, exec, MCP/catalog and network confinement remains open.
The existing durable sandbox ledger generation survives same-database restart,
but it is not exposed by this MCP contract. Endpoint/certificate/signer pins do
not prove continuity after ledger replacement. Reset/replacement with pending or
uncertain operations requires reviewed generation binding and reconciliation;
this source does not manufacture that binding or permit automatic replay.

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
