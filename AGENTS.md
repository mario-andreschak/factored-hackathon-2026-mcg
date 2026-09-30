# Repository instructions for coding agents

Read [FLUJO product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md) before proposing
architecture or code that touches FLUJO. The builder is developing FLUJO as a
long-lived generic product; this repository is a hackathon application.

- Keep FLUJO general purpose. Its existing generic chat, flow, tool, MCP and
  execution interfaces remain usable. Do not add banking or hackathon routes,
  DTOs, policy, dependencies or domain adapters to its backend or build.
- Put Savia, data pipeline, challenge flows, banking schemas and customer
  policy in this repository or the banking MCP. Do not create a banking-specific
  FLUJO branch or inject a banking backend adapter through a generic hook.
- Use FLUJO's existing generic chat, flow, tool and MCP interfaces. Propose a
  reusable main-branch extension only when those interfaces cannot meet a
  concrete need; justify it with a non-banking use case and regression coverage.
- Treat historical route proposals in docs as superseded by
  the product boundary. FLUJO #530/#532/#533 were removed by #534; their source
  and old runtime evidence are historical, not permission to restore them.
