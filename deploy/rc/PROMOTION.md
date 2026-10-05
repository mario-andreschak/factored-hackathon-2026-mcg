# Release source and deployment

The intended release is the integrated Savia frontend with its voice assistant,
Python customer and voice APIs, and informational inquiry team. Follow the
[public runtime runbook](PUBLIC.md) to build an immutable Git context and deploy
the separate fictional `savia-rc-2026` application. Its model calls use the
configured direct OpenRouter provider. The standalone top-level avatar source,
server and build have been deleted.

The earlier public image exposed the wrong standalone UI. Its captures and
measurements are historical evidence and do not establish acceptance of the
integrated Savia release. During correction its machine is stopped with automatic
startup disabled. Restore service only with the reviewed integrated image.

Deploy to the existing `savia-rc-2026` machine `851d7dc4460048` and preserve
its encrypted `rc_data` volume `vol_4qlemp91ly8qn98r`. Preserve existing fictional
inquiries and bank state. The reviewed image's Git manifest and served frontend
hashes must match the runtime receipt before running the current customer and
voice acceptance story. See [the release report](../../docs/submission/RELEASE_CANDIDATE.md)
for the final source, image, limitations and acceptance evidence.

The protected `flujo-factored-2026` deployment remains separate: machine
`683ddde5f044d8`, volume `vol_r7yoyjpgy2228kyr`, image
`sha256:46835d1748938843cb82eadf0706474739ce5446a84309ce5188bced76631a26`.
Its effective private admission code was rotated without changing its ledger,
signers, image or volume. Do not update that machine as part of this release.

This public image builds project-owned source only. FLUJO's permitted hackathon
revision is recorded as a compatibility reference, not a built or executed
dependency. Generic FLUJO main remains unchanged.
