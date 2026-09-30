# FLUJO product boundary for this hackathon

**Owner direction, clarified September 30, 2026:** FLUJO is a two-year
product effort. The generic secure MCP hook/adapter is acceptable on main.
Banking or hackathon routes must not land on FLUJO main. A separate FLUJO
hackathon branch is acceptable if the demo cannot be built through generic
interfaces. Protect the long-lived product when reviewing this demo.

## Where code belongs

| Surface | Allowed work |
| --- | --- |
| FLUJO main | Domain-neutral, optional capabilities useful beyond this challenge, including the generic secure MCP hook/adapter. Preserve existing behavior and use shared chat, flow, tool, MCP and extension interfaces. |
| This hackathon repository and banking MCP | Savia banking UI/API, challenge flows, prompts, evaluation, data pipeline, customer-scoped reads, banking schemas and policy. |
| Separate FLUJO hackathon branch, if needed | Isolated demo integration that cannot use the generic interfaces as they stand. Do not merge banking or hackathon routes into main. |

**Do not merge banking or hackathon routes into FLUJO main.** Keep
banking DTOs, policy branches, customer mappings, dataset fields, challenge
deadlines, demo switches and bank-specific configuration out of shared
FLUJO code and default flows. Banking endpoints in Savia's own API are
application code and do not make FLUJO a banking platform.

The current integration uses ordinary `/v1/chat/completions`, permanent
configured flows and MCP tools. Keep the generic secure MCP hook/adapter
available on main. If another capability is needed, first use an existing
extension point. If that is insufficient, propose the smallest reusable
interface with a non-banking use case and regression tests. Put domain
decisions in this repo or the banking MCP where practical. The separately
selected FLUJO banking adapter ([PR #530](https://github.com/mario-andreschak/FLUJO/pull/530))
can support the hackathon on a separate branch if necessary; it does not
justify banking or hackathon routes on main.

## Review gate

Before merging a change to FLUJO main, answer:

1. What reusable FLUJO capability does it provide, independently of banking?
2. Does the default FLUJO path behave the same without this integration?
3. Are banking and hackathon routes and domain assumptions absent from main?
4. Can the hackathon integration use existing FLUJO entry points and tools?

If the change serves only this demo, keep it in this repo or the banking MCP
where possible. If FLUJO code is unavoidable, keep it on a separate
hackathon branch; do not merge its domain-specific routes into main. The
September 27 banking-specific ingress proposal in
[FLUJO_BANKING_RUN_AUTH.md](FLUJO_BANKING_RUN_AUTH.md) is historical; its route
instructions are not implementation guidance. The
[current integration decisions](BANKING_MCP_NEXT_STEPS.md) supersede it.
