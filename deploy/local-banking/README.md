# Existing local banking service: retained native integration

This companion extends the existing `hackathon-banking` frontend service at
`http://localhost:43800`. It uses the supplied organizer DATA and the retained
`hackathon-banking-mcp-state` volume. It creates no dataset, simulator history,
coverage attestation, ledger generation or transition receipt. Missing original
authority retirement, history, receipt, live lease or actual Docker isolation
proof refuses startup. Implementation alone is not runtime acceptance.

The earlier documented local repair replaces only the Slack worker's `.next`
and protected policy. Keep that worker image/launcher and its gateway/operator
UI. This native extension does not replace their global chat adapter, bootstrap
snapshot, Slack state or volumes. Retire only their banking authority through a
reviewed original-owner procedure before opening the retained bank ledger here.
Disabling a visible model card alone does not prove retirement: drain admitted
work, settle revocations/late replies, disable future Banking MCP dispatch,
retire every bank stdio child, and prove that original source can no longer open
or write the volume, including after worker restart. Preserve other Slack MCPs.

## Image and companion provenance

Use the immutable joined image for application source
`676466111e7013136488b0aa7a0cf1ecbee45a86`, FLUJO
`0ba62296520a505e6d71eddf5aa650691f3dc311`. Set `SAVIA_LOCAL_JOINED_IMAGE` to the
approved `registry.fly.io/flujo-factored-2026@sha256:…` digest from the existing
sole build. No second image build is required by this extension. An e53 image or
a moving tag cannot stand in for the required installed revision.

The launcher imports only the installed `supervise` and `initializeNativeModel`
helpers. It does not invoke Fly bootstrap or its HTTPS-origin environment
factory. Installed engine, server, native adapter, wrapper, CLI, catalog and UI
remain unchanged. Record the companion Git revision and both `.mjs` hashes in a
separate approved deployment receipt; the image's source manifest does **not**
claim to contain this external companion. The source exporter currently selects
`deploy/fly/`, not this directory. Shipping these files inside a later image
requires a reviewed exporter/inventory update and a new source/image pin.

The installed transition verifier inventories application source, not these
deployment files. The launcher calls that exact verifier as banking UID10001
before starting any Service. It never edits its source hash or generation pin.
If a later verifier requires the companion inside its source closure, stop for
the source owner's procedure rather than rewriting the saved receipt.

## Exact local wiring

Append `compose.native.yaml` to the **existing frontend** Compose file list and
retain its project name `hackathon-banking` and recorded working directory.
Docker Compose 2.24.4 or newer is required for `!override`. The override replaces
old frontend mounts, not their volumes; existing frontend/worker archives remain
sealed evidence. It leaves Slack, gateway, operator UI and synthetic preview
services untouched. Resolve effective Compose configuration privately: it can
contain existing private values and must not be printed into public logs.

Required variables:

- `SAVIA_LOCAL_JOINED_IMAGE`: approved immutable registry digest.
- `SAVIA_LOCAL_COMPANION_DIR`: this public reviewed directory, mounted read-only.
- `SAVIA_LOCAL_COMPANION_REVISION`: its exact committed Git revision.
- `SAVIA_LOCAL_REAL_DATA`: complete existing actual DATA root containing CURRENT,
  selected build gold/silver/manifests/source objects and matching bronze.
- `SAVIA_LOCAL_NATIVE_VOLUME`: separately owned, already prepared native-state
  volume; the canonical bank volume remains `hackathon-banking-mcp-state`.
- `SAVIA_LOCAL_HOST_LEASE_DIR`: protected host directory containing the shared
  repository lease and owner-written `local-runtime-heartbeat.json`.
- `SAVIA_LOCAL_LEASE_OWNER`: current lease owner's UUID, for exact-container
  ownership labels and the approved private configuration.

One root supervisor runs the installed native worker on loopback4200, unchanged
`run_dispute.py` on loopback8082, and a local proxy on container8080. Docker alone
publishes `127.0.0.1:43800:8080`; worker4200 is never published. Proxy requests
require Host `localhost:43800`; mutations require Origin
`http://localhost:43800`. It forwards only to Savia8082, preserves inner cookies
and forwards no request to a worker/control endpoint. Local cookies use
`BANKING_COOKIE_SECURE=0` and that exact local origin. Public UI contains no new
fixture banner or deployment implementation flow.

Read-only DATA is mounted below `/run/local-bank`. Root seals this Linux-only
parent root:10001,0750; worker1000 has no traversal even if the underlying Windows
mount reports permissive file modes. No chmod/chown is attempted on the DATA
bind. Native controls remain UID10001:GID10002,2750 and admissions0640; bank
configuration/state/evidence stay inaccessible to reader group10002.

## Private preparations that must already exist

Under the prepared native-state volume, `/data/private/local-native` is root:root
0700 and contains root-owned, nonlinked, nonwritable private inputs:
`approval.json`, `bank-config.json`, `frontend.json`, `transition-receipt.json`,
`frontend-signer.pem`, `source.env`, `provider-auth.json` and `worker.json`.
`worker.json` contains only the independent `snapshot_control_token`; old worker
snapshot keys and bank credentials are never passed to the native worker.

