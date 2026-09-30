# Project host package: source preparation

This source migration uses unmodified FLUJO commit
`3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9`, tree
`780c2cf42266f8e55ff1917c137b196ee97df959`, version `3.46.1`.
The banking controller, signer and MCP remain project code. The generic language
graph has no banking tools, private handles or signing authority.

`scripts/package_project_host/flujo_source.py` is a new source-preparation path.
It reads a pinned Git closure and rejects domain routes/adapters/reexports,
symlinks and private data/credential paths. Its manifest explicitly states that
no image, runtime isolation or capacity has been demonstrated. The pure tests
use fake Git bytes and never start a service or export real source.

## Historical packages

The existing `package_preflight`, `package_issue21_preflight`, integration
Dockerfiles and PR28 artifacts describe earlier banking-adapter architectures.
They remain historical records. Their image identities, checks and acceptance
receipts do not validate this migration and must not be relabeled or activated
as its package.

## Runtime gates still open

A language graph without MCP nodes does not confine FLUJO's ordinary native
Codex process. The restored adapter does not select its restricted execution
profile for an ordinary language flow; the CLI inherits FLUJO's environment and
normally shares the worker's `node` UID with stdio children.

Before existing-model authenticated acceptance, the bank data, config, state,
S3 credentials and service bearer need an operating-system boundary from that
model identity. A separate fixed bank UID inside the same worker is a candidate;
the process must still be launched and owned through FLUJO's stdio lifecycle.
No additional MCP container or FLUJO instance is part of this correction.

Bank-only file permissions also do not isolate customers' generic conversation
logs from a native model process running under FLUJO's own UID. The exact native
tool, filesystem, environment and network boundary remains an acceptance gate;
the language compiler checks cannot establish it.

The host transport must also reach the existing frontend's actual network
namespace and authenticate the bank server, without publishing a new public
port. A loopback listener in the worker is not automatically reachable from an
external frontend. These deployment details require source review and later
authorized acceptance. This draft neither starts a listener nor claims they
are solved.

The bank's existing `sandbox_ledger_identity.generation` persists across restart
with the same durable database. It changes with a new database, but is not
currently exposed through the MCP result contract. Endpoint and signer pins
alone cannot verify continuity of that ledger. State reset or replacement with
pending or uncertain operations requires explicit reconciliation; it must not
silently become a fresh prepare or confirmation.
