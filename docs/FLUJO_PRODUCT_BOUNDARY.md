# FLUJO product boundary for this hackathon

**Owner direction, September 30, 2026:** FLUJO is a two-year product effort.
This hackathon is one use case for FLUJO, not a reason to turn FLUJO into a
banking product. Protect the long-lived product
when implementing or reviewing this demo.

## Where code belongs

| Surface | Allowed work |
| --- | --- |
| FLUJO core and shared packages | Domain-neutral, optional capabilities that are useful beyond this challenge and preserve existing behavior. Use existing chat, flow, tool, MCP and extension interfaces. |
| This hackathon repository | Savia banking UI/API, challenge flows, prompts, evaluation, data pipeline and banking integration code. |
| Banking MCP or external adapter | Customer-scoped banking reads, bank-specific schemas and policy, authorization checks, assertions and sandbox actions. Keep this code outside the FLUJO repository. |

**Do not add banking routes, banking DTOs, banking policy branches or
hackathon-specific behavior to FLUJO core.** Do not put customer mappings,
dataset fields, challenge deadlines, demo switches or bank-specific
configuration into the FLUJO repository or its default flows. Banking
endpoints in Savia's own API are application code and do not make FLUJO a banking platform.

The current integration uses ordinary `/v1/chat/completions`, permanent
configured flows and MCP tools. Shared FLUJO changes must remain generic and
optional. If a required capability is absent, first use an existing extension
point. If that is insufficient, propose the smallest reusable interface and
show a non-banking use case and regression tests. Put domain decisions in this
repo, the banking MCP, or an external adapter loaded through generic FLUJO
interfaces. The existing optional FLUJO banking adapter ([PR #530](https://github.com/mario-andreschak/FLUJO/pull/530))
is an integration to audit for extraction, not a precedent for adding more
bank-specific code to FLUJO. A two-year FLUJO product should not carry code
that only makes this ten-day demo work.

## Review gate

Before merging any change that touches FLUJO, answer:

1. What reusable FLUJO capability does it provide, independently of banking?
2. Does the default FLUJO path behave the same without this integration?
3. Are all banking nouns, schemas, routes, policies and dataset assumptions
   confined outside the FLUJO repository?
4. Can the hackathon integration use existing FLUJO entry points and tools?

If the answers do not establish a generic core change, move the code out of
FLUJO. The September 27 banking-specific ingress proposal in
[FLUJO_BANKING_RUN_AUTH.md](FLUJO_BANKING_RUN_AUTH.md) is historical; its route
instructions are not implementation guidance. The
[current integration decisions](BANKING_MCP_NEXT_STEPS.md) supersede it.