The delegated bank configuration retains approved principals/keys, uses
`data_dir=/run/local-bank/data`, `state_db=/data/banking-state/banking.db` and
`source_env=/run/dispute/source.env`. Its independently approved coverage start
and continuity flag must match the actual retained transition. Frontend chat
principal mapping must exactly match it. The receipt must already bind final
installed `/opt/joined` source, canonical ledger generation, original four-table
archive, final proof/archive paths, reader group10002, native controls and fresh
frontend input directory. Plan/apply and receipt publication are separate
original-owner operations, never performed by this launcher.

Require `/data/banking-state` banking:banking0700; preserve the bank archive
root:10001,0440. Require final controls/revocations/admissions/native-profile and
worker directories with the exact installed native permissions. The launcher
never initializes an empty admission registry, deletes tombstones or repairs
retained state. `/data/native-transition-evidence` is root:10001,0550; proof and
archive files are root:10001,0440 at their receipt-pinned final paths.

`approval.json` schema is `savia-local-retained-release/v1`. Required fields are
`applicationRevision`, `companionRevision`, `approvedImage`,
`sourceManifestSha256`, `canonicalBankVolume`, `nativeStateVolume`,
`enableSimulatedIntake=true`, `originalBankAuthorityRetired=true`,
`transitionReceiptSha256`, `kernelQualificationSha256`, `companionFiles`
(filename→SHA256 for the two `.mjs` files), `dataset` (`buildId`,
`sourceFingerprint`, `snapshotSha256`, `manifestSha256`, `sourceObjectsSha256`),
and `runtimeLease` (`ownerToken`, `controllerPid`). These attestations need real
owner evidence; there is no example filled with passing flags.

`dataset.inventorySha256` pins the existing private 150-file recovered closure
manifest, supplied as sealed `real-data-inventory.json` under the evidence
directory. Before any Service, the launcher streams every declared file through
SHA256 with1MiB buffers and checks final stat drift (932,297,878source bytes).
The external controller must keep that actual source frozen for the running
lease; a read-only container mount alone does not stop another host process from
editing the source. No Parquet bytes or metadata are regenerated.

The host controller must acquire the shared repository lease without stealing
it, check live PID and 6GiB available physical/16GiB commit guards, inspect the
immutable image/build receipt, original frontend Compose provenance, canonical
volume identity, native-volume ownership and absence of other bank writers,
then retain the lease while the owned frontend container runs. It writes a fresh
owner heartbeat at least every10seconds with `owner_token`, `controller_pid`,
`head` (companion revision), `status=active`,
`canonical_bank_volume=hackathon-banking-mcp-state` and UTC `heartbeat_at`.
The container verifies both files before startup and every5seconds; missing,
changed or older-than30seconds heartbeat terminates its children. Expose only
the lease directory read-only below root-owned Linux `/run/local-owner`,0700;
protect its host source with private ACLs. Windows bind files use stable regular
file/RO-mount checks rather than invented Unix0440 ownership. Public companion
bytes are SHA-pinned and copied into root-owned Linux tmpfs before the proxy is
spawned, so a subsequent host edit does not change the running proxy. The controller
must stop/restart only its captured full container ID with matching project,
labels, image and volume identity, preserve volumes, and release only its lease.
The existing fixture controller/start script is not a launcher for this route.

## Actual qualification and activation

First qualify the exact installed image under Docker Desktop, including nested
user/PID namespaces, UID/groups, wrapper raw CLI execution, private filesystem
sentinel denial, control mutation denial and immutable profile readback. The
override enables the nested namespace seccomp option while dropping unrelated
capabilities; bootstrap has CHOWN/FOWNER/DAC_OVERRIDE/SETUID/SETGID and KILL so its
trusted supervisor can terminate different-UID child groups. An actual
kernel failure has no unsandboxed fallback. Store the genuine aggregate result
as `local-kernel-qualification.json` in the sealed evidence directory, schema
`savia-local-native-kernel-qualification/v1`, with status `pass`, exact `image`,
`applicationRevision`, `nativeWrapperSha256`, `nativeBinarySha256` and measured
true fields `actualDockerKernel`, `uidAndGroups`, `userPidNamespace`,
`wrappedRawCliHelp`, `privateSentinelsDenied`, `controlsMutationDenied`,
`freshInvocationHomeOnly`, `immutableProfileReadback`, `readOnlyHostBindBoundary`,
`readOnlyDataBindBoundary`, `crossUidSupervisorSignals`. Do not author these from
source inspection or copy Fly kernel evidence as Docker proof.

Only after all gates and an exclusive resource handoff, the owned controller may
recreate **frontend only**, using the existing file list plus this override,
`--no-build --no-deps`. Runtime is capped at2GiB/2CPU/512PIDs with no swap; Linux
CI retains its separate guard. Restart the same container through that controller.
Qualify actual gpt-6-sol/Codex native replies, owned selected-charge inquiry,
source-backed historical policy, explicit simulated-intake consent, durable
receipt/readback, restart, replay/duplicate denial and logout/revocation. Neither
HTTP health nor static checks establish this acceptance.

Pure source boundary check: `node deploy/local-banking/native-local.static.test.mjs`.
It opens no ports and reads no DATA or credentials.
