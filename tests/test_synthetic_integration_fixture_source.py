"""Pure source/protocol gates. No app/server/pipeline/StateStore is started."""
import copy
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
from observer_adapter import token_from_cookie, transport_counts


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


class FixtureSourceTests(unittest.TestCase):
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
