"""Keep native-tool and snapshot-summary load evidence distinct."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from scripts.banking_acceptance_load import AcceptanceError, validate_manifest


class AcceptanceScopeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "flow.json"
        self.graph = {"name": "Customer", "nodes": [
            {"id": "start", "type": "start", "data": {"properties": {}}},
            {"id": "static", "type": "static", "data": {"properties": {"entries": [
                {"kind": "toolCall", "executionMode": "real", "serverName": "Banking MCP",
                 "toolName": "list_my_transactions", "argumentsJson": '{"limit":1}'}]}}},
            {"id": "process", "type": "process", "data": {"properties": {
                "boundModel": "existing-model", "inputMode": "full-history"}}},
            {"id": "bank", "type": "mcp", "data": {"properties": {
                "boundServer": "Banking MCP", "enabledTools": ["list_my_transactions"]}}}],
            "edges": [{"source": "start", "target": "static", "data": {"edgeType": "standard"}},
                      {"source": "static", "target": "process", "data": {"edgeType": "standard"}},
                      {"source": "static", "target": "bank", "sourceHandle": "static-right-mcp",
                       "targetHandle": "mcp-left", "data": {"edgeType": "mcp"}}]}
        self.config = {"base_url": "http://127.0.0.1:43420", "model": "flow-Customer",
            "provider_scope": "configured-codex-restricted", "approved_flow_file": str(self.path),
            "workload": "static-prefetch-model-summary", "oracle_scope": "response",
            "protected_server_name": "Banking MCP", "summary_model_ref": "existing-model",
            "cases": [{"subject": "a", "prompt": "Summarize my snapshot.",
                       "allowed_references": ["txn_0123456789ab"]}]}

    def validate(self):
        self.path.write_text(json.dumps(self.graph), encoding="utf-8")
        validate_manifest(self.config, 1)

    def test_explicit_real_snapshot_with_model_is_accepted(self):
        self.validate()

    def test_default_does_not_count_static_as_autonomous_model_tool_proof(self):
        del self.config["workload"]
        with self.assertRaisesRegex(AcceptanceError, "static_tool_workload_not_model_proof"):
            self.validate()

    def test_static_only_cannot_claim_model_summary(self):
        self.graph["nodes"] = [n for n in self.graph["nodes"] if n["type"] != "process"]
        with self.assertRaisesRegex(AcceptanceError, "process_flow_required"):
            self.validate()

    def test_mock_or_authored_answer_cannot_replace_real_summary_evidence(self):
        original = copy.deepcopy(self.graph)
        for replacement in ({"kind": "message", "role": "assistant", "content": "Done"},
                            {"kind": "toolCall", "executionMode": "mock", "serverName": "Banking MCP",
                             "toolName": "list_my_transactions", "argumentsJson": '{"limit":1}'}):
            self.graph = copy.deepcopy(original)
            self.graph["nodes"][1]["data"]["properties"]["entries"].append(replacement)
            with self.subTest(replacement=replacement["kind"]), self.assertRaises(AcceptanceError):
                self.validate()

    def test_selector_or_unbounded_prefetch_is_rejected(self):
        for args in ('{"limit":1,"customer_id":"b"}', '{"limit":20}', '{"limit":true}'):
            self.graph["nodes"][1]["data"]["properties"]["entries"][0]["argumentsJson"] = args
            with self.subTest(args=args), self.assertRaisesRegex(AcceptanceError, "bounded_snapshot_arguments_required"):
                self.validate()

    def test_process_handoff_would_change_the_claimed_tool_free_workload(self):
        self.graph["edges"].append({"source": "process", "target": "finish"})
        with self.assertRaisesRegex(AcceptanceError, "terminal_tool_free_process_required"):
            self.validate()

    def test_unbound_mcp_and_wrong_model_are_rejected(self):
        self.config["summary_model_ref"] = "other-model"
        with self.assertRaises(AcceptanceError):
            self.validate()
        self.config["summary_model_ref"] = "existing-model"
        self.graph["edges"] = self.graph["edges"][:2]
        with self.assertRaisesRegex(AcceptanceError, "connected_real_snapshot_tool_required"):
            self.validate()

    def test_prefetch_cannot_be_orphaned_or_bypassed(self):
        original = copy.deepcopy(self.graph)
        for index in (0, 1):
            self.graph = copy.deepcopy(original)
            del self.graph["edges"][index]
            with self.subTest(missing_edge=index), self.assertRaisesRegex(AcceptanceError, "linear_snapshot_then_summary_required"):
                self.validate()
        self.graph = copy.deepcopy(original)
        self.graph["edges"][0]["target"] = "process"
        with self.assertRaisesRegex(AcceptanceError, "linear_snapshot_then_summary_required"):
            self.validate()

    def test_incoming_mcp_attachment_and_inline_binding_are_rejected(self):
        self.graph["edges"].append({"source": "bank", "target": "process", "data": {"edgeType": "mcp"}})
        with self.assertRaises(AcceptanceError):
            self.validate()
        self.graph["edges"].pop()
        self.graph["nodes"][2]["data"]["properties"]["mcpNodes"] = [{"id": "bank"}]
        with self.assertRaisesRegex(AcceptanceError, "terminal_tool_free_process_required"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
