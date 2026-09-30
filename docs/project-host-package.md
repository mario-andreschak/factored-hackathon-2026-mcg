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
with the same durable database. Both existing JWT profiles now require its
64 lowercase hex `ledger_generation`; delegated bindings retain it and the
actual row is checked before authority mutation and inside action/readback
transactions. The frozen Config's `ledger_continuity_approved` defaults OFF
outside SQLite backups. A matching-generation older backup cannot prove
continuity: trusted restore/import/replacement must pause/drain and quarantine
before reopening, then explicitly reconcile pending/uncertain/acknowledged and
revoked state, rotate the existing row, re-attest coverage, retire old authority
and adopt a new host pin. No new discovery/reset endpoint or automatic adoption
is supplied. See [the bank contract](../banking_mcp/README.md#ledger-continuity-source-contract).

The corrected-source component tests use only temporary fictional SQLite,
fixture Principals and a fake Repository. Config/JWT are replaced before source
execution and JWT use/Authorizer construction are forbidden. These tests cover
generation fences and selected actual SQLite transactions; they do not prove
token/HTTP verification, transport, deployment, capacity or operator restore.
Transport tests remain a separate fully mocked security/Service/SDK/TLS lane.

## Separate source dependency and acceptance work

Frontend draft PR31 is pinned at
`fac397b4b56d12deb6c80a51de3c646e0916a7b5`, tree
`e2d1de15cc42e668bfa0fbc15cc0a577884473d7`. Its host now includes generation
continuity and Portuguese error fixes. It owns the trusted host, signer and
standard MCP client and is not folded into this bank/source branch.
Contract-v4 receipt SHA256
`b4ca7331f8baf11b4db1a573266a0407dd99c53ba7a6a25e152c240d69911505`
is a historical snapshot from before mandatory `ledger_generation`; it does
not establish the current wire agreement.

Three new mocked generation-delivery controls passed for frontend
`7d2305afe84a71724a3fd762812bc577f41079a6` and bank
`775eb89c3752df95c5f3dfbac23a00269e03d118`, receipt SHA256
`628313a6737f524570f2808c3f2feb26082e2c8f4a0d48f5065755c417943ade`.
Signer/security/Service/SDK/TLS and resource boundaries were fake. These controls
do not prove actual authentication, transport, installation or current host
durability. No old controls were rerun.

The bank listener requires the frontend URL and verified certificate IP identity
to match its explicit bind/port. The aligned example uses deliberately invalid
IP/port placeholders; no effective network/peer/certificate configuration was
chosen. No joined transport or installed graph is established here.

Current human direction permits an isolated FLUJO hackathon branch, as in the
original PR29; generic main remains general purpose. The active Slack gateway
fix is owned by the supervisor in `flujo-app/flujo-slack-bot`, using existing
generic endpoint IDs and `recovery.runId`. This package checkpoint still pins
the stock FLUJO source above; branch permission does not establish runtime or
package acceptance.

Protected action/CAS/prepare-to-dispatch/RPC/assertion/readback joins and accepted
guidance/fallback/context/provider provenance are still outstanding. Documentation,
source hashes and fake tests do not capture those events. Recovery exhaustion and
independent held-out/human ES/PT comparison also remain open. Preserve historical
evaluation/scorer packets, PR28 and their pins; source-only compilation does not
adapt or rescore them.
