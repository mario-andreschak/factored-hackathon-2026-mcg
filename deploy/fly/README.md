# Savia and the existing Docker FLUJO worker on Fly

The main deployment runs Savia and the existing hackathon inquiry worker in one Fly
Machine. The final profile exposes only the authenticated gateway on port 8080.
FLUJO on 4200, its sandbox on 4201 and the frontend API on 8082 bind to loopback.
The existing local Slack deployment continues independently.

The source worker is `flujo-slack-worker:turn-provenance-20260930`, image ID
`sha256:a071761b46eed021471508f8de8b7d5726752125a3d19e66c4b286d59bde6d86`.
The source frontend is `hackathon-banking-frontend:local`, image ID
`sha256:0b30771ce3b3b7653d27f6916813a96d9bb6fec039d32b7747d5546bb59c7f79`.
The worker reports version 3.46.1 and carries the turn-provenance image label.
Inspection found its compiled middleware had no banking execution adapter,
despite matching credentials. Customer chat and worker revocation therefore
failed authentication. Version/hotfix labels alone do not qualify that compiled
artifact. The migration preserves configurations and runtime dependencies.
The corrected Next.js build is deployed. Live authenticated chat, persisted
messages and independent exact-session revocation checks pass. The selected
movement inquiry also passed its frontend checks. Restart readiness and exact
ledger/message persistence pass. A separate explicit inquiry confirmed real
read-only banking MCP execution. Bank actions stay disabled under the existing
policy.

A gateway-only login fix is deployed and verified in a native browser.
The prior login page sent `Referrer-Policy: no-referrer`, causing native browser
form submissions to arrive with `Origin: null` and fail the exact-origin check.
The fix uses `same-origin` on the login page and retains the CSRF/origin checks;
all 12 gateway tests pass. Wrong credentials now reach password validation
(HTTP 401), and the existing valid credentials redirect to Savia's banking
entry screen.

## Persistent configuration and data

One encrypted 10 GB volume at `/data` holds flow/model/MCP configuration,
encrypted credentials, MCP dependencies, Codex authentication, bank authority
continuity records and consistent SQLite online backups. The initial migration
excluded old FLUJO conversations, CLI history, browser profiles, memory,
repository clones, user files and UI consent decisions. Savia started with new
browser sessions and empty chat history; newly created state persists on the
volume. The real dataset includes only its current published gold
files, silver customers/products and manifests; bronze and historical builds
stay local. The small synthetic banking dataset is also retained.

Savia banking conversations belong to protected executions bound to the
authenticated frontend session, customer and approved flow. Ordinary FLUJO UI
chat requests do not carry that banking authority. The temporary development
trace adapter described below provides viewing in the standard FLUJO interface
while preserving banking execution ownership. The public deployment exposes
Savia through the access gate; the FLUJO dashboard stays private.

Root bootstrap publishes private runtime files, provisions the approved policy
by SHA-256 and seals the dataset read-only. All application services then run as
UID 1000. HTTPS, Secure cookies and the outer access gate protect the private
demo; its existing inner demo code still applies. Credentials and migration
data never enter the build context or image.

## Temporary private development access

Private development is deployed and verified in a native browser. All 58 source
tests pass. Both accounts passed login and API checks; all four stored Savia
conversations, their detail/debug screens, Model Input timelines and archived
inputs are accessible. The browser showed the actual `list_my_transactions`
parameters/result and archived system/user prompts. The flow editor also opens
the existing four-node, three-edge `Banking_Customer` flow. Main Savia still
works in the same browser, all eight MCP servers are ready, and the banking
policy remains unchanged.

The corrected topology keeps `https://flujo-factored-2026.fly.dev` serving Savia
at all times. Private development uses `https://flujo-factored-dev-2026.fly.dev`.
A small stateless relay app forwards HTTPS over Fly's private 6PN network to the
development gateway on port 8081 of the existing live worker. There is no second
worker or data volume. Mario and Gloria share the same live default workspace,
with separate host-only development cookies and individual credentials. Both
apps can remain open in the same browser without changing Savia's routing.

