"""Cutoff checks for dated evidence and the lifecycle context it supports."""
from copy import deepcopy
import unittest

from scripts.history_sources.scope import apply_history_start, history_start


BEFORE = "2026-09-25T04:59:59.999999Z"
START = "2026-09-25T05:00:00Z"
AFTER = "2026-09-25T05:00:00.000001Z"


def event(identity, time, **extra):
    return {"id": identity, "timestamp": time, "body": "Visible work", **extra}


class HistoryScopeTests(unittest.TestCase):
    def test_bogota_midnight_is_inclusive_and_absolute_dates_are_unchanged(self):
        source = {"events": [event("prior", BEFORE), event("boundary", "2026-09-25T00:00:00-05:00"), event("later", AFTER), event("other-zone", "2026-09-25T06:00:00+01:00")], "stats": {"messages": 4}}
        original = deepcopy(source)
        result = apply_history_start(source)
        self.assertEqual([row["id"] for row in result["events"]], ["boundary", "later", "other-zone"])
        self.assertEqual(result["events"][0]["timestamp"], "2026-09-25T00:00:00-05:00")
        self.assertEqual(history_start(), "2026-09-25T05:00:00.000000Z")
        self.assertEqual(result["scopeExcludedEventIds"], ["prior"])
        self.assertEqual(result["stats"]["messages"], 3)
        self.assertEqual(source, original)
        self.assertEqual(apply_history_start(result), result)

    def test_unavailable_dates_remain_unknown_and_invalid_cutoff_is_rejected(self):
        source = {"events": [{"id": "minimal"}, event("unknown", None), event("naive", "2026-09-20T00:00:00")]}
        self.assertEqual(apply_history_start(source)["events"], source["events"])
        for value in (None, "invalid", "2026-09-25T00:00:00"):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "timezone-aware"):
                history_start({"history_start": value})

    def test_numeric_source_timestamp_and_custom_window(self):
        seconds = 1790312400  # 2026-09-25 05:00 UTC
        source = {"events": [event("before", seconds - 1), event("seconds", seconds), event("milliseconds", seconds * 1000)]}
        result = apply_history_start(source)
        self.assertEqual([row["id"] for row in result["events"]], ["seconds", "milliseconds"])
        custom = apply_history_start({"events": [event("a", START), event("b", AFTER)]}, {"history_start": AFTER})
        self.assertEqual([row["id"] for row in custom["events"]], ["b"])

    def test_moving_window_earlier_allows_freshly_returned_eligible_events(self):
        previous = apply_history_start({"events": [event("prior", BEFORE), event("current", AFTER)]})
        refreshed = {**previous, "events": [event("prior", BEFORE), event("current", AFTER)]}
        earlier = apply_history_start(refreshed, {"history_start": "2026-09-24T00:00:00-05:00"})
        self.assertEqual([row["id"] for row in earlier["events"]], ["prior", "current"])
        self.assertEqual(earlier["scopeExcludedEventIds"], [])
        self.assertEqual(apply_history_start(earlier, {"history_start": "2026-09-24T05:00:00Z"}), earlier)
        # Equivalent offsets identify the same window, retaining exclusions.
        same = apply_history_start({**previous, "historyStart": "2026-09-25T00:00:00-05:00"}, {"history_start": START})
        self.assertEqual(same["scopeExcludedEventIds"], ["prior"])
        # Legacy exclusions have no date provenance and apply only by default.
        legacy = {"events": [event("prior", BEFORE)], "scopeExcludedEventIds": ["prior"]}
        self.assertEqual(apply_history_start(legacy)["events"], [])
        self.assertEqual(apply_history_start(legacy, {"history_start": "2026-09-24T05:00:00Z"})["events"], legacy["events"])

    def test_topology_trims_external_evidence_and_keeps_actual_parent_creation(self):
        source = {
            "events": [event("old-action", BEFORE, metadata={"sessionId": "old"}), event("live-action", AFTER, metadata={"sessionId": "live", "flowId": "live-graph", "evidenceEventIds": ["old-msg", "live-msg"]})],
            "sessions": [
                {"id": "parent", "source": "codex", "startedAt": BEFORE, "lastActivityAt": BEFORE, "eventIds": ["old-parent-msg"], "eventCount": 1, "nodeActivity": [{"timestamp": BEFORE, "nodeId": "a", "eventId": "old-parent-msg"}]},
                {"id": "live", "source": "flujo", "parentId": "parent", "startedAt": BEFORE, "lastActivityAt": AFTER, "flowId": "live-graph", "eventIds": ["old-msg", "live-msg"], "eventCount": 2, "nodeActivity": [{"timestamp": BEFORE, "nodeId": "a", "eventId": "old-msg"}, {"timestamp": AFTER, "nodeId": "b", "eventId": "live-msg"}]},
                {"id": "old", "source": "flujo", "startedAt": BEFORE, "lastActivityAt": BEFORE, "flowId": "old-graph", "eventIds": ["old-msg"], "eventCount": 1},
            ],
            "agentEdges": [{"id": "past-edge", "from": "parent", "to": "old", "timestamp": BEFORE, "eventIds": ["old-action"]}, {"id": "current-edge", "from": "parent", "to": "live", "timestamp": AFTER, "eventIds": ["old-msg", "live-action"], "flowId": "live-graph"}],
            "flows": [{"id": "old-graph", "nodes": [{"id": "a"}], "eventIds": ["old-action"]}, {"id": "live-graph", "availableFrom": BEFORE, "nodes": [{"id": "b"}], "eventIds": ["old-action"]}],
            "stats": {"sessions": 3, "agentEdges": 2, "flowGraphs": 2, "executionEvents": 2, "codexSessions": 1, "flujoSessions": 2},
        }
        original = deepcopy(source)
        config = {"_history_event_timestamps": {"old-msg": BEFORE, "old-parent-msg": BEFORE, "live-msg": AFTER}}
        result = apply_history_start(source, config)
        self.assertEqual([row["id"] for row in result["sessions"]], ["parent", "live"])
        parent, live = result["sessions"]
        self.assertEqual(parent["startedAt"], BEFORE)
        self.assertEqual(parent["eventIds"], [])
        self.assertEqual(parent["nodeActivity"], [])
        self.assertEqual(live["startedAt"], BEFORE)
        self.assertEqual(live["eventIds"], ["live-msg"])
        self.assertEqual(live["eventCount"], 1)
        self.assertEqual(live["nodeActivity"], [{"timestamp": AFTER, "nodeId": "b", "eventId": "live-msg"}])
        self.assertEqual([row["id"] for row in result["agentEdges"]], ["current-edge"])
        self.assertEqual(result["agentEdges"][0]["eventIds"], ["live-action"])
        self.assertEqual([row["id"] for row in result["flows"]], ["live-graph"])
        self.assertEqual(result["flows"][0]["availableFrom"], BEFORE)
        self.assertEqual(result["flows"][0]["eventIds"], [])
        self.assertEqual(result["events"][0]["metadata"]["evidenceEventIds"], ["live-msg"])
        self.assertEqual(result["stats"]["sessions"], 2)
        self.assertEqual(source, original)
        self.assertEqual(apply_history_start(result, config), result)

    def test_ancestor_only_context_is_identified_without_old_execution_rows(self):
        source = {"events": [], "sessions": [{"id": "parent", "startedAt": BEFORE, "eventIds": ["past"]}, {"id": "child", "parentId": "parent", "startedAt": START, "eventIds": []}], "agentEdges": [], "flows": []}
        result = apply_history_start(source, {"_history_excluded_event_ids": ["past"]})
        self.assertTrue(result["sessions"][0]["historyContextOnly"])
        self.assertEqual(result["sessions"][0]["eventIds"], [])
        self.assertNotIn("historyContextOnly", result["sessions"][1])

    def test_unknown_cross_source_refs_are_kept_until_evidence_excludes_them(self):
        source = {"events": [], "sessions": [{"id": "session", "startedAt": BEFORE, "flowId": "graph", "eventIds": ["unavailable-source-message"], "eventCount": 1}], "flows": [{"id": "graph", "availableFrom": BEFORE}], "agentEdges": [{"id": "unknown", "from": "session", "to": "session", "eventIds": ["unavailable-source-message"]}]}
        retained = apply_history_start(source)
        self.assertEqual(len(retained["sessions"]), 1)
        self.assertEqual(len(retained["flows"]), 1)
        removed = apply_history_start(retained, {"_history_excluded_event_ids": ["unavailable-source-message"]})
        self.assertEqual(removed["sessions"], [])
        self.assertEqual(removed["agentEdges"], [])
        self.assertEqual(removed["flows"], [])

    def test_infrastructure_preserves_true_creation_and_spanning_receipts(self):
        source = {
            "events": [event("old", BEFORE), event("current", AFTER)],
            "machines": [{"id": "old-machine", "createdAt": BEFORE, "lastObservedAt": BEFORE, "evidenceEventIds": ["old"]}, {"id": "active-machine", "createdAt": BEFORE, "lastObservedAt": AFTER, "evidenceEventIds": ["old", "current"]}],
            "builds": [{"id": "old-build", "startedAt": BEFORE, "finishedAt": BEFORE, "evidenceEventIds": ["old"]}, {"id": "spanning-build", "startedAt": BEFORE, "finishedAt": AFTER, "evidenceEventIds": ["old", "current"]}],
            "deployments": [{"id": "old-release", "timestamp": BEFORE, "evidenceEventIds": ["old"]}, {"id": "release", "timestamp": AFTER, "evidenceEventIds": ["current"]}],
            "stats": {"machines": 2, "builds": 2, "deployments": 2},
        }
        result = apply_history_start(source)
        self.assertEqual([row["id"] for row in result["machines"]], ["active-machine"])
        self.assertEqual(result["machines"][0]["createdAt"], BEFORE)
        self.assertEqual(result["machines"][0]["evidenceEventIds"], ["current"])
        self.assertEqual([row["id"] for row in result["builds"]], ["spanning-build"])
        self.assertEqual(result["builds"][0]["startedAt"], BEFORE)
        self.assertEqual([row["id"] for row in result["deployments"]], ["release"])
        self.assertEqual(result["stats"]["machines"], 1)
        self.assertEqual(apply_history_start(result), result)

    def test_document_revisions_and_threads_do_not_restore_old_messages(self):
        source = {"events": [event("old-doc", BEFORE), event("new-doc", AFTER), event("chat", AFTER, threadId="child")], "documents": [{"path": "old.md", "revisions": [{"eventId": "old-doc", "timestamp": BEFORE}]}, {"path": "active.md", "firstObservedAt": BEFORE, "revisions": [{"eventId": "old-doc", "timestamp": BEFORE}, {"eventId": "new-doc", "timestamp": AFTER}]}], "threads": [{"id": "unused", "createdAt": BEFORE}, {"id": "parent", "createdAt": BEFORE}, {"id": "child", "createdAt": BEFORE, "parentThreadId": "parent"}], "stats": {"threads": 3}}
        result = apply_history_start(source)
        self.assertEqual([row["path"] for row in result["documents"]], ["active.md"])
        self.assertEqual(result["documents"][0]["firstObservedAt"], BEFORE)
        self.assertEqual(result["documents"][0]["revisions"], [{"eventId": "new-doc", "timestamp": AFTER}])
        self.assertEqual([row["id"] for row in result["threads"]], ["parent", "child"])
        self.assertEqual(result["threads"][0]["createdAt"], BEFORE)
        self.assertEqual(result["stats"]["threads"], 2)


if __name__ == "__main__":
    unittest.main()
