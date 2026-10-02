"""Checks for source pagination, exact evidence, and safe offline artifacts."""
import importlib.util
import base64
import copy
import gzip
import json
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from history_sources.common import redact, sanitize, timestamp
from history_sources.slack import channels_from, messages_from, next_cursor
import build_dev_history as builder


class DevelopmentHistoryTests(unittest.TestCase):
    def test_live_topology_outage_retains_prior_execution_and_graph_records_with_capture_provenance(self):
        prior_time = "2026-10-01T04:00:00Z"
        prior = {
            "sessions": [{"id": "flujo:w:parent", "flowId": "graph", "eventIds": ["recorded"], "nodeActivity": [], "label": "Previously observed supervisor"}],
            "agentEdges": [{"id": "dispatch-edge", "from": "flujo:w:parent", "to": "flujo:w:child", "eventIds": ["recorded"], "timestamp": "2026-10-01T02:00:00Z"}],
            "flows": [{"id": "graph", "flowDefinitionId": "flow", "nodes": [{"id": "supervisor"}], "edges": [], "basis": "Persisted graph declaration"}],
            "events": [{"id": "recorded", "source": "flujo", "threadId": "parent", "timestamp": "2026-10-01T02:00:00Z", "body": "Recorded dispatch", "metadata": {"sessionId": "flujo:w:parent", "targetSessionId": "flujo:w:child", "flowId": "graph"}}],
            "notes": [], "stats": {},
        }
        fresh = {"sessions": [{"id": "codex:new", "label": "New live chat", "eventIds": [], "nodeActivity": []}],
                 "agentEdges": [], "flows": [], "events": [], "notes": ["Docker topology unavailable"], "stats": {"flujoReaderUnavailable": 1}}
        fake = SimpleNamespace(derive=lambda repo, results, config: copy.deepcopy(fresh))
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            file = cache / "topology.json"
            builder.atomic_json(file, {"collectedAt": prior_time, "result": prior})
            sources = {"codex": {"events": []}, "flujo": {"events": []}}
            with patch.object(builder.importlib, "import_module", return_value=fake):
                result = builder.topology_result(sources, {}, cache, False)
            self.assertEqual(result["stats"]["retainedRecords"], 4)
            for key in ("sessions", "agentEdges", "flows", "events"):
                old = next(item for item in result[key] if item["id"] == prior[key][0]["id"])
                self.assertTrue(old["retainedFromPriorCapture"])
                self.assertEqual(old["lastCapturedAt"], prior_time)
            self.assertEqual(result["events"][0]["timestamp"], prior["events"][0]["timestamp"])
            self.assertEqual(sources["flujo"]["events"][0]["id"], "recorded")
            self.assertFalse(next(s for s in result["sessions"] if s["id"] == "codex:new").get("retainedFromPriorCapture", False))
            saved = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(saved["result"]["flows"][0]["lastCapturedAt"], prior_time)
            self.assertTrue(any("Retained 4 prior topology records" in note for note in result["notes"]))
            # A second unavailable rebuild must not turn its previous cache
            # generation time into a newer apparent source-capture time.
            with patch.object(builder.importlib, "import_module", return_value=fake):
                again = builder.topology_result({"codex": {"events": []}, "flujo": {"events": []}}, {}, cache, False)
            for key in ("sessions", "agentEdges", "flows", "events"):
                old = next(item for item in again[key] if item["id"] == prior[key][0]["id"])
                self.assertEqual(old["lastCapturedAt"], prior_time)

    def test_message_only_session_restored_graph_fields_are_marked_as_prior_capture(self):
        prior_time = "2026-10-01T04:00:00Z"
        previous = {"sessions": [{"id": "flujo:w:parent", "label": "Prior label", "flowId": "prior-graph", "flowDefinitionId": "prior-flow", "parentId": "flujo:w:supervisor",
                                  "eventIds": ["previous-record"], "eventCount": 1, "nodeActivity": [], "graphBasis": "Previously observed declared graph"}],
                    "agentEdges": [], "flows": [], "events": [], "notes": [], "stats": {}}
        fallback = {"sessions": [{"id": "flujo:w:parent", "label": "Fresh visible message label", "flowId": None, "flowDefinitionId": None, "parentId": None,
                                  "eventIds": ["fresh-record"], "eventCount": 1, "nodeActivity": [], "graphBasis": "Execution graph unavailable"}],
                    "agentEdges": [], "flows": [], "events": [], "notes": [], "stats": {"flujoReaderUnavailable": 1}}
        fake = SimpleNamespace(derive=lambda repo, results, config: copy.deepcopy(fallback))
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            builder.atomic_json(cache / "topology.json", {"collectedAt": prior_time, "result": previous})
            with patch.object(builder.importlib, "import_module", return_value=fake):
                result = builder.topology_result({"codex": {"events": []}, "flujo": {"events": []}}, {}, cache, False)
            session = result["sessions"][0]
            self.assertEqual(session["flowId"], "prior-graph")
            self.assertEqual(session["flowDefinitionId"], "prior-flow")
            self.assertEqual(session["parentId"], "flujo:w:supervisor")
            self.assertEqual(session["label"], "Fresh visible message label")
            self.assertEqual(set(session["eventIds"]), {"previous-record", "fresh-record"})
            self.assertTrue(session.get("retainedFromPriorCapture"), "Recovered graph/ancestry fields need explicit prior-capture provenance even without nodeActivity")
            self.assertEqual(session.get("lastCapturedAt"), prior_time)

    def test_offline_node_attribution_sorts_mixed_fractional_timestamp_precision_numerically(self):
        topology = {"sessions": [{"id": "flujo:w:parent", "eventIds": ["after", "between"], "flowId": "graph",
                                  "nodeActivity": [{"timestamp": "2026-10-01T00:00:01.123Z", "nodeId": "first"},
                                                   {"timestamp": "2026-10-01T00:00:01.123456Z", "nodeId": "second"}]}],
                    "agentEdges": [], "flows": [], "events": [], "notes": [], "stats": {}}
        results = {"flujo": {"events": [{"id": "after", "timestamp": "2026-10-01T00:00:01.123500Z", "metadata": {}},
                                        {"id": "between", "timestamp": "2026-10-01T00:00:01.123400Z", "metadata": {}}]}}
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            builder.atomic_json(cache / "topology.json", {"collectedAt": "2026-10-01T04:00:00Z", "result": topology})
            builder.topology_result(results, {}, cache, True)
        self.assertEqual(results["flujo"]["events"][0]["metadata"]["nodeId"], "second")
        self.assertEqual(results["flujo"]["events"][1]["metadata"]["nodeId"], "first")

    def test_offline_topology_restores_exact_node_context_and_child_execution_provenance(self):
        source_events = [
            {"id": "before", "source": "flujo", "threadId": "parent", "timestamp": "2026-10-01T00:00:00.500000Z", "metadata": {}},
            {"id": "during", "source": "flujo", "threadId": "parent", "timestamp": "2026-10-01T00:00:02.500000Z", "metadata": {}},
            {"id": "boundary", "source": "flujo", "threadId": "parent", "timestamp": "2026-10-01T00:00:03.000000Z", "metadata": {}},
        ]
        topology = {
            "sessions": [{"id": "flujo:w:parent", "flowId": "parent-graph", "flowDefinitionId": "parent-flow", "eventIds": [e["id"] for e in source_events] + ["child-dispatch"],
                          "nodeActivity": [{"timestamp": "2026-10-01T00:00:01.000000Z", "nodeId": "first", "eventId": "enter-first"},
                                           {"timestamp": "2026-10-01T00:00:03.000000Z", "nodeId": "second", "eventId": "enter-second"}]}],
            "events": [{"id": "child-dispatch", "source": "flujo", "threadId": "parent", "timestamp": "2026-10-01T00:00:02.000000Z",
                        "metadata": {"sessionId": "flujo:w:parent", "executingSessionId": "flujo:w:child", "observedInSessionId": "flujo:w:parent", "flowId": "child-graph", "flowDefinitionId": "child-flow", "nodeId": "builder", "eventType": "model:dispatch", "dispatchId": "turn-id"}}],
            "flows": [], "agentEdges": [], "notes": [], "stats": {},
        }
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            file = cache / "topology.json"
            builder.atomic_json(file, {"collectedAt": "2026-10-01T04:00:00Z", "result": topology})
            results = {"flujo": {"events": copy.deepcopy(source_events)}, "codex": {"events": []}}
            with patch.object(builder.importlib, "import_module", side_effect=AssertionError("Offline topology must not import a live collector")):
                restored = builder.topology_result(results, {}, cache, True)
            index = {event["id"]: event for event in results["flujo"]["events"]}
            self.assertNotIn("nodeId", index["before"]["metadata"])
            self.assertEqual(index["during"]["metadata"]["nodeId"], "first")
            self.assertEqual(index["boundary"]["metadata"]["nodeId"], "second")
            self.assertEqual(index["during"]["metadata"]["sessionId"], "flujo:w:parent")
            self.assertEqual(index["during"]["metadata"]["flowId"], "parent-graph")
            child = index["child-dispatch"]["metadata"]
            self.assertEqual(child["executingSessionId"], "flujo:w:child")
            self.assertEqual(child["observedInSessionId"], "flujo:w:parent")
            self.assertEqual(child["nodeId"], "builder")
            self.assertEqual(child["flowId"], "child-graph")
            self.assertEqual(restored["cachedAt"], "2026-10-01T04:00:00Z")
            saved = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(saved["collectedAt"], "2026-10-01T04:00:00Z")
            scoped_bytes = file.read_bytes()
            with patch.object(builder.importlib, "import_module", side_effect=AssertionError("Offline topology must not import a live collector")):
                builder.topology_result({"flujo": {"events": copy.deepcopy(source_events)}, "codex": {"events": []}}, {}, cache, True)
            self.assertEqual(file.read_bytes(), scoped_bytes)

    def test_browser_index_retains_execution_graph_provenance_and_machine_lifecycle(self):
        provenance = {"sessionId": "flujo:w:parent", "executingSessionId": "flujo:w:child", "observedInSessionId": "flujo:w:parent",
                      "flowId": "child-graph", "flowDefinitionId": "child-flow", "nodeId": "builder", "fromNodeId": "start", "toNodeId": "builder",
                      "dispatchId": "turn-id", "eventType": "model:dispatch", "depth": 1, "basis": "Timestamped execution log"}
        machine = {"machineId": "fly:app:machine", "provider": "fly", "location": "iad", "lifecycle": "stop", "timestampBasis": "fly.machine.events.timestamp", "observedAt": "2026-10-01T04:00:00Z"}
        events = [{"id": "child", "body": "Recorded model turn", "metadata": {**provenance, "originPath": "local-private-rollout", "fullPrompt": "PRIVATE PROMPT"}},
                  {"id": "machine", "body": "Recorded lifecycle", "metadata": machine}]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            builder.write_browser_snapshot(output, {"events": events, "collection": {}})
            index = (output / "history-data.js").read_text(encoding="utf-8")
            encoded = index.split("atob('", 1)[1].split("')", 1)[0]
            browser = json.loads(gzip.decompress(base64.b64decode(encoded)))
            child, observed_machine = browser["events"]
            self.assertEqual(child["metadata"], provenance)
            self.assertEqual(observed_machine["metadata"], machine)
            self.assertNotIn("PRIVATE PROMPT", json.dumps(browser))
            self.assertNotIn("local-private-rollout", json.dumps(browser))

    def test_refresh_preserves_missing_prior_events_and_updates_current_bodies(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory)
            builder.atomic_json(cache / "slack.json", {"collectedAt": "2026-10-01T00:00:00Z", "result": {"events": [{"id": "old", "body": "Previous"}, {"id": "same", "body": "Before edit"}], "status": "ok"}})
            fake = SimpleNamespace(collect=lambda repo, config: {"events": [{"id": "same", "body": "After edit"}], "status": "ok", "notes": []})
            with patch.object(builder.importlib, "import_module", return_value=fake):
                result = builder.source_result("slack", {}, cache, False)
            index = {e["id"]: e for e in result["events"]}
            self.assertEqual(index["same"]["body"], "After edit")
            self.assertTrue(index["old"]["metadata"]["retainedFromPriorCapture"])
            self.assertEqual(result["stats"]["retainedEvents"], 1)

    def test_slack_formatted_channel_and_thread_preserve_multiline_body(self):
        channel = {"id": "C123", "name": "team"}
        records = messages_from({"messages": "Channel: #team\n\n=== Message from Mario <m@example.com> (U1) at 2026-10-01 00:00:00 -05 === \nMessage TS: 1790827200.123456\nFirst line\nSecond line\nThread: 2 replies (latest: today)\n\n=== Message from Gloria (U2) at today ===\nMessage TS: 1790827201.000001\nNext message"}, channel)
        self.assertEqual(len(records), 2)
        self.assertIn("First line\nSecond line", records[0]["body"])
        self.assertEqual(records[0]["replies"], 2)
        thread = messages_from({"messages": "=== THREAD PARENT MESSAGE ===\nFrom: Mario (U1)\nTime: today\nMessage TS: 1790827200.123456\nParent\n\n=== THREAD REPLIES (1 total) ===\n\n--- Reply 1 of 1 ---\nFrom: Gloria (U2)\nTime: today\nMessage TS: 1790827201.000001\nReply\nfull text"}, channel, "1790827200.123456")
        self.assertEqual(thread[0]["body"], "Parent")
        self.assertEqual(thread[1]["body"], "Reply\nfull text")

    def test_slack_pagination_and_channel_user_ids(self):
        self.assertEqual(next_cursor({"pagination_info": "Next cursor: abc=="}), "abc==")
        self.assertEqual(next_cursor({"result": 'Pagination: More results available. Use cursor: "dGVzdA=="'}), "dGVzdA==")
        self.assertIsNone(next_cursor({"pagination_info": "There are no more messages available."}))
        channels = channels_from({"result": "## My Channels\n\n### DM with Gloria\n- **ID:** D1\n- **User ID:** U2\n"})
        self.assertEqual(channels[0]["user"], "U2")

    def test_authoritative_timestamp_and_credentials(self):
        self.assertEqual(timestamp("1790901408.406789"), "2026-10-02T00:36:48.406789Z")
        with self.assertRaises(ValueError):
            timestamp("2026-10-01T12:00:00")
        text = "token ghp_" + "x" * 30 + "\nAWS_SECRET_ACCESS_KEY=some-secret-value-here"
        safe = redact(text)
        self.assertNotIn("some-secret-value-here", safe)
        self.assertNotIn("x" * 30, safe)
        self.assertNotIn("synthetic-secret", redact('{"access_token":"synthetic-secret"}'))
        self.assertEqual(sanitize({"api_key": "synthetic-secret"})["api_key"], "[REDACTED]")

    def test_classification_and_explicit_reference_relation(self):
        event = {"id": "a", "timestamp": "2026-10-01T01:00:00Z", "source": "slack", "title": "MCP review", "body": "Review https://github.com/mario-andreschak/factored-hackathon-2026-mcg/pull/42", "metadata": {"channel": "equipo-mario-gloria"}, "tags": []}
        first = builder.enrich(event)
        second = builder.enrich({**event, "id": "b", "source": "github", "timestamp": "2026-10-01T02:00:00Z"})
        self.assertIn("mcp", first["workstreams"])
        self.assertTrue(first["metadata"]["developmentRelevant"])
        _, links, _ = builder.story([first, second])
        self.assertEqual(links[0]["fromEventId"], "a")
        self.assertIn("not proof of causation", links[0]["basis"])
        linked = builder.enrich({**event, "id": "c", "source": "github", "body": "Minimal PR", "url": "https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/42"})
        self.assertEqual(linked["references"], ["https://github.com/mario-andreschak/factored-hackathon-2026-mcg/issues/42"])
        watchdog = builder.enrich({**event, "id": "d", "source": "flujo", "title": "Check", "body": "OK", "metadata": {"flowName": "Hackathon_Release_Watchdog"}})
        self.assertTrue(watchdog["metadata"]["developmentRelevant"])

    def test_body_shards_preserve_text_and_escape_script_content(self):
        text = "</script>" + "Original message." * 400
        event = {"id": "e1", "body": text, "metadata": {}}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            builder.write_browser_snapshot(output, {"events": [event], "collection": {}})
            index = (output / "history-data.js").read_text(encoding="utf-8")
            encoded = index.split("atob('", 1)[1].split("')", 1)[0]
            data = json.loads(gzip.decompress(base64.b64decode(encoded)))
            item = data["events"][0]
            self.assertTrue(item["metadata"]["bodyTruncated"])
            shard = (output / "bodies" / item["bodyRef"]).read_text(encoding="utf-8")
            self.assertNotIn("</script>", shard)
            self.assertIn("Original message.", shard)
            self.assertEqual(event["body"], text)


if __name__ == "__main__":
    unittest.main()
