"""Generic FLUJO MCP bridge; trusted turn context is injected by the host."""
from __future__ import annotations

from copy import deepcopy


def make_run_turn_tool(workflow, binding, expected_message, turn_id):
    trusted_binding = deepcopy(binding)

    async def gloria_run_turn(message: str) -> dict:
        """Run the admitted original turn; model-authored changes are rejected."""
        if not isinstance(message, str) or message != expected_message:
            raise ValueError("original turn mismatch")
        state = await workflow.run(trusted_binding, expected_message, turn_id=turn_id)
        return {"response": state["response"]["message"], "language": state["response"]["language"], "rule_ids": state["workflow_state"]["policy_decision"]["rule_ids"], "turn_id": state["turn"]["turn_id"]}

    return gloria_run_turn


def create_mcp_server(workflow, binding, expected_message, turn_id):
    """Register a per-turn stdio server in the trusted host process.

    The host owns its lifetime and admitted context. Do not serve this closure
    on shared HTTP or infer a customer binding from tool arguments.
    """
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("gloria-admitted-turn")
    server.tool(name="gloria_run_turn")(make_run_turn_tool(workflow, binding, expected_message, turn_id))
    return server
