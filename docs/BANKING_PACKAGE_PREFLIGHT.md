# Private Banking MCP packaging preflight

This workflow establishes an **installed package and stdio discovery** checkpoint.
It is a separate draft from the merged core changes. It does not deploy a worker
or establish customer authorization, model readiness, action correctness or load.

## Why this build is different

`Dockerfile.flujo-banking-integration` overlays a new `.next` and two dependencies
onto an existing worker. Its revision label cannot prove the remaining dependency
tree belongs to that build. This preflight instead:

1. Checks out exact public FLUJO `961fd13b823088c9f0f473cddefd962816a13bc2`.
2. Prepares an explicit source-only context and builds its **full, unchanged
   Dockerfile**, including builder and production dependency installation.
3. Selects the optional banking adapter at build time and supplies version 3.46.1
   plus the actual FLUJO source revision.
4. Extends that exact locally built CI image with the Banking MCP runtime closure
   from `529bcca2ae83a705e8c372a065602f3e27fa11da`.
5. Verifies the final image retains every base filesystem layer, launcher,
   healthcheck and runtime user. It verifies installed banking source bytes
   against the source-context manifest, rather than relying on labels.

The extension copies no application `.next` or `node_modules`. The default Docker
driver lets the second build consume the first local image without pushing or
pulling an arbitrary registry/base image.

## Data and execution boundary

- Runs only in this **private repository**, on same-repository PRs or explicit
  workflow dispatch, with read-only repository permissions and no secrets input.
- Original Git metadata, organizer PDFs, datasets, source-object metadata,
  operational configs, keys and local environments are excluded from contexts.
- Runtime bank files come from pinned Git blobs; candidate packaging helpers are
  identified separately by the exact CI head. Core runtime drift fails the check.
- Builds and disposable inspection containers run on GitHub-hosted CI, never on
  the user's machine. There is no local Docker build/pull/container or new local
  FLUJO/MCP instance.
- Inspection has no network, a read-only root filesystem and no capabilities.
  It overrides the launcher; it does not start the FLUJO HTTP server.
- It parses compiled route JavaScript as data to verify the selected adapter. It
  does not import route factories or invoke action handlers.
- Banking verification imports the installed modules, generates a fictional
  fixture, creates disposable verification configuration and performs MCP
  `initialize`/`tools/list` only. It never calls a tool or signs a user assertion.
  The inventory must contain **three reads plus five host action tools**; this
  does not authorize exposing those actions to a model.
- Generated fixture publication and empty-state bootstrap are separate from
  action writes. The verifier checks action/authority tables remain empty.

## Evidence

The small private Actions artifact contains source-context manifests, exact image IDs
and layer identities, installed Python dependency/source/import inventories,
compiled application hashes and adapter provenance, installed Node dependency
inventory, stdio tool/schema inventory,
build/inspection logs, the OCI manifest and archive digest. The candidate OCI
archive is a separate private artifact, so receipt review needs no image download
or local Docker. Failed runs preserve the evidence produced before failure.
No registry publication occurs. Both artifacts expire after seven days; retain
needed receipts privately.

Node/Debian/uv installers and broad Python requirement ranges resolve during the
build. Recorded image/content and installed dependency digests identify this
observed build; the source pin is not a bit-for-bit reproducibility claim.
Python dependency RECORD hashes identify the installed inventory, not downloaded
wheel bytes. The OCI manifest/archive digests identify the actual image bytes.

The normal FLUJO Dockerfile may install its ordinary toolchain. This workflow adds
no dedicated restricted Codex binary and makes no restricted model readiness
claim. A no-model Static smoke needs no CLI. A later restricted profile still
requires the actual chosen 0.153.3 or 0.157.1 binary, catalog hash and private policy, followed by
its own runtime acceptance; package installation cannot establish those facts.

## Running and interpreting it

Open the draft PR to trigger `Private banking package preflight`. Use its private
run/job/artifact handles as the evidence. All steps must succeed before claiming
installed-package acceptance. A failure is a failed or incomplete package check;
source tests or labels do not turn it into a pass.

Local source checks are permitted:

```powershell
python -B -m unittest discover -s scripts/package_preflight -p 'test_*.py' -v
python -B -m unittest discover -s tests -p 'test_package_*.py' -v
```

Do not execute the installed-runtime verifier locally. Its banking imports and
stdio child have a Linux/GITHUB_ACTIONS accidental-use guard. The actual evidence
boundary is the hosted run in the private repository, not that environment flag.

This preflight leaves main, existing workers, saved graphs, protected policies,
datasets and action flags unchanged. Draft customer flow PR #17 is not part of
the installed banking package. Joined customer, ES/PT, host action/recovery,
clock/ledger, operational and capacity gates remain separate.
