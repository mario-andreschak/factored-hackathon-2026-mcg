# FLUJO product boundary for this hackathon

**Owner direction, September 30, 2026:** FLUJO is a general-purpose product.
Its main branch and default build must remain free of banking-specific or
hackathon-specific code. Existing generic interfaces remain usable. The owner
explicitly allows a separate hackathon branch and requested preservation of the
reversed integration there; this does not authorize putting it back on main.

## Where code belongs

| Surface | Allowed work |
| --- | --- |
| FLUJO main backend and default build | General-purpose capabilities and existing generic chat, flow, tool, MCP and execution interfaces. No banking or hackathon routes, policy, dependencies or domain adapters. |
| This hackathon repository and banking MCP | Savia banking UI/API, challenge flows, prompts, evaluation, data pipeline, customer-scoped reads, banking schemas and policy. |
| Dedicated FLUJO `codex/hackathon-banking` branch | Owner-authorized hackathon integration from #530/#532/#533, kept out of generic main and deployed only as an explicitly identified hackathon build. |

**Keep banking-specific and hackathon-specific coding out of FLUJO main.** Keep
banking DTOs, policy branches, customer mappings, dataset fields, challenge
deadlines, demo switches and bank-specific configuration out of shared
FLUJO code and default flows. Banking endpoints in Savia's own API are
application code and do not make FLUJO a banking platform.

FLUJO [PR #534](https://github.com/mario-andreschak/FLUJO/pull/534) removed the
domain changes from #530, #532 and #533. Main commit
`3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9` has exactly the pre-#530 source tree
of `45e37a5127027070858eca086675ca7675d59f3d`. The combined pre-restoration source
at `51ff39fc5bac84cbbb49bbd2b21b5ab89de8b14b` is preserved on the dedicated
hackathon branch. Existing adapter measurements remain tied to their original
revisions. Restoring main or preserving the branch does not upgrade the old
running image or migrate legacy banking conversation state. See the
[deployment source map](FLUJO_HACKATHON_DEPLOYMENT.md).

Project PRs #31/#32 merged the trusted Savia host/direct-MCP source at observed
project main `e967e7e` and it is included in the local release integration
`af3b22d`. That host resolves owned selections, authorizes consent, signs exact
MCP calls, verifies receipts and handles recovery/revocation. The banking MCP
owns its data, policy and durable state. Generic FLUJO supplies language
handling over bounded, permitted display facts through ordinary interfaces;
bank signing keys, raw record identifiers and action/selection capabilities stay
outside it. Source integration does not establish joined runtime or deployment
acceptance.

The dedicated branch is the permitted place for FLUJO changes needed by this
hackathon. Keep its source and build clearly identified and separate from main;
do not merge the domain integration into generic main under a renamed route or
generic build hook. A proposed main-branch improvement must be useful
independently of banking and preserve existing behavior.

## Review gate

Before merging a change to FLUJO main, answer:

1. What reusable FLUJO capability does it provide, independently of banking?
2. Does the default FLUJO path behave the same without this integration?
3. Are banking and hackathon code, dependencies, adapters and domain assumptions absent from the backend and build?
4. Can the hackathon integration use existing FLUJO entry points and tools?

If the change serves only this demo, prefer this repo or the banking MCP; use
the owner-authorized dedicated FLUJO branch when integration needs FLUJO source.
It must not be merged back into main. The
September 27 banking-specific ingress proposal in
[FLUJO_BANKING_RUN_AUTH.md](FLUJO_BANKING_RUN_AUTH.md) is historical; its route
instructions are not implementation guidance. The
[integration history and source status](BANKING_MCP_NEXT_STEPS.md) must be read
with this boundary; historical descriptions do not establish deployment or
current acceptance of the preserved branch.
