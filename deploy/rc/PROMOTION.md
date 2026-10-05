# Release source and deployment gap

The accepted demonstration is the local fictional portal on port 43900 and
voice companion on port 43941. Its fast language stages are explicitly direct
OpenRouter. See [the startup runbook](README.md) and
[the release report](../../docs/submission/RELEASE_CANDIDATE.md).

The existing Fly application remains a separately observed deployment:
`flujo-factored-2026`, machine `683ddde5f044d8`, volume
`vol_r7yoyjpgy2228kyr`, image
`sha256:46835d1748938843cb82eadf0706474739ce5446a84309ce5188bced76631a26`.
It does not establish acceptance of this release's inquiry module, selected-query
corrections, voice notifications or fast-provider profile. No deployment occurred
during release assembly.

The Git-only joined-context exporter now includes `savia_assistant/`. It was
successfully exercised at application revision
`0640622af02ce421e70b84bbedc4d5606115c4dd`: 192 application files and 1,410
permitted FLUJO files, zero credential files, manifest SHA-256
`b41bf516c03675c5c1436e924394ab8e079ce2c9ad80b0e2ad1fa76e1a25b05b`.
This prepares the existing native joined image source. Its Dockerfile does not
package the updated avatar or the accepted direct-provider launcher, so it must
not be relabelled as the demonstrated complete runtime.

To prepare a fresh context from a reviewed clean source revision:

```powershell
$rcRoot = 'C:/Users/Moe/.codex/worktrees/savia-final-day-rc/factored-hackathon-2026'
$rcRevision = git -C $rcRoot rev-parse HEAD
$catalogFile = 'C:/Users/Moe/Documents/GitHub/factored-hackathon-2026/private/banking-mcp/restricted-model-catalog.json'
$contextPath = 'C:/Users/Moe/.codex/visualizations/savia-reviewed-context'
node "$rcRoot/deploy/fly/build-joined-context.mjs" --app-repo $rcRoot --head $rcRevision --flujo-repo 'C:/Users/Moe/Documents/GitHub/FLUJO' --catalog $catalogFile --out $contextPath
docker build --build-arg "APPLICATION_REVISION=$rcRevision" --tag "savia-joined:$rcRevision" $contextPath
```

Choose a new context directory whose parent exists. The exporter requires the
approved public catalog's exact hash and rejects private runtime files. Its
FLUJO source stays pinned to the permitted isolated hackathon branch; generic
FLUJO main remains unchanged.

A complete Fly promotion first needs the updated avatar and fast-profile launch
packaged, server-only provider configuration supplied, and the actual customer
and voice story accepted against that exact image. Keep protected policies,
signers, session ownership and the existing volume; do not regenerate or copy
bank state to bypass continuity. Once those gates and deployment authorization
are established, the concrete image-only machine update is:

```powershell
fly machine update 683ddde5f044d8 --app flujo-factored-2026 --image 'registry.fly.io/flujo-factored-2026@sha256:<qualified-image-digest>'
```

Verify health, exact image/source provenance, retained volume and authorized
receipt/history/follow-up after promotion. The image build and machine-update
commands above were not executed during this release push.
