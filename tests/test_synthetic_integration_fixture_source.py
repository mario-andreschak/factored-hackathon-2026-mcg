"""Pure source/protocol gates. No app/server/pipeline/StateStore is started."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts/synthetic_integration"), str(ROOT / "scripts/synthetic_integration/fixture")]
import contract
import deterministic_provider as model
import integration_provider as integration
import fixture_setup
from assemble_source import hosted_publication
from observer_adapter import complete_bootstrap_log, token_from_cookie, transport_counts, verify_bootstrap_records


def request(stream=False):
    return {"model": "synthetic-fixture-model", "stream": stream, "messages": [{"role": "user", "content": "fixture"}],
            "tools": [{"type": "function", "function": {"name": "handoff_to_finish",
                "parameters": {"type": "object", "properties": {}}}}]}


def events(extra=()):
    generation = "a" * 32
    rows = [{"event": "observer_ready"}, {"event": "bank_transport_attached"},
            {"event": "send_started", "name": "confirm_simulated_intake", "send": 1, "child": 2},
            {"event": "send_completed", "name": "confirm_simulated_intake", "send": 1, "child": 2}, *extra]
    return [{"generation": generation, "pid": 1, "sequence": i + 1, **row} for i, row in enumerate(rows)]


def encoded(rows):
    return b"".join(json.dumps(row).encode() + b"\n" for row in rows)


def bootstrap_records():
    # Validator unit inputs only. Never loaded into a worker or used as runtime evidence.
    conversation, run = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-9bbb-bbbbbbbbbbbb"
    graph = json.loads((ROOT / "scripts/synthetic_integration/fixture/flow-snapshot.json").read_bytes())
    owner = {"issuer": "fixture", "subject": "fictional-owner", "graph": "c" * 64,
             "deployment": "fixture", "workspace": "synthetic-checkpoint"}
    issued = {"call_fixture": {"function": "handoff_to_finish", "arguments_sha256": hashlib.sha256(b"{}").hexdigest(),
                              "wire_sha256": "d" * 64}}
    state = {"conversationId": conversation, "flowId": graph["id"], "flowSnapshot": graph, "status": "completed",
             "currentNodeId": "finish", "source": "api", "executionExtensionOwned": True, "logicalRunId": run,
             "recovery": {"runId": run, "classification": "completed"}, "messages": [
                 {"role": "assistant", "tool_calls": [{"id": "call_fixture", "type": "function",
                     "function": {"name": "handoff_to_finish", "arguments": "{}"}}]},
                 {"role": "tool", "tool_call_id": "call_fixture", "content": json.dumps({
                     "status": "Handoff processed", "targetNodeId": "finish"})}]}
    rows = [{"type": "run:start", "flowId": graph["id"]},
            {"type": "recovery:transition", "recovery": {"runId": run, "classification": "running"}},
            {"type": "node:enter", "node": {"nodeId": "start"}},
            {"type": "node:exit", "node": {"nodeId": "start"}, "action": "start-process"},
            {"type": "node:enter", "node": {"nodeId": "process"}},
            {"type": "node:exit", "node": {"nodeId": "process"}, "action": "process-finish"},
            {"type": "handoff", "from": {"nodeId": "process"}, "toNodeId": "finish", "edgeId": "process-finish"},
            {"type": "node:enter", "node": {"nodeId": "finish"}},
            {"type": "node:exit", "node": {"nodeId": "finish"}, "action": "FINAL_RESPONSE"},
            {"type": "recovery:transition", "recovery": {"runId": run, "classification": "completed"}},
            {"type": "run:done", "status": "completed"}]
    # Durable seq starts at zero; nonpersisted events can leave gaps.
    rows = [{**row, "conversationId": conversation, "seq": i * 2} for i, row in enumerate(rows)]
    return state, rows, {"graph": graph, "conversation": conversation, "accepted_routing": issued,
        "reply": {"mode": "flujo", "status": "completed"}, "provider_rejections": 0,
        "owner": owner, "expected_owner": copy.deepcopy(owner)}


class FixtureSourceTests(unittest.TestCase):
    def test_bootstrap_requires_correlated_completed_finish(self):
        state, rows, arguments = bootstrap_records()
        proof = verify_bootstrap_records(state, rows, **arguments)
        self.assertTrue(proof["finish_verified"])
        self.assertEqual(proof["status"], "completed")
        self.assertEqual(proof["routing_wire_sha256"], "d" * 64)
        self.assertNotIn("conversationId", proof)
        self.assertNotIn("subject", proof)

    def test_bootstrap_waiting_rejected_even_with_accepted_provider(self):
        state, rows, arguments = bootstrap_records()
        for bad in ({**arguments, "reply": {"mode": "flujo", "status": "waiting_for_input"}},
                    {**arguments, "reply": {"mode": "preview", "status": "completed"}},
                    {**arguments, "provider_rejections": 1}):
            with self.assertRaises(contract.CheckpointError):
                verify_bootstrap_records(state, rows, **bad)
        with self.assertRaises(contract.CheckpointError):
            verify_bootstrap_records({**state, "status": "waiting_for_input"}, rows, **arguments)

    def test_bootstrap_provider_acceptance_without_finish_rejected(self):
        state, rows, arguments = bootstrap_records()
        for omitted in ("node:enter", "node:exit", "handoff", "recovery:transition", "run:done"):
            incomplete = [row for row in rows if row["type"] != omitted]
            with self.assertRaises(contract.CheckpointError):
                verify_bootstrap_records(state, incomplete, **arguments)
        without_finish = [row for row in rows if not (
            row["type"] in {"node:enter", "node:exit"} and row.get("node", {}).get("nodeId") == "finish")]
        with self.assertRaises(contract.CheckpointError):
            verify_bootstrap_records(state, without_finish, **arguments)
        without_result = {**state, "messages": state["messages"][:1]}
        with self.assertRaises(contract.CheckpointError):
            verify_bootstrap_records(without_result, rows, **arguments)
        wrong_result = copy.deepcopy(state)
        wrong_result["messages"][-1]["content"] = json.dumps({"status": "Handoff processed", "targetNodeId": "other"})
        with self.assertRaises(contract.CheckpointError):
            verify_bootstrap_records(wrong_result, rows, **arguments)

    def test_bootstrap_foreign_owner_run_conversation_and_route_rejected(self):
        state, rows, arguments = bootstrap_records()
        changed = copy.deepcopy(rows)
        changed[-2]["recovery"]["runId"] = "cccccccc-cccc-4ccc-accc-cccccccccccc"
        other_conversation = copy.deepcopy(rows)
        other_conversation[-1]["conversationId"] = "cccccccc-cccc-4ccc-accc-cccccccccccc"
        wrong_route = copy.deepcopy(rows)
        wrong_route[6]["edgeId"] = "other-edge"
        bad_finish = copy.deepcopy(rows)
        bad_finish[8]["action"] = "WAIT_FOR_INPUT"
        repeated_seq = copy.deepcopy(rows)
        repeated_seq[-1]["seq"] = repeated_seq[-2]["seq"]
        for altered in (changed, other_conversation, wrong_route, bad_finish, repeated_seq):
            with self.assertRaises(contract.CheckpointError):
                verify_bootstrap_records(state, altered, **arguments)
        for bad in ({**arguments, "owner": {**arguments["owner"], "subject": "foreign"}},
                    {**arguments, "accepted_routing": {}}, {**arguments, "conversation": "-" * 36}):
            with self.assertRaises(contract.CheckpointError):
                verify_bootstrap_records(state, rows, **bad)

    def test_bootstrap_partial_append_waits_before_json_parsing(self):
        _, rows, _ = bootstrap_records()
        raw = encoded(rows)
        self.assertIsNone(complete_bootstrap_log(b""))
        self.assertIsNone(complete_bootstrap_log(raw + b'{"type":'))
        self.assertEqual(complete_bootstrap_log(raw), rows)
        with self.assertRaises(contract.CheckpointError):
            complete_bootstrap_log(raw + b'{"type":\n')

    def test_inner_preview_and_outer_artifact_digests_are_distinct_fields(self):
        preview = {"schema": "private-synthetic-source-review/v2", "source_head": "a" * 40,
                   "digest_scope": "local_preview_zip_not_github_artifact_archive", "hosted_artifact": None,
                   "inner_preview_zip_sha256": "b" * 64, "manifest_sha256": "c" * 64}
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
               "GITHUB_REPOSITORY": contract.REPOSITORY, "GITHUB_SHA": "a" * 40,
               "GITHUB_RUN_ID": "12", "GITHUB_RUN_ATTEMPT": "1", "SOURCE_ARTIFACT_ID": "34",
               "SOURCE_ARTIFACT_DIGEST": "d" * 64}
        recorded = hosted_publication(preview, env)
        self.assertEqual(recorded["inner_preview_zip_sha256"], "b" * 64)
        self.assertEqual(recorded["outer_github_artifact"]["zip_sha256"], "d" * 64)
        self.assertEqual(recorded["checkpoint_bundle_zip_sha256_source"], "outer_github_artifact.zip_sha256")
        self.assertFalse(recorded["run_conclusion_independently_verified"])
        for bad in ({**preview, "zip_sha256": "b" * 64}, {**preview, "source_head": "e" * 40},
                    {**preview, "digest_scope": "github_downloadable_artifact_archive"}):
            with self.assertRaises(contract.CheckpointError):
                hosted_publication(bad, env)
        with self.assertRaises(contract.CheckpointError):
            hosted_publication(preview, {**env, "SOURCE_ARTIFACT_DIGEST": ""})

    def test_finish_only_wire_and_sse(self):
        for streaming in (False, True):
            result = model.completion(request(streaming))
            self.assertEqual(result["choices"][0]["message"]["tool_calls"][0]["function"],
                             {"name": "handoff_to_finish", "arguments": "{}"})
        chunks = model.stream_chunks(result).decode().split("\n\n")
        self.assertEqual(chunks[-2], "data: [DONE]")
        values = [json.loads(chunk.removeprefix("data: ")) for chunk in chunks[:-2]]
        self.assertEqual(values[1]["choices"][0]["delta"]["tool_calls"][0]["index"], 0)
        self.assertEqual(values[2]["choices"][0]["finish_reason"], "tool_calls")

    def test_wire_schema_drift_rejected(self):
        original = request()
        for field, value in (("name", "handoff_to_other"), ("parameters", None),
                             ("parameters", {"type": "object"}),
                             ("parameters", {"type": "array", "properties": {}}),
                             ("parameters", {"type": "object", "properties": {}, "required": ["message"]})):
            body = copy.deepcopy(original)
            body["tools"][0]["function"][field] = value
            with self.assertRaises(contract.CheckpointError):
                model.completion(body)
        for value in (0, "true", None):
            with self.assertRaises(contract.CheckpointError):
                model.completion({**original, "stream": value})

    def test_cookie_header_exact_token(self):
        self.assertEqual(token_from_cookie("other=x; flujo_bank_session=private-token; third=y"), "private-token")
        for header in ("other=x", "flujo_bank_session=a; flujo_bank_session=b", "flujo_bank_session="):
            with self.assertRaises(contract.CheckpointError):
                token_from_cookie(header)

    def test_transport_counts_acknowledged_sends(self):
        counts = transport_counts(encoded(events()), generations={"a" * 32})
        self.assertEqual(counts["tool_calls"]["confirm_simulated_intake"], 1)
        self.assertEqual(sum(counts["tool_calls"].values()), 1)
        self.assertEqual(counts["external_network_attempts"], 0)
        self.assertEqual(counts["forbidden_dispatch_attempts"], 0)
        self.assertNotIn("forbidden_writes", counts)

    def test_observer_gaps_fail_closed(self):
        original = events()
        variants = [original[:-1], original[1:], original + [original[-1]],
                    events([{"event": "send_failed"}]), events([{"event": "observer_invalid"}])]
        changed = copy.deepcopy(original)
        changed[-1]["name"] = "read_intake_receipt"
        variants.append(changed)
        for rows in variants:
            with self.assertRaises(contract.CheckpointError):
                transport_counts(encoded(rows), generations={"a" * 32})
        with self.assertRaises(contract.CheckpointError):
            transport_counts(encoded(original), generations={"a" * 32, "b" * 32})
        with self.assertRaises(contract.CheckpointError):
            transport_counts(encoded(original).rstrip(), generations={"a" * 32})

    def test_attempt_counters_do_not_claim_write_observation(self):
        counts = transport_counts(encoded(events([{"event": "external_attempt"}, {"event": "forbidden_tool"}])),
                                  generations={"a" * 32})
        self.assertEqual(counts["external_network_attempts"], 1)
        self.assertEqual(counts["forbidden_dispatch_attempts"], 1)

    def test_runtime_hold_precedes_process_network_state(self):
        env = {"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_OS": "Linux",
               "GITHUB_REPOSITORY": contract.REPOSITORY, "GITHUB_SHA": "a" * 40}
        with patch.dict("os.environ", env, clear=True), patch("subprocess.run") as run, \
             patch("subprocess.Popen") as popen, patch.object(Path, "mkdir") as mkdir, \
             patch.object(model, "ThreadingHTTPServer") as server:
            for fn in (integration.Provider(ROOT / "unused-synthetic-fixture",
                                           phase="stock-missing-coverage").start,
                       model.FixtureProvider(8202, "unused").start,
                       lambda: fixture_setup.setup(Path("/unused"), attested=False, service_token="unused")):
                with self.assertRaisesRegex(contract.CheckpointError, "integration_checkpoint_held"):
                    fn()
            run.assert_not_called()
            popen.assert_not_called()
            mkdir.assert_not_called()
            server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
