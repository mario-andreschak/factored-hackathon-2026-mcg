"""Compile/install ONE reusable operator graph with existing local FLUJO APIs.

No runtime MCP configs, models, Slack target, containers or customer flows change.
Default: validate and compile without saving. --write saves only Banking Operator.
Credentials come from FLUJO_API_TOKEN in the environment, never command arguments.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

from .flow import BANK_TOOLS, MARKER, TICKET_TOOL, build_operator_spec


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None  # Never forward host credentials to a redirect destination.


class LocalFlujo:
    def __init__(self, base_url: str, workspace: str, token: str = ""):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("local_flujo_url_required")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", workspace):
            raise ValueError("invalid_workspace")
        self.base_url, self.workspace, self.token = base_url.rstrip("/") + "/", workspace, token

    def request(self, route: str, *, body: dict | None = None, method: str | None = None):
        url = urllib.parse.urljoin(self.base_url, route)
        url += "?" + urllib.parse.urlencode({"workspace": self.workspace})
        headers = {"accept": "application/json"}
        if self.token:
            headers["authorization"] = "Bearer " + self.token
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers["content-type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=30) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            raise ValueError(f"flujo_http_{exc.code}") from None
        except (OSError, ValueError):
            raise ValueError("flujo_request_failed") from None
        if isinstance(result, dict) and result.get("error"):
            raise ValueError("flujo_request_rejected")
        return result


def _tools(client, server: str) -> dict:
    result = client.request("api/mcp/servers/" + urllib.parse.quote(server, safe="") + "/tools")
    if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
        raise ValueError("invalid_tool_inventory")
    return {tool["name"]: tool for tool in result["tools"] if isinstance(tool, dict) and isinstance(tool.get("name"), str)}


def _operator_status(client, server: str) -> None:
    result = client.request("api/mcp/servers/" + urllib.parse.quote(server, safe="") + "/tools/banking_status",
                            body={"args": {}})
    if not isinstance(result, dict) or result.get("success") is not True:
        raise ValueError("operator_profile_required")
    data = result.get("data", {})
    if not isinstance(data, dict) or data.get("isError") is True:
        raise ValueError("operator_profile_required")
    status = data.get("structuredContent")
    if not isinstance(status, dict):
        try:
            blocks = [json.loads(block["text"]) for block in data.get("content", [])
                      if isinstance(block, dict) and block.get("type") == "text"]
            status = blocks[0] if len(blocks) == 1 else {}
        except (ValueError, TypeError, KeyError):
            raise ValueError("operator_profile_required") from None
    if (not isinstance(status, dict) or status.get("mode") != "operator-test"
            or status.get("customer_selection_required") is not True
            or status.get("conversation_correlation_required") is not True
            or status.get("dataset_ready") is not True):
        raise ValueError("operator_profile_required")


def _registration_guards(client, bank_server: str, ticket_server: str) -> None:
    # Administrative responses are inspected in memory only, never printed or
    # copied into the graph; these objects can contain runtime configuration.
    bank = client.request("api/mcp/servers/" + urllib.parse.quote(bank_server, safe=""))
    if not isinstance(bank, dict) or bank.get("name") != bank_server or bank.get("transport") != "stdio":
        raise ValueError("in_worker_stdio_operator_required")
    presets = bank.get("toolParameterPresets", {})
    if not isinstance(presets, dict):
        raise ValueError("invalid_operator_server_presets")
    for tool in ("list_my_transactions", "get_my_transaction"):
        fixed = presets.get(tool, {})
        if not isinstance(fixed, dict) or "customer_id" in fixed:
            # Empty-string/null presets are still fixed at dispatch; truthiness
            # is not a sufficient test. Do not mutate shared server presets.
            raise ValueError("visible_operator_customer_selector_required")
    ticket = client.request("api/mcp/servers/" + urllib.parse.quote(ticket_server, safe=""))
    if (not isinstance(ticket, dict) or ticket.get("name") != ticket_server or ticket.get("transport") != "stdio"
            or not isinstance(ticket.get("source"), dict)
            or ticket["source"].get("id") != "@mario.andreschak/mcp-flujo"):
        raise ValueError("shipped_stdio_ticket_server_required")


def prepare_operator_flow(client, *, model_ref: str, bank_server: str, ticket_server: str,
                          start_date: str, end_date: str, name: str = "Banking Operator") -> tuple[dict, dict | None]:
    models = client.request("api/model")
    if not isinstance(models, list):
        raise ValueError("invalid_model_inventory")
    matching = [m for m in models if isinstance(m, dict) and model_ref in {m.get("id"), m.get("name"), m.get("displayName")}]
    if len(matching) != 1 or not isinstance(matching[0].get("id"), str):
        raise ValueError("configured_model_required")
    banks, tickets = _tools(client, bank_server), _tools(client, ticket_server)
    if not set(BANK_TOOLS) <= banks.keys() or TICKET_TOOL not in tickets:
        raise ValueError("required_operator_tools_missing")
    _operator_status(client, bank_server)
    _registration_guards(client, bank_server, ticket_server)
    for tool in ("list_my_transactions", "get_my_transaction"):
        schema = banks[tool].get("inputSchema", {})
        if "customer_id" not in schema.get("properties", {}):
            raise ValueError("selectable_operator_contract_required")
    flows = client.request("api/flow")
    if not isinstance(flows, list):
        raise ValueError("invalid_flow_inventory")
    matching_flows = [flow for flow in flows if isinstance(flow, dict) and flow.get("name") == name]
    if len(matching_flows) > 1:
        raise ValueError("ambiguous_operator_flow")
    existing = matching_flows[0] if matching_flows else None
    if existing and existing.get("description") != MARKER:
        raise ValueError("unowned_operator_flow")
    spec = build_operator_spec(model=matching[0]["id"], bank_server=bank_server, ticket_server=ticket_server,
                               start_date=start_date, end_date=end_date, name=name)
    compiled = client.request("api/flow/compile", body={"spec": spec, "save": False})
    if (not isinstance(compiled, dict) or not isinstance(compiled.get("flow"), dict)
            or compiled.get("saved") is True or len(compiled.get("flows", [])) != 1):
        raise ValueError("invalid_compiled_operator_graph")
    validation = compiled.get("validation", {})
    if (not isinstance(validation, dict) or validation.get("isRunnable") is not True
            or validation.get("errorCount", 0) != 0
            or any(issue.get("severity") == "error" for issue in validation.get("issues", []))):
        raise ValueError("operator_graph_validation_failed")
    flow = copy.deepcopy(compiled["flow"])
    flow["name"], flow["description"] = name, MARKER
    if existing:
        flow["id"] = existing["id"]
    nodes = flow.get("nodes", [])
    processes = [node for node in nodes if node.get("type") == "process"]
    mcp_nodes = [node for node in nodes if node.get("type") == "mcp"]
    if (len(processes) != 1 or len(mcp_nodes) != 2
            or any(node.get("type") not in {"start", "process", "mcp", "finish"} for node in nodes)):
        raise ValueError("unexpected_operator_graph_capability")
    expected_tools = {bank_server: set(BANK_TOOLS), ticket_server: {TICKET_TOOL}}
    seen = set()
    for node in mcp_nodes:
        properties = node.get("data", {}).get("properties", {})
        server = properties.get("boundServer")
        if server in seen or server not in expected_tools or set(properties.get("enabledTools", [])) != expected_tools[server]:
            raise ValueError("unexpected_operator_graph_capability")
        seen.add(server)
        # Runtime omission enables all resources. An explicit empty selection
        # keeps the shipped control server's unrelated run resources out of this
        # operator graph; disabling them does not change other saved flows.
        properties["enabledResources"] = []
        properties["enabledPrompts"] = []
        if server == bank_server:
            presets = properties.setdefault("toolParameterPresets", {})
            for tool in ("list_my_transactions", "get_my_transaction"):
                if "conversation_id" in banks[tool].get("inputSchema", {}).get("properties", {}):
                    presets[tool] = {"conversation_id": "@current.conversation.id"}
        else:
            fields = tickets[TICKET_TOOL].get("inputSchema", {}).get("properties", {})
            fixed = {"title": "Banking inquiry: local human review", "labels": "banking,local-handoff",
                     "conversation_id": "@current.conversation.id", "flow_id": "@current.flow.id"}
            if not set(fixed) <= set(fields):
                raise ValueError("ticket_context_contract_required")
            properties.setdefault("toolParameterPresets", {})[TICKET_TOOL] = fixed
    return flow, existing


def install_operator_flow(client, *, write: bool = False, **options) -> dict:
    flow, existing = prepare_operator_flow(client, **options)
    if write:
        route = "api/flow/" + urllib.parse.quote(existing["id"], safe="") if existing else "api/flow"
        client.request(route, body=flow, method="PUT" if existing else "POST")
        stored = client.request("api/flow/" + urllib.parse.quote(flow["id"], safe=""))
        if stored.get("id") != flow["id"] or stored.get("name") != flow["name"] or stored.get("nodes") != flow["nodes"]:
            raise ValueError("operator_graph_readback_failed")
    return {"saved": write, "updated": bool(existing) and write, "flow": flow}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:43420")
    parser.add_argument("--workspace", default="default-workspace")
    parser.add_argument("--model", default="GPT-6 Sol")
    parser.add_argument("--bank-server", required=True)
    parser.add_argument("--ticket-server", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--flow-name", default="Banking Operator")
    parser.add_argument("--write", action="store_true", help="Save the ONE operator graph; never changes Slack target.")
    args = parser.parse_args()
    try:
        result = install_operator_flow(LocalFlujo(args.base_url, args.workspace, os.getenv("FLUJO_API_TOKEN", "")),
                                       write=args.write, model_ref=args.model, bank_server=args.bank_server,
                                       ticket_server=args.ticket_server, start_date=args.start_date,
                                       end_date=args.end_date, name=args.flow_name)
    except ValueError as exc:
        print(json.dumps({"error": str(exc)}))
        return 1
    # The graph contains no selected customer or credential; model configuration is never printed.
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
