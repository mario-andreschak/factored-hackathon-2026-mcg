# Repository instructions for coding agents

Read [FLUJO product boundary](docs/FLUJO_PRODUCT_BOUNDARY.md) before proposing
architecture or code that touches FLUJO. The builder is developing FLUJO as a
long-lived generic product; this repository is a hackathon application.

- Keep FLUJO core and shared routes domain-neutral and optional. Do not add
  banking routes, banking DTOs, banking policy branches or challenge-specific
  behavior to FLUJO.
- Put Savia, data pipeline, challenge flows, banking schemas and customer
  policy in this repository, the banking MCP or an external adapter outside
  the FLUJO repository.
- Use FLUJO's existing generic chat, flow, tool and MCP interfaces. Propose a
  reusable FLUJO extension only when those interfaces cannot meet a concrete
  need; justify it with a non-banking use case and regression coverage.
- Treat historical route proposals in docs as superseded by
  [current integration decisions](docs/BANKING_MCP_NEXT_STEPS.md).
