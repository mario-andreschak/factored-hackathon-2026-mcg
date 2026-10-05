# Local banking worker repair

The `turn-provenance-20260930` worker image was rebuilt without selecting the
banking execution adapter during the Next webpack build. Signed customer calls
therefore fell through to snapshot-control authentication and returned HTTP 401.
The recreated container also lacked `/run/banking-runtime/policy.json`.

This overlay keeps the original local worker image, MCP packages, launcher and
mounted state. It replaces only `/app/.next` with the independently qualified
bank-enabled build, then restores the approved protected policy on every boot
before starting the worker as UID/GID 1000. It does not use the Fly entrypoint.

The base tag must resolve to
`sha256:a071761b46eed021471508f8de8b7d5726752125a3d19e66c4b286d59bde6d86`.
The compiled archive must come from the qualified image
`registry.fly.io/flujo-factored-2026@sha256:9a05802f5656073d81c9c70e650e2a2855e35dda058ae42a5eb61965ef2dc291`.
It must contain only `.next/`; stage it as `.artifacts/next.tar`. The directory is
ignored by Git and the Docker context excludes all other files.

Build with its independently recorded archive digest:

```powershell
docker build --pull=false --build-arg QUALIFIED_NEXT_SHA256=<approved-archive-sha256> -t flujo-slack-worker:banking-auth-20260930 deploy/local-banking
```

Append the absolute path of `compose.override.yaml` to the existing worker's
Compose file list, retaining its original project and working directory. Use
`up -d --no-build --no-deps --force-recreate --wait flujo gateway`: the gateway
shares the worker's network namespace and must follow the recreated worker.
Keep the existing volumes. The frontend and synthetic preview remain separate.

`apply.ps1 -QualifiedArchive <absolute-tar-path> -QualifiedArchiveSha256
<approved-sha256>` performs the base-image and archive checks, builds the overlay,
and carries forward the running worker's exact Compose file list before updating
the worker and its gateway.

Verify the policy SHA/ownership/mode, the worker process UID, worker health and
MCP connections. Then test browser sign-in, a selected-movement inquiry, a banking
tool read, persisted chat history, and browser plus worker revocation at logout.
Finally restart the same worker and check that policy and health remain valid.

## Executed local verification

The overlay image is
`sha256:498bb11ef908e71b0ac21f6fe3fa3aabe644a0c699072136f2d820a041da9262`.
Its qualified archive SHA is
`8a9895f4e1539c931ed371342736525a76825b45e346714ca6acc3eb8c59fb49`.
The actual browser selected-movement inquiry and a follow-up transaction lookup
returned HTTP 200. Both invoked `Banking_MCP__list_my_transactions`; every returned
row was checked against the published gold snapshot and silver product ownership.
Four public messages survived browser refresh. Logout returned 204, removed the
exact browser session, and confirmed that exact session's frontend and worker
revocation. Anonymous overview/history returned 401. A worker restart restored
the approved policy, retained revocation, and brought all eight MCPs to ready.
The worker remained UID 1000 and the native policy remained root:1000 mode 0440.

This verifies the read-only path, not complete selected-charge review. The existing
model prompt hardcodes one `list_my_transactions` call, dates May 18–June 17,
2026, and `limit=1`. The selected deposit inquiry therefore returned the customer's
latest transfer, and the assistant disclosed the mismatch. The shared model and
approved graph/policy are unchanged by this deployment repair. Private browser
proof and the aggregate test receipt are under `private/banking-frontend/`.
