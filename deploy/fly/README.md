# Joined Fly deployment

The production target is `flujo-factored-2026`. This project packages Savia's
frontend, Python banking/dispute host and a dedicated native FLUJO worker in one
image. Follow the [product boundary](../../docs/FLUJO_PRODUCT_BOUNDARY.md): FLUJO
source is pinned to the permitted hackathon commit
`0ba62296520a505e6d71eddf5aa650691f3dc311`, not generic FLUJO main. This runbook
describes release gates; it does not claim an image is deployed or accepted.

## Export and build an immutable candidate

Use a clean, reviewed application checkout whose HEAD is the exact final release
commit. Set `$flujoRepo` to an absolute FLUJO checkout containing the pinned Git
objects, `$catalog` to the approved public vendor model-catalog file, and
`$context` to a **new** absolute directory outside both repositories with an
existing parent. These inputs contain no runtime credentials or banking records.

```powershell
$appRepo = (git rev-parse --show-toplevel).Trim()
$revision = (git rev-parse HEAD).Trim()
node deploy/fly/build-joined-context.mjs --app-repo $appRepo --head $revision --flujo-repo $flujoRepo --catalog $catalog --out $context
if ($LASTEXITCODE -ne 0) { throw 'Source export failed.' }
flyctl deploy $context --app flujo-factored-2026 --config "$appRepo/deploy/fly/fly.dev.toml" --dockerfile "$context/Dockerfile" --remote-only --build-only --push --depot=false --build-arg "APPLICATION_REVISION=$revision"
if ($LASTEXITCODE -ne 0) { throw 'Candidate image build failed.' }
```

The exporter reads committed Git blobs, rejects dirty application source and
private/nonregular inputs, verifies the FLUJO pin/tree and the separately pinned
public catalog, and never overwrites an existing context. Record its exact
application/FLUJO revisions and `sourceManifestSha256`. The Dockerfile performs
locked `npm ci` installs and frontend/FLUJO builds, installs the aggregate Python
dispute requirements with `pip check`, verifies installed source hashes, and
retains dependency versions in the image. Record the pushed **OCI digest** and
installed `build-receipt.json`; a mutable image tag is insufficient.

The build-only command pushes an image without updating production Machines.
Export success, compilation and a registry push are separate from promotion.
The image receipt identifies the raw Codex CLI, namespace wrapper and model
catalog independently. Git `native-execution.mts` is copied byte-for-byte to
`/app/fly-native-execution.ts` for the Next loader at build and runtime.

## Installed runtime and evidence

The root entrypoint stages protected volume inputs and supervises separate
processes through `gosu`. Worker/gateway UID1000 owns the independent native
worker state. Banking UID/GID10001 owns the sole banking service, ledger and
workflow host. Supplementary reader GID10002 grants the worker read/traverse
access to application-issued admissions/revocations, never banking data, keys,
configuration or transition proofs. See [native isolation](NATIVE_EXECUTION.md).

The worker listens on loopback 4200; `scripts/run_dispute.py` listens on loopback
8082; the authenticated public gateway exposes port 8080. Application code lives
at `/opt/joined`. The runner's `--application-source-root /opt/joined` is code
inventory; its optional `--source-root` means private bank object data. Production
uses the bank-only configured source environment instead of treating application
code as bank data. Do not start another legacy bank stdio/listener alongside the
joined host.

Root seals old frontend/worker history and stages the read-only provider login.
Before retained adoption, the deployment owner places verified proof files and
sealed archives at their final bank-only paths in
`/data/native-transition-evidence`. The bank archive remains
`/data/banking-state/legacy-bank-before-native.sqlite3`. Plan/apply must record
those final paths; never relocate or rewrite paths in a saved receipt. Verify
the actual receipt as banking UID10001 before activation and after restart.
Root owns immutable proofs and the receipt; native-reader GID10002 cannot read
them. Private artifacts, account credentials, dataset, signer keys and retained
state are supplied from the volume, never committed or uploaded as build inputs.

## Promotion gates

1. Require all configured CI checks on the exact final application commit and
   retain their results. A partial local suite, component tests or checks for an
   earlier revision do not qualify a later release. If hosted CI is unavailable,
   use only the agreed complete same-source alternative and record the limit.
2. Qualify the installed candidate on Fly's actual kernel: process identities
   and groups, user/PID namespaces, filesystem/control isolation, TLS/DNS,
   restricted native provider execution and immutable profile readback. The
   wrapper fails closed; never bypass its namespace when a probe fails.
3. Complete application qualification and customer-path acceptance against the
   selected source/image/configuration. `scripts/qualify_dispute_app.py` supports
   fresh authored synthetic fixtures; label them as fixtures. HTTP health,
   model registration, source tests and a successful language-stage call alone
   do not prove connected banking inquiry or verified simulated intake.
4. Require independent retained-state review, an exclusive deployment lease,
   original-authority retirement/drain, original obligation settlement receipts,
   current backup/archive evidence and legitimate coverage provenance before
   adoption. Preserve revocation tombstones, late replies, replay history,
   ledger identity and generation pins. Unknown or pending obligations block.
   Follow the [transition contract](../../docs/DISPUTE_DEPLOYMENT_TRANSITION.md).
5. Promote only the qualified immutable digest with the reviewed configuration.
   Check authenticated inquiry, signed-in session boundaries, the explicit
   simulated-intake consent/action path and verified receipts, including restart
   and denial cases. Preserve truthful evidence of outcomes and limitations.

Never fabricate a replacement dataset, old history, settled obligation, generation
pin or coverage proof to satisfy these gates. Customers reauthenticate; archived
legacy chats stay unavailable until separately authorized archive access exists.
Simulated intake is an explicit reviewed switch, and real bank effects stay off.

## Repeated releases and recovery

Scheduled runs compare the deployed application revision with the candidate and
skip unchanged source. They use the same export, final-source CI, candidate and
promotion gates. Startup pins the installed application inventory to the retained
transition receipt: changed source needs an explicitly reviewed compatible
receipt/update procedure. An old receipt cannot authorize arbitrary new source.

Preserve a current, consistent backup and immutable archive before state adoption.
Keep newer state and pending obligations after a failed attempt; never restore a
stale ledger to make an older image start. Interrupted adoption requires explicit
recovery review, not deletion of receipts, archives or pins followed by retry.
Source/image rollback requires verified compatible authority and ledger schema;
otherwise keep maintenance or read-only archive mode until recovery is reviewed.

Use `fly.dev.toml` while preserving the existing temporary development relay
`flujo-factored-dev-2026`. Its access expires at **2026-10-16T05:00:00Z**. Keep that
expiry and separate development credentials intact; do not extend access during
a routine release. The private development listener is distinct from production
banking authorization.
