# Private WhatsApp companion contract

The owner authorized promotion on October 5, 2026. The release coordinator freezes
the current Savia baseline and reviews/merges the normal feature PR. The runtime
lead is the sole deployment writer. Source preparation here creates no Fly
resources, moves no account state and activates no test or outgoing message.

## Source and evidence

The original qualified feature is `27f6cedfca07d7f63035da4758b71ee0394690ff`.
Its frozen source ZIP SHA-256 is
`ab8f4c7cf0e542186f86e2b1033b440533f54d7bd32b2dc62e3f343158267a44`;
the package manifest SHA-256 is
`d5ceb896e7725fe2e7d9549545a40d5e4671769faea5e33074f117258bcbbd06`.
That Linux image is
`sha256:040aa4fe2b2b39cef05b428142b0a8d8ffe78444fe3731e3418a0d12766c3470`.
Keep those records immutable when preparing a successor package.

The companion deliberately exports RC.3
`843da50698b559dc748bea4505d1d93483ff29b3` and WhatsApp MCP
`65d39c4d83b7e9bacdd65e46059f18f185199f8d`, plus the recorded Chrome
browser-descriptor overlay. It uses a separate fictional banking cohort and
ledger. It is not the newer public Savia deployment, and it does not replace,
reset or attach to the public customer ledger. Generic FLUJO remains untouched.

Build only the exported source bundle. Startup verifies both manifests, all
public source hashes, RC/MCP pins and installed MCP source before credentials,
state creation or RC execution. `/status` includes the admitted feature revision
and package-manifest hash. Compiled Node assets are identified by the qualified
image/build receipt; source hashes alone are not a compiled-image attestation.

The standalone startup wrapper disables chat action availability and replaces
its internal bank backend with a read-only authority boundary before serving.
Retained prepare recovery cannot send an action POST, and cancellation cannot
expire bank pending state or delete frontend pending state. The internal backend
permits only session revocation POSTs and query-scope reads; ordinary workflow
bank reads remain available. HTTP action/follow-up blocks remain an additional
boundary. The pinned RC.3 source itself is unchanged.

Public evidence is the dated `validation.json`: owner-confirmed text-to-text/PTT
and independently observed PTT-to-text/PTT, four outbound replies, no uncertain
send. Frozen Windows and Linux suites passed 65 tests and 28 subtests, with one
environment-specific skip. No phone number, account content, credentials or raw
message IDs belong in public evidence. A delivery receipt is not playback.

## Hosted control and lifecycle

Use one separate private Fly app on an isolated custom network, exactly one
always-on Machine and one encrypted volume. Keep the public Savia app separate.
Define no public services or public IPs. Direct private access binds to
`fly-local-6pn:43980` through `--fly-private`; MCP 43981 and RC 43982 remain
loopback-only. Fly documents the [6PN binding](https://docs.fly.io/networking/app-services/)
and [custom-network isolation](https://docs.fly.io/networking/custom-private-networks/).

Reach the UI through an authenticated `fly proxy 43980:43980` tunnel. The remote
hop uses Fly's encrypted WireGuard network; the browser connects to localhost.
Hosted mode additionally requires a 32–256-character URL-safe operator token in
`SAVIA_WHATSAPP_OPERATOR_TOKEN`. Put it and `OPENROUTER_API_KEY` in private Fly
secrets, never the image, configuration repository, URL or command arguments.
The operator secret is removed from child environments. The UI exchanges it for
an eight-hour session token held only in page memory and explicit Authorization
headers. Reloading signs out; logout revokes the session. Cookies would leak
across localhost ports and are intentionally absent. The only unauthenticated
page is a static sign-in screen with no account data. Every account-control route,
including `/status` and `/qr`, requires authentication. Existing Host/Origin checks
still restrict requests to localhost:43980. Another same-organization app cannot
control the phone merely by spoofing those headers. Public ingress requires a
separate reviewed authentication/TLS contract; this mode does not support it.

Mount the private state namespace with UID/GID 1000 and private Unix permissions
(directories 0700, files 0600). Disable automatic suspension and scale-out. Never
start a second owner of the same WhatsApp credentials. Use normal SIGTERM with
sufficient shutdown time; preserve state after a crash and reconcile its owner
explicitly. The bridge starts stopped after every restart. Start baselines current
self-chat history, so messages received while stopped are skipped.

HTTP 200 from `/status` means the control API answered, not readiness. Hosted
acceptance must inspect admitted source, operator protection, child health,
provider configuration, retained account authentication, stopped state and no
uncertain delivery. Check the private RC's dataset health separately. A failed
Fly health check is not itself a restart/recovery strategy.

## Quiesced paired-account handoff

The runtime lead must first freeze the complete original local state privately,
then request graceful `/shutdown` from its current owner. Verify the parent and
both children are gone, ports released, `active.lock` absent, and SQLite files
quiesced before copying anything. Keep the original checkpoint recoverable;
do not restart the local paired owner once cloud ownership begins.

From that stopped checkpoint, copy only these existing account/bridge items into
a **new** cloud state namespace, for example `/state/whatsapp-rc3`:

- `baileys-session/`, including the complete `session.sqlite` and any retained
  SQLite sidecars, authentication and synchronized history;
- `local-config.json`, containing the declared own number/profile/language;
- `delivery.sqlite3` and any retained SQLite sidecars.

Do not copy `active.lock`, logs, QR images, generated samples, provider files or
the local `rc/` tree into this new namespace. The full original `rc/` fixture,
ledger and generation pin remain frozen privately at the original checkpoint.
The cloud may initialize a fresh, independent fictional RC.3 cohort because its
new namespace has no fixture. This must never be described as relocation of the
old lab ledger or public Savia ledger. Never run `prepare` over retained state.

The pinned Baileys store may retain one `session_owner` row after Windows process
termination. A foreign-host lease cannot prove the old owner is dead. After the
separate shutdown proof, the operator may explicitly reconcile **only that row in
the destination copy**, matching its observed old PID/host/token. Verify exactly
one expected row changed and credential, signal-key, alias, chat and message
contents remained unchanged. If ownership differs from the approved checkpoint,
stop and investigate. Do not automatically delete leases, credentials or session
directories; never clear the original snapshot. Preserve uncertain delivery for
operator review, with no replay. A cloud startup that needs phone pairing is an
explicit owner handoff, not permission to discard the migrated credential store.

After deployment, qualify retained account authentication, private authenticated
control and stable source identity with no outgoing message. The relay stays
stopped until an explicit operator Start. Confirm a graceful restart preserves
pairing, delivery state and the new cloud fixture/ledger generation before
claiming hosted continuity. The runtime lead records the deployed image, Machine,
volume and private handoff proof; public release evidence contains only safe
metadata. No self-chat sends or activation are implied by source/health checks.
