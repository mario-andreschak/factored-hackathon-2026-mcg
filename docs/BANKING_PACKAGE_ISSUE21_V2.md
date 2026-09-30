# Issue #21 installed package and discovery checkpoint

This is a new, versioned **FLUJO plus Banking MCP package/discovery** checkpoint.
It uses separate workflow, Dockerfile, helpers, tests and artifact names. The
historical banking `529bcca` / FLUJO `961fd13` proof and its drift guard remain
unchanged. Its successful run does not prove the issue #21 runtime is installed.

## Source identities

FLUJO #533 and banking #23 have passed review and merged. These are the final
source pins for this checkpoint. This source preparation is not an installed
receipt or permission to run a shared worker.

- Audited Banking MCP runtime head: `f07cadf3dd75a20ec945cd22ed4dd4a6b4b6d344`.
- Reviewed final banking source: `ccaedb71d127b9aae273da1ec4b9ebe7b4db8d9a`.
- Merged final banking source: `71ac0f020303abfd0073302a148752f0d2c9f23b`.
- Both final banking trees: `720fa823c4083522a351111b6b37d389df58eebc`.
- FLUJO reviewed source: `3037c1423f7d39ede4d4a9b50afae038e4dd7baa`, version 3.46.1.
- FLUJO merged source: `51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b`.
- Both FLUJO trees: `b754c1cae7def51ab9a1343c1726a63c30d2c53a`.
- Packaging candidate: the separate exact commit running this checkpoint.

The context records audited, reviewed and installed banking identities
separately. It verifies exact runtime-closure byte equivalence and rejects candidate runtime
drift, new banking modules or changed dependency files. The explicit 23-file
closure includes the new repository import of `pipeline.bronze`; it does not
copy whole source directories or local data.

Frontend readiness is a separate source gate. `frontend/` is not copied into
this FLUJO worker image, and this checkpoint makes no frontend installation or
joined browser-to-worker acceptance claim.

## What the remote run checks

1. Export exact reviewed Git blobs into source-only contexts. Build the full,
   unchanged pinned FLUJO Dockerfile with its optional adapter selected. Extend
   that exact CI image with the pinned Banking MCP closure and requirements.
2. Verify base filesystem layers and launcher/runtime metadata are retained in
   the daemon image. Parse compiled JavaScript as data to verify the selected
   adapter; do not invoke routes or action handlers. Retain the exact compiled
   banking route, files proving its configured-adapter binding, and launcher
   scripts with their installed paths and hashes for independent source
   checks. This selected evidence is not a full route dependency replay.
   Retain the observed inherited public-base entrypoint script separately from
   the launcher scripts owned by the FLUJO source pin.
3. Compare installed Python source bytes, dependency inventory and module paths
   to the context manifest. Generate a fictional snapshot and ephemeral
   discovery configuration. Use stdio `initialize` and `tools/list` only.
4. Require three customer read tools and five host action tools. Verify the new
   optional `unanswered_questions` array bounds: at most eight strings, each
   1–240 characters. Record actual schemas and their digest. This does not
   authorize exposing host actions to a model.
5. Verify all nine authority/action tables are empty, including
   `sandbox_case_receipts`, and only one bootstrap ledger identity exists.
   Record SQLite table/index metadata, including `confirmation_state` and
   nullable `packet_json`, without row contents.
6. Record the generated fixture's event-date metadata. This is generated
   fiction, not real S3 ingestion, freshness or measured cold-scan latency.
7. Export a private OCI archive. Link its archive, manifest and config hashes to
   the inspected daemon image; stream-check blob and uncompressed layer hashes.
   Compare safe launcher fields and report OCI Healthcheck presence only;
   retention remains unproven. Daemon base/final Healthcheck equality is a
   separate image receipt check.
   Skopeo may rewrite config serialization, so its config digest need not equal
   the Docker image ID. Retain the exact verified OCI index, manifest and config
   bytes with descriptor sizes and hashes in the small artifact. Reject
   unexpected environment entries before retaining raw config; never redact
   it while claiming the original digest.
   Reject foreign OCI annotations. Only the selected image descriptor may carry
   the exact public `org.opencontainers.image.ref.name=banking-preflight`;
   all other annotation maps must be absent or empty.

## Boundaries and artifacts

The private GitHub-hosted run uses no secrets input. Runtime inspection has no
network, a read-only root filesystem and no capabilities. It does not start the
FLUJO HTTP server. No banking tool, action handler, provider, model or live S3
call is made. Empty-state bootstrap is identified separately from action writes.

There is no local Docker build, pull, image load, container or MCP/FLUJO instance.
Existing workers, conversations, graphs, private policies and action settings
are unchanged. A package/discovery pass does not establish customer authority,
receipt correctness, model readiness, capacity or joined customer acceptance.
Those remain separate gates in issue #15.

Small receipts/logs and the OCI archive are separate private Actions artifacts,
retained for seven days. Small receipt review needs no image download or load.
Raw OCI history is retained under the no-secrets build provenance above. Public
base images and dependency installers are observed build inputs. This checkpoint
does not independently attest their origins.
Failures retain the evidence produced before the failed step and remain failed
or incomplete checkpoints. Dependency ranges and build installers still resolve
at build time; recorded bytes identify the observed build, not bit-for-bit
reproducibility from source pins alone.

Runtime-metadata failures identify the rejected field with safe structural
diagnostics. Image receipts also record separate base/final observations of
`ArgsEscaped`, `StopSignal` and `Volumes`; unknown values and volume paths are
omitted. These observations do not change the OCI acceptance rules.

Only pure local source/helper checks are permitted:

```powershell
python -B -m unittest discover -s scripts/package_issue21_preflight -p 'test_*.py' -v
python -B -m unittest discover -s tests -p 'test_issue21_package_*.py' -v
```

Do not run the installed verifier or fake its remote-only guard locally.
