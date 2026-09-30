"""Installer verifies capabilities without saving configs, models or customer flows."""
import copy
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from demo.flow import BANK_TOOLS, MARKER, build_operator_spec, historical_window
from demo.install_operator_flow import LocalFlujo, install_operator_flow


class FakeFlujo:
    def __init__(self):
        self.calls = []
        self.flows = [{"id": "unrelated", "name": "Slack Assistant", "nodes": ["preserve"]}]
        self.status = {"mode": "operator-test", "dataset_ready": True,
                       "customer_selection_required": True, "conversation_correlation_required": True}
        self.validation = {"isRunnable": True, "errorCount": 0, "issues": []}
        self.extra_tool = False
        self.selector = True
        self.server_presets = {}

    def request(self, route, *, body=None, method=None):
        self.calls.append((route, copy.deepcopy(body), method))
        if route == "api/model":
            return [{"id": "configured-sol", "displayName": "GPT-6 Sol", "adapter": "codex-cli"}]
        if route.endswith("/tools/banking_status"):
            return {"success": True, "data": {"structuredContent": self.status}}
        if route == "api/mcp/servers/Banking%20Operator%20MCP":
            return {"name": "Banking Operator MCP", "transport": "stdio", "toolParameterPresets": self.server_presets}
        if route == "api/mcp/servers/FLUJO":
            return {"name": "FLUJO", "transport": "stdio", "source": {"id": "@mario.andreschak/mcp-flujo"}}
        if route.endswith("/tools"):
            names = BANK_TOOLS if "/Banking%20Operator%20MCP/" in route else ["create_ticket_for_human"]
            return {"tools": [{"name": name, "inputSchema": {"properties":
                ({"customer_id": {"type": "string"}, "conversation_id": {"type": "string"}} if self.selector else {})
                if name != "create_ticket_for_human" else {key: {"type": "string"}
                    for key in ("message", "title", "labels", "conversation_id", "flow_id")}}}
                for name in names]}
        if route == "api/flow" and body is None:
            return copy.deepcopy(self.flows)
        if route == "api/flow/compile":
            spec = body["spec"]
            nodes = [{"id": n["key"], "type": n["type"], "data": {"properties": {}}} for n in spec["nodes"]]
            for i, server in enumerate(spec["nodes"][1]["servers"]):
                nodes.append({"id": "mcp-" + str(i), "type": "mcp", "data": {"properties": {
                    "boundServer": server["name"], "enabledTools": server["tools"] + (["read_conversation"] if self.extra_tool else [])}}})
            flow = {"id": "permanent-operator", "name": spec["name"], "description": MARKER, "nodes": nodes, "edges": []}
            return {"saved": False, "flow": flow, "flows": [flow], "validation": self.validation}
        if body is not None and (route == "api/flow" or route.startswith("api/flow/")):
            self.flows = [f for f in self.flows if f["id"] != body["id"]] + [copy.deepcopy(body)]
            return body
        if route.startswith("api/flow/"):
            return next(copy.deepcopy(f) for f in self.flows if f["id"] == route.split("/")[-1])
        raise AssertionError(route)


OPTIONS = dict(model_ref="GPT-6 Sol", bank_server="Banking Operator MCP", ticket_server="FLUJO",
               start_date="2026-06-01", end_date="2026-06-17")


