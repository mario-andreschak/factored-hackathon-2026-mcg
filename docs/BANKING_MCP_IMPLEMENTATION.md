# Banking MCP — implemented September 28, 2026

## Current state

Carlos's pipeline PRs #1 and #2 are merged. They provided data processing and a
Python lookup library, without an MCP endpoint. This implementation adds that
endpoint and connects two servers to local FLUJO at port 43420:

- **Banking MCP Demo:** synthetic data; usable now for graphical flow development.
- **Banking MCP:** real S3-derived data; customer reads require verified, signed
  per-call identity. Status and tool discovery work now.

There are three synchronous read-only tools: `banking_status`,
`list_my_transactions`, and `get_my_transaction`. The last can conditionally
recheck its pinned S3 object. There are no bank mutations or dispute submissions.

**Deployment:** FLUJO and the MCP execute inside the same Docker Desktop Linux VM,
in separate Linux containers on `flujo-slack_default`. The MCP uses Linux Python
3.13, with code installed in its image. Verified from inside FLUJO's container:
the internal MCP URL is reachable and rejects a request without its service bearer
with HTTP 401. Windows hosts the read-only bind-mounted files; no Windows Python
process serves or launches this MCP. Real credentials/data stay outside FLUJO's
general tool container.

The serving snapshot contains 150,000 customers, 400,000 products and 4,425,008
ownership-valid transactions. It was built from the real bucket with this branch's
private lineage fields and immutable source-object sidecar. No customer records,
source keys, credentials, signatures or private mappings are committed here.

## Executed checks

| Check | Result |
| --- | --- |
| Pipeline + MCP regression tests | **54 passed**; one Starlette TestClient deprecation warning |
| FLUJO tool discovery and service status | Both servers connected and ready |
| Synthetic list → inspect through FLUJO's MCP API | Passed; responses explicitly synthetic |
| Real customer read through ordinary FLUJO MCP call | Rejected with `authorization_required` |
| Signed direct MCP reads for two real customers | Passed; different transaction sets |
| Customer B uses customer A's selection handle | Rejected with `reference_unavailable` |
| Selected real transaction verified against pinned S3 | Passed, including conditional customer/product ETag checks |
| Interleaved isolation test | 500 synthetic reads passed |

The direct MCP tests use a local operator signer and private seeded subject map.
They verify the service boundary; they do not demonstrate authenticated frontend
users or FLUJO's trusted identity injection. No model/provider calls were made.

## Local HTTP burst measurements

Real 4.4M-row snapshot, Docker Desktop on Windows, two mapped customers alternating,
one transaction per page, eight active readers, two container CPUs and 2 GiB RAM.
Each level is one synchronized burst; latency includes local HTTP and assertion
verification. No S3 verification, FLUJO execution or model calls in this benchmark.

| Concurrent requests | Successful | p50 | p95 |
| --- | --- | --- | --- |
| 1 | 1/1 | 94 ms | 94 ms |
| 50 | 50/50 | 719 ms | 1,045 ms |
| 500 | 500/500 | 5,100 ms | 8,913 ms |

There were no errors or observed cross-customer results. This is a bounded-load
check, not a 500-distinct-customer or production capacity claim. The local mount,
one-row pages and repeated buckets limit what these numbers establish. Request
overflow returns `server_busy`; queued requests still require unexpired assertions.

## What remains for real customer chat

1. **FLUJO ingress:** verify the frontend session, resolve its authorized customer,
   and enforce conversation ownership.
2. **FLUJO runtime:** keep authority outside graph/model inputs and sign the exact
   tool call immediately before dispatch via MCP `_meta`. Mint a fresh assertion
   for every retry; propagate logout/revocation to the MCP's private state store.
3. **Acceptance test:** 500 distinct authenticated frontend customers through
   FLUJO, with normal pages, retries, providers and the real identity hook.

The MCP defaults to denying customer reads until steps 1 and 2 exist. Shared
headers, environment variables, conversation IDs and `@` tool substitutions do
not satisfy those requirements. Multiple MCP replicas require shared replay,
revocation and reference state before deployment.

See [server setup and assertion contract](../banking_mcp/README.md),
[FLUJO run auth design](FLUJO_BANKING_RUN_AUTH.md), and
[Carlos's pipeline](../pipeline/README.md).
