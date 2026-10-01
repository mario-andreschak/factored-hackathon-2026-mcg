# Repository instructions for coding agents

Read [FLUJO product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md) before proposing
architecture or code that touches FLUJO. The builder is developing FLUJO as a
long-lived generic product; this repository is a hackathon application.

- Keep FLUJO main general purpose. Its existing generic chat, flow, tool, MCP and
  execution interfaces remain usable. Do not add banking or hackathon routes,
  DTOs, policy, dependencies or domain adapters to shared main or its default build.
- Put Savia, data pipeline, challenge flows, banking schemas and customer
  policy in this repository or the banking MCP. The owner explicitly permits
  the isolated FLUJO `codex/hackathon-banking` branch for demo integration that
  needs FLUJO changes. Keep its domain source and build out of generic main.
- Use FLUJO's existing generic chat, flow, tool and MCP interfaces. Propose a
  reusable main-branch extension only when those interfaces cannot meet a
  concrete need; justify it with a non-banking use case and regression coverage.
- Treat historical route proposals in docs as superseded by
  the product boundary. FLUJO #530/#532/#533 were removed from main by #534;
  their combined source is preserved on the dedicated hackathon branch. Follow
  [the deployment source map](docs/FLUJO_HACKATHON_DEPLOYMENT.md); preserving
  source does not deploy it or establish current customer-path acceptance.
