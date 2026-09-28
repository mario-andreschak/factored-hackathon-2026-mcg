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

**Deployment:** Banking MCP is installed **inside the existing FLUJO container**
and launched by FLUJO as a Linux Python stdio child process. Both real and synthetic
registrations use stdio. Dataset/configuration/source files are read-only mounts;
SQLite state stays on durable writable volumes. No remote MCP URL or separate
Banking MCP service is required. The earlier separate-container deployment was
incorrect for this requirement and has been replaced.

The serving snapshot contains 150,000 customers, 400,000 products and 4,425,008
ownership-valid transactions. It was built from the real bucket with this branch's
private lineage fields and immutable source-object sidecar. No customer records,
source keys, credentials, signatures or private mappings are committed here.

## Executed checks

| Check | Result |
| --- | --- |
| MCP regression tests, including actual stdio subprocess and private revocation | **37 passed** |
| FLUJO banking + workspace mutation/process writer/snapshot tests | **107 passed** |
| TypeScript, changed-file lint, Linux production build | Passed |
| FLUJO process ancestry | Real and synthetic Python stdio servers are children of `next-server` in the existing container |
| Synthetic list and inspect through FLUJO | Passed; explicitly synthetic |
| Real reads through the protected FLUJO flow | Two customers matched independent private owner queries |
| Foreign read/delete/cancel/continue; ingress replay | Rejected |
| Ordinary FLUJO tool tester on the real bank | Rejected without trusted banking context |
| Signed local revocation | Passed; survives worker restart in both FLUJO and bank state |
| Saved Slack OAuth after restart | Reconnected |
| Live 500-subject burst through FLUJO | **500/500 successful; 500/500 tool results matched the expected customer** |

The live test uses operator-issued frontend assertions with 500 distinct subjects
mapped privately to 500 real dataset customers. It exercises a shared pinned Static
flow and the real stdio MCP, without a model provider. Thirty-two runs are active at
once; the remaining requests wait in the bounded queue. Each call returns one row.

| Current stdio + FLUJO test | Result |
| --- | --- |
| Concurrent submitted requests | 500 |
| p50 / p95 response latency, including queue time | 26.399 s / 48.401 s |
| Total test time, including private result audit | 53.43 s |
| Provider calls / selected-source S3 readback | 0 / disabled |

The initial burst exposed repeated workspace writer registrations: only 288 requests
completed before queued authority expired. One workspace write admission per banking
turn fixed that bottleneck; each individual commit retains ownership/revocation checks.
No authorization lifetime was extended. This proves the backend serving path for the
measured flow, not a production SLA or 500 paid model calls. Earlier conditional S3
readback and cross-customer selection-handle tests remain part of the service checks.

## Earlier standalone HTTP measurements (not the current stdio deployment)

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

## FLUJO identity integration

FLUJO's identity-hook PR adds authenticated banking routes, durable conversation
ownership, model-inaccessible per-call assertions and local signed revocation.
Live acceptance uses a pinned Static flow with two real customers. A customer-facing
frontend and API-provider conversational flow still need integration. The live 500-customer
backend test uses real derived data. Authentication through the actual frontend and
the conversational provider path remain acceptance gates.

See [server setup and assertion contract](../banking_mcp/README.md),
[FLUJO run auth design](FLUJO_BANKING_RUN_AUTH.md), and
[Carlos's pipeline](../pipeline/README.md).
