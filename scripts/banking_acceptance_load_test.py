"""Acceptance-runner negative controls; no worker, customer auth or model calls."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("banking_acceptance_load", Path(__file__).with_name("banking_acceptance_load.py"))
load = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = load
spec.loader.exec_module(load)


class AcceptanceRunnerTests(unittest.TestCase):
    def body(self, ref="txn_0123456789ab", conversation="test-A"):
        return {"conversation_id": conversation, "status": "completed", "messages": [
            {"role": "assistant", "tool_calls": [{"id": "one"}]},
            {"role": "tool", "content": json.dumps({"content": [{"type": "text", "text": json.dumps(
                {"transactions": [{"transaction_reference": ref}]})}]})}]}

    def test_prose_without_structured_tool_evidence_cannot_pass(self):
        body = self.body()
        body["messages"] = [{"role": "assistant", "content": "txn_0123456789ab"}]
        with self.assertRaisesRegex(load.AcceptanceError, "process_tool_evidence_missing"):
            load.audit_response({"allowed_references": ["txn_0123456789ab"]}, body)

    def test_foreign_result_is_detected_even_when_own_reference_also_present(self):
        body = self.body()
        body["messages"].append({"role": "tool", "content": json.dumps({"transaction_reference": "txn_ffffffffffff"})})
        with self.assertRaisesRegex(load.AcceptanceError, "foreign_transaction_result"):
            load.audit_response({"allowed_references": ["txn_0123456789ab"]}, body)

    def test_structured_wrapped_result_matches_private_oracle(self):
        self.assertEqual(load.audit_response({"allowed_references": ["txn_0123456789ab"]}, self.body()), "test-A")

    def test_explicit_response_oracle_does_not_silently_count_as_tool_proof(self):
        body = {"conversation_id": "test-A", "status": "completed", "choices": [
            {"message": {"content": "Transaction txn_0123456789ab."}}]}
        case = {"allowed_references": ["txn_0123456789ab"]}
        self.assertEqual(load.audit_response(case, body, "response"), "test-A")
        with self.assertRaisesRegex(load.AcceptanceError, "process_tool_evidence_missing"):
            load.audit_response(case, body)

    def test_shared_conversation_cannot_pass_distinct_owner_phase(self):
        samples = [load.Sample(True, "ok", 0.1, 0.02, "same"), load.Sample(True, "ok", 0.2, 0.03, "same")]
        evidence = load.summarize(samples, 0.25)
        self.assertFalse(evidence["passed"])
        self.assertIn("conversation_reused_across_distinct_owners", evidence["errors"])
        self.assertNotIn("same", json.dumps(evidence))
        self.assertIsNone(evidence["maximum_server_active_runs"])

    def test_manifest_rejects_static_workload_and_repeated_owners_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            graph_path = Path(directory) / "graph.json"
            graph_path.write_text(json.dumps({"name": "approved", "nodes": [{"type": "static"}]}), encoding="utf-8")
            config = {"base_url": "http://127.0.0.1:43420", "model": "flow-approved",
                "provider_scope": "configured-api", "approved_flow_file": str(graph_path), "cases": []}
            with self.assertRaisesRegex(load.AcceptanceError, "process_flow_required"):
                load.validate_manifest(config, 1)
            graph_path.write_text(json.dumps({"name": "approved", "nodes": [{"type": "process"}]}), encoding="utf-8")
            config["cases"] = [{"subject": "A", "prompt": "list", "allowed_references": ["txn_0123456789ab"]}] * 2
            with self.assertRaisesRegex(load.AcceptanceError, "distinct_subjects_required"):
                load.validate_manifest(config, 2)

    def test_percentiles_include_failed_request_latency(self):
        evidence = load.summarize([load.Sample(True, "ok", 0.1, conversation="A"),
                                   load.Sample(False, "http_429", 2)], 2)
        self.assertEqual(evidence["full_response_seconds"]["p95"], 2)
        self.assertFalse(evidence["passed"])
        self.assertEqual(evidence["errors"], {"http_429": 1})


if __name__ == "__main__":
    unittest.main()