class OperatorFlowTests(unittest.TestCase):
    def test_historical_window_limit_and_scope(self):
        self.assertEqual(historical_window("2026-05-18", "2026-06-17"), ("2026-05-18", "2026-06-17"))
        for start, end in [("2026-05-17", "2026-06-17"), ("2026-06-02", "2026-06-01"), ("2026-02-31", "2026-03-01")]:
            with self.subTest(start=start), self.assertRaises(ValueError):
                historical_window(start, end)
        with self.assertRaises(ValueError):
            build_operator_spec(model="Sol", bank_server="Bank", ticket_server="FLUJO", start_date="2026-06-01",
                                end_date="2026-06-17", name="Slack Assistant")

    def test_prepare_without_save_and_nonsecret_conversation_preset(self):
        client = FakeFlujo()
        result = install_operator_flow(client, **OPTIONS)
        self.assertFalse(result["saved"])
        self.assertEqual(len(client.flows), 1)
        self.assertFalse(any(route in {"api/flow", "api/flow/permanent-operator"} and body is not None
                             for route, body, method in client.calls))
        bank = next(n for n in result["flow"]["nodes"] if n["id"] == "mcp-0")
        presets = bank["data"]["properties"]["toolParameterPresets"]
        self.assertEqual(presets["list_my_transactions"], {"conversation_id": "@current.conversation.id"})
        self.assertNotIn("customer_id", presets["list_my_transactions"])
        ticket = next(n for n in result["flow"]["nodes"] if n["id"] == "mcp-1")
        fixed = ticket["data"]["properties"]["toolParameterPresets"]["create_ticket_for_human"]
        self.assertEqual(fixed["flow_id"], "@current.flow.id")
        self.assertEqual(fixed["conversation_id"], "@current.conversation.id")
        self.assertNotIn("message", fixed)
        for node in [bank, ticket]:
            self.assertEqual(node["data"]["properties"]["enabledResources"], [])
            self.assertEqual(node["data"]["properties"]["enabledPrompts"], [])
        self.assertFalse(any("config" in route or "chat/completions" in route for route, _, _ in client.calls))

    def test_create_then_update_one_permanent_flow_preserves_unrelated(self):
        client = FakeFlujo()
        original = copy.deepcopy(client.flows[0])
        first = install_operator_flow(client, write=True, **OPTIONS)
        second = install_operator_flow(client, write=True, **OPTIONS)
        self.assertTrue(first["saved"])
        self.assertTrue(second["updated"])
        self.assertEqual(len(client.flows), 2)
        self.assertEqual(next(f for f in client.flows if f["id"] == "unrelated"), original)
        self.assertEqual(second["flow"]["id"], first["flow"]["id"])

    def test_existing_unowned_graph_or_unsafe_capabilities_never_saved(self):
        for corruption in ["unowned", "extra_tool", "wrong_mode", "selector", "validation"]:
            client = FakeFlujo()
            if corruption == "unowned":
                client.flows.append({"id": "manual", "name": "Banking Operator"})
            elif corruption == "extra_tool":
                client.extra_tool = True
            elif corruption == "wrong_mode":
                client.status["mode"] = "delegated"
            elif corruption == "selector":
                client.selector = False
            else:
                client.validation["isRunnable"] = False
            with self.subTest(corruption=corruption), self.assertRaises(ValueError):
                install_operator_flow(client, write=True, **OPTIONS)
            self.assertFalse(any((route == "api/flow" or method == "PUT") and body is not None
                                 for route, body, method in client.calls))

    def test_credentials_not_accepted_in_url_and_public_hosts_rejected(self):
        for url in ["https://localhost:43420", "http://public.example", "http://secret@localhost:43420",
                    "http://localhost:43420?token=secret"]:
            with self.subTest(url=url), self.assertRaises(ValueError):
                LocalFlujo(url, "default-workspace")

    def test_inherited_customer_preset_cannot_silently_hide_operator_selector(self):
        for value in ["approved-A", "", None]:
            for tool in ["list_my_transactions", "get_my_transaction"]:
                client = FakeFlujo()
                client.server_presets = {tool: {"customer_id": value}}
                with self.subTest(tool=tool, value=value), self.assertRaisesRegex(ValueError, "visible_operator_customer_selector_required"):
                    install_operator_flow(client, write=True, **OPTIONS)
                self.assertEqual(len(client.flows), 1)

    def test_http_adapter_checks_local_auth_and_never_follows_redirects(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, self.headers.get("authorization")))
                if self.path.startswith("/redirect"):
                    self.send_response(302)
                    self.send_header("Location", "/credential-target")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode())

            def log_message(self, *_args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = LocalFlujo(f"http://127.0.0.1:{server.server_port}", "test-workspace", "synthetic-host-token")
            self.assertTrue(client.request("probe")["ok"])
            with self.assertRaisesRegex(ValueError, "flujo_http_302"):
                client.request("redirect")
            self.assertEqual(received, [("/probe?workspace=test-workspace", "Bearer synthetic-host-token"),
                                        ("/redirect?workspace=test-workspace", "Bearer synthetic-host-token")])
        finally:
            server.shutdown()
            worker.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
