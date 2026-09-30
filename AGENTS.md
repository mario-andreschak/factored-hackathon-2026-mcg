# Repository instructions for coding agents

Read [FLUJO product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md) before proposing
architecture or code that touches FLUJO. The builder is developing FLUJO as a
long-lived generic product; this repository is a hackathon application.

- Keep FLUJO main and its shared routes domain-neutral. The generic secure
  MCP hook/adapter is acceptable there. Do not merge banking or hackathon
  routes, DTOs, policy branches or challenge-specific behavior into main.
- Put Savia, data pipeline, challenge flows, banking schemas and customer
  policy in this repository or the banking MCP when possible. If a FLUJO
  change is unavoidable for the demo, use a separate hackathon branch.
- Use FLUJO's existing generic chat, flow, tool and MCP interfaces. Propose a
  reusable main-branch extension only when those interfaces cannot meet a
  concrete need; justify it with a non-banking use case and regression coverage.
- Treat historical route proposals in docs as superseded by
  [current integration decisions](docs/BANKING_MCP_NEXT_STEPS.md).
