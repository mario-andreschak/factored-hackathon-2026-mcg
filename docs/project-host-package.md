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

The focused v0 plan prefers a stock remote HTTP language adapter only when the
human's existing permitted model is already configured and usable through that
adapter. Restored FLUJO source supports OpenAI, Gemini and Anthropic HTTP
adapters; that source capability does not establish an available account, model
binding, permission or live connection. No new provider, account, payment or key
configuration is part of this source draft. The model placeholder remains a
declaration. Review the actual saved model and empty bank-tool graph/catalog,
minimized facts, endpoint/server authentication and network boundary before use.

If permitted existing HTTP model access is unavailable, native CLI acceptance
remains held. A privileged setuid launcher or native-tool wrapper is not supplied
as a v0 feature. Bank process identity, one-child lifecycle and file isolation
still require a reviewed package under either language-provider path.

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

## Separate source dependency and acceptance work

Frontend draft PR31 is pinned at
`7d684c20d8f71a437854d6b40aafd049227c1899`, tree
`8c8f32a4c34b35f6e7f7392a46ca32f83076859b`. It owns the trusted host,
signer and standard MCP client and is not folded into this bank/source branch.
Its reviewed contract-v3 receipt is SHA256
`674c99164cea5927bae17516572a07bac04257ea943a81da800c1737a9f926f0`.
The bank listener requires the frontend URL and verified certificate IP identity
to match its explicit bind/port; the frontend's DNS example is not that effective
configuration. No joined transport or installed graph is established here.

Protected action/CAS/prepare-to-dispatch/RPC/assertion/readback joins and accepted
guidance/fallback/context/provider provenance are still outstanding. Documentation,
source hashes and fake tests do not capture those events. Recovery exhaustion and
independent held-out/human ES/PT comparison also remain open. Preserve historical
evaluation/scorer packets, PR28 and their pins; source-only compilation does not
adapt or rescore them.
