# FLUJO product boundary for this hackathon

**Owner direction, September 30, 2026:** FLUJO is a general-purpose product.
Its backend must not be enhanced with banking-specific or hackathon-specific
coding under any circumstances. Existing genuinely generic interfaces remain
usable; they do not authorize adding or loading a banking backend adapter.

## Where code belongs

| Surface | Allowed work |
| --- | --- |
| FLUJO backend and build | General-purpose capabilities and existing generic chat, flow, tool, MCP and execution interfaces. No banking or hackathon routes, policy, dependencies or domain adapters. |
| This hackathon repository and banking MCP | Savia banking UI/API, challenge flows, prompts, evaluation, data pipeline, customer-scoped reads, banking schemas and policy. |

**Keep banking-specific and hackathon-specific coding out of FLUJO.** Keep
banking DTOs, policy branches, customer mappings, dataset fields, challenge
deadlines, demo switches and bank-specific configuration out of shared
FLUJO code and default flows. Banking endpoints in Savia's own API are
application code and do not make FLUJO a banking platform.

FLUJO [PR #534](https://github.com/mario-andreschak/FLUJO/pull/534) removed the
domain changes from #530, #532 and #533. Main commit
`3fccc557df97aba0e96ce28a8e6eebaa8e71d7d9` has exactly the pre-#530 source tree
of `45e37a5127027070858eca086675ca7675d59f3d`. The old adapter and its evidence
are historical. Restoring source does not upgrade the old running image or
migrate legacy banking conversation state.

The replacement is being implemented in this repository: the trusted Savia
host resolves owned selections, authorizes consent, signs exact MCP calls,
verifies receipts and handles recovery/revocation. The banking MCP owns its
data, policy and durable state. Generic FLUJO supplies language handling over
bounded, permitted display facts through ordinary interfaces; bank signing
keys, raw record identifiers and action/selection capabilities stay outside it.
This source direction is not a claim of deployment or joined acceptance.

Do not implement the domain in a separate FLUJO branch, rename its routes, or
inject a banking adapter through a generic build hook. A proposed generic
platform improvement must be useful independently of banking and preserve
existing behavior; a non-banking use case alone does not excuse domain source.

## Review gate

Before merging a change to FLUJO main, answer:

1. What reusable FLUJO capability does it provide, independently of banking?
2. Does the default FLUJO path behave the same without this integration?
3. Are banking and hackathon code, dependencies, adapters and domain assumptions absent from the backend and build?
4. Can the hackathon integration use existing FLUJO entry points and tools?

If the change serves only this demo, keep it in this repo or the banking MCP.
There is no separate-branch or adapter-injection exception. The
September 27 banking-specific ingress proposal in
[FLUJO_BANKING_RUN_AUTH.md](FLUJO_BANKING_RUN_AUTH.md) is historical; its route
instructions are not implementation guidance. The
[integration history and source status](BANKING_MCP_NEXT_STEPS.md) must be read
with this boundary; historical descriptions do not authorize reintroduction.