The relay has 256 MB RAM, zero minimum running Machines and automatic sleep.
It adds minor temporary compute cost through October 15, as authorized, and
needs no extra paid IPv4 for standard HTTPS. See
[Fly public-network services](https://docs.fly.io/networking/services/).
Access expires at midnight after October 15 in Bogotá:
`2026-10-16T05:00:00Z`. The gate/relay then reject requests and close development
streams while Savia continues. Temporary access remains outside the final `fly.toml`.
Cleanup is scheduled in this chat for October 16 at 00:10 Bogotá through
`remove-temporary-flujo-development-access`. The local Codex app must be
available for cleanup; access expiry remains enforced by the gate and relay.
The fallback operator commands are below.

The owner provisions distinct `FLUJO_DEV_UI_MARIO_PASSWORD` and
`FLUJO_DEV_UI_GLORIA_PASSWORD` secrets and keeps `development-access.json`
private beneath `%USERPROFILE%/.flujo-fly/flujo-factored-2026`. Usernames are
`mario` and `gloria`; changing the access URL preserves their password values.
Mario can share Gloria's password privately. The worker control bearer stays
server-side, and the original services receive neither development password.

Sign in on the development hostname through `/_dev/login`.
`POST /_dev/logout` revokes that development session; GET returns 405. A restart
also revokes development sessions. From the development editor, you can choose
to run this in the browser developer console:

```javascript
fetch('/_dev/logout', { method: 'POST' }).then(() => location.href = '/_dev/login')
```

A shell client can POST with its owner-private cookie jar:

```powershell
curl.exe -X POST --cookie '<private-cookie-jar>' -H 'Origin: https://flujo-factored-dev-2026.fly.dev' https://flujo-factored-dev-2026.fly.dev/_dev/logout
```

This opens the ordinary FLUJO interface for flows, conversations and traces,
with its existing editing permissions. Flow, model and MCP edits continue
through the existing worker. The temporary trace adapter reads stored banking
conversations and their durable message/tool logs from the same workspace for
the standard list, detail and debug screens, including the Model Input timeline;
private execution credentials and authority are omitted. Banking continuations
retain their existing execution ownership checks. HTTP/SSE and WebSocket
proxying support the editor. MCP Apps sandbox URLs still use `*.localhost:4201`,
and OAuth callbacks remain loopback. The relay
does not expose those endpoints, desktop apps or extra sidecar ports. Edits
apply to the live Fly workspace; file and terminal operations run inside its
Linux Machine. Application-source changes require an image rebuild and redeploy.
The existing fixed-query banking-flow limitations still apply.

The worker retains Machine `683ddde5f044d8` and volume `vol_r7yoyjpgy2228kyr`.
Both immutable image references below are qualified. The relay uses Machine
`83d1301fe41e38` without a data volume. Worker enablement uses the temporary
profile; stage credentials from the repository root, then deploy from `deploy/fly`:

```powershell
node deploy/fly/prepare-dev-access.mjs --stage
Set-Location deploy/fly
$devImage = 'registry.fly.io/flujo-factored-2026@sha256:78c3bf0bf4d090ca7db86b79e03ac8605b17b22a12807e465334df9ecac5746d'
fly deploy --config fly.dev.toml --image $devImage --ha=false
$relayImage = 'registry.fly.io/flujo-factored-dev-2026@sha256:7767d9a2e9db40c0811aa70e637f83f1e741fe424cdec0a1f2bcda30f20800ef'
fly deploy --config fly.dev-relay.toml --image $relayImage --ha=false
```

Build candidate images from `deploy/fly` with `Dockerfile.dev-ui`/
`fly.dev.toml` and `Dockerfile.dev-relay`/`fly.dev-relay.toml`, using
`fly deploy --config <profile> --dockerfile <Dockerfile> --remote-only --build-only --push`.
Qualify both emitted immutable digests before replacing the variables above.

Scheduled cleanup will retain the new dev-capable worker image and deploy the
unchanged final profile. With the development flag absent, only the original
three services run and development secrets remain filtered from them. Verify
Savia before removing the stateless relay and its credentials. An operator can
also perform that cleanup directly:

```powershell
fly deploy --config fly.toml --image $devImage --ha=false
fly status --app flujo-factored-2026
fly checks list --app flujo-factored-2026
# After verifying Savia works and the private development gateway is absent:
fly apps destroy flujo-factored-dev-2026 --yes
fly secrets unset FLUJO_DEV_UI_MARIO_PASSWORD FLUJO_DEV_UI_GLORIA_PASSWORD --app flujo-factored-2026
```

Keep the new dev-capable image during this switch: the older 7bd runtime does
not filter the introduced development-password environment variables.

## Canonical remote build

Requires the running source worker, both source images, private local banking
configuration and the sibling `flujo-cloud` helpers. Verify the source image IDs
above before preparing a new overlay. Private migration output lives under
`%USERPROFILE%/.flujo-fly/flujo-factored-2026`; keep it private. Capture into a
fresh migration staging directory when creating another archive.

From the repository root, the following reproduces the original overlay base:

```powershell
node deploy/fly/capture-docker.mjs
node deploy/fly/import-secrets.mjs
node --test deploy/fly/gateway.test.mjs
node deploy/fly/prepare-overlay.mjs
Set-Location deploy/fly
fly deploy --config fly.toml --dockerfile Dockerfile.remote --remote-only --build-only --push --image-label remote-migration-20260930
```

The build context must be `deploy/fly`; the successful base build used Fly's
default Depot builder. `Dockerfile.remote` uses the pinned public FLUJO ancestor
plus allowlisted immutable worker/frontend assets. Linux tar streams preserve
executable bits and symlinks; the manifest records source image IDs and hashes.
The original `Dockerfile` remains a local combined-image option.

The initial remote image, which has the adapter omission, is:

```text
registry.fly.io/flujo-factored-2026:remote-migration-20260930@sha256:fd81d2931c1031b25387b28473e7578165a3c9276d33af467198f41484bfc89d
```

The qualified repair rebuilds only `.next` from the immutable Docker builder
`sha256:965b248df034fc2bf238df1d1b8468fc401f9bb8004a2e2dbfa9e24aaf7cad26`
plus the five original frozen turn-provenance source files, verified by their
individual hashes. The builder's package, lock and Next configuration match
the preserved runtime byte-for-byte. Git revision
`153a039185b1d303fb0853f1d4935980388a1903` serves only as a comparison reference.
The build selects
`FLUJO_EXECUTION_ADAPTER_MODULE=/app/src/integrations/hackathon-banking/configuredAdapter.ts`
at build time. TypeScript compilation and generation of 116 pages passed.
MCP distributions, scripts, runtime dependencies and Savia assets remain the
original artifacts; only the rebuilt `.next` has separate compilation/hash
provenance.

After preparing the original overlay, build the qualified layer from the
repository root:

```powershell
node deploy/fly/prepare-source.mjs
Set-Location deploy/fly
fly deploy --config fly.toml --dockerfile Dockerfile.bank-enabled --remote-only --build-only --push --image-label banking-adapter-20260930
```

The qualified banking runtime base previously accepted on Machine
`683ddde5f044d8` is:

```text
registry.fly.io/flujo-factored-2026:banking-adapter-20260930@sha256:9a05802f5656073d81c9c70e650e2a2855e35dda058ae42a5eb61965ef2dc291
```

The qualified browser-login gateway base preserves that immutable runtime,
dataset and volume.
`Dockerfile.gateway` replaces only `/opt/savia/fly/gateway.mjs` and records its
hash plus inherited artifact/compilation hashes. The built overlay is:

```text
registry.fly.io/flujo-factored-2026:browser-login-20260930@sha256:7bd920095679e7a8d907f98afb4dd0262d1dfea98e04e7ce2138bc0e3afa4efa
```

From the repository root, build the gateway layer using the default Depot
builder, then deploy its immutable reference from `deploy/fly`:

```powershell
node --test deploy/fly/gateway.test.mjs
Set-Location deploy/fly
fly deploy --config fly.toml --dockerfile Dockerfile.gateway --remote-only --build-only --push --image-label browser-login-20260930
# Deploy this older base only after development password secrets are unset.
fly deploy --config fly.toml --image registry.fly.io/flujo-factored-2026@sha256:7bd920095679e7a8d907f98afb4dd0262d1dfea98e04e7ce2138bc0e3afa4efa --ha=false
```

Postdeploy health and dataset readiness pass with no pending revocations. Native
browser form submissions carry the exact application origin; valid credentials
successfully open Savia. The same Machine and persistent volume are retained.

## First migration and current status

The archive was uploaded, checksum-verified and promoted to the persistent
volume. The first image passed live health, gateway/banking login, Secure cookies,
owned overview and fresh history checks, then failed customer chat and worker
revocation because of the adapter omission. The corrected image is deployed in
place on Machine `683ddde5f044d8`, with all eight configured MCP servers
connected. Generic chat and the selected movement inquiry returned HTTP 200
and persisted their user/assistant exchange. Logout returned 204, denied the
original browser cookie and produced exactly one additional confirmed worker
revocation with none pending or retrying. The independent exact-session audit
confirmed frontend revocation, worker binding/revocation, conversation ownership
and both persisted messages. After a Machine restart, all eight MCP servers
reconnected, readiness and protected policy/credential checks passed, and the
same exact ledger/messages passed again after restoring only the three temporary
audit files. An explicit bank-list inquiry produced one successful native
`list_my_transactions` call against the real read-only dataset. Its delegated
session matched the frontend subject/customer, and its returned selection handle
matched that customer and exact conversation. The targeted private archive is
305,103,310 bytes, SHA-256:

```text
638a2d0769eeada58d3593c733e2a52b37ad2c523407bec59907e09bad8fd285
```

For first-volume staging, place `upload-server.py` and `promote-migration.py`
under `/data` on a temporary Alpine helper. The completed migration used helper
`784eee51f5d078`. From `deploy/fly`, configure only a fresh helper and send the
archive; these commands are historical first-migration instructions:

```powershell
node configure-stager.mjs 784eee51f5d078
node upload-migration.mjs
```

`configure-stager.mjs` requires the explicit Machine ID, validates that the app
contains only that temporary Alpine helper and reads the archive hash/size from
the private receipt. It refuses to reconfigure an application Machine.

Inside the helper, activate the uploaded archive:

```sh
python3 /data/promote-migration.py 638a2d0769eeada58d3593c733e2a52b37ad2c523407bec59907e09bad8fd285 305103310
```

The promoter verifies checksum, size, expected archive roots, source worker and
empty conversation/userdata directories before activation. It extracts under
`/data/.migration-incoming`, refuses an initialized volume and publishes
`/data/.migration-complete.json` last. Replace the helper with the application
image before acceptance; the authenticated HTTPS upload endpoint is temporary.
The application entrypoint waits for the completion marker. Later deployments
reuse the volume and preserve newly created state.

## Verification and operations

`GET /_fly/health` is designed to require dataset readiness and authenticated
private worker readiness without returning identities or credentials. Live
acceptance must additionally verify denied anonymous API access, login, Secure
cookies, owned overview, fresh history, a customer-bound inquiry and confirmed
worker revocation after logout:

```powershell
node verify.mjs --chat --wait-ledger
fly status --app flujo-factored-2026
fly checks list --app flujo-factored-2026
```

Run `node bind-ledger.mjs 683ddde5f044d8`
in a second terminal while verification waits after login. It binds the exact
session by the private cookie hash and acknowledges that run. After logout,
`node bind-ledger.mjs 683ddde5f044d8 --check` verifies its frontend and worker
revocation records using read-only queries. Only booleans/counts are printed;
session correlation stays in private receipts and root-only temporary files.

For the selected movement variant, run
`node verify.mjs --chat --bank-read --wait-ledger` with the same binder/check
sequence. It chooses a movement from the authenticated customer's overview and
asserts that the inquiry returns and persists an exchange. That check verifies
frontend round-trip behavior; bank MCP execution is verified separately.

For explicit tool-path verification, use
`node verify.mjs --chat --bank-read --bank-list --wait-ledger`, then independently
inspect the exact run's tool trace. This check passed with a real read-only call,
matched delegated session and conversation-bound selection handle. The preserved
`Banking_Customer` flow has a
fixed smoke-query system prompt: call `list_my_transactions` once for May 18
through June 17 with limit 1. This deployment preserves that model and policy.
The returned movement can differ from the movement selected in the UI. The
latest canonical model and full 21-node prompts are not installed here.
Acceptance covers authenticated read-only inquiry and tool execution; it does
not establish complete selected-charge or unrecognized-charge resolution.

Before a restart, after the latest exact-session check has passed, preserve its
private audit correlation from the repository root:

```powershell
node deploy/fly/persistence-ledger.mjs 683ddde5f044d8 --save
# Restart the same Machine, wait for health checks, then:
node deploy/fly/persistence-ledger.mjs 683ddde5f044d8 --restore
```

The helper saves an owner-private bundle beneath `%USERPROFILE%/.flujo-fly`,
bound to the exact verification run and Machine. It restores only that run's
three root-only `/tmp` audit files if missing, refuses changed files and reruns
read-only checks against the persistent frontend and worker ledgers. It never
restores application state. Run this before another verification overwrites the
current private receipt. Only booleans and counts enter the result report.

The `brain-online` reference informed the private-worker boundary, one persistent
data mount, an always-running frontend and immutable image deployment. This
final Savia/worker topology uses loopback in place of its separate-app 6PN network;
the optional development relay uses 6PN to that same Machine.
It retains the non-root protected banking runtime. Two shared CPUs, 4 GB RAM,
1 GB swap and a 600-second HTTP idle timeout provide headroom for MCP startup
and long inquiries. Keep independent bank-state backups: a persistent volume
alone does not provide recovery. Preserve policy, signing keys, graph identity
and bank-state continuity when updating the image.
